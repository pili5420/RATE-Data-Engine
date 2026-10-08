"""Disk/cold-process codec regression. All materials synthetic, no HTTP."""
from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from src.eps_duration_facts.model import Rejected
from src.eps_duration_facts.raw import sha256
from src.provider_eps_candidate import _canonical, _json, _decimal
from src.provider_eps_coverage import initialize, make_plan, read_events, save, summary
from src.provider_eps_dispatch import DispatchGate, exclusive_scan
from src.provider_eps_handoff import handoff, verify_handoff
from src.provider_eps_metadata import read_metadata, read_intent, validate_dispatches
from tests.provider_eps_engineering_fixture import make_fixture
from tests.test_provider_eps_coverage import BINDING, engineering_universe
from tests import test_provider_eps_recovery as recovery_tests
from src.provider_eps_recovery import replay_archive

REPO = Path(__file__).resolve().parents[1]


class MetadataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="metadata-engineering-")
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        original = self.directory / "original"
        original.mkdir()
        make_fixture(original)
        universe = engineering_universe(self.directory / "historical.json")
        universe["stocks"].append({"symbol": "8888", "market": "TPEX"})
        universe["expected_market_counts"]["TPEX"] = 3
        save(self.directory / "universe.json", universe)
        self.universe = universe
        self.root = self.directory / "rate-eps-public-research" / "coverage"
        self.mode("normal")

    def mode(self, mode, **kwargs):
        (self.directory / "mock-config.json").write_bytes(_canonical({"mode": mode, **kwargs}))

    def worker(self, budget=1, expected=0):
        run = subprocess.run([sys.executable, "-B", str(REPO / "tests/provider_eps_cold_start_worker.py"),
            str(self.directory), str(budget)], cwd=REPO, capture_output=True, text=True)
        self.assertEqual(run.returncode, expected, run.stdout + run.stderr)
        return read_metadata(sorted((self.root / "reports").glob("*/execution.json"))[-1].read_bytes())

    def calls(self):
        path = self.directory / "mock-calls.jsonl"
        return [json.loads(s)["symbol"] for s in path.read_text().splitlines()] if path.exists() else []

    def intent(self):
        return self.root / "intents/7777.json"

    def test_old_decimal_reader_failure_same_disk_bytes_new_digest_pass(self):
        for value in (13, 13.0, 100.125, 1.3e1, 1.3125e-3):
            with self.subTest(value=value):
                body = _canonical({"time": value})
                path = self.directory / "reproduction.json"
                path.write_bytes(body)
                old = _json(path.read_bytes())
                if type(value) is float:
                    self.assertIsInstance(old["time"], Decimal)
                    with self.assertRaises(TypeError):
                        _canonical(old)
                else:
                    self.assertEqual(_canonical(old), body)
                self.assertEqual(sha256(_canonical(read_metadata(path.read_bytes()))), sha256(body))
                self.assertEqual(path.read_bytes(), body)

    def test_supported_scientific_notation_preserves_writer_numeric_types(self):
        self.assertEqual(read_metadata(b'{"a":13,"b":13.0,"c":1.3e1,"d":1.3125e-3}'),
                         {"a": 13, "b": 13.0, "c": 13.0, "d": 0.0013125})
        self.assertIs(type(read_metadata(b'{"a":13}')['a']), int)
        self.assertIs(type(read_metadata(b'{"a":13.0}')['a']), float)

    def test_duplicate_key_rejected(self):
        with self.assertRaises(Rejected):
            read_metadata(b'{"nested":{"x":1,"x":2}}')

    def test_nonfinite_and_overflow_rejected(self):
        for value in ("NaN", "Infinity", "-Infinity", "1e999", "-1e999"):
            with self.subTest(value=value), self.assertRaises(Rejected):
                read_metadata(('{"x":' + value + '}').encode())

    def test_eps_decimal_precision_negative_and_zero_unchanged(self):
        value = _json(b'{"eps":-0.12345678901234567890123456789,"zero":0.0}')
        self.assertEqual(str(value["eps"]), "-0.12345678901234567890123456789")
        self.assertIsInstance(value["eps"], Decimal)
        self.assertEqual(_decimal(value["zero"]), Decimal("0.0"))

    def test_cli_three_cold_processes_and_original_digest_unchanged(self):
        first = self.worker()
        self.assertEqual(first["stop"]["reason"], "BOUNDED_BATCH_BUDGET")
        body = self.intent().read_bytes()
        intent = read_metadata(body)
        digest = intent["dispatch_evidence_sha256"]
        with self.assertRaises(TypeError):
            _canonical(_json(body)["dispatch_evidence"])
        second = self.worker()
        self.assertEqual(second["stop"]["reason"], "ALL_COMPANIES_ACCOUNTED_FOR")
        third = self.worker()
        self.assertEqual(third["stop"]["new_requests"], 0)
        self.assertEqual(self.calls(), ["7777", "8888"])
        self.assertEqual(self.intent().read_bytes(), body)
        self.assertEqual(digest, sha256(_canonical(intent["dispatch_evidence"])))
        plan = read_metadata((self.root / "plan.json").read_bytes())
        self.assertEqual(len(read_events(self.root, plan)), 5)
        results = [json.loads(s) for s in (self.directory / "worker-results.jsonl").read_text().splitlines()]
        self.assertEqual(len({r["process_id"] for r in results}), 3)

    def test_cross_session_wait_and_fractional_disk_report_round_trip(self):
        self.worker()
        self.mode("normal", clock_start=0.0625)
        self.worker()
        plan = read_metadata((self.root / "plan.json").read_bytes())
        intents = validate_dispatches(self.root, plan)
        one, two = [r["dispatch_evidence"] for r in intents]
        self.assertNotEqual(one["session_identity"], two["session_identity"])
        self.assertEqual(two["prior_session_continuity"], "UNPROVEN_CONSERVATIVE_WAIT")
        self.assertGreaterEqual(two["actual_wait_seconds"], 13)
        self.assertEqual(one["minimum_interval_seconds"], 13.0)
        for path in (self.root / "reports").glob("*/*.json"):
            value = read_metadata(path.read_bytes())
            self.assertEqual(read_metadata(_canonical(value)), value)

    def tamper(self, change, resign=False):
        self.worker()
        intent = read_metadata(self.intent().read_bytes())
        change(intent)
        if resign:
            intent["dispatch_evidence_sha256"] = sha256(_canonical(intent["dispatch_evidence"]))
        self.intent().write_bytes(_canonical(intent))
        self.worker(expected=2)
        self.assertEqual(self.calls(), ["7777"])

    def test_timestamp_tamper_rejected(self):
        self.tamper(lambda x: x["dispatch_evidence"].update(monotonic_timestamp=500))

    def test_request_identity_tamper_rejected_even_when_resigned(self):
        self.tamper(lambda x: x["dispatch_evidence"]["request_identity"].update(symbol="8888"), True)

    def test_digest_tamper_rejected(self):
        self.tamper(lambda x: x.update(dispatch_evidence_sha256="0" * 64))

    def test_bool_cannot_masquerade_as_time_even_when_resigned(self):
        self.tamper(lambda x: x["dispatch_evidence"].update(actual_wait_seconds=True), True)

    def test_negative_time_rejected_even_when_resigned(self):
        self.tamper(lambda x: x["dispatch_evidence"].update(monotonic_timestamp=-1), True)

    def test_session_domain_tamper_rejected_even_when_resigned(self):
        self.tamper(lambda x: x["dispatch_evidence"].update(clock_domain="OTHER_SESSION"), True)

    def test_resealed_below_minimum_interval_rejected(self):
        self.tamper(lambda x: x["dispatch_evidence"].update(minimum_interval_seconds=12.9), True)

    def test_resealed_missing_intent_market_rejected(self):
        self.tamper(lambda x: x.pop("market"), True)

    def test_fractional_stop_gate_disk_round_trip_keeps_digest(self):
        from src.provider_eps_coverage import persist_stop, scan
        plan = make_plan(self.universe, BINDING, {"path": "MOCK_ONLY", "sha256": "0" * 64})
        root = initialize(self.root, plan)
        persist_stop(root, plan, {"reason": "SYNTHETIC_STOP", "elapsed": 13.125})
        body = (root / "stop-gate.json").read_bytes()
        result = scan(root, plan, lambda *a, **k: self.fail("NO_STOP_BYPASS"))
        self.assertEqual(result["persisted_reason"], "SYNTHETIC_STOP")
        self.assertEqual((root / "stop-gate.json").read_bytes(), body)

    def test_cli_shared_block_cold_restart_calls_no_more_transport(self):
        self.mode("blocked")
        first = self.worker(280, 2)
        self.assertEqual(first["stop"]["reason"], "SHARED_HOST_ACCESS_STOP")
        self.mode("normal")
        self.assertEqual(self.worker(280, 2)["stop"]["reason"], "PERSISTED_STOP_GATE")
        self.assertEqual(self.calls(), ["7777"])

    def test_cli_validation_failure_cold_restart_calls_no_more_transport(self):
        self.mode("invalid")
        self.assertEqual(self.worker(280, 2)["stop"]["reason"], "VALIDATION_FAILED_STOP")
        self.mode("normal")
        self.worker(280, 2)
        self.assertEqual(self.calls(), ["7777"])

    def test_cli_unknown_request_outcome_never_retried(self):
        self.mode("unknown")
        self.worker(280, 2)
        self.mode("normal")
        self.worker(280, 2)
        self.assertEqual(self.calls(), ["7777"])
        self.assertFalse((self.root / "receipts/coverage-7777.json").exists())

    def test_unknown_without_stop_gate_also_blocks_cold_restart(self):
        self.worker()
        save(self.root / "intents/8888.json", {"plan_id": read_metadata((self.root / "plan.json").read_bytes())["plan_id"], "symbol": "8888"})
        self.assertEqual(self.worker(280, 2)["stop"]["reason"], "REQUEST_OUTCOME_UNKNOWN_NO_AUTOMATIC_RETRY")
        self.assertEqual(self.calls(), ["7777"])

    def test_single_writer_lock_blocks_cold_cli(self):
        self.worker()
        with exclusive_scan(self.root):
            run = subprocess.run([sys.executable, "-B", str(REPO / "tests/provider_eps_cold_start_worker.py"),
                str(self.directory), "280"], cwd=REPO, capture_output=True, text=True)
            self.assertNotEqual(run.returncode, 0)
            self.assertIn("COVERAGE_WRITER_ALREADY_ACTIVE", run.stderr)
        self.assertEqual(self.calls(), ["7777"])


class HandoffTests(unittest.TestCase):
    def test_successor_of_successor_resolves_real_ancestor_once(self):
        helper = recovery_tests.RecoveryEngineeringTests()
        helper.setUp()
        self.addCleanup(helper.doCleanups)
        archive, files = helper.archive_synthetic_failure()
        parent, _, _ = replay_archive(archive, helper.directory / "first-successor", {**BINDING, "head_sha": "2" * 40})
        output, plan, report = handoff(parent, helper.directory / "second-successor", {**BINDING, "head_sha": "3" * 40})
        self.assertEqual(len(list((parent / "intents").glob("*.json"))), 0)
        self.assertEqual(report["counts"]["accounted_for"], 4)
        self.assertEqual(report["counts"]["inherited_data_requests"], 1)
        self.assertEqual(report["counts"]["new_plan_data_request_intents"], 0)
        entry = read_events(output, plan)["7777"]
        self.assertEqual(entry["recovery"]["original_request_reference"], str(helper.root / "intents/7777.json"))
        self.assertEqual(len(entry["recovery"]["ancestral_event_chain"]), 2)
        self.assertEqual(files, {p: {"bytes": len(b), "sha256": sha256(b)} for p in files for b in [Path(p).read_bytes()]})
        verify_handoff(output, plan, "3" * 40)
        old_rows = read_events(parent, read_metadata((parent / "plan.json").read_bytes()))["7777"]["rows"]
        for old, new in zip(old_rows, entry["rows"]):
            self.assertEqual({k: v for k, v in old.items() if k not in {"coverage_plan_id", "recovery_provenance", "verified_observed_at"}},
                             {k: v for k, v in new.items() if k not in {"coverage_plan_id", "recovery_provenance", "verified_observed_at"}})

    def test_handoff_rejects_unresolved_parent_stop(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            universe = engineering_universe(root / "universe.json")
            parent = initialize(root / "parent", make_plan(universe, BINDING, {"path": "MOCK", "sha256": "0" * 64}))
            save(parent / "stop-gate.json", {"reason": "STILL_BLOCKED"})
            with self.assertRaisesRegex(Rejected, "UNRESOLVED_STOP_GATE"):
                handoff(parent, root / "new", {**BINDING, "head_sha": "2" * 40})
            self.assertFalse((root / "new").exists())

    def test_incomplete_handoff_is_not_a_usable_checkpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises((KeyError, FileNotFoundError, Rejected)):
                verify_handoff(root, {}, "1" * 40)


if __name__ == "__main__":
    unittest.main()
