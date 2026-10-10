"""Synthetic owner verdicts only; no real qualification or Production credit."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import unittest

from src import fundamental_eligibility as e
from src.eps_duration_facts.model import Rejected
from src.rate_logic import rank_composites

ROOT = Path(__file__).resolve().parents[1]
AS_OF = "2026-10-10T14:00:00+00:00"
LATER = "2026-10-10T15:00:00+00:00"
POPULATION = "SYNTHETIC_ENGINEERING_NOT_REAL_CATALOGUE"


def row(symbol="S0000", market="TWSE"):
    inputs = {}
    for name, owner in e.OWNERS.items():
        periods = e.WINDOW if name == "eps_8q" else e.REVENUE_PERIODS if name == "revenue_3m" else ()
        score = name not in {"eps_8q", "revenue_3m", "formal_eps_period_identity"}
        inputs[name] = {"owner": owner, "status": "PASS", "reason": None, "observed_at": AS_OF,
            "validated_at": AS_OF, "evidence_references": [{"path": "SYNTHETIC_ONLY_OWNER_VERDICT.json",
                "sha256": "a" * 64, "json_locator": "$.synthetic_owner_verdict"}],
            "period_statuses": dict.fromkeys(periods, "PASS"), "value": "50.125" if score else None,
            "population_id": POPULATION if score else None}
    return {"symbol": symbol, "market": market, "inputs": inputs}


def block(value, name, status="NOT_EVALUATED", reason="SYNTHETIC_REQUIRED_INPUT_MISSING", period=None):
    verdict = value["inputs"][name]
    verdict.update(status=status, reason=reason, value=None)
    if verdict["period_statuses"]:
        verdict["period_statuses"][period or next(iter(verdict["period_statuses"]))] = status
    return value


def fixture():
    stocks = [{"symbol": f"S{i:04d}", "market": "TWSE" if i < 1085 else "TPEX"} for i in range(1978)]
    universe = {"verification_status": "PASS", "catalogue_id": POPULATION, "stocks": stocks,
                "evidence_class": "SYNTHETIC_ONLY"}
    rows = [{**s, "inputs": {}} for s in stocks]
    rows[0] = row()
    rows[1] = block(row("S0001"), "eps_8q", "MISSING_REQUIRED_PERIOD", period="2024Q3")
    bundle = {"artifact_kind": "RATE_OWNER_INPUT_VERDICTS_V1", "universe_id": POPULATION,
              "as_of": AS_OF, "rows": rows}
    context = {"current_state_id": "SYNTHETIC_FORMAL_OWNER_STATE_NOT_LIVE", "issuer_history": {"S0001": ["kept"]},
               "eligibility_history": ["existing_owner_history_kept"],
               "roy_portfolio": {"cash": 1000, "positions": [{"symbol": "S0001", "shares": 10}]},
               "ai_paper_portfolio": {"cash": 500, "positions": []}, "transaction_ledger": [{"id": "unchanged"}]}
    return bundle, universe, context


def overlay(bundle=None, universe=None, context=None, previous=None, generated_at=AS_OF):
    b, u, c = fixture()
    b, u, c = bundle if bundle is not None else b, universe if universe is not None else u, context if context is not None else c
    return e.build_overlay(b, u, expected_bundle_sha256=e.digest(b), expected_universe_sha256=e.digest(u),
                           context=c, previous=previous, generated_at=generated_at)


def owner_result(r, kind, result):
    return {"symbol": r["symbol"], "market": r["market"], "population_id": POPULATION,
            "input_row_sha256": e.digest(r), "ranking_kind": kind, **result}


class EligibilityTests(unittest.TestCase):
    def evaluate(self, r=None):
        r = row() if r is None else r
        return e.issuer_eligibility(r, symbol="S0000", market="TWSE", as_of=AS_OF, population_id=POPULATION)

    def gate(self, r, kind, result=None):
        result = owner_result(r, kind, {"score": 50.125, "rank": 1} if result is None else result)
        return e.gate_owner_ranking(r, kind=kind, owner_result=result,
            symbol="S0000", market="TWSE", as_of=AS_OF, population_id=POPULATION)

    def test_complete_all_mandatory_fundamental(self):
        state = self.evaluate()
        self.assertTrue(state["fundamental_ready"])
        self.assertEqual(state["fundamental_status"], "PASS")

    def test_missing_eps(self):
        state = self.evaluate(block(row(), "eps_8q", "MISSING_REQUIRED_PERIOD"))
        self.assertFalse(state["eps_ready"])
        self.assertFalse(state["fundamental_ready"])
        self.assertEqual(state["fundamental_status"], "MISSING_REQUIRED_PERIOD")

    def test_missing_revenue(self):
        state = self.evaluate(block(row(), "revenue_3m", "MISSING_REQUIRED_PERIOD"))
        self.assertFalse(state["fundamental_ready"])
        self.assertFalse(state["revenue_ready"])
        self.assertEqual(state["fundamental_missing_reasons"][0]["input"], "revenue_3m")

    def test_zero_base_preserves_reason(self):
        state = self.evaluate(block(row(), "revenue_3m", "UNDEFINED_ZERO_BASE", "UNDEFINED_ZERO_BASE", "2026-09"))
        self.assertFalse(state["revenue_ready"])
        self.assertEqual(state["fundamental_missing_reasons"][0]["status"], "UNDEFINED_ZERO_BASE")

    def test_top50_missing_fundamental_null(self):
        gate = self.gate(block(row(), "eps_8q", "MISSING_REQUIRED_PERIOD"), "top50")
        self.assertEqual((gate["ranking_eligible"], gate["score"], gate["rank"]), (False, None, None))

    def test_long_missing_fundamental_null(self):
        gate = self.gate(block(row(), "revenue_3m", "MISSING_REQUIRED_PERIOD"), "long")
        self.assertEqual((gate["ranking_eligible"], gate["score"], gate["rank"]), (False, None, None))

    def test_short_missing_fundamental_still_eligible(self):
        r = block(row(), "eps_8q", "MISSING_REQUIRED_PERIOD")
        self.assertFalse(self.evaluate(r)["fundamental_ready"])
        self.assertTrue(self.gate(r, "short")["ranking_eligible"])

    def test_short_own_technical_missing_blocks(self):
        gate = self.gate(block(row(), "M7"), "short")
        self.assertFalse(gate["ranking_eligible"])
        self.assertIsNone(gate["score"])

    def test_short_tie_liquidity_missing_blocks(self):
        self.assertFalse(self.gate(block(row(), "Liquidity"), "short")["ranking_eligible"])

    def test_short_market_block(self):
        self.assertFalse(self.gate(block(row(), "RelativeStrength", "BLOCKED_EXTERNAL"), "short")["ranking_eligible"])

    def test_stage_independent_eps(self):
        self.assertTrue(self.evaluate(block(row(), "eps_8q", "MISSING_REQUIRED_PERIOD"))["stage_input_ready"])

    def test_rotation_independent_eps(self):
        self.assertTrue(self.evaluate(block(row(), "eps_8q", "MISSING_REQUIRED_PERIOD"))["rotation_input_ready"])

    def test_m7_independent_eps(self):
        self.assertTrue(self.evaluate(block(row(), "eps_8q", "MISSING_REQUIRED_PERIOD"))["m7_input_ready"])

    def test_mhe_independent_eps(self):
        self.assertTrue(self.evaluate(block(row(), "eps_8q", "MISSING_REQUIRED_PERIOD"))["mhe_input_ready"])

    def test_technical_missing_does_not_block_fundamental(self):
        state = self.evaluate(block(row(), "Stage"))
        self.assertTrue(state["fundamental_ready"])
        self.assertFalse(state["stage_input_ready"])

    def test_each_module_still_requires_own_owner(self):
        for name, key in (("Stage", "stage_input_ready"), ("Rotation", "rotation_input_ready"),
                          ("M7", "m7_input_ready"), ("MHE", "mhe_input_ready")):
            with self.subTest(name=name):
                self.assertFalse(self.evaluate(block(row(), name))[key])

    def test_long_does_not_add_rotation_requirement(self):
        self.assertTrue(self.gate(block(row(), "Rotation"), "long")["ranking_eligible"])

    def test_no_score_renormalization(self):
        r = block(row(), "Fundamental", "NOT_COMPUTED")
        gate = self.gate(r, "long", {"score": 99, "rank": 1})
        self.assertIsNone(gate["score"])
        self.assertIsNone(gate["rank"])

    def test_no_weight_redistribution_owner_result_unchanged(self):
        values = {k: 20 + i * 7.125 for i, k in enumerate(("M7", "MHE", "Stage", "Rotation", "SmartMoney", "Fundamental", "RelativeStrength"))}
        scores = rank_composites(values)
        for kind, key in (("top50", "rate_composite_score"), ("long", "long_score"), ("short", "short_score")):
            result = {"score": scores[key], "rank": 7}
            actual = self.gate(row(), kind, result)
            self.assertEqual((actual["score"], actual["rank"]), (result["score"], 7))

    def test_no_owner_output_no_fabricated_score(self):
        self.assertEqual(self.evaluate()["ranking_gates"]["short"]["status"], "INPUT_READY_NOT_CALCULATED")
        self.assertIsNone(self.evaluate()["ranking_gates"]["short"]["score"])

    def test_fundamental_inputs_ready_before_own_score_exists(self):
        r = row()
        del r["inputs"]["Fundamental"]
        state = self.evaluate(r)
        self.assertTrue(state["fundamental_ready"])
        self.assertFalse(state["long_rank_input_ready"])
        self.assertFalse(state["top50_input_ready"])

    def test_stage_inputs_ready_before_own_score_exists(self):
        r = row()
        r["inputs"]["Stage"]["value"] = None
        state = self.evaluate(r)
        self.assertTrue(state["stage_input_ready"])
        self.assertFalse(state["short_rank_input_ready"])
        self.assertTrue(any(reason["status"] == "NOT_COMPUTED" for reason in state["ranking_gates"]["short"]["missing_reasons"]))

    def test_uncomputed_component_never_renormalized(self):
        r = row()
        r["inputs"]["Fundamental"]["value"] = None
        self.assertTrue(self.evaluate(r)["fundamental_ready"])
        self.assertIsNone(self.gate(r, "long")["score"])

    def test_formal_period_qualification_not_bypassed(self):
        state = self.evaluate(block(row(), "formal_eps_period_identity", "NOT_AUTHORIZED"))
        self.assertTrue(state["eps_ready"])
        self.assertFalse(state["fundamental_ready"])
        self.assertFalse(state["top50_input_ready"])

    def test_calendar_owner_cannot_impersonate_formal_owner(self):
        r = row()
        r["inputs"]["formal_eps_period_identity"]["owner"] = "PROVIDER_CALENDAR_QUARTER_BASIC_EPS"
        with self.assertRaisesRegex(Rejected, "OWNER_OR_STATUS"):
            self.evaluate(r)

    def test_wrong_symbol(self):
        with self.assertRaisesRegex(Rejected, "ISSUER_IDENTITY"):
            self.evaluate(row("wrong"))

    def test_wrong_market(self):
        with self.assertRaisesRegex(Rejected, "ISSUER_IDENTITY"):
            self.evaluate(row(market="TPEX"))

    def test_wrong_window(self):
        r = row()
        r["inputs"]["eps_8q"]["period_statuses"]["2024Q2"] = r["inputs"]["eps_8q"]["period_statuses"].pop("2024Q3")
        with self.assertRaisesRegex(Rejected, "WINDOW_MISMATCH"):
            self.evaluate(r)

    def test_pass_cannot_hide_missing_period(self):
        r = row()
        r["inputs"]["eps_8q"]["period_statuses"]["2024Q3"] = "MISSING_REQUIRED_PERIOD"
        with self.assertRaisesRegex(Rejected, "PERIOD_VERDICT_CONFLICT"):
            self.evaluate(r)

    def test_missing_reason_mandatory(self):
        r = block(row(), "M7")
        r["inputs"]["M7"]["reason"] = None
        with self.assertRaisesRegex(Rejected, "MISSING_REASON"):
            self.evaluate(r)

    def test_no_global_ready_override(self):
        r = row()
        r["inputs"]["global_ready"] = True
        with self.assertRaisesRegex(Rejected, "UNKNOWN_INPUT"):
            self.evaluate(r)

    def test_unknown_technical_not_inferred(self):
        r = row()
        for name in e.RANK_INPUTS["short"]:
            del r["inputs"][name]
        state = self.evaluate(r)
        self.assertTrue(state["fundamental_ready"])
        self.assertFalse(state["short_rank_input_ready"])

    def test_nonfinite_and_bool_scores_rejected(self):
        for value in (True, "NaN", "Infinity", float("inf"), "x", -1, 101):
            with self.subTest(value=str(value)), self.assertRaises(Rejected):
                self.gate(row(), "short", {"score": value, "rank": 1})

    def test_invalid_rank_rejected(self):
        for rank in (0, True, 1.5, 1979):
            with self.subTest(rank=rank), self.assertRaises(Rejected):
                self.gate(row(), "short", {"score": 20, "rank": rank})

    def test_owner_ranking_wrong_identity_rejected(self):
        for key, value in (("symbol", "wrong"), ("market", "wrong"), ("population_id", "wrong"),
                           ("input_row_sha256", "0" * 64), ("ranking_kind", "long")):
            with self.subTest(key=key), self.assertRaisesRegex(Rejected, "RANKING_BINDING_INVALID"):
                self.gate(row(), "short", {"score": 20, "rank": 1, key: value})

    def test_zero_score_preserved(self):
        self.assertEqual(self.gate(row(), "short", {"score": 0, "rank": 1})["score"], 0)

    def test_future_evidence_rejected(self):
        r = row()
        r["inputs"]["M7"]["validated_at"] = LATER
        with self.assertRaisesRegex(Rejected, "NOT_YET_AVAILABLE"):
            self.evaluate(r)

    def test_wrong_component_population_rejected(self):
        r = row()
        r["inputs"]["M7"]["population_id"] = "EPS_PREFILTERED_SUBSET"
        with self.assertRaisesRegex(Rejected, "POPULATION_MISMATCH"):
            self.evaluate(r)


class OverlayTests(unittest.TestCase):
    def test_full_universe_1978_preserved(self):
        actual = overlay()["core"]
        self.assertEqual(len(actual["issuers"]), 1978)
        self.assertEqual(dict(e.Counter(r["market"] for r in actual["issuers"])), e.COUNTS)
        self.assertTrue(all(r["universe_eligible"] for r in actual["issuers"]))

    def test_counts_are_derived_from_inputs(self):
        actual = overlay()["core"]["counts"]
        self.assertEqual(actual["fundamental_ready"], 1)
        self.assertEqual(actual["short_rank_input_ready"], 2)

    def test_no_portfolio_mutation(self):
        b, u, c = fixture()
        original = deepcopy(c)
        actual = overlay(b, u, c)
        self.assertEqual(c, original)
        self.assertEqual(actual["core"]["continuity_context"]["roy_portfolio"], original["roy_portfolio"])
        self.assertEqual(actual["core"]["continuity_context"]["ai_paper_portfolio"], original["ai_paper_portfolio"])

    def test_no_ledger_fill(self):
        b, u, c = fixture()
        self.assertEqual(overlay(b, u, c)["core"]["continuity_context"]["transaction_ledger"], c["transaction_ledger"])

    def test_held_ineligible_no_trade(self):
        actual = overlay()["core"]["issuers"][1]
        self.assertEqual(actual["held_position_status"], "RANKING_INELIGIBLE_HELD_POSITION")
        self.assertFalse({"order", "BUY", "SELL", "forced_exit", "fill"} & set(actual))

    def test_continuity_history_and_parent_hash(self):
        first = overlay()
        b, u, c = fixture()
        b["as_of"] = LATER
        b["rows"][1] = row("S0001")
        second = overlay(b, u, c, previous=first, generated_at=LATER)
        self.assertEqual(second["core"]["previous_eligibility_snapshot_id"], first["snapshot_id"])
        self.assertEqual(second["core"]["previous_eligibility_content_sha256"], first["content_sha256"])
        self.assertEqual(second["core"]["continuity_context"], first["core"]["continuity_context"])
        self.assertEqual(second["core"]["issuers"][1]["eligibility_history"][:-1], first["core"]["issuers"][1]["eligibility_history"])
        self.assertFalse(first["core"]["issuers"][1]["fundamental_ready"])
        self.assertTrue(second["core"]["issuers"][1]["fundamental_ready"])

    def test_account_reset_rejected(self):
        first = overlay()
        b, u, c = fixture()
        c["roy_portfolio"]["positions"] = []
        with self.assertRaisesRegex(Rejected, "ACCOUNT_OR_ISSUER_HISTORY_MUTATION"):
            overlay(b, u, c, previous=first)

    def test_previous_issuer_history_reset_rejected(self):
        first = overlay()
        b, u, c = fixture()
        c["issuer_history"] = {}
        with self.assertRaisesRegex(Rejected, "ACCOUNT_OR_ISSUER_HISTORY_MUTATION"):
            overlay(b, u, c, previous=first)

    def test_issuer_cannot_be_dropped(self):
        b, u, c = fixture()
        b["rows"].pop()
        with self.assertRaisesRegex(Rejected, "DROPPED_OR_DUPLICATED"):
            overlay(b, u, c)

    def test_duplicate_issuer_rejected(self):
        b, u, c = fixture()
        b["rows"][-1] = b["rows"][0]
        with self.assertRaisesRegex(Rejected, "DROPPED_OR_DUPLICATED"):
            overlay(b, u, c)

    def test_previous_overlay_tamper_rejected(self):
        previous = overlay()
        previous["core"]["issuers"][0]["fundamental_ready"] = False
        with self.assertRaisesRegex(Rejected, "OVERLAY_TAMPERED"):
            overlay(previous=previous)

    def test_time_backfill_rejected(self):
        first = overlay()
        b, u, c = fixture()
        b["as_of"] = "2026-10-05T00:00:00+00:00"
        with self.assertRaisesRegex(Rejected, "TIME_BACKFILL"):
            overlay(b, u, c, previous=first)

    def test_generation_cannot_precede_inputs(self):
        with self.assertRaisesRegex(Rejected, "GENERATION_TIME"):
            overlay(generated_at="2026-10-05T00:00:00+00:00")

    def test_no_provider_or_warmup_activation(self):
        flags = overlay()["core"]["governance"]
        self.assertEqual(flags["formal_provider_activation"], "NOT_AUTHORIZED")
        self.assertEqual(flags["warmup_activation"], "NOT_AUTHORIZED")
        self.assertFalse(flags["production_eligible"])
        self.assertFalse(flags["fallback_allowed"])
        self.assertEqual(flags["historical_pit"], "UNPROVEN")
        self.assertEqual(flags["warmup_acceptance"], "UNCHANGED_NOT_PERFORMED")

    def test_output_cannot_mutate_governance_constants(self):
        result = overlay()
        result["core"]["governance"]["production_eligible"] = True
        self.assertFalse(e.FLAGS["production_eligible"])
        with self.assertRaisesRegex(Rejected, "OVERLAY_TAMPERED"):
            e.verify_overlay(result)

    def test_reordering_does_not_change_readiness_or_display_order(self):
        b, u, c = fixture()
        first = overlay(b, u, c)
        random.Random(10).shuffle(b["rows"])
        # Bundle source identity changes, but sorted issuer readiness is invariant.
        second = overlay(b, u, c)
        self.assertEqual(first["core"]["counts"], second["core"]["counts"])
        self.assertEqual([r["symbol"] for r in first["core"]["issuers"]], [r["symbol"] for r in second["core"]["issuers"]])

    def test_same_inputs_reproduce_identity(self):
        self.assertEqual(overlay()["content_sha256"], overlay(generated_at=LATER)["content_sha256"])

    def test_independent_process_cold_read(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "overlay.json"
            actual = overlay()
            path.write_text(json.dumps(actual), encoding="utf-8")
            code = "from src.fundamental_eligibility import read_pinned,verify_overlay; import sys; print(verify_overlay(read_pinned(sys.argv[1],sys.argv[2]))['content_sha256'])"
            result = subprocess.run([sys.executable, "-B", "-c", code, str(path), hashlib.sha256(path.read_bytes()).hexdigest()],
                cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), actual["content_sha256"])


class IntegrityTests(unittest.TestCase):
    def test_bundle_pin_tamper_rejected(self):
        b, u, c = fixture()
        pin = e.digest(b)
        b["rows"][0]["market"] = "TPEX"
        with self.assertRaisesRegex(Rejected, "TRUSTED_BINDING"):
            e.build_overlay(b, u, expected_bundle_sha256=pin, expected_universe_sha256=e.digest(u), context=c, generated_at=AS_OF)

    def test_universe_identity_tamper_rejected(self):
        b, u, c = fixture()
        pin = e.digest(u)
        u["stocks"][0]["symbol"] = "different"
        with self.assertRaisesRegex(Rejected, "TRUSTED_BINDING"):
            e.build_overlay(b, u, expected_bundle_sha256=e.digest(b), expected_universe_sha256=pin, context=c, generated_at=AS_OF)

    def test_reference_tamper_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.json"
            path.write_bytes(b"synthetic")
            b, _, _ = fixture()
            b["rows"] = [row()]
            for v in b["rows"][0]["inputs"].values():
                v["evidence_references"] = [{"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "json_locator": "$"}]
            before = e.replay_references(b)
            path.write_bytes(b"tamper")
            with self.assertRaisesRegex(Rejected, "SOURCE_HASH_MISMATCH"):
                e.replay_references(b)
            self.assertEqual(len(before), 1)

    def test_file_pin_tamper_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.json"
            path.write_text('{"value":1}', encoding="utf-8")
            pin = hashlib.sha256(path.read_bytes()).hexdigest()
            path.write_text('{"value":2}', encoding="utf-8")
            with self.assertRaisesRegex(Rejected, "INPUT_HASH_MISMATCH"):
                e.read_pinned(path, pin)

    def test_strict_reader_duplicate_key(self):
        with self.assertRaisesRegex(Rejected, "DUPLICATE_KEY"):
            e.read_metadata('{"key":1,"key":2}')

    def test_contract_matches_engine(self):
        contract = json.loads((ROOT / "docs/contracts/RATE_FUNDAMENTAL_ELIGIBILITY_SUBGATE_V1.json").read_text())
        self.assertEqual(contract["governance"], e.FLAGS)
        self.assertEqual(contract["schema_version"], e.VERSION)
        for name, inputs in e.REQUIREMENTS.items():
            self.assertEqual(contract["readiness_requirements"][name], list(inputs))
        for kind, inputs in e.RANK_INPUTS.items():
            key = {"top50": "top50_input_ready", "long": "long_rank_input_ready", "short": "short_rank_input_ready"}[kind]
            self.assertEqual(contract["readiness_requirements"][key], list(inputs) + ([] if kind == "short" else ["fundamental_ready"]))

    def test_no_existing_entry_imports_overlay(self):
        # The exact-head verifier additionally compares every existing Git blob.
        for path in (ROOT / "src").glob("*.py"):
            if path.name != "fundamental_eligibility.py":
                self.assertNotIn("import fundamental_eligibility", path.read_text(encoding="utf-8"))
                self.assertNotIn("from .fundamental_eligibility", path.read_text(encoding="utf-8"))


class CLITests(unittest.TestCase):
    def setUp(self):
        from tests.test_provider_eps_coverage import engineering_universe
        from src.cer074_acceptance import sha256 as catalogue_hash
        from src.full_market_history import digest
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        historical_path = self.root / "historical.json"
        engineering_universe(historical_path)
        historical = json.loads(historical_path.read_text())
        catalogue = historical["catalogue"]
        stocks = []
        for market in catalogue["markets"]:
            count = e.COUNTS[market["market"]]
            template = market["records"][0]
            prefix = "T" if market["market"] == "TWSE" else "P"
            market["records"] = [{**template, "symbol": f"{prefix}{i:04d}"} for i in range(count)]
            market["record_count"] = count
            market["records_sha256"] = catalogue_hash(market["records"])
            for receipt in market["source_receipt"].values():
                receipt["record_count"] = count
            stocks.extend({"symbol": r["symbol"], "market": r["market"]} for r in market["records"])
        catalogue.update(record_count=1978, eligible_count=1978)
        for key in ("content_hash", "catalogue_id"):
            del catalogue[key]
        catalogue["content_hash"] = catalogue_hash(catalogue)
        catalogue["catalogue_id"] = "rate-full-market-catalogue-" + catalogue["content_hash"][:24]
        historical["catalogue_sha256"] = digest(catalogue)
        historical["shards"] = [{"market": m["market"], "symbols": [r["symbol"] for r in m["records"]]} for m in catalogue["markets"]]
        del historical["plan_id"]
        historical["plan_id"] = "rate-history-plan-" + digest(historical)[:24]
        historical_path.write_text(json.dumps(historical), encoding="utf-8")
        self.source = self.root / "synthetic-source.json"
        self.source.write_bytes(b'{"synthetic":true}')
        complete = row(stocks[0]["symbol"])
        for verdict in complete["inputs"].values():
            verdict["observed_at"] = verdict["validated_at"] = "2026-10-09T00:00:00+00:00"
            if verdict["population_id"]:
                verdict["population_id"] = catalogue["catalogue_id"]
            verdict["evidence_references"] = [{"path": str(self.source), "sha256": hashlib.sha256(self.source.read_bytes()).hexdigest(), "json_locator": "$"}]
        self.bundle = {"artifact_kind": "RATE_OWNER_INPUT_VERDICTS_V1", "universe_id": catalogue["catalogue_id"],
            "as_of": "2026-10-09T00:00:00+00:00", "rows": [complete] + [{**s, "inputs": {}} for s in stocks[1:]]}
        self.input = self.root / "input.json"
        self.input.write_text(json.dumps(self.bundle), encoding="utf-8")
        self.context = self.root / "context.json"
        self.context.write_text(json.dumps(fixture()[2]), encoding="utf-8")
        self.args = [sys.executable, "-B", str(ROOT / "scripts/build_fundamental_eligibility.py"),
            "--input", str(self.input), "--input-sha256", hashlib.sha256(self.input.read_bytes()).hexdigest(),
            "--universe-evidence", str(historical_path), "--universe-sha256", hashlib.sha256(historical_path.read_bytes()).hexdigest(),
            "--universe-commit", "0" * 40, "--context", str(self.context),
            "--context-sha256", hashlib.sha256(self.context.read_bytes()).hexdigest()]

    def run_cli(self, output, extra=()):
        return subprocess.run([*self.args, "--output-dir", str(output), *extra], cwd=ROOT, capture_output=True, text=True)

    def test_cli_first_then_cold_incremental_process(self):
        one, two = self.root / "one", self.root / "two"
        first = self.run_cli(one)
        self.assertEqual(first.returncode, 0, first.stderr)
        path = one / "ELIGIBILITY_OVERLAY.json"
        original = path.read_bytes()
        second = self.run_cli(two, ["--previous-overlay", str(path), "--previous-sha256", hashlib.sha256(original).hexdigest()])
        self.assertEqual(second.returncode, 0, second.stderr)
        old, new = json.loads(original), json.loads((two / path.name).read_bytes())
        self.assertEqual(new["core"]["previous_eligibility_snapshot_id"], old["snapshot_id"])
        self.assertEqual(new["core"]["counts"]["universe"], 1978)
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(new["core"]["continuity_context"], old["core"]["continuity_context"])

    def test_cli_output_overwrite_forbidden(self):
        output = self.root / "exists"
        output.mkdir()
        self.assertNotEqual(self.run_cli(output).returncode, 0)

    def test_cli_source_tamper_writes_nothing(self):
        self.source.write_bytes(b"tamper")
        output = self.root / "source-failed"
        result = self.run_cli(output)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SOURCE_HASH_MISMATCH", result.stderr)
        self.assertFalse(output.exists())

    def test_cli_context_tamper_writes_nothing(self):
        self.context.write_bytes(b"{}")
        output = self.root / "context-failed"
        result = self.run_cli(output)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("INPUT_HASH_MISMATCH", result.stderr)
        self.assertFalse(output.exists())

    def test_cli_input_tamper_writes_nothing(self):
        self.input.write_bytes(b"{}")
        output = self.root / "input-failed"
        result = self.run_cli(output)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("INPUT_HASH_MISMATCH", result.stderr)
        self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
