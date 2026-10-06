"""MAIN-only, history-only bootstrap and append-only durable publication."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.full_market_catalogue import build_catalogue
from src.full_market_history import (aggregate, checkpoint_path, contract, digest, encoded, eligible,
    load_checkpoint, load_material, persist_symbol, put_bytes, put_json, reload_snapshot,
    safe_path, validate_authority, validate_plan, validate_symbol)
from src.full_market_history_acquisition import acquire_shard
from src.production_live_state import require

REPOSITORY = "pili5420/RATE-Data-Engine"
REMOTE = "https://github.com/" + REPOSITORY + ".git"
BRANCH = "rate-production-history"
SOURCE_OVERRIDE_VARS = ("TPEX_HISTORICAL_ENDPOINT", "TPEX_BENCHMARK_HISTORY_ENDPOINT", "TWSE_BENCHMARK_HISTORY_ENDPOINT",
                        "TPEX_INSTITUTIONAL_DAILY_ENDPOINT", "RATE_CER073_ACCEPTED_FUNDAMENTAL_CROSS_SECTION")


def git(root, *args, check=True):
    result = subprocess.run(["git", "-C", str(root), *args], check=check, capture_output=True, text=True, timeout=120)
    return result


def outside_code(path):
    path = Path(path).resolve()
    require(not path.is_relative_to(ROOT) and path != ROOT, "WARMUP_OUTPUT_MUST_BE_OUTSIDE_CODE_CHECKOUT")
    return path


def main_authority():
    value = {"ref": os.getenv("GITHUB_REF"), "event": os.getenv("GITHUB_EVENT_NAME"),
             "run_id": os.getenv("GITHUB_RUN_ID"), "commit_sha": os.getenv("GITHUB_SHA", ""),
             "run_attempt": os.getenv("GITHUB_RUN_ATTEMPT", "1")}
    require(value["ref"] == "refs/heads/main" and value["event"] == "workflow_dispatch"
            and str(value["run_id"]).isdigit() and len(value["commit_sha"]) == 40,
            "WARMUP_MAIN_AUTHORITY_REQUIRED")
    require(os.getenv("GITHUB_REPOSITORY") == REPOSITORY and os.getenv("EXECUTION_AUTHORITY") == "MAIN_ONLY",
            "WARMUP_MAIN_AUTHORITY_REQUIRED")
    require(os.getenv("GITHUB_ACTIONS") == "true", "LOCAL_EVIDENCE_NOT_PRODUCTION_AUTHORITY")
    require(git(ROOT, "rev-parse", "HEAD").stdout.strip() == value["commit_sha"], "WARMUP_SOURCE_COMMIT_MISMATCH")
    require(git(ROOT, "merge-base", "--is-ancestor", value["commit_sha"], "origin/main", check=False).returncode == 0,
            "WARMUP_COMMIT_NOT_MAIN_ANCESTOR")
    require(not any(os.getenv(name) for name in SOURCE_OVERRIDE_VARS), "UNAUTHORIZED_SOURCE_OVERRIDE")
    response = subprocess.run(["gh", "api", "repos/" + REPOSITORY + "/actions/runs/" + value["run_id"]],
                              check=True, capture_output=True, text=True, timeout=60)
    run = json.loads(response.stdout)
    # Whole-run status is volatile while matrix jobs queue/start, not authority.
    require(str(run["id"]) == value["run_id"] and run["head_sha"] == value["commit_sha"]
            and run["head_branch"] == "main" and run["event"] == "workflow_dispatch"
            and run["path"].split("@")[0] == ".github/workflows/rate_full_market_history_bootstrap.yml"
            and str(run["run_attempt"]) == value["run_attempt"],
            "GITHUB_WARMUP_RUN_BINDING_INVALID")
    value["github_execution_evidence"] = {"run_id": str(run["id"]), "head_sha": run["head_sha"],
        "head_branch": run["head_branch"], "event": run["event"], "workflow_path": run["path"].split("@")[0],
        "run_attempt": str(run["run_attempt"])}
    validate_authority(value)
    return value


def open_store(path, *, revision=None):
    path = outside_code(path)
    path.mkdir(parents=True, exist_ok=True)
    require(not any(path.iterdir()), "HISTORY_CHECKOUT_MUST_BE_EMPTY")
    git(path, "init", "--initial-branch=" + BRANCH)
    git(path, "config", "core.autocrlf", "false")
    git(path, "config", "core.eol", "lf")
    git(path, "remote", "add", "origin", REMOTE)
    exists = git(path, "ls-remote", "--heads", "origin", "refs/heads/" + BRANCH).stdout.strip()
    if exists:
        git(path, "fetch", "origin", "refs/heads/" + BRANCH + ":refs/remotes/origin/" + BRANCH)
        git(path, "checkout", "-B", BRANCH, "origin/" + BRANCH)
    require(exists or revision is None, "HISTORY_REVISION_MISSING")
    if revision:
        require(len(revision) == 40 and all(c in "0123456789abcdef" for c in revision), "HISTORY_REVISION_INVALID")
        require(git(path, "merge-base", "--is-ancestor", revision, "origin/" + BRANCH, check=False).returncode == 0,
                "HISTORY_REVISION_NOT_ANCESTOR")
        git(path, "checkout", "--detach", revision)
    return path


def commit_store(root, plan):
    require(git(root, "branch", "--show-current").stdout.strip() == BRANCH, "HISTORY_STORAGE_BRANCH_INVALID")
    require(git(root, "remote", "get-url", "origin").stdout.strip() == REMOTE, "HISTORY_STORAGE_REMOTE_INVALID")
    allowed = {"catalogues", "plans", "materials", "progress", "reports", "shards", "manifests", "snapshots"}
    # No modification/deletion/overwrite is allowed in the dedicated data-plane branch.
    require(not git(root, "diff", "--name-only").stdout.strip(), "IMMUTABLE_HISTORY_CONFLICT")
    for name in git(root, "ls-files", "--others", "--exclude-standard").stdout.splitlines():
        require(name.split("/")[0] in allowed, "HISTORY_STORAGE_PATH_FORBIDDEN")
    git(root, "add", "--all")
    require(not git(root, "diff", "--cached", "--name-only", "--diff-filter=MDRC").stdout.strip(), "IMMUTABLE_HISTORY_CONFLICT")
    if git(root, "diff", "--cached", "--quiet", check=False).returncode == 0:
        return git(root, "rev-parse", "HEAD").stdout.strip()
    git(root, "config", "user.name", "github-actions[bot]")
    git(root, "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com")
    git(root, "commit", "-m", "Persist verified RATE history " + plan["plan_id"])
    # Workflow-wide concurrency makes this the sole writer. A racing remote push
    # fails closed; no force push, reset, rebase, merge or MAIN write is attempted.
    git(root, "push", "origin", "HEAD:refs/heads/" + BRANCH)
    head = git(root, "rev-parse", "HEAD").stdout.strip()
    require(git(root, "ls-remote", "--heads", "origin", "refs/heads/" + BRANCH).stdout.split()[0] == head,
            "HISTORY_DURABLE_COMMIT_UNCONFIRMED")
    return head


def import_progress(root, plan, input_root):
    symbols = {row["symbol"]: row["market"] for row in eligible(plan["catalogue"])}
    incoming = []
    # Validate every incoming symbol before placing any object in durable staging.
    for path in Path(input_root).glob("*/progress/*/*.json"):
        checkpoint = json.loads(path.read_bytes())
        require(checkpoint["plan_id"] == plan["plan_id"] and checkpoint["symbol"] in symbols,
                "CHECKPOINT_BINDING_INVALID")
        symbol = checkpoint["symbol"]
        require(checkpoint["market"] == symbols[symbol], "CHECKPOINT_BINDING_INVALID")
        require(path.name == Path(checkpoint_path(plan, symbol)).name, "CHECKPOINT_BINDING_INVALID")
        material = load_material(path.parents[2], checkpoint["material"])
        require(checkpoint["coverage"] == validate_symbol(material, plan, symbol, symbols[symbol]), "CHECKPOINT_COVERAGE_MISMATCH")
        incoming.append((symbol, material))
    require(len(incoming) == len({symbol for symbol, _ in incoming}), "DUPLICATE_SYMBOL")
    for symbol, material in incoming:
        persist_symbol(root, material, plan, symbol, symbols[symbol])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("plan", "shard", "publish", "reload"))
    parser.add_argument("--as-of")
    parser.add_argument("--resume-plan-id")
    parser.add_argument("--plan")
    parser.add_argument("--shard-id")
    parser.add_argument("--input-root")
    parser.add_argument("--store-root", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--storage-commit")
    parser.add_argument("--snapshot-id")
    args = parser.parse_args()
    output = outside_code(args.output_root)
    output.mkdir(parents=True, exist_ok=True)
    try:
        authority = main_authority()
        root = open_store(args.store_root, revision=args.storage_commit)
        if args.command == "plan":
            if args.resume_plan_id:
                require(args.resume_plan_id.startswith("rate-history-plan-") and len(args.resume_plan_id) == 42,
                        "HISTORY_PLAN_ID_INVALID")
                plan = json.loads(safe_path(root, "plans/" + args.resume_plan_id + ".json").read_bytes())
                validate_plan(plan)
                require(plan["as_of"] == args.as_of, "RESUME_ASOF_MISMATCH")
            else:
                plan = build_history_plan(args.as_of, authority)
            put_json(output, "plan.json", plan)
            put_json(output, "matrix.json", {"include": [{"shard_id": s["shard_id"]} for s in plan["shards"]]})
            result = {"validation_status": "PASS", "plan_id": plan["plan_id"], "eligible_count": len(eligible(plan["catalogue"]))}
        else:
            plan = json.loads(Path(args.plan).read_bytes())
            validate_plan(plan)
            if args.command == "shard":
                result = acquire_shard(plan, args.shard_id, root, output, authority=authority)
                put_json(output, "report.json", result)
            elif args.command == "reload":
                require(args.storage_commit and args.snapshot_id, "EXACT_HISTORY_REVISION_REQUIRED")
                result = reload_snapshot(root, plan, args.snapshot_id)
                put_json(output, "RATE_FULL_MARKET_HISTORY_SNAPSHOT.json", result)
            else:
                require(not args.storage_commit, "READ_ONLY_REVISION_CANNOT_PUBLISH")
                import_progress(root, plan, args.input_root)
                put_json(root, "plans/" + plan["plan_id"] + ".json", plan)
                put_json(root, "catalogues/" + digest(plan["catalogue"]) + ".json", plan["catalogue"])
                try:
                    result = aggregate(root, plan)
                    if result["validation_status"] == "PASS":
                        reload_snapshot(root, plan, result["snapshot_id"])
                except Exception as exc:
                    result = {"artifact": "RATE_FULL_MARKET_HISTORY_COVERAGE", "validation_status": "FAIL_CLOSED",
                              "blocking_reason": str(exc), "fallback_used": False}
                put_json(root, "reports/" + digest(result) + ".json", result)
                commit = commit_store(root, plan)
                result = {**result, "storage_branch": BRANCH, "storage_git_commit_sha": commit,
                          "publishing_runtime_authority": authority, "production_live_state_mutation": 0,
                          "production_state_latest_mutation": 0, "portfolio_mutation": 0, "ledger_mutation": 0}
                put_json(output, "RATE_FULL_MARKET_HISTORY_BOOTSTRAP_RESULT.json", result)
        print(json.dumps(result, ensure_ascii=True))
        return 0 if result["validation_status"] == "PASS" else 1
    except Exception as exc:
        result = {"validation_status": "FAIL_CLOSED", "blocking_reason": str(exc), "fallback_used": False,
                  "production_live_state_mutation": 0, "production_state_latest_mutation": 0,
                  "portfolio_mutation": 0, "ledger_mutation": 0}
        if hasattr(exc, "catalogue_transport_evidence"):
            result["catalogue_transport_evidence"] = exc.catalogue_transport_evidence
        put_json(output, "failure.json", result)
        print(json.dumps(result))
        return 1


def build_history_plan(as_of, authority):
    from src.full_market_history import build_plan
    require(as_of, "WARMUP_ASOF_REQUIRED")
    return build_plan(build_catalogue(as_of), authority)


if __name__ == "__main__":
    raise SystemExit(main())
