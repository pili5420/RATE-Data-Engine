"""Synthetic GitHub responses only: no API calls or Production credit."""
from __future__ import annotations

import copy
from datetime import timedelta
import hashlib
import io
import json
from pathlib import Path
import unittest
from zipfile import ZipFile, ZIP_DEFLATED

from src.cer081_scheduler_actual_timing import (
    CADENCE_CRONS, CADENCE_WORKFLOWS, build_actual_timing_evidence, expected_slot_utc,
)
from src.route_b_timing_provenance import (
    REPOSITORY, REPOSITORY_ID, WORKFLOW_IDS, TIMING_NAME, TimingProvenanceError,
    verify_timing_provenance,
)


class Reader:
    def __init__(self, data):
        self.data = data

    def get(self, path):
        if path not in self.data:
            raise TimingProvenanceError("SYNTHETIC_API_UNAVAILABLE")
        return self.data[path]


def encoded(value):
    return json.dumps(value, sort_keys=True).encode("utf-8")


def fixture(delay=120):
    run_id, job_id, artifact_id = 123, 456, 789
    cadence, day, sha = "09:30", "2026-11-06", "a" * 40
    slot = expected_slot_utc(day, cadence)
    created = (slot + timedelta(seconds=60)).isoformat()
    started = (slot + timedelta(seconds=delay)).isoformat()
    path = CADENCE_WORKFLOWS[cadence]
    run_api = {
        "id": run_id, "run_attempt": 1, "event": "schedule", "path": path,
        "head_sha": sha, "workflow_id": WORKFLOW_IDS[cadence], "created_at": created,
        "run_started_at": started, "conclusion": "success",
        "repository": {"id": REPOSITORY_ID, "full_name": REPOSITORY},
        "head_repository": {"id": REPOSITORY_ID},
    }
    timing = build_actual_timing_evidence(
        run_api, cadence=cadence, trading_date=day,
        event_schedule=CADENCE_CRONS[cadence], workflow_path=path,
        expected_run_id=str(run_id), expected_head_sha=sha,
    )
    raw = json.dumps(timing, sort_keys=True).encode("utf-8")
    buf = io.BytesIO()
    with ZipFile(buf, "w", ZIP_DEFLATED) as z:
        z.writestr(TIMING_NAME, raw)
    archive = buf.getvalue()
    artifact = {
        "id": artifact_id, "name": f"RATE_CER081_SCHEDULER_ACTUAL_TIMING_0930_{run_id}",
        "expired": False, "digest": "sha256:" + hashlib.sha256(archive).hexdigest(),
        "workflow_run": {"id": run_id, "repository_id": REPOSITORY_ID,
                         "head_repository_id": REPOSITORY_ID, "head_sha": sha},
    }
    row = {"workflow_run_id": str(run_id), "workflow_job_id": str(job_id),
           "trading_date": day, "cadence": cadence, "run_head_sha": sha,
           "official_event": "schedule", "scheduler_actual_timing": timing}
    base = f"/actions/runs/{run_id}"
    data = {
        base: encoded(run_api),
        base + "/attempts/1": encoded(run_api),
        base + "/attempts/1/jobs?per_page=100": encoded({"total_count": 1,
            "jobs": [{"id": job_id, "name": "production-0930", "run_attempt": 1,
                      "run_id": run_id, "head_sha": sha,
                      "workflow_name": "RATE Production 09:30 Recurring Scheduler",
                      "started_at": (slot + timedelta(seconds=delay)).isoformat(),
                      "completed_at": (slot + timedelta(seconds=delay+60)).isoformat(),
                      "conclusion": "success"}]}),
        base + "/artifacts?per_page=100": encoded({"total_count": 1, "artifacts": [artifact]}),
        f"/actions/artifacts/{artifact_id}/zip": archive,
    }
    return row, data


class TimingProvenanceTests(unittest.TestCase):
    def test_runtime_verifiers_receive_actions_read_token(self):
        workflows = Path(__file__).resolve().parents[1] / ".github" / "workflows"
        for filename, step in (
            ("rate_route_b_acceptance_ledger_collector.yml", "Collect scheduled run into acceptance ledger"),
            ("rate_route_b_current_production_finalization.yml", "Build finalization package"),
        ):
            text = (workflows / filename).read_text(encoding="utf-8")
            self.assertIn("actions: read", text)
            self.assertIn("- name: " + step + "\n        env:\n          GH_TOKEN: ${{ github.token }}", text)

    def check(self, row, data):
        return verify_timing_provenance(row, reader=Reader(data))

    def test_authentic_source_and_exact_900_pass(self):
        for delay in (120, 900):
            with self.subTest(delay=delay):
                row, data = fixture(delay)
                receipt = self.check(row, data)
                self.assertEqual(receipt["delay_seconds"], delay)
                self.assertEqual(receipt["workflow_job_id"], 456)

    def test_pre_admission_and_durable_event_shapes_are_both_bound(self):
        row, data = fixture()
        row["event"] = row.pop("official_event")
        self.assertEqual(self.check(row, data)["workflow_run_id"], "123")
        row["official_event"] = "workflow_dispatch"
        with self.assertRaisesRegex(TimingProvenanceError, "LEDGER_EVENT_INVALID"):
            self.check(row, data)

    def test_coordinated_ledger_timestamp_delay_and_hash_rewrite_fails(self):
        row, data = fixture()
        original = self.check(row, data)
        altered = copy.deepcopy(row)
        slot = expected_slot_utc(row["trading_date"], row["cadence"])
        altered["scheduler_actual_timing"].update(
            actions_created_at=slot.isoformat().replace("+00:00", "Z"),
            actions_run_started_at=slot.isoformat().replace("+00:00", "Z"),
            scheduler_start_delay_seconds=0)
        altered["scheduler_timing_provenance"]={"archive_sha256": "0" * 64,
                                               "timing_sha256": "0" * 64}
        with self.assertRaisesRegex(TimingProvenanceError, "LEDGER_SOURCE_MISMATCH"):
            self.check(altered, data)
        self.assertEqual(original["delay_seconds"], 120)

    def test_timestamp_or_delay_only_fails(self):
        for field, value in (("actions_run_started_at", "2026-11-06T01:30:00Z"),
                             ("scheduler_start_delay_seconds", 0)):
            row, data = fixture()
            row["scheduler_actual_timing"][field] = value
            with self.subTest(field=field), self.assertRaises(TimingProvenanceError):
                self.check(row, data)

    def test_wrong_ledger_run_job_sha_date_cadence_and_event_fail(self):
        for field, value in (("workflow_run_id", "124"), ("workflow_job_id", "457"),
                             ("run_head_sha", "b" * 40), ("trading_date", "2026-11-05"),
                             ("cadence", "12:00"), ("official_event", "workflow_dispatch")):
            row, data = fixture()
            row[field] = value
            with self.subTest(field=field), self.assertRaises(TimingProvenanceError):
                self.check(row, data)

    def test_wrong_server_identity_workflow_event_attempt_head_fail(self):
        for field, value in (("repository", {"id": 9, "full_name": REPOSITORY}),
                             ("head_repository", {"id": 9}),
                             ("workflow_id", 777), ("path", "wrong.yml"),
                             ("event", "workflow_dispatch"), ("run_attempt", 2),
                             ("head_sha", "b" * 40)):
            row, data = fixture()
            base = "/actions/runs/123"
            server = json.loads(data[base])
            server[field] = value
            data[base] = encoded(server)
            with self.subTest(field=field), self.assertRaises(TimingProvenanceError):
                self.check(row, data)

    def test_wrong_job_and_relevant_job_time_fail(self):
        for field, value in (("id", 999), ("run_attempt", 2),
                             ("name", "production-1930"),
                             ("started_at", "2026-11-06T01:29:00Z")):
            row, data = fixture()
            key = "/actions/runs/123/attempts/1/jobs?per_page=100"
            jobs = json.loads(data[key]); jobs["jobs"][0][field] = value
            data[key] = encoded(jobs)
            with self.subTest(field=field), self.assertRaises(TimingProvenanceError):
                self.check(row, data)

    def test_artifact_missing_expired_duplicate_wrong_run_or_digest_fail(self):
        for field, value in (("expired", True), ("digest", "sha256:" + "0" * 64),
                             ("workflow_run", {"id": 999, "repository_id": REPOSITORY_ID,
                                               "head_sha": "a" * 40})):
            row, data = fixture(); key = "/actions/runs/123/artifacts?per_page=100"
            body = json.loads(data[key]); body["artifacts"][0][field] = value
            data[key] = encoded(body)
            with self.subTest(field=field), self.assertRaises(TimingProvenanceError):
                self.check(row, data)
        row, data = fixture(); del data["/actions/runs/123/artifacts?per_page=100"]
        with self.assertRaises(TimingProvenanceError):
            self.check(row, data)
        row, data = fixture(); key = "/actions/runs/123/artifacts?per_page=100"
        body = json.loads(data[key]); body["artifacts"].append(body["artifacts"][0]); body["total_count"] = 2
        data[key] = encoded(body)
        with self.assertRaises(TimingProvenanceError):
            self.check(row, data)

    def test_raw_artifact_byte_change_and_api_unavailable_fail(self):
        row, data = fixture(); data["/actions/artifacts/789/zip"] += b"tamper"
        with self.assertRaisesRegex(TimingProvenanceError, "DIGEST_MISMATCH"):
            self.check(row, data)
        row, data = fixture(); del data["/actions/runs/123"]
        with self.assertRaises(TimingProvenanceError):
            self.check(row, data)

    def test_over_900_and_negative_or_historical_date_fail(self):
        row, data = fixture(901)
        with self.assertRaisesRegex(TimingProvenanceError, "DELAY_BLOCKED"):
            self.check(row, data)
        row, data = fixture(); row["trading_date"]="2026-11-05"
        with self.assertRaises(TimingProvenanceError):
            self.check(row, data)


if __name__ == "__main__":
    unittest.main()
