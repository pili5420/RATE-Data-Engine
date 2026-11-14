"""Independent GitHub Actions timing replay for Route B scheduled runs."""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
from datetime import datetime, timezone
from urllib.parse import urlparse
from urllib.request import Request, build_opener, HTTPRedirectHandler
from zipfile import ZipFile, BadZipFile

from src.cer081_scheduler_actual_timing import (
    CADENCE_CRONS, CADENCE_WORKFLOWS, expected_slot_utc,
    summarize_actual_timing_evidence,
)

REPOSITORY = "pili5420/RATE-Data-Engine"
REPOSITORY_ID = 1370145728
WORKFLOW_IDS = {"07:30": 368174775, "09:30": 368386687,
                "12:00": 368386683, "19:30": 368386682}
API = "https://api.github.com/repos/" + REPOSITORY
TIMING_NAME = "RATE_CER081_SCHEDULER_ACTUAL_TIMING_EVIDENCE.json"
_ALLOWED_ACTIONS_PATHS = tuple(re.compile(pattern) for pattern in (
    r"/actions/runs/[1-9][0-9]*",
    r"/actions/runs/[1-9][0-9]*/attempts/1",
    r"/actions/runs/[1-9][0-9]*/attempts/1/jobs\?per_page=100",
    r"/actions/runs/[1-9][0-9]*/artifacts\?per_page=100",
    r"/actions/artifacts/[1-9][0-9]*/zip",
))


class TimingProvenanceError(RuntimeError):
    pass


def require(value, reason):
    if not value:
        raise TimingProvenanceError(reason)


class GitHubActionsReader:
    """GET-only transport; tests inject a reader and never open a connection."""

    def __init__(self, token=None):
        self.token = token if token is not None else os.environ.get("GH_TOKEN")

    def get(self, path):
        require(self.token, "TIMING_PROVENANCE_GITHUB_TOKEN_MISSING")
        require(isinstance(path, str) and any(p.fullmatch(path) for p in _ALLOWED_ACTIONS_PATHS),
                "TIMING_PROVENANCE_ENDPOINT_INVALID")
        req = Request(API + path, headers={
            "Accept": "application/vnd.github+json",
            "Authorization": "Bearer " + self.token,
            "X-GitHub-Api-Version": "2022-11-28",
        })
        try:
            # GitHub's archive endpoint redirects to a signed storage URL.
            # Never forward the repository token to that different host.
            class SafeRedirect(HTTPRedirectHandler):
                def redirect_request(self, request, fp, code, message, headers, newurl):
                    target = urlparse(newurl)
                    require(target.scheme == "https", "TIMING_PROVENANCE_REDIRECT_INVALID")
                    forwarded = {k: v for k, v in request.headers.items()
                                 if k.lower() != "authorization"}
                    return Request(newurl, headers=forwarded)

            with build_opener(SafeRedirect()).open(req, timeout=20) as response:
                require(response.status == 200, "TIMING_PROVENANCE_API_STATUS")
                return response.read()
        except Exception as exc:
            raise TimingProvenanceError("TIMING_PROVENANCE_API_UNAVAILABLE") from exc


def _json(reader, path):
    try:
        value = json.loads(reader.get(path))
    except (ValueError, TypeError) as exc:
        raise TimingProvenanceError("TIMING_PROVENANCE_API_JSON_INVALID") from exc
    require(isinstance(value, dict), "TIMING_PROVENANCE_API_OBJECT_REQUIRED")
    return value


def _utc(value):
    require(isinstance(value, str) and value, "TIMING_PROVENANCE_TIMESTAMP_MISSING")
    try:
        instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise TimingProvenanceError("TIMING_PROVENANCE_TIMESTAMP_INVALID") from exc
    require(instant.tzinfo is not None, "TIMING_PROVENANCE_TIMESTAMP_NAIVE")
    return instant.astimezone(timezone.utc)


def verify_scheduled_source_from_actions(*, run_id, cadence, trading_date, head_sha, reader=None):
    """Obtain original timing bytes from GitHub, then replay the full verifier."""
    reader = reader if reader is not None else GitHubActionsReader()
    run_id = str(run_id)
    require(run_id.isdecimal() and int(run_id) > 0 and cadence in CADENCE_CRONS,
            "TIMING_PROVENANCE_SOURCE_ID_INVALID")
    artifacts = _json(reader, f"/actions/runs/{run_id}/artifacts?per_page=100")
    require(artifacts.get("total_count") == len(artifacts.get("artifacts", []))
            and len(artifacts["artifacts"]) <= 100,
            "TIMING_PROVENANCE_ARTIFACTS_INCOMPLETE")
    name = f"RATE_CER081_SCHEDULER_ACTUAL_TIMING_{cadence.replace(':', '')}_{run_id}"
    matching = [a for a in artifacts["artifacts"] if a.get("name") == name]
    require(len(matching) == 1 and matching[0].get("expired") is False,
            "TIMING_PROVENANCE_ARTIFACT_MISSING_OR_EXPIRED")
    artifact = matching[0]
    artifact_id = artifact.get("id")
    require(type(artifact_id) is int and artifact_id > 0,
            "TIMING_PROVENANCE_ARTIFACT_ID_INVALID")
    archive = reader.get(f"/actions/artifacts/{artifact_id}/zip")
    require(artifact.get("digest") == "sha256:" + hashlib.sha256(archive).hexdigest(),
            "TIMING_PROVENANCE_ARTIFACT_DIGEST_MISMATCH")
    try:
        with ZipFile(io.BytesIO(archive)) as z:
            require(z.namelist() == [TIMING_NAME], "TIMING_PROVENANCE_ARTIFACT_MEMBERS_INVALID")
            timing = json.loads(z.read(TIMING_NAME))
    except (BadZipFile, KeyError, ValueError) as exc:
        raise TimingProvenanceError("TIMING_PROVENANCE_ARTIFACT_BYTES_INVALID") from exc
    jobs = _json(reader, f"/actions/runs/{run_id}/attempts/1/jobs?per_page=100")
    require(jobs.get("total_count") == len(jobs.get("jobs", []))
            and len(jobs["jobs"]) <= 100, "TIMING_PROVENANCE_JOBS_INCOMPLETE")
    matches = [j for j in jobs["jobs"] if j.get("name") == "production-" + cadence.replace(":", "")]
    require(len(matches) == 1 and type(matches[0].get("id")) is int,
            "TIMING_PROVENANCE_JOB_MISMATCH")
    row = {"workflow_run_id": run_id, "workflow_job_id": matches[0]["id"],
           "cadence": cadence, "trading_date": trading_date, "run_head_sha": head_sha,
           "event": "schedule", "scheduler_actual_timing": timing}
    return verify_timing_provenance(row, reader=reader)


def verify_timing_provenance(run, *, reader=None):
    """Re-fetch original server metadata and bytes; ledger fields confer no trust."""
    reader = reader if reader is not None else GitHubActionsReader()
    try:
        run_id = str(run["workflow_run_id"])
        job_id = int(run["workflow_job_id"])
        cadence = run["cadence"]
        day = run["trading_date"]
        sha = run["run_head_sha"]
        ledger_timing = run["scheduler_actual_timing"]
    except (KeyError, ValueError, TypeError) as exc:
        raise TimingProvenanceError("TIMING_PROVENANCE_LEDGER_BINDING_MISSING") from exc
    require(run_id.isdecimal() and int(run_id) > 0 and job_id > 0,
            "TIMING_PROVENANCE_RUN_JOB_ID_INVALID")
    require(cadence in CADENCE_CRONS and isinstance(sha, str) and len(sha) == 40,
            "TIMING_PROVENANCE_SLOT_OR_SHA_INVALID")
    require(isinstance(ledger_timing, dict), "TIMING_PROVENANCE_LEDGER_TIMING_MISSING")
    event_fields = [run[key] for key in ("event", "event_name", "official_event") if key in run]
    require(event_fields and all(value == "schedule" for value in event_fields),
            "TIMING_PROVENANCE_LEDGER_EVENT_INVALID")
    run_api = _json(reader, f"/actions/runs/{run_id}")
    attempt = _json(reader, f"/actions/runs/{run_id}/attempts/1")
    require(run_api.get("id") == int(run_id) and attempt.get("id") == int(run_id)
            and run_api.get("run_attempt") == attempt.get("run_attempt") == 1,
            "TIMING_PROVENANCE_RUN_ATTEMPT_MISMATCH")
    require(run_api.get("repository", {}).get("id") == REPOSITORY_ID
            and run_api.get("repository", {}).get("full_name") == REPOSITORY
            and run_api.get("head_repository", {}).get("id") == REPOSITORY_ID
            and attempt.get("repository", {}).get("id") == REPOSITORY_ID
            and attempt.get("repository", {}).get("full_name") == REPOSITORY
            and attempt.get("head_repository", {}).get("id") == REPOSITORY_ID,
            "TIMING_PROVENANCE_REPOSITORY_MISMATCH")
    path = CADENCE_WORKFLOWS[cadence]
    require(run_api.get("path") == attempt.get("path") == path
            and run_api.get("workflow_id") == attempt.get("workflow_id") == WORKFLOW_IDS[cadence],
            "TIMING_PROVENANCE_WORKFLOW_MISMATCH")
    require(run_api.get("event") == attempt.get("event") == "schedule"
            and run_api.get("head_sha") == attempt.get("head_sha") == sha,
            "TIMING_PROVENANCE_EVENT_OR_HEAD_MISMATCH")
    created = _utc(run_api.get("created_at"))
    started = _utc(run_api.get("run_started_at"))
    require(created == _utc(attempt.get("created_at"))
            and started == _utc(attempt.get("run_started_at")) and created <= started,
            "TIMING_PROVENANCE_API_TIMESTAMPS_MISMATCH")
    jobs = _json(reader, f"/actions/runs/{run_id}/attempts/1/jobs?per_page=100")
    require(jobs.get("total_count") == len(jobs.get("jobs", []))
            and len(jobs.get("jobs", [])) <= 100,
            "TIMING_PROVENANCE_JOBS_INCOMPLETE")
    matches = [j for j in jobs["jobs"] if j.get("id") == job_id]
    require(len(matches) == 1 and matches[0].get("name") == "production-" + cadence.replace(":", "")
            and matches[0].get("run_attempt") == 1
            and matches[0].get("run_id") == int(run_id)
            and matches[0].get("head_sha") == sha
            and matches[0].get("workflow_name") == f"RATE Production {cadence} Recurring Scheduler",
            "TIMING_PROVENANCE_JOB_MISMATCH")
    job = matches[0]
    require(_utc(job.get("started_at")) >= started
            and _utc(job.get("completed_at")) >= _utc(job.get("started_at")),
            "TIMING_PROVENANCE_JOB_TIMING_INVALID")
    require(run_api.get("conclusion") == attempt.get("conclusion") == "success"
            and job.get("conclusion") == "success",
            "TIMING_PROVENANCE_SOURCE_NOT_SUCCESS")
    artifacts = _json(reader, f"/actions/runs/{run_id}/artifacts?per_page=100")
    require(artifacts.get("total_count") == len(artifacts.get("artifacts", []))
            and len(artifacts.get("artifacts", [])) <= 100,
            "TIMING_PROVENANCE_ARTIFACTS_INCOMPLETE")
    name = f"RATE_CER081_SCHEDULER_ACTUAL_TIMING_{cadence.replace(':', '')}_{run_id}"
    matching = [a for a in artifacts["artifacts"] if a.get("name") == name]
    require(len(matching) == 1 and matching[0].get("expired") is False,
            "TIMING_PROVENANCE_ARTIFACT_MISSING_OR_EXPIRED")
    artifact = matching[0]
    require(artifact.get("workflow_run", {}).get("id") == int(run_id)
            and artifact.get("workflow_run", {}).get("repository_id") == REPOSITORY_ID
            and artifact.get("workflow_run", {}).get("head_repository_id") == REPOSITORY_ID
            and artifact.get("workflow_run", {}).get("head_sha") == sha,
            "TIMING_PROVENANCE_ARTIFACT_RUN_MISMATCH")
    artifact_id = artifact.get("id")
    require(type(artifact_id) is int and artifact_id > 0,
            "TIMING_PROVENANCE_ARTIFACT_ID_INVALID")
    archive = reader.get(f"/actions/artifacts/{artifact_id}/zip")
    archive_sha = hashlib.sha256(archive).hexdigest()
    require(artifact.get("digest") == "sha256:" + archive_sha,
            "TIMING_PROVENANCE_ARTIFACT_DIGEST_MISMATCH")
    try:
        with ZipFile(io.BytesIO(archive)) as z:
            names = z.namelist()
            require(names == [TIMING_NAME], "TIMING_PROVENANCE_ARTIFACT_MEMBERS_INVALID")
            original_bytes = z.read(TIMING_NAME)
            original = json.loads(original_bytes)
    except (BadZipFile, KeyError, ValueError) as exc:
        raise TimingProvenanceError("TIMING_PROVENANCE_ARTIFACT_BYTES_INVALID") from exc
    require(isinstance(original, dict)
            and json.dumps(original, sort_keys=True, separators=(",", ":"))
            == json.dumps(ledger_timing, sort_keys=True, separators=(",", ":")),
            "TIMING_PROVENANCE_LEDGER_SOURCE_MISMATCH")
    require(original.get("workflow_run_id") == run_id
            and original.get("run_attempt") == 1
            and original.get("run_head_sha") == sha
            and original.get("workflow_path") == path
            and original.get("event_name") == "schedule"
            and original.get("event_schedule") == CADENCE_CRONS[cadence]
            and original.get("cadence") == cadence
            and original.get("trading_date") == day
            and _utc(original.get("actions_created_at")) == created
            and _utc(original.get("actions_run_started_at")) == started,
            "TIMING_PROVENANCE_ORIGINAL_BINDING_MISMATCH")
    slot = expected_slot_utc(day, cadence)
    delay = (started - slot).total_seconds()
    require(delay >= 0 and delay <= 900 and original.get("blocking_delay_seconds") == 900
            and type(original.get("scheduler_start_delay_seconds")) in (int, float)
            and original.get("scheduler_start_delay_seconds") == delay,
            "TIMING_PROVENANCE_DELAY_BLOCKED")
    checked = summarize_actual_timing_evidence([run])
    require(checked["actual_timing_evidence"] == "PASS"
            and checked["delayed_execution_blocking_count"] == 0,
            "TIMING_PROVENANCE_SUMMARY_BLOCKED")
    return {"repository_id": REPOSITORY_ID, "workflow_run_id": run_id,
            "run_attempt": 1, "workflow_job_id": job_id, "artifact_id": artifact_id,
            "archive_sha256": archive_sha,
            "timing_sha256": hashlib.sha256(original_bytes).hexdigest(),
            "created_at": original["actions_created_at"],
            "run_started_at": original["actions_run_started_at"],
            "delay_seconds": original["scheduler_start_delay_seconds"]}
