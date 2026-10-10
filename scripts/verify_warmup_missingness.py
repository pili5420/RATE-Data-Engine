"""Exact-head additive isolation and all inherited synthetic acceptance gates."""
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
from scripts.verify_fundamental_eligibility import GROUPS as PRIOR_GROUPS, deny_network

BASE = "e8aa0f923c4605e57709446dde2ec23cc9edfb17"
ALLOWED = {"src/warmup_missingness.py", "scripts/build_warmup_missingness.py", "scripts/verify_warmup_missingness.py",
    "tests/test_warmup_missingness.py", "docs/RATE_FULL_MARKET_WARMUP_MISSINGNESS_V1.md",
    "docs/contracts/RATE_FULL_MARKET_WARMUP_MISSINGNESS_V1.json", ".github/workflows/rate_warmup_missingness_ci.yml"}
GROUPS = {**PRIOR_GROUPS, "warmup_inventory_new": (["test_warmup_missingness"], 47)}


def proof(directory):
    from tests.test_warmup_missingness import material, AS_OF, LATER
    from src.fundamental_eligibility import digest
    from src.warmup_missingness import build_inventory, verify_inventory
    directory.mkdir(parents=True, exist_ok=True)
    source, universe, context, _ = material(directory)
    kwargs = {"expected_projection_sha256": digest(source), "expected_universe_sha256": digest(universe), "context": context}
    first = build_inventory(source, universe, generated_at=AS_OF, **kwargs)
    second = build_inventory(source, universe, generated_at=LATER, previous=first, **kwargs)
    verify_inventory(second)
    write(directory / "first-inventory.json", first)
    write(directory / "second-inventory.json", second)
    write(directory / "SYNTHETIC_PROOF.json", {"scope": "SYNTHETIC_ENGINEERING_ONLY_NOT_LIVE_ACCEPTANCE",
        "layers": second["core"]["layers"], "counts": second["core"]["counts"], "governance": second["core"]["governance"],
        "all_1978_preserved": len(second["core"]["issuers"]) == 1978,
        "partial_history_preserved": all(r["preserved_owner_evidence"] == s for r, s in zip(second["core"]["issuers"], source["issuers"])),
        "portfolio_ledger_decision_state_context_unchanged": first["core"]["continuity_context"] == second["core"]["continuity_context"] == context,
        "inventory_history_append_only": all(b["inventory_history"][:-1] == a["inventory_history"] for a, b in zip(first["core"]["issuers"], second["core"]["issuers"])),
        "financial_requests": 0, "live_state_writes": 0})


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
                 "src/full_market_history.py", "src/phase2_production.py", "src/fundamental_eligibility.py",
                 "config/RATE_EXTERNAL_PRODUCTION_DEPENDENCIES.json"):
        before = subprocess.check_output(["git", "show", BASE + ":" + path], cwd=ROOT)
        after = subprocess.check_output(["git", "show", args.expected_head + ":" + path], cwd=ROOT)
        owners[path] = {"base_sha256": hashlib.sha256(before).hexdigest(), "head_sha256": hashlib.sha256(after).hexdigest(), "byte_identical": before == after}
    write(args.output_dir / "unchanged-owner-hashes.json", owners)
    temp = args.output_dir.resolve() / "temporary"
    temp.mkdir()
    results = {}
    with tempfile.TemporaryDirectory(prefix="wm-", dir=ROOT.parent) as directory:
        mirror = Path(directory) / "head"
        extract(args.expected_head, mirror)
        (mirror / ".git").write_text("gitdir: " + git("rev-parse", "--absolute-git-dir") + "\n", encoding="utf-8")
        command = [sys.executable, "-B", str(mirror / "scripts/verify_warmup_missingness.py")]
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8", "TEMP": str(temp), "TMP": str(temp)}
        for name, (modules, count) in GROUPS.items():
            output = args.output_dir.resolve() / (name + ".json")
            run = subprocess.run([*command, "--test-child", str(output), *modules], cwd=mirror, capture_output=True, text=True, encoding="utf-8", env=env)
            (args.output_dir / (name + ".log")).write_text(run.stdout + run.stderr, encoding="utf-8")
            result = json.loads(output.read_text(encoding="utf-8"))
            result.update(exit_code=run.returncode, exact_count_pass=result["tests_run"] == count)
            results[name] = result
            print(json.dumps({"group": name, "tests": result["tests_run"], "pass": result["all_pass"]}), flush=True)
        run = subprocess.run([*command, "--proof-child", str(args.output_dir.resolve() / "synthetic-proof")], cwd=mirror, capture_output=True, text=True, encoding="utf-8", env=env)
        (args.output_dir / "synthetic-proof.log").write_text(run.stdout + run.stderr, encoding="utf-8")
        if run.returncode:
            raise ValueError("INVENTORY_SYNTHETIC_PROOF_FAILED")
    passed = all(r["all_pass"] and r["exact_count_pass"] and r["exit_code"] == 0 for r in results.values())
    if git("rev-parse", "HEAD") != args.expected_head or git("status", "--porcelain"):
        raise ValueError("HEAD_OR_WORKTREE_CHANGED")
    write(args.output_dir / "VERIFICATION_PACKAGE.json", {"base_sha": BASE, "head_sha": args.expected_head,
        "changed_files": sorted(ALLOWED), "results": results, "existing_tests": sum(c for _, c in PRIOR_GROUPS.values()),
        "new_tests": GROUPS["warmup_inventory_new"][1], "protected_existing_blobs_unchanged": len(old),
        "existing_owners_and_weights_byte_identical": all(v["byte_identical"] for v in owners.values()),
        "financial_requests": 0, "production_mutations": 0, "production_eligible": False,
        "validation_status": "PASS" if passed else "FAIL"})
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
