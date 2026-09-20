from __future__ import annotations

import unittest
from unittest.mock import patch
from io import BytesIO
from pathlib import Path
import shutil

from src.sources.fundamental_history import (
    FundamentalHistoryStoreV2,
    MOPSHistoricalFundamentalAdapter,
    extract_disclosure_date,
    _table_records,
    normalize_revenue_period,
)


def revenue(symbol, period, disclosure, value=1.0):
    return {"symbol": symbol, "market": "TWSE", "revenue_period": period,
            "revenue_yoy": value, "official_disclosure_date": disclosure,
            "provider": "MOPS Official", "official_product": "月營業收入資訊",
            "endpoint": "official", "content_hash": period + disclosure,
            "retrieval_timestamp": "2026-09-18T00:00:00Z"}


def eps(symbol, year, quarter, disclosure, value=1.0):
    return {"symbol": symbol, "market": "TWSE", "fiscal_year": year, "quarter": quarter,
            "single_quarter_eps": value, "official_disclosure_date": disclosure,
            "source_semantics": "OFFICIAL_SINGLE_QUARTER", "provider": "MOPS Official",
            "official_product": "綜合損益表", "endpoint": "official",
            "content_hash": f"{year}-{quarter}-{disclosure}", "retrieval_timestamp": "2026-09-18T00:00:00Z"}


class FakeResponse(BytesIO):
    status = 200

    def __init__(self, text):
        super().__init__(text.encode("utf-8"))
        self.headers = {"Content-Type": "text/html; charset=utf-8"}

    def getcode(self):
        return self.status

    def geturl(self):
        return "https://official.example.test/fundamental"


def fake_opener(html):
    def _open(_request, timeout=45):
        return FakeResponse(html)
    return _open


def revenue_html(rows):
    body = "".join(
        f"<tr><td>{period}</td><td>{symbol}</td><td>{yoy}</td><td>{disclosure}</td></tr>"
        for period, symbol, yoy, disclosure in rows
    )
    return (
        "<html><table><tr><th>資料年月</th><th>公司代號</th>"
        "<th>去年同月增減(%)</th><th>出表日期</th></tr>"
        f"{body}</table></html>"
    )


def eps_html(include_identity=True):
    prefix = "資料年度：115年 第2季" if include_identity else "綜合損益表"
    return (
        f"<html>{prefix} 出表日期：115年08月14日"
        "<table><tr><th>公司代號</th><th>基本每股盈餘</th></tr>"
        "<tr><td>2330</td><td>10.25</td></tr></table></html>"
    )


class TestCER073FundamentalHistoryV2(unittest.TestCase):
    def test_explicit_disclosure_date_is_required(self):
        self.assertEqual(extract_disclosure_date("出表日期：115年09月10日"), "2026-09-10")
        with self.assertRaisesRegex(ValueError, "FUNDAMENTAL_DISCLOSURE_DATE"):
            extract_disclosure_date("retrieval_timestamp=2026-09-18T00:00:00Z")

    def test_store_revises_and_selects_asof(self):
        obj = {"revenue_events": [revenue("2330", "2026-06", "2026-07-10", 1.0), revenue("2330", "2026-06", "2026-07-11", 2.0)], "eps_events": []}
        selected = FundamentalHistoryStoreV2.select_asof(obj, ["2330"], "2026-09-18")
        self.assertEqual(selected["2330"]["revenue"]["2026-06"]["revenue_yoy"], 2.0)

    def test_future_disclosure_is_excluded(self):
        obj = {"revenue_events": [revenue("2330", "2026-08", "2026-10-10")], "eps_events": []}
        selected = FundamentalHistoryStoreV2.select_asof(obj, ["2330"], "2026-09-18")
        self.assertEqual(selected["2330"]["revenue"], {})

    def test_distinct_month_and_quarter_selection(self):
        obj = {"revenue_events": [revenue("2330", f"2026-0{month}", "2026-09-01") for month in range(1, 7)],
               "eps_events": [eps("2330", 2026 - index // 4, 2 - index % 4 if index % 4 < 2 else 6 - index % 4,
                                  "2026-09-01", index) for index in range(8)]}
        selected = FundamentalHistoryStoreV2.select_asof(obj, ["2330"], "2026-09-18")
        self.assertGreaterEqual(len(selected["2330"]["revenue"]), 3)
        self.assertEqual(len(selected["2330"]["eps"]), 8)

    def test_production_namespace_is_refused(self):
        with self.assertRaisesRegex(RuntimeError, "PRODUCTION_FUNDAMENTAL_NAMESPACE_FORBIDDEN"):
            FundamentalHistoryStoreV2("data/production/fundamental")

    def test_store_is_deterministic_for_identical_events(self):
        rows = [revenue("2330", "2026-06", "2026-07-10"), revenue("2330", "2026-05", "2026-06-10")]
        selected_one = FundamentalHistoryStoreV2.select_asof({"revenue_events": rows, "eps_events": []}, ["2330"], "2026-09-18")
        selected_two = FundamentalHistoryStoreV2.select_asof({"revenue_events": list(reversed(rows)), "eps_events": []}, ["2330"], "2026-09-18")
        self.assertEqual(selected_one, selected_two)

    def test_revenue_period_normalization_accepts_official_forms(self):
        self.assertEqual(normalize_revenue_period("11508"), "2026-08")
        self.assertEqual(normalize_revenue_period("115/08"), "2026-08")
        self.assertEqual(normalize_revenue_period("115年08月"), "2026-08")
        self.assertEqual(normalize_revenue_period("202608"), "2026-08")
        self.assertEqual(normalize_revenue_period("2026/08"), "2026-08")

    def test_revenue_identity_uses_row_level_official_period(self):
        html = revenue_html([("11508", "2330", "12.3", "115年09月10日")])
        adapter = MOPSHistoricalFundamentalAdapter(opener=fake_opener(html), min_interval_seconds=0)
        rows = adapter.fetch_revenue_period("TWSE", "2026-08")
        self.assertEqual(rows[0]["revenue_period"], "2026-08")
        self.assertEqual(rows[0]["official_disclosure_date"], "2026-09-10")
        self.assertEqual(adapter.diagnostics[-1]["period_identity_source"], "ROW_LEVEL_OFFICIAL_FIELD")

    def test_revenue_mixed_period_response_is_rejected(self):
        html = revenue_html([
            ("11508", "2330", "12.3", "115年09月10日"),
            ("11507", "2317", "1.2", "115年08月10日"),
        ])
        adapter = MOPSHistoricalFundamentalAdapter(opener=fake_opener(html), min_interval_seconds=0)
        with self.assertRaisesRegex(RuntimeError, "FUNDAMENTAL_REVENUE_PERIOD_IDENTITY_MISMATCH:2026-08:2026-07,2026-08"):
            adapter.fetch_revenue_period("TWSE", "2026-08")

    def test_revenue_zero_parseable_period_is_rejected(self):
        html = revenue_html([("unknown", "2330", "12.3", "115年09月10日")])
        adapter = MOPSHistoricalFundamentalAdapter(opener=fake_opener(html), min_interval_seconds=0)
        with self.assertRaisesRegex(RuntimeError, "FUNDAMENTAL_REVENUE_PERIOD_IDENTITY_UNPROVEN"):
            adapter.fetch_revenue_period("TWSE", "2026-08")

    def test_revenue_nested_table_parser_preserves_outer_rows(self):
        html = """
        <html><table>
          <tr><th>資料年月</th><th>公司代號</th><th>去年同月增減(%)</th><th>出表日期</th></tr>
          <tr><td>11508</td><td>2330</td><td>12.3</td><td>115年09月10日</td></tr>
          <tr><td colspan="4"><table>
            <tr><th>nested header</th></tr>
            <tr><td>nested value</td></tr>
          </table></td></tr>
          <tr><td>11508</td><td>2317</td><td>1.2</td><td>115年09月10日</td></tr>
        </table></html>
        """
        rows, schemas = _table_records(html, {"symbol": ("公司代號",), "period": ("資料年月",),
                                              "yoy": ("去年同月增減",), "disclosure": ("出表日期",)})
        self.assertEqual([row["symbol"] for row in rows], ["2330", "2317"])
        self.assertEqual(len(schemas), 1)

    def test_eps_returned_period_identity_is_required(self):
        adapter = MOPSHistoricalFundamentalAdapter(opener=fake_opener(eps_html(include_identity=False)), min_interval_seconds=0)
        with self.assertRaisesRegex(RuntimeError, "FUNDAMENTAL_EPS_PERIOD_IDENTITY_UNPROVEN"):
            adapter.fetch_eps_period("TWSE", 2026, 2)

    def test_unverified_events_are_not_persisted(self):
        store = FundamentalHistoryStoreV2("data/staging/test-fundamental")
        bad_revenue = revenue("2330", "2026-08", "")
        with self.assertRaisesRegex(RuntimeError, "UNVERIFIED_REVENUE_EVENT"):
            store.upsert([bad_revenue], [])

    def test_eps_semantics_are_validated_before_persistence(self):
        store = FundamentalHistoryStoreV2("data/staging/test-fundamental")
        bad_eps = eps("2330", 2026, 2, "2026-08-14")
        bad_eps["source_semantics"] = "MIXED_CUMULATIVE_SINGLE"
        with self.assertRaisesRegex(RuntimeError, "FUNDAMENTAL_EPS_SOURCE_SEMANTICS_INVALID"):
            store.upsert([], [bad_eps])

    def test_identical_refetch_deduplicates_without_retrieval_time_identity(self):
        root = Path("artifacts/test-fundamental-idempotency")
        shutil.rmtree(root, ignore_errors=True)
        store = FundamentalHistoryStoreV2(root)
        first = revenue("2330", "2026-08", "2026-09-10", 12.3)
        second = dict(first, retrieval_timestamp="2026-09-18T01:00:00Z")
        obj = store.upsert([first, second], [])
        self.assertEqual(len(obj["revenue_events"]), 1)
        self.assertEqual(obj["_last_upsert_summary"]["inserted_revenue_events"], 1)
        again = store.upsert([dict(first, retrieval_timestamp="2026-09-18T02:00:00Z")], [])
        self.assertEqual(len(again["revenue_events"]), 1)
        self.assertEqual(again["_last_upsert_summary"]["inserted_revenue_events"], 0)
        shutil.rmtree(root, ignore_errors=True)

    def test_official_fetch_retries_transport_failures(self):
        from scripts import bootstrap_cer073_fundamentals as bootstrap

        calls = []

        def fake_fetch(url, params=None):
            calls.append((url, params))
            if len(calls) == 1:
                return "", {"http_status": None, "error": "URLError: refused"}
            return "<html>ok</html>", {"http_status": 200, "response_bytes": 15}

        with patch.object(bootstrap, "fetch", side_effect=fake_fetch), patch.object(bootstrap.time, "sleep"):
            text, evidence = bootstrap.official_fetch("https://doc.twse.com.tw/server-java/t57sb01", attempts=3)

        self.assertEqual(text, "<html>ok</html>")
        self.assertEqual(evidence["attempt"], 2)
        self.assertEqual(len(calls), 2)


    def test_official_revision_preserves_separate_semantic_event(self):
        root = Path("artifacts/test-fundamental-revision")
        shutil.rmtree(root, ignore_errors=True)
        store = FundamentalHistoryStoreV2(root)
        original = eps("2330", 2025, 4, "2026-02-26", 19.51)
        revised = dict(original, single_quarter_eps=19.75, official_disclosure_date="2026-03-01",
                       correction_lineage=[{"official_correction_date": "2026-03-01"}])
        obj = store.upsert([], [original, revised])
        self.assertEqual(len(obj["eps_events"]), 2)
        self.assertEqual(obj["_last_upsert_summary"]["inserted_eps_events"], 2)
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
