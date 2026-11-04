from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from src.cer074_acceptance import atomic_write_json
from src.route_b_acceptance_store import persist_activation_package


def main() -> int:
    p=argparse.ArgumentParser()
    p.add_argument("--package",required=True)
    p.add_argument("--store-root",required=True)
    p.add_argument("--output",required=True)
    a=p.parse_args()
    try:
        package=json.loads(Path(a.package).read_text(encoding="utf-8"))
        result=persist_activation_package(package,a.store_root)
        atomic_write_json(Path(a.output),result)
        print(json.dumps(result,ensure_ascii=False,sort_keys=True))
        return 0
    except Exception as exc:
        result={"artifact":"RATE_ROUTE_B_ACCEPTANCE_STORE_RESULT_V1",
                "validation_status":"FAIL_CLOSED","reason":str(exc)}
        atomic_write_json(Path(a.output),result)
        print(json.dumps(result,ensure_ascii=False,sort_keys=True),file=sys.stderr)
        return 1

if __name__=="__main__":
    raise SystemExit(main())
