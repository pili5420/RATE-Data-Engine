"""Temporary contained children only; Windows Job Object and POSIX death monitor."""
from pathlib import Path
import ctypes
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from src.prospective_acquisition_recovery import offline_network_guard
sys.addaudithook(offline_network_guard)
from src import history_batch_authority as a
from src.history_batch_launcher import ContainedProcess


def alive(pid):
    if os.name == "nt":
        from ctypes import wintypes as w
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes, kernel.OpenProcess.restype = [w.DWORD, w.BOOL, w.DWORD], w.HANDLE
        kernel.GetExitCodeProcess.argtypes = [w.HANDLE, ctypes.POINTER(w.DWORD)]
        kernel.CloseHandle.argtypes = [w.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        code = w.DWORD()
        try:
            if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)):
                raise OSError(ctypes.get_last_error())
            return code.value == 259
        finally:
            kernel.CloseHandle(handle)
    status = Path(f"/proc/{pid}/stat")
    if status.exists() and status.read_text().split()[2] == "Z":
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


class ContainmentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="SYNTHETIC-batch-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.probe = a.h.ROOT / "tests/history_batch_process_probe.py"

    def wait_dead(self, *pids):
        deadline = time.monotonic() + 10
        while any(alive(pid) for pid in pids) and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertTrue(all(not alive(pid) for pid in pids))

    def test_contained_close_terminates_child_and_grandchild(self):
        process = ContainedProcess([sys.executable, "-I", "-B", str(self.probe), "child", str(self.base)], cwd=a.h.ROOT)
        process.send({"start": True}); result = process.receive()
        if os.name == "nt":
            self.assertIsNotNone(process.job)
        else:
            self.assertIsNotNone(process.monitor_pid)
        process.close()
        self.wait_dead(result["child_pid"], result["grandchild_pid"])

    def test_parent_abnormal_death_kills_tree(self):
        supervisor = subprocess.Popen([sys.executable, "-I", "-B", str(self.probe), "supervisor", str(self.base)],
            cwd=a.h.ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            line = supervisor.stdout.readline()
            self.assertTrue(line)
            result = json.loads(line)
            supervisor.kill(); supervisor.wait(timeout=10)
            self.wait_dead(result["child_pid"], result["grandchild_pid"])
        finally:
            if supervisor.poll() is None:
                supervisor.kill(); supervisor.wait(timeout=10)
            supervisor.stdout.close(); supervisor.stderr.close()

    def test_nonzero_child_is_not_success(self):
        process = ContainedProcess([sys.executable, "-I", "-c", "import sys;sys.stdin.readline();sys.exit(9)"], cwd=a.h.ROOT)
        self.addCleanup(process.close)
        process.send({"start": True})
        with self.assertRaisesRegex(ValueError, "UNKNOWN_OUTCOME"):
            process.receive()

    def test_hanging_child_timeout_halts_and_kills(self):
        process = ContainedProcess([sys.executable, "-I", "-c", "import sys,time;sys.stdin.readline();time.sleep(60)"], cwd=a.h.ROOT)
        process.send({"start": True})
        with self.assertRaisesRegex(ValueError, "TIMEOUT_UNKNOWN_OUTCOME"):
            process.receive(timeout=0.1)
        self.assertIsNotNone(process.process.poll())

    def test_network_attempt_is_denied_before_connect(self):
        code = ("import sys,socket;sys.path.insert(0,sys.argv[1]);"
                "from src.prospective_acquisition_recovery import offline_network_guard;"
                "sys.addaudithook(offline_network_guard);socket.create_connection(('127.0.0.1',9))")
        result = subprocess.run([sys.executable, "-I", "-B", "-c", code, str(a.h.ROOT)], capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b"NETWORK", result.stderr.upper())

    def test_owner_signing_key_never_serialized_by_worker(self):
        source = (a.h.ROOT / "scripts/history_batch_synthetic_issuer.py").read_text(encoding="utf-8")
        self.assertNotIn("private_bytes", source)
        self.assertNotIn("FINMIND_TOKEN", source)
        self.assertIn("Ed25519PrivateKey.generate()", source)

    def test_redirected_pid_rejected_before_initialization(self):
        from src.history_batch_launcher import IssuerClient
        calls = []
        class Redirected:
            process = type("Process", (), {"pid": 101})()
            def send(self, value):
                calls.append(value["operation"])
            def receive(self):
                return {"status": "PASS", "pid": 102, "parent_pid": os.getpid()}
            def close(self):
                calls.append("CLOSED")
        with patch("src.history_batch_launcher.ContainedProcess", return_value=Redirected()):
            with self.assertRaisesRegex(ValueError, "NATIVE_INTERPRETER"):
                IssuerClient(self.base)
        self.assertEqual(calls, ["BOOT", "CLOSED"])

    def test_unapproved_environment_secret_not_inherited(self):
        name = "RATE_CC_TEST_SECRET_" + str(os.getpid())
        self.assertNotIn(name, os.environ)
        os.environ[name] = "SYNTHETIC_SENTINEL_ONLY"
        try:
            code = "import sys,os,json;sys.stdin.readline();print(json.dumps({'status':'PASS','present':sys.argv[1] in os.environ}),flush=True)"
            process = ContainedProcess([sys.executable, "-I", "-c", code, name], cwd=a.h.ROOT)
            try:
                process.send({"start": True})
                self.assertFalse(process.receive()["present"])
            finally:
                process.close()
        finally:
            del os.environ[name]
