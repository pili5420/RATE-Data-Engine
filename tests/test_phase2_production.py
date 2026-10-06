"""Engineering fixtures in temporary namespaces, not production acceptance data."""
import copy
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts.build_phase2_production_source import build_phase2_bundle
from scripts.publish_production_state_latest import publish_state
from scripts.publish_production_source_bundle_latest import publish_latest, validate_production_source_bundle
from src.cer074_acceptance import atomic_write_json, sha256
from src.full_market_catalogue import (build_catalogue, parse_classification, validate_catalogue,
    CLASSIFICATION_ENDPOINTS, LISTING_ENDPOINTS, policy_hash)
from src.full_market_rotation import EXTERNAL_FEED, evaluate_rotation
from src.phase2_production import (bind_input_material, bundle_from_material, contract, evaluate_material,
    latest_predecessor, persist_prepared_state, prepare_bundle_state, validate_first_refresh, validate_transition)
from src.production_live_state import load_live_state, CADENCE_DIR, STATE_NAME
from tests.test_full_market_rotation import fixture_inputs, ROOT, BASE

AUTHORITY = {"run_id": "100", "commit_sha": "b" * 40, "event": "schedule", "ref": "refs/heads/main"}
FIXTURE_RETRIEVAL = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def fake_catalogue(day, symbols=None):
    symbols = symbols or [str(1000 + i) for i in range(60)]
    header = ["Security Code & Security Name", "ISIN Code", "Date Listed", "Market", "Industrial Group", "CFICode", "Remarks"]
    def fetch(endpoint, html=False):
        market = next(m for m in ("TWSE", "TPEX") if endpoint in (CLASSIFICATION_ENDPOINTS[m], LISTING_ENDPOINTS[m]))
        own = [s for i, s in enumerate(symbols) if (i % 2 == 0) == (market == "TWSE")]
        if html:
            rows = [header, ["Stocks"]] + [[s + " Fixture", "TESTISIN" + s, "2000/01/01",
                "TWSE LISTED" if market == "TWSE" else "TPEx LISTED", "", "ESVUFR", ""] for s in own]
            body = ("Date Stock Updated:" + day.replace("-", "/") + "<table>" + "".join(
                "<tr>" + "".join("<td>" + cell.replace("&", "&amp;") + "</td>" for cell in row) + "</tr>" for row in rows) + "</table>").encode("big5")
        else:
            key = "\u516c\u53f8\u4ee3\u865f" if market == "TWSE" else "SecuritiesCompanyCode"
            body = json.dumps([{key: s} for s in own]).encode()
        return body, {"endpoint": endpoint, "http_status": 200, "content_type": "text/html" if html else "application/json",
            "body_sha256": hashlib.sha256(body).hexdigest(), "response_bytes": len(body),
            "retrieved_at": day + "T10:00:00Z", "fallback_used": False}
    return build_catalogue(day, fetcher=fetch)


def raw_fixture(day):
    _, _, raw = fixture_inputs()
    delta = date.fromisoformat(day) - date.fromisoformat(raw["trading_date"])
    def shift(value):
        if isinstance(value, dict):
            return {k: shift(v) for k, v in value.items()}
        if isinstance(value, list):
            return [shift(v) for v in value]
        if isinstance(value, str) and len(value) >= 10:
            try:
                return (date.fromisoformat(value[:10]) + delta).isoformat() + value[10:]
            except ValueError:
                pass
        return value
    result = shift(raw)
    result["normalized_source_receipts"] = [{"domain": domain, "source": source, "normalization_status": "PASS",
        "retrieval_timestamp": FIXTURE_RETRIEVAL} for domain, source in
        [(d, m) for d in ("market_daily", "benchmark", "institutional", "trading_metadata") for m in ("TWSE", "TPEX")]
        + [("large_holder", "TDCC"), ("fundamental", "MOPS")]]
    return result


class Phase2ProductionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="rate-phase2-integration-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.artifacts = self.root / "artifacts"
        self.state_root = self.artifacts / "production_state"
        shutil.copytree(ROOT / "artifacts/production_state", self.state_root)
        shutil.copyfile(ROOT / "artifacts/RATE_PRODUCTION_STATE_LATEST.json", self.artifacts / "RATE_PRODUCTION_STATE_LATEST.json")
        self.previous = load_live_state(self.state_root, "2026-10-02", "19:30")["state"]
        self.day = "2026-10-05"
        self.catalogue = fake_catalogue(self.day)
        self.material = bind_input_material(raw_fixture(self.day), self.catalogue, self.previous,
            trading_date=self.day, cadence="19:30", authority=AUTHORITY)

    def snapshot(self):
        return {str(p.relative_to(self.artifacts)): p.read_bytes() for p in self.artifacts.rglob("*.json")}

    def bundle(self):
        return bundle_from_material(self.material, self.catalogue, self.state_root)

    def publish(self, bundle):
        path = self.root / "source.json"
        atomic_write_json(path, bundle)
        state = prepare_bundle_state(bundle, state_root=self.state_root)
        persist = persist_prepared_state(state, self.root / "runtime", bundle["cadence"])
        persist_path = self.root / "persist.json"
        atomic_write_json(persist_path, persist)
        with patch.dict(os.environ, {"GITHUB_SHA": AUTHORITY["commit_sha"], "GITHUB_EVENT_NAME": "schedule"}):
            source = publish_latest(source_bundle_path=path, trading_date=bundle["trading_date"], cadence=bundle["cadence"],
                artifacts_root=self.artifacts, workflow_run_id="100", workflow_job_id="200")
        self.assertEqual(source.get("publish_result"), "PASS", source)
        out = publish_state(persist_evidence_path=persist_path, trading_date=bundle["trading_date"], cadence=bundle["cadence"],
            artifacts_root=self.artifacts, state_root=self.root / "runtime", workflow_run_id="100", workflow_job_id="200",
            event_name="schedule", ref="refs/heads/main", commit_sha=AUTHORITY["commit_sha"], phase2=True, source_bundle_path=path)
        self.assertEqual(out["validation_status"], "PASS", out)
        return load_live_state(self.state_root, bundle["trading_date"], bundle["cadence"])["state"], source

    def test_first_exact_rankless_predecessor_canonical_publication(self):
        result, previous = evaluate_material(self.material, self.catalogue, self.state_root)
        self.assertEqual(result["ranking_turnover_status"], "NOT_APPLICABLE_FIRST_FULL_MARKET_REFRESH")
        self.assertIsNone(result["short_term_entries"])
        self.assertIsNone(result["short_term_exits"])
        before = self.snapshot()
        state, source = self.publish(self.bundle())
        self.assertEqual([len(state["decision"][k]) for k in ("top50", "short_top30", "long_top30")], [50, 30, 30])
        self.assertEqual(state["decision"]["previous_state_id"], previous["current_state_id"])
        self.assertTrue(state["decision"]["first_full_market_refresh_authority"]["consumed"])
        self.assertTrue(state["decision"]["first_full_market_refresh_authority"]["completed"])
        for key in ("roy_portfolio", "ai_paper_portfolio"):
            self.assertEqual(state["decision"][key], self.previous["decision"][key])
        self.assertEqual({k: v for k, v in state["decision"]["transaction_ledger"].items() if k != "transactions"},
                         self.previous["decision"]["transaction_ledger"])
        self.assertEqual(state["decision"]["transaction_ledger"]["transactions"], [])
        for path, body in before.items():
            if "LATEST" not in path:
                self.assertEqual((self.artifacts / path).read_bytes(), body)
        self.assertEqual(len(source["delivery_targets"]), 5)
        self.assertEqual(source["manifest_validation"]["validation_status"], "PASS")

    def test_first_authority_reuse_fail_closed(self):
        self.publish(self.bundle())
        with self.assertRaisesRegex(RuntimeError, "FIRST_FULL_MARKET_REFRESH_AUTHORITY_ALREADY_CONSUMED"):
            validate_first_refresh(self.previous, self.state_root, "2026-10-06", "19:30")

    def test_wrong_first_predecessor_id_and_hash_rejected(self):
        for key in ("current_state_id", "decision_payload_hash"):
            previous = {**self.previous, key: "WRONG"}
            with self.subTest(key=key), self.assertRaisesRegex(RuntimeError, "FIRST_REFRESH_PREDECESSOR_BINDING_INVALID"):
                validate_first_refresh(previous, self.state_root, self.day, "19:30")

    def test_second_1930_uses_canonical_ranked_continuity(self):
        previous, _ = self.publish(self.bundle())
        catalogue = fake_catalogue("2026-10-06")
        raw = raw_fixture("2026-10-06")
        material = bind_input_material(raw, catalogue, previous, trading_date="2026-10-06", cadence="19:30", authority=AUTHORITY)
        result, _ = evaluate_material(material, catalogue, self.state_root)
        self.assertEqual(result["continuity_baseline_source"], "PREVIOUS_VALIDATION_PASS_DECISION_STATE_SHORT_TERM_TOP30")
        next_state, _ = self.publish(bundle_from_material(material, catalogue, self.state_root))
        self.assertEqual(next_state["decision"]["previous_state_id"], previous["current_state_id"])
        self.assertEqual(next_state["decision"]["transaction_ledger"], previous["decision"]["transaction_ledger"])
        self.assertEqual(next_state["decision"]["first_full_market_refresh_authority"], previous["decision"]["first_full_market_refresh_authority"])

    def test_0730_carries_ranking_without_scan(self):
        previous, _ = self.publish(self.bundle())
        raw = {"carried_state_id": previous["current_state_id"], "carried_state_hash": previous["decision_payload_hash"], "intraday_feed": None}
        material = bind_input_material(raw, self.catalogue, previous, trading_date="2026-10-06", cadence="07:30", authority=AUTHORITY)
        with patch("src.full_market_rotation.derive_full_market_inputs", side_effect=AssertionError("RESCAN")):
            state, _ = self.publish(bundle_from_material(material, self.catalogue, self.state_root))
        for key in ("records", "top50", "short_top30", "long_top30", "roy_portfolio", "ai_paper_portfolio", "transaction_ledger"):
            self.assertEqual(state["decision"][key], previous["decision"][key])

    def test_missing_eligible_inputs_and_history_preserve_canonical_state(self):
        before = self.snapshot()
        for group in ("stock_histories", "benchmark_by_symbol", "institutional_histories", "tdcc_histories"):
            raw = raw_fixture(self.day)
            del raw[group]["1059"]
            material = bind_input_material(raw, self.catalogue, self.previous, trading_date=self.day, cadence="19:30", authority=AUTHORITY)
            with self.subTest(group=group), self.assertRaisesRegex(RuntimeError, "FULL_MARKET_INPUTS_INCOMPLETE"):
                evaluate_material(material, self.catalogue, self.state_root)
        raw = raw_fixture(self.day)
        raw["stock_histories"]["1059"] = raw["stock_histories"]["1059"][1:]
        material = bind_input_material(raw, self.catalogue, self.previous, trading_date=self.day, cadence="19:30", authority=AUTHORITY)
        with self.assertRaisesRegex(RuntimeError, "HISTORICAL_WARMUP_REQUIRED"):
            evaluate_material(material, self.catalogue, self.state_root)
        self.assertEqual(self.snapshot(), before)

    def test_portfolio_and_ledger_tamper_rejected_before_live_write(self):
        bundle = self.bundle()
        state = prepare_bundle_state(bundle, state_root=self.state_root)
        before = self.snapshot()
        for key in ("roy_portfolio", "ai_paper_portfolio", "transaction_ledger"):
            altered = copy.deepcopy(state)
            altered["decision"][key]["injected"] = True
            with self.subTest(key=key), self.assertRaisesRegex(RuntimeError, "CONTINUITY_FAILED"):
                validate_transition(self.previous, altered, state_root=self.state_root, trading_date=self.day, cadence="19:30")
        self.assertEqual(self.snapshot(), before)

    def test_missing_intraday_feed_never_calls_full_market_materializer(self):
        with patch("scripts.build_phase2_production_source.main_authority", return_value=AUTHORITY), \
             patch("scripts.build_phase2_production_source.materialize_full_market", side_effect=AssertionError("INTRADAY_RESCAN")), \
             patch.dict(os.environ, {"RATE_AUTHORIZED_INTRADAY_FEED_PATH": ""}):
            for cadence in ("09:30", "12:00"):
                before = self.snapshot()
                result = build_phase2_bundle(trading_date=self.day, cadence=cadence, output=self.root / "blocked.json",
                    evidence_output=self.root / "evidence.json", state_root=self.state_root, history_root=self.root / "history")
                self.assertEqual(result["validation_status"], "FAIL_CLOSED")
                self.assertEqual(result["blocked_dependencies"], [EXTERNAL_FEED])
                self.assertIsNone(result["ranking"])
                self.assertEqual(self.snapshot(), before)
                self.assertFalse((self.root / "blocked.json").exists())

    def test_file_cannot_override_unresolved_external_intraday_policy(self):
        feed_path = self.root / "declared_feed.json"
        atomic_write_json(feed_path, {"authorization_status": "PASS", "validation_status": "PASS"})
        with patch("scripts.build_phase2_production_source.main_authority", return_value=AUTHORITY), \
             patch.dict(os.environ, {"RATE_AUTHORIZED_INTRADAY_FEED_PATH": str(feed_path)}), \
             patch("scripts.build_phase2_production_source.materialize_full_market", side_effect=AssertionError("RESCAN")):
            result = build_phase2_bundle(trading_date=self.day, cadence="09:30", output=self.root / "blocked.json",
                evidence_output=self.root / "evidence.json", state_root=self.state_root, history_root=self.root / "history")
        self.assertEqual(result["blocked_dependencies"], [EXTERNAL_FEED])
        self.assertFalse((self.root / "blocked.json").exists())

    def test_duplicate_full_market_publication_leaves_state_latest_untouched(self):
        from scripts.publish_production_source_bundle_latest import build_delivery_targets
        bundle = self.bundle()
        path = self.root / "source.json"
        atomic_write_json(path, bundle)
        before = self.snapshot()
        def duplicate(**kwargs):
            targets = build_delivery_targets(**kwargs)
            targets[2]["path"] = targets[1]["path"]
            return targets
        with patch("scripts.publish_production_source_bundle_latest.build_delivery_targets", side_effect=duplicate):
            result = publish_latest(source_bundle_path=path, trading_date=self.day, cadence="19:30",
                artifacts_root=self.artifacts, workflow_run_id="100", workflow_job_id="200")
        self.assertNotEqual(result.get("publish_result"), "PASS")
        self.assertEqual(result["blocking_reason"], "DUPLICATE_DELIVERY_TARGET")
        self.assertEqual(self.snapshot(), before)

    def test_main_guard_rejects_pr_without_acquisition(self):
        with patch.dict(os.environ, {"GITHUB_REF": "refs/pull/24/head"}), \
             patch("scripts.build_phase2_production_source.materialize_full_market", side_effect=AssertionError("ACQUISITION")):
            result = build_phase2_bundle(trading_date=self.day, cadence="19:30", output=self.root / "blocked.json",
                evidence_output=self.root / "evidence.json", state_root=self.state_root, history_root=self.root / "history")
        self.assertEqual(result["blocking_reason"], "PHASE2_MAIN_AUTHORITY_REQUIRED")
        self.assertFalse((self.root / "blocked.json").exists())

    def test_source_material_tamper_and_seed_coverage_fail_closed(self):
        bundle = self.bundle()
        tampered = copy.deepcopy(bundle)
        tampered["input_material"]["stock_histories"]["1000"][0]["close"] += 1
        self.assertEqual(validate_production_source_bundle(tampered, trading_date=self.day, cadence="19:30")["validation_status"], "FAIL")
        reduced = {**bundle, "decision_records": bundle["decision_records"][:30], "coverage": "30/30"}
        self.assertEqual(validate_production_source_bundle(reduced, trading_date=self.day, cadence="19:30")["blocking_reason"], "FULL_MARKET_INPUTS_INCOMPLETE")
        legacy = {**bundle, "schema_version": "RATE-PRODUCTION-SOURCE-BUNDLE-V1"}
        self.assertEqual(validate_production_source_bundle(legacy, trading_date=self.day, cadence="19:30")["validation_status"], "FAIL")

    def test_stale_catalogue_and_incomplete_market_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "STALE_OR_FUTURE_CATALOGUE"):
            validate_catalogue(self.catalogue, "2026-10-06")
        partial = {**self.catalogue, "markets": self.catalogue["markets"][:1]}
        with self.assertRaises(RuntimeError):
            validate_catalogue(partial, self.day)

    def test_true_future_and_stale_receipts_keep_existing_freshness_gate(self):
        for offset, blocker in ((timedelta(hours=1), "SOURCE_FUTURE_DATED"),
                                (-timedelta(days=1), "SOURCE_STALE")):
            raw = raw_fixture(self.day)
            raw["normalized_source_receipts"][0]["retrieval_timestamp"] = (
                datetime.now(timezone.utc) + offset).isoformat()
            material = bind_input_material(raw, self.catalogue, self.previous,
                trading_date=self.day, cadence="19:30", authority=AUTHORITY)
            before = self.snapshot()
            with self.subTest(blocker=blocker), self.assertRaisesRegex(RuntimeError, blocker):
                bundle_from_material(material, self.catalogue, self.state_root)
            self.assertEqual(before, self.snapshot())

    def test_bootstrap_seed_main_publication_cli_rejected(self):
        source = self.root / "seed.json"
        atomic_write_json(source, {"schema_version": "RATE-PRODUCTION-SOURCE-BUNDLE-V1"})
        env = {**os.environ, "GITHUB_REF": "refs/heads/main"}
        result = subprocess.run([sys.executable, "-B", str(ROOT / "scripts/publish_production_source_bundle_latest.py"),
            "--source-bundle", str(source), "--trading-date", self.day, "--cadence", "19:30",
            "--artifacts-root", str(self.artifacts)], capture_output=True, text=True, env=env)
        self.assertEqual(result.returncode, 1)
        self.assertIn("BOOTSTRAP_UNIVERSE_NOT_NORMAL_PRODUCTION", result.stdout)

    def test_eligibility_cfi_not_symbol_heuristics_or_data_availability(self):
        header = "<tr>" + "".join("<td>" + v + "</td>" for v in
            ["Security Code &amp; Security Name", "ISIN Code", "Date Listed", "Market", "Industrial Group", "CFICode", "Remarks"]) + "</tr>"
        cases = [("COMMON-LONG", "ESVUFR", "Stocks", True), ("ETF1", "CEOILU", "ETF", False),
            ("ETN1", "DEMXXX", "ETN", False), ("WAR1", "RWXXXX", "Warrants", False),
            ("BOND1", "DBXXXX", "Bonds", False), ("PREF1", "EPXXXX", "Preferred", False),
            ("FUND1", "CIXXXX", "Funds", False), ("RIGHT1", "RSXXXX", "Rights", False)]
        body = "Date Stock Updated:2026/10/05<table>" + header
        for symbol, cfi, section, _ in cases:
            body += "<tr><td>" + section + "</td></tr><tr>" + "".join("<td>" + cell + "</td>" for cell in
                [symbol + " Fixture", "ISIN" + symbol, "2000/01/01", "TWSE LISTED", "", cfi, ""]) + "</tr>"
        _, records = parse_classification((body + "</table>").encode("big5"), "TWSE")
        self.assertEqual([row["eligible"] for row in records], [case[3] for case in cases])
        catalogue = fake_catalogue(self.day, ["LONG-COMMON-CODE"] + [str(i) for i in range(60)])
        self.assertTrue(validate_catalogue(catalogue, self.day))

    def test_schedulers_keep_cron_and_use_phase2_not_seed_runtime(self):
        import yaml
        for slot in ("0730", "0930", "1200", "1930"):
            relative = f".github/workflows/rate_production_{slot}_scheduler.yml"
            old = subprocess.check_output(["git", "-C", str(ROOT), "show", BASE + ":" + relative]).decode()
            text = (ROOT / relative).read_text()
            self.assertEqual(yaml.safe_load(text)[True]["schedule"], yaml.safe_load(old)[True]["schedule"])
            self.assertIn("run_phase2_production.py", text)
            self.assertIn("--phase2", text)
            self.assertIn("EXECUTION_AUTHORITY: MAIN_ONLY", text)
            self.assertNotIn("--cer074-persisted-evidence", text)
            self.assertLess(text.index("- name: Publish immutable production source bundle latest"),
                            text.index("- name: Publish live production state pointer"))


if __name__ == "__main__":
    unittest.main()
