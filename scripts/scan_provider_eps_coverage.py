"""Bounded local coverage of an immutable approved universe, not a warmup run."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.eps_duration_facts.model import require
from src.eps_duration_facts.raw import sha256
from src.provider_eps_candidate import build_candidate
from src.provider_eps_coverage import (initialize, load_universe, make_plan, now, read_events,
    reuse_original, revenue_inventory, save, scan, summary)
from verify_provider_eps_candidate import binding


def snapshot(paths):
    return {str(p): {"bytes": len(body), "sha256": sha256(body)} for p in sorted(set(paths)) for body in [Path(p).read_bytes()]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--universe-evidence", required=True)
    parser.add_argument("--universe-sha256", required=True)
    parser.add_argument("--universe-commit", required=True)
    parser.add_argument("--reuse-input", required=True)
    parser.add_argument("--transport", required=True)
    parser.add_argument("--transport-sha256", required=True)
    parser.add_argument("--revenue-evidence-root", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--expected-base", required=True)
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--max-requests", type=int, default=280)
    parser.add_argument("--max-seconds", type=int, default=3600)
    parser.add_argument("--interval-seconds", type=float, default=13)
    parser.add_argument("--continue-ledger", action="store_true")
    args = parser.parse_args()
    isolation = binding(args.expected_base, args.expected_head)
    universe = load_universe(args.universe_evidence, args.universe_sha256, args.universe_commit)
    transport_path = Path(args.transport).resolve()
    require(sha256(transport_path.read_bytes()) == args.transport_sha256, "TRANSPORT_CODE_HASH_MISMATCH")
    plan = make_plan(universe, {"base_sha": args.expected_base, "head_sha": args.expected_head},
                     {"path": str(transport_path), "sha256": args.transport_sha256})
    root = Path(args.output_dir).resolve()
    require(not root.is_relative_to(ROOT) and not root.is_relative_to(Path(args.reuse_input).resolve()), "OUTPUT_MUST_BE_EXTERNAL")
    require("rate-eps-public-research" in root.parts and not any(p.lower() in {"production", "latest", "state", "portfolio", "ledger"} for p in root.parts), "UNSAFE_OUTPUT_PATH")
    require(not any(p.is_symlink() or (hasattr(p, "is_junction") and p.is_junction()) for p in (root, *root.parents)), "LINKED_OUTPUT_FORBIDDEN")
    require(not root.exists() or args.continue_ledger, "NEW_OUTPUT_OR_EXPLICIT_LEDGER_CONTINUATION_REQUIRED")
    original = build_candidate(args.reuse_input, plan["code_binding"])
    revenue = revenue_inventory(args.revenue_evidence_root, args.universe_evidence, universe)
    paths = [Path(p) for p in original["input_integrity"]] + [Path(p) for p in revenue["input_integrity"]]
    paths += list(Path(args.reuse_input).rglob("*"))
    paths = [p for p in paths if p.is_file()] + [transport_path, Path(args.universe_evidence).resolve()]
    before = snapshot(paths)
    root = initialize(root, plan)
    reuse_original(root, plan, args.reuse_input)
    spec = importlib.util.spec_from_file_location("saved_finmind_transport", transport_path)
    transport = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(transport)
    token = os.environ.get("FINMIND_TOKEN")
    started = now()
    try:
        stop = scan(root, plan, transport.capture, token=token, max_requests=args.max_requests,
            max_seconds=args.max_seconds, interval_seconds=args.interval_seconds,
            progress=lambda p: print(json.dumps(p), flush=True))
    except Exception:
        trace = traceback.format_exc()
        if token:
            trace = trace.replace(token, "[REDACTED]")
        stop = {"reason": "TOOL_ERROR_STOPPED_NO_RETRY", "traceback": trace}
    report = summary(root, plan, stop)
    after = snapshot(paths)
    require(before == after and binding(args.expected_base, args.expected_head) == isolation, "EXISTING_INPUT_OR_PROTECTED_CODE_CHANGED")
    output = root / "reports" / ("report-" + now().replace(":", "").replace(".", ""))
    output.mkdir(exist_ok=False)
    save(output / "coverage-result.json", report)
    save(output / "request-ledger.json", {"plan_id": plan["plan_id"], "companies": list(read_events(root, plan).values())})
    save(output / "revenue-availability.json", revenue)
    save(output / "invariance.json", {"unchanged": True, "before": before, "after": after, "isolation": isolation})
    save(output / "execution.json", {"started_at": started, "finished_at": now(), "python": sys.version,
        "command_without_credentials": sys.argv, "code_binding": plan["code_binding"], "stop": stop,
        "request_limits": {"max_requests": args.max_requests, "max_seconds": args.max_seconds,
            "interval_seconds": args.interval_seconds, "token_present": bool(token),
            "credential_tier": "UNKNOWN_EXISTING_TOKEN" if token else "ANONYMOUS",
            "documented_anonymous_limit_per_hour": 300, "live_remaining_quota": "NOT_OBSERVABLE_WITHOUT_AUTHENTICATED_USER_INFO",
            "documentation": "https://finmind.github.io/quickstart/", "retry_count": 0},
        "production_eligible": False, "original_eight_quarter_coverage_credit": 0})
    print(json.dumps({"report_dir": str(output), "plan_id": plan["plan_id"], "counts": report["counts"], "stop": {k: v for k, v in stop.items() if k != "traceback"}}))
    return 2 if stop["reason"] == "TOOL_ERROR_STOPPED_NO_RETRY" else 0


if __name__ == "__main__":
    raise SystemExit(main())
