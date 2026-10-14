"""Read-only cold replay child; no acquisition or authorization claim entry point."""
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.prospective_acquisition_recovery import offline_network_guard

network_attempts = 0


def network_guard(event, args):
    global network_attempts
    if event in {"socket.connect", "socket.getaddrinfo", "socket.sendto", "urllib.Request"}:
        network_attempts += 1
    offline_network_guard(event, args)


sys.addaudithook(network_guard)
guard_installed_before_owner_import = "src.history_acquisition_execution" not in sys.modules
from src import history_acquisition_execution as h
from src.eps_duration_facts.model import require
from src.provider_eps_metadata import read_metadata


def main():
    require(sys.flags.isolated == 1 and sys.flags.dont_write_bytecode == 1
            and guard_installed_before_owner_import, "CHUNK_COLD_INTERPRETER_REQUIRED")
    binding = read_metadata(sys.stdin.buffer.read())
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT).decode().strip()
    require(head == binding["source_head"] and h.ROOT == ROOT
            and Path(h.__file__).resolve() == ROOT / "src/history_acquisition_execution.py", "CHUNK_COLD_SOURCE_MISMATCH")
    for relative, pin in binding["source_sha256_lf"].items():
        path = (ROOT / relative).resolve()
        require(path.is_relative_to(ROOT), "CHUNK_COLD_SOURCE_ESCAPE")
        committed = subprocess.check_output(["git", "show", head + ":" + relative], cwd=ROOT)
        require(h.evidence.sha(path.read_bytes().replace(b"\r\n", b"\n")) == pin == h.evidence.sha(committed),
                "CHUNK_COLD_COMMITTED_SOURCE_DRIFT")
    run, consumption = Path(binding["execution_root"]), Path(binding["consumption_root"])
    plan, seal, auth = [read_metadata((run / (name + ".json")).read_bytes())
                        for name in ("plan", "seal", "authorization")]
    require(plan["plan_sha256"] == binding["plan_sha256"] and seal["seal_sha256"] == binding["seal_sha256"],
            "CHUNK_COLD_ORIGINAL_BINDING_MISMATCH")
    result = h.replay(run, plan, seal, auth, consumption)
    require(result["status"] == "PASS" and h.evidence.sha(result) == binding["result_sha256"]
            and network_attempts == 0, "CHUNK_COLD_RESULT_INVALID")
    proof = {"status":result["status"], "ledger_head":result["ledger_head"], "result_sha256":h.evidence.sha(result),
        "source_head":head, "source_sha256_lf":binding["source_sha256_lf"], "owner_module":str(Path(h.__file__).resolve()),
        "execution_root":str(run), "consumption_root":str(consumption), "plan_sha256":plan["plan_sha256"],
        "seal_sha256":seal["seal_sha256"], "pid":os.getpid(), "parent_pid":os.getppid(), "isolated":True,
        "guard_installed_before_owner_import":guard_installed_before_owner_import, "network_attempts":network_attempts}
    sys.stdout.buffer.write(h.evidence.canonical(proof))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
