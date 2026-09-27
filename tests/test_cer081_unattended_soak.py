
import copy
import json
import unittest
from pathlib import Path
from unittest.mock import patch

import src.cer081_unattended_soak as cer081

CER080_PERSISTED = Path("artifacts/remote-36310435776/RATE_CER080_PERSIST_RESULT_EVIDENCE/RATE_CER080_PERSIST_RESULT_EVIDENCE.json")


def cer080_persisted_fixture():
    if CER080_PERSISTED.exists():
        return json.loads(CER080_PERSISTED.read_text(encoding="utf-8"))
    return {"validation_status": "PASS", "current_state_id": cer081.PREVIOUS_STATE_ID, "current_state_hash": cer081.PREVIOUS_STATE_HASH, "persist_result": {"state_entry": {"current_state_id": cer081.PREVIOUS_STATE_ID, "decision_payload_hash": cer081.PREVIOUS_STATE_HASH, "trading_date": cer081.PREVIOUS_TRADING_DATE, "cadence": cer081.PREVIOUS_CADENCE, "previous_state_resolution": "PERSISTED_PRODUCTION_STATE"}}}


def scheduled_runs_fixture():
    runs=[]
    for d in ["2026-09-21","2026-09-22","2026-09-23"]:
        for c in cer081.CADENCES:
            runs.append({"event_name":"schedule","workflow_run_id":f"run-{d}-{c}","job_id":f"job-{d}-{c}","trading_date":d,"cadence":c,"validation_status":"PASS","publish_result":"PASS","previous_state_id":"prev","current_state_id":"cur","previous_state_hash":"ph","current_state_hash":"ch"})
    return runs


class CER081UnattendedSoakTests(unittest.TestCase):
    def setUp(self):
        self.cer080 = cer080_persisted_fixture()
        self.patch = patch("src.cer081_unattended_soak._verify_model_freeze", return_value={"status": "PASS", "changed_files": []})
        self.patch.start()

    def tearDown(self):
        self.patch.stop()

    def test_source_ssot_requires_approved_urls(self):
        self.assertEqual(cer081.production_source_ssot(cer081.APPROVED_RATE_SOURCE_URL)["production_source_ssot"], "PASS")
        self.assertEqual(cer081.production_source_ssot("")["production_source_ssot"], "FAIL")

    def test_scheduler_definition_coverage(self):
        evidence = cer081.scheduler_definition_evidence()
        self.assertEqual(evidence["scheduler_coverage"], "PASS")
        self.assertEqual(set(evidence["definitions"]), set(cer081.CADENCES))

    def test_no_scheduled_evidence_holds_not_passes(self):
        artifacts = cer081.build_cer081_artifacts(cer080_persisted=self.cer080, scheduled_runs_raw=[], rate_source_url=cer081.APPROVED_RATE_SOURCE_URL, run_head_sha="h", actions_run_id="r", actions_job_id="j", event_name="push")
        summary = artifacts["RATE_CER081_SOAK_SUMMARY.json"]
        self.assertEqual(summary["final_result"], "FAIL")
        self.assertIn("AWAITING_3_TRADING_DAYS_12_SCHEDULED_RUNS", summary["remaining_blockers"])
        self.assertEqual(summary["completion_status"], "HOLD:AWAITING_SCHEDULED_SOAK_EVIDENCE")

    def test_scheduled_evidence_can_pass_gate(self):
        artifacts = cer081.build_cer081_artifacts(cer080_persisted=self.cer080, scheduled_runs_raw=scheduled_runs_fixture(), rate_source_url=cer081.APPROVED_RATE_SOURCE_URL, run_head_sha="h", actions_run_id="r", actions_job_id="j", event_name="schedule")
        summary = artifacts["RATE_CER081_SOAK_SUMMARY.json"]
        self.assertEqual(summary["final_result"], "PASS")
        self.assertEqual(summary["trading_days_tested"], 3)
        self.assertEqual(summary["successful_cadence_runs"], 12)
        self.assertEqual(summary["duplicate_production_record_count"], 0)

    def test_failure_gates_preserve_previous_state(self):
        gates = cer081.source_failure_gates()["source_failure_gates"]
        self.assertEqual(gates["production_source_url_missing"]["publish"], "BLOCKED")
        self.assertEqual(gates["invalid_json"]["previous_production_state_preserved"], "PASS")
        self.assertEqual(gates["previous_state_unavailable_or_corrupted"]["silent_fallback"], "NO")

    def test_wrong_predecessor_is_blocked(self):
        bad = copy.deepcopy(self.cer080)
        bad["persist_result"]["state_entry"]["current_state_id"] = "rate-state-wrong"
        with self.assertRaisesRegex(RuntimeError, "CER080_PREDECESSOR_BINDING_FAIL"):
            cer081.validate_cer080_predecessor(bad)


if __name__ == "__main__":
    unittest.main()
