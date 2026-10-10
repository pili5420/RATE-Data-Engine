"""Synthetic ENGINEERING-only acceptance. Never fabricate production warmup evidence."""
import copy
from datetime import date, timedelta
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from src.cer074_acceptance import atomic_write_json, sha256, strip_runtime
from src.full_market_rotation import EXTERNAL_FEED, UNIVERSE, evaluate_rotation, rank_full_market
from src.production_live_state import ARTIFACTS, CADENCE_DIR, MANIFEST_NAME, PERSIST_NAME, STATE_NAME, file_hash
from src.rate_logic import rank_candidates, rank_composites

ROOT = Path(__file__).resolve().parents[1]
BASE = "b1d4376c1e774bf09b16bde619a352cc9d48dcc2"


def fixture_inputs():
    contract = json.loads((ROOT / "config/RATE_FULL_MARKET_ROTATION_CONTRACT_V1.json").read_bytes())
    contract.update(validation_status="PASS", eligibility_policy_id="ENGINEERING_TEST_POLICY",
                    eligibility_policy_sha256="f" * 64)
    days = [(date(2026, 1, 1) + timedelta(days=day)).isoformat() for day in range(180)]
    symbols = [str(1000 + index) for index in range(60)]
    catalogue = {"validation_status": "PASS", "source_status": "PASS", "freshness_status": "PASS",
                 "blocked_dependencies": [], "fallback_used": False, "universe_mode": UNIVERSE,
                 "valid_scope": "NORMAL_PRODUCTION", "trading_date": days[-1], "approved_by": "CONTROL_CENTER",
                 "eligibility_policy_id": contract["eligibility_policy_id"],
                 "eligibility_policy_sha256": contract["eligibility_policy_sha256"], "markets": []}
    inputs = {"artifact": "RATE_FULL_MARKET_EOD_INPUTS", "evidence_scope": "ENGINEERING_FIXTURE_ONLY",
              "validation_status": "PASS", "source_status": "PASS", "freshness_status": "PASS",
              "blocked_dependencies": [], "fallback_used": False, "trading_date": days[-1], "cadence": "19:30",
              "production_snapshot_id": "ENGINEERING_CURRENT_SNAPSHOT_NOT_PREVIOUS_STATE",
              "input_snapshot_id": "ENGINEERING_INPUT_SNAPSHOT_NOT_PRODUCTION_SNAPSHOT",
              "stock_histories": {}, "benchmark_by_symbol": {}, "institutional_histories": {},
              "tdcc_histories": {}, "fundamental_records": []}
    for market in ("TWSE", "TPEX"):
        rows = [{"symbol": symbol, "eligible": True, "eligibility_reason": "ENGINEERING_TEST_ONLY"}
                for index, symbol in enumerate(symbols) if (index % 2 == 0) == (market == "TWSE")]
        catalogue["markets"].append({"market": market, "authority": market, "complete": True,
                                     "validation_status": "PASS", "record_count": len(rows),
                                     "records": rows, "records_sha256": sha256(rows)})
    for index, symbol in enumerate(symbols):
        source = "TWSE" if index % 2 == 0 else "TPEX"
        slope = -.1 + .001 * index if index < 30 else .08 + .006 * index
        history = []
        for offset, day in enumerate(days):
            close = 100 + slope * offset + (.15 if offset % 2 == 0 else -.15)
            volume = 10000 + index * 25 + offset * (index + 1)
            history.append({"symbol": symbol, "trade_date": day, "open": close, "high": close + .5,
                            "low": close - .5, "close": close, "volume": volume, "turnover": close * volume,
                            "source": source, "source_timestamp": day + "T10:00:00Z"})
        inputs["stock_histories"][symbol] = history
        inputs["benchmark_by_symbol"][symbol] = [{"trade_date": day, "close": 100 + offset * .01,
            "benchmark_symbol": "TAIEX" if source == "TWSE" else "TPEX", "source": source,
            "source_timestamp": day + "T10:00:00Z"} for offset, day in enumerate(days)]
        net_shares = -5000 + index if 30 <= index < 36 else index + 1
        inputs["institutional_histories"][symbol] = [{"trade_date": day, "foreign_net_shares": net_shares,
            "investment_trust_net_shares": net_shares, "close": history[offset]["close"],
            "turnover": history[offset]["turnover"], "source": source, "source_timestamp": day + "T10:00:00Z"}
            for offset, day in enumerate(days)]
        inputs["tdcc_histories"][symbol] = [{"period_end": days[offset], "holder_pct_400": 20 + index * .4,
            "source": "TDCC", "source_timestamp": days[offset] + "T10:00:00Z"} for offset in range(0, 170, 7)]
        inputs["fundamental_records"].append({"symbol": symbol, "revenue_yoy": [index, index + 1, index + 2],
            "quarterly_eps": [index + 1] * 4 + [1] * 4, "source": "MOPS", "source_timestamp": days[-1] + "T10:00:00Z",
            "as_of_date": days[-1]})
    inputs.update(catalogue_sha256=sha256(catalogue), contract_sha256=sha256(contract))
    return contract, catalogue, inputs


def install_canonical_fixture(root, day, cadence, *, full_market=False):
    previous_rows = [{"symbol": str(1000 + index), "Stage_output": {"stage_current": "CONSOLIDATION"}} for index in range(60 if full_market else 30)]
    decision = {"trading_date": day, "cadence": cadence, "execution_scope": "PRODUCTION",
                "previous_state_resolution": "PERSISTED_PRODUCTION_STATE", "previous_state_id": "TEST_PREDECESSOR",
                "previous_state_hash": "a" * 64, "records": previous_rows,
                "short_top30": previous_rows[:30], "long_top30": previous_rows[:30], "top50": previous_rows[:50],
                "roy_portfolio": {"positions": [], "cash": 123}, "ai_paper_portfolio": {"positions": [], "cash": 456},
                "transaction_ledger": {"transactions": [{"id": "TEST_TXN"}]}}
    if full_market:
        decision.update(candidate_universe_source=UNIVERSE, ranking_refresh_source="FULL_MARKET_SCAN")
    digest = sha256(strip_runtime(decision))
    current = "rate-state-" + digest[:24]
    entry = {key: decision[key] for key in ("trading_date", "cadence", "execution_scope", "previous_state_resolution", "previous_state_id")}
    entry.update(current_state_id=current, decision_payload_hash=digest)
    persist = {"artifact": ARTIFACTS[cadence], "validation_status": "PASS", "current_state_id": current,
               "current_state_hash": digest, "previous_state_id": "TEST_PREDECESSOR",
               "persist_result": {"status": "PERSISTED", "state_entry": entry}}
    state = {"current_state_id": current, "decision_payload_hash": digest, "previous_state_id": "TEST_PREDECESSOR", "decision": decision}
    directory = root / "live" / day / CADENCE_DIR[cadence]
    atomic_write_json(directory / PERSIST_NAME, persist)
    atomic_write_json(directory / STATE_NAME, {"state_entry": entry, "decision_state": state})
    atomic_write_json(directory / MANIFEST_NAME, {"artifact": "RATE_PRODUCTION_STATE_MANIFEST", "validation_status": "PASS",
        "trading_date": day, "cadence": cadence, "event_name": "schedule", "ref": "refs/heads/main",
        "workflow_run_id": "100", "workflow_job_id": "200", "commit_sha": "b" * 40,
        "current_state_id": current, "current_state_hash": digest,
        "files": {name: file_hash(directory / name) for name in (PERSIST_NAME, STATE_NAME)}})
    return directory


class FullMarketRotationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract, cls.catalogue, cls.inputs = fixture_inputs()
        cls.day = cls.inputs["trading_date"]
        cls.previous_day = (date.fromisoformat(cls.day) - timedelta(days=1)).isoformat()
        cls.temp = tempfile.TemporaryDirectory(prefix="rate-phase2-test-")
        cls.addClassCleanup(cls.temp.cleanup)
        cls.state_root = Path(cls.temp.name) / "state"
        install_canonical_fixture(cls.state_root, cls.previous_day, "19:30")
        cls.positive = cls.evaluate()

    @classmethod
    def evaluate(cls, **overrides):
        args = dict(state_root=cls.state_root, previous_trading_date=cls.previous_day, previous_cadence="19:30",
                    trading_date=cls.day, cadence="19:30", contract=cls.contract, catalogue=cls.catalogue,
                    inputs=cls.inputs, verification_only=True)
        args.update(overrides)
        return evaluate_rotation(**args)

    def test_full_market_scan_regenerates_60_inputs_and_50_30_30(self):
        result = self.positive
        self.assertEqual(result["validation_status"], "PASS", result.get("blocking_reason"))
        self.assertEqual(result["candidate_universe_count"], 60)
        self.assertEqual(len(result["outside_previous_top30"]), 30)
        self.assertEqual(len(result["ranking"]["records"]), 60)
        self.assertEqual([len(result["ranking"][key]) for key in ("top50", "short_top30", "long_top30")], [50, 30, 30])
        self.assertFalse(result["production_publication_allowed"])
        self.assertFalse(result["production_authoritative"])

    def test_actual_full_market_entry_and_exit_from_previous_top30(self):
        previous = {str(1000 + index) for index in range(30)}
        short = {row["symbol"] for row in self.positive["ranking"]["short_top30"]}
        self.assertTrue(short - previous)
        self.assertTrue(previous - short)

    def test_current_input_production_and_previous_state_lineage_are_separate(self):
        result = self.positive
        self.assertEqual(result["production_snapshot_id"], self.inputs["production_snapshot_id"])
        self.assertEqual(result["input_snapshot_id"], self.inputs["input_snapshot_id"])
        self.assertNotEqual(result["production_snapshot_id"], result["input_snapshot_id"])
        for row in result["ranking"]["records"]:
            self.assertEqual(row["Stage_output"]["input_snapshot_id"], self.inputs["input_snapshot_id"])
            self.assertEqual(row["Stage_output"]["source_state_id"], result["previous_state_id"])
        for key, reason in (("production_snapshot_id", "MISSING_PRODUCTION_SNAPSHOT_ID"),
                            ("input_snapshot_id", "MISSING_INPUT_SNAPSHOT_ID")):
            inputs = {k: v for k, v in self.inputs.items() if k != key}
            self.assertEqual(self.evaluate(inputs=inputs)["blocking_reason"], reason)

    def test_frozen_rank_formulas_ties_and_selection_scope_exactly_preserved(self):
        ranking = self.positive["ranking"]
        for row in ranking["records"]:
            self.assertEqual({key: row[key] for key in rank_composites(row)}, rank_composites(row))
        for key, score, count in (("top50", "rate_composite_score", 50), ("short_top30", "short_score", 30), ("long_top30", "long_score", 30)):
            self.assertEqual(ranking[key], rank_candidates(ranking["records"], score, count))
        ties = [{"symbol": str(index), **{key: 50 for key in ("M7", "MHE", "Stage", "Rotation", "SmartMoney", "Fundamental", "RelativeStrength", "Liquidity")}} for index in range(60)]
        forward, reverse = rank_full_market(ties), rank_full_market(list(reversed(ties)))
        for key in ("top50", "short_top30", "long_top30"):
            self.assertEqual(forward[key], reverse[key])

    def test_previous_top30_only_normal_universe_rejected(self):
        catalogue = copy.deepcopy(self.catalogue)
        for market in catalogue["markets"]:
            market["records"] = [row for row in market["records"] if int(row["symbol"]) < 1030]
            market.update(record_count=len(market["records"]), records_sha256=sha256(market["records"]))
        result = self.evaluate(catalogue=catalogue)
        self.assertEqual(result["blocking_reason"], "PREVIOUS_TOP30_ONLY_UNIVERSE_FORBIDDEN")
        self.assertIsNone(result["ranking"])

    def test_bootstrap_seed_and_stale_catalogue_not_normal_authority(self):
        for changes, reason in (({"universe_mode": "CONTROL_CENTER_REBASELINE_BOOTSTRAP_SEED"}, "BOOTSTRAP_UNIVERSE_NOT_NORMAL_PRODUCTION"),
                                ({"trading_date": self.previous_day}, "FULL_MARKET_CATALOGUE_DATE_MISMATCH"),
                                ({"freshness_status": "STALE"}, "FULL_MARKET_CATALOGUE_NOT_PASS")):
            with self.subTest(changes=changes):
                result = self.evaluate(catalogue={**self.catalogue, **changes})
                self.assertEqual(result["blocking_reason"], reason)

    def test_policy_must_be_authorized_not_invented(self):
        draft = json.loads((ROOT / "config/RATE_FULL_MARKET_ROTATION_CONTRACT_V1.json").read_bytes())
        draft["validation_status"] = "BLOCKED"
        self.assertEqual(self.evaluate(contract=draft)["blocking_reason"], "ELIGIBILITY_POLICY_AUTHORIZATION_REQUIRED")

    def test_missing_input_preserves_previous_and_produces_no_ranking(self):
        inputs = copy.deepcopy(self.inputs)
        del inputs["stock_histories"]["1059"]
        before = {str(p): p.read_bytes() for p in self.state_root.rglob("*.json")}
        result = self.evaluate(inputs=inputs)
        self.assertEqual(result["blocking_reason"], "FULL_MARKET_INPUTS_INCOMPLETE")
        self.assertIsNone(result["ranking"])
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.state_root.rglob("*.json")})

    def test_short_official_history_requires_warmup_no_fabrication(self):
        inputs = copy.deepcopy(self.inputs)
        inputs["stock_histories"]["1059"] = inputs["stock_histories"]["1059"][1:]
        self.assertEqual(self.evaluate(inputs=inputs)["blocking_reason"], "HISTORICAL_WARMUP_REQUIRED")

    def test_official_zero_volume_is_not_a_universe_filter(self):
        inputs = copy.deepcopy(self.inputs)
        inputs["stock_histories"]["1059"][0].update(volume=0, turnover=0)
        result = self.evaluate(inputs=inputs)
        self.assertEqual(result["validation_status"], "PASS", result.get("blocking_reason"))
        self.assertEqual(result["candidate_universe_count"], 60)

    def test_nonofficial_synthetic_and_wrong_benchmark_history_rejected(self):
        for group, changes, reason in (("stock_histories", {"source": "THIRD_PARTY"}, "OFFICIAL_HISTORY_REQUIRED"),
                                       ("stock_histories", {"synthetic": True}, "OFFICIAL_HISTORY_REQUIRED"),
                                       ("benchmark_by_symbol", {"benchmark_symbol": "TAIEX"}, "BENCHMARK_MARKET_BINDING_INVALID")):
            with self.subTest(changes=changes):
                inputs = copy.deepcopy(self.inputs)
                inputs[group]["1059"][-1].update(changes)
                self.assertEqual(self.evaluate(inputs=inputs)["blocking_reason"], reason)

    def test_incomplete_catalogue_and_duplicate_symbols_fail_closed(self):
        missing = {**self.catalogue, "markets": self.catalogue["markets"][:1]}
        self.assertEqual(self.evaluate(catalogue=missing)["blocking_reason"], "FULL_MARKET_CATALOGUE_INCOMPLETE")
        duplicate = copy.deepcopy(self.catalogue)
        duplicate["markets"][1]["records"][0]["symbol"] = "1000"
        duplicate["markets"][1]["records_sha256"] = sha256(duplicate["markets"][1]["records"])
        self.assertEqual(self.evaluate(catalogue=duplicate)["blocking_reason"], "FULL_MARKET_CATALOGUE_DUPLICATE_OR_INVALID")

    def test_no_forced_turnover_when_rankings_stay_unchanged(self):
        rows = self.positive["ranking"]["records"]
        one = rank_full_market(rows)
        two = rank_full_market(copy.deepcopy(rows))
        self.assertEqual(one["short_top30"], two["short_top30"])

    def test_0730_consumes_latest_canonical_1930_without_rescan(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            install_canonical_fixture(root, self.previous_day, "19:30", full_market=True)
            with patch("src.full_market_rotation.derive_full_market_inputs", side_effect=AssertionError("RESCAN_FORBIDDEN")):
                result = self.evaluate(state_root=root, cadence="07:30", inputs=None, catalogue=None)
            self.assertEqual(result["validation_status"], "PASS", result)
            self.assertFalse(result["full_market_refresh"])
            install_canonical_fixture(root, self.day, "19:30", full_market=True)
            next_day = (date.fromisoformat(self.day) + timedelta(days=1)).isoformat()
            result = self.evaluate(state_root=root, cadence="07:30", trading_date=next_day)
            self.assertEqual(result["blocking_reason"], "LATEST_PASS_1930_STATE_REQUIRED")

    def test_intraday_missing_feed_remains_blocked_no_rescan(self):
        for cadence in ("09:30", "12:00"):
            result = self.evaluate(cadence=cadence)
            self.assertEqual(result["blocked_dependencies"], [EXTERNAL_FEED])
            self.assertEqual(result["validation_status"], "FAIL_CLOSED")

    def test_authorized_intraday_is_incremental_only_and_no_full_scan(self):
        for cadence, previous_cadence in (("09:30", "07:30"), ("12:00", "09:30")):
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                install_canonical_fixture(root, self.day, previous_cadence, full_market=True)
                feed = {"authorization_status": "PASS", "validation_status": "PASS", "source_status": "PASS",
                        "freshness_status": "PASS", "blocked_dependencies": [], "fallback_used": False,
                        "source_authority": "AUTHORIZED_TWSE_INTRADAY_FEED", "trading_date": self.day, "cadence": cadence}
                with patch("src.full_market_rotation.derive_full_market_inputs", side_effect=AssertionError("RESCAN_FORBIDDEN")):
                    result = self.evaluate(state_root=root, previous_trading_date=self.day, previous_cadence=previous_cadence,
                                           cadence=cadence, intraday_feed=feed)
                self.assertEqual(result["validation_status"], "PASS", result)
                self.assertEqual(result["mode"], "AUTHORIZED_INCREMENTAL_ONLY")

    def test_engineering_inputs_cannot_claim_production_authority(self):
        result = self.evaluate(verification_only=False)
        self.assertEqual(result["blocking_reason"], "ENGINEERING_INPUTS_NOT_PRODUCTION")

    def test_explicit_fallback_and_non_pass_inputs_rejected(self):
        for changes in ({"fallback_used": True}, {"validation_status": "BLOCKED"},
                        {"freshness_status": "STALE"}, {"source_status": "FAIL"}):
            with self.subTest(changes=changes):
                result = self.evaluate(inputs={**self.inputs, **changes})
                self.assertEqual(result["validation_status"], "FAIL_CLOSED")
                self.assertIsNone(result["ranking"])
                self.assertFalse(result["state_mutation_allowed"])
                self.assertFalse(result["portfolio_mutation_allowed"])
                self.assertFalse(result["ledger_mutation_allowed"])

    def test_cli_cannot_write_to_live_or_production_namespaces(self):
        for output in (ROOT / "artifacts/production_state/RATE_PHASE2_FULL_MARKET_ROTATION_REVIEW.json",
                       ROOT / "RATE_PRODUCTION_STATE_LATEST.json"):
            completed = subprocess.run([sys.executable, "-B", str(ROOT / "scripts/run_full_market_rotation.py"),
                                       "--previous-trading-date", "2026-10-02", "--previous-cadence", "19:30",
                                       "--trading-date", "2026-10-05", "--cadence", "19:30", "--output", str(output)],
                                      capture_output=True, text=True)
            self.assertEqual(completed.returncode, 2)
            self.assertIn("FORBIDDEN" if output.parent.name == "production_state" else "FILENAME_REQUIRED",
                          completed.stderr)

    def test_canonical_tamper_and_missing_slot_rejected(self):
        self.assertEqual(self.evaluate(previous_trading_date="2026-01-01")["validation_status"], "FAIL_CLOSED")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            slot = install_canonical_fixture(root, self.previous_day, "19:30")
            (slot / STATE_NAME).write_bytes(b"{}")
            self.assertEqual(self.evaluate(state_root=root)["blocking_reason"], "LIVE_STATE_FILE_HASH_MISMATCH")

    def test_real_rebaseline_has_no_short_top30_and_cannot_be_silently_promoted(self):
        result = self.evaluate(state_root=ROOT / "artifacts/production_state", previous_trading_date="2026-10-02",
                               previous_cadence="19:30", trading_date="2026-10-05")
        self.assertEqual(result["previous_state_id"], "rate-state-baa7113253efcaf5d448e431")
        self.assertEqual(result["previous_state_hash"], "baa7113253efcaf5d448e4319318e070da6f6a680d55303e209cd3d64d2d7fec")
        self.assertEqual(result["blocking_reason"], "PREVIOUS_DECISION_SHORT_TOP30_MISSING")
        self.assertIsNone(result["ranking"])

    def test_frozen_owners_state_accounts_authorization_and_bootstrap_unchanged(self):
        names = subprocess.check_output(["git", "-C", str(ROOT), "ls-tree", "-r", "--name-only", BASE]).decode().splitlines()
        integration = {"scripts/build_production_source_bundle_from_official.py", "scripts/resolve_production_runtime_context.py",
                       "scripts/publish_production_state_latest.py", "scripts/publish_production_source_bundle_latest.py"}
        integration.update(f".github/workflows/rate_production_{slot}_scheduler.yml" for slot in ("0730", "0930", "1200", "1930"))
        integration.add(".github/workflows/rate_public_official_partial_valid_ci.yml")
        for name in names:
            if name in integration:
                continue
            self.assertEqual((ROOT / name).read_bytes(), subprocess.check_output(["git", "-C", str(ROOT), "show", f"{BASE}:{name}"]), name)
        expected = os.getenv("RATE_PHASE2_CI_HEAD_SHA")
        if expected:
            self.assertEqual(subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"]).decode().strip(), expected)


if __name__ == "__main__":
    unittest.main()
