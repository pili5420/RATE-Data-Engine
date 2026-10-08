"""Writer/reader wait semantics with real disk and cold CLI processes, no HTTP."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from src.eps_duration_facts.model import Rejected
from src.eps_duration_facts.raw import sha256
from src.provider_eps_candidate import _canonical
from src.provider_eps_coverage import initialize, make_plan, now, read_events, save
from src.provider_eps_dispatch import DispatchGate
from src.provider_eps_metadata import read_metadata, read_intent, validate_dispatches
from tests.provider_eps_engineering_fixture import make_fixture
from tests.test_provider_eps_coverage import BINDING, engineering_universe

REPO = Path(__file__).resolve().parents[1]
REVIEWED = "c4cdbfe0362df45d91fd4e23f0a7d6ba008ca661"


class WaitSemanticsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="dispatch-wait-engineering-")
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name).resolve()
        self.original = self.directory / "original"
        self.original.mkdir()
        make_fixture(self.original)
        self.universe = engineering_universe(self.directory / "historical.json")
        self.universe["stocks"].extend([{"symbol": s, "market": "TPEX"} for s in ("8888", "9999")])
        self.universe["expected_market_counts"]["TPEX"] = 4
        save(self.directory / "universe.json", self.universe)
        self.plan = make_plan(self.universe, BINDING, {"path": "SYNTHETIC_ONLY", "sha256": "0" * 64})
        self.clock = [100.0]

    def writer(self, elapsed):
        gate = DispatchGate(13.0, prior_dispatch=True, clock=lambda: self.clock[0],
            sleep=lambda seconds: self.clock.__setitem__(0, self.clock[0] + seconds), utc=now)
        self.clock[0] += elapsed
        return gate

    def persist(self, root, gate, symbol="7777"):
        query = {**self.plan["query"], "data_id": symbol}
        evidence = gate.boundary({"plan_id": self.plan["plan_id"], "symbol": symbol,
            "request_id": "coverage-" + symbol, "query": query})
        gate.check_outbound(evidence)
        value = {"plan_id": self.plan["plan_id"], "symbol": symbol, "market": "TPEX", "query": query,
                 "started_at": now(), "dispatch_evidence": evidence, "dispatch_evidence_sha256": sha256(_canonical(evidence))}
        path = root / "intents" / (symbol + ".json")
        save(path, value)
        return path, path.read_bytes(), evidence

    def test_reader_accepts_unmodified_writer_wait_12_75(self):
        root = initialize(self.directory / "writer", self.plan)
        path, body, evidence = self.persist(root, self.writer(0.25))
        self.assertEqual(evidence["monotonic_timestamp"] - evidence["previous_wait_anchor_monotonic"], 13)
        self.assertEqual(evidence["actual_wait_seconds"], 12.75)
        intent = read_intent(path, self.plan)
        self.assertEqual(intent["dispatch_evidence_sha256"], sha256(_canonical(evidence)))
        self.assertEqual(path.read_bytes(), body)

    def test_reviewed_reader_misrejects_same_unmodified_writer_bytes(self):
        body = subprocess.check_output(["git", "show", REVIEWED + ":src/provider_eps_metadata.py"], cwd=REPO)
        source = self.directory / "reviewed_metadata.py"
        source.write_bytes(body)
        spec = importlib.util.spec_from_file_location("src.reviewed_provider_eps_metadata", source)
        old = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(old)
        root = initialize(self.directory / "old-reader", self.plan)
        path, persisted, evidence = self.persist(root, self.writer(0.25))
        self.assertEqual(evidence["actual_wait_seconds"], 12.75)
        self.assertEqual(read_metadata(persisted)["dispatch_evidence_sha256"], sha256(_canonical(evidence)))
        with self.assertRaisesRegex(Rejected, "DISPATCH_CONTINUITY_INVALID"):
            old.read_intent(path, self.plan)
        self.assertEqual(path.read_bytes(), persisted)

    def worker(self, budget):
        run = subprocess.run([sys.executable, "-B", str(REPO / "tests/provider_eps_cold_start_worker.py"),
            str(self.directory), str(budget)], cwd=REPO, capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)

    def lifecycle(self, elapsed, *, early=False):
        save(self.directory / "mock-config.json", {"mode": "normal", "clock_start": 100.0,
            "boundary_pre_elapsed": elapsed, "exact_sleep": True, "early_return": early})
        self.worker(2)
        root = self.directory / "rate-eps-public-research/coverage"
        before = {str(p): p.read_bytes() for p in (root / "intents").glob("*.json")}
        self.assertEqual(len(before), 2)
        self.worker(1)
        self.worker(1)
        self.assertEqual(before, {p: Path(p).read_bytes() for p in before})
        plan = read_metadata((root / "plan.json").read_bytes())
        intents = {r["symbol"]: r for r in validate_dispatches(root, plan)}
        one, same, new = [intents[s]["dispatch_evidence"] for s in ("7777", "8888", "9999")]
        self.assertEqual(one["session_identity"], same["session_identity"])
        self.assertNotEqual(same["session_identity"], new["session_identity"])
        self.assertEqual(same["prior_session_continuity"], "SAME_MONOTONIC_DOMAIN")
        self.assertEqual(new["prior_session_continuity"], "UNPROVEN_CONSERVATIVE_WAIT")
        self.assertIsNone(new["previous_dispatch_interval_seconds"])
        for evidence in (same, new):
            self.assertGreaterEqual(evidence["monotonic_timestamp"] - evidence["previous_wait_anchor_monotonic"], 13)
            self.assertAlmostEqual(evidence["actual_wait_seconds"], max(0, 13 - elapsed), places=6)
        for intent in intents.values():
            self.assertEqual(intent["dispatch_evidence_sha256"], sha256(_canonical(intent["dispatch_evidence"])))
        calls = [json.loads(s)["symbol"] for s in (self.directory / "mock-calls.jsonl").read_text().splitlines()]
        self.assertEqual(calls, ["7777", "8888", "9999"])
        runs = [json.loads(s) for s in (self.directory / "worker-results.jsonl").read_text().splitlines()]
        self.assertEqual(len({r["process_id"] for r in runs}), 3)
        if early:
            self.assertGreaterEqual(len(runs[1]["sleeps"]), 2)
            self.assertAlmostEqual(runs[1]["sleeps"][0], 13 - elapsed)
            self.assertAlmostEqual(runs[1]["sleep_elapsed_seconds"][0], (13 - elapsed) / 2)
            self.assertAlmostEqual(runs[1]["sleeps"][1], (13 - elapsed) / 2)
            self.assertAlmostEqual(sum(runs[1]["sleep_elapsed_seconds"]), max(0, 13 - elapsed))
        self.assertEqual(len(read_events(root, plan)), 6)
        for path in (root / "reports").glob("*/execution.json"):
            report = read_metadata(path.read_bytes())
            self.assertIn(report["stop"]["reason"], {"BOUNDED_BATCH_BUDGET", "ALL_COMPANIES_ACCOUNTED_FOR"})

    def test_cli_boundary_pre_elapsed_zero(self):
        self.lifecycle(0)

    def test_cli_boundary_pre_elapsed_0001(self):
        self.lifecycle(0.0001)

    def test_cli_boundary_pre_elapsed_025(self):
        self.lifecycle(0.25)

    def test_cli_boundary_pre_elapsed_13(self):
        self.lifecycle(13)

    def test_cli_boundary_pre_elapsed_above_13(self):
        self.lifecycle(13.25)

    def test_cli_early_sleep_returns_and_wait_is_topped_up(self):
        self.lifecycle(0.25, early=True)

    def reject_forged(self, change, *, same_session=False, reason):
        root = initialize(self.directory / "negative", self.plan)
        gate = self.writer(0.25)
        path, body, evidence = self.persist(root, gate)
        if same_session:
            gate.completed()
            self.clock[0] += 0.25
            path, body, evidence = self.persist(root, gate, "8888")
        forged = deepcopy(read_metadata(body))
        change(forged["dispatch_evidence"])
        forged["dispatch_evidence_sha256"] = sha256(_canonical(forged["dispatch_evidence"]))
        # Explicitly adversarial synthetic evidence, not a changed writer output.
        path.write_bytes(_canonical(forged))
        with self.assertRaisesRegex(Rejected, reason):
            read_intent(path, self.plan)

    def test_new_session_total_anchor_gap_below_13_is_rejected(self):
        self.reject_forged(lambda e: e.update(previous_wait_anchor_monotonic=e["monotonic_timestamp"] - 12.9999),
                           reason="DISPATCH_INTERVAL_VIOLATION")

    def test_same_session_total_anchor_gap_below_13_is_rejected(self):
        self.reject_forged(lambda e: e.update(previous_wait_anchor_monotonic=e["monotonic_timestamp"] - 12.9999),
                           same_session=True, reason="DISPATCH_INTERVAL_VIOLATION")

    def test_new_session_anchor_still_required(self):
        self.reject_forged(lambda e: e.update(previous_wait_anchor_monotonic=None), reason="DISPATCH_CONTINUITY_INVALID")

    def test_wait_cannot_exceed_total_anchor_elapsed(self):
        self.reject_forged(lambda e: e.update(actual_wait_seconds=13.25), reason="DISPATCH_WAIT_INCONSISTENT")


if __name__ == "__main__":
    unittest.main()
