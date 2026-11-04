"""Hash private TWSE/TPEx authority files and emit metadata only."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))

from src.intraday_exchange_authority_private_evidence import (
    REQUIRED_SCOPE,
    build_private_authority_manifest,
    hash_private_evidence,
)


def main() -> int:
    parser=argparse.ArgumentParser()
    parser.add_argument("--twse-file",required=True)
    parser.add_argument("--tpex-file",required=True)
    parser.add_argument("--twse-reference",required=True)
    parser.add_argument("--tpex-reference",required=True)
    parser.add_argument("--twse-contract-id",required=True)
    parser.add_argument("--tpex-contract-id",required=True)
    parser.add_argument("--twse-scope",required=True,choices=[REQUIRED_SCOPE])
    parser.add_argument("--tpex-scope",required=True,choices=[REQUIRED_SCOPE])
    parser.add_argument("--provider-name",default="Fugle")
    parser.add_argument("--service-id",default="marketdata-v1-stock-intraday-quote")
    parser.add_argument("--credential-secret-name",default="FUGLE_API_KEY")
    parser.add_argument("--valid-from",required=True)
    parser.add_argument("--valid-through",required=True)
    parser.add_argument("--output",required=True)
    args=parser.parse_args()

    output=Path(args.output)
    if output.exists():
        raise RuntimeError("PRIVATE_AUTH_OUTPUT_EXISTS")
    if output.is_absolute() is False:
        output=output.resolve()

    twse=hash_private_evidence(
        args.twse_file,
        market="TWSE",
        evidence_reference=args.twse_reference,
        contract_id=args.twse_contract_id,
        asserted_scope=args.twse_scope,
    )
    tpex=hash_private_evidence(
        args.tpex_file,
        market="TPEX",
        evidence_reference=args.tpex_reference,
        contract_id=args.tpex_contract_id,
        asserted_scope=args.tpex_scope,
    )
    manifest=build_private_authority_manifest(
        twse,tpex,
        provider_name=args.provider_name,
        service_id=args.service_id,
        credential_secret_name=args.credential_secret_name,
        valid_from=args.valid_from,
        valid_through=args.valid_through,
    )
    output.parent.mkdir(parents=True,exist_ok=True)
    with output.open("x",encoding="utf-8",newline="\n") as stream:
        json.dump(manifest,stream,ensure_ascii=False,indent=2,sort_keys=True)
        stream.write("\n")

    print(json.dumps({
        "artifact":manifest["artifact"],
        "status":manifest["status"],
        "twse_sha256":twse["evidence_sha256"],
        "tpex_sha256":tpex["evidence_sha256"],
        "private_evidence_bytes_embedded":0,
        "output":str(output),
    },sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
