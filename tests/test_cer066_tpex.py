import json
import shutil
import unittest
from datetime import date, timedelta
from pathlib import Path

from scripts import bootstrap_tpex_history as stock_bootstrap
from scripts import materialize_tpex_history as stock_materializer
from scripts import bootstrap_tpex_index as index_bootstrap
from scripts import align_tpex_index_history as index_aligner
from scripts import build_historical_state_manifest as manifest
from src.benchmark_history import benchmark_digest
from src.sources.tpex import normalize_tpex_date


def _months(start_year=2026, start_month=9, count=22):
    out=[]; y=start_year; m=start_month
    for _ in range(count):
        out.append(f"{y:04d}{m:02d}")
        m -= 1
        if m == 0: y -= 1; m = 12
    return out


def _stock_row(symbol, period, day):
    y, m = int(period[:4]), int(period[4:6])
    return {"symbol": symbol, "trade_date": f"{y:04d}-{m:02d}-{day:02d}", "open": "10", "high": "11", "low": "9", "close": "10.5", "volume": "1000", "turnover": "10000"}


def _index_row(period, day):
    y, m = int(period[:4]), int(period[4:6])
    return {"Date": f"{y:04d}/{m:02d}/{day:02d}", "Open": "400", "High": "410", "Low": "390", "Close": "405"}


class _StockAdapter:
    calls = []
    def fetch_historical_symbol(self, symbol, period):
        self.calls.append(period)
        return {"endpoint": "official-test", "source_timestamp": "x", "retrieval_timestamp": "x", "raw_payload": [{**_stock_row(s, period, d)} for s in stock_bootstrap.TPEx_SYMBOLS for d in range(1, 11)]}


class _IndexAdapter:
    calls = []
    def fetch_historical_benchmark(self, period):
        self.calls.append(period)
        return {"endpoint": "official-index-test", "source_timestamp": "x", "retrieval_timestamp": "x", "raw_payload": [_index_row(period, d) for d in range(1, 11)]}


class Cer066TPExTests(unittest.TestCase):
    def setUp(self):
        self.root = Path("artifacts/test_cer066_tpex")
        shutil.rmtree(self.root, ignore_errors=True); self.root.mkdir(parents=True)
        _StockAdapter.calls=[]; _IndexAdapter.calls=[]

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_date_normalization_roc_and_gregorian(self):
        self.assertEqual(normalize_tpex_date("115/09/16"), "2026-09-16")
        self.assertEqual(normalize_tpex_date("20260916"), "2026-09-16")
        self.assertEqual(normalize_tpex_date("2026-09-16"), "2026-09-16")

    def test_monthly_shared_response_filters_and_deduplicates(self):
        period = "202609"; result = {"source_timestamp":"x", "retrieval_timestamp":"x", "raw_payload":[_stock_row(s, period, 1) for s in stock_bootstrap.TPEx_SYMBOLS]}
        rows = stock_bootstrap.extract_month_rows(result, stock_bootstrap.TPEx_SYMBOLS, period)
        self.assertEqual({r["symbol"] for r in rows}, set(stock_bootstrap.TPEx_SYMBOLS)); self.assertEqual(len(rows), 5)

    def test_response_identity_mismatch_fails_closed(self):
        result = {"raw_payload":[_stock_row("6274", "202608", 1)]}
        with self.assertRaisesRegex(RuntimeError, "TPEX_HISTORY_RESPONSE_IDENTITY_MISMATCH"):
            stock_bootstrap.extract_month_rows(result, stock_bootstrap.TPEx_SYMBOLS, "202609")

    def test_bootstrap_uses_one_request_per_month(self):
        cp=self.root/"cp.json"; ev=self.root/"ev.json"
        result=stock_bootstrap.bootstrap(trading_date="2026-09-18", checkpoint=cp, output=ev, max_months=22, adapter=_StockAdapter())
        self.assertEqual(result["status"], "PASS"); self.assertEqual(result["monthly_request_count"], len(set(_StockAdapter.calls))); self.assertEqual(result["monthly_request_deduplication"], "PASS")
        self.assertEqual(result["raw_coverage"], "5/5"); self.assertEqual(result["raw_sessions_ge_190"], "5/5")

    def test_materialization_persists_five_tpex_symbols(self):
        cp=self.root/"cp.json"; ev=self.root/"ev.json"; stock_bootstrap.bootstrap(trading_date="2026-09-18", checkpoint=cp, output=ev, max_months=22, adapter=_StockAdapter())
        out=stock_materializer.materialize(checkpoint=cp, history_root=self.root/"history", output=self.root/"mat.json")
        self.assertEqual(out["status"], "PASS"); self.assertEqual(out["materialized_symbols"], "5/5")
        for symbol in stock_bootstrap.TPEx_SYMBOLS:
            self.assertGreaterEqual(len(json.loads((self.root/"history"/"market_daily"/f"{symbol}.json").read_text())), 180)

    def test_index_contract_is_month_scoped_and_single_request_per_month(self):
        cp=self.root/"icp.json"; ev=self.root/"iev.json"
        result=index_bootstrap.bootstrap(trading_date="2026-09-18", checkpoint=cp, history_root=self.root/"history", output=ev, max_months=22, adapter=_IndexAdapter())
        self.assertEqual(result["status"], "PASS"); self.assertEqual(result["endpoint_contract"], "MONTH_SCOPED_HISTORICAL_PAGE"); self.assertEqual(result["redundant_requests"], 0); self.assertEqual(result["request_count"], len(set(_IndexAdapter.calls)))
        self.assertGreaterEqual(result["record_count"], 180)

    def test_benchmark_digest_ignores_lineage_timestamps(self):
        base={"benchmark_symbol":"TPEX","market":"TPEX","trade_date":"2026-09-16","close":405.0,"source":"x"}
        self.assertEqual(benchmark_digest([{**base,"source_timestamp":"a","ingested_at":"a"}]), benchmark_digest([{**base,"source_timestamp":"b","ingested_at":"b"}]))

    def test_exact_date_alignment_and_no_carry_forward(self):
        cp=self.root/"cp.json"; stock_bootstrap.bootstrap(trading_date="2026-09-18", checkpoint=cp, output=self.root/"ev.json", max_months=22, adapter=_StockAdapter()); stock_materializer.materialize(checkpoint=cp, history_root=self.root/"history", output=self.root/"mat.json")
        index_bootstrap.bootstrap(trading_date="2026-09-18", checkpoint=self.root/"icp.json", history_root=self.root/"history", output=self.root/"iev.json", max_months=22, adapter=_IndexAdapter())
        out=index_aligner.align(history_root=self.root/"history", output=self.root/"align.json")
        self.assertEqual(out["status"], "PASS"); self.assertFalse(out["carry_forward_used"]); self.assertEqual(out["tpex_index_alignment"], "5/5")

    def test_alignment_under_180_fails_closed(self):
        h=self.root/"history"; (h/"market_daily").mkdir(parents=True); (h/"benchmark").mkdir(parents=True)
        bench=[]
        for d in range(1,181): bench.append({"trade_date":f"2026-01-{d:02d}"}) if d <= 31 else None
        (h/"benchmark"/"TPEX.json").write_text(json.dumps(bench))
        for s in stock_bootstrap.TPEx_SYMBOLS: (h/"market_daily"/f"{s}.json").write_text(json.dumps([]))
        out=index_aligner.align(history_root=h, output=self.root/"align.json"); self.assertEqual(out["status"], "FAIL"); self.assertIn("DATA_INCOMPLETE:TPEX_EXACT_DATE_BENCHMARK_ALIGNMENT", out["blocking_reason"])

    def test_manifest_full_six_component_semantics_and_digest(self):
        h=self.root/"history"; (h/"market_daily").mkdir(parents=True); (h/"benchmark").mkdir(parents=True)
        symbols=[]
        for i in range(25):
            s=str(1000+i); symbols.append({"symbol":s,"market":"TWSE"}); (h/"market_daily"/f"{s}.json").write_text(json.dumps([{"trade_date":(date(2025,1,1)+timedelta(days=j)).isoformat()} for j in range(220)]))
        for s in stock_bootstrap.TPEx_SYMBOLS:
            symbols.append({"symbol":s,"market":"TPEX"}); (h/"market_daily"/f"{s}.json").write_text(json.dumps([{"trade_date":(date(2025,1,1)+timedelta(days=j)).isoformat(),"market":"TPEX"} for j in range(220)]))
        (h/"benchmark"/"TAIEX.json").write_text(json.dumps([{"trade_date":(date(2025,1,1)+timedelta(days=j)).isoformat()} for j in range(220)])); (h/"benchmark"/"TPEX.json").write_text(json.dumps([{"trade_date":(date(2025,1,1)+timedelta(days=j)).isoformat()} for j in range(220)]))
        u=self.root/"u.json"; u.write_text(json.dumps({"universe_symbol_digest":"u","symbols":symbols})); cp=self.root/"cp.json"; cp.write_text(json.dumps({"content_hash":"accepted"}))
        a=manifest.build(universe_file=u, checkpoint=cp, history_root=h, output=self.root/"m1.json"); b=manifest.build(universe_file=u, checkpoint=cp, history_root=h, output=self.root/"m2.json")
        self.assertEqual(a["full_historical_acceptance"], "PASS"); self.assertEqual(a["Stock_Historical_Coverage"], "30/30"); self.assertIsNotNone(a["RATE_FULL_HISTORICAL_STATE_DIGEST"]); self.assertEqual(a["RATE_FULL_HISTORICAL_STATE_DIGEST"], b["RATE_FULL_HISTORICAL_STATE_DIGEST"])


if __name__ == "__main__": unittest.main()
