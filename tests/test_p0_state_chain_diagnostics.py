from __future__ import annotations

import unittest
from src.p0_state_chain_diagnostics import blocked_predecessor_diagnostic

SEED = ("2026-10-02", "19:30")
POLICY = {"predecessor_trading_date": SEED[0], "predecessor_cadence": SEED[1]}


class PredecessorDiagnosticTests(unittest.TestCase):
    def test_missing_0730_predecessor_stays_blocked(self):
        evidence = blocked_predecessor_diagnostic(
            trading_date="2026-11-23", cadence="07:30",
            previous_legal_trading_day="2026-11-20",
            observed_slots=[SEED], approved_first_refresh=POLICY)
        self.assertEqual(evidence["expected_predecessor_trading_date"], "2026-11-20")
        self.assertEqual(evidence["expected_predecessor_cadence"], "19:30")
        self.assertFalse(evidence["expected_slot_present"])
        self.assertFalse(evidence["publication_permitted"])

    def test_incremental_slots_are_exact(self):
        for cadence, expected in (("09:30", "07:30"), ("12:00", "09:30")):
            with self.subTest(cadence=cadence):
                e = blocked_predecessor_diagnostic(
                    trading_date="2026-11-23", cadence=cadence,
                    previous_legal_trading_day="2026-11-20",
                    observed_slots=[SEED, ("2026-11-23", "07:30")],
                    approved_first_refresh=POLICY)
                self.assertEqual(e["expected_predecessor_cadence"], expected)
                self.assertFalse(e["publication_permitted"])

    def test_first_refresh_seed_is_candidate_not_permit(self):
        e = blocked_predecessor_diagnostic(
            trading_date="2026-11-23", cadence="19:30",
            previous_legal_trading_day="2026-11-20",
            observed_slots=[SEED], approved_first_refresh=POLICY)
        self.assertEqual(e["expected_predecessor_basis"],
                         "SINGLE_USE_FIRST_REFRESH_CANDIDATE_ONLY")
        self.assertFalse(e["first_refresh_authority_consumption_verified"])
        self.assertFalse(e["state_id_hash_verified"])

    def test_missing_all_never_fabricates_predecessor(self):
        e = blocked_predecessor_diagnostic(
            trading_date="2026-11-23", cadence="19:30",
            previous_legal_trading_day="2026-11-20",
            observed_slots=[], approved_first_refresh=POLICY)
        self.assertIsNone(e["expected_predecessor_trading_date"])
        self.assertFalse(e["publication_permitted"])


if __name__ == "__main__":
    unittest.main()
