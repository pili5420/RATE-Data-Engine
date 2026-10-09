"""Synthetic-only tests for FinMind intraday qualification."""
from __future__ import annotations

import io
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError

from src.provider_finmind_intraday_candidate import (
    INDEX_IDS,
    QualificationError,
    fetch_stock_all,
    normalize_futures_rows,
    normalize_stock_rows,
    qualify,
)


NOW = datetime(2026, 10, 12, 1, 30, 0, tzinfo=timezone.utc)


def stock_row(symbol, timestamp="2026-10-12 09:29:30"):
    return {
        "stock_id": symbol,
        "date": timestamp,
        "open": 100,
        "high": 102,
        "low": 99,
        "close": 101,
        "total_volume": 1000,
        "total_amount": 101000,
    }


def future_row(fid, timestamp="2026-10-12 09:29:20"):
    return {
        "futures_id": fid,
        "date": timestamp,
        "open": 20000,
        "high": 20100,
        "low": 19900,
        "close": 20050,
        "total_volume": 12345,
    }


class Response(io.BytesIO):
    def __init__(self, payload, url, status=200):
        body = json.dumps(payload).encode()
        super().__init__(body)
        self.status = status
        self._url = url
        self.headers = {"Content-Type": "application/json"}

    def getcode(self):
        return self.status

    def geturl(self):
        return self._url


class FakeProvider:
    def __init__(self, *, stock_rows=None, index_rows=None, futures_rows=None, provider_status=200):
        self.stock_rows = stock_rows if stock_rows is not None else [stock_row(str(i)) for i in range(1000, 2978)]
        self.index_rows = index_rows if index_rows is not None else [stock_row("001"), stock_row("101")]
        self.futures_rows = futures_rows if futures_rows is not None else [future_row("TXFR1"), future_row("TXFF3")]
        self.provider_status = provider_status
        self.calls = []

    def __call__(self, request, timeout=30):
        url = request.full_url
        self.calls.append(url)
        if "taiwan_futures_snapshot" in url:
            rows = self.futures_rows
        elif "data_id=001" in url:
            rows = self.index_rows
        else:
            rows = self.stock_rows
        return Response({"status": self.provider_status, "data": rows}, url)


class FinMindQualificationTests(unittest.TestCase):
    def write_universe(self, rows=None):
        temp = tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False)
        values = rows if rows is not None else [{"symbol": str(i)} for i in range(1000, 2978)]
        json.dump(values, temp)
        temp.close()
        self.addCleanup(lambda: Path(temp.name).unlink(missing_ok=True))
        return temp.name

    def test_exact_three_calls_and_full_1978_coverage(self):
        provider = FakeProvider()
        result = qualify("secret", universe_path=self.write_universe(), opener=provider, now=NOW)
        self.assertEqual(len(provider.calls), 3)
        self.assertEqual(result["request_count"], 3)
        self.assertEqual(result["coverage"]["expected_count"], 1978)
        self.assertEqual(result["coverage"]["missing_count"], 0)
        self.assertTrue(result["gates"]["full_universe_coverage"])
        self.assertEqual(result["stock_snapshot"]["row_count"], 1978)
        self.assertIn(result["classification"], {"PASS_CANDIDATE", "PARTIAL_CANDIDATE"})

    def test_no_universe_is_partial_not_silent_pass(self):
        result = qualify("secret", opener=FakeProvider(), now=NOW)
        self.assertEqual(result["coverage"]["status"], "INCONCLUSIVE_FULL_UNIVERSE_INPUT_REQUIRED")
        self.assertFalse(result["gates"]["full_universe_coverage"])
        self.assertEqual(result["classification"], "PARTIAL_CANDIDATE")

    def test_non_1978_universe_rejected_as_coverage_proof(self):
        result = qualify("secret", universe_path=self.write_universe([{"symbol": "2330"}]), opener=FakeProvider(), now=NOW)
        self.assertFalse(result["gates"]["full_universe_coverage"])
        self.assertIn("EXPECTED_1978", result["coverage"]["status"])
        self.assertEqual(result["classification"], "FAIL_CLOSED")

    def test_missing_symbol_fails_coverage(self):
        rows = [stock_row(str(i)) for i in range(1000, 2977)]
        result = qualify("secret", universe_path=self.write_universe(), opener=FakeProvider(stock_rows=rows), now=NOW)
        self.assertEqual(result["coverage"]["missing_count"], 1)
        self.assertFalse(result["gates"]["full_universe_coverage"])
        self.assertEqual(result["classification"], "FAIL_CLOSED")

    def test_indices_001_101_required(self):
        result = qualify("secret", opener=FakeProvider(index_rows=[stock_row("001")]), now=NOW)
        self.assertFalse(result["gates"]["index_001_101_present"])
        self.assertEqual(result["classification"], "FAIL_CLOSED")

    def test_txf_family_required(self):
        result = qualify("secret", opener=FakeProvider(futures_rows=[future_row("MXFR1")]), now=NOW)
        self.assertFalse(result["gates"]["txf_family_present"])
        self.assertEqual(result["classification"], "FAIL_CLOSED")

    def test_stale_stock_probe_fails(self):
        rows = [stock_row(str(i), "2026-10-12 09:00:00") for i in range(1000, 2978)]
        result = qualify("secret", opener=FakeProvider(stock_rows=rows), now=NOW)
        self.assertFalse(result["gates"]["stock_freshness_candidate"])
        self.assertEqual(result["classification"], "FAIL_CLOSED")

    def test_stale_futures_probe_fails(self):
        result = qualify("secret", opener=FakeProvider(futures_rows=[future_row("TXFR1", "2026-10-12 09:00:00")]), now=NOW)
        self.assertFalse(result["gates"]["futures_freshness_candidate"])
        self.assertEqual(result["classification"], "FAIL_CLOSED")

    def test_naive_timezone_is_explicitly_not_production_proof(self):
        result = qualify("secret", opener=FakeProvider(), now=NOW)
        self.assertFalse(result["timestamp_semantics"]["provider_timezone_explicit_in_payload"])
        self.assertFalse(result["timestamp_semantics"]["production_timestamp_contract_satisfied"])
        self.assertEqual(result["classification"], "PARTIAL_CANDIDATE")

    def test_schema_missing_fails_closed(self):
        row = stock_row("2330")
        del row["total_volume"]
        with self.assertRaisesRegex(QualificationError, "STOCK_SCHEMA_MISSING"):
            normalize_stock_rows([row])

    def test_duplicate_stock_id_fails_closed(self):
        with self.assertRaisesRegex(QualificationError, "DUPLICATE"):
            normalize_stock_rows([stock_row("2330"), stock_row("2330")])

    def test_duplicate_futures_id_fails_closed(self):
        with self.assertRaisesRegex(QualificationError, "DUPLICATE"):
            normalize_futures_rows([future_row("TXFR1"), future_row("TXFR1")])

    def test_nonfinite_numeric_fails_closed(self):
        row = stock_row("2330")
        row["close"] = "NaN"
        with self.assertRaisesRegex(QualificationError, "NUMERIC_INVALID"):
            normalize_stock_rows([row])

    def test_token_is_not_present_in_evidence(self):
        token = "SUPER_SECRET_TOKEN"
        result = qualify(token, opener=FakeProvider(), now=NOW)
        text = json.dumps(result)
        self.assertNotIn(token, text)
        self.assertFalse(result["credential_persisted"])
        self.assertFalse(result["raw_response_persisted"])

    def test_provider_status_non_200_fails(self):
        with self.assertRaisesRegex(QualificationError, "PROVIDER_STATUS_NOT_200"):
            fetch_stock_all("secret", opener=FakeProvider(provider_status=402), now=lambda: NOW.isoformat())

    def test_http_403_maps_to_plan_not_authorized_and_no_retry(self):
        calls = []
        def opener(request, timeout=30):
            calls.append(request.full_url)
            raise HTTPError(request.full_url, 403, "forbidden", {}, None)
        with self.assertRaisesRegex(QualificationError, "PLAN_NOT_AUTHORIZED"):
            fetch_stock_all("secret", opener=opener, now=lambda: NOW.isoformat())
        self.assertEqual(len(calls), 1)

    def test_missing_token_fails_before_transport(self):
        calls = []
        def opener(request, timeout=30):
            calls.append(request.full_url)
            return Response({"status": 200, "data": []}, request.full_url)
        with self.assertRaisesRegex(QualificationError, "TOKEN_NOT_INJECTED"):
            fetch_stock_all("", opener=opener)
        self.assertEqual(calls, [])

    def test_no_production_mutation_flags(self):
        result = qualify("secret", opener=FakeProvider(), now=NOW)
        self.assertFalse(result["source_registry_modified"])
        self.assertFalse(result["production_scheduler_modified"])
        self.assertFalse(result["external_dependency_resolved"])
        self.assertFalse(result["decision_eligible"])
        self.assertFalse(result["production_eligible"])

    def test_futures_near_month_mapping_remains_unproven(self):
        result = qualify("secret", opener=FakeProvider(), now=NOW)
        self.assertEqual(result["futures"]["near_month_selection_status"], "UNPROVEN_BY_SNAPSHOT_SCHEMA")


if __name__ == "__main__":
    unittest.main()
