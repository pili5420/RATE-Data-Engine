from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from src.cer074_acceptance import atomic_write_json
from src.route_b_git_ancestry import build_ancestry_evidence


def main() -> int:
    p=argparse.ArgumentParser(description="Build Route B Git ancestry evidence")
    p.add_argument("--activation-merge-sha",required=True)
    p.add_argument("--activation-binding-sha",default=None)
    p.add_argument("--source-head",action="append",default=[],
                   help="label=40hexsha; may be repeated")
    p.add_argument("--repo-root",default=".")
    p.add_argument("--output",required=True)
    a=p.parse_args()
    try:
        heads={}
        for item in a.source_head:
            label,sep,sha=item.partition("=")
            if not sep or not label or not sha:
                raise RuntimeError("ROUTE_B_SOURCE_HEAD_ARGUMENT_INVALID")
            if label in heads:
                raise RuntimeError("ROUTE_B_SOURCE_HEAD_DUPLICATE_LABEL")
            heads[label]=sha
        result=build_ancestry_evidence(
            a.repo_root,
            activation_merge_sha=a.activation_merge_sha,
            activation_binding_sha=a.activation_binding_sha,
            source_heads=heads,
        )
        atomic_write_json(Path(a.output),result)
        print(json.dumps(result,ensure_ascii=False,sort_keys=True))
        return 0 if result["validation_status"]=="PASS" else 1
    except Exception as exc:
        result={
            "artifact":"RATE_ROUTE_B_GIT_ANCESTRY_EVIDENCE_V1",
            "validation_status":"FAIL_CLOSED",
            "activation_merge_sha":a.activation_merge_sha,
            "fallback_allowed":False,
            "reason":str(exc),
        }
        atomic_write_json(Path(a.output),result)
        print(json.dumps(result,ensure_ascii=False,sort_keys=True),file=sys.stderr)
        return 1


if __name__=="__main__":
    raise SystemExit(main())
