"""SYNTHETIC ONLY process-tree containment probe; no data or keys."""
from pathlib import Path
import os
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.prospective_acquisition_recovery import offline_network_guard
sys.addaudithook(offline_network_guard)


def main():
    mode, base = sys.argv[1], Path(sys.argv[2])
    if mode == "supervisor":
        from src.history_batch_launcher import ContainedProcess
        process = ContainedProcess([sys.executable, "-I", "-B", __file__, "child", str(base)], cwd=ROOT)
        process.send({"start": True})
        result = process.receive()
        sys.stdout.write(__import__("json").dumps(result) + "\n"); sys.stdout.flush()
        while True:
            time.sleep(1)
    elif mode == "child":
        if not sys.stdin.readline():
            return
        child = subprocess.Popen([sys.executable, "-I", "-B", __file__, "grandchild", str(base)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        sys.stdout.write(__import__("json").dumps({"status": "PASS", "child_pid": os.getpid(), "grandchild_pid": child.pid}) + "\n")
        sys.stdout.flush()
        while True:
            time.sleep(1)
    elif mode == "grandchild":
        while True:
            (base / "heartbeat.txt").write_text(str(time.monotonic()), encoding="ascii")
            time.sleep(0.05)


if __name__ == "__main__":
    main()
