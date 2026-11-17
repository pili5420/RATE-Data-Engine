"""Offline P0 diagnostic regression; no official-source network or production writes."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.full_market_catalogue import build_catalogue, CLASSIFICATION_ENDPOINTS, LISTING_ENDPOINTS, CatalogueTransportError
from src.p0_source_diagnostics import new_receipt, write_evidence
from src.cer081_scheduler_actual_timing import (CADENCE_CRONS, CADENCE_WORKFLOWS,
    build_actual_timing_evidence, expected_slot_utc, summarize_actual_timing_evidence)
from scripts.build_phase2_production_source import build_phase2_bundle
from scripts.publish_production_state_latest import publish_state
from datetime import timedelta


DAY = "2026-11-17"
HEADER = ["Security Code & Security Name", "ISIN Code", "Date Listed", "Market", "Industrial Group", "CFICode", "Remarks"]


def fixture_fetch(*, dates=None, missing=False, schema=False, secret=""):
    dates = dates or {"TWSE": DAY, "TPEX": DAY}
    def fetch(endpoint, *, html=False):
        market = next(m for m in ("TWSE", "TPEX") if endpoint in (CLASSIFICATION_ENDPOINTS[m], LISTING_ENDPOINTS[m]))
        symbols = [str(1000 + index) for index in range(30 if market == "TWSE" else 30, 60 if market == "TWSE" else 90)]
        if html:
            date_label = "" if missing and market == "TWSE" else "Date Stock Updated:" + dates[market].replace("-", "/")
            rows = ([HEADER[:-1]] if schema and market == "TWSE" else [HEADER]) + [["Stocks"]] + [
                [symbol + " Fixture", "TESTISIN" + symbol, "2000/01/01", "TWSE LISTED" if market == "TWSE" else "TPEx LISTED", "", "ESVUFR", ""] for symbol in symbols]
            body = (date_label + "<table>" + "".join("<tr>" + "".join("<td>" + cell + "</td>" for cell in row) + "</tr>" for row in rows) + "</table>" + secret).encode("big5")
        else:
            key = "公司代號" if market == "TWSE" else "SecuritiesCompanyCode"
            body = json.dumps([{key: symbol} for symbol in symbols]).encode()
        return body, {"endpoint": endpoint, "http_status": 200,
            "content_type": "text/html; charset=big5" if html else "application/json",
            "response_bytes": len(body), "body_sha256": hashlib.sha256(body).hexdigest(),
            "retrieved_at": "2026-11-16T16:01:00Z", "fallback_used": False}
    return fetch


class SourceDiagnosticsTests(unittest.TestCase):
    def run_case(self, fetcher, expected_error=None):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "run" / "RATE_P0_SOURCE_DIAGNOSTIC_EVIDENCE.json"
            if expected_error:
                with self.assertRaisesRegex(Exception, expected_error):
                    build_catalogue(DAY, fetcher=fetcher, diagnostic_output=path)
            else:
                catalogue = build_catalogue(DAY, fetcher=fetcher, diagnostic_output=path)
                self.assertEqual(catalogue["validation_status"], "PASS")
            return json.loads(path.read_text(encoding="utf-8")), path.read_text(encoding="utf-8")

    def test_valid_both_markets_and_utc_taipei_boundary(self):
        evidence, _ = self.run_case(fixture_fetch())
        self.assertEqual([r["market_id"] for r in evidence["market_receipts"]], ["TWSE", "TPEX"])
        for receipt in evidence["market_receipts"]:
            self.assertEqual(receipt["parsed_date"], DAY)
            self.assertEqual(receipt["freshness_decision"], "PASS")
            self.assertEqual(receipt["hash_scope"], "COMPLETE_RESPONSE")
            self.assertEqual(receipt["actual_execution_timestamp_utc"], "2026-11-16T16:01:00Z")

    def test_delayed_and_future_dates_fail_closed(self):
        for source_date in ("2026-11-16", "2026-11-18"):
            with self.subTest(source_date=source_date):
                evidence, _ = self.run_case(fixture_fetch(dates={"TWSE": source_date, "TPEX": DAY}), "STALE_OR_FUTURE_CATALOGUE")
                receipt = evidence["market_receipts"][0]
                self.assertEqual(receipt["freshness_decision"], "BLOCK")
                self.assertEqual(receipt["failure_reason"], "SOURCE_DATE_MISMATCH")
                self.assertEqual(receipt["parsed_date"], source_date)

    def test_missing_malformed_date_and_schema_fail_closed(self):
        for fetcher, error, reason in (
            (fixture_fetch(missing=True), "CATALOGUE_ASOF_MISSING", "ASOF_MISSING"),
            (fixture_fetch(dates={"TWSE": "2026/13/40", "TPEX": DAY}), "month must be", "DATE_PARSE_FAILED"),
            (fixture_fetch(schema=True), "CATALOGUE_SCHEMA_INVALID", "SCHEMA_INVALID"),
        ):
            with self.subTest(reason=reason):
                evidence, _ = self.run_case(fetcher, error)
                receipt = evidence["market_receipts"][0]
                self.assertEqual(receipt["freshness_decision"], "BLOCK")
                self.assertEqual(receipt["failure_reason"], reason)
                self.assertEqual(receipt["hash_scope"], "COMPLETE_RESPONSE")

    def test_partial_transport_and_secret_exclusion(self):
        secret = "SENSITIVE_TOKEN_123"
        def fetch(endpoint, *, html=False):
            raise CatalogueTransportError("TRANSPORT", [{"http_status": 200, "content_type": "text/html", "partial_body_sha256": hashlib.sha256(b"abc").hexdigest(), "partial_response_bytes": 3, "exception_message": secret}])
        evidence, text = self.run_case(fetch, "TRANSPORT")
        self.assertEqual(evidence["market_receipts"][0]["hash_scope"], "PARTIAL_BYTES")
        self.assertEqual(evidence["market_receipts"][0]["freshness_decision"], "BLOCK")
        self.assertNotIn(secret, text)
        self.assertNotIn("exception_message", text)
        _, text = self.run_case(fixture_fetch(secret=secret))
        self.assertNotIn(secret, text)
        self.assertNotIn("TESTISIN", text)

    def test_serialization_and_write_fail_closed(self):
        receipt = new_receipt("TWSE", DAY, "2026-11-17T00:00:00Z")
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "diagnostic.json"
            with self.assertRaises(ValueError):
                write_evidence(path, [{**receipt, "market_id": "UNKNOWN"}], DAY)
            self.assertFalse(path.exists())
            with patch("src.full_market_catalogue.write_evidence", side_effect=OSError("disk failed")):
                with self.assertRaisesRegex(RuntimeError, "SOURCE_DIAGNOSTIC_PERSISTENCE_FAILED"):
                    build_catalogue(DAY, fetcher=fixture_fetch(), diagnostic_output=path)

    def test_missing_predecessor_and_evidence_write_fail_closed(self):
        with tempfile.TemporaryDirectory() as root:
            output = Path(root) / "bundle.json"
            evidence_path = Path(root) / "ingestion.json"
            with patch("scripts.build_phase2_production_source.main_authority", return_value={}), patch(
                "scripts.build_phase2_production_source.latest_predecessor", side_effect=RuntimeError("PREDECESSOR_MISSING")):
                result = build_phase2_bundle(trading_date=DAY, cadence="19:30", output=output,
                    evidence_output=evidence_path, state_root=Path(root) / "state", history_root=Path(root) / "history")
            self.assertEqual(result["validation_status"], "FAIL_CLOSED")
            self.assertEqual(result["publication_decision"], "BLOCK")
            self.assertFalse(output.exists())
            with patch("scripts.build_phase2_production_source.main_authority", return_value={}), patch(
                "scripts.build_phase2_production_source.latest_predecessor", return_value=(None, None, {"state": {}})), patch(
                "scripts.build_phase2_production_source.materialize_full_market", side_effect=RuntimeError("SOURCE_DIAGNOSTIC_PERSISTENCE_FAILED")):
                result = build_phase2_bundle(trading_date=DAY, cadence="19:30", output=output,
                    evidence_output=evidence_path, state_root=Path(root) / "state", history_root=Path(root) / "history")
            self.assertEqual(result["validation_status"], "FAIL_CLOSED")
            self.assertEqual(result["blocking_reason"], "SOURCE_DIAGNOSTIC_PERSISTENCE_FAILED")
            self.assertFalse(output.exists())

    def test_upload_failure_precedes_publication(self):
        workflow = (Path(__file__).resolve().parents[1] / ".github/workflows/rate_production_1930_scheduler.yml").read_text(encoding="utf-8")
        upload = workflow.index("- name: Upload P0 source diagnostic evidence")
        publish = workflow.index("- name: Publish live production state pointer")
        self.assertLess(upload, publish)
        self.assertIn("if: ${{ success() && (github.event_name == 'schedule' || inputs.phase2)", workflow[upload:publish])
        self.assertIn("if-no-files-found: error", workflow[upload:publish])
        self.assertIn("- name: Upload blocked P0 source diagnostic evidence", workflow[upload:publish])
        self.assertIn("steps.source_acquisition.outcome == 'failure'", workflow[upload:publish])
        self.assertEqual(workflow[upload:publish].count("if-no-files-found: error"), 2)
        self.assertNotIn("github.event_name != 'push'", workflow[upload:publish])
        self.assertNotIn("continue-on-error: true", workflow[upload:publish])

    def test_production_run_binding_and_offline_qualification(self):
        receipt = new_receipt("TWSE", DAY, "2026-11-17T00:00:00Z")
        valid = {"GITHUB_ACTIONS": "true", "GITHUB_REPOSITORY": "pili5420/RATE-Data-Engine",
                 "GITHUB_REF": "refs/heads/main", "GITHUB_SHA": "a" * 40,
                 "GITHUB_RUN_ID": "42", "GITHUB_RUN_ATTEMPT": "1",
                 "GITHUB_EVENT_NAME": "schedule", "GITHUB_JOB": "production-1930",
                 "ACTIONS_JOB_ID": "43"}
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "diagnostic.json"
            with patch.dict(os.environ, valid, clear=True):
                write_evidence(path, [receipt], DAY)
            binding = json.loads(path.read_text())["run_binding"]
            self.assertEqual(binding["qualification"], "PRODUCTION_QUALIFIED")
            self.assertEqual(binding["workflow_job_id"], "43")
            for key, bad in (("GITHUB_REPOSITORY", "other/repo"), ("GITHUB_SHA", "bad"),
                             ("GITHUB_RUN_ID", ""), ("GITHUB_RUN_ATTEMPT", "2"),
                             ("GITHUB_EVENT_NAME", ""),
                             ("GITHUB_JOB", "wrong"), ("ACTIONS_JOB_ID", ""),
                             ("GITHUB_REF", "refs/heads/other"), ("GITHUB_ACTIONS", "")):
                with self.subTest(key=key), patch.dict(os.environ, {**valid, key: bad}, clear=True):
                    with self.assertRaisesRegex(ValueError, "DIAGNOSTIC_PRODUCTION_BINDING_INVALID"):
                        write_evidence(path, [receipt], DAY)
            with patch.dict(os.environ, {}, clear=True):
                write_evidence(path, [receipt], DAY)
            self.assertEqual(json.loads(path.read_text())["run_binding"]["qualification"], "OFFLINE_TEST")

    def test_exception_text_is_excluded_from_adjacent_evidence(self):
        failure = RuntimeError("SECRET_TOKEN_ABC")
        failure.primary_failure_reason = "SECRET_TOKEN_ABC"
        captured = []
        with patch("scripts.build_phase2_production_source.main_authority", side_effect=failure), patch(
                "scripts.build_phase2_production_source.atomic_write_json", side_effect=lambda path, value: captured.append(value)):
            source = build_phase2_bundle(trading_date=DAY, cadence="19:30", output="unused",
                evidence_output="unused", state_root="unused", history_root="unused")
        self.assertEqual(source["validation_status"], "FAIL_CLOSED")
        self.assertNotIn("SECRET_TOKEN_ABC", json.dumps(captured))
        captured.clear()
        with patch("scripts.publish_production_state_latest.read_object", side_effect=failure), patch(
                "scripts.publish_production_state_latest.atomic_write_json", side_effect=lambda path, value: captured.append(value)):
            state = publish_state(persist_evidence_path="unused", trading_date=DAY, cadence="19:30",
                workflow_run_id="42", workflow_job_id="43", evidence_output="unused", state_root="unused",
                event_name="schedule", commit_sha="a" * 40, ref="refs/heads/main")
        self.assertEqual(state["publication_decision"], "BLOCK")
        self.assertNotIn("SECRET_TOKEN_ABC", json.dumps(captured))
        self.assertEqual(state["blocking_reason"], "LIVE_STATE_PUBLICATION_FAILED")

    def test_source_publication_write_and_preflight_failures(self):
        for boundary in ("bundle_write", "preflight"):
            with self.subTest(boundary=boundary):
                writes = []
                def writer(path, value):
                    if boundary == "bundle_write" and str(path) == "bundle":
                        raise OSError("SECRET_TOKEN_ABC")
                    writes.append(str(path))
                with patch("scripts.build_phase2_production_source.main_authority", return_value={}), patch(
                    "scripts.build_phase2_production_source.latest_predecessor", return_value=(None, None, {"state": {}})), patch(
                    "scripts.build_phase2_production_source.materialize_full_market", return_value=({}, {})), patch(
                    "scripts.build_phase2_production_source.bind_input_material", return_value={}), patch(
                    "scripts.build_phase2_production_source.bundle_from_material", return_value={}), patch(
                    "scripts.build_phase2_production_source.prepare_bundle_state", return_value={}), patch(
                    "scripts.build_phase2_production_source.preflight_manifest", side_effect=RuntimeError("SECRET_TOKEN_ABC") if boundary == "preflight" else None), patch(
                    "scripts.build_phase2_production_source.atomic_write_json", side_effect=writer):
                    evidence = build_phase2_bundle(trading_date=DAY, cadence="19:30", output="bundle",
                        evidence_output="evidence", state_root="unused", history_root="unused")
                self.assertEqual(evidence["publication_decision"], "BLOCK")
                self.assertIsNotNone(evidence["publication_intent_at"])
                self.assertIsNotNone(evidence["publication_decision_at"])
                self.assertEqual(evidence["source_bundle_write_result"], "FAILED" if boundary == "bundle_write" else "PERSISTED")
                self.assertNotIn("SECRET_TOKEN_ABC", json.dumps(evidence))


class SchedulerDiagnosticsTests(unittest.TestCase):
    def evidence(self, delay, job=None):
        slot = expected_slot_utc(DAY, "07:30")
        api = {"id": 42, "event": "schedule", "path": CADENCE_WORKFLOWS["07:30"],
               "head_sha": "a" * 40, "run_attempt": 1,
               "created_at": (slot + timedelta(seconds=1)).isoformat(),
               "run_started_at": (slot + timedelta(seconds=delay)).isoformat()}
        return build_actual_timing_evidence(api, cadence="07:30", trading_date=DAY,
            event_schedule=CADENCE_CRONS["07:30"], workflow_path=CADENCE_WORKFLOWS["07:30"],
            expected_run_id="42", expected_head_sha="a" * 40, job_api=job,
            expected_job_id="43", expected_job_name="production-0730")

    def test_boundary_and_missing_job(self):
        for delay, blocked in ((899.9, False), (900, False), (900.1, True)):
            with self.subTest(delay=delay):
                evidence = self.evidence(delay)
                self.assertEqual(evidence["delayed_execution_blocking"], blocked)
                self.assertEqual(evidence["p0_scheduler_diagnostics"]["observability_status"], "FAIL")
                self.assertIsNone(evidence["p0_scheduler_diagnostics"]["schedule_triggered_at"])
                self.assertEqual(evidence["p0_scheduler_diagnostics"]["schedule_triggered_at_unavailable_reason"], "NOT_EXPOSED")
        job = {"id": 43, "name": "production-0730", "run_id": 42, "started_at": "2026-11-16T23:45:01Z"}
        self.assertEqual(self.evidence(900, job)["p0_scheduler_diagnostics"]["observability_status"], "PASS")

    def test_invalid_job_and_missing_run_fail(self):
        self.assertEqual(self.evidence(900, {"run_id": 42, "started_at": "bad"})["p0_scheduler_diagnostics"]["observability_status"], "FAIL")
        self.assertEqual(summarize_actual_timing_evidence([{"workflow_run_id": "42", "trading_date": DAY, "cadence": "07:30"}])["actual_timing_evidence"], "FAIL")

    def test_wrong_job_identity_fails_diagnostic_qualification(self):
        slot = expected_slot_utc(DAY, "07:30")
        run = {"id": 42, "event": "schedule", "path": CADENCE_WORKFLOWS["07:30"],
               "head_sha": "a" * 40, "run_attempt": 1,
               "created_at": slot.isoformat(), "run_started_at": slot.isoformat()}
        job = {"id": 43, "name": "production-0730", "run_id": 42, "started_at": slot.isoformat()}
        for bad in ({**job, "id": 44}, {**job, "name": "other"}):
            evidence = build_actual_timing_evidence(run, cadence="07:30", trading_date=DAY,
                event_schedule=CADENCE_CRONS["07:30"], workflow_path=CADENCE_WORKFLOWS["07:30"],
                expected_run_id="42", expected_head_sha="a" * 40, job_api=bad,
                expected_job_id="43", expected_job_name="production-0730")
            self.assertEqual(evidence["p0_scheduler_diagnostics"]["observability_status"], "FAIL")


if __name__ == "__main__":
    unittest.main()
