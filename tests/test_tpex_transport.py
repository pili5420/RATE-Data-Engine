import hashlib
import json
import unittest
from http.client import IncompleteRead
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request

from src.sources import tpex
from src.sources import tpex_transport as transport
from scripts import build_production_source_bundle_from_official as builder


class Response:
    status = 200
    def __init__(self, body=b'[{"SecuritiesCompanyCode":"6274","Date":"1151002"}]', length=None):
        self.body = body
        self.headers = {"Content-Type": "application/json", "Date": "Fri, 02 Oct 2026 08:00:00 GMT"}
        if length is not None:
            self.headers["Content-Length"] = str(length)
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def read(self):
        if isinstance(self.body, Exception):
            raise self.body
        return self.body


class TPExTransportTests(unittest.TestCase):
    def fetch(self, outcomes, endpoint=tpex.CURRENT_DAILY_ENDPOINT):
        with patch.object(transport.time, "sleep") as sleep, patch.object(tpex, "urlopen", side_effect=outcomes) as opener:
            result = tpex._resilient_tpex_current_daily_json(endpoint)
        return result, opener, sleep

    def test_incomplete_read_then_complete(self):
        result, opener, sleep = self.fetch([Response(IncompleteRead(b'[{', 50)), Response()])
        self.assertEqual(result["diagnostics"]["attempt_count"], 2)
        first, second = result["diagnostics"]["attempts"]
        self.assertEqual(first["response_bytes"], 2)
        self.assertEqual(first["exception_type"], "IncompleteRead")
        self.assertNotIn("body_sha256", first)
        self.assertEqual(second["parse_status"], "PASS")
        sleep.assert_called_once_with(1)
        self.assertTrue(all(call.args[0].full_url == tpex.CURRENT_DAILY_ENDPOINT for call in opener.call_args_list))

    def test_truncated_json_then_complete(self):
        result, _, _ = self.fetch([Response(b'[{"x":"'), Response()])
        self.assertEqual(result["diagnostics"]["attempts"][0]["exception_type"], "JSONDecodeError")
        self.assertEqual(result["diagnostics"]["parse_status"], "PASS")

    def test_all_bounded_failures_fail_closed_without_hash(self):
        for failure in (IncompleteRead(b'[{', 10), b'[{"x":"'):
            with self.subTest(failure=repr(failure)), patch.object(tpex, "urlopen", side_effect=[Response(failure) for _ in range(3)]) as opener, patch.object(transport.time, "sleep") as sleep:
                with self.assertRaises(transport.TPExJSONTransportError) as caught:
                    tpex.TPExAdapter().fetch_daily()
                evidence = caught.exception.diagnostics
                self.assertEqual(evidence["attempt_count"], 3)
                self.assertEqual(evidence["final_blocking_reason"], "TPEX_CURRENT_DAILY_RETRIEVAL_FAILED")
                self.assertFalse(evidence["fallback_used"])
                self.assertEqual(opener.call_count, 3)
                self.assertEqual([c.args[0] for c in sleep.call_args_list], [1, 2])
                self.assertTrue(all("body_sha256" not in a for a in evidence["attempts"]))

    def test_retryable_http_statuses(self):
        for code in (408, 429, 500, 502, 503, 504, 599):
            with self.subTest(code=code):
                result, opener, _ = self.fetch([HTTPError(tpex.CURRENT_DAILY_ENDPOINT, code, "error", {}, None), Response()])
                self.assertEqual(opener.call_count, 2)
                self.assertEqual(result["diagnostics"]["attempts"][0]["http_status"], code)

    def test_non_retryable_http_fails_immediately(self):
        with patch.object(tpex, "urlopen", side_effect=HTTPError(tpex.CURRENT_DAILY_ENDPOINT, 403, "denied", {}, None)) as opener, patch.object(transport.time, "sleep") as sleep:
            with self.assertRaises(transport.TPExJSONTransportError):
                tpex.TPExAdapter().fetch_daily()
            self.assertEqual(opener.call_count, 1)
            sleep.assert_not_called()

    def test_structurally_invalid_complete_payload_fails_immediately(self):
        for body in (b'{"unexpected":1}', b'[1]', b'null'):
            with self.subTest(body=body), patch.object(tpex, "urlopen", return_value=Response(body)) as opener, patch.object(transport.time, "sleep") as sleep:
                with self.assertRaises(transport.TPExJSONTransportError):
                    tpex.TPExAdapter().fetch_daily()
                self.assertEqual(opener.call_count, 1)
                sleep.assert_not_called()

    def test_existing_success_payload_unchanged(self):
        response = Response()
        result, opener, _ = self.fetch([response])
        self.assertEqual(result["payload"], json.loads(response.body))
        self.assertEqual(result["body_sha256"], hashlib.sha256(response.body).hexdigest())
        self.assertEqual(opener.call_count, 1)

    def test_run_37282858561_structural_replay(self):
        result, opener, _ = self.fetch([Response(IncompleteRead(b'x')), Response(IncompleteRead(b'y')), Response()])
        self.assertEqual(opener.call_count, 3)
        self.assertEqual(result["diagnostics"]["parse_status"], "PASS")

    def test_run_37295383164_structural_replay_includes_revenue(self):
        registry = json.loads(Path("config/RATE_PRODUCTION_OFFICIAL_SOURCE_REGISTRY_V1.json").read_text(encoding="utf-8"))["datasets"]
        for dataset, failure in (("tpex_market_daily", IncompleteRead(b'x')), ("tpex_fundamental_revenue", b'[{"x":"'), ("tpex_trading_metadata", IncompleteRead(b'x'))):
            entry = next(e for e in registry if e["dataset_id"] == dataset)
            with self.subTest(dataset=dataset), patch.object(tpex, "urlopen", side_effect=[Response(failure), Response()]), patch.object(builder.urllib.request, "urlopen", side_effect=[Response(failure), Response()]), patch.object(transport.time, "sleep"):
                result = builder.RegistryDatasetAdapter(entry, trading_date="2026-10-02").fetch()
                self.assertEqual(result["status"], "PASS")
                self.assertEqual(result["attempt_count"], 2)
                self.assertEqual(result["endpoint"], entry["endpoint"])

    def test_institutional_uses_same_helper_and_preserves_table(self):
        payload = {"tables": [{"fields": ["code"], "data": [["6274"]], "date": "115/10/02"}]}
        with patch.object(tpex, "build_opener") as factory, patch.object(transport.time, "sleep"):
            factory.return_value.open.side_effect = [Response(IncompleteRead(b'{')), Response(json.dumps(payload).encode())]
            result = tpex._resilient_tpex_daily_json(tpex.INSTITUTIONAL_DAILY_ENDPOINT, {"date": "115/10/02"})
        self.assertEqual(result["payload"], payload)
        self.assertEqual(result["diagnostics"]["attempt_count"], 2)
        self.assertEqual(result["diagnostics"]["response_field_names"], ["code"])
        self.assertEqual(result["diagnostics"]["http_date"], "Fri, 02 Oct 2026 08:00:00 GMT")

    def test_content_length_mismatch_and_empty_response_retry(self):
        for response in (Response(length=1000), Response(b''), Response(b'[]')):
            result, opener, _ = self.fetch([response, Response()])
            self.assertEqual(opener.call_count, 2)
            self.assertEqual(result["diagnostics"]["parse_status"], "PASS")

    def test_total_budget_exhaustion_does_not_start_another_request(self):
        with patch.object(transport.time, "monotonic", side_effect=[0, 0, 0, 96]), patch.object(tpex, "urlopen", side_effect=IncompleteRead(b'x')) as opener, patch.object(transport.time, "sleep") as sleep:
            with self.assertRaises(transport.TPExJSONTransportError):
                tpex.TPExAdapter().fetch_daily()
            self.assertEqual(opener.call_count, 1)
            sleep.assert_not_called()

    def test_slow_chunked_body_respects_attempt_deadline(self):
        class SlowResponse(Response):
            def read1(self, size):
                return b'['
        with patch.object(transport.time, "monotonic", side_effect=[0, 0, 0, 0, 31, 96]), patch.object(tpex, "urlopen", return_value=SlowResponse()) as opener, patch.object(transport.time, "sleep"):
            with self.assertRaises(transport.TPExJSONTransportError) as caught:
                tpex.TPExAdapter().fetch_daily()
        self.assertEqual(caught.exception.diagnostics["exception_type"], "TimeoutError")
        self.assertEqual(caught.exception.diagnostics["response_bytes"], 1)
        self.assertEqual(opener.call_args.kwargs["timeout"], 30)

    def test_diagnostics_have_required_fields_and_no_attempt_carryover(self):
        result, _, _ = self.fetch([Response(IncompleteRead(b'x')), Response()])
        for attempt in result["diagnostics"]["attempts"]:
            for key in ("attempt", "started_at", "completed_at", "http_status", "response_bytes", "content_length_header", "exception_type", "parse_status", "retry_reason"):
                self.assertIn(key, attempt)
        self.assertIsNone(result["diagnostics"]["exception_type"])
        self.assertIsNone(result["diagnostics"]["retry_reason"])

    def test_connection_reset_and_timeout_are_bounded(self):
        for exc in (ConnectionResetError("reset"), TimeoutError("timeout")):
            with self.subTest(exc=type(exc).__name__):
                result, _, _ = self.fetch([exc, Response()])
                self.assertEqual(result["diagnostics"]["attempts"][0]["exception_type"], type(exc).__name__)
                self.assertEqual(result["diagnostics"]["attempt_count"], 2)

    def test_blocked_registry_path_retains_evidence_and_does_not_write(self):
        entries = json.loads(Path("config/RATE_PRODUCTION_OFFICIAL_SOURCE_REGISTRY_V1.json").read_text(encoding="utf-8"))["datasets"]
        root = Path("artifacts/test_tpex_transport_no_mutation")
        root.mkdir(parents=True, exist_ok=True)
        try:
            sentinels = [root / name for name in ("RATE_PRODUCTION_STATE_LATEST.json", "RATE_PRODUCTION_SOURCE_BUNDLE_LATEST.json", "portfolio.json", "ledger.json")]
            for file in sentinels:
                file.write_bytes(b'unchanged')
            for dataset in ("tpex_market_daily", "tpex_fundamental_revenue", "tpex_trading_metadata", "tpex_institutional"):
                entry = next(e for e in entries if e["dataset_id"] == dataset)
                with patch.object(tpex, "urlopen", side_effect=IncompleteRead(b'x')), patch.object(builder.urllib.request, "urlopen", side_effect=IncompleteRead(b'x')), patch.object(tpex, "build_opener") as factory, patch.object(transport.time, "sleep"):
                    factory.return_value.open.side_effect = IncompleteRead(b'x')
                    result = builder.RegistryDatasetAdapter(entry, trading_date="2026-10-02").fetch()
                self.assertEqual(result["status"], "BLOCKED")
                self.assertEqual(result["attempt_count"], 3)
                self.assertFalse(result["fallback_used"])
                self.assertNotIn("body_sha256", result)
            self.assertCountEqual(list(root.iterdir()), sentinels)
            self.assertTrue(all(file.read_bytes() == b'unchanged' for file in sentinels))
        finally:
            for file in root.iterdir():
                file.unlink()
            root.rmdir()
