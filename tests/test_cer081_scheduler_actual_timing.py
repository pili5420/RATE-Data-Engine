import unittest
from datetime import timedelta

from src.cer081_scheduler_actual_timing import (
    SchedulerActualTimingError,
    CADENCE_CRONS,
    CADENCE_WORKFLOWS,
    build_actual_timing_evidence,
    expected_slot_utc,
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

    def test_timing_cli_direct_execution_imports_src(self):
        # Run the same direct script entrypoint used by the production workflow.
        import subprocess
        import sys
        from pathlib import Path

        repo_root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [sys.executable, str(repo_root / "scripts/build_scheduler_actual_timing_evidence.py"), "--help"],
            cwd=repo_root, capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--github-run-json", result.stdout)

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

    def test_exact_and_fractional_blocking_delay_boundaries(self):
        slot = expected_slot_utc("2026-11-05", "09:30")
        for delay, blocking in ((900, 0), (900.9, 1)):
            with self.subTest(delay=delay):
                api = self.api()
                api["created_at"] = (slot + timedelta(seconds=60)).isoformat()
                api["run_started_at"] = (slot + timedelta(seconds=delay)).isoformat()
                evidence = build_actual_timing_evidence(
                    api, cadence="09:30", trading_date="2026-11-05",
                    event_schedule=CADENCE_CRONS["09:30"],
                    workflow_path=CADENCE_WORKFLOWS["09:30"],
                    expected_run_id="123", expected_head_sha="a" * 40,
                )
                result = summarize_actual_timing_evidence([{
                    "workflow_run_id": "123", "trading_date": "2026-11-05",
                    "cadence": "09:30", "run_head_sha": "a" * 40,
                    "scheduler_actual_timing": evidence,
                }])
                self.assertEqual(evidence["scheduler_start_delay_seconds"], delay)
                self.assertEqual(result["actual_timing_evidence"], "PASS")
                self.assertEqual(result["delayed_execution_blocking_count"], blocking)
                self.assertEqual(result["max_scheduler_delay_seconds"], delay)
        self.assertIs(type(self.evidence()["scheduler_start_delay_seconds"]), int)

    def test_fractional_negative_delay_is_rejected_before_truncation(self):
        slot = expected_slot_utc("2026-11-05", "09:30")
        api = self.api()
        api["created_at"] = (slot - timedelta(seconds=1)).isoformat()
        api["run_started_at"] = (slot - timedelta(seconds=0.5)).isoformat()
        with self.assertRaisesRegex(SchedulerActualTimingError, "NEGATIVE_DELAY"):
            build_actual_timing_evidence(
                api, cadence="09:30", trading_date="2026-11-05",
                event_schedule=CADENCE_CRONS["09:30"],
                workflow_path=CADENCE_WORKFLOWS["09:30"],
                expected_run_id="123", expected_head_sha="a" * 40,
            )
        # A prior truncated artifact must also fail during independent replay.
        evidence = self.evidence()
        evidence.update(actions_created_at=api["created_at"],
                        actions_run_started_at=api["run_started_at"],
                        scheduler_start_delay_seconds=0)
        result = summarize_actual_timing_evidence([{
            "workflow_run_id": "123", "trading_date": "2026-11-05",
            "cadence": "09:30", "run_head_sha": "a" * 40,
            "scheduler_actual_timing": evidence,
        }])
        self.assertEqual(result["actual_timing_evidence"], "FAIL")
        self.assertEqual(result["actual_timing_missing_or_invalid_count"], 1)


if __name__ == "__main__":
    unittest.main()
