"""Read-only PR29/PR30 integration proof; never publish or dispatch warmup."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ORIGINAL_BASE = "40c00f300d6ba64ca06850ba172fd1df222d1c86"
REVIEWED_PR29 = "7d8d4ebd22f6b28218786546c3ce7a3f65d6cd4a"
ACCEPTED_MAIN = "54f30786a05acad3106acb727c6653ed23ecbb48"
DIAGNOSTIC_PATHS = frozenset({
    "src/sources/fundamental_history.py",
    "tests/test_full_market_history.py",
    "tests/test_full_market_history_acquisition.py",
    "tests/test_full_market_history_yoy_semantics.py",
})
HARNESS_PATHS = frozenset({
    "scripts/verify_rate_eps_postmerge_integration.py",
    ".github/workflows/rate_eps_postmerge_integration_ci.yml",
})
ROOT = Path(__file__).resolve().parents[1]


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise RuntimeError(reason)



def validate_base_binding(event_base: str, observed_main: str) -> None:
    require(event_base in (ORIGINAL_BASE, ACCEPTED_MAIN), "EVENT_BASE_BINDING_INVALID")
    require(observed_main == ACCEPTED_MAIN, "OBSERVED_MAIN_ADVANCED_REVIEW_REQUIRED")


def git(root: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", "-c", "core.autocrlf=false", *args], cwd=root)


def tree(root: Path, ref: str) -> dict:
    result = {}
    for entry in git(root, "ls-tree", "-r", "-z", ref).split(b"\0"):
        if not entry:
            continue
        metadata, path = entry.split(b"\t", 1)
        mode, kind, digest = metadata.decode("ascii").split()
        require(kind == "blob" and mode in ("100644", "100755", "120000"), "UNSUPPORTED_TREE_ENTRY")
        result[path.decode("utf-8")] = (mode, kind, digest)
    return result


def changed_paths(before: dict, after: dict) -> set:
    return {path for path in before.keys() | after.keys() if before.get(path) != after.get(path)}


def working_fingerprints(root: Path, expected: dict) -> dict:
    result = {}
    for relative, (mode, _kind, digest) in expected.items():
        path = root / relative
        if mode == "120000":
            require(path.is_symlink(), "SYMLINK_MODE_MISMATCH:" + relative)
            data = os.fsencode(os.readlink(path))
        else:
            require(path.is_file() and not path.is_symlink(), "WORKTREE_FILE_MISSING:" + relative)
            data = path.read_bytes()
        actual = hashlib.sha1(b"blob " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest()
        require(actual == digest, "WORKTREE_BYTE_MISMATCH:" + relative)
        result[relative] = hashlib.sha256(data).hexdigest()
    require(not git(root, "status", "--porcelain", "--untracked-files=all").strip(), "WORKTREE_NOT_CLEAN")
    return result


def run_tests(root: Path, command: list, logfile: Path, expected_count: int, head: str) -> dict:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["RATE_WARMUP_CI_HEAD_SHA"] = head
    with logfile.open("xb") as stream:
        try:
            completed = subprocess.run(command, cwd=root, env=env, stdout=stream,
                                       stderr=subprocess.STDOUT, timeout=600, check=False)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("TEST_BUDGET_EXHAUSTED:" + logfile.name) from exc
    log = logfile.read_text(encoding="utf-8", errors="replace")
    matches = re.findall(r"^Ran (\d+) tests? in ", log, flags=re.MULTILINE)
    require(len(matches) == 1, "TEST_COUNT_UNPROVEN:" + logfile.name)
    count = int(matches[0])
    require(completed.returncode == 0 and re.search(r"^OK\s*$", log, flags=re.MULTILINE) is not None,
            "REGRESSION_FAILED:" + logfile.name)
    require(count == expected_count, "TEST_COUNT_CHANGED_REVIEW_REQUIRED:" + logfile.name)
    return {"test_count": count, "exit_code": completed.returncode, "status": "PASS",
            "log_sha256": hashlib.sha256(logfile.read_bytes()).hexdigest()}


def verify(output: Path, expected_head: str, expected_base: str, report: dict) -> None:
    head = git(ROOT, "rev-parse", "HEAD").decode().strip()
    require(re.fullmatch(r"[0-9a-f]{40}", expected_head) is not None and head == expected_head,
            "PR_HEAD_BINDING_INVALID")
    observed_main = git(ROOT, "rev-parse", "refs/remotes/origin/main").decode().strip()
    report.update({"pr_head_sha": head, "event_base_sha": expected_base,
                   "accepted_main_sha": ACCEPTED_MAIN, "observed_main_sha": observed_main})
    # PR event metadata may retain the original branch base. It is not the
    # target of this integration proof. Preserve it and verify both identities.
    validate_base_binding(expected_base, observed_main)
    git(ROOT, "merge-base", "--is-ancestor", REVIEWED_PR29, head)
    require(git(ROOT, "merge-base", ACCEPTED_MAIN, REVIEWED_PR29).decode().strip() == ORIGINAL_BASE,
            "HISTORICAL_BASE_BINDING_INVALID")
    original = tree(ROOT, ORIGINAL_BASE)
    approved = tree(ROOT, REVIEWED_PR29)
    main_tree = tree(ROOT, ACCEPTED_MAIN)
    head_tree = tree(ROOT, head)
    require(changed_paths(original, approved) == DIAGNOSTIC_PATHS, "REVIEWED_PR29_SCOPE_CHANGED")
    require(all(path in original and path in approved for path in DIAGNOSTIC_PATHS), "PR29_NOT_MODIFICATION_ONLY")
    require(changed_paths(approved, head_tree) == HARNESS_PATHS and
            all(path not in approved and path in head_tree for path in HARNESS_PATHS),
            "NEW_CHANGE_NOT_CI_ONLY")
    require(all(main_tree.get(path) == value for path, value in original.items()), "PR30_BASE_BYTES_CHANGED")
    require(len(main_tree) - len(original) == 14, "PR30_ADDITION_COUNT_CHANGED")
    working_fingerprints(ROOT, head_tree)
    expected_tree = dict(main_tree)
    expected_tree.update({path: head_tree[path] for path in DIAGNOSTIC_PATHS | HARNESS_PATHS})
    report.update({"reviewed_pr29_sha": REVIEWED_PR29, "pr_head_sha": head,
                   "accepted_main_sha": ACCEPTED_MAIN, "historical_base_sha": ORIGINAL_BASE,
                   "scope_validation": "PASS", "harness_only_additions": sorted(HARNESS_PATHS)})
    roots = []
    with tempfile.TemporaryDirectory(prefix="rate-eps-integration-") as temporary:
        temporary = Path(temporary)
        try:
            isolated = temporary / "isolated"
            git(ROOT, "worktree", "add", "--detach", str(isolated), ACCEPTED_MAIN)
            roots.append(isolated)
            before = working_fingerprints(isolated, main_tree)
            try:
                report["pr30_original_isolation"] = run_tests(
                    isolated, [sys.executable, "-B", "scripts/verify_eps_duration_isolation.py"],
                    output / "pr30-original-isolation.log", 302, ACCEPTED_MAIN)
            finally:
                require(working_fingerprints(isolated, main_tree) == before, "ISOLATED_WORKING_BYTES_CHANGED")
            combined = temporary / "combined"
            git(ROOT, "worktree", "add", "--detach", str(combined), ACCEPTED_MAIN)
            roots.append(combined)
            git(combined, "-c", "user.name=RATE Integration CI", "-c", "user.email=ci@localhost",
                "merge", "--no-commit", "--no-ff", head)
            tree_sha = git(combined, "write-tree").decode().strip()
            require(tree(ROOT, tree_sha) == expected_tree, "PROSPECTIVE_MERGE_TREE_MISMATCH")
            local_commit = git(combined, "-c", "user.name=RATE Integration CI", "-c", "user.email=ci@localhost",
                               "commit-tree", tree_sha, "-p", ACCEPTED_MAIN, "-p", head,
                               "-m", "LOCAL_CI_ONLY PR29 + isolated PR30; no remote publication").decode().strip()
            git(combined, "merge", "--abort")
            git(combined, "checkout", "--detach", local_commit)
            before_combined = working_fingerprints(combined, expected_tree)
            script = ast.parse((isolated / "scripts/verify_eps_duration_isolation.py").read_text(encoding="utf-8"))
            assignments = [node for node in script.body if isinstance(node, ast.Assign) and
                           any(isinstance(target, ast.Name) and target.id == "MODULES" for target in node.targets)]
            require(len(assignments) == 1, "CANONICAL_SUITE_UNPROVEN")
            modules = ast.literal_eval(assignments[0].value)
            require(isinstance(modules, tuple) and all(isinstance(item, str) for item in modules), "CANONICAL_SUITE_INVALID")
            report.update({"integration_commit_local_only": local_commit,
                           "integration_tree_sha": tree_sha,
                           "integration_parents": [ACCEPTED_MAIN, head]})
            try:
                report["combined_regression"] = run_tests(
                    combined, [sys.executable, "-B", "-m", "unittest", *modules, "-v"],
                    output / "combined-regression.log", 312, local_commit)
            finally:
                require(working_fingerprints(combined, expected_tree) == before_combined, "COMBINED_WORKING_BYTES_CHANGED")
            protected = {path: value for path, value in main_tree.items() if path not in DIAGNOSTIC_PATHS}
            require(all(expected_tree.get(path) == value for path, value in protected.items()), "PROTECTED_MAIN_BYTES_CHANGED")
            report.update({"protected_main_file_count": len(protected), "protected_main_git_blobs": "PASS",
                           "pr30_files_and_raw_archive_preserved": "PASS", "working_bytes_unchanged": "PASS",
                           "result": "PASS", "release_scope": "DIAGNOSTIC_ONLY_PLUS_ISOLATED_ONLY",
                           "source_proof": "BLOCKED", "historical_pit": "BLOCKED", "production_readiness": "BLOCKED",
                           "production_coverage_credit": 0, "run5_dispatched": False,
                           "old_plan_resumed": False, "remote_writes": False})
        finally:
            for root in reversed(roots):
                subprocess.run(["git", "worktree", "remove", "--force", str(root)], cwd=ROOT, check=False)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--expected-base", required=True)
    args = parser.parse_args()
    output = Path(args.output_dir).resolve()
    require(output != ROOT and ROOT not in output.parents and not output.exists(), "OUTPUT_MUST_BE_NEW_EXTERNAL_DIRECTORY")
    output.mkdir(parents=True)
    report = {"artifact": "RATE_EPS_PR29_PR30_INTEGRATION", "result": "FAIL_CLOSED",
              "evidence_kind": "ENGINEERING_CI_ONLY", "production_coverage_credit": 0}
    try:
        verify(output, args.expected_head, args.expected_base, report)
    except Exception as exc:
        report.update({"result": "FAIL_CLOSED", "error_class": type(exc).__name__, "reason": str(exc)})
    (output / "acceptance.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["result"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
