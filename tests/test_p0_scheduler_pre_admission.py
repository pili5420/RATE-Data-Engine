from __future__ import annotations

from copy import deepcopy
from datetime import timedelta
from pathlib import Path
import unittest

from src.cer081_scheduler_actual_timing import (
    CADENCE_CRONS, CADENCE_WORKFLOWS, expected_slot_utc,
    build_actual_timing_evidence,
)
from scripts.enforce_p0_scheduler_admission import (
    qualify_schedule_before_sources, SchedulerPreAdmissionBlocked,
)

SHA = "a" * 40


def make_evidence(cadence="19:30", job_delay=900, run_delay=1):
    day = "2026-11-17"
    nominal = expected_slot_utc(day, cadence)
    run = {
        "id": 42, "event": "schedule", "path": CADENCE_WORKFLOWS[cadence],
        "head_sha": SHA, "run_attempt": 1,
        "created_at": nominal.isoformat(),
        "run_started_at": (nominal + timedelta(seconds=run_delay)).isoformat(),
    }
    job = {
        "id": 43, "run_id": 42, "name": "production-" + cadence.replace(":", ""),
        "started_at": (nominal + timedelta(seconds=job_delay)).isoformat(),
    }
    return build_actual_timing_evidence(
        run, cadence=cadence, trading_date=day,
        event_schedule=CADENCE_CRONS[cadence],
        workflow_path=CADENCE_WORKFLOWS[cadence],
        expected_run_id="42", expected_head_sha=SHA,
        job_api=job, expected_job_id="43", expected_job_name=job["name"])


def check(evidence, cadence="19:30", **kw):
    return qualify_schedule_before_sources(
        evidence, cadence=cadence, trading_date="2026-11-17",
        run_id="42", head_sha=SHA, job_id="43",
        job_name="production-" + cadence.replace(":", ""), **kw)


class AdmissionTests(unittest.TestCase):
    def test_exact_boundary_for_every_cadence(self):
        for cadence in CADENCE_CRONS:
            for delay in (899.9, 900):
                with self.subTest(cadence=cadence, delay=delay):
                    self.assertEqual(check(make_evidence(cadence, delay), cadence)["admission"], "PASS")
            with self.subTest(cadence=cadence, delay=900.1):
                with self.assertRaisesRegex(SchedulerPreAdmissionBlocked,
                                            "P0_SCHEDULER_START_DELAY_EXCEEDED_900S"):
                    check(make_evidence(cadence, 900.1), cadence)

    def test_failed_run_even_if_job_api_is_present(self):
        with self.assertRaisesRegex(SchedulerPreAdmissionBlocked, "START_DELAY"):
            check(make_evidence(run_delay=901, job_delay=901))

    def test_missing_or_invalid_job_rejected(self):
        evidence = make_evidence()
        for field, value in (
            ("github_job_timestamp_status", "INVALID"),
            ("github_job_started_at", None),
            ("github_job_id", "44"),
            ("github_job_timestamp_provenance", None),
            ("observability_status", "FAIL"),
        ):
            with self.subTest(field=field):
                bad = deepcopy(evidence)
                bad["p0_scheduler_diagnostics"][field] = value
                with self.assertRaises(SchedulerPreAdmissionBlocked):
                    check(bad)

    def test_wrong_run_identity_retry_and_date_rejected(self):
        for key, value in (
            ("workflow_run_id", "99"),
            ("run_head_sha", "b" * 40),
            ("trading_date", "2026-11-16"),
            ("run_attempt", 2),
            ("event_name", "workflow_dispatch"),
            ("event_schedule", "0 0 * * *"),
            ("blocking_delay_seconds", 901),
        ):
            with self.subTest(key=key):
                bad = make_evidence()
                bad[key] = value
                with self.assertRaises(SchedulerPreAdmissionBlocked):
                    check(bad)

    def test_missing_evidence_and_false_late_flag(self):
        bad = make_evidence()
        bad.pop("p0_scheduler_diagnostics")
        with self.assertRaises(SchedulerPreAdmissionBlocked):
            check(bad)
        bad = make_evidence()
        bad["delayed_execution_blocking"] = True
        with self.assertRaises(SchedulerPreAdmissionBlocked):
            check(bad)

    def test_schedule_gate_precedes_source_in_authorized_workflows(self):
        # Do not rewrite frozen intraday workflows just to satisfy this test.
        # The four-cadence 900s admission logic is still verified by the
        # exact-boundary test above; intraday wiring is explicitly NOT qualified.
        root = Path(__file__).resolve().parents[1]
        for cadence in ("07:30", "19:30"):
            slot = cadence.replace(":", "")
            workflow = (root / f".github/workflows/rate_production_{slot}_scheduler.yml").read_text(encoding="utf-8")
            capture = workflow.index("- name: Capture CER-081 scheduler actual-timing evidence")
            admit = workflow.index("- name: Enforce P0 scheduler admission before any source acquisition")
            acquire = workflow.index("- name: Build official production source bundle")
            self.assertTrue(capture < admit < acquire)
            self.assertIn("python scripts/enforce_p0_scheduler_admission.py", workflow[admit:acquire])
            self.assertIn("github.event_name == 'schedule'", workflow[admit:acquire])
            self.assertNotIn("continue-on-error: true", workflow[admit:acquire])

    def test_intraday_frozen_workflows_have_unresolved_admission_gap(self):
        root = Path(__file__).resolve().parents[1]
        for cadence in ("09:30", "12:00"):
            with self.subTest(cadence=cadence):
                slot = cadence.replace(":", "")
                workflow = (root / f".github/workflows/rate_production_{slot}_scheduler.yml").read_text(encoding="utf-8")
                self.assertIn("- name: Capture CER-081 scheduler actual-timing evidence", workflow)
                self.assertIn("- name: Build official production source bundle", workflow)
                self.assertNotIn("- name: Enforce P0 scheduler admission before any source acquisition", workflow)
                self.assertNotIn("continue-on-error: true", workflow)
                self.assertIn("--public-official-partial", workflow)


if __name__ == "__main__":
    unittest.main()
