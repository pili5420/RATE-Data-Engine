"""Synthetic-only inventory policy tests. No live warmup or provider credit."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from src import warmup_missingness as w
from src import fundamental_eligibility as e
from src.eps_duration_facts.model import Rejected
from tests.test_fundamental_eligibility import AS_OF, LATER, block, fixture, row

ROOT = Path(__file__).resolve().parents[1]


def material(directory):
    leaf = Path(directory) / "synthetic-owner-certificate.json"
    leaf.write_text('{"scope":"SYNTHETIC_ONLY","owner":"test"}\n', encoding="utf-8")
    ref = {"path": str(leaf), "sha256": hashlib.sha256(leaf.read_bytes()).hexdigest(), "json_locator": "$"}
    _, universe, context = fixture()
    issuers = []
    for index, stock in enumerate(universe["stocks"]):
        r = row(**stock)
        if index < 123:
            block(r, "eps_8q", "MISSING_REQUIRED_PERIOD", period="2024Q3")
        block(r, "formal_eps_period_identity", "NOT_AUTHORIZED", "FORMAL_PROVIDER_NOT_ACTIVATED")
        for verdict in r["inputs"].values():
            verdict["evidence_references"] = [deepcopy(ref)]
        state = e.issuer_eligibility(r, symbol=stock["symbol"], market=stock["market"], as_of=AS_OF,
                                    population_id=universe["catalogue_id"])
        labels = [p for p in e.WINDOW if p not in state["input_verdicts"]["eps_8q"]["missing_periods"]]
        history = {**stock, "market_universe_retained": True, "production_eligible": False,
            "eps_valid_quarter_labels": labels, "eps_missing_quarters": [p for p in e.WINDOW if p not in labels],
            "eps_valid_quarters": len(labels), "eps8_calendar_window_complete": state["eps_ready"],
            "eps_evidence_references": [{"quarter": p, "json_locator": "$.synthetic[" + str(i) + "]",
                "raw_sha256": ref["sha256"], "receipt_reference": ref["path"], "observed_at": AS_OF} for i, p in enumerate(labels)],
            "three_revenue_finite": True, "three_revenue_observations": [{"period": p,
                "finite_numeric_present": True, "numeric_status": "FINITE", "observation_exists": True,
                "receipt_reference": ref["path"]} for p in e.REVENUE_PERIODS]}
        issuers.append({**state, "original_source_issuer_evidence": history})
    return {"scope": w.PROJECTION_SCOPE, "governance": deepcopy(e.FLAGS), "generated_at": AS_OF,
            "universe_binding": universe, "issuers": issuers}, universe, context, leaf


class WarmupMissingnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.source, cls.universe, cls.context, cls.leaf = material(cls.temp.name)

    def build(self, source=None, universe=None, context=None, previous=None, generated_at=AS_OF):
        s = self.source if source is None else source
        u = self.universe if universe is None else universe
        return w.build_inventory(s, u, expected_projection_sha256=e.digest(s), expected_universe_sha256=e.digest(u),
            generated_at=generated_at, context=context, previous=previous)

    def altered(self, action, reason):
        source = deepcopy(self.source)
        action(source)
        with self.assertRaisesRegex(Rejected, reason):
            self.build(source)

    def test_1978_accounted_123_incomplete_pass(self):
        result = self.build()["core"]
        self.assertEqual(result["layers"]["FULL_MARKET_UNIVERSE_ACCOUNTING"], "PASS")
        self.assertEqual((result["counts"]["universe_accounted"], result["counts"]["eps_incomplete"]), (1978, 123))

    def test_incomplete_issuers_preserved(self):
        result = self.build()["core"]["issuers"]
        self.assertEqual({r["symbol"] for r in result}, {r["symbol"] for r in self.source["issuers"]})

    def test_valid_partial_history_preserved(self):
        self.assertEqual(self.build()["core"]["issuers"][0]["preserved_owner_evidence"], self.source["issuers"][0])

    def test_missing_issuer_rejected(self):
        self.altered(lambda s: s["issuers"].pop(), "ISSUER_MISSING")

    def test_duplicate_issuer_rejected(self):
        self.altered(lambda s: s["issuers"].__setitem__(-1, s["issuers"][0]), "ISSUER_MISSING_OR_DUPLICATED")

    def test_wrong_market_rejected(self):
        self.altered(lambda s: s["issuers"][0].update(market="TPEX"), "MARKET_IDENTITY")

    def test_wrong_universe_counts_rejected(self):
        source = deepcopy(self.source)
        source["universe_binding"]["stocks"][0]["market"] = "TPEX"
        with self.assertRaisesRegex(Rejected, "EXACT_UNIVERSE"):
            self.build(source, source["universe_binding"])

    def test_same_counts_wrong_symbol_rejected(self):
        source = deepcopy(self.source)
        source["universe_binding"]["stocks"][0]["symbol"] = "WRONG"
        with self.assertRaisesRegex(Rejected, "ISSUER_MISSING"):
            self.build(source, source["universe_binding"])

    def test_missing_eps_not_zero(self):
        state = self.build()["core"]["issuers"][0]["eligibility"]
        self.assertIsNone(state["input_verdicts"]["eps_8q"]["value"])
        self.assertEqual(state["fundamental_status"], "MISSING_REQUIRED_PERIOD")

    def test_missing_eps_fundamental_not_ready(self):
        self.assertFalse(self.build()["core"]["issuers"][0]["eligibility"]["fundamental_ready"])

    def test_universe_pass_not_ranking_pass(self):
        core = self.build()["core"]
        self.assertEqual(core["layers"]["RANKING_ELIGIBILITY_STATUS"], "SUBGATE_VERDICTS_ONLY_CONSUMER_NOT_ACTIVATED")
        self.assertEqual(core["counts"]["top50_input_ready"], 0)

    def test_short_independent_owner_gate(self):
        self.assertTrue(self.build()["core"]["issuers"][0]["eligibility"]["short_rank_input_ready"])

    def test_stage_rotation_m7_mhe_independent(self):
        state = self.build()["core"]["issuers"][0]["eligibility"]
        self.assertTrue(all(state[k] for k in ("stage_input_ready", "rotation_input_ready", "m7_input_ready", "mhe_input_ready")))

    def test_provider_not_activated(self):
        self.assertEqual(self.build()["core"]["governance"]["formal_provider_activation"], "NOT_AUTHORIZED")

    def test_first_refresh_not_authorized(self):
        self.assertEqual(self.build()["core"]["governance"]["first_refresh"], "NOT_AUTHORIZED")

    def test_no_full_warmup_pass(self):
        self.assertNotIn("FULL_WARMUP_PASS", self.build()["core"]["layers"])

    def test_production_not_eligible(self):
        self.assertIs(self.build()["core"]["governance"]["production_eligible"], False)

    def test_historical_pit_unproven(self):
        self.assertEqual(self.build()["core"]["governance"]["historical_pit"], "UNPROVEN")

    def test_fallback_false(self):
        self.assertIs(self.build()["core"]["governance"]["fallback_allowed"], False)

    def test_blocked_external_unchanged(self):
        self.assertEqual(self.build()["core"]["governance"]["external_authorized_intraday_feed_dependency"], "BLOCKED_EXTERNAL")

    def test_silent_fallback_rejected(self):
        self.altered(lambda s: s["governance"].update(fallback_allowed=True), "SOURCE_GOVERNANCE")

    def test_synthetic_missing_value_rejected(self):
        self.altered(lambda s: s["issuers"][0]["input_verdicts"]["eps_8q"].update(value=0), "NON_SCORE_VALUE_FORBIDDEN")

    def test_missing_reason_absent_rejected(self):
        self.altered(lambda s: s["issuers"][0]["input_verdicts"]["eps_8q"].update(reason=None), "MISSING_REASON_REQUIRED")

    def test_missing_owner_verdict_rejected(self):
        self.altered(lambda s: s["issuers"][0]["input_verdicts"].pop("eps_8q"), "EXPLICIT_EVIDENCE")

    def test_invalid_evidence_not_accepted_as_missing(self):
        self.altered(lambda s: s["issuers"][0]["input_verdicts"]["eps_8q"].update(status="INVALID_EVIDENCE"), "INVALID_OWNER_EVIDENCE")

    def test_unknown_missing_status_rejected(self):
        self.altered(lambda s: s["issuers"][0]["input_verdicts"]["eps_8q"].update(status="NOT_APPLICABLE"), "UNAPPROVED_MISSING")

    def test_readiness_conflict_rejected(self):
        self.altered(lambda s: s["issuers"][0].update(fundamental_ready=True), "READINESS_STATE_CONFLICT")

    def test_duplicate_history_quarter_rejected(self):
        self.altered(lambda s: s["issuers"][0]["original_source_issuer_evidence"]["eps_valid_quarter_labels"].append("2025Q1"), "HISTORY_WINDOW")

    def test_older_quarter_substitution_rejected(self):
        self.altered(lambda s: s["issuers"][0]["original_source_issuer_evidence"]["eps_valid_quarter_labels"].__setitem__(0, "2023Q4"), "HISTORY_WINDOW")

    def test_history_identity_conflict_rejected(self):
        self.altered(lambda s: s["issuers"][0]["original_source_issuer_evidence"].update(symbol="WRONG"), "HISTORY_IDENTITY")

    def test_partial_history_reference_loss_rejected(self):
        self.altered(lambda s: s["issuers"][0]["original_source_issuer_evidence"]["eps_evidence_references"].pop(), "PARTIAL_HISTORY_REFERENCE")

    def test_revenue_wrong_period_rejected(self):
        self.altered(lambda s: s["issuers"][0]["original_source_issuer_evidence"]["three_revenue_observations"][0].update(period="2026-06"), "REVENUE_WINDOW")

    def test_trusted_projection_hash_rejected(self):
        with self.assertRaisesRegex(Rejected, "TRUSTED_INPUT"):
            w.build_inventory(self.source, self.universe, expected_projection_sha256="0" * 64,
                expected_universe_sha256=e.digest(self.universe), generated_at=AS_OF)

    def test_source_byte_tamper_rejected(self):
        before = self.leaf.read_bytes()
        try:
            self.leaf.write_bytes(before + b" ")
            with self.assertRaisesRegex(Rejected, "SOURCE_HASH_MISMATCH"):
                self.build()
        finally:
            self.leaf.write_bytes(before)

    def test_future_time_rejected(self):
        with self.assertRaisesRegex(Rejected, "TIME_BACKFILL"):
            self.build(generated_at="2026-10-09T00:00:00+00:00")

    def test_artifact_tamper_rejected(self):
        result = self.build()
        result["core"]["counts"]["eps_ready"] += 1
        with self.assertRaisesRegex(Rejected, "TAMPERED"):
            w.verify_inventory(result)

    def test_rehashed_false_readiness_rejected(self):
        result = self.build()
        result["core"]["issuers"][0]["eligibility"]["eps_ready"] = True
        result["content_sha256"] = e.digest(result["core"])
        result["snapshot_id"] = "rate-warmup-inventory-" + result["content_sha256"]
        with self.assertRaisesRegex(Rejected, "ACCEPTANCE_STATE_CONFLICT"):
            w.verify_inventory(result)

    def test_order_independence(self):
        source = deepcopy(self.source)
        source["issuers"].reverse()
        self.assertEqual(self.build()["core"]["counts"], self.build(source)["core"]["counts"])

    def test_no_context_not_initialized(self):
        self.assertIsNone(self.build()["core"]["continuity_context"])

    def test_portfolio_ledger_decision_context_preserved(self):
        before = deepcopy(self.context)
        first = self.build(context=self.context)
        second = self.build(context=self.context, previous=first, generated_at=LATER)
        self.assertEqual(first["core"]["continuity_context"], second["core"]["continuity_context"])
        self.assertEqual(self.context, before)
        self.assertEqual(second["core"]["previous_inventory_sha256"], first["content_sha256"])
        self.assertTrue(all(b["inventory_history"][:-1] == a["inventory_history"] for a, b in zip(first["core"]["issuers"], second["core"]["issuers"])))

    def test_context_reset_rejected(self):
        first = self.build(context=self.context)
        changed = deepcopy(self.context)
        changed["current_state_id"] = "RESET"
        with self.assertRaisesRegex(Rejected, "STATE_OR_HISTORY_IDENTITY"):
            self.build(context=changed, previous=first, generated_at=LATER)

    def test_ledger_fill_rejected(self):
        first = self.build(context=self.context)
        changed = deepcopy(self.context)
        changed["transaction_ledger"].append({"synthetic_fill": True})
        with self.assertRaisesRegex(Rejected, "STATE_OR_HISTORY_IDENTITY"):
            self.build(context=changed, previous=first, generated_at=LATER)

    def test_cli_cold_read_and_no_overwrite(self):
        from tests.test_fundamental_eligibility import CLITests
        authority = CLITests()
        authority.setUp()
        try:
            root = authority.root
            path = root / "historical.json"
            pin, commit = hashlib.sha256(path.read_bytes()).hexdigest(), "0" * 40
            from src.provider_eps_coverage import load_universe
            universe = load_universe(path, pin, commit)
            source = deepcopy(self.source)
            source["universe_binding"] = universe
            symbols = {m: iter([s["symbol"] for s in universe["stocks"] if s["market"] == m]) for m in e.COUNTS}
            for r in source["issuers"]:
                r["symbol"] = next(symbols[r["market"]])
                r["original_source_issuer_evidence"]["symbol"] = r["symbol"]
                for verdict in r["input_verdicts"].values():
                    if verdict.get("population_id") is not None:
                        verdict["population_id"] = universe["catalogue_id"]
            source_path = root / "projection.json"
            source_path.write_text(json.dumps(source), encoding="utf-8")
            pins = root / "source-pins.json"
            pins.write_text(json.dumps({str(self.leaf): {"bytes": self.leaf.stat().st_size,
                "sha256": hashlib.sha256(self.leaf.read_bytes()).hexdigest()}}), encoding="utf-8")
            command = [sys.executable, "-B", str(ROOT / "scripts/build_warmup_missingness.py"),
                "--projection", str(source_path), "--projection-sha256", hashlib.sha256(source_path.read_bytes()).hexdigest(),
                "--universe-evidence", str(path), "--universe-sha256", pin, "--universe-commit", commit,
                "--source-manifest", str(pins), "--source-manifest-sha256", hashlib.sha256(pins.read_bytes()).hexdigest(),
                "--output-dir", str(root / "first")]
            first = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(first.returncode, 0, first.stderr)
            output = root / "first/WARMUP_INVENTORY.json"
            frozen = output.read_bytes()
            code = "from src.fundamental_eligibility import read_pinned; from src.warmup_missingness import verify_inventory; import sys; verify_inventory(read_pinned(sys.argv[1],sys.argv[2]))"
            cold = subprocess.run([sys.executable, "-B", "-c", code, str(output), hashlib.sha256(frozen).hexdigest()], cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(cold.returncode, 0, cold.stderr)
            self.assertNotEqual(subprocess.run(command, capture_output=True).returncode, 0)
            self.assertEqual(output.read_bytes(), frozen)
        finally:
            authority.doCleanups()

    def test_input_not_mutated(self):
        before = e.digest(self.source)
        self.build()
        self.assertEqual(e.digest(self.source), before)

    def test_revenue_zero_base_not_zero(self):
        source = deepcopy(self.source)
        original = source["issuers"][0]
        inputs = {k: {n: v for n, v in verdict.items() if n != "missing_periods"} for k, verdict in original["input_verdicts"].items()}
        r = {"symbol": original["symbol"], "market": original["market"], "inputs": inputs}
        block(r, "revenue_3m", "UNDEFINED_ZERO_BASE", "UNDEFINED_ZERO_BASE", "2026-09")
        state = e.issuer_eligibility(r, symbol=r["symbol"], market=r["market"], as_of=AS_OF, population_id=self.universe["catalogue_id"])
        original.update(state)
        history = original["original_source_issuer_evidence"]
        history["three_revenue_finite"] = False
        history["three_revenue_observations"][2].update(finite_numeric_present=False, numeric_status="UNDEFINED_ZERO_BASE")
        result = self.build(source)["core"]
        self.assertEqual(result["counts"]["revenue_incomplete"], 1)
        self.assertIsNone(result["issuers"][0]["eligibility"]["input_verdicts"]["revenue_3m"]["value"])

    def test_future_history_observation_rejected(self):
        self.altered(lambda s: s["issuers"][0]["original_source_issuer_evidence"]["eps_evidence_references"][0].update(observed_at=LATER), "FUTURE_HISTORY")

    def test_eps_zero_base_not_approved_missing_reason(self):
        self.altered(lambda s: s["issuers"][0]["input_verdicts"]["eps_8q"].update(status="UNDEFINED_ZERO_BASE"), "EPS_MISSING_REASON")


if __name__ == "__main__":
    unittest.main()
