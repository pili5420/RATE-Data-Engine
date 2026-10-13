"""Offline, external-output-only Fundamental consumer; no ranking command."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.eps_duration_facts.model import require
from src.fundamental_first_refresh_execution import canonical, digest
from src.fundamental_ranking_consumer import build, now, pinned, verify_bundle
from scripts.run_prospective_provider_activation import external


def isolation_guard(output, counters):
    def guard(event, args):
        if event in {"socket.connect", "socket.getaddrinfo", "socket.sendto", "urllib.Request"}:
            counters["network_attempts"] += 1
            raise RuntimeError("CONSUMER_NETWORK_FORBIDDEN")
        path = None
        if event == "open" and isinstance(args[0], (str, bytes, os.PathLike)):
            mode, flags = args[1], args[2]
            if (isinstance(mode, str) and any(c in mode for c in "wax+")) or (
                    isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC)):
                path = args[0]
        elif event in {"os.remove", "os.rmdir", "os.mkdir", "os.chmod", "os.utime"}:
            path = args[0]
        elif event in {"os.rename", "os.replace"}:
            for item in args[:2]:
                if not Path(item).resolve().is_relative_to(output):
                    counters["protected_write_attempts"] += 1
                    raise RuntimeError("CONSUMER_PROTECTED_WRITE_FORBIDDEN")
        if path is not None and not Path(path).resolve().is_relative_to(output):
            counters["protected_write_attempts"] += 1
            raise RuntimeError("CONSUMER_PROTECTED_WRITE_FORBIDDEN")
    return guard


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--binding", type=Path, required=True)
    parser.add_argument("--binding-sha256", required=True)
    parser.add_argument("--expected-base", required=True)
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--synthetic-only", action="store_true")
    parser.add_argument("--verify-bundle", type=Path)
    parser.add_argument("--verdict-content-sha256")
    args = parser.parse_args()
    def git(*words):
        return subprocess.check_output(["git", *words], cwd=ROOT).decode().strip()
    require(args.expected_base == "e5953fa3ff7123a28d85ec6c4f361c25da9bc4ab"
            and git("rev-parse", "HEAD") == args.expected_head
            and git("merge-base", args.expected_base, args.expected_head) == args.expected_base
            and not git("status", "--porcelain"), "CONSUMER_EXACT_HEAD_OR_WORKTREE_MISMATCH")
    binding = pinned({"path": str(args.binding), "sha256": args.binding_sha256})
    output = external(args.output_dir)
    require(not output.exists(), "CONSUMER_OUTPUT_MUST_BE_NEW")
    for root in (binding["artifacts_root"], binding["lineage_root"], Path(binding["acceptance"]["path"]).parent):
        require(not output.is_relative_to(Path(root).resolve()), "CONSUMER_OUTPUT_OVERLAPS_EVIDENCE")
    output.mkdir(parents=True)
    counters = {"network_attempts": 0, "protected_write_attempts": 0}
    sys.addaudithook(isolation_guard(output, counters))
    def save(name, value):
        with (output / name).open("xb") as stream:
            stream.write(canonical(value))
    try:
        generated = now()
        if args.verify_bundle:
            require(args.verdict_content_sha256 is not None, "CONSUMER_TRUSTED_VERDICT_HASH_REQUIRED")
            bundle = json.loads(args.verify_bundle.read_bytes())
            require(bundle["content_sha256"] == args.verdict_content_sha256, "CONSUMER_TRUSTED_VERDICT_HASH_MISMATCH")
            verify_bundle(bundle, binding, as_of=now(), synthetic=args.synthetic_only)
        else:
            bundle = build(binding, generated_at=generated, validated_at=now(), synthetic=args.synthetic_only)
        # Validation is a separate completed-run timestamp, not source availability.
        completed = now()
        if not args.verify_bundle:
            bundle["consumer_validated_at"] = completed
        save("FUNDAMENTAL_OWNER_VERDICTS.json", bundle)
        save("RUN.json", {"status": "PASS", "base_sha": args.expected_base, "head_sha": args.expected_head,
            "binding_sha256": args.binding_sha256, "content_sha256": bundle["content_sha256"],
            "counts": bundle["core"]["counts"], "started_at": generated, "finished_at": completed,
            "independent_cold_verification": bool(args.verify_bundle), "audit_counters": counters,
            "financial_requests": 0, "first_refresh_executions": 0, "ranking_executions": 0,
            "publications": 0, "state_portfolio_ledger_scheduler_mutations": 0})
        print(json.dumps({"status": "PASS", "content_sha256": bundle["content_sha256"],
                          "counts": bundle["core"]["counts"], "output": str(output)}))
        return 0
    except Exception:
        with (output / "traceback.txt").open("x", encoding="utf-8") as stream:
            traceback.print_exc(file=stream)
        save("RUN.json", {"status": "BLOCKED", "audit_counters": counters})
        raise


if __name__ == "__main__":
    raise SystemExit(main())
