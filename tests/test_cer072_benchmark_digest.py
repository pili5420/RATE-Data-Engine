import unittest

from scripts.run_cer072_acceptance import _assert_benchmark_digest_binding
from src.benchmark_history import benchmark_digest


class CER072BenchmarkDigestContractTests(unittest.TestCase):
    def setUp(self):
        self.row = {
            "benchmark_symbol": "TAIEX",
            "market": "TWSE",
            "trade_date": "2026-09-18",
            "open": 27000.0,
            "high": 27100.0,
            "low": 26900.0,
            "close": 27050.0,
            "source": "TWSE official",
            "source_timestamp": "2026-09-18T08:00:00Z",
            "ingested_at": "2026-09-18T08:01:00Z",
        }

    def test_volatile_lineage_metadata_does_not_change_accepted_digest(self):
        accepted = benchmark_digest([self.row])
        replay = {**self.row, "source_timestamp": "2026-09-19T01:00:00Z", "ingested_at": "2026-09-19T01:01:00Z"}
        self.assertEqual(benchmark_digest([replay]), accepted)
        self.assertEqual(_assert_benchmark_digest_binding([replay], accepted, "TAIEX"), accepted)

    def test_substantive_mutations_change_digest_and_fail_binding(self):
        accepted = benchmark_digest([self.row])
        for field, changed in (
            ("trade_date", "2026-09-17"),
            ("close", 27051.0),
            ("benchmark_symbol", "OTHER"),
            ("market", "TPEX"),
        ):
            with self.subTest(field=field):
                mutated = {**self.row, field: changed}
                self.assertNotEqual(benchmark_digest([mutated]), accepted)
                with self.assertRaisesRegex(RuntimeError, "RESTORED_TAIEX_HISTORY_DIGEST_MISMATCH"):
                    _assert_benchmark_digest_binding([mutated], accepted, "TAIEX")


if __name__ == "__main__":
    unittest.main()
