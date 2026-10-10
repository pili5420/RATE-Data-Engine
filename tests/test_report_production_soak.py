"""Synthetic only. No source requests, real soak credit or live account writes."""
import copy
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from src import cer081_unattended_soak as cer081
from src import report_production_soak as report
from src.cer074_acceptance import atomic_write_json, sha256
from src.production_live_state import MANIFEST_NAME, PERSIST_NAME, STATE_NAME, file_hash, load_live_state, read_object
from tests.report_soak_support import ReportSoakFixture, reference
from tests.test_cer081_unattended_soak import cer080_persisted_fixture, scheduled_runs_fixture


class ReportProductionSoakTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = ReportSoakFixture()
        cls.addClassCleanup(cls.fixture.close)

    def setUp(self):
        self.evidence = copy.deepcopy(self.fixture.evidence)
        self.root = self.fixture.artifacts / "production_state"

    def evaluate(self):
        return report.evaluate(evidence=self.evidence, state_root=self.root)

    def rewrite(self, reference_value, mutate):
        path = Path(reference_value["path"])
        original = path.read_bytes()
        self.addCleanup(path.write_bytes, original)
        value = read_object(path)
        mutate(value)
        atomic_write_json(path, value)
        reference_value["sha256"] = file_hash(path)

    def change_decision(self, index, mutate):
        slot = self.evidence["runs"][index]
        directory = Path(slot["state_manifest"]["path"]).parent
        material = read_object(directory / STATE_NAME)
        persist = read_object(directory / PERSIST_NAME)
        manifest = read_object(directory / MANIFEST_NAME)
        decision = material["decision_state"]["decision"]
        mutate(decision)
        digest = sha256(report.partial.strip_runtime(decision))
        state_id = "rate-state-" + digest[:24]
        material["decision_state"].update(current_state_id=state_id, decision_payload_hash=digest)
        material["state_entry"].update(current_state_id=state_id, decision_payload_hash=digest)
        persist.update(current_state_id=state_id, current_state_hash=digest)
        persist["persist_result"]["state_entry"] = material["state_entry"]
        for name, value in ((STATE_NAME, material), (PERSIST_NAME, persist)):
            path = directory / name
            self.addCleanup(path.write_bytes, path.read_bytes())
            atomic_write_json(path, value)
        manifest.update(current_state_id=state_id, current_state_hash=digest,
            files={name: file_hash(directory / name) for name in (STATE_NAME, PERSIST_NAME)})
        self.rewrite(slot["state_manifest"], lambda value: value.update(manifest))

    def test_three_by_four_report_pass(self):
        result = self.evaluate()
        self.assertEqual(result["RATE_REPORT_PRODUCTION_SOAK"], "PASS")
        self.assertEqual((result["trading_days"], result["scheduled_runs"], result["intraday_chains"], result["cross_day_transitions"]), (3, 12, 3, 2))

    def test_partial_valid_receives_report_credit(self):
        partial = [run for run in self.evaluate()["runs"] if run["cadence"] in ("09:30", "12:00")]
        self.assertEqual(len(partial), 6)
        self.assertTrue(all(run["report_soak_credit"] == 1 and run["report_runtime_status"] == "PARTIAL_VALID" for run in partial))

    def test_same_evidence_cer081_blocked(self):
        result = self.evaluate()
        with patch("src.cer081_unattended_soak._verify_model_freeze", return_value={"status": "PASS"}):
            artifacts = cer081.build_cer081_artifacts(cer080_persisted=cer080_persisted_fixture(),
                scheduled_runs_raw=[dict(run, event_name="schedule") for run in result["runs"]],
                rate_source_url=cer081.APPROVED_RATE_SOURCE_URL, token_present=False)
        summary = artifacts["RATE_CER081_SOAK_SUMMARY.json"]
        self.assertEqual(summary["CER081_FULL_PRODUCTION_SOAK"], "BLOCKED_EXTERNAL")
        self.assertEqual(summary["final_result"], "FAIL")
        self.assertTrue(all(run["cer081_credit"] == 0 for run in summary["report_only_runs"]))

    def test_manual_no_credit(self):
        for run in self.evidence["runs"]:
            run["event_name"] = "workflow_dispatch"
        self.assertEqual(self.evaluate()["scheduled_runs"], 0)
        self.assertEqual(self.evaluate()["RATE_REPORT_PRODUCTION_SOAK"], "HOLD")

    def test_conflicting_event_no_credit(self):
        self.evidence["runs"][0]["event"] = "workflow_dispatch"
        with self.assertRaises(RuntimeError):
            self.evaluate()

    def test_manifest_dispatch_is_not_schedule(self):
        self.rewrite(self.evidence["runs"][0]["state_manifest"], lambda m: m.update(event_name="workflow_dispatch"))
        with self.assertRaises(RuntimeError):
            self.evaluate()

    def test_public_gate_fail(self):
        self.change_decision(1, lambda d: d.update(public_official_evidence_gate="FAIL"))
        with self.assertRaisesRegex(RuntimeError, "GATE_INVALID"):
            self.evaluate()

    def test_midday_synthetic_fill(self):
        self.change_decision(2, lambda d: d["transaction_ledger"]["transactions"].append({"id": "synthetic-fill"}))
        with self.assertRaisesRegex(RuntimeError, "LEDGER_CHANGED"):
            self.evaluate()

    def test_ai_paper_execution(self):
        self.change_decision(1, lambda d: d.update(ai_paper_execution_status="EXECUTED"))
        with self.assertRaisesRegex(RuntimeError, "GATE_INVALID"):
            self.evaluate()

    def test_state_reset(self):
        self.change_decision(0, lambda d: d.update(state_reinitialized=True))
        with self.assertRaisesRegex(RuntimeError, "STATE_RESET"):
            self.evaluate()

    def test_broken_midday_lineage(self):
        self.change_decision(2, lambda d: d.update(previous_state_hash="e" * 64))
        with self.assertRaisesRegex(RuntimeError, "LINEAGE_BROKEN"):
            self.evaluate()

    def test_broken_cross_day(self):
        self.change_decision(4, lambda d: d.update(previous_state_hash="e" * 64))
        with self.assertRaisesRegex(RuntimeError, "LINEAGE_BROKEN"):
            self.evaluate()

    def test_roy_continuity(self):
        self.change_decision(4, lambda d: d["roy_portfolio"].update(cash=0))
        with self.assertRaisesRegex(RuntimeError, "ACCOUNT_OR_LEDGER_CHANGED"):
            self.evaluate()

    def test_previous_close_cannot_be_current(self):
        self.change_decision(1, lambda d: d["records"][0].update(current_price=100))
        with self.assertRaisesRegex(RuntimeError, "CURRENT_PRICE_FORBIDDEN"):
            self.evaluate()

    def test_dependency_and_governance_separate(self):
        contract = report.governance()
        self.assertEqual(contract["cer081_credit"], 0)
        self.assertEqual(contract["credit_scope"], "PUBLIC_OFFICIAL_EVIDENCE_PARTIAL_VALID_REPORT_SOAK_ONLY")
        result = self.evaluate()
        self.assertFalse(result["fallback_allowed"])
        self.assertEqual(result["external_dependency_status"], "BLOCKED_EXTERNAL")
        self.assertEqual(result["CER081_FULL_PRODUCTION_SOAK"], "BLOCKED_EXTERNAL")

    def test_no_live_credit_for_synthetic(self):
        self.assertEqual(self.evaluate()["live_scheduled_report_credit"], 0)
        self.assertFalse(self.evaluate()["production_acceptance_granted"])

    def test_no_execution_and_no_fill(self):
        self.assertTrue(all(r["ai_paper_intraday_executions"] == 0 and r["new_intraday_fills"] == 0 for r in self.evaluate()["runs"]))

    def test_read_only_hashes_unchanged(self):
        before = self.fixture.hashes()
        self.evaluate()
        self.assertEqual(self.fixture.hashes(), before)

    def test_duplicate_slot(self):
        self.evidence["runs"].append(copy.deepcopy(self.evidence["runs"][0]))
        with self.assertRaisesRegex(RuntimeError, "DUPLICATE_SLOT"):
            self.evaluate()

    def test_context_reset(self):
        self.rewrite(self.evidence["runs"][0]["runtime_context"], lambda c: c.update(production_persistent_state_reset_count=1))
        with self.assertRaisesRegex(RuntimeError, "CONTEXT_INVALID"):
            self.evaluate()

    def test_missing_source(self):
        self.evidence["runs"][1]["source_bundle"]["path"] += ".missing"
        with self.assertRaises(OSError):
            self.evaluate()

    def test_source_hash_tamper(self):
        self.evidence["runs"][1]["source_bundle"]["sha256"] = "e" * 64
        with self.assertRaisesRegex(RuntimeError, "REFERENCE_HASH_MISMATCH"):
            self.evaluate()

    def test_state_hash_tamper(self):
        self.evidence["runs"][1]["state_manifest"]["sha256"] = "e" * 64
        with self.assertRaisesRegex(RuntimeError, "REFERENCE_HASH_MISMATCH"):
            self.evaluate()

    def test_future_validation(self):
        self.evidence["runs"][0]["source_validated_at"] = "2099-01-01T00:00:00Z"
        with self.assertRaisesRegex(RuntimeError, "FUTURE_VALIDATION"):
            self.evaluate()

    def test_stale_source_at_validation(self):
        self.evidence["runs"][1]["source_validated_at"] = "2026-01-01T00:00:00Z"
        with self.assertRaisesRegex(RuntimeError, "FUTURE_OBSERVATION"):
            self.evaluate()

    def test_raw_receipt_tamper(self):
        bundle = read_object(self.evidence["runs"][1]["source_bundle"]["path"])
        receipt_path = Path(bundle["sources"][0]["receipt_path"])
        old = receipt_path.read_bytes()
        self.addCleanup(receipt_path.write_bytes, old)
        receipt_path.write_bytes(old + b" ")
        with self.assertRaisesRegex(RuntimeError, "RECEIPT_HASH_MISMATCH"):
            self.evaluate()

    def test_eod_closure_required(self):
        self.change_decision(3, lambda d: d["evening_closure"].update(state_reinitialized=True))
        with self.assertRaisesRegex(RuntimeError, "EOD_CLOSURE_INVALID"):
            self.evaluate()

    def test_full_acceptance_promotion_rejected(self):
        self.change_decision(2, lambda d: d.update(full_production_acceptance="PASS"))
        with self.assertRaisesRegex(RuntimeError, "GATE_INVALID"):
            self.evaluate()

    def test_report_cli_cold_read(self):
        output = self.fixture.base / "cli-output"
        result = subprocess.run([sys.executable, "-B", str(report.ROOT / "scripts/run_report_production_soak_acceptance.py"),
            "--evidence", str(self.fixture.input_path), "--evidence-sha256", file_hash(self.fixture.input_path),
            "--state-root", str(self.root), "--output-dir", str(output)], cwd=report.ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(read_object(output / "REPORT_SOAK_ACCEPTANCE.json")["scheduled_runs"], 12)

    def replace_source(self, index, mutate):
        reference_value = self.evidence["runs"][index]["source_bundle"]
        self.rewrite(reference_value, mutate)
        source = read_object(reference_value["path"])
        def bind(decision):
            decision["source_bundle_hash"] = sha256(source)
            if index % 4 == 3:
                decision["eod_source_bundle"] = source
                by_symbol = {r["symbol"]: r for r in source["eod_close_records"]}
                for row in decision["records"]:
                    row["Evening_evidence"] = by_symbol[row["symbol"]]
        self.change_decision(index, bind)

    def test_synthetic_cannot_claim_live_credit(self):
        self.evidence["synthetic_only"] = False
        with self.assertRaisesRegex(RuntimeError, "LIVE_SOURCE_REQUIRED"):
            self.evaluate()

    def test_stale_morning_official_source(self):
        self.replace_source(0, lambda b: b["source_provenance"].update(retrieval_timestamp="2026-01-01T00:00:00Z"))
        with self.assertRaisesRegex(RuntimeError, "OFFICIAL_SOURCE_INVALID"):
            self.evaluate()

    def test_future_morning_official_source(self):
        self.replace_source(0, lambda b: b["source_provenance"].update(retrieval_timestamp="2099-01-01T00:00:00Z"))
        with self.assertRaisesRegex(RuntimeError, "OFFICIAL_SOURCE_INVALID"):
            self.evaluate()

    def test_eod_wrong_price_date(self):
        def mutate(bundle):
            bundle["eod_close_records"][0]["trade_date"] = "2026-10-02"
            bundle["eod_close_content_sha256"] = sha256(bundle["eod_close_records"])
        self.replace_source(3, mutate)
        with self.assertRaisesRegex(RuntimeError, "EOD_PRICE_SOURCE_INVALID"):
            self.evaluate()

    def test_eod_invalid_price(self):
        def mutate(bundle):
            bundle["eod_close_records"][0]["close"] = 0
            bundle["eod_close_content_sha256"] = sha256(bundle["eod_close_records"])
        self.replace_source(3, mutate)
        with self.assertRaisesRegex(RuntimeError, "EOD_PRICE_INVALID"):
            self.evaluate()

    def test_yahoo_or_mis_fallback_rejected(self):
        self.replace_source(3, lambda b: b["official_source_transformation"]["datasets"][0].update(endpoint="https://mis.twse.com.tw/stock/api/getStockInfo.jsp"))
        with self.assertRaisesRegex(RuntimeError, "UNAPPROVED_SOURCE"):
            self.evaluate()

    def test_raw_response_tamper(self):
        bundle = read_object(self.evidence["runs"][1]["source_bundle"]["path"])
        receipt = read_object(bundle["sources"][0]["receipt_path"])
        path = Path(receipt["raw_path"])
        original = path.read_bytes()
        self.addCleanup(path.write_bytes, original)
        path.write_bytes(original + b" ")
        with self.assertRaisesRegex(RuntimeError, "RAW_HASH_MISMATCH"):
            self.evaluate()

    def test_trade_intent_execution_rejected(self):
        self.change_decision(1, lambda d: d.update(trade_intent_status="EXECUTED"))
        with self.assertRaisesRegex(RuntimeError, "INTRADAY_EXECUTION"):
            self.evaluate()


class CER081CreditHardeningTests(unittest.TestCase):
    def test_each_partial_gate_zero_credit(self):
        for key, value in (("report_runtime_status", "PARTIAL_VALID"), ("market_intraday_price_gate", "BLOCKED_EXTERNAL"),
            ("full_intraday_decision_status", "BLOCKED_EXTERNAL"), ("full_production_acceptance", "NOT_ALLOWED")):
            runs = scheduled_runs_fixture()
            runs[1][key] = value
            with self.subTest(key=key):
                self.assertEqual(len(cer081.normalize_scheduled_runs(runs)), 11)

    def test_nested_gate_zero_credit(self):
        runs = scheduled_runs_fixture()
        runs[1]["material"] = {"decision_state": {"decision": {"report_runtime_status": "PARTIAL_VALID"}}}
        self.assertEqual(len(cer081.normalize_scheduled_runs(runs)), 11)

    def test_conflicting_event_rejected(self):
        runs = scheduled_runs_fixture()
        runs[1]["event"] = "workflow_dispatch"
        self.assertEqual(len(cer081.normalize_scheduled_runs(runs)), 11)

    def test_twelve_schedules_cannot_override_current_governance(self):
        dependency = read_object(report.ROOT / "config/RATE_EXTERNAL_PRODUCTION_DEPENDENCIES.json")["dependencies"][0]
        with patch("src.cer081_unattended_soak._verify_model_freeze", return_value={"status": "PASS"}):
            summary = cer081.build_cer081_artifacts(cer080_persisted=cer080_persisted_fixture(),
                scheduled_runs_raw=scheduled_runs_fixture(), current_dependency=dependency,
                rate_source_url=cer081.APPROVED_RATE_SOURCE_URL, token_present=False)["RATE_CER081_SOAK_SUMMARY.json"]
        self.assertEqual(summary["successful_cadence_runs"], 0)
        self.assertEqual(summary["completion_status"], "HOLD:BLOCKED_EXTERNAL")
        self.assertEqual(summary["CER081_FULL_PRODUCTION_SOAK"], "BLOCKED_EXTERNAL")

    def test_current_cli_cannot_omit_governance(self):
        import tempfile
        with tempfile.TemporaryDirectory(prefix="c81-") as directory:
            root = Path(directory)
            atomic_write_json(root / "previous.json", cer080_persisted_fixture())
            atomic_write_json(root / "runs.json", {"runs": scheduled_runs_fixture()})
            completed = subprocess.run([sys.executable, "-B", str(report.ROOT / "scripts/run_cer081_unattended_soak_acceptance.py"),
                "--cer080-persisted-evidence", str(root / "previous.json"), "--scheduled-runs-json", str(root / "runs.json"),
                "--output-dir", str(root / "out")], cwd=report.ROOT, capture_output=True, text=True)
            self.assertNotEqual(completed.returncode, 0)
            summary = read_object(root / "out/RATE_CER081_SOAK_SUMMARY.json")
            self.assertEqual(summary["successful_cadence_runs"], 0)
            self.assertEqual(summary["completion_status"], "HOLD:BLOCKED_EXTERNAL")


if __name__ == "__main__":
    unittest.main()
