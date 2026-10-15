"""Contained, offline synthetic workers; no deployment or activation capability."""
import ctypes
import os
from pathlib import Path
import signal
import subprocess
import sys
import queue
import threading

from .eps_duration_facts.model import require
from . import history_batch_authority as a


def engineering_environment():
    names = ("PATH", "SYSTEMROOT", "SystemRoot", "WINDIR", "COMSPEC", "TEMP", "TMP", "HOME", "USERPROFILE",
             "LOCALAPPDATA", "APPDATA", "LANG", "LC_ALL", "TZ", "CI", "GITHUB_ACTIONS", "RUNNER_OS", "RUNNER_TEMP",
             "GITHUB_WORKSPACE", "PYTHONDONTWRITEBYTECODE", "PYTHONIOENCODING")
    return {name: os.environ[name] for name in names if name in os.environ}


def verify_checkout(path, head, owner_pins, *, main=False):
    path = a.e.safe(path)
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=path).decode().strip()
    require(git("rev-parse", "HEAD") == head and not git("status", "--porcelain", "--untracked-files=all"),
            "BATCH_LAUNCHER_HEAD_OR_WORKTREE_MISMATCH")
    if main:
        require(git("branch", "--show-current") == "main" and git("rev-parse", "origin/main") == head,
                "BATCH_LAUNCHER_FROZEN_MAIN_MISMATCH")
    for relative, pin in owner_pins.items():
        require(a.e.sha((path / relative).read_bytes().replace(b"\r\n", b"\n")) == pin
                and a.e.sha(subprocess.check_output(["git", "show", head + ":" + relative], cwd=path)) == pin,
                "BATCH_LAUNCHER_COMMITTED_OWNER_MISMATCH")
    return {"checkout": str(path), "head": head, "owners": owner_pins}


def real_launch(*args, **kwargs):
    raise ValueError("BATCH_REAL_DEPLOYMENT_AND_AUTO_NEXT_NOT_AUTHORIZED")


class ContainedProcess:
    """Child must wait for a boot line before doing work or spawning descendants."""
    def __init__(self, command, *, cwd):
        self.job = None
        self.monitor_fd = self.monitor_pid = None
        self.process = subprocess.Popen(command, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding="utf-8", start_new_session=os.name != "nt",
            env=engineering_environment())
        try:
            if os.name == "nt":
                self._windows_job()
            else:
                # EOF from parent death kills the entire isolated process group.
                read_fd, self.monitor_fd = os.pipe()
                self.monitor_pid = os.fork()
                if self.monitor_pid == 0:
                    os.close(self.monitor_fd)
                    try:
                        os.read(read_fd, 1)
                        os.killpg(self.process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    finally:
                        os._exit(0)
        except BaseException:
            self.process.kill(); self.process.wait(timeout=10)
            raise
        if os.name != "nt":
            os.close(read_fd)
        self.responses = queue.Queue()
        def read_lines():
            try:
                for line in self.process.stdout:
                    self.responses.put(line)
            finally:
                self.responses.put(None)
        self.reader = threading.Thread(target=read_lines, daemon=True)
        self.reader.start()

    def _windows_job(self):
        from ctypes import wintypes as w
        class BASIC(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", w.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t), ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", w.DWORD), ("Affinity", ctypes.c_size_t), ("PriorityClass", w.DWORD), ("SchedulingClass", w.DWORD)]
        class IO(ctypes.Structure):
            _fields_ = [(name, ctypes.c_ulonglong) for name in ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]
        class EXTENDED(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", BASIC), ("IoInfo", IO), ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateJobObjectW.argtypes, kernel.CreateJobObjectW.restype = [ctypes.c_void_p, w.LPCWSTR], w.HANDLE
        kernel.SetInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD]
        kernel.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
        kernel.CloseHandle.argtypes = [w.HANDLE]
        job = kernel.CreateJobObjectW(None, None)
        require(bool(job), "BATCH_JOB_CREATE_FAILED")
        info = EXTENDED(); info.BasicLimitInformation.LimitFlags = 0x2000
        if not kernel.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):
            kernel.CloseHandle(job); raise OSError(ctypes.get_last_error(), "BATCH_JOB_CONFIG_FAILED")
        if not kernel.AssignProcessToJobObject(job, w.HANDLE(int(self.process._handle))):
            kernel.CloseHandle(job); raise OSError(ctypes.get_last_error(), "BATCH_JOB_ASSIGN_FAILED")
        self.job, self.kernel = job, kernel

    def send(self, value):
        require(self.process.poll() is None, "BATCH_CHILD_ALREADY_EXITED")
        completed = queue.Queue()
        def write():
            try:
                self.process.stdin.write(a.e.canonical(value).decode() + "\n"); self.process.stdin.flush()
                completed.put(None)
            except Exception as exc:
                completed.put(exc)
        threading.Thread(target=write, daemon=True).start()
        try:
            failure = completed.get(timeout=300)
        except queue.Empty as exc:
            self.close(); raise ValueError("BATCH_CHILD_WRITE_TIMEOUT_UNKNOWN_OUTCOME") from exc
        require(failure is None, "BATCH_CHILD_WRITE_FAILED_UNKNOWN_OUTCOME")

    def receive(self, timeout=300):
        try:
            line = self.responses.get(timeout=timeout)
        except queue.Empty as exc:
            self.close(); raise ValueError("BATCH_CHILD_READ_TIMEOUT_UNKNOWN_OUTCOME") from exc
        require(bool(line), "BATCH_CHILD_NONZERO_OR_UNKNOWN_OUTCOME")
        value = a.read_metadata(line.encode())
        require(value.get("status") == "PASS", "BATCH_CHILD_FAILED:" + str(value.get("error")))
        return value

    def close(self):
        if self.job is not None:
            self.kernel.CloseHandle(self.job); self.job = None
        elif self.process.poll() is None:
            os.killpg(self.process.pid, signal.SIGKILL)
        if self.monitor_fd is not None:
            os.close(self.monitor_fd); self.monitor_fd = None
            os.waitpid(self.monitor_pid, 0); self.monitor_pid = None
        if self.process.poll() is None:
            self.process.wait(timeout=10)
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            stream.close()


class IssuerClient:
    """Only public keys and signed replies cross into this process."""
    def __init__(self, base, *, expected_engineering_head, trusted_owner_sha256_lf):
        self.base = a.sandbox(base)
        required = set(a.h.owners()) | set(a.sidecar.owners()) | set(a.engineering_owners())
        require(set(trusted_owner_sha256_lf) == required, "BATCH_LAUNCHER_OWNER_SET_MISMATCH")
        verify_checkout(a.h.ROOT, expected_engineering_head, trusted_owner_sha256_lf)
        self.child = ContainedProcess([sys.executable, "-I", "-B", str(a.h.ROOT / "scripts/history_batch_synthetic_issuer.py")], cwd=a.h.ROOT)
        self.child.send({"operation": "BOOT", "material_scope": a.SCOPE, "sandbox": str(self.base)})
        self.public = self.child.receive()
        if self.public["pid"] != self.child.process.pid or self.public["parent_pid"] != os.getpid():
            self.child.close()
            raise ValueError("BATCH_NATIVE_INTERPRETER_PROCESS_BINDING_REQUIRED")

    def initialize(self, policy, ctx, registry, policy_envelope, *, trusted_registry_sha256, at, synthetic_fault_stage=None):
        require(a.e.sha(registry) == trusted_registry_sha256, "BATCH_EXTERNAL_KEY_REGISTRY_PIN_REQUIRED")
        self.child.send({"operation": "INITIALIZE", "policy": policy, "ctx": ctx, "registry": registry,
            "registry_pin": trusted_registry_sha256, "policy_envelope": policy_envelope, "at": at,
            "synthetic_fault_stage": synthetic_fault_stage})
        return self.child.receive()

    def call(self, operation, **values):
        require(operation in {"AUTHORIZE", "ACCEPT", "ACK", "REVOKE"}, "BATCH_ISSUER_RPC_NOT_ALLOWED")
        self.child.send({"operation": operation, **values})
        return self.child.receive()["result"]

    def close(self):
        self.child.close()
