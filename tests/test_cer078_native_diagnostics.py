"""Synthetic diagnostics tests; do not alter any historical acceptance assertion."""
import unittest
import hashlib
import json
import os
from pathlib import Path
import tempfile
from unittest.mock import patch
from src.cer078_native_diagnostics import Observer, SAFE_ENVIRONMENT, environment, test_ids
from src.cer078_native_diagnostics import TERMINAL_SUBGATES, summaries


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

    def test_actual_terminal_failure_auto_captures_complete_envelope(self):
        import src.cer078_evening_1930 as owner
        from tests.test_cer078_evening_1930 import CER078Evening1930Tests
        fixture = CER078Evening1930Tests()
        fixture.setUp()
        before = Path(owner.__file__).read_bytes()
        original = owner.failure_gate_results
        def inject(*args):
            value = original(*args)
            return {**value, "failure_closed_behavior": "FAIL"}
        context = {"environment": environment(), "execution_head": "a"*40,
                   "test_order": ["synthetic-terminal"], "artifact_output": "synthetic"}
        try:
            with tempfile.TemporaryDirectory(prefix="dt-", dir=Path.cwd().parent) as directory:
                log = Path(directory) / "events.jsonl"
                observer = Observer(owner, context=context, event_path=log)
                observer.tool = 5
                observer.test_id = self.id()
                with observer, patch.object(owner, "failure_gate_results", side_effect=inject):
                    with self.assertRaisesRegex(RuntimeError, "^CER078_TERMINAL_GATE_FAIL$"):
                        fixture.test_evening_acceptance_artifacts_pass()
                    persisted = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
                event = next(e for e in persisted if "terminal_subgate_vector" in e)
                self.assertEqual(set(event["terminal_subgate_vector"]), set(TERMINAL_SUBGATES))
                self.assertFalse(event["terminal_subgate_vector"]["failure_closed_behavior"])
                self.assertEqual(len(event["terminal_vector_raw"]), 16)
                self.assertTrue(event["all_gate_values"])
                self.assertTrue(event["relevant_artifact_content_hashes"])
                self.assertTrue(event["relevant_artifact_file_hashes"])
                identities = event["state_source_bundle_identities"]
                for key in ("previous_1200/current_state_id", "dry_a/current_state_id",
                            "snapshot/input_snapshot_id", "snapshot/source_bundle_hash"):
                    self.assertIn(key, identities)
                self.assertEqual(event["test_id"], self.id())
                self.assertEqual(event["context"], context)
                self.assertTrue(event["timestamp"])
                self.assertTrue(event["paths"]["state_root"])
                self.assertFalse(observer.diagnostic_errors)
            self.assertEqual(Path(owner.__file__).read_bytes(), before)
        finally:
            fixture.tearDown()

    def test_diagnostic_read_failure_does_not_escape(self):
        import src.cer078_evening_1930 as owner
        observer = Observer(owner)
        with patch.object(observer, "record", side_effect=PermissionError("synthetic")):
            observer.raised(owner.build_cer078_artifacts.__code__, 0, RuntimeError("other"))
        self.assertEqual(observer.diagnostic_errors[0]["error_type"], "PermissionError")

    def test_return_diagnostic_failure_does_not_escape(self):
        import src.cer078_evening_1930 as owner
        observer = Observer(owner)
        with patch.object(observer, "record", side_effect=OSError("synthetic")):
            observer.returned(owner.failure_gate_results.__code__, 0, {"failure_closed_behavior": "FAIL"})
        self.assertEqual(observer.diagnostic_errors[0]["error_type"], "OSError")

    def test_event_output_is_exclusive(self):
        import src.cer078_evening_1930 as owner
        with tempfile.TemporaryDirectory(prefix="dt-", dir=Path.cwd().parent) as directory:
            path = Path(directory) / "events.jsonl"
            path.write_bytes(b"original")
            with self.assertRaises(FileExistsError):
                with Observer(owner, event_path=path): pass
            self.assertEqual(path.read_bytes(), b"original")

    def test_gate_summaries_keep_false_and_failed_values(self):
        gates, identities = {}, {}
        summaries({"failure_gates": {"a": "FAIL", "b": False}, "count_count": 1}, "", gates, identities)
        self.assertEqual(gates["/failure_gates/a"], "FAIL")
        self.assertIs(gates["/failure_gates/b"], False)
        self.assertEqual(gates["/count_count"], 1)

    def test_identity_summaries_include_bundle_and_state(self):
        gates, identities = {}, {}
        summaries({"bundle_id": "bundle", "source_snapshot_id": "snapshot", "previous_state_id": "prev"}, "", gates, identities)
        self.assertEqual(len(identities), 3)

    def test_sensitive_environment_not_dumped(self):
        with patch.dict(os.environ, {"FINMIND_TOKEN": "synthetic-secret", "GITHUB_TOKEN": "synthetic-secret"}):
            self.assertNotIn("synthetic-secret", json.dumps(environment()))

    def test_summary_does_not_mutate_inputs(self):
        value = {"failure_gates": {"a": "FAIL"}, "current_state_id": "id"}
        before = json.dumps(value)
        summaries(value, "", {}, {})
        self.assertEqual(json.dumps(value), before)

    def test_artifact_hash_is_content_bound(self):
        from src.cer078_native_diagnostics import digest
        self.assertEqual(digest({"a": 1, "b": 2}), digest({"b": 2, "a": 1}))
        self.assertNotEqual(digest({"a": 1}), digest({"a": 2}))

    def test_production_modules_do_not_import_diagnostics(self):
        import subprocess
        files = subprocess.check_output(["git", "ls-tree", "-r", "--name-only", "d419c545f075b93e994d4b732c754e8fa77b1eed"]).decode().splitlines()
        for name in files:
            if name.endswith(".py") and (name.startswith("src/") or name.startswith("scripts/")):
                self.assertNotIn(b"cer078_native_diagnostics", Path(name).read_bytes(), name)


if __name__ == "__main__": unittest.main()
