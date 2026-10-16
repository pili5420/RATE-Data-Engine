"""SYNTHETIC ONLY process-tree containment probe; no data or keys."""
from pathlib import Path
import base64
import os
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.prospective_acquisition_recovery import offline_network_guard
sys.addaudithook(offline_network_guard)
from src import history_batch_authority as a


def reply(value):
    sys.stdout.buffer.write(a.e.canonical(value) + b"\n")
    sys.stdout.buffer.flush()


def main():
    mode, base = sys.argv[1], Path(sys.argv[2])
    if mode == "supervisor":
        from src.history_batch_launcher import ContainedProcess
        process = ContainedProcess([sys.executable, "-I", "-B", __file__, "child", str(base)], cwd=ROOT)
        process.send({"start": True})
        result = process.receive()
        reply(result)
        while True:
            time.sleep(1)
    elif mode == "child":
        if not sys.stdin.readline():
            return
        child = subprocess.Popen([sys.executable, "-I", "-B", __file__, "grandchild", str(base)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        reply({"status": "PASS", "child_pid": os.getpid(), "grandchild_pid": child.pid})
        while True:
            time.sleep(1)
    elif mode == "capture":
        # Retain actual wire bytes inside the same OS-contained process tree.
        request = a.canonical_metadata(sys.stdin.buffer.readline()[:-1])
        child = subprocess.Popen(request["command"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, cwd=ROOT)
        child.stdin.write(a.e.canonical({"start": True}) + b"\n"); child.stdin.flush()
        raw = child.stdout.readline()
        value = a.canonical_metadata(raw[:-1])
        reply({"status": "PASS", "wire_base64": base64.b64encode(raw).decode(), "child_pid": child.pid,
               "grandchild_pid": value.get("grandchild_pid")})
        while True:
            time.sleep(1)
    elif mode == "grandchild":
        while True:
            (base / "heartbeat.txt").write_text(str(time.monotonic()), encoding="ascii")
            time.sleep(0.05)


if __name__ == "__main__":
    main()
