"""Exact-head additive isolation, unchanged owners and synthetic regressions."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.verify_public_official_partial_valid import child, extract, git, write
from scripts.verify_provider_calendar_eps import GROUPS as PRIOR_GROUPS

BASE = "af1c9f6c13ab61749d7a465152daebd4ff53bec8"
ALLOWED = {"src/fundamental_eligibility.py", "scripts/build_fundamental_eligibility.py",
    "scripts/verify_fundamental_eligibility.py", "tests/test_fundamental_eligibility.py",
    "docs/RATE_FUNDAMENTAL_ELIGIBILITY_SUBGATE_V1.md",
    "docs/contracts/RATE_FUNDAMENTAL_ELIGIBILITY_SUBGATE_V1.json",
    ".github/workflows/rate_fundamental_eligibility_ci.yml"}
STRATEGY_MODULES = ["test_technical_features", "test_rotation_history", "test_stage_evidence", "test_stage_history",
    "test_institutional_rotation_features", "test_full_rate_replay", "test_state_engine", "test_validation_pipeline",
    "test_stage_bootstrap_state", "test_decision_record_wiring", "test_live_decision_inputs",
    "test_production_layer", "test_live_runtime_closure"]
GROUPS = {**PRIOR_GROUPS, "ranking_strategy_additional_existing": (STRATEGY_MODULES, 119),
          "eligibility_new": (["test_fundamental_eligibility"], 64)}


def deny_network(event, args):
    if event in {"socket.connect", "socket.getaddrinfo", "socket.sendto"}:
        raise RuntimeError("ELIGIBILITY_ENGINEERING_NETWORK_FORBIDDEN:" + event)


def proof(directory):
    from tests.test_fundamental_eligibility import fixture, overlay, LATER
    from src.fundamental_eligibility import gate_owner_ranking
    bundle, universe, context = fixture()
    first = overlay(bundle, universe, context)
    bundle["as_of"] = LATER
    second = overlay(bundle, universe, context, previous=first, generated_at=LATER)
    row = bundle["rows"][1]
    results = {kind: gate_owner_ranking(row, kind=kind, owner_result={"score": 50.125, "rank": 1},
        symbol=row["symbol"], market=row["market"], as_of=LATER, population_id=bundle["universe_id"])
        for kind in ("top50", "long", "short")}
    write(directory / "synthetic-first-overlay.json", first)
    write(directory / "synthetic-second-overlay.json", second)
    write(directory / "SYNTHETIC_PROOF.json", {"scope": "SYNTHETIC_ENGINEERING_ONLY_NOT_REAL_QUALIFICATION",
        "counts": first["core"]["counts"], "missing_fundamental_gates": results,
        "portfolio_ledger_issuer_context_unchanged": first["core"]["continuity_context"] == second["core"]["continuity_context"] == context,
        "parent_snapshot_hash_bound": second["core"]["previous_eligibility_content_sha256"] == first["content_sha256"],
        "all_1978_preserved": len(second["core"]["issuers"]) == 1978,
        "eligibility_history_append_only": all(new["eligibility_history"][:-1] == old["eligibility_history"]
            for old, new in zip(first["core"]["issuers"], second["core"]["issuers"])),
        "financial_requests": 0, "production_mutations": 0, "governance": first["core"]["governance"]})


def main():
    if len(sys.argv) > 1 and sys.argv[1] in {"--test-child", "--proof-child"}:
        sys.addaudithook(deny_network)
        if sys.argv[1] == "--test-child":
            return child(Path(sys.argv[2]), sys.argv[3:])
        proof(Path(sys.argv[2]))
        return 0
    p = argparse.ArgumentParser()
    p.add_argument("--expected-base", required=True)
    p.add_argument("--expected-head", required=True)
    p.add_argument("--output-dir", required=True, type=Path)
    args = p.parse_args()
    if args.output_dir.exists():
        raise ValueError("OUTPUT_MUST_BE_NEW")
    if args.expected_base != BASE or git("rev-parse", "HEAD") != args.expected_head or git("merge-base", BASE, "HEAD") != BASE:
        raise ValueError("EXACT_BASE_HEAD_MISMATCH")
    if set(git("diff", "--name-status", "--no-renames", BASE, args.expected_head).splitlines()) != {"A\t" + f for f in ALLOWED} or git("status", "--porcelain"):
        raise ValueError("EXACT_ADDITIVE_SCOPE_OR_WORKTREE_CHANGED")
    def tree(ref):
        return {line.split("\t", 1)[1]: line.split("\t", 1)[0].split()[2] for line in git("ls-tree", "-r", ref).splitlines()}
    old, new = tree(BASE), tree(args.expected_head)
    if any(new.get(path) != blob for path, blob in old.items()):
        raise ValueError("EXISTING_PRODUCTION_STRATEGY_OR_HISTORICAL_BLOB_CHANGED")
    args.output_dir.mkdir(parents=True)
    write(args.output_dir / "protected-existing-blobs.json", old)
    owners = {}
    for path in ("src/rate_logic.py", "src/fundamental.py", "src/feature_math.py", "src/full_market_rotation.py",
                 "src/full_market_history.py", "src/phase2_production.py", "config/RATE_EXTERNAL_PRODUCTION_DEPENDENCIES.json"):
        before = subprocess.check_output(["git", "show", BASE + ":" + path], cwd=ROOT)
        after = subprocess.check_output(["git", "show", args.expected_head + ":" + path], cwd=ROOT)
        owners[path] = {"base_sha256": hashlib.sha256(before).hexdigest(), "head_sha256": hashlib.sha256(after).hexdigest(),
                        "byte_identical": before == after}
    write(args.output_dir / "ranking-weights-and-owner-hashes.json", owners)
    temp = args.output_dir.resolve() / "temporary"
    temp.mkdir()
    results = {}
    with tempfile.TemporaryDirectory(prefix="elig-", dir=ROOT.parent) as directory:
        mirror = Path(directory) / "head"
        extract(args.expected_head, mirror)
        (mirror / ".git").write_text("gitdir: " + git("rev-parse", "--absolute-git-dir") + "\n", encoding="utf-8")
        command = [sys.executable, "-B", str(mirror / "scripts/verify_fundamental_eligibility.py")]
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8", "TEMP": str(temp), "TMP": str(temp)}
        for name, (modules, count) in GROUPS.items():
            output = args.output_dir.resolve() / (name + ".json")
            run = subprocess.run([*command, "--test-child", str(output), *modules], cwd=mirror,
                capture_output=True, text=True, encoding="utf-8", env=env)
            (args.output_dir / (name + ".log")).write_text(run.stdout + run.stderr, encoding="utf-8")
            result = json.loads(output.read_text(encoding="utf-8"))
            result.update(exit_code=run.returncode, exact_count_pass=result["tests_run"] == count)
            results[name] = result
            print(json.dumps({"group": name, "tests": result["tests_run"], "pass": result["all_pass"]}), flush=True)
        run = subprocess.run([*command, "--proof-child", str(args.output_dir.resolve())], cwd=mirror,
            capture_output=True, text=True, encoding="utf-8", env=env)
        (args.output_dir / "synthetic-proof.log").write_text(run.stdout + run.stderr, encoding="utf-8")
        if run.returncode:
            raise ValueError("ELIGIBILITY_SYNTHETIC_PROOF_FAILED")
    passed = all(r["all_pass"] and r["exact_count_pass"] and r["exit_code"] == 0 for r in results.values())
    if git("rev-parse", "HEAD") != args.expected_head or git("status", "--porcelain"):
        raise ValueError("HEAD_OR_WORKTREE_CHANGED")
    write(args.output_dir / "VERIFICATION_PACKAGE.json", {"base_sha": BASE, "head_sha": args.expected_head,
        "changed_files": sorted(ALLOWED), "results": results, "existing_tests": sum(c for _, c in list(GROUPS.values())[:-1]),
        "new_tests": GROUPS["eligibility_new"][1], "protected_existing_blobs_unchanged": len(old),
        "existing_ranking_weights_byte_identical": all(v["byte_identical"] for v in owners.values()),
        "financial_requests": 0, "production_mutations": 0, "production_eligible": False,
        "validation_status": "PASS" if passed else "FAIL"})
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
