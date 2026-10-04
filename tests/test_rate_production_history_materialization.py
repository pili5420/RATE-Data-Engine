import json
import shutil
import unittest
from pathlib import Path

from scripts.materialize_production_history_store import materialize


APPROVED_UNIVERSE = [
    "3231", "6274", "3443", "6669", "2313", "2449", "3413", "3081", "6187", "2368",
    "6442", "3017", "2345", "3661", "3037", "2383", "2317", "2330", "2376", "2356",
    "5388", "2344", "2337", "2408", "3035", "3034", "6510", "3036", "3014", "3227",
]


class FakeTWSEAdapter:
    def fetch_historical_symbol(self, symbol, period):
        return {
            "raw_payload": [
                {
                    "Date": "20261001",
                    "OpeningPrice": "10",
                    "HighestPrice": "12",
                    "LowestPrice": "9",
                    "ClosingPrice": "11",
                    "TradeVolume": "1000",
                    "TradeValue": "11000",
                }
            ],
            "source_timestamp": "2026-10-02T10:00:00Z",
            "retrieval_timestamp": "2026-10-02T10:01:00Z",
        }

    def fetch_historical_benchmark(self, period):
        return {
            "raw_payload": [{"trade_date": "2026-10-01", "close": "20000"}],
            "source_timestamp": "2026-10-02T10:00:00Z",
            "retrieval_timestamp": "2026-10-02T10:01:00Z",
        }


class FakeTPExAdapter:
    def fetch_historical_symbol(self, symbol, period):
        return {
            "raw_payload": {
                "code": symbol,
                "tables": [
                    {
                        "subtitle": symbol,
                        "fields": ["Date", "Open", "High", "Low", "Close", "Trade unit", "Trade Amt.(NTD1000)"],
                        "data": [["2026/10/01", "10", "12", "9", "11", "1000", "11000"]],
                    }
                ],
            },
            "source_timestamp": "2026-10-02T10:00:00Z",
            "retrieval_timestamp": "2026-10-02T10:01:00Z",
        }

    def fetch_historical_benchmark(self, period):
        return {
            "raw_payload": [{"trade_date": "2026-10-01", "close": "300"}],
            "source_timestamp": "2026-10-02T10:00:00Z",
            "retrieval_timestamp": "2026-10-02T10:01:00Z",
        }


class ProductionHistoryMaterializationTests(unittest.TestCase):
    def setUp(self):
        self.root = Path("artifacts/test_rate_production_history_materialization")
        shutil.rmtree(self.root, ignore_errors=True)
        self.root.mkdir(parents=True, exist_ok=True)
        self.contract = self.root / "contract.json"
        self.contract.write_text(
            json.dumps(
                {
                    "artifact": "RATE_PRODUCTION_UNIVERSE_CONTRACT",
                    "approved_universe": APPROVED_UNIVERSE,
                    "required_count": 30,
                    "validation_status": "PASS",
                }
            ),
            encoding="utf-8",
        )

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_materializes_exact_30_and_benchmarks_with_completed_sessions_only(self):
        history_root = self.root / "history"
        evidence = self.root / "evidence.json"
        result = materialize(
            trading_date="2026-10-02",
            universe_contract=self.contract,
            history_root=history_root,
            evidence_output=evidence,
            max_months=1,
            minimum_sessions=1,
            max_runtime_seconds=30,
            twse_adapter=FakeTWSEAdapter(),
            tpex_adapter=FakeTPExAdapter(),
        )
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["symbols_materialized"], 30)
        self.assertEqual(len(result["benchmark_rows"]), 2)
        self.assertFalse(result["fallback_used"])
        for symbol in APPROVED_UNIVERSE:
            rows = json.loads((history_root / "market_daily" / f"{symbol}.json").read_text(encoding="utf-8"))
            self.assertEqual(len(rows), 1)
            self.assertLess(rows[0]["trade_date"], "2026-10-02")
        for benchmark in ("TAIEX", "TPEX"):
            rows = json.loads((history_root / "benchmark" / f"{benchmark}.json").read_text(encoding="utf-8"))
            self.assertEqual(len(rows), 1)
            self.assertLess(rows[0]["trade_date"], "2026-10-02")

    def test_month_limit_fails_closed_instead_of_unbounded_loop(self):
        result = materialize(
            trading_date="2026-10-02",
            universe_contract=self.contract,
            history_root=self.root / "history",
            evidence_output=self.root / "evidence.json",
            max_months=1,
            minimum_sessions=2,
            max_runtime_seconds=30,
            twse_adapter=FakeTWSEAdapter(),
            tpex_adapter=FakeTPExAdapter(),
        )
        self.assertEqual(result["status"], "FAIL_CLOSED")
        self.assertIn("HARD_LIMIT_REACHED", result["blocking_reason"])
        self.assertFalse(result["fallback_used"])

    def test_runtime_limit_fails_closed(self):
        result = materialize(
            trading_date="2026-10-02",
            universe_contract=self.contract,
            history_root=self.root / "history",
            evidence_output=self.root / "evidence.json",
            max_months=1,
            minimum_sessions=1,
            max_runtime_seconds=0,
            twse_adapter=FakeTWSEAdapter(),
            tpex_adapter=FakeTPExAdapter(),
        )
        self.assertEqual(result["status"], "FAIL_CLOSED")
        self.assertEqual(result["blocking_reason"], "OFFICIAL_HISTORY_RUNTIME_HARD_LIMIT_REACHED")


if __name__ == "__main__":
    unittest.main()
