"""Current-main exact-head scope, identity-only AST proof and synthetic regression."""
import argparse
import ast
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.verify_public_official_partial_valid import child, extract, git, write
from scripts.verify_history_acquisition_wiring import GROUPS as INHERITED
from scripts.verify_fundamental_ranking_consumer import clean_consumer_checkout, tree
from scripts.verify_ci_applicability import network_guard

BASE = "8471bf53bec15a82da7976ac9be86ac0f9faff5f"
RUNTIME = "src/history_acquisition_validation.py"
WORKFLOW = ".github/workflows/rate_history_acquisition_wiring_ci.yml"
ADDED = {"tests/test_history_twse_title_identity.py", "scripts/verify_history_twse_title_identity.py",
         "docs/RATE_MH_TWSE_TITLE_IDENTITY_FIX_V1.md"}
MODIFIED = {RUNTIME, WORKFLOW}
NEW_COUNT = 43
GROUPS = {**INHERITED, "twse_title_identity_new": (["test_history_twse_title_identity"], NEW_COUNT)}


def runtime_delta(old, new):
    def definitions(text):
        return {node.name: node for node in ast.parse(text).body if isinstance(node, ast.FunctionDef)}
    def dump(value):
        return ast.dump(value, include_attributes=False)
    def outside_identity(text):
        return [dump(node) for node in ast.parse(text).body if not isinstance(node, ast.FunctionDef) or node.name != "identity"]
    if outside_identity(old) != outside_identity(new):
        raise ValueError("TITLE_FIX_OUTSIDE_IDENTITY_CHANGED")
    old_defs, new_defs = definitions(old), definitions(new)
    if set(old_defs) != set(new_defs) or any(dump(value) != dump(new_defs[name]) for name, value in old_defs.items() if name != "identity"):
        raise ValueError("TITLE_FIX_OTHER_RUNTIME_FUNCTION_CHANGED")
    old_id, new_id = old_defs["identity"], new_defs["identity"]
    same = lambda left, right: [dump(node) for node in left] == [dump(node) for node in right]
    old_stock, new_stock = old_id.body[-1], new_id.body[-1]
    if (len(old_stock.body) != len(new_stock.body) or dump(old_stock.test) != dump(new_stock.test)
            or dump(old_stock.body[3].test) != dump(new_stock.body[3].test)
            or not same(old_id.body[:-1], new_id.body[:-1]) or not same(old_stock.body[:3], new_stock.body[:3])):
        raise ValueError("TITLE_FIX_EXPLICIT_IDENTITY_CHANGED")
    if not same(old_stock.orelse, new_stock.orelse):
        raise ValueError("TITLE_FIX_BENCHMARK_CHANGED")
    nested = new_stock.body[3].body
    if len(nested) != 1 or not isinstance(nested[0], ast.If) or not same(old_stock.body[3].body, nested[0].orelse):
        raise ValueError("TITLE_FIX_TPEX_SUBTITLE_CHANGED")
    if dump(nested[0].test) != dump(ast.parse("entry['market'] == 'TWSE'", mode="eval").body):
        raise ValueError("TITLE_FIX_TWSE_ONLY_BOUNDARY_CHANGED")
    return {"status": "TWSE_STOCK_ABSENT_EXPLICIT_IDENTITY_FALLBACK_ONLY", "explicit_identity_unchanged": True,
        "tpex_subtitle_unchanged": True, "benchmark_unchanged": True, "non_identity_functions_unchanged": True}


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--test-child":
        sys.addaudithook(network_guard)
        return child(Path(sys.argv[2]), sys.argv[3:])
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-base", required=True)
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.expected_base != BASE or git("rev-parse", "HEAD") != args.expected_head or git("merge-base", BASE, args.expected_head) != BASE or git("status", "--porcelain"):
        raise ValueError("TITLE_FIX_EXACT_BASE_HEAD_OR_WORKTREE")
    changed = set(git("diff", "--name-status", "--no-renames", BASE, args.expected_head).splitlines())
    if changed != {"A\t" + path for path in ADDED} | {"M\t" + path for path in MODIFIED}:
        raise ValueError("TITLE_FIX_FIVE_FILE_SCOPE_REQUIRED")
    old, new = tree(BASE), tree(args.expected_head)
    if any(new.get(path) != value for path, value in old.items() if path not in MODIFIED):
        raise ValueError("TITLE_FIX_PROTECTED_MAIN_BLOB_CHANGED")
    old_runtime = subprocess.check_output(["git", "show", BASE + ":" + RUNTIME], cwd=ROOT).decode("utf-8")
    delta = runtime_delta(old_runtime, (ROOT / RUNTIME).read_text(encoding="utf-8"))
    if args.output_dir.exists():
        raise ValueError("OUTPUT_MUST_BE_NEW")
    args.output_dir.mkdir(parents=True)
    write(args.output_dir / "PROTECTED_MAIN_BLOBS.json", {path: value for path, value in old.items() if path not in MODIFIED})
    results = {}
    with tempfile.TemporaryDirectory(prefix="twse-title-ci-", dir=ROOT.parent) as directory:
        mirror = Path(directory) / "head"
        extract(args.expected_head, mirror)
        (mirror / ".git").write_text("gitdir: " + git("rev-parse", "--absolute-git-dir") + "\n", encoding="utf-8")
        temp = Path(directory) / "tmp"
        temp.mkdir()
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8", "TEMP": str(temp), "TMP": str(temp)}
        for name, (modules, count) in GROUPS.items():
            repo = mirror
            if name == "consumer_new":
                repo = Path(directory) / "consumer"
                clean_consumer_checkout(args.expected_head, repo)
            report = args.output_dir.resolve() / (name + ".json")
            completed = subprocess.run([sys.executable, "-B", str(repo / "scripts/verify_history_twse_title_identity.py"),
                "--test-child", str(report), *modules], cwd=repo, env=env, capture_output=True)
            (args.output_dir / (name + ".log")).write_bytes(completed.stdout + completed.stderr)
            row = json.loads(report.read_text(encoding="utf-8"))
            row.update(exit_code=completed.returncode, exact_count_pass=row["tests_run"] == count)
            results[name] = row
            print(json.dumps({"group": name, "tests": row["tests_run"], "pass": row["all_pass"]}), flush=True)
    passed = all(row["all_pass"] and row["exact_count_pass"] and not row["exit_code"] and not row["skipped"] for row in results.values())
    if git("status", "--porcelain") or git("rev-parse", "HEAD") != args.expected_head:
        raise ValueError("TITLE_FIX_EXECUTION_BINDING_CHANGED")
    write(args.output_dir / "VERIFICATION_PACKAGE.json", {"status": "PASS" if passed else "BLOCKED", "base_sha": BASE,
        "head_sha": args.expected_head, "changed_files": sorted(ADDED | MODIFIED), "runtime_delta": delta,
        "existing_tests": sum(count for _, count in INHERITED.values()), "new_tests": NEW_COUNT,
        "total_tests": sum(count for _, count in GROUPS.values()), "results": results,
        "protected_existing_blobs_preserved": len(old) - len(MODIFIED), "runtime_files_changed": [RUNTIME],
        "tests_skipped": sum(len(row["skipped"]) for row in results.values()), "assertions_relaxed": 0, "failure_whitelists": 0,
        "official_market_data_requests": 0, "ranking_executions": 0, "production_publications": 0,
        "authorization_reused": False, "live_qualification_executed": False, "strategy_ranking_files_modified": 0,
        "historical_pit": "UNPROVEN", "calendar_180_ready": False, "intraday": "BLOCKED_EXTERNAL",
        "fallback_allowed": False, "tpex_unit_scale": "TPEX_UNIT_SCALE_QUALIFICATION_REQUIRED", "material_scope": "SYNTHETIC_ONLY"})
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
