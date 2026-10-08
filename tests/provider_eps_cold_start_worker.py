"""A fresh OS process exercising the real CLI with synthetic input adapters."""
import json
from pathlib import Path
import socket
import sys
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
from scripts import scan_provider_eps_coverage as cli
from src.eps_duration_facts.raw import sha256
from src.provider_eps_metadata import read_metadata, validate_dispatches
from src import provider_eps_coverage as coverage
from tests.test_provider_eps_coverage import BINDING


def main():
    directory = Path(sys.argv[1]).resolve()
    budget = sys.argv[2]
    config = read_metadata((directory / "mock-config.json").read_bytes())
    universe = read_metadata((directory / "universe.json").read_bytes())
    transport = REPO / "tests" / "provider_eps_mock_transport.py"
    root = directory / "rate-eps-public-research" / "coverage"
    clock = [config.get("clock_start", 100.125)]
    sleeps = []
    sleep_elapsed = []
    def sleep(seconds):
        before = clock[0]
        sleeps.append(seconds)
        if config.get("exact_sleep"):
            clock[0] += seconds / 2 if config.get("early_return") and len(sleeps) == 1 else seconds
        else:
            clock[0] += seconds / 2 if len(sleeps) == 1 else seconds + 0.25
        sleep_elapsed.append(clock[0] - before)
    class BoundaryDelayGate(coverage.DispatchGate):
        def boundary(self, request_identity):
            clock[0] += config.get("boundary_pre_elapsed", 0)
            return super().boundary(request_identity)
    real_scan = cli.scan
    def scan(*args, **kwargs):
        return real_scan(*args, **kwargs, clock=lambda: clock[0], sleep=sleep)
    argv = ["scripts/scan_provider_eps_coverage.py", "--universe-evidence", str(directory / "universe.json"),
        "--universe-sha256", sha256((directory / "universe.json").read_bytes()), "--universe-commit", "0" * 40,
        "--reuse-input", str(directory / "original"), "--transport", str(transport),
        "--transport-sha256", sha256(transport.read_bytes()), "--revenue-evidence-root", str(directory / "empty-revenue"),
        "--output-dir", str(root), "--expected-base", BINDING["base_sha"], "--expected-head", BINDING["head_sha"],
        "--max-requests", budget, "--max-seconds", "3600", "--interval-seconds", "13.0"]
    if root.exists():
        argv.append("--continue-ledger")
    # Only fixture authority and Git identity are substituted; actual CLI,
    # scanner, persistence, lock, stop/report and transport loading run intact.
    with patch.object(sys, "argv", argv), patch.object(cli, "binding", return_value={"synthetic": True}), \
         patch.object(cli, "load_universe", return_value=universe), patch.object(cli, "revenue_inventory", return_value={"input_integrity": {}}), \
         patch.object(cli, "scan", side_effect=scan), patch.object(socket, "create_connection", side_effect=AssertionError("NO_NETWORK")):
        with patch.object(coverage, "DispatchGate", BoundaryDelayGate):
            code = cli.main()
    plan = read_metadata((root / "plan.json").read_bytes())
    if config["mode"] == "normal" and code == 0:
        validate_dispatches(root, plan)
    with (directory / "worker-results.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"code": code, "sleeps": sleeps, "sleep_elapsed_seconds": sleep_elapsed,
            "clock": clock[0], "process_id": __import__("os").getpid()}) + "\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
