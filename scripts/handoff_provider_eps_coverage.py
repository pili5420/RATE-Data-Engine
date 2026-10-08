"""Offline code handoff. Does not import or invoke a market transport."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.eps_duration_facts.model import require
from src.eps_duration_facts.raw import sha256
from src.provider_eps_coverage import load_universe, save
from src.provider_eps_handoff import handoff
from src.provider_eps_metadata import read_metadata
from verify_provider_eps_candidate import binding


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("parent-root", "output-dir", "expected-base", "expected-head", "command-source"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    isolation = binding(args.expected_base, args.expected_head)
    command_source = Path(args.command_source).resolve()
    command = read_metadata(command_source.read_bytes())["command_without_credentials"]
    require(command[0] == "scripts/scan_provider_eps_coverage.py" and command[-1] == "--continue-ledger",
            "HANDOFF_COMMAND_SOURCE_INVALID")
    params = dict(zip(command[1:-1:2], command[2:-1:2]))
    require(params["--output-dir"] == str(Path(args.parent_root).resolve()) and
            (params["--max-requests"], params["--max-seconds"], params["--interval-seconds"]) ==
            ("280", "3600", "13"), "HANDOFF_COMMAND_BINDING_INVALID")
    parent = read_metadata((Path(args.parent_root) / "plan.json").read_bytes())
    require(parent["code_binding"] == {"base_sha": params["--expected-base"], "head_sha": params["--expected-head"]},
            "HANDOFF_PARENT_CODE_MISMATCH")
    universe = load_universe(params["--universe-evidence"], params["--universe-sha256"], params["--universe-commit"])
    require(universe == parent["universe"] and parent["transport_binding"] ==
            {"path": params["--transport"], "sha256": params["--transport-sha256"]} and
            sha256(Path(params["--transport"]).read_bytes()) == params["--transport-sha256"], "HANDOFF_SOURCE_BINDING_INVALID")
    output = Path(args.output_dir).resolve()
    require(not output.is_relative_to(ROOT) and "rate-eps-public-research" in output.parts and
            not any(p.lower() in {"production", "latest", "state", "portfolio", "ledger"} for p in output.parts),
            "HANDOFF_OUTPUT_MUST_BE_EXTERNAL")
    root, plan, report = handoff(args.parent_root, output, {"base_sha": args.expected_base, "head_sha": args.expected_head})
    require(binding(args.expected_base, args.expected_head) == isolation, "HANDOFF_PROTECTED_CODE_CHANGED")
    for name, value in (("--output-dir", str(root)), ("--expected-base", args.expected_base), ("--expected-head", args.expected_head)):
        command[command.index(name) + 1] = value
    save(root / "reports" / "future-continuation.json", {"command_without_credentials": command,
        "checkout": str(ROOT), "executed": False, "remaining_companies": report["counts"]["unattempted_companies"],
        "prerequisites": ["Separate authorization; READY_FOR_REVIEW is not scan authorization",
            "Exact clean code/base/head, plan, source/codec/dispatch/transport hashes and HANDOFF_READY verified",
            "Single writer; no unresolved stop gate or unknown outcome", "280 / 3600 / >=13 seconds; conservative new session"]})
    with (root / "reports" / "future-continuation.ps1.txt").open("x", encoding="utf-8") as stream:
        stream.write("# NOT EXECUTED; separate authorization required\nSet-Location -LiteralPath '" + str(ROOT) + "'\n")
        stream.write("& py -3 -B " + " ".join('"' + item + '"' for item in command) + "\n")
    save(root / "reports" / "isolation.json", isolation)
    print(json.dumps({"output": str(root), "plan_id": plan["plan_id"], "counts": report["counts"], "new_requests": 0}))


if __name__ == "__main__":
    main()
