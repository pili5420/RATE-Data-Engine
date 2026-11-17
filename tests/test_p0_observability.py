"""Offline P0 diagnostic regression; no official-source network or production writes."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.full_market_catalogue import build_catalogue, CLASSIFICATION_ENDPOINTS, LISTING_ENDPOINTS, CatalogueTransportError
from src.p0_source_diagnostics import new_receipt, write_evidence
from src.cer081_scheduler_actual_timing import (CADENCE_CRONS, CADENCE_WORKFLOWS,
    build_actual_timing_evidence, expected_slot_utc, summarize_actual_timing_evidence)
from scripts.build_phase2_production_source import build_phase2_bundle
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
        self.assertIn("if: ${{ success() && github.event_name != 'push'", workflow[upload:publish])
        self.assertIn("if-no-files-found: error", workflow[upload:publish])
        self.assertIn("- name: Upload blocked P0 source diagnostic evidence", workflow[upload:publish])
        self.assertNotIn("continue-on-error: true", workflow[upload:publish])


class SchedulerDiagnosticsTests(unittest.TestCase):
    def evidence(self, delay, job=None):
        slot = expected_slot_utc(DAY, "07:30")
        api = {"id": 42, "event": "schedule", "path": CADENCE_WORKFLOWS["07:30"],
               "head_sha": "a" * 40, "run_attempt": 1,
               "created_at": (slot + timedelta(seconds=1)).isoformat(),
               "run_started_at": (slot + timedelta(seconds=delay)).isoformat()}
        return build_actual_timing_evidence(api, cadence="07:30", trading_date=DAY,
            event_schedule=CADENCE_CRONS["07:30"], workflow_path=CADENCE_WORKFLOWS["07:30"],
            expected_run_id="42", expected_head_sha="a" * 40, job_api=job)

    def test_boundary_and_missing_job(self):
        for delay, blocked in ((899.9, False), (900, False), (900.1, True)):
            with self.subTest(delay=delay):
                evidence = self.evidence(delay)
                self.assertEqual(evidence["delayed_execution_blocking"], blocked)
                self.assertEqual(evidence["p0_scheduler_diagnostics"]["observability_status"], "FAIL")
                self.assertIsNone(evidence["p0_scheduler_diagnostics"]["schedule_triggered_at"])
                self.assertEqual(evidence["p0_scheduler_diagnostics"]["schedule_triggered_at_unavailable_reason"], "NOT_EXPOSED")
        job = {"run_id": 42, "started_at": "2026-11-16T23:45:01Z"}
        self.assertEqual(self.evidence(900, job)["p0_scheduler_diagnostics"]["observability_status"], "PASS")

    def test_invalid_job_and_missing_run_fail(self):
        self.assertEqual(self.evidence(900, {"run_id": 42, "started_at": "bad"})["p0_scheduler_diagnostics"]["observability_status"], "FAIL")
        self.assertEqual(summarize_actual_timing_evidence([{"workflow_run_id": "42", "trading_date": DAY, "cadence": "07:30"}])["actual_timing_evidence"], "FAIL")


if __name__ == "__main__":
    unittest.main()
