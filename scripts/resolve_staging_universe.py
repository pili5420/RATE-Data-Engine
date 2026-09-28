"""Resolve the Control Center staging universe against official symbol masters."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.sources.twse import TWSEAdapter
from src.sources.tpex import TPExAdapter

EXPECTED_STATE_ID = "RATE-V11.1-PS-20260913-V1-r000009"
EXPECTED_STATE_HASH = "f1cc9c5f005a07f081943e279cfab9624079d51ae7d3ef1f1e23ef74b638864b"
EXPECTED_DIGEST = "30276287608b87f7d9b606891514247da523dce9214e4b82bb34ba118a35af4c"


def _rows(payload):
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        data = payload.get("data") or payload.get("records") or []
        fields = payload.get("fields") or []
        if fields and isinstance(data, list):
            return [dict(zip(fields, x)) if isinstance(x, list) else x for x in data if isinstance(x, (list, dict))]
        return [x for x in data if isinstance(x, dict)] if isinstance(data, list) else []
    return []


def _pick(row, *names):
    for name in names:
        value = row.get(name)
        if value not in (None, "", "-", "--"):
            return str(value).strip()
    return None


def canonical_digest(state_id: str, symbols: list[str]) -> str:
    payload = {"source_state_id": state_id, "symbols": symbols}
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _load_approval(path: Path) -> dict:
    obj = json.loads(path.read_text(encoding="utf-8-sig"))
    if obj.get("schema_version") != "RATE-UNIVERSE-V1.0":
        raise RuntimeError("INVALID_PRODUCTION_UNIVERSE_AUTHORITY:SCHEMA")
    if obj.get("validation_scope") != "STAGING_LIVE_ONLY":
        raise RuntimeError("INVALID_PRODUCTION_UNIVERSE_AUTHORITY:SCOPE")
    if obj.get("ranking_status") != "NOT_A_VALIDATED_TOP30_RANKING":
        raise RuntimeError("INVALID_PRODUCTION_UNIVERSE_AUTHORITY:RANKING_STATUS")
    if obj.get("source_state_id") != EXPECTED_STATE_ID or obj.get("source_state_file_sha256") != EXPECTED_STATE_HASH:
        raise RuntimeError("INVALID_PRODUCTION_UNIVERSE_AUTHORITY:STATE_ID_OR_HASH")
    entries = obj.get("symbols")
    if not isinstance(entries, list) or len(entries) != 30:
        raise RuntimeError("INVALID_PRODUCTION_UNIVERSE_AUTHORITY:RECORD_COUNT")
    symbols = [str(x.get("symbol", "")).strip() if isinstance(x, dict) else str(x).strip() for x in entries]
    if any(not s.isdigit() for s in symbols) or len(set(symbols)) != 30:
        raise RuntimeError("INVALID_PRODUCTION_UNIVERSE_AUTHORITY:SYMBOLS")
    if canonical_digest(obj["source_state_id"], symbols) != EXPECTED_DIGEST or obj.get("universe_symbol_digest") != EXPECTED_DIGEST:
        raise RuntimeError("INVALID_PRODUCTION_UNIVERSE_AUTHORITY:DIGEST")
    return obj


def resolve(approval_path: Path, output_path: Path, twse_payload=None, tpex_payload=None) -> dict:
    approval = _load_approval(approval_path)
    if twse_payload is None:
        twse_payload = TWSEAdapter().fetch_symbol_master().get("raw_payload")
    if tpex_payload is None:
        tpex_payload = TPExAdapter().fetch_symbol_master().get("raw_payload")
    twse_rows, tpex_rows = _rows(twse_payload), _rows(tpex_payload)
    def index(rows):
        result = {}
        for row in rows:
            symbol = _pick(row, "symbol", "Code", "公司代號", "公司代碼", "SecuritiesCompanyCode", "股票代號")
            if symbol and symbol.isdigit():
                result.setdefault(symbol, row)
        return result
    twse, tpex = index(twse_rows), index(tpex_rows)
    symbols = approval["symbols"]
    out_symbols = []
    unresolved = []
    for item in symbols:
        symbol = str(item["symbol"]).strip()
        if symbol in twse:
            row, market, source = twse[symbol], "TWSE", "TWSE official listed-company symbol master"
        elif symbol in tpex:
            row, market, source = tpex[symbol], "TPEX", "TPEx official OTC symbol master"
        else:
            unresolved.append(symbol)
            continue
        out_symbols.append({
            "candidate_slot": int(item.get("candidate_slot", len(out_symbols) + 1)),
            "symbol": symbol,
            "name": item.get("name") or _pick(row, "name", "公司名稱", "公司簡稱", "CompanyName") or "",
            "market": market,
            "source_membership": ["PERSISTENT_CANDIDATE_SLOT"],
            "ranking_status": "PENDING_LIVE_RECOMPUTE",
            "market_classification_source": source,
            "classification_timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        })
    if unresolved:
        raise RuntimeError("UNRESOLVED_MARKET:" + ",".join(unresolved))
    if len(out_symbols) != 30 or len({x["symbol"] for x in out_symbols}) != 30:
        raise RuntimeError("INVALID_PRODUCTION_UNIVERSE_AUTHORITY:MARKET_RESOLUTION")
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    twse_count = sum(x["market"] == "TWSE" for x in out_symbols)
    tpex_count = sum(x["market"] == "TPEX" for x in out_symbols)
    result = {
        "artifact": "CONTROL_CENTER_APPROVED_STAGING_VALIDATION_UNIVERSE_V1",
        "schema_version": "RATE-UNIVERSE-V1.0",
        "validation_scope": "STAGING_LIVE_ONLY",
        "ranking_status": "NOT_A_VALIDATED_TOP30_RANKING",
        "source_state_id": approval["source_state_id"],
        "source_state_file_sha256": approval["source_state_file_sha256"],
        "universe_symbol_digest": approval["universe_symbol_digest"],
        "as_of_timestamp": now,
        "markets": {"TWSE": twse_count, "TPEX": tpex_count},
        "symbols": out_symbols,
        "record_count": 30,
        "unique_count": 30,
        "unresolved_market_count": 0,
        "duplicate_count": 0,
        "validation_status": "PASS",
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--approval", default="config/staging/RATE_STAGING_UNIVERSE_APPROVAL_V1.json")
    ap.add_argument("--output", default="config/staging/RATE_STAGING_LIVE_UNIVERSE_V1.json")
    args = ap.parse_args()
    try:
        result = resolve(Path(args.approval), Path(args.output))
        print(json.dumps({"status": "PASS", "record_count": result["record_count"], "markets": result["markets"]}))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "FAIL", "reason": str(exc)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
