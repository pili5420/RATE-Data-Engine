import unittest

from src.cer081_scheduler_actual_timing import (
    SchedulerActualTimingError,
    build_actual_timing_evidence,
    summarize_actual_timing_evidence,
)


class SchedulerActualTimingTests(unittest.TestCase):
    def api(self):
        return {
            "id": 123,
            "event": "schedule",
            "path": ".github/workflows/rate_production_0930_scheduler.yml",
            "head_sha": "a" * 40,
            "run_attempt": 1,
            "created_at": "2026-11-05T01:31:00Z",
            "run_started_at": "2026-11-05T01:31:10Z",
        }

    def evidence(self):
        return build_actual_timing_evidence(
            self.api(),
            cadence="09:30",
            trading_date="2026-11-05",
            event_schedule="30 1 * * 1-5",
            workflow_path=".github/workflows/rate_production_0930_scheduler.yml",
            expected_run_id="123",
            expected_head_sha="a" * 40,
        )

    def test_direct_actions_timing_pass(self):
        e = self.evidence()
        self.assertEqual(e["scheduler_start_delay_seconds"], 70)
        self.assertFalse(e["nearest_slot_inference_used"])
        self.assertFalse(e["post_hoc_date_inference_used"])

    def test_manual_event_rejected(self):
        api = self.api()
        api["event"] = "workflow_dispatch"
        with self.assertRaisesRegex(SchedulerActualTimingError, "NOT_SCHEDULE_EVENT"):
            build_actual_timing_evidence(
                api,
                cadence="09:30",
                trading_date="2026-11-05",
                event_schedule="30 1 * * 1-5",
                workflow_path=".github/workflows/rate_production_0930_scheduler.yml",
                expected_run_id="123",
                expected_head_sha="a" * 40,
            )

    def test_wrong_event_schedule_rejected(self):
        with self.assertRaisesRegex(SchedulerActualTimingError, "EVENT_CRON_MISMATCH"):
            build_actual_timing_evidence(
                self.api(),
                cadence="09:30",
                trading_date="2026-11-05",
                event_schedule="0 0 * * *",
                workflow_path=".github/workflows/rate_production_0930_scheduler.yml",
                expected_run_id="123",
                expected_head_sha="a" * 40,
            )

    def test_retry_rejected(self):
        api = self.api()
        api["run_attempt"] = 2
        with self.assertRaisesRegex(SchedulerActualTimingError, "RETRY_NOT_ALLOWED"):
            build_actual_timing_evidence(
                api,
                cadence="09:30",
                trading_date="2026-11-05",
                event_schedule="30 1 * * 1-5",
                workflow_path=".github/workflows/rate_production_0930_scheduler.yml",
                expected_run_id="123",
                expected_head_sha="a" * 40,
            )

    def test_summary_fails_closed_when_timing_missing(self):
        run = {"workflow_run_id": "123", "trading_date": "2026-11-05", "cadence": "09:30"}
        s = summarize_actual_timing_evidence([run])
        self.assertEqual(s["actual_timing_evidence"], "FAIL")
        self.assertEqual(s["actual_timing_missing_or_invalid_count"], 1)

    def test_summary_binds_exact_run(self):
        run = {
            "workflow_run_id": "123",
            "trading_date": "2026-11-05",
            "cadence": "09:30",
            "run_head_sha": "a" * 40,
            "scheduler_actual_timing": self.evidence(),
        }
        s = summarize_actual_timing_evidence([run])
        self.assertEqual(s["actual_timing_evidence"], "PASS")
        self.assertEqual(s["delayed_execution_blocking_count"], 0)

    def test_summary_recomputes_delay_from_actions_timestamp(self):
        evidence = self.evidence()
        evidence["scheduler_start_delay_seconds"] = 0
        run = {"workflow_run_id": "123", "trading_date": "2026-11-05",
               "cadence": "09:30", "run_head_sha": "a" * 40,
               "scheduler_actual_timing": evidence}
        result = summarize_actual_timing_evidence([run])
        self.assertEqual(result["actual_timing_evidence"], "FAIL")
        self.assertEqual(result["actual_timing_missing_or_invalid_count"], 1)

    def test_summary_rejects_wrong_run_head(self):
        run = {"workflow_run_id": "123", "trading_date": "2026-11-05",
               "cadence": "09:30", "run_head_sha": "b" * 40,
               "scheduler_actual_timing": self.evidence()}
        result = summarize_actual_timing_evidence([run])
        self.assertEqual(result["actual_timing_evidence"], "FAIL")


if __name__ == "__main__":
    unittest.main()
