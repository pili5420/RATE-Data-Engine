from __future__ import annotations

import unittest
from io import BytesIO
from pathlib import Path

from src.sources.fundamental_history import (
    FundamentalHistoryStoreV2,
    MOPSHistoricalFundamentalAdapter,
    extract_disclosure_date,
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


if __name__ == "__main__":
    unittest.main()
