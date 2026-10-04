import json
import os
import shutil
import unittest
import sys
from pathlib import Path
from unittest.mock import patch

from src.sources import tpex
from src.sources.fundamental import FundamentalAdapter
from src.historical_store import align_histories
from scripts import build_live_source_bundle as live_builder
from scripts import probe_official_sources


class _Response:
    status = 200
    headers = {"Content-Type": "application/json"}
    def __init__(self, body): self.body = body
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def read(self): return self.body


class CER057TPExTests(unittest.TestCase):
    def test_tpex_daily_normalization(self):
        out = tpex.TPExAdapter.normalize_daily({"SecuritiesCompanyCode": "6274", "Date": "1150916", "Open": "100", "High": "101", "Low": "99", "Close": "100.5", "TradingShares": "10", "TransactionAmount": "1000"})
        self.assertEqual(out["symbol"], "6274")
        self.assertEqual(out["source"], "TPEx Official OpenAPI")

    def test_historical_route_is_official_individual_stock_contract(self):
        self.assertIn("afterTrading/tradingStock", tpex.HISTORICAL_ENDPOINT)
        self.assertEqual(tpex._period_date("202609"), "2026/09/01")

    def test_incomplete_read_retries_then_passes(self):
        calls = []
        def fake(_req, timeout=30):
            calls.append(timeout)
            if len(calls) == 1:
                from http.client import IncompleteRead
                raise IncompleteRead(b"{")
            return _Response(b'[{"SecuritiesCompanyCode":"6274"}]')
        with patch.object(tpex, "urlopen", side_effect=fake), patch.object(tpex.time, "sleep"):
            payload, digest, diagnostics = tpex._resilient_json("https://example.invalid")
        self.assertEqual(len(payload), 1)
        self.assertEqual(diagnostics["attempt"], 2)

    def test_truncated_response_rejected(self):
        from http.client import IncompleteRead
        with patch.object(tpex, "urlopen", side_effect=IncompleteRead(b"{")), patch.object(tpex.time, "sleep"):
            with self.assertRaisesRegex(RuntimeError, "TPEX_HISTORICAL_RETRIEVAL_FAILED"):
                tpex._resilient_json("https://example.invalid", retries=2)

    def test_current_daily_truncated_then_valid_passes(self):
        calls = []
        valid = b'[{"SecuritiesCompanyCode":"6274","Date":"1151002","LatestPrice":"100"}]'
        def fake(req, timeout=30):
            calls.append(req.full_url)
            if len(calls) == 1:
                return _Response(b'[{"SecuritiesCompanyCode":"6274"')
            return _Response(valid)
        with patch.object(tpex, "urlopen", side_effect=fake), patch.object(tpex.time, "sleep"):
            result = tpex.TPExAdapter().fetch_daily()
        self.assertEqual(result["endpoint"], tpex.CURRENT_DAILY_ENDPOINT)
        self.assertEqual(result["diagnostics"]["http_status"], 200)
        self.assertEqual(result["diagnostics"]["parse_status"], "PASS")
        self.assertEqual(result["diagnostics"]["attempt_count"], 2)
        self.assertEqual(result["diagnostics"]["record_count"], 1)
        self.assertEqual(calls, [tpex.CURRENT_DAILY_ENDPOINT, tpex.CURRENT_DAILY_ENDPOINT])

    def test_current_daily_first_two_fail_third_valid_passes(self):
        calls = []
        valid = b'[{"SecuritiesCompanyCode":"6274","Date":"1151002","LatestPrice":"100"}]'
        def fake(req, timeout=30):
            calls.append(req.full_url)
            if len(calls) < 3:
                return _Response(b'[{"SecuritiesCompanyCode":"6274"')
            return _Response(valid)
        with patch.object(tpex, "urlopen", side_effect=fake), patch.object(tpex.time, "sleep"):
            result = tpex.TPExAdapter().fetch_daily()
        self.assertEqual(result["diagnostics"]["attempt_count"], 3)
        self.assertEqual(result["diagnostics"]["parse_status"], "PASS")
        self.assertEqual(calls, [tpex.CURRENT_DAILY_ENDPOINT] * 3)

    def test_current_daily_all_invalid_fails_closed_without_fallback(self):
        calls = []
        def fake(req, timeout=30):
            calls.append(req.full_url)
            return _Response(b'[{"SecuritiesCompanyCode":"6274"')
        with patch.object(tpex, "urlopen", side_effect=fake), patch.object(tpex.time, "sleep"):
            with self.assertRaisesRegex(RuntimeError, "TPEX_CURRENT_DAILY_RETRIEVAL_FAILED"):
                tpex.TPExAdapter().fetch_daily()
        self.assertEqual(calls, [tpex.CURRENT_DAILY_ENDPOINT] * 3)
        self.assertNotIn(tpex.HISTORICAL_ENDPOINT, calls)
        self.assertNotIn(tpex.LEGACY_DIAGNOSTIC_REFERENCE, calls)

    def test_current_daily_does_not_modify_historical_store_seed(self):
        root = Path("artifacts/test-current-daily-history-store")
        shutil.rmtree(root, ignore_errors=True)
        seed = root / "benchmark" / "TPEX.json"
        seed.parent.mkdir(parents=True, exist_ok=True)
        seed.write_text(json.dumps({"seed": "approved"}), encoding="utf-8")
        before = seed.read_text(encoding="utf-8")
        valid = b'[{"SecuritiesCompanyCode":"6274","Date":"1151002","LatestPrice":"100"}]'
        try:
            with patch.dict(os.environ, {"RATE_OFFICIAL_HISTORY_STORE_ROOT": str(root)}), \
                 patch.object(tpex, "urlopen", return_value=_Response(valid)), \
                 patch.object(tpex.time, "sleep"):
                result = tpex.TPExAdapter().fetch_daily()
            self.assertEqual(result["diagnostics"]["parse_status"], "PASS")
            self.assertEqual(seed.read_text(encoding="utf-8"), before)
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_benchmark_contract(self):
        adapter = tpex.TPExAdapter()
        with patch.object(tpex, "_resilient_json", return_value=([{"Date":"1150916","Close":"100"}], "abc", {"attempt":1})), patch.dict(os.environ, {}, clear=True):
            out = adapter.fetch_historical_benchmark("202609")
        self.assertEqual(out["benchmark_symbol"], "TPEX")
        self.assertEqual(out["benchmark_name"], "TPEx Index")

    def test_exact_date_alignment(self):
        stock=[{"symbol":"6274","market":"TPEX","trade_date":"2026-09-15","close":1,"open":1,"high":1,"low":1,"volume":1,"turnover":1,"source":"x","source_timestamp":"x","ingested_at":"x"}]
        bench=[{"benchmark_symbol":"TPEX","market":"TPEX","trade_date":"2026-09-15","close":1,"source":"x","source_timestamp":"x","ingested_at":"x"}]
        self.assertEqual(len(align_histories(stock, bench)), 1)

    def test_otc_fundamental_routes(self):
        a = FundamentalAdapter()
        self.assertIn("mopsfin_t187ap05_O", a.OTC_REVENUE_ENDPOINT)
        self.assertTrue(all("mopsfin_t187ap06_O_" in x for x in a.OTC_EPS_ENDPOINTS))

    def test_source_registry_market_coverage(self):
        reg=json.loads(Path("config/SOURCE_REGISTRY.json").read_text(encoding="utf-8"))
        text=json.dumps(reg,ensure_ascii=False)
        self.assertIn("TWSE_HISTORICAL_STOCK", text)
        self.assertIn("TPEX_HISTORICAL_STOCK", text)
        self.assertIn("TPEX_INDEX_BENCHMARK", text)
        self.assertIn("TPEX_OTC_FUNDAMENTAL", text)

    def test_institutional_history_does_not_repeat_snapshot(self):
        class NoHistory:
            def fetch_institutional_history(self, *args): raise RuntimeError("unavailable")
        with self.assertRaisesRegex(RuntimeError, "STAGE_LOOKBACK_TPEX_26_SESSIONS"):
            live_builder._tpex_institutional_history(NoHistory(), ["6274"], {"6274": []}, "2026-09-16")

    def test_required_tpex_failure_propagates_overall_probe(self):
        def fake_probe(source, endpoint, parser):
            return {"source": source, "parse_status": "FAIL:IncompleteRead" if source == "TPEX_HISTORICAL_STOCK" else "PASS"}
        out = Path("artifacts/test_cer057_probe.json")
        argv = ["probe_official_sources.py", "--trading-date", "2026-09-16", "--output", str(out), "--universe-file", "config/staging/RATE_STAGING_LIVE_UNIVERSE_V1.json"]
        try:
            with patch.object(probe_official_sources, "probe", side_effect=fake_probe), patch.object(sys, "argv", argv):
                self.assertEqual(probe_official_sources.main(), 1)
            obj = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(obj["status"], "FAIL")
            self.assertEqual(obj["tpex_source_capability"], "FAIL")
        finally:
            out.unlink(missing_ok=True)


if __name__ == "__main__": unittest.main()
