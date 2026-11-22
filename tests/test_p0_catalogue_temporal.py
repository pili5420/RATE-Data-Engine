from __future__ import annotations

import unittest
from src.p0_catalogue_temporal import (
    assess_classification_source_date, require_classification_admission,
)


class ClassificationDateSemanticsTests(unittest.TestCase):
    def test_exact_update_date_retains_frozen_pass(self):
        evidence = require_classification_admission(
            trading_date="2026-11-20", source_update_date="2026-11-20")
        self.assertEqual(evidence["admission"], "PASS")
        self.assertEqual(evidence["classification_date_role"],
                         "ISIN_PAGE_DATE_STOCK_UPDATED_NOT_TRADING_DATE")

    def test_prior_and_future_update_dates_remain_blocked(self):
        for source_date, direction in (
            ("2026-11-19", "SOURCE_BEFORE_TARGET"),
            ("2026-11-21", "SOURCE_AFTER_TARGET"),
        ):
            with self.subTest(source_date=source_date):
                evidence = assess_classification_source_date(
                    trading_date="2026-11-20", source_update_date=source_date)
                self.assertEqual(evidence["comparison"], direction)
                self.assertEqual(evidence["admission"], "BLOCK")
                with self.assertRaisesRegex(RuntimeError, "^STALE_OR_FUTURE_CATALOGUE$"):
                    require_classification_admission(
                        trading_date="2026-11-20", source_update_date=source_date)

    def test_invalid_dates_never_pass(self):
        for day in ("2026-11-40", "not-a-date", "2026-02-30"):
            with self.assertRaises(ValueError):
                require_classification_admission(
                    trading_date="2026-11-20", source_update_date=day)


if __name__ == "__main__":
    unittest.main()
