"""Offline external evidence builder. No acquisition or ranking operation exists."""
import argparse
from pathlib import Path
import subprocess
import sys
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src import full_market_component_evidence as owner
from scripts.run_fundamental_ranking_consumer import isolation_guard
from scripts.run_prospective_provider_activation import external


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--expected-base", required=True)
    p.add_argument("--expected-head", required=True)
    p.add_argument("--fundamental-verdicts", type=Path, required=True)
    p.add_argument("--fundamental-file-sha256", required=True)
    p.add_argument("--fundamental-content-sha256", required=True)
    p.add_argument("--source-binding", type=Path)
    p.add_argument("--source-binding-sha256")
    p.add_argument("--trusted-source-acceptance-sha256")
    p.add_argument("--verify-bundle", type=Path)
    p.add_argument("--output-dir", type=Path, required=True)
    args = p.parse_args()
    def git(*words):
        return subprocess.check_output(["git", *words], cwd=ROOT).decode().strip()
    owner.require(args.expected_base == owner.CONTRACT["base_sha"] and git("rev-parse", "HEAD") == args.expected_head
        and git("merge-base", args.expected_base, args.expected_head) == args.expected_base
        and not git("status", "--porcelain"), "COMPONENT_EXACT_HEAD_OR_WORKTREE")
    output = external(args.output_dir)
    owner.require(not output.exists(), "COMPONENT_OUTPUT_MUST_BE_NEW")
    output.mkdir(parents=True)
    counters = {"network_attempts": 0, "protected_write_attempts": 0}
    sys.addaudithook(isolation_guard(output, counters))
    def save(name, value):
        with (output / name).open("xb") as stream:
            stream.write(owner.canonical(value))
    try:
        fb = owner.read_metadata(owner.pinned({"path": str(args.fundamental_verdicts), "sha256": args.fundamental_file_sha256}))
        owner.require(fb["content_sha256"] == args.fundamental_content_sha256 == owner.digest(fb["core"]),
                      "COMPONENT_ACCEPTED_FUNDAMENTAL_CONTENT")
        universe = {"verification_status": "PASS", "stocks": fb["core"]["issuers"]}
        binding = None
        if args.source_binding:
            owner.require(args.source_binding_sha256 and args.trusted_source_acceptance_sha256, "COMPONENT_SOURCE_TRUST_PINS_REQUIRED")
            binding = owner.read_metadata(owner.pinned({"path": str(args.source_binding), "sha256": args.source_binding_sha256}))
        started = owner.now()
        if args.verify_bundle:
            bundle = owner.read_metadata(args.verify_bundle.read_bytes())
            owner.verify(bundle, universe, expected_universe_identity=owner.CONTRACT["universe_identity"], as_of=owner.now(),
                         trusted_acceptance_sha256=args.trusted_source_acceptance_sha256)
        else:
            bundle = owner.build(universe, expected_universe_identity=owner.CONTRACT["universe_identity"],
                generated_at=started, validated_at=None, evidence_as_of=None, binding=binding,
                trusted_acceptance_sha256=args.trusted_source_acceptance_sha256)
        save("RATE_FULL_MARKET_COMPONENT_EVIDENCE_V1.json", bundle)
        preview = owner.readiness_preview(bundle, args.fundamental_verdicts, trusted_file_sha256=args.fundamental_file_sha256)
        save("READINESS_PREVIEW.json", preview)
        plan = owner.acquisition_plan(universe, expected_universe_identity=owner.CONTRACT["universe_identity"], execution_head=args.expected_head)
        save("ACQUISITION_REQUEST_PLAN.json", plan)
        result = {"status": "BLOCKED_ACQUISITION_AUTHORIZATION_REQUIRED" if binding is None else "FULL_MARKET_COMPONENT_EVIDENCE_READY_FOR_REVIEW",
            "source_status": bundle["source_status"], "base_sha": args.expected_base, "head_sha": args.expected_head,
            "content_sha256": bundle["content_sha256"], "counts": bundle["core"]["counts"],
            "universe_count": 1978, "preview_counts": preview["counts"], "fundamental_recomputed": False,
            "cold_read": bool(args.verify_bundle), "financial_requests": 0, "ranking_executions": 0,
            "publications": 0, "state_portfolio_ledger_scheduler_mutations": 0, "audit_counters": counters,
            "started_at": started, "finished_at": owner.now()}
        save("RUN.json", result)
        print(owner.canonical(result).decode())
        return 0
    except Exception:
        with (output / "traceback.txt").open("x", encoding="utf-8") as stream:
            traceback.print_exc(file=stream)
        save("RUN.json", {"status": "BLOCKED", "audit_counters": counters})
        raise


if __name__ == "__main__":
    raise SystemExit(main())
