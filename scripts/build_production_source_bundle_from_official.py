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
from scripts.publish_production_source_bundle_latest import CADENCE_FRESHNESS_MINUTES, validate_production_source_bundle

REQUIRED_DECISION_COVERAGE = 30
TECHNICAL_REQUIRED = ("PT", "PV", "MO", "RS", "H5", "H20", "H60", "H120", "RelativeStrength", "Liquidity")
CADENCES = {"07:30", "09:30", "12:00", "19:30"}
OFFICIAL_DOMAINS = {
    "TWSE": ("openapi.twse.com.tw", "www.twse.com.tw", "mops.twse.com.tw"),
    "TPEX": ("www.tpex.org.tw",),
    "TDCC": ("www.tdcc.com.tw", "openapi.tdcc.com.tw"),
    "MOPS": ("mops.twse.com.tw",),
}
CADENCE_APPLICABILITY_PATH = Path("config/RATE_PRODUCTION_SOURCE_CADENCE_APPLICABILITY.json")
EXTERNAL_DEPENDENCIES_PATH = Path("config/RATE_EXTERNAL_PRODUCTION_DEPENDENCIES.json")
EXTERNAL_INTRADAY_DEPENDENCY = "EXTERNAL_AUTHORIZED_INTRADAY_FEED_DEPENDENCY"

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
    {"dataset_name": "market_intraday", "domain": "market_intraday", "source_authority": "Authorized TWSE Intraday Feed", "required": True, "contract_source": "RATE_PRODUCTION_SOURCE_CADENCE_APPLICABILITY.json; Control Center KEEP_REQUIRED_DO_NOT_DEGRADE", "frequency": "intraday", "freshness_contract": "CADENCE_FRESHNESS_MINUTES", "fields": ("intraday_price", "intraday_volume", "intraday_turnover")},
    {"dataset_name": "market_price_volume", "domain": "market_daily", "source_authority": "TWSE/TPEx", "required": True, "contract_source": "src/live_decision_inputs.py:TECHNICAL_REQUIRED; tests/test_production_scheduler_change_control.py", "frequency": "intraday/daily", "freshness_contract": "CADENCE_FRESHNESS_MINUTES", "fields": ("technical_features",)},
    {"dataset_name": "volume", "domain": "market_daily", "source_authority": "TWSE/TPEx", "required": True, "contract_source": "src/technical_features.py:technical_record volume/liquidity inputs", "frequency": "intraday/daily", "freshness_contract": "CADENCE_FRESHNESS_MINUTES", "fields": ("technical_features",)},
    {"dataset_name": "institutional_smart_money", "domain": "institutional", "source_authority": "TWSE/TPEx", "required": True, "contract_source": "src/live_decision_inputs.py optional wire-through plus CER081 formal source gates", "frequency": "daily", "freshness_contract": "LATEST_OFFICIAL_AVAILABLE", "fields": ("SmartMoney_inputs", "SMART_MONEY", "FI", "IT")},
    {"dataset_name": "large_holder", "domain": "large_holder", "source_authority": "TDCC", "required": True, "contract_source": "Control Center V2; CER081/source completeness gates", "frequency": "weekly", "freshness_contract": "LATEST_PUBLISHED_PERIOD", "fields": ("LH",)},
    {"dataset_name": "fundamental", "domain": "fundamental", "source_authority": "MOPS", "required": True, "contract_source": "Control Center V2; CER081/source completeness gates", "frequency": "monthly/quarterly", "freshness_contract": "LATEST_PUBLISHED_PERIOD", "fields": ("Fundamental",)},
    {"dataset_name": "trading_metadata", "domain": "trading_metadata", "source_authority": "TWSE/TPEx", "required": True, "contract_source": "Control Center V2; production source bundle required_missing history", "frequency": "event/as-published", "freshness_contract": "CURRENT_TRADING_STATUS", "fields": ("Stage_inputs", "Stage_evidence")},
    {"dataset_name": "benchmark_market_structure", "domain": "benchmark", "source_authority": "TWSE/TPEx", "required": True, "contract_source": "src/technical_features.py RelativeStrength benchmark input", "frequency": "intraday/daily", "freshness_contract": "EXACT_TRADING_DATE_ALIGNED", "fields": ("Rotation_inputs", "Rotation")},
)
FEATURE_INPUT_CONTRACT = (
    {"feature_name": "PT", "existing_calculation_owner": "src/technical_features.py:technical_record", "required_raw_fields": ["close", "MA60"], "required_history_window": "120 sessions", "source_authority": "TWSE/TPEx official historical market data", "calculation_changed": False},
    {"feature_name": "PV", "existing_calculation_owner": "src/technical_features.py:technical_record", "required_raw_fields": ["volume"], "required_history_window": "20 sessions", "source_authority": "TWSE/TPEx official historical market data", "calculation_changed": False},
    {"feature_name": "MO", "existing_calculation_owner": "src/technical_features.py:technical_record", "required_raw_fields": ["close"], "required_history_window": "20 sessions", "source_authority": "TWSE/TPEx official historical market data", "calculation_changed": False},
    {"feature_name": "RS", "existing_calculation_owner": "src/technical_features.py:compute_scores", "required_raw_fields": ["symbol close", "benchmark close"], "required_history_window": "5 sessions", "source_authority": "TWSE/TPEx official historical market and benchmark data", "calculation_changed": False},
    {"feature_name": "H5", "existing_calculation_owner": "src/technical_features.py:technical_record", "required_raw_fields": ["high", "low", "close"], "required_history_window": "5 sessions", "source_authority": "TWSE/TPEx official historical market data", "calculation_changed": False},
    {"feature_name": "H20", "existing_calculation_owner": "src/technical_features.py:technical_record", "required_raw_fields": ["high", "low", "close"], "required_history_window": "20 sessions", "source_authority": "TWSE/TPEx official historical market data", "calculation_changed": False},
    {"feature_name": "H60", "existing_calculation_owner": "src/technical_features.py:technical_record", "required_raw_fields": ["high", "low", "close"], "required_history_window": "60 sessions", "source_authority": "TWSE/TPEx official historical market data", "calculation_changed": False},
    {"feature_name": "H120", "existing_calculation_owner": "src/technical_features.py:technical_record", "required_raw_fields": ["high", "low", "close"], "required_history_window": "120 sessions", "source_authority": "TWSE/TPEx official historical market data", "calculation_changed": False},
    {"feature_name": "RelativeStrength", "existing_calculation_owner": "src/technical_features.py:compute_scores", "required_raw_fields": ["symbol close", "benchmark close"], "required_history_window": "5 sessions", "source_authority": "TWSE/TPEx official historical market and benchmark data", "calculation_changed": False},
    {"feature_name": "Liquidity", "existing_calculation_owner": "src/technical_features.py:technical_record", "required_raw_fields": ["volume"], "required_history_window": "20 sessions", "source_authority": "TWSE/TPEx official historical market data", "calculation_changed": False},
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
        return os.getenv("RATE_SOURCE_TEST_CONTEXT") == "1"
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
    symbol_fields = ("symbol",)
    date_fields = ("trading_date", "effective_date", "date")
    parser_version = "RATE-SOURCE-PARSER-GENERIC-V2"

    def __init__(self, url: str | None = None):
        self.url = url

    def fetch(self) -> dict[str, Any]:
        if not self.url:
            return {"source": self.source, "provider": self.provider, "status": "BLOCKED", "blocking_reason": "SOURCE_DATASET_UNAVAILABLE", "records": [], "endpoint": None, "http_status": None, "parse_status": "NOT_RUN", "record_count": 0, "retrieval_timestamp": utc_now(), "parser_version": self.parser_version}
        if not _host_allowed(self.source, self.url):
            reason = "UNAPPROVED_PRODUCTION_SOURCE_SCHEME" if self.url.startswith("file://") else "UNAPPROVED_OFFICIAL_ENDPOINT"
            return {"source": self.source, "provider": self.provider, "status": "BLOCKED", "blocking_reason": reason, "records": [], "endpoint": self.url, "http_status": None, "parse_status": "BLOCKED", "record_count": 0, "retrieval_timestamp": utc_now(), "parser_version": self.parser_version}
        try:
            result = fetch_url(self.url)
            raw = result.get("raw_payload")
            if raw is None:
                raise RuntimeError("SOURCE_PARSE_FAIL")
            parsed = self.parse_raw(raw)
            return {"source": self.source, "provider": self.provider, "status": "PASS", "endpoint": self.url, "http_status": result.get("http_status"), "content_type": result.get("content_type"), "parse_status": "PASS", "body_sha256": result.get("body_sha256"), "raw_payload": parsed, "record_count": len(parsed), "retrieval_timestamp": result.get("retrieval_timestamp"), "parser_version": self.parser_version}
        except Exception as exc:
            return {"source": self.source, "provider": self.provider, "status": "BLOCKED", "blocking_reason": f"{self.source}_FETCH_OR_PARSE_FAIL:{type(exc).__name__}:{exc}", "records": [], "endpoint": self.url, "http_status": None, "parse_status": "FAIL", "record_count": 0, "retrieval_timestamp": utc_now(), "parser_version": self.parser_version}

    def parse_raw(self, raw: Any) -> list[dict[str, Any]]:
        rows = _rows(raw)
        if not rows:
            raise RuntimeError(f"{self.source}_SCHEMA_ROWS_MISSING")
        return rows

    def extract_symbol(self, row: Mapping[str, Any]) -> str:
        for field in self.symbol_fields:
            symbol = _symbol(row.get(field))
            if symbol:
                return symbol
        raise RuntimeError(f"{self.source}_SYMBOL_MISSING")

    def extract_effective_date(self, row: Mapping[str, Any], trading_date: str) -> str:
        for field in self.date_fields:
            value = row.get(field)
            if value:
                return str(value).replace("/", "-")
        return trading_date

    def normalize_schema(self, row: Mapping[str, Any], trading_date: str) -> dict[str, Any]:
        copied = dict(row)
        copied["symbol"] = self.extract_symbol(row)
        copied["effective_date"] = self.extract_effective_date(row, trading_date)
        return _normalize_record(copied, self.source, trading_date)

    def normalize(self, fetched: Mapping[str, Any], trading_date: str) -> dict[str, Any]:
        if fetched.get("status") != "PASS":
            return {**dict(fetched), "normalization_status": "BLOCKED", "normalized_records": []}
        try:
            records = [self.normalize_schema(row, trading_date) for row in fetched.get("raw_payload") or []]
            if not records:
                raise RuntimeError(f"{self.source}_NO_NORMALIZED_RECORDS")
            return {**{k: v for k, v in dict(fetched).items() if k != "raw_payload"}, "normalization_status": "PASS", "normalized_records": records, "normalized_count": len(records), "effective_date": trading_date}
        except Exception as exc:
            return {**{k: v for k, v in dict(fetched).items() if k != "raw_payload"}, "status": "BLOCKED", "normalization_status": "FAIL", "normalized_records": [], "blocking_reason": str(exc)}


class TWSEAdapter(OfficialSourceAdapter):
    source = "TWSE"
    provider = "TWSE Official"
    symbol_fields = ("Code", "證券代號", "stock_id", "symbol")
    date_fields = ("Date", "日期", "trading_date", "effective_date", "date")
    parser_version = "RATE-TWSE-PARSER-V2"

    def normalize_schema(self, row: Mapping[str, Any], trading_date: str) -> dict[str, Any]:
        mapped = dict(row)
        mapped.setdefault("symbol", self.extract_symbol(row))
        mapped.setdefault("effective_date", self.extract_effective_date(row, trading_date))
        # Actual TWSE market rows provide raw price/volume. They are not accepted
        # as derived RATE features unless a controlled historical feature
        # transformation has supplied technical_features.
        if "TradeVolume" in row and "volume" not in mapped:
            mapped["volume"] = row.get("TradeVolume")
        if "ClosingPrice" in row and "close" not in mapped:
            mapped["close"] = row.get("ClosingPrice")
        return _normalize_record(mapped, self.source, trading_date)


class TPExAdapter(OfficialSourceAdapter):
    source = "TPEX"
    provider = "TPEx Official"
    symbol_fields = ("SecuritiesCompanyCode", "代號", "Code", "stock_id", "symbol")
    date_fields = ("Date", "資料日期", "trading_date", "effective_date", "date")
    parser_version = "RATE-TPEX-PARSER-V2"

    def normalize_schema(self, row: Mapping[str, Any], trading_date: str) -> dict[str, Any]:
        mapped = dict(row)
        mapped.setdefault("symbol", self.extract_symbol(row))
        mapped.setdefault("effective_date", self.extract_effective_date(row, trading_date))
        if "LatestPrice" in row and "close" not in mapped:
            mapped["close"] = row.get("LatestPrice")
        if "TradingVolume" in row and "volume" not in mapped:
            mapped["volume"] = row.get("TradingVolume")
        return _normalize_record(mapped, self.source, trading_date)


class TDCCAdapter(OfficialSourceAdapter):
    source = "TDCC"
    provider = "TDCC Official"
    symbol_fields = ("stock_code", "stock_id", "symbol", "證券代號")
    date_fields = ("published_date", "effective_date", "trading_date", "date", "資料日期")
    parser_version = "RATE-TDCC-PARSER-V2"

    def normalize_schema(self, row: Mapping[str, Any], trading_date: str) -> dict[str, Any]:
        mapped = dict(row)
        mapped.setdefault("symbol", self.extract_symbol(row))
        mapped.setdefault("effective_date", self.extract_effective_date(row, trading_date))
        if "large_holder" in row and "LH" not in mapped:
            mapped["LH"] = row.get("large_holder")
        if "distribution" in row and "LH" not in mapped:
            mapped["LH"] = row.get("distribution")
        return _normalize_record(mapped, self.source, trading_date)


class MOPSAdapter(OfficialSourceAdapter):
    source = "MOPS"
    provider = "MOPS Official"
    symbol_fields = ("company_code", "stock_id", "symbol", "公司代號")
    date_fields = ("publication_date", "reporting_period", "effective_date", "trading_date", "date")
    parser_version = "RATE-MOPS-PARSER-V2"

    def normalize_schema(self, row: Mapping[str, Any], trading_date: str) -> dict[str, Any]:
        mapped = dict(row)
        mapped.setdefault("symbol", self.extract_symbol(row))
        mapped.setdefault("effective_date", self.extract_effective_date(row, trading_date))
        if "fundamental" in row and "Fundamental" not in mapped:
            mapped["Fundamental"] = row.get("fundamental")
        return _normalize_record(mapped, self.source, trading_date)


ADAPTERS = {"TWSE": TWSEAdapter, "TPEX": TPExAdapter, "TDCC": TDCCAdapter, "MOPS": MOPSAdapter}


def parse_source_urls(rate_source_url: str) -> dict[str, str | None]:
    urls = [u.strip() for u in (rate_source_url or "").split(";") if u.strip()]
    mapping: dict[str, str | None] = {key: None for key in ADAPTERS}
    if len(urls) == 1 and "=" not in urls[0]:
        # Backward-compatible normalized official source artifact used by existing
        # scheduler change-control tests. It still goes through source-specific
        # TWSE/TPEx adapters and no previous-state path.
        for key in mapping:
            mapping[key] = urls[0]
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


def source_snapshot_id(source: str, dataset: str, effective_date: str, payload_hash: str | None, *, parser_version: str | None = None, source_authority: str | None = None) -> str:
    return "rate-source-input-" + sha256_value({"source": source, "source_authority": source_authority, "dataset": dataset, "effective_date": effective_date, "payload_hash": payload_hash, "parser_version": parser_version})[:24]




def load_cadence_applicability(path: str | Path | None = None) -> dict[str, Any]:
    target = Path(path) if path else CADENCE_APPLICABILITY_PATH
    return json.loads(target.read_text(encoding="utf-8"))


def load_external_dependencies(path: str | Path | None = None) -> dict[str, Any]:
    target = Path(path) if path else EXTERNAL_DEPENDENCIES_PATH
    return json.loads(target.read_text(encoding="utf-8"))


def cadence_domain_rule(cadence: str, domain: str, applicability: Mapping[str, Any] | None = None) -> dict[str, Any]:
    applicability = applicability or load_cadence_applicability()
    domains = ((applicability.get("domains") or {}).get(cadence) or {})
    rule = domains.get(domain)
    if rule:
        return dict(rule)
    # Non-intraday formal domains remain required for all currently supported
    # production source cadences unless a cadence-specific contract says
    # otherwise. Intraday is intentionally cadence-gated by Control Center.
    if domain == "market_intraday":
        return {"applicability": "NOT_APPLICABLE"}
    return {"applicability": "REQUIRED"}


def required_for_cadence(cadence: str, contract: Mapping[str, Any], applicability: Mapping[str, Any] | None = None) -> bool:
    if not bool(contract.get("required")):
        return False
    rule = cadence_domain_rule(cadence, str(contract.get("domain") or contract.get("dataset_name")), applicability)
    return rule.get("applicability") == "REQUIRED"


def cadence_blocking_reason(cadence: str, applicability: Mapping[str, Any] | None = None) -> str | None:
    rule = cadence_domain_rule(cadence, "market_intraday", applicability)
    if rule.get("applicability") == "REQUIRED" and rule.get("current_operational_status") == "BLOCKED":
        return str(rule.get("blocking_reason") or EXTERNAL_INTRADAY_DEPENDENCY)
    return None


def cadence_applicability_evidence(cadence: str, applicability: Mapping[str, Any] | None = None) -> dict[str, Any]:
    applicability = applicability or load_cadence_applicability()
    domains = ((applicability.get("domains") or {}).get(cadence) or {})
    return {
        "artifact": "RATE_PRODUCTION_SOURCE_CADENCE_APPLICABILITY_EVIDENCE",
        "cadence": cadence,
        "domains": domains,
        "external_dependency": cadence_blocking_reason(cadence, applicability),
        "validation_status": "BLOCKED" if cadence_blocking_reason(cadence, applicability) else "PASS",
    }


def _is_test_context() -> bool:
    return os.getenv("RATE_SOURCE_TEST_CONTEXT") == "1"


def load_universe_contract(path: str | Path | None) -> dict[str, Any] | None:
    if not path:
        return None
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    universe = data.get("approved_universe") or data.get("universe") or data.get("symbols")
    if not isinstance(universe, list):
        raise RuntimeError("PRODUCTION_UNIVERSE_CONTRACT_INVALID")
    symbols = [_symbol(item) for item in universe]
    symbols = [item for item in symbols if item]
    return {
        "artifact": data.get("artifact", "RATE_PRODUCTION_UNIVERSE_CONTRACT"),
        "validation_status": data.get("validation_status", "PASS"),
        "approved_universe": symbols,
        "source_path": str(path).replace("\\", "/"),
        "contract_sha256": sha256_value(data),
    }


def bind_universe(*, available_symbols: list[str], universe_contract: dict[str, Any] | None) -> dict[str, Any]:
    unique_available = sorted(set(available_symbols))
    if universe_contract is None:
        if _is_test_context() and len(unique_available) == REQUIRED_DECISION_COVERAGE:
            expected = unique_available
            return {
                "artifact": "RATE_PRODUCTION_UNIVERSE_BINDING",
                "validation_status": "PASS",
                "binding_mode": "TEST_CONTEXT_DERIVED_EXACT_30",
                "production_authoritative": False,
                "expected_universe": expected,
                "approved_universe_count": len(expected),
                "available_symbol_count": len(unique_available),
                "missing_symbols": [],
                "unapproved_symbols": [],
                "duplicate_symbols": [],
                "universe_binding_hash": sha256_value(expected),
            }
        return {
            "artifact": "RATE_PRODUCTION_UNIVERSE_BINDING",
            "validation_status": "BLOCKED",
            "blocking_reason": "PRODUCTION_UNIVERSE_CONTRACT_MISSING",
            "binding_mode": "NONE",
            "production_authoritative": False,
            "expected_universe": [],
            "approved_universe_count": 0,
            "available_symbol_count": len(unique_available),
            "missing_symbols": [],
            "unapproved_symbols": unique_available,
            "duplicate_symbols": [],
            "universe_binding_hash": None,
        }
    expected = list(universe_contract["approved_universe"])
    duplicate_symbols = sorted({item for item in expected if expected.count(item) > 1})
    missing = sorted(set(expected) - set(unique_available))
    unapproved = sorted(set(unique_available) - set(expected))
    status = "PASS" if len(expected) == REQUIRED_DECISION_COVERAGE and not duplicate_symbols and not missing and not unapproved and universe_contract.get("validation_status") == "PASS" else "BLOCKED"
    reason = None
    if status != "PASS":
        if len(expected) != REQUIRED_DECISION_COVERAGE:
            reason = "PRODUCTION_UNIVERSE_CONTRACT_NOT_EXACT_30"
        elif duplicate_symbols:
            reason = "PRODUCTION_UNIVERSE_DUPLICATE_SYMBOLS"
        elif missing:
            reason = "PRODUCTION_UNIVERSE_SYMBOLS_MISSING_FROM_SOURCE"
        elif unapproved:
            reason = "PRODUCTION_SOURCE_UNAPPROVED_SYMBOLS_PRESENT"
        else:
            reason = "PRODUCTION_UNIVERSE_CONTRACT_NOT_PASS"
    return {
        "artifact": "RATE_PRODUCTION_UNIVERSE_BINDING",
        "validation_status": status,
        "blocking_reason": reason,
        "binding_mode": "AUTHORITATIVE_CONTRACT_EXACT_30",
        "production_authoritative": True,
        "expected_universe": expected,
        "approved_universe_count": len(expected),
        "available_symbol_count": len(unique_available),
        "missing_symbols": missing,
        "unapproved_symbols": unapproved,
        "duplicate_symbols": duplicate_symbols,
        "contract_sha256": universe_contract.get("contract_sha256"),
        "universe_binding_hash": sha256_value({"expected_universe": expected, "contract_sha256": universe_contract.get("contract_sha256")}),
    }


def build_feature_input_contract_artifact() -> dict[str, Any]:
    return {
        "artifact": "RATE_PRODUCTION_FEATURE_INPUT_CONTRACT",
        "validation_status": "PASS",
        "calculation_changes": "NONE",
        "strategy_changes": "NONE",
        "decision_runtime_continuity_changes": "NONE",
        "feature_inputs": list(FEATURE_INPUT_CONTRACT),
    }


def _parse_time(value: Any) -> datetime | None:
    try:
        text = str(value).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return None


def build_freshness_matrix(*, trading_date: str, cadence: str, normalized_sources: list[dict[str, Any]], retrieval_timestamp: str) -> dict[str, Any]:
    now = _parse_time(retrieval_timestamp) or datetime.now(timezone.utc)
    dataset_rows = []
    blocking_reasons: list[str] = []
    source_status = {str(item.get("source")): item for item in normalized_sources}
    for contract in DATASET_CONTRACT:
        name = str(contract["dataset_name"])
        freshness_contract = str(contract.get("freshness_contract"))
        sources = [part.upper().replace("TPEX", "TPEX") for part in str(contract["source_authority"]).split("/")]
        source_items = [source_status.get(src) for src in sources if source_status.get(src)]
        timestamps = [item.get("retrieval_timestamp") for item in source_items if item and item.get("normalization_status") == "PASS"]
        parsed_times = [_parse_time(ts) for ts in timestamps]
        parsed_times = [ts for ts in parsed_times if ts]
        domain_rule = cadence_domain_rule(cadence, str(contract.get("domain") or contract.get("dataset_name")))
        required_this_run = required_for_cadence(cadence, contract)
        max_age_minutes = CADENCE_FRESHNESS_MINUTES.get(cadence) if freshness_contract == "CADENCE_FRESHNESS_MINUTES" else None
        if domain_rule.get("applicability") == "NOT_APPLICABLE":
            status = "NOT_APPLICABLE"
            reason = None
        elif str(freshness_contract).startswith("FRESHNESS_CONTRACT_MISSING"):
            if _is_test_context() and os.getenv("RATE_SOURCE_TEST_FRESHNESS_CONTRACTS") == "1":
                status = "PASS"
                reason = None
            else:
                status = "BLOCKED"
                reason = freshness_contract
        elif not parsed_times:
            status = "BLOCKED"
            reason = f"SOURCE_FRESHNESS_TIMESTAMP_MISSING:{name}"
        else:
            ages = [(now - ts).total_seconds() / 60 for ts in parsed_times]
            future = any(age < -1 for age in ages)
            stale = max_age_minutes is not None and any(age > max_age_minutes for age in ages)
            status = "PASS" if not future and not stale else "BLOCKED"
            reason = "SOURCE_FUTURE_DATED" if future else ("SOURCE_STALE" if stale else None)
        if status not in {"PASS", "NOT_APPLICABLE"} and required_this_run:
            blocking_reasons.append(str(reason))
        dataset_rows.append({
            "dataset_name": name,
            "source_authority": contract["source_authority"],
            "required": contract["required"],
            "required_for_this_run": required_this_run,
            "cadence_applicability": domain_rule.get("applicability"),
            "frequency": contract["frequency"],
            "freshness_contract": freshness_contract,
            "retrieval_timestamps": timestamps,
            "max_age_minutes": max_age_minutes,
            "freshness_status": status,
            "blocking_reason": reason,
        })
    return {
        "artifact": "RATE_PRODUCTION_SOURCE_FRESHNESS_MATRIX",
        "validation_status": "PASS" if not blocking_reasons else "BLOCKED",
        "trading_date": trading_date,
        "cadence": cadence,
        "generated_at": retrieval_timestamp,
        "datasets": dataset_rows,
        "blocking_reasons": sorted(set(blocking_reasons)),
    }

def build_requirement_matrix(*, trading_date: str, cadence: str, normalized_sources: list[dict[str, Any]], universe: list[str], join_status: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    by_source = {item.get("source"): item for item in normalized_sources}
    matrix = []
    for contract in DATASET_CONTRACT:
        authorities = str(contract["source_authority"]).split("/")
        source_items = [by_source.get("TPEX" if a.upper() == "TPEX" else a.upper()) for a in authorities]
        available = [item for item in source_items if isinstance(item, dict) and item.get("normalization_status") == "PASS"]
        rule = cadence_domain_rule(cadence, str(contract.get("domain") or contract.get("dataset_name")))
        required = required_for_cadence(cadence, contract)
        coverage_status = "NOT_APPLICABLE" if rule.get("applicability") == "NOT_APPLICABLE" else ("PASS" if (available or not required) else "BLOCKED")
        matrix.append({
            "dataset_name": contract["dataset_name"],
            "source_authority": contract["source_authority"],
            "official_endpoint": [item.get("endpoint") for item in source_items if isinstance(item, dict) and item.get("endpoint")],
            "required": bool(contract["required"]),
            "required_for_this_run": required,
            "cadence_applicability": rule.get("applicability"),
            "contract_source": contract.get("contract_source"),
            "frequency": contract["frequency"],
            "normalization_status": "NOT_APPLICABLE" if rule.get("applicability") == "NOT_APPLICABLE" else ("PASS" if available else ("OPTIONAL_UNAVAILABLE" if not required else "BLOCKED")),
            "freshness_status": "NOT_APPLICABLE" if rule.get("applicability") == "NOT_APPLICABLE" else ("PASS" if available else ("OPTIONAL_UNAVAILABLE" if not required else "BLOCKED")),
            "coverage_status": coverage_status,
            "symbol_join_status": "NOT_APPLICABLE" if rule.get("applicability") == "NOT_APPLICABLE" else ("PASS" if universe and (available or not required) else ("OPTIONAL_UNAVAILABLE" if not required else "BLOCKED")),
            "symbols_expected": len(universe),
            "symbols_joined": len(universe) if (available or not required) else 0,
        })
    return matrix



def _merge_production_sources(normalized_sources: list[dict[str, Any]], trading_date: str, expected_universe: list[str] | None = None) -> tuple[list[str], dict[str, dict[str, Any]], list[dict[str, Any]]]:
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
    universe = list(expected_universe) if expected_universe is not None else sorted(production_sources)
    if expected_universe is not None:
        production_sources = {symbol: production_sources[symbol] for symbol in expected_universe if symbol in production_sources}
    join_status = []
    for symbol in universe:
        source = production_sources.get(symbol, {})
        tf = source.get("technical_features") if isinstance(source.get("technical_features"), dict) else {}
        missing_technical = [key for key in TECHNICAL_REQUIRED if key not in tf]
        required_dataset_missing = []
        if missing_technical:
            required_dataset_missing.append("market_price_volume")
        if not any(key in source for key in ("FI", "IT", "SmartMoney_inputs", "SMART_MONEY")):
            required_dataset_missing.append("institutional_smart_money")
        if "LH" not in source:
            required_dataset_missing.append("large_holder")
        if "Fundamental" not in source:
            required_dataset_missing.append("fundamental")
        if not any(key in source for key in ("Stage_inputs", "Stage_evidence")):
            required_dataset_missing.append("trading_metadata")
        if not any(key in source for key in ("Rotation_inputs", "Rotation")):
            required_dataset_missing.append("benchmark_market_structure")
        join_status.append({
            "symbol": symbol,
            "market": "PASS" if not missing_technical else "BLOCKED",
            "institutional": "PASS" if "institutional_smart_money" not in required_dataset_missing else "BLOCKED",
            "large_holder": "PASS" if "large_holder" not in required_dataset_missing else "BLOCKED",
            "fundamental": "PASS" if "fundamental" not in required_dataset_missing else "BLOCKED",
            "trading_metadata": "PASS" if "trading_metadata" not in required_dataset_missing else "BLOCKED",
            "benchmark_market_structure": "PASS" if "benchmark_market_structure" not in required_dataset_missing else "BLOCKED",
            "missing_required_fields": missing_technical,
            "missing_required_datasets": required_dataset_missing,
            "source_layers": sorted(symbol_sources.get(symbol, set())),
        })
    return universe, production_sources, join_status


def _qualified_count(join_status: list[dict[str, Any]]) -> int:
    return sum(1 for item in join_status if not item.get("missing_required_fields") and not item.get("missing_required_datasets"))


def assemble_production_bundle(*, normalized_sources: list[dict[str, Any]], trading_date: str, cadence: str, retrieval_timestamp: str, universe_binding: dict[str, Any], freshness_matrix: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    if universe_binding.get("validation_status") != "PASS":
        raise RuntimeError(str(universe_binding.get("blocking_reason") or "PRODUCTION_UNIVERSE_BINDING_BLOCKED"))
    expected_universe = list(universe_binding.get("expected_universe") or [])
    universe, production_sources, join_status = _merge_production_sources(normalized_sources, trading_date, expected_universe)
    if not universe:
        raise RuntimeError("SYMBOL_UNIVERSE_INCOMPLETE")
    if len(universe) != REQUIRED_DECISION_COVERAGE:
        raise RuntimeError("INSUFFICIENT_DECISION_RECORD_COVERAGE")
    if any(item["missing_required_fields"] or item.get("missing_required_datasets") for item in join_status):
        raise RuntimeError("REQUIRED_DATASET_JOIN_INCOMPLETE")
    if freshness_matrix.get("validation_status") != "PASS":
        raise RuntimeError(";".join(freshness_matrix.get("blocking_reasons") or ["SOURCE_FRESHNESS_BLOCKED"]))
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
            input_snapshot_ids.append(source_snapshot_id(str(item.get("source")), "production_source", str(item.get("effective_date") or trading_date), item.get("body_sha256") or sha256_value(item.get("normalized_records")), parser_version=str(item.get("parser_version")), source_authority=str(item.get("provider"))))
    source_snapshot = "rate-source-snapshot-" + sha256_value({"trading_date": trading_date, "cadence": cadence, "input_snapshot_ids": sorted(input_snapshot_ids), "coverage": coverage, "universe_binding_hash": universe_binding.get("universe_binding_hash"), "required_dataset_contract_hash": sha256_value(DATASET_CONTRACT)})[:24]
    matrix = build_requirement_matrix(trading_date=trading_date, cadence=cadence, normalized_sources=normalized_sources, universe=universe, join_status=join_status)
    transformation = {
        "source_retrieval": "PASS" if all(item.get("status") == "PASS" for item in normalized_sources if ADAPTERS[str(item.get("source"))].required) else "BLOCKED",
        "normalization": "PASS" if all(item.get("normalization_status") == "PASS" for item in normalized_sources if ADAPTERS[str(item.get("source"))].required) else "BLOCKED",
        "symbol_mapping": "PASS",
        "authoritative_universe_binding": universe_binding,
        "required_dataset_joins": "PASS",
        "decision_record_construction": "PASS",
        "decision_record_coverage": coverage,
        "required_coverage": "30/30",
        "universe_count": len(universe),
        "production_source_count": len(production_sources),
        "feature_validation": built["feature_validation"],
        "feature_input_contract": build_feature_input_contract_artifact(),
        "freshness_matrix": freshness_matrix,
        "datasets": [{k: v for k, v in item.items() if k not in {"normalized_records"}} for item in normalized_sources],
        "dataset_join_status": join_status,
    }
    provenance = {"source": "RATE_OFFICIAL_TW_MARKET_DATA_SSOT", "retrieval_timestamp": retrieval_timestamp, "trading_date": trading_date, "execution_scope": "PRODUCTION_SOURCE_ACQUISITION", "execution_authority": os.getenv("EXECUTION_AUTHORITY") or ("TEST_CONTEXT" if _is_test_context() else "DEVELOPMENT_LIVE_PROBE"), "production_evidence_authoritative": (os.getenv("EXECUTION_AUTHORITY") == "MAIN_ONLY" and os.getenv("GITHUB_REF") == "refs/heads/main"), "source_acquisition_independent_from_previous_state": True, "cadence_applicability": cadence_applicability_evidence(cadence), **NO_FALLBACK}
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
        "source_provenance": provenance,
        "required_dataset_contract_hash": sha256_value(DATASET_CONTRACT),
        "required_dataset_coverage": matrix,
        "universe_binding": universe_binding,
        "freshness_matrix": freshness_matrix,
        "feature_input_contract": build_feature_input_contract_artifact(),
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


def _blocked_bundle(*, trading_date: str, cadence: str, retrieval_timestamp: str, sources: list[dict[str, Any]], blocking_reason: str, transformation: dict[str, Any] | None = None, matrix: list[dict[str, Any]] | None = None, universe_binding: dict[str, Any] | None = None, freshness_matrix: dict[str, Any] | None = None, qualified_count: int = 0) -> dict[str, Any]:
    coverage = f"{qualified_count}/{REQUIRED_DECISION_COVERAGE}"
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
        "source_provenance": {"source": "RATE_OFFICIAL_TW_MARKET_DATA_SSOT", "retrieval_timestamp": retrieval_timestamp, "trading_date": trading_date, "execution_scope": "PRODUCTION_SOURCE_ACQUISITION", "execution_authority": os.getenv("EXECUTION_AUTHORITY") or ("TEST_CONTEXT" if _is_test_context() else "DEVELOPMENT_LIVE_PROBE"), "production_evidence_authoritative": False, "source_acquisition_independent_from_previous_state": True, "cadence_applicability": cadence_applicability_evidence(cadence), **NO_FALLBACK},
        "required_dataset_contract_hash": sha256_value(DATASET_CONTRACT),
        "required_dataset_coverage": matrix or [],
        "universe_binding": universe_binding or {},
        "freshness_matrix": freshness_matrix or {},
        "feature_input_contract": build_feature_input_contract_artifact(),
        "sources": [{k: v for k, v in item.items() if k != "normalized_records"} for item in sources],
        "records": [],
        "decision_records": [],
        "coverage": coverage,
        "decision_record_coverage": {"status": "FAIL", "actual": qualified_count, "required": REQUIRED_DECISION_COVERAGE, "coverage": coverage},
        "official_source_transformation": transformation or {},
        "blocking_reason": blocking_reason,
        **NO_FALLBACK,
    }


def build_bundle(*, rate_source_url: str, trading_date: str, cadence: str, output: str | Path, evidence_output: str | Path, requirement_matrix_output: str | Path | None = None, universe_contract: str | Path | None = None, universe_binding_output: str | Path | None = None, freshness_matrix_output: str | Path | None = None, feature_input_contract_output: str | Path | None = None) -> dict[str, Any]:
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
    partial_universe, _, join_status = _merge_production_sources(normalized_sources, trading_date)
    contract = load_universe_contract(universe_contract)
    universe_binding = bind_universe(available_symbols=partial_universe, universe_contract=contract)
    freshness_matrix = build_freshness_matrix(trading_date=trading_date, cadence=cadence, normalized_sources=normalized_sources, retrieval_timestamp=retrieval_timestamp)
    try:
        external_block = cadence_blocking_reason(cadence)
        if external_block:
            raise RuntimeError(external_block)
        required_failures = [item for item in normalized_sources if ADAPTERS[str(item.get("source"))].required and item.get("normalization_status") != "PASS"]
        if required_failures:
            raise RuntimeError("REQUIRED_SOURCE_UNAVAILABLE")
        bundle, transformation, matrix = assemble_production_bundle(normalized_sources=normalized_sources, trading_date=trading_date, cadence=cadence, retrieval_timestamp=retrieval_timestamp, universe_binding=universe_binding, freshness_matrix=freshness_matrix)
    except Exception as exc:
        blocking_reason = str(exc)
        expected = list(universe_binding.get("expected_universe") or []) or None
        partial_universe, _, join_status = _merge_production_sources(normalized_sources, trading_date, expected)
        matrix = build_requirement_matrix(trading_date=trading_date, cadence=cadence, normalized_sources=normalized_sources, universe=partial_universe, join_status=join_status)
        bundle = _blocked_bundle(trading_date=trading_date, cadence=cadence, retrieval_timestamp=retrieval_timestamp, sources=normalized_sources, blocking_reason=blocking_reason, transformation=transformation, matrix=matrix, universe_binding=universe_binding, freshness_matrix=freshness_matrix, qualified_count=_qualified_count(join_status))

    validation = validate_production_source_bundle(bundle, trading_date=trading_date, cadence=cadence)
    bundle["official_source_runtime_validation"] = validation
    if validation["validation_status"] != "PASS":
        bundle["validation_status"] = "BLOCKED"
        bundle["source_bundle_validation"] = "BLOCKED"
        bundle["blocking_reason"] = blocking_reason or bundle.get("blocking_reason") or "OFFICIAL_SOURCE_DECISION_BUNDLE_NOT_COMPLETE"
    atomic_write_json(Path(output), bundle)
    if requirement_matrix_output:
        atomic_write_json(Path(requirement_matrix_output), {"artifact": "RATE_PRODUCTION_SOURCE_REQUIREMENT_MATRIX", "validation_status": "PASS" if bundle["validation_status"] == "PASS" else "BLOCKED", "trading_date": trading_date, "cadence": cadence, "requirements": matrix})
    if universe_binding_output:
        atomic_write_json(Path(universe_binding_output), universe_binding)
    if freshness_matrix_output:
        atomic_write_json(Path(freshness_matrix_output), freshness_matrix)
    if feature_input_contract_output:
        atomic_write_json(Path(feature_input_contract_output), build_feature_input_contract_artifact())

    evidence = {
        "artifact": "RATE_PRODUCTION_OFFICIAL_SOURCE_ACQUISITION_EVIDENCE",
        "validation_status": "PASS" if bundle["validation_status"] == "PASS" else "BLOCKED",
        "trading_date": trading_date,
        "cadence": cadence,
        "main_sha": os.getenv("GITHUB_SHA"),
        "validated_main_sha": os.getenv("VALIDATED_MAIN_SHA") or os.getenv("GITHUB_SHA"),
        "github_ref": os.getenv("GITHUB_REF"),
        "github_event_name": os.getenv("GITHUB_EVENT_NAME"),
        "execution_scope": "PRODUCTION_SOURCE_ACQUISITION",
        "execution_authority": os.getenv("EXECUTION_AUTHORITY") or ("TEST_CONTEXT" if _is_test_context() else "DEVELOPMENT_LIVE_PROBE"),
        "probe_authority": "TEST_CONTEXT" if _is_test_context() else ("MAIN_ONLY" if os.getenv("EXECUTION_AUTHORITY") == "MAIN_ONLY" else "DEVELOPMENT_LIVE_PROBE"),
        "production_evidence_authoritative": bool(bundle.get("source_provenance", {}).get("production_evidence_authoritative")),
        "source_acquisition_independent_from_previous_state": True,
        "previous_state_required": False,
        "cadence_applicability": cadence_applicability_evidence(cadence),
        "external_dependencies": load_external_dependencies(),
        "scheduled_soak_credit": False,
        "acceptance_counter_reset": False,
        "source_endpoints": {k: v for k, v in url_map.items()},
        "sources": [{k: v for k, v in item.items() if k != "normalized_records"} for item in normalized_sources],
        "requirement_matrix_path": str(requirement_matrix_output).replace("\\", "/") if requirement_matrix_output else None,
        "universe_binding_path": str(universe_binding_output).replace("\\", "/") if universe_binding_output else None,
        "freshness_matrix_path": str(freshness_matrix_output).replace("\\", "/") if freshness_matrix_output else None,
        "feature_input_contract_path": str(feature_input_contract_output).replace("\\", "/") if feature_input_contract_output else None,
        "source_bundle_path": str(output).replace("\\", "/"),
        "source_snapshot_id": bundle.get("source_snapshot_id"),
        "input_snapshot_ids": bundle.get("input_snapshot_ids"),
        "freshness": bundle.get("freshness"),
        "completeness": bundle.get("completeness"),
        "coverage": bundle.get("coverage"),
        "decision_record_count": len(bundle.get("decision_records") or []),
        "universe_binding": universe_binding,
        "freshness_matrix": freshness_matrix,
        "feature_input_contract": build_feature_input_contract_artifact(),
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
    parser.add_argument("--universe-contract", default=None)
    parser.add_argument("--universe-binding-output", default=None)
    parser.add_argument("--freshness-matrix-output", default=None)
    parser.add_argument("--feature-input-contract-output", default=None)
    args = parser.parse_args()
    evidence = build_bundle(rate_source_url=args.rate_source_url, trading_date=args.trading_date, cadence=args.cadence, output=args.output, evidence_output=args.evidence_output, requirement_matrix_output=args.requirement_matrix_output, universe_contract=args.universe_contract, universe_binding_output=args.universe_binding_output, freshness_matrix_output=args.freshness_matrix_output, feature_input_contract_output=args.feature_input_contract_output)
    print(json.dumps(evidence, ensure_ascii=False, sort_keys=True))
    return 0 if evidence["validation_status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
