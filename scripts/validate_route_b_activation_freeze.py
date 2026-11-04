from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from src.route_b_activation_package import baseline_policy

ROOT=Path(__file__).resolve().parents[1]
BASELINE="config/RATE_ROUTE_B_ACTIVATION_BASELINE_V1.json"


def git(*args: str) -> str:
    run=subprocess.run(
        ["git","-C",str(ROOT),*args],
        capture_output=True,text=True,encoding="utf-8",
    )
    if run.returncode:
        raise RuntimeError("FREEZE_GIT_COMMAND_FAILED:"+args[0])
    return run.stdout.strip()


def main() -> int:
    p=argparse.ArgumentParser()
    p.add_argument("--expected-base",required=True)
    p.add_argument("--expected-head",required=True)
    a=p.parse_args()

    if git("rev-parse","HEAD")!=a.expected_head:
        raise RuntimeError("FREEZE_HEAD_MISMATCH")
    if git("merge-base",a.expected_base,a.expected_head)!=a.expected_base:
        raise RuntimeError("FREEZE_BASE_NOT_ANCESTOR")
    changed=[x for x in git("diff","--name-only",a.expected_base+".."+a.expected_head).splitlines() if x]
    if changed != [BASELINE]:
        raise RuntimeError("FREEZE_SCOPE_INVALID:"+",".join(changed))
    if git("status","--porcelain"):
        raise RuntimeError("FREEZE_WORKTREE_NOT_CLEAN")

    raw=json.loads((ROOT/BASELINE).read_text(encoding="utf-8"))
    if raw.get("status")!="ACTIVE":
        raise RuntimeError("FREEZE_BASELINE_NOT_ACTIVE")
    if raw.get("activation_merge_sha")!=a.expected_base:
        raise RuntimeError("FREEZE_CODE_SHA_NOT_BASE")
    if raw.get("activation_binding_sha") is not None:
        raise RuntimeError("FREEZE_MANUAL_BINDING_SHA_FORBIDDEN")
    if raw.get("activation_binding_mode")!="DERIVE_FROM_GIT_HISTORY":
        raise RuntimeError("FREEZE_BINDING_MODE_INVALID")
    if raw.get("production_credit_allowed") is not True:
        raise RuntimeError("FREEZE_PRODUCTION_CREDIT_NOT_ENABLED")

    resolved=baseline_policy()
    if resolved.get("activation_merge_sha")!=a.expected_base:
        raise RuntimeError("FREEZE_RESOLVED_CODE_SHA_MISMATCH")
    if resolved.get("activation_binding_sha")!=a.expected_head:
        raise RuntimeError("FREEZE_RESOLVED_BINDING_SHA_MISMATCH")
    if resolved.get("status")!="ACTIVE":
        raise RuntimeError("FREEZE_RESOLVED_STATUS_INVALID")

    print(json.dumps({
        "artifact":"RATE_ROUTE_B_ACTIVATION_FREEZE_VALIDATION_V1",
        "validation_status":"PASS",
        "activation_code_sha":a.expected_base,
        "activation_binding_sha":a.expected_head,
        "changed_files":changed,
        "production_credit_allowed":True,
    },sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
