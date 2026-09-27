import copy
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch

import src.cer080_multi_day_continuity as cer080
from tests.test_cer079_full_day_chain import cer076_source_bundle_fixture, cer078_persisted_fixture


class CER080MultiDayContinuityTests(unittest.TestCase):
    def setUp(self):
        self.state = Path("data/production/test-cer080")
        shutil.rmtree(self.state, ignore_errors=True)
        self.bundle = cer076_source_bundle_fixture()
        self.cer078 = cer078_persisted_fixture()
        self.patch = patch("src.cer080_multi_day_continuity._verify_model_freeze", return_value={"status": "PASS"})
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        shutil.rmtree(self.state, ignore_errors=True)

    def test_next_trading_day_skips_weekend(self):
        resolved = cer080.resolve_next_trading_day("2026-09-18")
        self.assertEqual(resolved["next_trading_date"], "2026-09-21")
        self.assertEqual(resolved["weekend_days_skipped"], 2)
        self.assertEqual(resolved["status"], "PASS")

    def test_previous_final_state_binding(self):
        binding = cer080.validate_previous_final_state(self.cer078)
        self.assertEqual(binding["status"], "PASS")
        self.assertEqual(binding["state_entry"]["current_state_id"], cer080.PREVIOUS_STATE_ID)

    def test_multi_day_acceptance_artifacts_pass(self):
        arts = cer080.build_cer080_artifacts(source_bundle=self.bundle, cer078_persisted=self.cer078, state_root=self.state, run_head_sha="h", actions_run_id="r", actions_job_id="j", event_name="workflow_dispatch")
        self.assertEqual(arts["RATE_CER080_NEXT_TRADING_DAY_RESOLUTION_EVIDENCE.json"]["next_trading_date"], "2026-09-21")
        self.assertEqual(arts["RATE_CER080_CROSS_DAY_PREVIOUS_STATE_BINDING_EVIDENCE.json"]["cross_day_previous_state_binding"], "PASS")
        self.assertEqual(arts["RATE_CER080_PERSISTENT_STATE_CARRY_FORWARD_EVIDENCE.json"]["persistent_state_carry_forward"], "PASS")
        self.assertEqual(arts["RATE_CER080_NEW_DAY_BASELINE_INTEGRITY_EVIDENCE.json"]["new_day_baseline_integrity"], "PASS")
        self.assertEqual(arts["RATE_CER080_PORTFOLIO_CARRY_FORWARD_EVIDENCE.json"]["portfolio_carry_forward"], "PASS")
        self.assertEqual(arts["RATE_CER080_TRANSACTION_LEDGER_CROSS_DAY_EVIDENCE.json"]["transaction_ledger_cross_day_continuity"], "PASS")
        self.assertEqual(arts["RATE_CER080_RANKING_MODEL_CARRY_FORWARD_EVIDENCE.json"]["ranking_model_carry_forward"], "PASS")
        self.assertEqual(arts["RATE_CER080_DRY_RUN_A.json"]["decision_state_id"], arts["RATE_CER080_DRY_RUN_B.json"]["decision_state_id"])
        self.assertEqual(arts["RATE_CER080_DRY_RUN_A.json"]["decision_state_hash"], arts["RATE_CER080_DRY_RUN_B.json"]["decision_state_hash"])
        self.assertEqual(arts["RATE_CER080_PERSIST_RESULT_EVIDENCE.json"]["first_persist_new_record_count"], 1)
        self.assertEqual(arts["RATE_CER080_REPLAY_IDEMPOTENCY_EVIDENCE.json"]["replay_new_record_count"], 0)
        self.assertEqual(arts["RATE_CER080_WEEKEND_GATE_EVIDENCE.json"]["weekend_gate"], "PASS")
        self.assertEqual(arts["RATE_CER080_HOLIDAY_GATE_EVIDENCE.json"]["holiday_gate"], "PASS")
        self.assertEqual(arts["RATE_CER080_STALE_DATA_GATE_EVIDENCE.json"]["stale_data_gate"], "PASS")
        self.assertEqual(arts["RATE_CER080_MISSED_SCHEDULER_RECOVERY_EVIDENCE.json"]["missed_scheduler_recovery"], "PASS")
        self.assertEqual(arts["RATE_CER080_CONCURRENCY_EVIDENCE.json"]["concurrency_protection"], "PASS")
        self.assertEqual(arts["RATE_CER080_CROSS_DAY_REPLAY_EVIDENCE.json"]["cross_day_replay"], "PASS")
        self.assertEqual(arts["RATE_CER080_FAILURE_GATE_EVIDENCE.json"]["failure_closed_behavior"], "PASS")

    def test_wrong_previous_state_is_blocked(self):
        bad = copy.deepcopy(self.cer078)
        bad["persist_result"]["state_entry"]["current_state_id"] = "rate-state-wrong"
        with self.assertRaisesRegex(RuntimeError, "DAY_N_FINAL_STATE_BINDING_FAIL"):
            cer080.validate_previous_final_state(bad)


if __name__ == "__main__":
    unittest.main()
