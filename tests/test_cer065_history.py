import hashlib
import json
import shutil
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from scripts import align_twse_taiex_history as aligner
from scripts import bootstrap_taiex_history as taiex_bootstrap
from scripts import build_historical_state_manifest as manifest
from scripts import materialize_twse_history as materializer
from src.historical_store import PersistentHistoricalStore
from src.benchmark_history import benchmark_digest, normalize_benchmark


def _stock_rows(symbol, count=195, market="TWSE"):
    start = date(2025, 1, 1)
    rows = []
    for i in range(count):
        d = (start + timedelta(days=i)).isoformat()
        rows.append({"symbol": symbol, "market": market, "trade_date": d, "open": 10.0, "high": 11.0, "low": 9.0, "close": 10.5, "volume": 1000.0, "turnover": 10500.0, "source": "TWSE_STOCK_DAY", "source_timestamp": "2026-09-18T00:00:00Z", "ingested_at": "2026-09-18T00:00:00Z"})
    return rows


class Cer065HistoryTests(unittest.TestCase):
    def setUp(self):
        self.root = Path("artifacts/test_cer065_history")
        shutil.rmtree(self.root, ignore_errors=True)
        self.root.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _universe(self, symbols=None):
        symbols = symbols or [str(1000 + i) for i in range(25)]
        path = self.root / "universe.json"
        path.write_text(json.dumps({"universe_symbol_digest": "u", "symbols": [{"symbol": s, "market": "TWSE"} for s in symbols]}), encoding="utf-8")
        return path, symbols

    def test_store_retention_and_retained_subset_identity(self):
        store = PersistentHistoricalStore(self.root / "history")
        rows = _stock_rows("1000", 240)
        out = store.materialize_stock("1000", rows)
        self.assertEqual(out["record_count"], 220)
        self.assertEqual(out["trimmed_count"], 20)
        self.assertEqual(store.load_stock("1000"), rows[-220:])

    def test_store_duplicate_date_fail_closed(self):
        store = PersistentHistoricalStore(self.root / "history")
        rows = _stock_rows("1000", 180)
        with self.assertRaises(ValueError):
            store.materialize_stock("1000", rows + [rows[0]])

    def test_materialization_accepted_checkpoint_and_identity(self):
        universe_path, symbols = self._universe()
        months = {}
        for symbol in symbols:
            records = _stock_rows(symbol)
            months[f"{symbol}:202501"] = {"symbol": symbol, "market": "TWSE", "records": records}
        checkpoint = {"content_hash": "accepted", "months": months}
        with patch.object(materializer, "validate_checkpoint", return_value={"checkpoint": checkpoint}):
            result = materializer.materialize(checkpoint=self.root / "checkpoint.json", universe_file=universe_path, history_root=self.root / "history", output=self.root / "materialization.json", expected_checkpoint_digest="accepted")
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["content_identity_status"], "25/25 PASS")
        self.assertEqual(result["twse_network_requests_for_stock_backfill"], 0)

    def test_materialization_rejects_checkpoint_identity(self):
        universe_path, symbols = self._universe()
        checkpoint = {"content_hash": "wrong", "months": {}}
        with patch.object(materializer, "validate_checkpoint", return_value={"checkpoint": checkpoint}):
            with self.assertRaisesRegex(RuntimeError, "TWSE_ACCEPTED_CHECKPOINT_IDENTITY_MISMATCH"):
                materializer.materialize(checkpoint=self.root / "checkpoint.json", universe_file=universe_path, history_root=self.root / "history", output=self.root / "materialization.json", expected_checkpoint_digest="accepted")

    def test_taiex_normalization_supports_official_chinese_fields(self):
        row = normalize_benchmark({"日期": "115/09/16", "開盤指數": "25000", "最高指數": "25100", "最低指數": "24900", "收盤指數": "25050"}, benchmark_symbol="TAIEX", market="TWSE", source="TWSE_TAIEX_MI_5MINS_HIST", source_timestamp="x", ingested_at="x")
        self.assertEqual(row["trade_date"], "2026-09-16")
        self.assertEqual(row["close"], 25050.0)

    def test_taiex_digest_excludes_volatile_lineage_timestamps(self):
        base = {"benchmark_symbol": "TAIEX", "market": "TWSE", "trade_date": "2026-09-16", "close": 25050.0, "source": "TWSE_TAIEX_MI_5MINS_HIST"}
        a = {**base, "source_timestamp": "2026-09-16T00:00:00Z", "ingested_at": "2026-09-16T00:01:00Z"}
        b = {**base, "source_timestamp": "2026-09-18T00:00:00Z", "ingested_at": "2026-09-18T00:01:00Z"}
        self.assertEqual(benchmark_digest([a]), benchmark_digest([b]))

    def test_taiex_monthly_cache_deduplicates_requests(self):
        periods = []
        class FakeAdapter:
            def fetch_historical_benchmark(self, period):
                periods.append(period)
                year, month = int(period[:4]), int(period[4:])
                rows = [[f"{year}/{month:02d}/{day:02d}", "25000", "25100", "24900", str(25000 + day)] for day in range(1, 16)]
                return {"raw_payload": {"fields": ["日期", "開盤指數", "最高指數", "最低指數", "收盤指數"], "data": rows}, "source_timestamp": "x", "retrieval_timestamp": "x"}
        with patch.object(taiex_bootstrap, "TWSEAdapter", FakeAdapter):
            result = taiex_bootstrap.bootstrap(trading_date="2026-09-16", checkpoint=self.root / "taiex.json", history_root=self.root / "history", output=self.root / "taiex-evidence.json", max_months=20)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["request_count"], len(periods))
        self.assertEqual(len(periods), len(set(periods)))
        self.assertGreaterEqual(result["record_count"], 180)

    def test_alignment_is_exact_date_inner_join_without_carry_forward(self):
        universe_path, symbols = self._universe()
        history = self.root / "history"
        (history / "market_daily").mkdir(parents=True)
        (history / "benchmark").mkdir(parents=True)
        benchmark = [{"benchmark_symbol": "TAIEX", "market": "TWSE", "trade_date": (date(2025, 1, 1) + timedelta(days=i)).isoformat(), "close": 25000.0, "source": "x", "source_timestamp": "x", "ingested_at": "x"} for i in range(195)]
        (history / "benchmark" / "TAIEX.json").write_text(json.dumps(benchmark), encoding="utf-8")
        for symbol in symbols:
            (history / "market_daily" / f"{symbol}.json").write_text(json.dumps(_stock_rows(symbol)), encoding="utf-8")
        result = aligner.align(universe_file=universe_path, history_root=history, output=self.root / "alignment.json")
        self.assertEqual(result["twse_taiex_alignment"], "25/25")
        self.assertFalse(result["carry_forward_used"])

    def test_alignment_under_180_fails_closed(self):
        universe_path, symbols = self._universe()
        history = self.root / "history"
        (history / "market_daily").mkdir(parents=True)
        (history / "benchmark").mkdir(parents=True)
        benchmark = [{"trade_date": (date(2025, 1, 1) + timedelta(days=i)).isoformat()} for i in range(180)]
        (history / "benchmark" / "TAIEX.json").write_text(json.dumps(benchmark), encoding="utf-8")
        for i, symbol in enumerate(symbols):
            (history / "market_daily" / f"{symbol}.json").write_text(json.dumps(_stock_rows(symbol, 179 if i == 0 else 180)), encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "DATA_INCOMPLETE:EXACT_DATE_BENCHMARK_ALIGNMENT"):
            aligner.align(universe_file=universe_path, history_root=history, output=self.root / "alignment.json")

    def test_manifest_reads_canonical_store_and_keeps_tpex_not_run(self):
        universe_path, symbols = self._universe()
        history = self.root / "history"
        (history / "market_daily").mkdir(parents=True)
        (history / "benchmark").mkdir(parents=True)
        benchmark = [{"trade_date": (date(2025, 1, 1) + timedelta(days=i)).isoformat()} for i in range(195)]
        (history / "benchmark" / "TAIEX.json").write_text(json.dumps(benchmark), encoding="utf-8")
        for symbol in symbols:
            (history / "market_daily" / f"{symbol}.json").write_text(json.dumps(_stock_rows(symbol)), encoding="utf-8")
        checkpoint = self.root / "checkpoint.json"
        checkpoint.write_text(json.dumps({"content_hash": "accepted"}), encoding="utf-8")
        result = manifest.build(universe_file=universe_path, checkpoint=checkpoint, history_root=history, output=self.root / "manifest.json")
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["TPEx_stock_component"], "NOT_RUN")
        self.assertEqual(result["full_historical_acceptance"], "HOLD")

    def test_checkpoint_remaining_work_semantics_fields_are_distinct(self):
        from scripts.bootstrap_live_history import _evidence
        self.assertIn("periods_remaining_to_target", _evidence.__code__.co_consts)


if __name__ == "__main__":
    unittest.main()
