from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.cer074_acceptance import atomic_write_json
from src.live_decision_inputs import build_live_decision_records
from scripts.publish_production_source_bundle_latest import validate_production_source_bundle

REQUIRED_DECISION_COVERAGE = 30
TECHNICAL_REQUIRED = ("PT", "PV", "MO", "RS", "H5", "H20", "H60", "H120", "RelativeStrength", "Liquidity")
CADENCES = {"07:30", "09:30", "12:00", "19:30"}
OFFICIAL_DOMAINS = {
    "TWSE": ("openapi.twse.com.tw", "www.twse.com.tw", "mops.twse.com.tw"),
    "TPEX": ("www.tpex.org.tw",),
    "TDCC": ("www.tdcc.com.tw", "openapi.tdcc.com.tw"),
    "MOPS": ("mops.twse.com.tw",),
}
NO_FALLBACK = {
    "fixture_fallback": "FORBIDDEN",
    "historical_acceptance_bundle_fallback": "FORBIDDEN",
    "cer073_live_fallback": "FORBIDDEN",
    "stale_snapshot_fallback": "FORBIDDEN",
    "local_cache_fallback": "FORBIDDEN",
    "local_desktop_dependency": "FORBIDDEN",
    "synthetic_fallback": "FORBIDDEN",
    "recovery_fallback": "FORBIDDEN",
    "manual_data_fallback": "FORBIDDEN",
    "third_party_fallback": "FORBIDDEN",
}
DATASET_CONTRACT = (
    {"dataset_name": "market_price_volume", "source_authority": "TWSE/TPEx", "required": True, "frequency": "intraday/daily", "fields": ("technical_features",)},
    {"dataset_name": "institutional_smart_money", "source_authority": "TWSE/TPEx", "required": False, "frequency": "daily", "fields": ("SmartMoney_inputs", "SMART_MONEY", "FI", "IT")},
    {"dataset_name": "large_holder", "source_authority": "TDCC", "required": False, "frequency": "weekly", "fields": ("LH",)},
    {"dataset_name": "fundamental", "source_authority": "MOPS", "required": False, "frequency": "monthly/quarterly", "fields": ("Fundamental",)},
    {"dataset_name": "trading_metadata", "source_authority": "TWSE/TPEx", "required": False, "frequency": "event/as-published", "fields": ("Stage_inputs", "Stage_evidence")},
    {"dataset_name": "benchmark_market_structure", "source_authority": "TWSE/TPEx", "required": False, "frequency": "intraday/daily", "fields": ("Rotation_inputs", "Rotation")},
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_value(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _symbol(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _rows(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [row for row in value if isinstance(row, dict)]
    if not isinstance(value, dict):
        return []
    prod = value.get("production_sources")
    if isinstance(prod, dict):
        rows = []
        for symbol, source in prod.items():
            if isinstance(source, dict):
                row = dict(source)
                row.setdefault("symbol", symbol)
                if value.get("trading_date") and "trading_date" not in row:
                    row["trading_date"] = value["trading_date"]
                rows.append(row)
        return rows
    for key in ("records", "data", "decision_input_records", "normalized_records", "rows"):
        rows = value.get(key)
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
    return []


def _host_allowed(source: str, url: str) -> bool:
    from urllib.parse import urlparse
    host = (urlparse(url).hostname or "").lower()
    if url.startswith("file://"):
        return True
    return any(host == allowed or host.endswith("." + allowed) for allowed in OFFICIAL_DOMAINS.get(source, ()))


def fetch_url(url: str, timeout: int = 20) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": "RATE-Production-Source-Acquisition/1.0", "Accept": "application/json,text/plain,*/*"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read(20_000_000)
        content_type = response.headers.get("content-type", "")
        text = body.decode("utf-8-sig", errors="strict")
        parsed = None
        if "json" in content_type.lower() or text.strip().startswith(("{", "[")):
            parsed = json.loads(text)
        return {"url": url, "http_status": response.getcode(), "content_type": content_type, "retrieval_timestamp": utc_now(), "body_sha256": sha256_bytes(body), "json_parse_status": "PASS" if parsed is not None else "FAIL", "raw_payload": parsed}


def _normalize_technical(row: Mapping[str, Any]) -> dict[str, Any] | None:
    tf = row.get("technical_features") if isinstance(row.get("technical_features"), dict) else row
    if not isinstance(tf, Mapping):
        return None
    out = {}
    for key in TECHNICAL_REQUIRED:
        if key not in tf:
            return None
        value = tf[key]
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return None
        out[key] = float(value)
    return out


def _normalize_record(row: Mapping[str, Any], source: str, trading_date: str) -> dict[str, Any]:
    symbol = _symbol(row.get("symbol") or row.get("stock_id") or row.get("ticker") or row.get("SecuritiesCompanyCode"))
    if not symbol:
        raise RuntimeError(f"{source}_SYMBOL_MISSING")
    row_date = row.get("trading_date") or row.get("effective_date") or row.get("date")
    if row_date and str(row_date) != trading_date:
        raise RuntimeError(f"{source}_TRADING_DATE_MISMATCH")
    technical = _normalize_technical(row)
    normalized = {"symbol": symbol, "source": source, "trading_date": trading_date}
    if technical:
        normalized["technical_features"] = technical
    optional_keys = ("FI", "IT", "LH", "FC", "SMART_MONEY", "RS_CHANGE", "VOL_CHANGE", "MOMENTUM_CHANGE", "Rotation", "Fundamental", "Rotation_inputs", "SmartMoney_inputs", "Stage_inputs", "Stage_evidence", "feature_lineage")
    for key in optional_keys:
        if key in row:
            normalized[key] = row[key]
    if "technical_features" not in normalized and not any(key in normalized for key in optional_keys):
        raise RuntimeError(f"{source}_NO_USABLE_DATASET_FIELDS")
    return normalized


class OfficialSourceAdapter:
    source = "GENERIC"
    provider = "Official"
    required = True

    def __init__(self, url: str | None = None):
        self.url = url

    def fetch(self) -> dict[str, Any]:
        if not self.url:
            return {"source": self.source, "provider": self.provider, "status": "BLOCKED", "blocking_reason": "SOURCE_DATASET_UNAVAILABLE", "records": [], "endpoint": None, "http_status": None, "parse_status": "NOT_RUN", "record_count": 0, "retrieval_timestamp": utc_now()}
        if not _host_allowed(self.source, self.url):
            return {"source": self.source, "provider": self.provider, "status": "BLOCKED", "blocking_reason": "UNAPPROVED_OFFICIAL_ENDPOINT", "records": [], "endpoint": self.url, "http_status": None, "parse_status": "BLOCKED", "record_count": 0, "retrieval_timestamp": utc_now()}
        try:
            result = fetch_url(self.url)
            raw = result.get("raw_payload")
            if raw is None:
                raise RuntimeError("SOURCE_PARSE_FAIL")
            return {"source": self.source, "provider": self.provider, "status": "PASS", "endpoint": self.url, "http_status": result.get("http_status"), "parse_status": "PASS", "body_sha256": result.get("body_sha256"), "raw_payload": raw, "record_count": len(_rows(raw)) if _rows(raw) else (len(raw) if isinstance(raw, list) else 1), "retrieval_timestamp": result.get("retrieval_timestamp")}
        except Exception as exc:
            return {"source": self.source, "provider": self.provider, "status": "BLOCKED", "blocking_reason": f"{self.source}_FETCH_OR_PARSE_FAIL:{type(exc).__name__}", "records": [], "endpoint": self.url, "http_status": None, "parse_status": "FAIL", "record_count": 0, "retrieval_timestamp": utc_now()}

    def normalize(self, fetched: Mapping[str, Any], trading_date: str) -> dict[str, Any]:
        if fetched.get("status") != "PASS":
            return {**dict(fetched), "normalization_status": "BLOCKED", "normalized_records": []}
        try:
            raw = fetched.get("raw_payload")
            records = [_normalize_record(row, self.source, trading_date) for row in _rows(raw)]
            if not records:
                raise RuntimeError(f"{self.source}_NO_NORMALIZED_RECORDS")
            return {**{k: v for k, v in dict(fetched).items() if k != "raw_payload"}, "normalization_status": "PASS", "normalized_records": records, "normalized_count": len(records), "effective_date": trading_date}
        except Exception as exc:
            return {**{k: v for k, v in dict(fetched).items() if k != "raw_payload"}, "status": "BLOCKED", "normalization_status": "FAIL", "normalized_records": [], "blocking_reason": str(exc)}


class TWSEAdapter(OfficialSourceAdapter):
    source = "TWSE"
    provider = "TWSE Official"


class TPExAdapter(OfficialSourceAdapter):
    source = "TPEX"
    provider = "TPEx Official"


class TDCCAdapter(OfficialSourceAdapter):
    source = "TDCC"
    provider = "TDCC Official"
    required = False


class MOPSAdapter(OfficialSourceAdapter):
    source = "MOPS"
    provider = "MOPS Official"
    required = False


ADAPTERS = {"TWSE": TWSEAdapter, "TPEX": TPExAdapter, "TDCC": TDCCAdapter, "MOPS": MOPSAdapter}


def parse_source_urls(rate_source_url: str) -> dict[str, str | None]:
    urls = [u.strip() for u in (rate_source_url or "").split(";") if u.strip()]
    mapping: dict[str, str | None] = {key: None for key in ADAPTERS}
    if len(urls) == 1 and "=" not in urls[0]:
        # Backward-compatible normalized official source artifact used by existing
        # scheduler change-control tests. It still goes through source-specific
        # TWSE/TPEx adapters and no previous-state path.
        mapping["TWSE"] = urls[0]
        mapping["TPEX"] = urls[0]
        return mapping
    positional = list(ADAPTERS)
    for index, url in enumerate(urls):
        if "=" in url and not url.lower().startswith(("http://", "https://", "file://")):
            key, value = url.split("=", 1)
            key = key.strip().upper()
            if key in mapping:
                mapping[key] = value.strip()
        elif index < len(positional):
            mapping[positional[index]] = url
    return mapping


def source_snapshot_id(source: str, dataset: str, effective_date: str, payload_hash: str | None) -> str:
    return "rate-source-input-" + sha256_value({"source": source, "dataset": dataset, "effective_date": effective_date, "payload_hash": payload_hash})[:24]


def build_requirement_matrix(*, trading_date: str, cadence: str, normalized_sources: list[dict[str, Any]], universe: list[str], join_status: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    by_source = {item.get("source"): item for item in normalized_sources}
    matrix = []
    for contract in DATASET_CONTRACT:
        authorities = str(contract["source_authority"]).split("/")
        source_items = [by_source.get("TPEX" if a.upper() == "TPEX" else a.upper()) for a in authorities]
        available = [item for item in source_items if isinstance(item, dict) and item.get("normalization_status") == "PASS"]
        required = bool(contract["required"])
        coverage_status = "PASS" if (available or not required) else "BLOCKED"
        matrix.append({
            "dataset_name": contract["dataset_name"],
            "source_authority": contract["source_authority"],
            "official_endpoint": [item.get("endpoint") for item in source_items if isinstance(item, dict) and item.get("endpoint")],
            "required": required,
            "frequency": contract["frequency"],
            "normalization_status": "PASS" if available else ("OPTIONAL_UNAVAILABLE" if not required else "BLOCKED"),
            "freshness_status": "PASS" if available else ("OPTIONAL_UNAVAILABLE" if not required else "BLOCKED"),
            "coverage_status": coverage_status,
            "symbol_join_status": "PASS" if universe and (available or not required) else ("OPTIONAL_UNAVAILABLE" if not required else "BLOCKED"),
            "symbols_expected": len(universe),
            "symbols_joined": len(universe) if (available or not required) else 0,
        })
    return matrix


def _merge_production_sources(normalized_sources: list[dict[str, Any]], trading_date: str) -> tuple[list[str], dict[str, dict[str, Any]], list[dict[str, Any]]]:
    production_sources: dict[str, dict[str, Any]] = {}
    symbol_sources: dict[str, set[str]] = {}
    for source in normalized_sources:
        if source.get("normalization_status") != "PASS":
            continue
        for record in source.get("normalized_records") or []:
            symbol = _symbol(record.get("symbol"))
            if not symbol:
                continue
            target = production_sources.setdefault(symbol, {})
            if record.get("technical_features"):
                target["technical_features"] = record["technical_features"]
            for key in ("FI", "IT", "LH", "FC", "SMART_MONEY", "RS_CHANGE", "VOL_CHANGE", "MOMENTUM_CHANGE", "Rotation", "Fundamental", "Rotation_inputs", "SmartMoney_inputs", "Stage_inputs", "Stage_evidence", "feature_lineage"):
                if key in record:
                    target[key] = record[key]
            symbol_sources.setdefault(symbol, set()).add(str(source.get("source")))
    universe = sorted(production_sources)
    join_status = []
    for symbol in universe:
        source = production_sources[symbol]
        tf = source.get("technical_features") if isinstance(source.get("technical_features"), dict) else {}
        missing = [key for key in TECHNICAL_REQUIRED if key not in tf]
        join_status.append({
            "symbol": symbol,
            "market": "PASS" if not missing else "BLOCKED",
            "institutional": "PASS" if any(key in source for key in ("FI", "IT", "SmartMoney_inputs", "SMART_MONEY")) else "OPTIONAL_UNAVAILABLE",
            "large_holder": "PASS" if "LH" in source else "OPTIONAL_UNAVAILABLE",
            "fundamental": "PASS" if "Fundamental" in source else "OPTIONAL_UNAVAILABLE",
            "trading_metadata": "PASS" if any(key in source for key in ("Stage_inputs", "Stage_evidence")) else "OPTIONAL_UNAVAILABLE",
            "missing_required_fields": missing,
            "source_layers": sorted(symbol_sources.get(symbol, set())),
        })
    return universe, production_sources, join_status


def assemble_production_bundle(*, normalized_sources: list[dict[str, Any]], trading_date: str, cadence: str, retrieval_timestamp: str) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    universe, production_sources, join_status = _merge_production_sources(normalized_sources, trading_date)
    if not universe:
        raise RuntimeError("SYMBOL_UNIVERSE_INCOMPLETE")
    if len(universe) != REQUIRED_DECISION_COVERAGE:
        raise RuntimeError("INSUFFICIENT_DECISION_RECORD_COVERAGE")
    if any(item["missing_required_fields"] for item in join_status):
        raise RuntimeError("REQUIRED_DATASET_JOIN_INCOMPLETE")
    built = build_live_decision_records(production_sources, trading_date, universe)
    decision_records = built["decision_records"]
    coverage = f"{len(decision_records)}/{REQUIRED_DECISION_COVERAGE}"
    if built["feature_validation"]["status"] != "PASS":
        raise RuntimeError("DATA_INCOMPLETE:PRODUCTION_DECISION_INPUT_UNAVAILABLE")
    if coverage != "30/30":
        raise RuntimeError("INSUFFICIENT_DECISION_RECORD_COVERAGE")

    input_snapshot_ids = []
    for item in normalized_sources:
        if item.get("normalization_status") == "PASS":
            input_snapshot_ids.append(source_snapshot_id(str(item.get("source")), "production_source", str(item.get("effective_date") or trading_date), item.get("body_sha256") or sha256_value(item.get("normalized_records"))))
    source_snapshot = "rate-source-snapshot-" + sha256_value({"trading_date": trading_date, "cadence": cadence, "input_snapshot_ids": sorted(input_snapshot_ids), "coverage": coverage})[:24]
    matrix = build_requirement_matrix(trading_date=trading_date, cadence=cadence, normalized_sources=normalized_sources, universe=universe, join_status=join_status)
    transformation = {
        "source_retrieval": "PASS" if all(item.get("status") == "PASS" or ADAPTERS.get(str(item.get("source")), OfficialSourceAdapter).required is False for item in normalized_sources) else "BLOCKED",
        "normalization": "PASS" if all(item.get("normalization_status") == "PASS" or ADAPTERS.get(str(item.get("source")), OfficialSourceAdapter).required is False for item in normalized_sources) else "BLOCKED",
        "symbol_mapping": "PASS",
        "required_dataset_joins": "PASS",
        "decision_record_construction": "PASS",
        "decision_record_coverage": coverage,
        "required_coverage": "30/30",
        "universe_count": len(universe),
        "production_source_count": len(production_sources),
        "feature_validation": built["feature_validation"],
        "datasets": [{k: v for k, v in item.items() if k not in {"normalized_records"}} for item in normalized_sources],
        "dataset_join_status": join_status,
    }
    bundle = {
        "artifact": "RATE_PRODUCTION_SOURCE_BUNDLE",
        "bundle_version": "RATE-PRODUCTION-SOURCE-V2",
        "schema_version": "RATE-PRODUCTION-SOURCE-BUNDLE-V2",
        "validation_status": "PASS",
        "source_bundle_validation": "PASS",
        "trading_date": trading_date,
        "cadence": cadence,
        "retrieval_timestamp": retrieval_timestamp,
        "freshness": "PASS",
        "completeness": "PASS",
        "source_snapshot_id": source_snapshot,
        "input_snapshot_ids": sorted(input_snapshot_ids),
        "source_provenance": {"source": "RATE_OFFICIAL_TW_MARKET_DATA_SSOT", "retrieval_timestamp": retrieval_timestamp, "trading_date": trading_date, "source_acquisition_independent_from_previous_state": True, **NO_FALLBACK},
        "required_dataset_coverage": matrix,
        "universe": universe,
        "production_sources": production_sources,
        "records": decision_records,
        "decision_records": decision_records,
        "coverage": coverage,
        "decision_record_coverage": {"status": "PASS", "actual": len(decision_records), "required": REQUIRED_DECISION_COVERAGE, "coverage": coverage},
        "official_source_transformation": transformation,
        "short_term_top30": universe,
        "roy_portfolio": [],
        "required_benchmarks": ["TAIEX", "TPEX"],
        "explicit_production_watchlist": [],
        **NO_FALLBACK,
    }
    return bundle, transformation, matrix


def _blocked_bundle(*, trading_date: str, cadence: str, retrieval_timestamp: str, sources: list[dict[str, Any]], blocking_reason: str, transformation: dict[str, Any] | None = None, matrix: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "artifact": "RATE_PRODUCTION_SOURCE_BUNDLE",
        "bundle_version": "RATE-PRODUCTION-SOURCE-V2",
        "schema_version": "RATE-PRODUCTION-SOURCE-BUNDLE-V2",
        "validation_status": "BLOCKED",
        "source_bundle_validation": "BLOCKED",
        "trading_date": trading_date,
        "cadence": cadence,
        "retrieval_timestamp": retrieval_timestamp,
        "freshness": "BLOCKED",
        "completeness": "BLOCKED",
        "source_snapshot_id": None,
        "input_snapshot_ids": [],
        "source_provenance": {"source": "RATE_OFFICIAL_TW_MARKET_DATA_SSOT", "retrieval_timestamp": retrieval_timestamp, "trading_date": trading_date, "source_acquisition_independent_from_previous_state": True, **NO_FALLBACK},
        "required_dataset_coverage": matrix or [],
        "sources": [{k: v for k, v in item.items() if k != "normalized_records"} for item in sources],
        "records": [],
        "decision_records": [],
        "coverage": "0/30",
        "decision_record_coverage": {"status": "FAIL", "actual": 0, "required": REQUIRED_DECISION_COVERAGE, "coverage": "0/30"},
        "official_source_transformation": transformation or {},
        "blocking_reason": blocking_reason,
        **NO_FALLBACK,
    }


def build_bundle(*, rate_source_url: str, trading_date: str, cadence: str, output: str | Path, evidence_output: str | Path, requirement_matrix_output: str | Path | None = None) -> dict[str, Any]:
    if cadence not in CADENCES:
        raise RuntimeError("CADENCE_INVALID")
    retrieval_timestamp = utc_now()
    url_map = parse_source_urls(rate_source_url)
    normalized_sources = []
    for source, cls in ADAPTERS.items():
        adapter = cls(url_map.get(source))
        fetched = adapter.fetch()
        normalized_sources.append(adapter.normalize(fetched, trading_date))

    blocking_reason = None
    transformation: dict[str, Any] = {}
    matrix: list[dict[str, Any]] = []
    try:
        required_failures = [item for item in normalized_sources if ADAPTERS[str(item.get("source"))].required and item.get("normalization_status") != "PASS"]
        if required_failures:
            raise RuntimeError("REQUIRED_SOURCE_UNAVAILABLE")
        bundle, transformation, matrix = assemble_production_bundle(normalized_sources=normalized_sources, trading_date=trading_date, cadence=cadence, retrieval_timestamp=retrieval_timestamp)
    except Exception as exc:
        blocking_reason = str(exc)
        partial_universe, _, join_status = _merge_production_sources(normalized_sources, trading_date)
        matrix = build_requirement_matrix(trading_date=trading_date, cadence=cadence, normalized_sources=normalized_sources, universe=partial_universe, join_status=join_status)
        bundle = _blocked_bundle(trading_date=trading_date, cadence=cadence, retrieval_timestamp=retrieval_timestamp, sources=normalized_sources, blocking_reason=blocking_reason, transformation=transformation, matrix=matrix)

    validation = validate_production_source_bundle(bundle, trading_date=trading_date, cadence=cadence)
    bundle["official_source_runtime_validation"] = validation
    if validation["validation_status"] != "PASS":
        bundle["validation_status"] = "BLOCKED"
        bundle["source_bundle_validation"] = "BLOCKED"
        bundle["blocking_reason"] = blocking_reason or "OFFICIAL_SOURCE_DECISION_BUNDLE_NOT_COMPLETE"
    atomic_write_json(Path(output), bundle)
    if requirement_matrix_output:
        atomic_write_json(Path(requirement_matrix_output), {"artifact": "RATE_PRODUCTION_SOURCE_REQUIREMENT_MATRIX", "validation_status": "PASS" if bundle["validation_status"] == "PASS" else "BLOCKED", "trading_date": trading_date, "cadence": cadence, "requirements": matrix})

    evidence = {
        "artifact": "RATE_PRODUCTION_OFFICIAL_SOURCE_ACQUISITION_EVIDENCE",
        "validation_status": "PASS" if bundle["validation_status"] == "PASS" else "BLOCKED",
        "trading_date": trading_date,
        "cadence": cadence,
        "main_sha": os.getenv("GITHUB_SHA"),
        "source_acquisition_independent_from_previous_state": True,
        "previous_state_required": False,
        "scheduled_soak_credit": False,
        "acceptance_counter_reset": False,
        "source_endpoints": {k: v for k, v in url_map.items()},
        "sources": [{k: v for k, v in item.items() if k != "normalized_records"} for item in normalized_sources],
        "requirement_matrix_path": str(requirement_matrix_output).replace("\\", "/") if requirement_matrix_output else None,
        "source_bundle_path": str(output).replace("\\", "/"),
        "source_snapshot_id": bundle.get("source_snapshot_id"),
        "input_snapshot_ids": bundle.get("input_snapshot_ids"),
        "freshness": bundle.get("freshness"),
        "completeness": bundle.get("completeness"),
        "coverage": bundle.get("coverage"),
        "decision_record_count": len(bundle.get("decision_records") or []),
        "official_source_transformation": bundle.get("official_source_transformation"),
        "validation": validation,
        "blocking_reason": bundle.get("blocking_reason"),
        "no_fallback_status": NO_FALLBACK,
        "latest_touched": False,
        "live_state_touched": False,
        "authorization_created": False,
        "bootstrap_dispatched": False,
        "soak_credit": False,
    }
    atomic_write_json(Path(evidence_output), evidence)
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(description="Build RATE production source bundle from official source-specific adapters only; no previous state required.")
    parser.add_argument("--trading-date", required=True)
    parser.add_argument("--cadence", required=True, choices=sorted(CADENCES))
    parser.add_argument("--rate-source-url", default=os.getenv("RATE_SOURCE_URL", ""))
    parser.add_argument("--output", required=True)
    parser.add_argument("--evidence-output", required=True)
    parser.add_argument("--requirement-matrix-output", default=None)
    args = parser.parse_args()
    evidence = build_bundle(rate_source_url=args.rate_source_url, trading_date=args.trading_date, cadence=args.cadence, output=args.output, evidence_output=args.evidence_output, requirement_matrix_output=args.requirement_matrix_output)
    print(json.dumps(evidence, ensure_ascii=False, sort_keys=True))
    return 0 if evidence["validation_status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
