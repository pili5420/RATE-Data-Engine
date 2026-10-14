"""SYNTHETIC ONLY: genuine cold interpreters; no live authorization or transport."""
from contextlib import contextmanager
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from src import history_acquisition_execution as h
from src import history_chunk_planning as c
from tests import test_history_chunked_acquisition as fixtures


class ColdReplayTests(unittest.TestCase):
    setUp = fixtures.ChunkTests.setUp
    make = fixtures.ChunkTests.make
    plan = fixtures.ChunkTests.plan
    material = fixtures.ChunkTests.material
    capture = fixtures.ChunkTests.capture
    run_chunk = fixtures.ChunkTests.run_chunk

    @classmethod
    def setUpClass(cls):
        fixtures.ChunkTests.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        fixtures.ChunkTests.tearDownClass.__func__(cls)

    def previous(self):
        a, b = self.material(0), self.material(1)
        result, auth = self.run_chunk(a)
        self.assertEqual(result["result"]["status"], "PASS")
        return a, b, result["result"], auth

    def rejected(self, b):
        before = len(self.calls)
        with patch.object(h, "execute", wraps=h.execute) as execute:
            with self.assertRaisesRegex(ValueError, "HALTED_FOR_CONTROL_CENTER_REVIEW"):
                self.run_chunk(b)
            execute.assert_not_called()
        self.assertEqual(len(self.calls), before)
        self.assertFalse(Path(b["consumption_root"]).exists())
        self.assertFalse(Path(b["execution_root"]).exists())

    @contextmanager
    def child_fault(self, action):
        real_run, calls = subprocess.run, []
        def dispatch(command, **kwargs):
            if command[-1] == str(h.ROOT / "scripts/replay_history_chunk_success.py"):
                calls.append(command)
                return action(real_run, command, kwargs)
            return real_run(command, **kwargs)
        with patch.object(c.subprocess, "run", side_effect=dispatch):
            yield
        self.assertEqual(len(calls), 1)

    def test_success_replayed_before_later_execute(self):
        a, b, result, _ = self.previous()
        proofs = []
        cold = c._cold_replay_success
        def replay(*args):
            proof = cold(*args)
            proofs.append(proof)
            self.assertFalse(Path(b["consumption_root"]).exists())
            return proof
        with patch.object(c, "_cold_replay_success", side_effect=replay):
            later, _ = self.run_chunk(b)
        self.assertEqual(later["result"]["status"], "PASS")
        self.assertEqual(len(proofs), 1)
        self.assertEqual(proofs[0]["ledger_head"], result["ledger_head"])
        self.assertEqual(proofs[0]["execution_root"], a["execution_root"])
        self.assertEqual(proofs[0]["network_attempts"], 0)

    def test_fresh_interpreter_does_not_inherit_parent_owner(self):
        a, _, result, _ = self.previous()
        with patch.object(h, "replay", side_effect=AssertionError("PARENT_OWNER_MUST_NOT_RUN")):
            proofs = c._campaign_guard(self.manifest, Path(a["campaign_root"]))
        proof = proofs[0]
        self.assertNotEqual(proof["pid"], os.getpid())
        self.assertEqual(proof["parent_pid"], os.getpid())
        self.assertTrue(proof["isolated"] and proof["guard_installed_before_owner_import"])
        self.assertEqual(proof["owner_module"], str(h.ROOT / "src/history_acquisition_execution.py"))
        self.assertEqual(proof["source_head"], subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=h.ROOT).decode().strip())
        self.assertEqual(proof["result_sha256"], h.evidence.sha(result))

    def test_every_success_gets_distinct_cold_process(self):
        self.make(21, periods=["202609"])
        self.run_chunk(self.material(0))
        self.run_chunk(self.material(1))
        cold, proofs = c._cold_replay_success, []
        def replay(*args):
            proof = cold(*args); proofs.append(proof); return proof
        with patch.object(c, "_cold_replay_success", side_effect=replay):
            result, _ = self.run_chunk(self.material(2))
        self.assertEqual(result["result"]["status"], "PASS")
        self.assertEqual(len(proofs), 2)
        self.assertEqual(len({p["pid"] for p in proofs}), 2)
        self.assertEqual({p["execution_root"] for p in proofs}, {self.material(i)["execution_root"] for i in (0, 1)})

    def test_original_files_unchanged_by_cold_replay(self):
        a, b, _, _ = self.previous()
        paths = [p for root in (a["execution_root"], a["consumption_root"]) for p in Path(root).rglob("*")
                 if p.is_file() and p.name != ".scan.lock"]
        before = {str(p):h.evidence.sha(p.read_bytes()) for p in paths}
        self.run_chunk(b)
        self.assertEqual(before, {str(p):h.evidence.sha(p.read_bytes()) for p in paths})

    def test_cold_child_nonzero_exit_blocks_claim(self):
        _, b, _, _ = self.previous()
        with self.child_fault(lambda *_: subprocess.CompletedProcess([], 7, b"", b"SYNTHETIC_CHILD_ERROR")):
            self.rejected(b)

    def test_cold_child_timeout_blocks_claim(self):
        _, b, _, _ = self.previous()
        def timeout(*_):
            raise subprocess.TimeoutExpired("synthetic", 300)
        with self.child_fault(timeout):
            self.rejected(b)

    def test_cold_child_malformed_output_blocks_claim(self):
        _, b, _, _ = self.previous()
        with self.child_fault(lambda *_: subprocess.CompletedProcess([], 0, b"not-json", b"")):
            self.rejected(b)

    def test_actual_child_network_attempt_blocked_before_claim(self):
        _, b, _, _ = self.previous()
        attempted = []
        def inject(real_run, command, kwargs):
            # Fault injection exists only in this synthetic test, not in the child API.
            code = ("import runpy,sys,socket; n=runpy.run_path(sys.argv[1]); "
                    "n['h'].replay=lambda *a: socket.getaddrinfo('localhost',443); n['main']()")
            run = real_run([sys.executable, "-I", "-B", "-c", code, command[-1]], **kwargs)
            attempted.append(run)
            return run
        with self.child_fault(inject):
            self.rejected(b)
        self.assertEqual(len(attempted), 1)
        self.assertNotEqual(attempted[0].returncode, 0)
        self.assertIn(b"RECOVERY_NETWORK_FORBIDDEN", attempted[0].stderr)

    def test_network_guard_blocks_connect_sendto_and_url(self):
        code = """import runpy,sys,socket,urllib.request
n=runpy.run_path(sys.argv[1])
for action in (lambda:socket.socket().connect(('127.0.0.1',9)),
               lambda:socket.socket(type=socket.SOCK_DGRAM).sendto(b'x',('127.0.0.1',9)),
               lambda:urllib.request.urlopen('https://example.invalid')):
    try: action()
    except RuntimeError as error: assert str(error)=='RECOVERY_NETWORK_FORBIDDEN'
    else: raise AssertionError('NETWORK_NOT_BLOCKED')
assert n['network_guard'].__globals__['network_attempts']==3
print('BLOCKED_BEFORE_NETWORK')
"""
        run = subprocess.run([sys.executable, "-I", "-B", "-c", code,
            str(h.ROOT / "scripts/replay_history_chunk_success.py")], capture_output=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn(b"BLOCKED_BEFORE_NETWORK", run.stdout)

    def test_structural_checks_all_precede_cold_children(self):
        self.make(21, periods=["202609"])
        self.run_chunk(self.material(0))
        b, last = self.material(1), self.material(2)
        Path(b["consumption_root"]).mkdir(parents=True)
        (Path(b["consumption_root"]) / "unknown.json").write_bytes(b"{}")
        with patch.object(c, "_cold_replay_success") as cold:
            self.rejected(last)
            cold.assert_not_called()

    def test_halted_check_precedes_cold_children(self):
        _, b, _, _ = self.previous()
        (Path(b["campaign_root"]) / "HALTED.json").write_bytes(b"{}")
        with patch.object(c, "_cold_replay_success") as cold:
            self.rejected(b)
            cold.assert_not_called()


def tamper_test(family):
    def test(self):
        a, b, _, _ = self.previous()
        root = Path(a["execution_root"])
        path = (next(Path(a["consumption_root"]).glob("*.json")) if family == "consumption" else
                root / family if family.endswith(".json") else next((root / family).glob("*")))
        if family in {"raw", "receipts"}:
            path.write_bytes(path.read_bytes() + b" ")
        else:
            value = h.read_metadata(path.read_bytes()); value["TAMPER"] = True
            path.write_bytes(h.evidence.canonical(value))
        with patch.object(c, "_cold_replay_success", wraps=c._cold_replay_success) as cold:
            self.rejected(b)
            self.assertEqual(cold.call_count, 1)
    return test


for family in ("raw", "receipts", "events", "checkpoints", "RESULT.json", "consumption", "plan.json", "seal.json", "authorization.json"):
    setattr(ColdReplayTests, "test_prior_tamper_" + family.replace(".", "_"), tamper_test(family))


def output_test(field, replacement):
    def test(self):
        _, b, _, _ = self.previous()
        def corrupt(real_run, command, kwargs):
            run = real_run(command, **kwargs)
            self.assertEqual(run.returncode, 0, run.stderr)
            proof = h.read_metadata(run.stdout)
            proof[field] = replacement
            return subprocess.CompletedProcess(command, 0, h.evidence.canonical(proof), b"")
        with self.child_fault(corrupt):
            self.rejected(b)
    return test


for field, value in {"ledger_head":"0"*64, "status":"STOPPED", "result_sha256":"0"*64,
                     "source_head":"0"*40, "pid":os.getpid(), "network_attempts":1}.items():
    setattr(ColdReplayTests, "test_child_wrong_" + field, output_test(field, value))


if __name__ == "__main__":
    unittest.main()
