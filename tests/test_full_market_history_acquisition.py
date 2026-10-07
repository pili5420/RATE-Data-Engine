"""Transport and resumable shard engineering tests; all official owners mocked."""
from http.client import IncompleteRead
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from src import full_market_history as h
from src import full_market_history_acquisition as a
from src.sources.fundamental_history import EPSPeriodNotAvailable
from tests.test_full_market_history import cfg, material, plan, receipt


class HistoryAcquisitionTests(unittest.TestCase):
    def setUp(self):
        self.patch = patch("src.full_market_history.contract", side_effect=cfg)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.tmp = tempfile.TemporaryDirectory(prefix="rate-history-shard-test-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.plan = plan()
        self.shard = self.plan["shards"][0]

    def test_truncated_json_then_valid_bounded_same_call(self):
        calls, delays = [], []
        def call():
            calls.append("SAME_OFFICIAL_OWNER")
            if len(calls) == 1: raise json.JSONDecodeError("truncated", "{", 1)
            return {"valid": True}
        self.assertEqual(a.retry(call, started=0, budget=100, clock=lambda: 0, sleep=delays.append), {"valid": True})
        self.assertEqual(calls, ["SAME_OFFICIAL_OWNER"] * 2)
        self.assertEqual(delays, [1])

    def test_first_two_fail_third_valid_exponential_backoff(self):
        calls, delays = [], []
        def call():
            calls.append(1)
            if len(calls) < 3: raise URLError("reset")
            return "PASS"
        self.assertEqual(a.retry(call, started=0, budget=100, clock=lambda: 0, sleep=delays.append), "PASS")
        self.assertEqual(len(calls), 3)
        self.assertEqual(delays, [1, 2])

    def test_all_attempts_fail_no_fallback(self):
        calls = []
        def call():
            calls.append(1)
            raise IncompleteRead(b"partial", 100)
        with self.assertRaisesRegex(RuntimeError, "OFFICIAL_HISTORY_TRANSPORT_FAILED"):
            a.retry(call, started=0, budget=100, clock=lambda: 0, sleep=lambda _: None)
        self.assertEqual(len(calls), 3)

    def test_nonretryable_http_and_budget_fail_before_new_request(self):
        for error in (HTTPError("https://www.twse.com.tw", 403, "denied", {}, None), ValueError("BAD_SCHEMA")):
            calls = []
            def call():
                calls.append(1)
                raise error
            with self.assertRaises(type(error)):
                a.retry(call, started=0, budget=100, clock=lambda: 0, sleep=lambda _: None)
            self.assertEqual(len(calls), 1)
        with self.assertRaisesRegex(RuntimeError, "WARMUP_RUNTIME_BUDGET_EXHAUSTED"):
            a.retry(lambda: self.fail("NEW_REQUEST"), started=0, budget=10, clock=lambda: 11)

    def test_partial_progress_resume_uses_only_exact_verified_symbol(self):
        symbols = self.shard["symbols"]
        durable, output = self.root / "durable", self.root / "out"
        first = symbols[0]
        h.persist_symbol(durable, material(self.plan, first), self.plan, first, "TWSE")
        def fetch(symbol, market, *args):
            if symbol == symbols[-1]: raise URLError("OFFICIAL_TRANSPORT_FAILED")
            return material(self.plan, symbol, market)
        with patch.object(a, "acquire_fundamentals", return_value={s: {} for s in symbols}), patch.object(a, "acquire_symbol", side_effect=fetch):
            result = a.acquire_shard(self.plan, self.shard["shard_id"], durable, output, authority=self.plan["runtime_authority"])
        self.assertEqual(result["reused_symbols"], [first])
        self.assertEqual(len(result["completed_symbols"]), 8)
        self.assertEqual(result["failed_symbols"][0]["symbol"], symbols[-1])
        self.assertEqual(result["validation_status"], "FAIL_CLOSED")
        self.assertFalse(result["fallback_used"])
        self.assertFalse((output / "snapshots").exists())

    def test_all_verified_resume_has_zero_network_calls(self):
        for symbol in self.shard["symbols"]:
            h.persist_symbol(self.root, material(self.plan, symbol), self.plan, symbol, "TWSE")
        with patch.object(a, "acquire_fundamentals", side_effect=AssertionError("NETWORK")), patch.object(a, "acquire_symbol", side_effect=AssertionError("NETWORK")):
            result = a.acquire_shard(self.plan, self.shard["shard_id"], self.root, self.root / "output", authority=self.plan["runtime_authority"])
        self.assertEqual(result["validation_status"], "PASS")
        self.assertEqual(result["reused_symbols"], self.shard["symbols"])
        self.assertEqual(result["completed_symbols"], [])

    def test_corrupt_resume_blocks_before_any_acquisition(self):
        symbol = self.shard["symbols"][0]
        cp = h.persist_symbol(self.root, material(self.plan, symbol), self.plan, symbol, "TWSE")
        h.safe_path(self.root, cp["material"]["path"]).write_bytes(b"corrupted")
        with patch.object(a, "acquire_fundamentals", side_effect=AssertionError("REACQUIRE")), self.assertRaisesRegex(RuntimeError, "HISTORY_MATERIAL_HASH_MISMATCH"):
            a.acquire_shard(self.plan, self.shard["shard_id"], self.root, self.root / "out", authority=self.plan["runtime_authority"])

    def test_receipt_adapter_keeps_same_official_owner_and_body_hash(self):
        class Owner:
            def fetch_historical_symbol(self, symbol, period):
                self.request = (symbol, period)
                r = receipt("https://www.tpex.org.tw/www/en-us/afterTrading/tradingStock")
                return {"endpoint": r["endpoint"], "content_hash": r["content_hash"], "retrieval_timestamp": r["retrieved_at"]}
        owner = Owner()
        import time
        adapter = a.ReceiptAdapter(owner, time.monotonic(), 100)
        response = adapter.fetch_historical_symbol("OFFICIAL-COMMON", "202609")
        self.assertEqual(owner.request, ("OFFICIAL-COMMON", "202609"))
        self.assertEqual(adapter.receipts["stock"][0]["content_hash"], response["content_hash"])

    def test_same_job_market_response_memo_preserves_actual_receipt_not_fallback(self):
        import time
        class Owner:
            calls = 0
            def fetch_t86(self, day):
                self.calls += 1
                r = receipt("https://www.twse.com.tw/rwd/zh/fund/T86")
                return {"endpoint": r["endpoint"], "content_hash": r["content_hash"], "retrieval_timestamp": r["retrieved_at"]}
        shared, owner = {}, Owner()
        first = a.ReceiptAdapter(owner, time.monotonic(), 100, shared)
        second = a.ReceiptAdapter(owner, time.monotonic(), 100, shared)
        self.assertEqual(first.fetch_t86("2026-10-05"), second.fetch_t86("2026-10-05"))
        self.assertEqual(owner.calls, 1)
        self.assertEqual(first.receipts["institutional"], second.receipts["institutional"])

    def test_materializer_reuses_existing_stock_benchmark_institutional_tdcc_owners(self):
        import time
        m = material(self.plan)
        class Proxy:
            receipts = {k: m["source_receipts"][k] for k in ("stock", "benchmark", "institutional")}
        def stock(**kw):
            self.assertEqual(kw["minimum_sessions"], 180)
            kw["store"].materialize_stock("1000", m["stock"])
        def benchmark(**kw): kw["store"].upsert_benchmark("TAIEX", m["benchmark"])
        with patch("scripts.materialize_production_history_store._materialize_stock", side_effect=stock) as so, \
             patch("scripts.materialize_production_history_store._materialize_benchmark", side_effect=benchmark) as bo, \
             patch("scripts.build_live_source_bundle._institutional_histories", return_value=({"1000": m["institutional"]}, {})) as io, \
             patch("scripts.build_live_source_bundle._tdcc_history", return_value={"1000": m["tdcc"]}) as td:
            value = a.acquire_symbol("1000", "TWSE", self.plan, Proxy(), self.root, m["fundamental"], time.monotonic())
            value["acquisition_runtime_authority"] = self.plan["runtime_authority"]
        self.assertEqual(h.validate_symbol(value, self.plan, "1000", "TWSE")["validation_status"], "PASS")
        self.assertEqual([so.call_count, bo.call_count, io.call_count, td.call_count], [1, 1, 1, 1])

    def test_distinct_mops_periods_revision_store_and_existing_asof_selector(self):
        import time
        base = material(self.plan)["fundamental"]
        requests = []
        class Adapter:
            def __init__(self, **kwargs):
                self.row_failures = []
            def fetch_revenue_period(self, market, period):
                requests.append(("revenue", market, period))
                return [{**base["revenue"][0], "market": market, "revenue_period": period,
                         "official_disclosure_date": "2026-10-01"}]
            def fetch_eps_period(self, market, year, quarter):
                requests.append(("eps", market, year, quarter))
                return [{**base["eps"][0], "market": market, "fiscal_year": year, "quarter": quarter,
                         "official_disclosure_date": "2026-10-01"}]
        with patch("src.sources.fundamental_history.MOPSHistoricalFundamentalAdapter", Adapter):
            selected = a.acquire_fundamentals(["1000"], "TWSE", self.plan, self.root, time.monotonic())
        self.assertEqual(len({r[2] for r in requests if r[0] == "revenue"}), 6)
        self.assertEqual(len({r[2:] for r in requests if r[0] == "eps"}), 10)
        self.assertEqual(len(selected["1000"]["revenue"]), 3)
        self.assertEqual(len(selected["1000"]["eps"]), 8)


    def test_leading_query_no_data_cannot_skip_to_older_eps_for_pass(self):
        # Control Center scope correction: replace the former skip authorization
        # assertion with immediate fail-closed and no normalized persistence.
        import time
        base = material(self.plan)["fundamental"]
        requests = []
        class Adapter:
            def __init__(self, **kwargs):
                self.row_failures = []
            def fetch_revenue_period(self, market, period):
                return [{**base["revenue"][0], "market": market, "revenue_period": period,
                         "official_disclosure_date": "2026-10-01"}]
            def fetch_eps_period(self, market, year, quarter):
                requests.append((year, quarter))
                if len(requests) == 1:
                    raise EPSPeriodNotAvailable(f"{year}Q{quarter}")
                return [{**base["eps"][0], "market": market, "fiscal_year": year, "quarter": quarter,
                         "official_disclosure_date": "2026-10-01"}]
        with patch("src.sources.fundamental_history.MOPSHistoricalFundamentalAdapter", Adapter), \
             patch("src.sources.fundamental_history.FundamentalHistoryStoreV2.upsert") as persist:
            with self.assertRaisesRegex(EPSPeriodNotAvailable, "FUNDAMENTAL_EPS_PERIOD_NOT_AVAILABLE:2026Q3"):
                a.acquire_fundamentals(["1000"], "TWSE", self.plan, self.root, time.monotonic())
            persist.assert_not_called()
        self.assertEqual(requests, [(2026, 3)])
        self.assertFalse((self.root / "fundamental" / "RATE_FUNDAMENTAL_HISTORY_V2.json").exists())

    def test_eps_no_data_after_available_history_started_remains_fail_closed(self):
        import time
        base = material(self.plan)["fundamental"]
        calls = 0
        class Adapter:
            def __init__(self, **kwargs):
                self.row_failures = []
            def fetch_revenue_period(self, market, period):
                return [{**base["revenue"][0], "market": market, "revenue_period": period,
                         "official_disclosure_date": "2026-10-01"}]
            def fetch_eps_period(self, market, year, quarter):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise EPSPeriodNotAvailable(f"{year}Q{quarter}")
                return [{**base["eps"][0], "market": market, "fiscal_year": year, "quarter": quarter,
                         "official_disclosure_date": "2026-10-01"}]
        with patch("src.sources.fundamental_history.MOPSHistoricalFundamentalAdapter", Adapter), \
             self.assertRaisesRegex(EPSPeriodNotAvailable, "FUNDAMENTAL_EPS_PERIOD_NOT_AVAILABLE:2026Q2"):
            a.acquire_fundamentals(["1000"], "TWSE", self.plan, self.root, time.monotonic())
        self.assertEqual(calls, 2)

    def test_multiple_no_data_quarters_do_not_authorize_even_one_skip(self):
        import time
        base = material(self.plan)["fundamental"]
        calls = 0
        class Adapter:
            def __init__(self, **kwargs):
                self.row_failures = []
            def fetch_revenue_period(self, market, period):
                return [{**base["revenue"][0], "market": market, "revenue_period": period,
                         "official_disclosure_date": "2026-10-01"}]
            def fetch_eps_period(self, market, year, quarter):
                nonlocal calls
                calls += 1
                if calls <= 2:
                    raise EPSPeriodNotAvailable(f"{year}Q{quarter}")
                return [{**base["eps"][0], "market": market, "fiscal_year": year, "quarter": quarter,
                         "official_disclosure_date": "2026-10-01"}]
        with patch("src.sources.fundamental_history.MOPSHistoricalFundamentalAdapter", Adapter), \
             self.assertRaisesRegex(EPSPeriodNotAvailable, "FUNDAMENTAL_EPS_PERIOD_NOT_AVAILABLE:2026Q3"):
            a.acquire_fundamentals(["1000"], "TWSE", self.plan, self.root, time.monotonic())
        self.assertEqual(calls, 1)

    def test_formal_fundamental_acquisition_is_exact_main_implementation(self):
        import ast
        import inspect
        import subprocess
        original = subprocess.check_output(["git", "-C", str(h.ROOT), "show",
            "40c00f300d6ba64ca06850ba172fd1df222d1c86:src/full_market_history_acquisition.py"]).decode()
        expected = next(node for node in ast.parse(original).body
                        if isinstance(node, ast.FunctionDef) and node.name == 'acquire_fundamentals')
        current = ast.parse(inspect.getsource(a.acquire_fundamentals)).body[0]
        self.assertEqual(ast.dump(current), ast.dump(expected))


if __name__ == "__main__":
    unittest.main()
