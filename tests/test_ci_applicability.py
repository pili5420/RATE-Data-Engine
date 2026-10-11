"""Synthetic applicability tests; historical assertions are not changed."""
import unittest
from scripts.verify_ci_applicability import ALLOWED, HISTORICAL_BASE, applicability, verdict, network_guard

MAIN = "6" * 40
HEAD = "a" * 40


class ApplicabilityTests(unittest.TestCase):
    def test_historical_exact_scope_uses_strict(self):
        self.assertEqual(applicability(HISTORICAL_BASE, HEAD, HISTORICAL_BASE, MAIN,
                         ["src/phase2_production.py"], True), "HISTORICAL_STRICT_GATE")

    def test_historical_scope_cannot_hide_new_cr(self):
        with self.assertRaisesRegex(ValueError, "CURRENT_MAIN_BASE_REQUIRED"):
            applicability(HISTORICAL_BASE, HEAD, HISTORICAL_BASE, MAIN, ["src/new_owner.py"], True)

    def test_current_main_publisher_requires_replacement(self):
        self.assertEqual(applicability(MAIN, HEAD, MAIN, MAIN,
                         ["scripts/publish_production_source_bundle_latest.py", "src/new_owner.py"], True),
                         "CURRENT_MAIN_COMPATIBILITY_GATE")

    def test_current_main_diagnostics_requires_replacement(self):
        self.assertEqual(applicability(MAIN, HEAD, MAIN, MAIN, ["src/cer078_native_diagnostics.py"], True),
                         "CURRENT_MAIN_COMPATIBILITY_GATE")

    def test_dirty_rejected(self):
        with self.assertRaises(ValueError): applicability(MAIN, HEAD, MAIN, MAIN, ["x"], False)

    def test_wrong_merge_base_rejected(self):
        with self.assertRaises(ValueError): applicability(MAIN, HEAD, "b"*40, MAIN, ["x"], True)

    def test_stale_main_rejected(self):
        with self.assertRaises(ValueError): applicability(MAIN, HEAD, MAIN, "b"*40, ["x"], True)

    def test_empty_delta_rejected(self):
        with self.assertRaises(ValueError): applicability(MAIN, HEAD, MAIN, MAIN, [], True)

    def test_replacement_failure_cannot_pass(self):
        self.assertEqual(verdict("CURRENT_MAIN_COMPATIBILITY_GATE", False, True), "BLOCKED")
        self.assertEqual(verdict("CURRENT_MAIN_COMPATIBILITY_GATE", True, False), "BLOCKED")

    def test_strict_pass_identity(self):
        self.assertEqual(verdict("HISTORICAL_STRICT_GATE", True, True), "APPLICABLE_STRICT_PASS")

    def test_replacement_pass_identity(self):
        self.assertEqual(verdict("CURRENT_MAIN_COMPATIBILITY_GATE", True, True),
                         "NOT_APPLICABLE_REPLACED_BY_CURRENT_MAIN_GATE_PASS")

    def test_network_forbidden_fixture_only(self):
        network_guard("urllib.Request", ("file:///synthetic.json",))
        with self.assertRaises(Exception): network_guard("socket.connect", ())
        self.assertIn("scripts/verify_phase2_compatibility.py", ALLOWED)


if __name__ == "__main__": unittest.main()
