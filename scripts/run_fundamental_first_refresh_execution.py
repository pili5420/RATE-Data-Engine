"""CLI for the Fundamental-only First Refresh execution owner.

Engineering modes never call financial endpoints. Live execution is unreachable
without a separate immutable FIRST_REFRESH_EXECUTION_AUTHORIZED object.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.eps_duration_facts.raw import sha256
from src.provider_eps_coverage import load_universe
from src.provider_eps_dispatch import DispatchGate
from src.provider_eps_metadata import read_metadata
from src.fundamental_first_refresh_execution import (
    CONTRACT, build_request_plan, validate_plan, simulate_full_plan,
    preexecution_seal, execute_authorized_first_refresh, digest,
)
from scripts.run_prospective_provider_activation import finmind_capture, mops_capture


def now():
    return datetime.now(timezone.utc).isoformat()


def load_pinned(ref):
    body = Path(ref["path"]).read_bytes()
    if sha256(body) != ref["sha256"]:
        raise ValueError("FIRST_REFRESH_BINDING_TAMPER")
    return read_metadata(body)


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT).decode().strip()


def exact_main(execution_main_sha):
    if (git("rev-parse", "HEAD") != execution_main_sha
            or git("rev-parse", "origin/main") != execution_main_sha
            or git("merge-base", CONTRACT["base_sha"], execution_main_sha) != CONTRACT["base_sha"]
            or git("status", "--porcelain")):
        raise ValueError("FIRST_REFRESH_EXECUTION_MAIN_OR_WORKTREE_MISMATCH")


def universe_from(binding):
    ref = binding["universe"]
    return load_universe(ref["path"], ref["sha256"], ref["commit"],
                         expected_counts={"TWSE": 1085, "TPEX": 893})


def plan_from(binding):
    execution_main_sha = binding["execution_main_sha"]
    exact_main(execution_main_sha)
    universe = universe_from(binding)
    authority_id = binding["authority_id"]
    return universe, build_request_plan(universe, authority_id, execution_main_sha)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--operation", choices=("plan", "dry-run", "preflight", "execute"), required=True)
    parser.add_argument("--binding", type=Path, required=True)
    parser.add_argument("--binding-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    body = args.binding.read_bytes()
    if sha256(body) != args.binding_sha256:
        raise ValueError("FIRST_REFRESH_BINDING_TAMPER")
    binding = read_metadata(body)
    universe, plan = plan_from(binding)

    if args.operation == "plan":
        payload = {"status": "PASS", "plan": plan, "financial_requests": 0, "production_publications": 0}
    elif args.operation == "dry-run":
        simulation = simulate_full_plan(plan, universe)
        payload = {"status": simulation["status"], "plan": plan, "simulation": simulation,
                   "financial_requests": 0, "production_publications": 0}
    elif args.operation == "preflight":
        expected = binding.get("expected_previous_fundamental_latest_identity")
        payload = {"status": "PASS", "plan": plan, "preexecution_seal": preexecution_seal(plan, expected),
                   "financial_requests": 0, "production_publications": 0}
    else:
        authorization = load_pinned(binding["execution_authorization"])
        validate_plan(plan, universe, plan["authority_id"], plan["execution_main_sha"])
        policy = binding["transport_policy"]
        if policy != {"FinMind": {"timeout_seconds": 20}, "MOPS Official": {"timeout_seconds": 45},
                      "minimum_dispatch_interval_seconds": 13, "automatic_retry": 0, "fallback_allowed": False}:
            raise ValueError("FIRST_REFRESH_TRANSPORT_POLICY_MISMATCH")
        token_name = binding.get("finmind_token_env")
        if not token_name or not os.getenv(token_name):
            raise ValueError("FIRST_REFRESH_FINMIND_TOKEN_MISSING")
        transport = binding["finmind_transport"]
        captures = {
            "FinMind": finmind_capture(transport["path"], transport["sha256"], token=os.getenv(token_name)),
            "MOPS Official": mops_capture(clock=now),
        }
        gate = DispatchGate(13, prior_dispatch=False, utc=now)
        payload = execute_authorized_first_refresh(
            plan, universe, authorization,
            authority_root=binding["authority_root"],
            authority_sha256=binding["authority_sha256"],
            execution_root=binding["execution_root"],
            captures=captures,
            expected_previous_latest=binding.get("expected_previous_fundamental_latest_identity"),
            artifacts_root=binding["artifacts_root"],
            dispatch_gate=gate,
            clock=now,
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.exists():
        raise ValueError("FIRST_REFRESH_OUTPUT_MUST_BE_NEW")
    args.output.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "output_sha256": digest(args.output.read_bytes())}, sort_keys=True))
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
