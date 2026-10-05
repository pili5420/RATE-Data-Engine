"""Exact-date evidence from the approved TPEx individual-stock monthly source."""
import hashlib
import json
import re
from datetime import date, datetime
from pathlib import Path

from .tpex import HISTORICAL_ENDPOINT, normalize_tpex_date

ARTIFACT = "RATE_TPEX_DATE_BOUND_OFFICIAL_HISTORY_V1"


class TPExDateBindingError(RuntimeError):
    def __init__(self, reason, diagnostics):
        super().__init__(reason)
        self.diagnostics = diagnostics


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode()).hexdigest()


def material_path(root, trading_date):
    date.fromisoformat(trading_date)
    return Path(root) / "market_daily_date_bound" / (trading_date + ".json")


def _validate_source(result, symbol, trading_date):
    if (result.get("endpoint") != HISTORICAL_ENDPOINT
            or result.get("source_type") != "OFFICIAL_PRIMARY"
            or result.get("provider") != "TPEx Official OpenAPI"
            or (result.get("diagnostics") or {}).get("http_status") != 200
            or not re.fullmatch(r"[0-9a-f]{64}", str(result.get("content_hash") or ""))):
        raise RuntimeError("TPEX_DATE_BOUND_PROVENANCE_INVALID:" + symbol)
    for key in ("source_timestamp", "retrieval_timestamp"):
        timestamp = datetime.fromisoformat(str(result.get(key) or "").replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            raise RuntimeError("TPEX_DATE_BOUND_TIMESTAMP_INVALID:" + symbol)
    params = result.get("request_params") or {}
    if result.get("request_method") != "POST" or params != {
            "code": symbol, "date": trading_date[:7].replace("-", "/") + "/01", "response": "json"}:
        raise RuntimeError("TPEX_DATE_BOUND_REQUEST_BINDING_INVALID:" + symbol)


def build_material(trading_date, source_results, symbols):
    # Reuse the canonical monthly normalizer, including symbol/period checks.
    from scripts.bootstrap_tpex_history import extract_symbol_month_rows
    period = trading_date[:7].replace("-", "")
    entries = []
    for symbol in symbols:
        result = source_results.get(symbol)
        if result is None:
            raise RuntimeError("TPEX_DATE_BOUND_SOURCE_MISSING:" + symbol)
        _validate_source(result, symbol, trading_date)
        rows = [r for r in extract_symbol_month_rows(result, symbol, period)
                if r["trade_date"] == trading_date]
        if len(rows) != 1:
            raise RuntimeError("TPEX_DATE_BOUND_EXACT_DATE_MISSING:" + symbol)
        entries.append({"symbol": symbol, "record": rows[0],
                        "source_evidence": result,
                        "source_payload_hash": digest(result["raw_payload"])})
    material = {"artifact": ARTIFACT, "validation_status": "PASS",
                "source_authority": "TPEx Official", "requested_trading_date": trading_date,
                "source_effective_date": trading_date, "required_symbols": list(symbols),
                "entries": entries, "fallback_used": False}
    material["historical_material_hash"] = digest(material)
    material["historical_material_id"] = "rate-tpex-date-bound-" + material["historical_material_hash"][:24]
    return material


def load_material(root, trading_date, symbols):
    path = material_path(root, trading_date)
    if not path.is_file():
        raise RuntimeError("TPEX_DATE_BOUND_CANONICAL_MATERIAL_MISSING")
    body = path.read_bytes()
    obj = json.loads(body.decode("utf-8"))
    core = {k: v for k, v in obj.items() if k not in ("historical_material_hash", "historical_material_id")}
    if (obj.get("artifact") != ARTIFACT or obj.get("validation_status") != "PASS"
            or obj.get("historical_material_hash") != digest(core)
            or obj.get("historical_material_id") != "rate-tpex-date-bound-" + digest(core)[:24]
            or obj.get("required_symbols") != list(symbols)
            or obj.get("requested_trading_date") != trading_date
            or obj.get("source_effective_date") != trading_date
            or obj.get("fallback_used") is not False):
        raise RuntimeError("TPEX_DATE_BOUND_MATERIAL_BINDING_INVALID")
    entries = obj.get("entries") or []
    if [e.get("symbol") for e in entries] != list(symbols):
        raise RuntimeError("TPEX_DATE_BOUND_SYMBOL_BINDING_INVALID")
    sources = {}
    for entry in entries:
        source = entry.get("source_evidence") or {}
        if entry.get("source_payload_hash") != digest(source.get("raw_payload")):
            raise RuntimeError("TPEX_DATE_BOUND_SOURCE_HASH_INVALID")
        sources[entry["symbol"]] = source
    rebuilt = build_material(trading_date, sources, symbols)
    if rebuilt != obj:
        raise RuntimeError("TPEX_DATE_BOUND_RECORD_BINDING_INVALID")
    return obj, path, hashlib.sha256(body).hexdigest()


def select_market_daily(current_result, *, trading_date, history_root, symbols):
    date.fromisoformat(trading_date)
    rows = current_result.get("raw_payload") or []
    if not rows:
        raise RuntimeError("TPEX_CURRENT_OFFICIAL_DATE_MISSING")
    current_date = max(normalize_tpex_date(row.get("Date")) for row in rows)
    if trading_date == current_date:
        return {**current_result, "market_daily_source_mode": "CURRENT_OFFICIAL_DAILY",
                "requested_trading_date": trading_date, "source_effective_date": current_date,
                "current_official_date": current_date}
    if trading_date > current_date:
        raise RuntimeError("TPEX_RAW_TRADING_DATE_MISMATCH")
    try:
        material, path, file_hash = load_material(history_root, trading_date, symbols)
    except Exception as exc:
        raise TPExDateBindingError(str(exc), {
            "requested_trading_date": trading_date, "current_official_date": current_date,
            "market_daily_source_mode": "DATE_BOUND_OFFICIAL_HISTORY", "fallback_used": False}) from exc
    entries = material["entries"]
    retrieval = max(e["source_evidence"]["retrieval_timestamp"] for e in entries)
    return {"endpoint": HISTORICAL_ENDPOINT, "raw_payload": [e["record"] for e in entries],
            "content_hash": file_hash,
            "retrieval_timestamp": retrieval,
            "market_daily_source_mode": "DATE_BOUND_OFFICIAL_HISTORY",
            "historical_authority_classification": "DATE_BOUND_AUTHORITATIVE_OFFICIAL_HISTORY",
            "historical_material_id": material["historical_material_id"],
            "historical_material_hash": material["historical_material_hash"],
            "historical_material_file_sha256": file_hash,
            "historical_material_path": str(path), "historical_provenance": entries,
            "requested_trading_date": trading_date, "source_effective_date": trading_date,
            "current_official_date": current_date,
            "current_official_probe": {"endpoint": current_result["endpoint"],
                "body_sha256": current_result["content_hash"],
                "diagnostics": current_result.get("diagnostics")},
            "diagnostics": {"http_status": 200, "parse_status": "PASS", "fallback_used": False,
                            "record_count": len(entries)}}
