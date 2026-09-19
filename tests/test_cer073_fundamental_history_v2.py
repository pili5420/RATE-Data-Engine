from __future__ import annotations

import unittest
from pathlib import Path

from src.sources.fundamental_history import FundamentalHistoryStoreV2, extract_disclosure_date


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


if __name__ == "__main__":
    unittest.main()
