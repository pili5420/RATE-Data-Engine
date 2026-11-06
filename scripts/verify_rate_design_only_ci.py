"""Fail-closed design-document PR scope gate. No Production imports or writes."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

DESIGN_FILES = {
    213: "docs/design/RATE_V11_TRACK_B_PROSPECTIVE_REBASELINE_DESIGN_V1.md",
    214: "docs/design/RATE_V11_TRACK_C_INDEPENDENT_SCHEDULER_POC_DESIGN_V1.md",
}
GATE_FILES = {
    ".github/workflows/rate_v11_design_only_ci_gate.yml",
    "scripts/verify_rate_design_only_ci.py",
    "tests/test_rate_design_only_ci.py",
}
FORBIDDEN = (
    "artifacts/", "control/", "config/", "src/", ".github/workflows/rate_production_",
)
SECTIONS = {
    213: (
        "## Problem, source custody and non-credit boundary",
        "## Proposed future new-boundary contract",
        "## Contract-gap matrix",
        "## Offline regression / proof specification",
        "### Owner decisions remaining",
    ),
    214: (
        "## Current immutable authority and observed failure",
        "## Options and recommendation",
        "## Proposed offline architecture",
        "## Contract change impact",
        "## Offline simulated PoC test vectors",
        "### Owner decisions required",
    ),
}
REQUIRED_TEXT = {
    213: ("B01:", "B10:", "900", "POST_REBASELINE_ONLY", "NO_AUTO_NEXT=TRUE"),
    214: ("C01", "C12", "900", "event=schedule", "NO_AUTO_NEXT=TRUE"),
}

class DesignGateError(RuntimeError):
    pass


def ensure(ok: bool, message: str) -> None:
    if not ok:
        raise DesignGateError(message)


def sha(value: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-f]{40}", value))


def validate_scope(*, number: int, base_sha: str, head_sha: str,
                   changed: list[str], document: str | None) -> dict:
    ensure(sha(base_sha) and sha(head_sha) and base_sha != head_sha,
           "DESIGN_GATE_SHA_INVALID")
    ensure(changed and len(changed) == len(set(changed)), "DESIGN_GATE_DIFF_INVALID")
    ensure(not any(path.startswith(FORBIDDEN) for path in changed),
           "DESIGN_GATE_PROTECTED_SCOPE_CHANGED")
    if number in DESIGN_FILES:
        expected = DESIGN_FILES[number]
        ensure(changed == [expected], "DESIGN_GATE_DOC_ONLY_DIFF_REQUIRED")
        ensure(isinstance(document, str) and document.strip(),
               "DESIGN_GATE_DOCUMENT_MISSING")
        ensure(all(section in document for section in SECTIONS[number]),
               "DESIGN_GATE_REQUIRED_SECTIONS_MISSING")
        # Content checks are syntactic, not an independent design-acceptance decision.
        if number == 213:
            checks = ("B01:", "B10:", "POST_REBASELINE_ONLY", "NO_AUTO_NEXT=TRUE")
        else:
            checks = REQUIRED_TEXT[number]
        ensure(all(check in document for check in checks),
               "DESIGN_GATE_REQUIRED_TOPICS_MISSING")
        mode = "DESIGN_DOC_ONLY"
    elif number == 215:
        # Candidate-only self-validation; never trusted for design PR admission.
        ensure(set(changed) == GATE_FILES,
               "DESIGN_GATE_SELF_REVIEW_SCOPE_INVALID")
        ensure(document is None, "DESIGN_GATE_SELF_REVIEW_DOC_FORBIDDEN")
        mode = "UNTRUSTED_CANDIDATE_SELF_REVIEW_ONLY"
    else:
        raise DesignGateError("DESIGN_GATE_PR_NOT_AUTHORIZED")
    return {"artifact": "RATE_V11_DESIGN_ONLY_CI_GATE_V1",
            "validation_status": "PASS", "pr_number": number,
            "validation_mode": mode, "base_sha": base_sha,
            "head_sha": head_sha, "changed_files": changed,
            "production_credit": 0, "cer081_credit": 0}


def git(*args: str) -> str:
    result = subprocess.run(["git", *args], text=True, capture_output=True,
                            encoding="utf-8", check=False)
    ensure(result.returncode == 0, "DESIGN_GATE_GIT_FAILURE")
    return result.stdout.strip()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--pr-number", type=int, required=True)
    p.add_argument("--base-sha", required=True)
    p.add_argument("--head-sha", required=True)
    args = p.parse_args()
    ensure(git("rev-parse", "HEAD") == args.head_sha,
           "DESIGN_GATE_CHECKOUT_HEAD_MISMATCH")
    ensure(git("merge-base", args.base_sha, args.head_sha) == args.base_sha,
           "DESIGN_GATE_BASE_NOT_ANCESTOR")
    ensure(git("status", "--porcelain") == "", "DESIGN_GATE_DIRTY_WORKTREE")
    changed = git("diff", "--name-only", args.base_sha + "..." + args.head_sha).splitlines()
    doc = None
    if args.pr_number in DESIGN_FILES:
        path = Path(DESIGN_FILES[args.pr_number])
        ensure(path.is_file(), "DESIGN_GATE_DOC_NOT_FOUND")
        doc = path.read_text(encoding="utf-8")
    result = validate_scope(number=args.pr_number, base_sha=args.base_sha,
                            head_sha=args.head_sha, changed=changed, document=doc)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
