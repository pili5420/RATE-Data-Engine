"""Base/head-bound additive isolation and engineering-only offline verification."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.eps_duration_facts.model import Rejected, require
from src.eps_duration_facts.raw import sha256

ADDITIONS = {
    "src/provider_eps_candidate.py", "scripts/build_provider_eps_candidate.py",
    "scripts/verify_provider_eps_candidate.py", "tests/test_provider_eps_candidate.py",
    "tests/provider_eps_engineering_fixture.py",
    "tests/fixtures/provider_eps_candidate/engineering_spec.json",
    "docs/RATE_PROVIDER_EPS_CANDIDATE.md",
    ".github/workflows/rate_provider_eps_candidate_ci.yml",
}
COVERAGE_CHANGES = {
    "src/provider_eps_candidate.py": "M", "scripts/verify_provider_eps_candidate.py": "M",
    "src/provider_eps_coverage.py": "A", "scripts/scan_provider_eps_coverage.py": "A",
    "scripts/verify_provider_eps_coverage.py": "A", "tests/test_provider_eps_coverage.py": "A",
    "docs/RATE_PROVIDER_EPS_COVERAGE.md": "A", ".github/workflows/rate_provider_eps_coverage_ci.yml": "A",
}
RECOVERY_CHANGES = {**COVERAGE_CHANGES, "src/provider_eps_dispatch.py": "A",
    "src/provider_eps_recovery.py": "A", "scripts/recover_provider_eps_coverage.py": "A",
    "tests/test_provider_eps_recovery.py": "A"}


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT)


def binding(base, head):
    actual = git("rev-parse", "HEAD").decode().strip()
    require(actual == head and git("rev-parse", base).decode().strip() == base, "CODE_SHA_BINDING_MISMATCH")
    require(subprocess.run(["git", "merge-base", "--is-ancestor", base, head], cwd=ROOT).returncode == 0, "BASE_NOT_ANCESTOR")
    require(not git("status", "--porcelain", "--untracked-files=all"), "WORKTREE_NOT_CLEAN")
    changes = git("diff", "--name-status", "--no-renames", base, head).decode().splitlines()
    has_candidate = subprocess.run(["git", "cat-file", "-e", base + ":src/provider_eps_candidate.py"],
                                  cwd=ROOT, capture_output=True).returncode == 0
    has_recovery = subprocess.run(["git", "cat-file", "-e", head + ":src/provider_eps_recovery.py"],
                                 cwd=ROOT, capture_output=True).returncode == 0
    allowed = (RECOVERY_CHANGES if has_recovery else COVERAGE_CHANGES) if has_candidate else {name: "A" for name in ADDITIONS}
    changed = []
    for line in changes:
        status, name = line.split("\t")
        require(allowed.get(name) == status, "EXISTING_OR_UNAUTHORIZED_FILE_CHANGED:" + name)
        changed.append(name)
    require(set(changed) == set(allowed), "CANDIDATE_ADDITIONS_INCOMPLETE")
    base_tree = git("ls-tree", "-r", "-z", base).split(b"\0")
    head_tree = dict(entry.split(b"\t", 1)[::-1] for entry in git("ls-tree", "-r", "-z", head).split(b"\0") if entry)
    protected = {}
    for entry in base_tree:
        if not entry:
            continue
        mode_blob, name_bytes = entry.split(b"\t", 1)
        name = name_bytes.decode()
        if allowed.get(name) == "M":
            continue
        require(head_tree.get(name_bytes) == mode_blob, "BASE_FILE_BLOB_CHANGED:" + name)
        body = (ROOT / name).read_bytes()
        if name.startswith(("src/", "scripts/")) and name.endswith(".py") and name not in ADDITIONS:
            require(b"provider_eps_candidate" not in body and b"provider_eps_coverage" not in body,
                    "EXISTING_ENTRY_DEPENDS_ON_CANDIDATE:" + name)
        protected[name] = {"git_tree_entry": mode_blob.decode(), "working_bytes": len(body), "working_sha256": sha256(body)}
    return {"base_sha": base, "head_sha": head, "changed_files": sorted(changed),
            "existing_tracked_file_count": len(protected), "existing_tracked_files": protected,
            "existing_files_unchanged": not any(status == "M" for status in allowed.values()),
            "authorized_modified_files": sorted(name for name, status in allowed.items() if status == "M"),
            "protected_existing_files_unchanged": True, "active_consumer_dependency_added": False}


def write_json(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=True, allow_nan=False)
        stream.write("\n")


def new_output(value, input_dir=None):
    output = Path(value).resolve()
    require(not output.exists(), "OUTPUT_ALREADY_EXISTS")
    require(not output.is_relative_to(ROOT), "OUTPUT_MUST_BE_OUTSIDE_REPOSITORY")
    if input_dir is not None:
        require(not output.is_relative_to(input_dir), "OUTPUT_MUST_NOT_OVERWRITE_INPUT_TREE")
    require(not any(part.lower() in {"production", "latest", "state", "portfolio", "ledger"} for part in output.parts), "PROTECTED_OUTPUT_FORBIDDEN")
    output.mkdir(parents=True, exist_ok=False)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-base", required=True)
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    before = binding(args.expected_base, args.expected_head)
    output = new_output(args.output_dir)
    run = subprocess.run([sys.executable, "-B", "-m", "unittest", "tests.test_provider_eps_candidate", "-v"],
                         cwd=ROOT, capture_output=True, text=True)
    (output / "engineering-tests.log").write_text(run.stdout + run.stderr, encoding="utf-8")
    require(run.returncode == 0, "ENGINEERING_TESTS_FAILED")
    from src.provider_eps_candidate import ENGINEERING, build_candidate, consume_candidate
    from tests.provider_eps_engineering_fixture import make_fixture
    with tempfile.TemporaryDirectory(prefix="rate-provider-eps-ci-") as temporary:
        inputs = make_fixture(Path(temporary))
        first = build_candidate(inputs, {"base_sha": args.expected_base, "head_sha": args.expected_head})
        second = build_candidate(inputs, first["code_binding"])
        require(first["material_class"] == ENGINEERING, "REAL_DATA_FORBIDDEN_IN_ENGINEERING_CI")
        require(first["artifact_id"] == second["artifact_id"] and consume_candidate(first) == consume_candidate(second), "ENGINEERING_REPLAY_NOT_REPRODUCIBLE")
        write_json(output / "engineering-candidate.json", first)
        write_json(output / "engineering-consumption-preview.json", consume_candidate(first))
    after = binding(args.expected_base, args.expected_head)
    require(before == after, "EXISTING_FILES_CHANGED_DURING_TESTS")
    write_json(output / "verification.json", {"status": "PASS", "material_class": ENGINEERING,
        "validated_at": datetime.now(timezone.utc).isoformat(), "real_finmind_replay": "NOT_RUN_IN_PUBLIC_CI",
        "engineering_test_exit_code": run.returncode, "repeated_replay_stable": True,
        "formal_eight_quarter_acceptance": "NOT_PERFORMED", "production_eligible": False,
        "original_eight_quarter_coverage_credit": 0, "isolation": before})
    print(json.dumps({"status": "PASS", "material_class": ENGINEERING, "output_dir": str(output)}))


if __name__ == "__main__":
    try:
        main()
    except Rejected as exc:
        print("REJECTED: " + str(exc), file=sys.stderr)
        raise SystemExit(1)
