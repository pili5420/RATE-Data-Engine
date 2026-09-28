from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.cer074_acceptance import atomic_write_json
from src.live_decision_inputs import build_live_decision_records
from scripts.publish_production_source_bundle_latest import validate_production_source_bundle

REQUIRED_DECISION_COVERAGE = 30


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def source_record_count(parsed: Any) -> int:
    if isinstance(parsed, list):
        return len(parsed)
    if not isinstance(parsed, dict):
        return 0
    if isinstance(parsed.get("production_sources"), dict):
        return len(parsed["production_sources"])
    if isinstance(parsed.get("universe"), list):
        return len(parsed["universe"])
    for key in ("data", "records", "decision_input_records", "normalized_records"):
        if isinstance(parsed.get(key), list):
            return len(parsed[key])
    return 0


def fetch_url(url: str, timeout: int = 20) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": "RATE-Production-Scheduler/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read(20_000_000)
        content_type = response.headers.get("content-type", "")
        text = body.decode("utf-8", errors="replace")
        parsed = None
        if "json" in content_type.lower() or text.strip().startswith(("{", "[")):
            parsed = json.loads(text)
        return {
            "url": url,
            "http_status": response.getcode(),
            "content_type": content_type,
            "retrieval_timestamp": utc_now(),
            "record_count": source_record_count(parsed),
            "json_parse_status": "PASS" if parsed is not None else "FAIL",
            "raw_payload": parsed,
        }


def _rows(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [row for row in value if isinstance(row, dict)]
    if not isinstance(value, dict):
        return []
    for key in ("records", "data", "decision_input_records", "normalized_records"):
        rows = value.get(key)
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
    return []


def _symbol(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _production_source_from_row(row: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    symbol = _symbol(row.get("symbol") or row.get("stock_id") or row.get("ticker"))
    if not symbol:
        raise RuntimeError("MALFORMED_SOURCE_JOIN:SYMBOL_MISSING")
    if isinstance(row.get("technical_features"), dict):
        source = dict(row)
    else:
        source = {"technical_features": dict(row)}
        for key in (
            "FI", "IT", "LH", "FC", "SMART_MONEY", "RS_CHANGE", "VOL_CHANGE",
            "MOMENTUM_CHANGE", "Rotation", "Fundamental", "Rotation_inputs",
            "SmartMoney_inputs", "Stage_inputs", "Stage_evidence", "feature_lineage",
        ):
            if key in row:
                source[key] = row[key]
    source.pop("symbol", None)
    source.pop("stock_id", None)
    source.pop("ticker", None)
    return symbol, source


def assemble_production_bundle(*, payloads: list[dict[str, Any]], trading_date: str, cadence: str, retrieval_timestamp: str) -> tuple[dict[str, Any], dict[str, Any]]:
    universe: list[str] = []
    production_sources: dict[str, dict[str, Any]] = {}
    source_trading_dates = set()
    source_versions = []
    dataset_evidence = []

    for payload in payloads:
        if not isinstance(payload, dict):
            raise RuntimeError("OFFICIAL_SOURCE_PAYLOAD_NOT_OBJECT")
        raw = payload.get("raw_payload")
        if not isinstance(raw, (dict, list)):
            raise RuntimeError("OFFICIAL_SOURCE_JSON_PAYLOAD_MISSING")
        objects = raw if isinstance(raw, list) else [raw]
        for obj in objects:
            if not isinstance(obj, dict):
                continue
            if obj.get("trading_date"):
                source_trading_dates.add(str(obj["trading_date"]))
            if obj.get("schema_version") or obj.get("bundle_version"):
                source_versions.append(obj.get("schema_version") or obj.get("bundle_version"))
            obj_universe = obj.get("universe") or obj.get("symbols")
            if isinstance(obj_universe, list):
                for item in obj_universe:
                    symbol = _symbol(item.get("symbol") if isinstance(item, dict) else item)
                    if symbol and symbol not in universe:
                        universe.append(symbol)
            prod = obj.get("production_sources")
            if isinstance(prod, dict):
                for symbol, source in prod.items():
                    mapped = _symbol(symbol)
                    if not mapped or not isinstance(source, dict):
                        raise RuntimeError("MALFORMED_SOURCE_JOIN:PRODUCTION_SOURCE")
                    production_sources[mapped] = dict(source)
                    if mapped not in universe:
                        universe.append(mapped)
            for row in _rows(obj):
                symbol, source = _production_source_from_row(row)
                production_sources[symbol] = source
                if symbol not in universe:
                    universe.append(symbol)
            dataset_evidence.append({
                "url": payload.get("url"),
                "http_status": payload.get("http_status"),
                "json_parse_status": payload.get("json_parse_status"),
                "record_count": payload.get("record_count"),
            })

    universe = sorted(dict.fromkeys(universe))
    if not universe:
        raise RuntimeError("OFFICIAL_SOURCE_UNIVERSE_MISSING")
    if source_trading_dates and source_trading_dates != {trading_date}:
        raise RuntimeError("SOURCE_TRADING_DATE_MISMATCH")
    missing = [symbol for symbol in universe if symbol not in production_sources]
    if missing:
        raise RuntimeError("MALFORMED_SOURCE_JOIN:MISSING_PRODUCTION_SOURCE")

    built = build_live_decision_records(production_sources, trading_date, universe)
    decision_records = built["decision_records"]
    coverage = f"{len(decision_records)}/{REQUIRED_DECISION_COVERAGE}"
    transformation = {
        "source_retrieval": "PASS",
        "normalization": "PASS",
        "symbol_mapping": "PASS",
        "required_dataset_joins": "PASS" if built["feature_validation"]["status"] == "PASS" else "FAIL",
        "decision_record_construction": "PASS" if built["feature_validation"]["status"] == "PASS" else "FAIL",
        "decision_record_coverage": coverage,
        "required_coverage": f"{REQUIRED_DECISION_COVERAGE}/{REQUIRED_DECISION_COVERAGE}",
        "universe_count": len(universe),
        "production_source_count": len(production_sources),
        "feature_validation": built["feature_validation"],
        "datasets": dataset_evidence,
    }
    if built["feature_validation"]["status"] != "PASS":
        raise RuntimeError("DATA_INCOMPLETE:PRODUCTION_DECISION_INPUT_UNAVAILABLE")
    if len(decision_records) != REQUIRED_DECISION_COVERAGE or len(universe) != REQUIRED_DECISION_COVERAGE:
        raise RuntimeError("INSUFFICIENT_DECISION_RECORD_COVERAGE")

    bundle = {
        "artifact": "RATE_PRODUCTION_SOURCE_BUNDLE",
        "bundle_version": "RATE-PRODUCTION-SOURCE-V1",
        "schema_version": "RATE-PRODUCTION-SOURCE-BUNDLE-V1",
        "validation_status": "PASS",
        "source_bundle_validation": "PASS",
        "trading_date": trading_date,
        "cadence": cadence,
        "retrieval_timestamp": retrieval_timestamp,
        "source_provenance": {
            "source": "RATE_OFFICIAL_TW_MARKET_DATA_SSOT",
            "retrieval_timestamp": retrieval_timestamp,
            "trading_date": trading_date,
            "source_schema_versions": sorted(set(str(v) for v in source_versions if v)),
            "rate_source_url_configured": True,
            "fixture_fallback": "FORBIDDEN",
            "historical_acceptance_bundle_fallback": "FORBIDDEN",
            "cer073_live_fallback": "FORBIDDEN",
            "stale_snapshot_fallback": "FORBIDDEN",
            "local_desktop_dependency": "FORBIDDEN",
        },
        "universe": universe,
        "production_sources": production_sources,
        "records": decision_records,
        "decision_records": decision_records,
        "coverage": coverage,
        "decision_record_coverage": {
            "status": "PASS",
            "actual": len(decision_records),
            "required": REQUIRED_DECISION_COVERAGE,
            "coverage": coverage,
        },
        "official_source_transformation": transformation,
        "short_term_top30": universe,
        "roy_portfolio": [],
        "required_benchmarks": ["TAIEX", "TPEX"],
        "explicit_production_watchlist": [],
    }
    return bundle, transformation


def _redact_payloads(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{k: v for k, v in item.items() if k != "raw_payload"} for item in sources]


def build_bundle(*, rate_source_url: str, trading_date: str, cadence: str, output: str | Path, evidence_output: str | Path) -> dict[str, Any]:
    if not rate_source_url or not rate_source_url.strip():
        raise RuntimeError("RATE_SOURCE_URL_MISSING")
    urls = [u.strip() for u in rate_source_url.split(";") if u.strip()]
    if not urls:
        raise RuntimeError("RATE_SOURCE_URL_EMPTY")

    retrieval_timestamp = utc_now()
    sources = []
    for url in urls:
        try:
            result = fetch_url(url)
            result["status"] = "PASS" if result["json_parse_status"] == "PASS" and result["raw_payload"] is not None else "FAIL"
            sources.append(result)
        except Exception as exc:
            sources.append({"url": url, "status": "FAIL", "retrieval_timestamp": utc_now(), "error": str(exc)})

    blocking_reason = None
    transformation: dict[str, Any] = {}
    try:
        if not sources or any(item.get("status") != "PASS" for item in sources):
            raise RuntimeError("OFFICIAL_SOURCE_FETCH_OR_PARSE_FAIL")
        bundle, transformation = assemble_production_bundle(payloads=sources, trading_date=trading_date, cadence=cadence, retrieval_timestamp=retrieval_timestamp)
    except Exception as exc:
        blocking_reason = str(exc)
        bundle = {
            "artifact": "RATE_PRODUCTION_SOURCE_BUNDLE",
            "bundle_version": "RATE-PRODUCTION-SOURCE-V1",
            "schema_version": "RATE-PRODUCTION-SOURCE-BUNDLE-V1",
            "validation_status": "BLOCKED",
            "source_bundle_validation": "BLOCKED",
            "trading_date": trading_date,
            "cadence": cadence,
            "retrieval_timestamp": retrieval_timestamp,
            "source_provenance": {
                "source": "RATE_OFFICIAL_TW_MARKET_DATA_SSOT",
                "retrieval_timestamp": retrieval_timestamp,
                "trading_date": trading_date,
                "rate_source_url_configured": True,
                "fixture_fallback": "FORBIDDEN",
                "historical_acceptance_bundle_fallback": "FORBIDDEN",
                "cer073_live_fallback": "FORBIDDEN",
                "stale_snapshot_fallback": "FORBIDDEN",
                "local_desktop_dependency": "FORBIDDEN",
            },
            "sources": _redact_payloads(sources),
            "records": [],
            "decision_records": [],
            "coverage": "0/30",
            "decision_record_coverage": {"status": "FAIL", "actual": 0, "required": REQUIRED_DECISION_COVERAGE, "coverage": "0/30"},
            "official_source_transformation": transformation,
            "blocking_reason": blocking_reason,
        }

    validation = validate_production_source_bundle(bundle, trading_date=trading_date, cadence=cadence)
    bundle["official_source_runtime_validation"] = validation
    if validation["validation_status"] != "PASS":
        bundle["validation_status"] = "BLOCKED"
        bundle["source_bundle_validation"] = "BLOCKED"
        bundle["blocking_reason"] = blocking_reason or "OFFICIAL_SOURCE_DECISION_BUNDLE_NOT_COMPLETE"
    atomic_write_json(Path(output), bundle)

    evidence = {
        "artifact": "RATE_PRODUCTION_OFFICIAL_SOURCE_INGESTION_EVIDENCE",
        "validation_status": "PASS" if bundle["validation_status"] == "PASS" else "BLOCKED",
        "trading_date": trading_date,
        "cadence": cadence,
        "source": "RATE_OFFICIAL_TW_MARKET_DATA_SSOT",
        "rate_source_url_configured": True,
        "source_count": len(urls),
        "fixture_fallback": "FORBIDDEN",
        "historical_acceptance_bundle_fallback": "FORBIDDEN",
        "cer073_live_fallback": "FORBIDDEN",
        "stale_snapshot_fallback": "FORBIDDEN",
        "local_desktop_dependency": "FORBIDDEN",
        "decision_record_coverage": bundle.get("coverage"),
        "record_count": len(bundle.get("records") or []),
        "decision_record_count": len(bundle.get("decision_records") or []),
        "official_source_transformation": bundle.get("official_source_transformation"),
        "source_bundle_path": str(output).replace("\\", "/"),
        "validation": validation,
        "blocking_reason": bundle.get("blocking_reason"),
    }
    atomic_write_json(Path(evidence_output), evidence)
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(description="Build current-cadence RATE production source bundle from official configured RATE_SOURCE_URL only.")
    parser.add_argument("--trading-date", required=True)
    parser.add_argument("--cadence", required=True, choices=["07:30", "09:30", "12:00", "19:30"])
    parser.add_argument("--rate-source-url", default=os.getenv("RATE_SOURCE_URL", ""))
    parser.add_argument("--output", required=True)
    parser.add_argument("--evidence-output", required=True)
    args = parser.parse_args()
    evidence = build_bundle(rate_source_url=args.rate_source_url, trading_date=args.trading_date, cadence=args.cadence, output=args.output, evidence_output=args.evidence_output)
    print(json.dumps(evidence, ensure_ascii=False, sort_keys=True))
    return 0 if evidence["validation_status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
