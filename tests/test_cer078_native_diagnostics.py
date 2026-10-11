"""Synthetic diagnostics tests; do not alter any historical acceptance assertion."""
import unittest
from src.cer078_native_diagnostics import Observer, SAFE_ENVIRONMENT, environment, test_ids


class DiagnosticsTests(unittest.TestCase):
    def test_environment_explicit_allowlist(self):
        value = environment()
        self.assertEqual(set(value["selected_nonsecret_environment"]), set(SAFE_ENVIRONMENT))
        for secret in ("FINMIND_TOKEN", "PATH", "AUTHORIZATION", "GITHUB_TOKEN"):
            self.assertNotIn(secret, value["selected_nonsecret_environment"])

    def test_exact_order_preserved(self):
        suite = unittest.defaultTestLoader.loadTestsFromNames([
            "tests.test_cer078_evening_1930", "tests.test_cer079_full_day_chain"])
        ids = test_ids(suite)
        self.assertEqual(len(ids), 8)
        self.assertTrue(all("CER078" in name for name in ids[:5]))
        self.assertTrue(all("CER079" in name for name in ids[5:]))

    def test_observer_does_not_replace_owner(self):
        import src.cer078_evening_1930 as owner
        before = owner.failure_gate_results
        observer = Observer(owner)
        observer.tool = 5
        with observer:
            self.assertIs(owner.failure_gate_results, before)
            observer.returned(before.__code__, 0, {"failure_closed_behavior": "FAIL"})
        self.assertIs(owner.failure_gate_results, before)
        self.assertEqual(observer.events[0]["result"]["failure_closed_behavior"], "FAIL")

    def test_foreign_exception_not_recorded(self):
        import src.cer078_evening_1930 as owner
        observer = Observer(owner)
        observer.raised(self.test_foreign_exception_not_recorded.__code__, 0, ValueError("foreign"))
        self.assertEqual(observer.events, [])


if __name__ == "__main__": unittest.main()
