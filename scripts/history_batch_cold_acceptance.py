"""Fresh, network-denied original Sidecar replay for isolated synthetic evidence."""
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT))
from src.prospective_acquisition_recovery import offline_network_guard
attempts = 0
def guard(event, args):
    global attempts
    if event in {"socket.connect", "socket.getaddrinfo", "socket.sendto", "urllib.Request"}:
        attempts += 1
    offline_network_guard(event, args)
sys.addaudithook(guard)
from src import history_batch_authority as a


def main():
    binding = a.read_metadata(sys.stdin.buffer.read())
    a.require(binding["ctx"]["synthetic"] is True, "BATCH_COLD_REAL_ROOT_FORBIDDEN")
    a.sandbox(Path(binding["ctx"]["campaign_root"]).parent)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT).decode().strip()
    owners = {**a.h.owners(), **a.sidecar.owners(), **a.engineering_owners()}
    a.require(head == binding["source_head"] and owners == binding["source_owner_sha256_lf"], "BATCH_COLD_SOURCE_MISMATCH")
    for path, digest in owners.items():
        a.require(a.e.sha(subprocess.check_output(["git", "show", head + ":" + path], cwd=ROOT)) == digest, "BATCH_COLD_COMMITTED_SOURCE_MISMATCH")
    def no_write(event, args):
        if event == "open" and not isinstance(args[0], int):
            mode, flags = args[1:3]
            a.require(not ((isinstance(mode, str) and any(x in mode for x in "wax+")) or
                (isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))), "BATCH_COLD_WRITE_FORBIDDEN")
        a.require(event not in {"os.mkdir", "os.remove", "os.rmdir", "os.rename", "os.chmod", "os.utime", "os.symlink", "os.link"},
                  "BATCH_COLD_WRITE_FORBIDDEN")
    sys.addaudithook(no_write)
    result = a.sidecar.replay(binding["ctx"], genesis_path=binding["genesis_path"],
        trusted_genesis_sha256=binding["genesis_sha256"], trusted_records=binding["record_paths"], expected_head=binding["head"])
    a.require(result["status"] == "PASS" and attempts == 0, "BATCH_COLD_REPLAY_FAILED")
    sys.stdout.buffer.write(a.e.canonical({"status": "PASS", "head": result["head"], "pid": os.getpid(),
        "parent_pid": os.getppid(), "isolated": bool(sys.flags.isolated), "network_attempts": attempts,
        "source_head": head, "source_owner_sha256_lf": owners, "accepted_chunks": result["accepted_chunks"]}))


if __name__ == "__main__":
    main()
