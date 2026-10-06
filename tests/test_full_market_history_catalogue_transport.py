"""Mock-only catalogue transport regressions; no Production acceptance credit."""
import hashlib
import ast
from http.client import IncompleteRead
from io import BytesIO, StringIO
import json
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from scripts import bootstrap_full_market_history as cli
from src import full_market_catalogue as catalogue
from src import full_market_history as history
from tests.test_full_market_history import AUTHORITY


ENDPOINT = catalogue.LISTING_ENDPOINTS["TPEX"]
BODY = b'[{"SecuritiesCompanyCode":"4207"}]'


class Response(BytesIO):
    def __init__(self, body=BODY, *, endpoint=ENDPOINT, status=200, length=None, error=None):
        super().__init__(body)
        self.url, self.status, self.error = endpoint, status, error
        self.headers = {"Content-Type": "application/json", "Content-Length": str(len(body) if length is None else length)}

    def geturl(self):
        return self.url

    def getcode(self):
        return self.status

    def read(self):
        if self.error is not None:
            raise self.error
        return super().read()


def interrupted(body=b"partial", remaining=20, **kwargs):
    return Response(body, length=len(body) + remaining, error=IncompleteRead(body, remaining), **kwargs)


class CatalogueTransportTests(unittest.TestCase):
    def fetch(self, responses, endpoint=ENDPOINT, html=False):
        with patch.object(catalogue, "urlopen", side_effect=responses) as opener, \
                patch("time.sleep") as sleep:
            result = catalogue.fetch_receipt(endpoint, html=html)
        return result, opener, sleep

    def test_first_incomplete_then_full_response_passes_same_endpoint(self):
        (body, receipt), opener, sleep = self.fetch([interrupted(), Response()])
        self.assertEqual(body, BODY)
        self.assertEqual(receipt["attempt_count"], 2)
        self.assertEqual(receipt["body_sha256"], hashlib.sha256(BODY).hexdigest())
        self.assertEqual([c.args[0].full_url for c in opener.call_args_list], [ENDPOINT, ENDPOINT])
        sleep.assert_called_once_with(1)

    def test_retry_then_complete_1978_catalogue_and_new_plan_pass(self):
        # Mock schema fixtures only; never used as official Production material.
        responses = []
        for market, count, first_symbol in (("TWSE", 1085, 1000), ("TPEX", 893, 5000)):
            symbols = [str(first_symbol + i) for i in range(count)]
            listing_market = "TWSE LISTED" if market == "TWSE" else "TPEx LISTED"
            header = ["Security Code & Security Name", "ISIN Code", "Date Listed", "Market", "Industrial Group", "CFICode", "Remarks"]
            rows = [header, ["Stocks"]] + [[s + " Engineering", "ISIN" + s, "2000/01/01", listing_market, "", "ESVUFR", ""] for s in symbols]
            html = ("Date Stock Updated:2026/10/06<table>" + "".join("<tr>" + "".join("<td>" + c.replace("&", "&amp;") + "</td>" for c in row) + "</tr>" for row in rows) + "</table>").encode("big5")
            endpoint = catalogue.CLASSIFICATION_ENDPOINTS[market]
            if market == "TWSE":
                responses.append(interrupted(html, endpoint=endpoint))
            responses.append(Response(html, endpoint=endpoint))
            key = "\u516c\u53f8\u4ee3\u865f" if market == "TWSE" else "SecuritiesCompanyCode"
            responses.append(Response(json.dumps([{key: s} for s in symbols]).encode(), endpoint=catalogue.LISTING_ENDPOINTS[market]))
        with patch.object(catalogue, "urlopen", side_effect=responses) as opener, patch("time.sleep"):
            result = catalogue.build_catalogue("2026-10-06")
            new_plan = history.build_plan(result, AUTHORITY)
            self.assertTrue(history.validate_plan(new_plan))
        self.assertEqual(result["eligible_count"], 1978)
        self.assertEqual(opener.call_count, 5)
        self.assertEqual(result["validation_status"], "PASS")
        self.assertFalse(result["fallback_used"])
        self.assertEqual(result["markets"][0]["source_receipt"]["classification"]["attempt_count"], 2)
        self.assertEqual(sum(len(s["symbols"]) for s in new_plan["shards"]), 1978)

    def test_exact_run2_incomplete_counts_exhaust_bounded_attempts(self):
        partial = b"x" * 540280
        with patch.object(catalogue, "urlopen", side_effect=[interrupted(partial, 534132) for _ in range(3)]) as opener, \
                patch("time.sleep") as sleep:
            with self.assertRaisesRegex(RuntimeError, "CATALOGUE_TRANSPORT_FAILED") as caught:
                catalogue.fetch_receipt(ENDPOINT)
        evidence = caught.exception.catalogue_transport_evidence
        self.assertEqual(opener.call_count, 3)
        self.assertEqual([c.args[0] for c in sleep.call_args_list], [1, 2])
        self.assertEqual([e["attempt_number"] for e in evidence], [1, 2, 3])
        self.assertEqual(evidence[-1]["exception_message"], "IncompleteRead(540280 bytes read, 534132 more expected)")
        self.assertEqual(evidence[-1]["bytes_actually_read"], 540280)
        self.assertEqual(evidence[-1]["bytes_remaining"], 534132)
        self.assertEqual(evidence[-1]["expected_response_bytes"], 1074412)
        self.assertEqual(evidence[-1]["retry_decision"], "FAIL_CLOSED_RETRY_EXHAUSTED")

    def test_parseable_partial_html_never_reaches_parser(self):
        endpoint = catalogue.CLASSIFICATION_ENDPOINTS["TWSE"]
        partial = b"<html><table><tr><td>valid-looking</td></tr></table></html>"
        with patch.object(catalogue, "urlopen", side_effect=[interrupted(partial, endpoint=endpoint) for _ in range(3)]), \
                patch("time.sleep"), patch.object(catalogue, "parse_classification") as parser:
            with self.assertRaises(RuntimeError):
                catalogue.build_catalogue("2026-10-06")
        parser.assert_not_called()

    def test_wrong_redirect_after_retry_fails_closed_without_third_attempt(self):
        with patch.object(catalogue, "urlopen", side_effect=[interrupted(), Response(endpoint="https://mirror.invalid/")]) as opener, \
                patch("time.sleep"):
            with self.assertRaisesRegex(RuntimeError, "CATALOGUE_UNAPPROVED_REDIRECT") as caught:
                catalogue.fetch_receipt(ENDPOINT)
        self.assertEqual(opener.call_count, 2)
        self.assertEqual(caught.exception.catalogue_transport_evidence[-1]["final_url"], "https://mirror.invalid/")
        self.assertNotIn("body_sha256", caught.exception.catalogue_transport_evidence[-1])

    def test_http_error_from_unapproved_redirect_is_not_retried(self):
        with patch.object(catalogue, "urlopen", side_effect=HTTPError("https://mirror.invalid/", 503, "redirected", {}, None)) as opener, \
                patch("time.sleep") as sleep:
            with self.assertRaisesRegex(RuntimeError, "CATALOGUE_UNAPPROVED_REDIRECT"):
                catalogue.fetch_receipt(ENDPOINT)
        self.assertEqual(opener.call_count, 1)
        sleep.assert_not_called()

    def test_non_retriable_http_status_never_retries(self):
        for status in (400, 401, 403, 404, 410):
            with self.subTest(status=status), patch.object(catalogue, "urlopen", side_effect=HTTPError(ENDPOINT, status, "denied", {}, None)) as opener, \
                    patch("time.sleep") as sleep:
                with self.assertRaises(RuntimeError) as caught:
                    catalogue.fetch_receipt(ENDPOINT)
                self.assertEqual(opener.call_count, 1)
                sleep.assert_not_called()
                self.assertEqual(caught.exception.catalogue_transport_evidence[0]["http_status"], status)

    def test_retriable_http_statuses_retry_and_exhaust_bounded(self):
        for status in (408, 429, 500, 502, 503, 504):
            with self.subTest(status=status):
                (_, receipt), opener, _ = self.fetch([HTTPError(ENDPOINT, status, "retry", {}, None), Response()])
                self.assertEqual(opener.call_count, 2)
                self.assertEqual(receipt["transport_attempts"][0]["http_status"], status)
            with self.subTest(status=status, exhausted=True), patch.object(catalogue, "urlopen", side_effect=[HTTPError(ENDPOINT, status, "retry", {}, None) for _ in range(3)]) as opener, \
                    patch("time.sleep"):
                with self.assertRaises(RuntimeError):
                    catalogue.fetch_receipt(ENDPOINT)
                self.assertEqual(opener.call_count, 3)

    def test_connection_timeout_and_url_errors_retry_same_official_source(self):
        for error in (ConnectionError("lost"), ConnectionResetError("reset"), TimeoutError("timeout"), URLError("network")):
            with self.subTest(error=type(error).__name__):
                (_, receipt), opener, _ = self.fetch([error, Response()])
                self.assertEqual(receipt["attempt_count"], 2)
                self.assertEqual([c.args[0].full_url for c in opener.call_args_list], [ENDPOINT, ENDPOINT])

    def test_complete_receipt_preserves_exact_transport_binding(self):
        (body, receipt), _, sleep = self.fetch([Response()])
        self.assertEqual(receipt["endpoint"], ENDPOINT)
        self.assertEqual(receipt["final_url"], ENDPOINT)
        self.assertEqual(receipt["http_status"], 200)
        self.assertEqual(receipt["response_bytes"], len(body))
        self.assertEqual(receipt["body_sha256"], hashlib.sha256(body).hexdigest())
        self.assertEqual(receipt["attempt_count"], 1)
        self.assertFalse(receipt["fallback_used"])
        sleep.assert_not_called()

    def test_failed_attempt_preserves_partial_hash_not_authoritative_hash(self):
        (_, receipt), _, _ = self.fetch([interrupted(), Response()])
        evidence = receipt["transport_attempts"][0]
        required = ("source_owner", "market", "endpoint", "request_type", "attempt_number", "exception_class",
                    "exception_message", "http_status", "final_url", "content_type", "content_length",
                    "bytes_actually_read", "bytes_remaining", "retrieval_timestamp", "retry_decision", "fallback_used")
        self.assertTrue(all(key in evidence for key in required))
        self.assertEqual(evidence["market"], "TPEX")
        self.assertEqual(evidence["request_type"], "listing")
        self.assertEqual(evidence["partial_body_sha256"], hashlib.sha256(b"partial").hexdigest())
        self.assertFalse(evidence["partial_body_hash_authoritative"])
        self.assertNotIn("body_sha256", evidence)
        self.assertFalse(evidence["fallback_used"])

    def test_short_content_length_read_is_retried_not_accepted(self):
        (_, receipt), opener, _ = self.fetch([Response(length=len(BODY) + 1), Response()])
        self.assertEqual(opener.call_count, 2)
        self.assertEqual(receipt["transport_attempts"][0]["exception_class"], "IncompleteRead")

    def test_excess_or_invalid_content_length_fails_closed(self):
        for length in (len(BODY) - 1, "invalid", -1):
            with self.subTest(length=length), patch.object(catalogue, "urlopen", side_effect=lambda *a, **k: Response(length=length)), \
                    patch("time.sleep"):
                with self.assertRaises(RuntimeError):
                    catalogue.fetch_receipt(ENDPOINT)

    def test_absent_content_length_can_accept_completed_nonempty_response(self):
        response = Response()
        del response.headers["Content-Length"]
        (_, receipt), _, _ = self.fetch([response])
        self.assertEqual(receipt["body_sha256"], hashlib.sha256(BODY).hexdigest())

    def test_empty_body_and_non200_cannot_be_successful_receipts(self):
        for response in (Response(b""), Response(status=201)):
            with self.subTest(status=response.status), patch.object(catalogue, "urlopen", return_value=response), \
                    patch("time.sleep"):
                with self.assertRaises(RuntimeError):
                    catalogue.fetch_receipt(ENDPOINT)

    def test_unapproved_endpoint_rejected_before_network(self):
        with patch.object(catalogue, "urlopen") as opener, self.assertRaises(RuntimeError):
            catalogue.fetch_receipt("https://mirror.invalid/catalogue")
        opener.assert_not_called()

    def test_all_four_official_endpoint_owner_and_request_type_bindings(self):
        for request_type, endpoints in (("classification", catalogue.CLASSIFICATION_ENDPOINTS), ("listing", catalogue.LISTING_ENDPOINTS)):
            for market, endpoint in endpoints.items():
                with self.subTest(market=market, request_type=request_type):
                    (_, receipt), _, _ = self.fetch([Response(endpoint=endpoint)], endpoint, request_type == "classification")
                    attempt = receipt["transport_attempts"][0]
                    self.assertEqual(attempt["source_owner"], market)
                    self.assertEqual(attempt["market"], market)
                    self.assertEqual(attempt["request_type"], request_type)

    def test_prior_retry_lineage_survives_later_endpoint_failure(self):
        first = catalogue.CLASSIFICATION_ENDPOINTS["TWSE"]
        second = catalogue.LISTING_ENDPOINTS["TWSE"]
        def build(trading_date, *, fetcher):
            fetcher(first, html=True)
            fetcher(second)
        responses = [interrupted(endpoint=first), Response(endpoint=first)]
        responses += [interrupted(endpoint=second) for _ in range(3)]
        with patch.object(catalogue, "_build_catalogue", side_effect=build), \
                patch.object(catalogue, "urlopen", side_effect=responses), patch("time.sleep"):
            with self.assertRaises(RuntimeError) as caught:
                catalogue.build_catalogue("2026-10-06")
        evidence = caught.exception.catalogue_transport_evidence
        self.assertEqual([e["endpoint"] for e in evidence], [first, first, second, second, second])
        self.assertEqual(evidence[-1]["retry_decision"], "FAIL_CLOSED_RETRY_EXHAUSTED")

    def test_retry_evidence_survives_later_semantic_gate_failure(self):
        def build(trading_date, *, fetcher):
            fetcher(ENDPOINT)
            raise RuntimeError("STALE_OR_FUTURE_CATALOGUE")
        with patch.object(catalogue, "_build_catalogue", side_effect=build), \
                patch.object(catalogue, "urlopen", side_effect=[interrupted(), Response()]), patch("time.sleep"):
            with self.assertRaisesRegex(RuntimeError, "STALE_OR_FUTURE_CATALOGUE") as caught:
                catalogue.build_catalogue("2026-10-06")
        self.assertEqual(len(caught.exception.catalogue_transport_evidence), 2)

    def test_canonical_policy_eligibility_and_validation_bodies_unchanged(self):
        original = subprocess.check_output(["git", "-C", str(cli.ROOT), "show",
            "fcf06e512a62fad9eba828416e52041614f7dc3d:src/full_market_catalogue.py"]).decode()
        current = (cli.ROOT / "src/full_market_catalogue.py").read_text()
        old_nodes = {n.name: n for n in ast.parse(original).body if isinstance(n, ast.FunctionDef)}
        new_nodes = {n.name: n for n in ast.parse(current).body if isinstance(n, ast.FunctionDef)}
        for name in ("approved_policy", "policy_hash", "parse_classification", "validate_catalogue", "build_catalogue"):
            new = "_build_catalogue" if name == "build_catalogue" else name
            with self.subTest(name=name):
                self.assertEqual([ast.dump(n) for n in old_nodes[name].body], [ast.dump(n) for n in new_nodes[new].body])

    def test_cli_retains_failure_json_with_zero_production_mutation(self):
        protected = {p: p.read_bytes() for p in (cli.ROOT / "artifacts").rglob("*.json")}
        endpoint = catalogue.CLASSIFICATION_ENDPOINTS["TWSE"]
        with tempfile.TemporaryDirectory(prefix="catalogue-evidence-test-") as tmp:
            output = Path(tmp) / "output"
            args = ["bootstrap_full_market_history.py", "plan", "--as-of", "2026-10-06", "--store-root", str(Path(tmp) / "store"), "--output-root", str(output)]
            with patch.object(sys, "argv", args), patch.object(cli, "main_authority", return_value={"engineering_test_only": True}), \
                    patch.object(cli, "open_store", return_value=Path(tmp)), \
                    patch.object(catalogue, "urlopen", side_effect=[interrupted(endpoint=endpoint) for _ in range(3)]) as opener, \
                    patch("time.sleep"), patch.object(cli, "commit_store") as commit, \
                    patch.object(cli, "acquire_shard") as acquire, patch("sys.stdout", new_callable=StringIO) as stdout:
                self.assertEqual(cli.main(), 1)
                commit.assert_not_called()
                acquire.assert_not_called()
            result = json.loads((output / "failure.json").read_bytes())
            self.assertEqual(json.loads(stdout.getvalue()), result)
            self.assertEqual(result["validation_status"], "FAIL_CLOSED")
            self.assertEqual(len(result["catalogue_transport_evidence"]), 3)
            self.assertEqual(result["catalogue_transport_evidence"][-1]["endpoint"], endpoint)
            self.assertEqual(result["catalogue_transport_evidence"][-1]["request_type"], "classification")
            self.assertFalse(result["fallback_used"])
            for key in ("production_live_state_mutation", "production_state_latest_mutation", "portfolio_mutation", "ledger_mutation"):
                self.assertEqual(result[key], 0)
            self.assertEqual([c.args[0].full_url for c in opener.call_args_list], [endpoint] * 3)
            self.assertFalse((output / "plan.json").exists())
        self.assertEqual(protected, {p: p.read_bytes() for p in (cli.ROOT / "artifacts").rglob("*.json")})

    def test_failed_plan_workflow_always_uploads_failure_evidence(self):
        import yaml
        value = yaml.safe_load((cli.ROOT / ".github/workflows/rate_full_market_history_bootstrap.yml").read_text())
        steps = value["jobs"]["plan"]["steps"]
        failures = [s for s in steps if s.get("with", {}).get("path", "").endswith("/failure.json")]
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]["if"], "always()")
        self.assertEqual(failures[0]["uses"], "actions/upload-artifact@v4")
        self.assertNotEqual(failures[0]["with"]["name"], "RATE_HISTORY_PLAN_${{ github.run_id }}_${{ github.run_attempt }}")


if __name__ == "__main__":
    unittest.main()
