"""Official-owner plumbing tests; all responses are isolated engineering fixtures."""
from contextlib import ExitStack
import copy
from datetime import date
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from src.full_market_materialization import materialize_full_market, refresh_fundamentals
from tests.test_phase2_production import fake_catalogue, raw_fixture, FIXTURE_RETRIEVAL


class FullMarketMaterializationTests(unittest.TestCase):
    def owner_context(self, missing_current=False, warmup_failure=False):
        stack = ExitStack()
        self.addCleanup(stack.close)
        day = "2026-10-05"
        raw = raw_fixture(day)
        catalogue = fake_catalogue(day)
        stack.enter_context(patch("src.full_market_materialization.build_catalogue", return_value=catalogue))
        store = Mock()
        store.load_stock.side_effect = lambda symbol: raw["stock_histories"][symbol][:-1]
        store.load_benchmark.side_effect = lambda symbol: raw["benchmark_by_symbol"]["1000" if symbol == "TAIEX" else "1001"]
        stack.enter_context(patch("src.full_market_materialization.PersistentHistoricalStore", return_value=store))
        stocks = []
        for market, owner in (("TWSE", "TWSEAdapter"), ("TPEX", "TPExAdapter")):
            response = {"source_timestamp": FIXTURE_RETRIEVAL, "retrieval_timestamp": FIXTURE_RETRIEVAL,
                "endpoint": "OFFICIAL_OWNER_FIXTURE", "content_hash": "f" * 64,
                "raw_payload": [{**rows[-1], "Code": symbol, "Date": day}
                    for symbol, rows in raw["stock_histories"].items()
                    if rows[-1]["source"] == market and not (missing_current and symbol == "1059")]}
            adapter = Mock()
            adapter.fetch_daily.return_value = response
            stack.enter_context(patch("src.full_market_materialization." + owner, return_value=adapter))
        stock_owner = stack.enter_context(patch("scripts.materialize_production_history_store._materialize_stock",
            side_effect=RuntimeError("OFFICIAL_MARKET_HISTORY_HARD_LIMIT_REACHED") if warmup_failure else lambda **kw: stocks.append(kw)))
        stack.enter_context(patch("scripts.materialize_production_history_store._materialize_benchmark"))
        stack.enter_context(patch("scripts.materialize_production_history_store._benchmark_month_rows",
            side_effect=lambda adapter, market, period, cutoff: [{**raw["benchmark_by_symbol"]["1000" if market == "TWSE" else "1001"][-1],
                                                                 "ingested_at": FIXTURE_RETRIEVAL}]))
        stack.enter_context(patch("scripts.materialize_production_history_store._replace_benchmark"))
        for rows in raw["benchmark_by_symbol"].values():
            for row in rows:
                row["ingested_at"] = FIXTURE_RETRIEVAL
        institutional = {symbol: [{**row, "trading_date": row["trade_date"], "source_timestamp": FIXTURE_RETRIEVAL} for row in rows]
                         for symbol, rows in raw["institutional_histories"].items()}
        stack.enter_context(patch("scripts.build_live_source_bundle._institutional_histories", return_value=(institutional, {})))
        for rows in raw["tdcc_histories"].values():
            for row in rows:
                row["retrieval_timestamp"] = FIXTURE_RETRIEVAL
        stack.enter_context(patch("scripts.build_live_source_bundle._tdcc_history", return_value=raw["tdcc_histories"]))
        stack.enter_context(patch("src.full_market_materialization.refresh_fundamentals",
            return_value={r["symbol"]: r for r in raw["fundamental_records"]}))
        evidence = {"validation_status": "PASS", "fixture_used": False,
            "symbols": [{"symbol": row["symbol"], "source_lineage": {"revenue": [{"official_disclosure_date": day}]}}
                        for row in raw["fundamental_records"]]}
        path = stack.enter_context(patch("src.full_market_materialization.Path"))
        path.return_value.read_bytes.return_value = json.dumps(evidence).encode()
        return day, catalogue, stocks, stock_owner

    def test_all_eligible_symbols_materialized_by_existing_bounded_owners(self):
        day, catalogue, stocks, _ = self.owner_context()
        returned, material = materialize_full_market(day, "ENGINEERING_TEMP_HISTORY_ROOT")
        self.assertEqual(returned, catalogue)
        self.assertEqual(len(material["stock_histories"]), 60)
        self.assertEqual(len(stocks), 60)
        self.assertEqual({kw["market"] for kw in stocks}, {"TWSE", "TPEX"})
        self.assertTrue(all(kw["minimum_sessions"] == 179 and len(kw["periods"]) == 12 for kw in stocks))
        self.assertTrue(all(len(rows) == 180 and rows[-1]["trade_date"] == day for rows in material["stock_histories"].values()))
        self.assertEqual(len(material["fundamental_records"]), 60)
        self.assertTrue(material["normalized_source_receipts"])

    def test_missing_current_input_fails_without_shrinking_catalogue(self):
        day, catalogue, _, _ = self.owner_context(missing_current=True)
        before = copy.deepcopy(catalogue)
        with self.assertRaisesRegex(RuntimeError, "FULL_MARKET_CURRENT_DAILY_INCOMPLETE:1059"):
            materialize_full_market(day, "ENGINEERING_TEMP_HISTORY_ROOT")
        self.assertEqual(catalogue, before)
        self.assertEqual(catalogue["eligible_count"], 60)

    def test_existing_owner_history_hard_limit_maps_to_warmup_required(self):
        day, _, _, owner = self.owner_context(warmup_failure=True)
        with self.assertRaisesRegex(RuntimeError, "HISTORICAL_WARMUP_REQUIRED"):
            materialize_full_market(day, "ENGINEERING_TEMP_HISTORY_ROOT")
        self.assertEqual(owner.call_count, 1)

    def test_fundamental_period_acquisition_distinct_and_existing_selector(self):
        from scripts import build_live_source_bundle as owner
        adapter = Mock()
        adapter.fetch_revenue_period.return_value = []
        adapter.fetch_eps_period.return_value = []
        expected = {"COMMON": {"revenue_yoy": [1, 2, 3], "quarterly_eps": [1] * 8}}
        with patch.object(owner, "MOPSHistoricalFundamentalAdapter", return_value=adapter), \
             patch.object(owner, "FundamentalHistoryStoreV2"), \
             patch.object(owner, "_fundamental_history", return_value=expected) as selector:
            result = refresh_fundamentals(["COMMON"], {"COMMON": "TWSE"}, "2026-10-05", "TEMP_HISTORY",
                started=__import__("time").monotonic(), budget=60)
        self.assertEqual(result, expected)
        self.assertEqual(selector.call_count, 1)
        periods = [call.args[1] for call in adapter.fetch_revenue_period.call_args_list if call.args[0] == "TWSE"]
        self.assertEqual(periods, ["2026-09", "2026-08", "2026-07", "2026-06", "2026-05", "2026-04"])
        self.assertEqual(len(adapter.fetch_eps_period.call_args_list), 20)


if __name__ == "__main__":
    unittest.main()
