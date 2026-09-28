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
from src.cer074_acceptance import atomic_write_json, sha256, strip_runtime
from src.live_decision_inputs import build_live_decision_records
from src.cer080_multi_day_continuity import EXCHANGE_HOLIDAYS, TRADING_CALENDAR_SOURCE, is_trading_day
from scripts.publish_production_source_bundle_latest import validate_production_source_bundle

REQUIRED_DECISION_COVERAGE = 30
REQUIRED_DATASETS = ("market_daily", "market_intraday", "institutional", "large_holder", "fundamental", "benchmark", "trading_metadata")
HOLIDAY_REQUIRED_DATASETS = ("trading_metadata",)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")




def production_input_snapshot_id(bundle: dict[str, Any]) -> str:
    payload = strip_runtime({k: v for k, v in bundle.items() if k != "input_snapshot_id"})
    return "rate-prod-source-snapshot-" + sha256(payload)[:24]


def trading_calendar_gate(trading_date: str) -> dict[str, Any]:
    trading = is_trading_day(trading_date)
    return {
        "status": "PASS",
        "trading_calendar_source": TRADING_CALENDAR_SOURCE,
        "trading_date": trading_date,
        "is_trading_day": trading,
        "market_status": "TRADING_DAY" if trading else "HOLIDAY_OR_NON_TRADING_DAY",
        "exchange_holidays": sorted(EXCHANGE_HOLIDAYS),
    }


def dataset_rows(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        if isinstance(value.get("rows"), list):
            return [row for row in value["rows"] if isinstance(row, dict)]
        if isinstance(value.get("records"), list):
            return [row for row in value["records"] if isinstance(row, dict)]
        if isinstance(value.get("data"), list):
            return [row for row in value["data"] if isinstance(row, dict)]
    if isinstance(value, list):
        return [row for row in value if isinstance(row, dict)]
    return []


def collect_required_datasets(objects: list[dict[str, Any]], trading_date: str) -> tuple[dict[str, Any], dict[str, str]]:
    datasets: dict[str, Any] = {}
    status: dict[str, str] = {}
    for obj in objects:
        raw_datasets = obj.get("datasets")
        if isinstance(raw_datasets, dict):
            for domain, payload in raw_datasets.items():
                datasets[str(domain)] = payload
        elif isinstance(raw_datasets, list):
            for item in raw_datasets:
                if isinstance(item, dict) and item.get("domain"):
                    datasets[str(item["domain"])] = item
        for domain in REQUIRED_DATASETS:
            if domain in obj:
                datasets[domain] = obj[domain]
    for domain in REQUIRED_DATASETS:
        payload = datasets.get(domain)
        if payload is None:
            status[domain] = "MISSING"
            continue
        if isinstance(payload, dict) and payload.get("validation_status") not in (None, "PASS"):
            status[domain] = "FAIL"
            continue
        if domain == "trading_metadata":
            source_date = payload.get("trading_date") if isinstance(payload, dict) else None
            if source_date not in (None, trading_date):
                status[domain] = "FAIL"
            else:
                status[domain] = "PASS"
            continue
        rows = dataset_rows(payload)
        status[domain] = "PASS" if rows or (isinstance(payload, dict) and int(payload.get("record_count", 0) or 0) > 0) else "FAIL"
    return datasets, status


def rows_by_symbol(payload: Any, *, symbol_keys=("symbol", "stock_id", "ticker")) -> dict[str, dict[str, Any]]:
    out = {}
    for row in dataset_rows(payload):
        symbol = None
        for key in symbol_keys:
            if row.get(key) is not None:
                symbol = str(row[key]).strip()
                break
        if symbol:
            out[symbol] = row
    return out


def apply_required_dataset_joins(production_sources: dict[str, dict[str, Any]], universe: list[str], datasets: dict[str, Any], dataset_status: dict[str, str]) -> dict[str, Any]:
    missing_domains = [domain for domain in REQUIRED_DATASETS if dataset_status.get(domain) != "PASS"]
    if missing_domains:
        raise RuntimeError("REQUIRED_DATASET_NOT_PASS:" + ",".join(sorted(missing_domains)))
    large_holder_by_symbol = rows_by_symbol(datasets["large_holder"])
    fundamental_by_symbol = rows_by_symbol(datasets["fundamental"])
    metadata = datasets["trading_metadata"] if isinstance(datasets["trading_metadata"], dict) else {}
    missing_large = [symbol for symbol in universe if symbol not in large_holder_by_symbol]
    missing_fundamental = [symbol for symbol in universe if symbol not in fundamental_by_symbol]
    if missing_large:
        raise RuntimeError("REQUIRED_DATASET_JOIN_MISSING:large_holder")
    if missing_fundamental:
        raise RuntimeError("REQUIRED_DATASET_JOIN_MISSING:fundamental")
    for symbol in universe:
        source = production_sources[symbol]
        large_holder = large_holder_by_symbol[symbol]
        fundamental = fundamental_by_symbol[symbol]
        source["large_holder_structure"] = large_holder
        if "LH" not in source and large_holder.get("LH") is not None:
            source["LH"] = large_holder["LH"]
        if "Fundamental" not in source:
            source["Fundamental"] = fundamental.get("Fundamental", fundamental.get("fundamental_score"))
        source["fundamental_dataset"] = fundamental
        source["trading_metadata"] = metadata
    return {
        "required_datasets": {domain: dataset_status.get(domain, "MISSING") for domain in REQUIRED_DATASETS},
        "large_holder_coverage": f"{len(large_holder_by_symbol)}/{len(universe)}",
        "fundamental_coverage": f"{len(fundamental_by_symbol)}/{len(universe)}",
        "trading_metadata_status": dataset_status.get("trading_metadata"),
    }


def build_holiday_bundle(*, trading_date: str, cadence: str, retrieval_timestamp: str, calendar_gate: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    bundle = {
        "artifact": "RATE_PRODUCTION_SOURCE_BUNDLE",
        "bundle_version": "RATE-PRODUCTION-SOURCE-V1",
        "schema_version": "RATE-PRODUCTION-SOURCE-BUNDLE-V1",
        "snapshot_type": "HOLIDAY",
        "holiday_snapshot": True,
        "validation_status": "PASS",
        "source_bundle_validation": "PASS",
        "trading_date": trading_date,
        "cadence": cadence,
        "retrieval_timestamp": retrieval_timestamp,
        "trading_calendar_gate": calendar_gate,
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
        "records": [],
        "decision_records": [],
        "coverage": "HOLIDAY_NO_TRADING",
        "decision_record_coverage": {"status": "PASS", "actual": 0, "required": 0, "coverage": "HOLIDAY_NO_TRADING"},
        "required_dataset_gate": {"status": "PASS", "required_datasets": {"trading_metadata": "PASS"}},
        "official_source_transformation": {
            "source_retrieval": "SKIPPED_MARKET_CLOSED",
            "normalization": "SKIPPED_MARKET_CLOSED",
            "symbol_mapping": "SKIPPED_MARKET_CLOSED",
            "required_dataset_joins": "SKIPPED_MARKET_CLOSED",
            "decision_record_construction": "SKIPPED_MARKET_CLOSED",
            "decision_record_coverage": "HOLIDAY_NO_TRADING",
        },
    }
    bundle["input_snapshot_id"] = production_input_snapshot_id(bundle)
    return bundle, bundle["official_source_transformation"]

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
    official_objects: list[dict[str, Any]] = []

    for payload in payloads:
        if not isinstance(payload, dict):
            raise RuntimeError("OFFICIAL_SOURCE_PAYLOAD_NOT_OBJECT")
        raw = payload.get("raw_payload")
        if not isinstance(raw, (dict, list)):
            raise RuntimeError("OFFICIAL_SOURCE_JSON_PAYLOAD_MISSING")
        objects = raw if isinstance(raw, list) else [raw]
        official_objects.extend([obj for obj in objects if isinstance(obj, dict)])
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

    datasets, dataset_status = collect_required_datasets(official_objects, trading_date)
    dataset_join_evidence = apply_required_dataset_joins(production_sources, universe, datasets, dataset_status)

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
        **dataset_join_evidence,
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
        "trading_calendar_gate": trading_calendar_gate(trading_date),
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
        "required_dataset_gate": {"status": "PASS", **dataset_join_evidence},
        "official_source_transformation": transformation,
        "short_term_top30": universe,
        "roy_portfolio": [],
        "required_benchmarks": ["TAIEX", "TPEX"],
        "explicit_production_watchlist": [],
    }
    bundle["input_snapshot_id"] = production_input_snapshot_id(bundle)
    return bundle, transformation


def _redact_payloads(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{k: v for k, v in item.items() if k != "raw_payload"} for item in sources]


def build_bundle(*, rate_source_url: str, trading_date: str, cadence: str, output: str | Path, evidence_output: str | Path) -> dict[str, Any]:
    retrieval_timestamp = utc_now()
    calendar_gate = trading_calendar_gate(trading_date)
    if calendar_gate["is_trading_day"] is False:
        bundle, _ = build_holiday_bundle(trading_date=trading_date, cadence=cadence, retrieval_timestamp=retrieval_timestamp, calendar_gate=calendar_gate)
        validation = validate_production_source_bundle(bundle, trading_date=trading_date, cadence=cadence)
        bundle["official_source_runtime_validation"] = validation
        if validation["validation_status"] != "PASS":
            bundle["validation_status"] = "BLOCKED"
            bundle["source_bundle_validation"] = "BLOCKED"
            bundle["blocking_reason"] = "HOLIDAY_SOURCE_BUNDLE_VALIDATION_NOT_PASS"
        atomic_write_json(Path(output), bundle)
        evidence = {
            "artifact": "RATE_PRODUCTION_OFFICIAL_SOURCE_INGESTION_EVIDENCE",
            "validation_status": "PASS" if bundle["validation_status"] == "PASS" else "BLOCKED",
            "trading_date": trading_date,
            "cadence": cadence,
            "source": "RATE_OFFICIAL_TW_MARKET_DATA_SSOT",
            "snapshot_type": "HOLIDAY",
            "input_snapshot_id": bundle.get("input_snapshot_id"),
            "trading_calendar_gate": calendar_gate,
            "rate_source_url_configured": bool(rate_source_url and rate_source_url.strip()),
            "fixture_fallback": "FORBIDDEN",
            "historical_acceptance_bundle_fallback": "FORBIDDEN",
            "cer073_live_fallback": "FORBIDDEN",
            "stale_snapshot_fallback": "FORBIDDEN",
            "local_desktop_dependency": "FORBIDDEN",
            "decision_record_coverage": bundle.get("coverage"),
            "record_count": 0,
            "decision_record_count": 0,
            "official_source_transformation": bundle.get("official_source_transformation"),
            "source_bundle_path": str(output).replace("\\", "/"),
            "validation": validation,
            "blocking_reason": bundle.get("blocking_reason"),
        }
        atomic_write_json(Path(evidence_output), evidence)
        return evidence
    if not rate_source_url or not rate_source_url.strip():
        raise RuntimeError("RATE_SOURCE_URL_MISSING")
    urls = [u.strip() for u in rate_source_url.split(";") if u.strip()]
    if not urls:
        raise RuntimeError("RATE_SOURCE_URL_EMPTY")

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
            "input_snapshot_id": None,
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
        "input_snapshot_id": bundle.get("input_snapshot_id"),
        "required_dataset_gate": bundle.get("required_dataset_gate"),
        "trading_calendar_gate": bundle.get("trading_calendar_gate"),
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



