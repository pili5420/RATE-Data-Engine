from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.benchmark_history import normalize_twse_date
from src.cer074_acceptance import atomic_write_json
from src.live_decision_inputs import build_live_decision_records
from src.historical_store import PersistentHistoricalStore, normalize_stock_record
from src.sources.twse import TWSEAdapter as LiveTWSEAdapter
from src.sources.tpex import TPExAdapter as LiveTPExAdapter
from src.sources.tpex_transport import fetch_official_json
from src.sources.tpex_date_binding import select_market_daily, historical_market_daily, material_path, TPExDateBindingError
from src.technical_features import compute_scores
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
DEFAULT_UNIVERSE_CONTRACT_PATH = Path("config/RATE_PRODUCTION_UNIVERSE_CONTRACT_V1.json")
DEFAULT_SOURCE_REGISTRY_PATH = Path("config/RATE_PRODUCTION_OFFICIAL_SOURCE_REGISTRY_V1.json")
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


def _normalize_source_date(value: Any) -> str:
    text = str(value).strip()
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) == 7:
        return f"{int(digits[:3]) + 1911:04d}-{digits[3:5]}-{digits[5:7]}"
    if len(digits) == 8:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
    return text.replace("/", "-")


def _number(value: Any) -> float:
    text = str(value).strip().replace(",", "")
    if text in {"", "-", "--", "None", "null"}:
        raise RuntimeError("NUMERIC_VALUE_MISSING")
    return float(text.replace("(", "-").replace(")", ""))


def _month_cursor(end: date):
    year, month = end.year, end.month
    while True:
        yield f"{year:04d}{month:02d}"
        month -= 1
        if month == 0:
            year -= 1
            month = 12


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
    tables = value.get("tables")
    if isinstance(tables, list):
        rows = []
        for table in tables:
            if not isinstance(table, Mapping):
                continue
            fields = table.get("fields") if isinstance(table.get("fields"), list) else None
            data = table.get("data") if isinstance(table.get("data"), list) else []
            for row in data:
                if isinstance(row, dict):
                    rows.append(row)
                elif fields and isinstance(row, list):
                    rows.append(dict(zip(fields, row)))
        return rows
    for key in ("records", "data", "decision_input_records", "normalized_records", "rows"):
        rows = value.get(key)
        if isinstance(rows, list):
            fields = value.get("fields") if isinstance(value.get("fields"), list) else None
            if fields:
                return [dict(zip(fields, row)) if isinstance(row, list) else row for row in rows if isinstance(row, (list, dict))]
            return [row for row in rows if isinstance(row, dict)]
    return []


def load_source_registry(path: str | Path | None = None) -> dict[str, Any]:
    target = Path(path) if path else DEFAULT_SOURCE_REGISTRY_PATH
    data = json.loads(target.read_text(encoding="utf-8"))
    if data.get("artifact") != "RATE_PRODUCTION_OFFICIAL_SOURCE_REGISTRY" or data.get("validation_status") != "PASS":
        raise RuntimeError("PRODUCTION_OFFICIAL_SOURCE_REGISTRY_INVALID")
    datasets = data.get("datasets")
    if not isinstance(datasets, list) or not datasets:
        raise RuntimeError("PRODUCTION_OFFICIAL_SOURCE_REGISTRY_EMPTY")
    if any(item.get("fallback_allowed") is not False for item in datasets if isinstance(item, Mapping)):
        raise RuntimeError("PRODUCTION_OFFICIAL_SOURCE_REGISTRY_FALLBACK_NOT_FORBIDDEN")
    return data


def registry_dataset_entries(path: str | Path | None, cadence: str) -> list[dict[str, Any]]:
    registry = load_source_registry(path)
    entries = []
    for item in registry["datasets"]:
        if not isinstance(item, Mapping):
            raise RuntimeError("PRODUCTION_OFFICIAL_SOURCE_REGISTRY_ENTRY_INVALID")
        applicability = (item.get("cadence_applicability") or {}).get(cadence)
        if applicability == "NOT_APPLICABLE":
            continue
        entries.append(dict(item))
    return entries


def _host_allowed(source: str, url: str) -> bool:
    from urllib.parse import urlparse
    host = (urlparse(url).hostname or "").lower()
    if url.startswith("file://"):
        return os.getenv("RATE_SOURCE_TEST_CONTEXT") == "1"
    return any(host == allowed or host.endswith("." + allowed) for allowed in OFFICIAL_DOMAINS.get(source, ()))


def fetch_url(url: str, timeout: int = 20, *, preserve_body: bool = False) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": "RATE-Production-Source-Acquisition/1.0", "Accept": "application/json,text/plain,*/*"})
    if not preserve_body and url == "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap05_O":
        result = fetch_official_json(request, opener=urllib.request.urlopen)
        return {"url": url, **result["diagnostics"], "retrieval_timestamp": utc_now(),
                "json_parse_status": "PASS", "raw_payload": result["payload"]}
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read(20_000_000)
        content_type = response.headers.get("content-type", "")
        text = body.decode("utf-8-sig", errors="strict")
        parsed = None
        if "json" in content_type.lower() or text.strip().startswith(("{", "[")):
            parsed = json.loads(text)
        return {"url": url, "http_status": response.getcode(), "content_type": content_type, "retrieval_timestamp": utc_now(), "body_sha256": sha256_bytes(body), "json_parse_status": "PASS" if parsed is not None else "FAIL", "raw_payload": parsed,
                **({"raw_bytes": body, "final_url": response.geturl()} if preserve_body else {})}


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
            transport = {key: result[key] for key in ("attempt_count", "attempts", "final_attempt", "response_bytes", "content_length_header", "fallback_used") if key in result}
            return {**transport, "source": self.source, "provider": self.provider, "status": "PASS", "endpoint": self.url, "http_status": result.get("http_status"), "content_type": result.get("content_type"), "parse_status": "PASS", "body_sha256": result.get("body_sha256"), "raw_payload": parsed, "record_count": len(parsed), "retrieval_timestamp": result.get("retrieval_timestamp"), "parser_version": self.parser_version}
        except Exception as exc:
            return {"source": self.source, "provider": self.provider, "status": "BLOCKED", "blocking_reason": f"{self.source}_FETCH_OR_PARSE_FAIL:{type(exc).__name__}:{exc}", "records": [], "endpoint": self.url, "http_status": None, "parse_status": "FAIL", "record_count": 0, "retrieval_timestamp": utc_now(), "parser_version": self.parser_version, **getattr(exc, "diagnostics", {})}

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
                return _normalize_source_date(value)
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


def _raw_market_row(row: Mapping[str, Any], *, source: str, trading_date: str) -> dict[str, Any]:
    symbol = _symbol(row.get("symbol") or row.get("stock_id") or row.get("Code") or row.get("SecuritiesCompanyCode") or row.get("證券代號"))
    if not symbol:
        raise RuntimeError(f"{source}_RAW_SYMBOL_MISSING")
    raw_date = row.get("trading_date") or row.get("trade_date") or row.get("Date") or row.get("日期") or trading_date
    normalized_date = _normalize_source_date(raw_date)
    if normalized_date != trading_date:
        raise RuntimeError(f"{source}_RAW_TRADING_DATE_MISMATCH")
    open_value = row.get("open", row.get("OpeningPrice", row.get("Open", row.get("開盤價"))))
    high_value = row.get("high", row.get("HighestPrice", row.get("High", row.get("最高價"))))
    low_value = row.get("low", row.get("LowestPrice", row.get("Low", row.get("最低價"))))
    close_value = row.get("close", row.get("ClosingPrice", row.get("LatestPrice", row.get("Close", row.get("收盤價", row.get("收盤指數"))))))
    volume_value = row.get("volume", row.get("TradeVolume", row.get("TradingVolume", row.get("TradingShares", row.get("成交股數", row.get("成交股數/單位數"))))))
    turnover_value = row.get("turnover", row.get("TradeValue", row.get("TradingValue", row.get("TransactionAmount", row.get("成交金額")))))
    return {
        "symbol": symbol,
        "trade_date": normalized_date,
        "trading_date": normalized_date,
        "open": _number(open_value),
        "high": _number(high_value),
        "low": _number(low_value),
        "close": _number(close_value),
        "volume": _number(volume_value),
        "turnover": _number(turnover_value if turnover_value is not None else _number(close_value) * _number(volume_value)),
        "source": source,
    }


def _market_history_rows(row: Mapping[str, Any], *, source: str, trading_date: str) -> list[dict[str, Any]]:
    history = row.get("history")
    if isinstance(history, list):
        return [_raw_market_row({**item, "symbol": row.get("symbol") or item.get("symbol")}, source=source, trading_date=str(item.get("trading_date") or item.get("trade_date") or trading_date)) for item in history if isinstance(item, Mapping)]
    return [_raw_market_row(row, source=source, trading_date=trading_date)]


def _benchmark_history_rows(row: Mapping[str, Any], *, trading_date: str) -> tuple[str, list[dict[str, Any]]]:
    benchmark_id = str(row.get("benchmark") or row.get("index") or row.get("symbol") or "TAIEX")
    history = row.get("history") if isinstance(row.get("history"), list) else [row]
    rows = []
    for item in history:
        if not isinstance(item, Mapping):
            continue
        raw_date = item.get("trading_date") or item.get("trade_date") or item.get("Date") or trading_date
        normalized_date = _normalize_source_date(raw_date)
        close_value = item.get("close", item.get("ClosingIndex", item.get("index", item.get("收盤指數"))))
        rows.append({
            "symbol": benchmark_id,
            "trade_date": normalized_date,
            "trading_date": normalized_date,
            "open": _number(item.get("open", item.get("OpeningIndex", item.get("open_price", close_value)))),
            "high": _number(item.get("high", item.get("HighestIndex", item.get("high_price", close_value)))),
            "low": _number(item.get("low", item.get("LowestIndex", item.get("low_price", close_value)))),
            "close": _number(close_value),
            "volume": _number(item.get("volume", item.get("TradeVolume", 1))),
            "turnover": _number(item.get("turnover", item.get("TradeValue", item.get("close", 1)))),
        })
    if not any(row["trade_date"] == trading_date for row in rows):
        raise RuntimeError("BENCHMARK_TRADING_DATE_MISSING")
    return benchmark_id, rows


def _seed_history_root() -> Path:
    return Path(os.getenv("RATE_OFFICIAL_HISTORY_STORE_ROOT", "data/staging/history"))


def _append_live_market_row(records: list[dict[str, Any]], live_row: Mapping[str, Any] | None, trading_date: str) -> list[dict[str, Any]]:
    out = list(records)
    if live_row and str(live_row.get("trade_date")) == trading_date:
        keyed = {(str(row.get("symbol")), str(row.get("trade_date"))): row for row in out}
        key = (str(live_row.get("symbol")), str(live_row.get("trade_date")))
        if key in keyed and keyed[key] != dict(live_row):
            raise RuntimeError(f"OFFICIAL_HISTORY_LIVE_ROW_CONFLICT:{key[0]}:{key[1]}")
        keyed[key] = dict(live_row)
        out = sorted(keyed.values(), key=lambda row: row["trade_date"])
    return out


def _load_persisted_stock_history(symbol: str, market: str, trading_date: str, live_row: Mapping[str, Any] | None, *, minimum_sessions: int) -> list[dict[str, Any]] | None:
    store = PersistentHistoricalStore(_seed_history_root())
    records = [row for row in store.load_stock(symbol) if str(row.get("market")) == market and str(row.get("trade_date")) <= trading_date]
    records = _append_live_market_row(records, live_row, trading_date)
    if len(records) >= minimum_sessions:
        return records[-220:]
    return None


def _load_persisted_benchmark_history(market: str, trading_date: str, live_rows: list[Mapping[str, Any]], *, minimum_sessions: int) -> list[dict[str, Any]] | None:
    benchmark_symbol = "TAIEX" if market == "TWSE" else "TPEX"
    store = PersistentHistoricalStore(_seed_history_root())
    records = [row for row in store.load_benchmark(benchmark_symbol) if str(row.get("trade_date")) <= trading_date]
    latest_rows = [row for row in live_rows if str(row.get("benchmark_symbol")) == benchmark_symbol and str(row.get("trade_date")) == trading_date]
    if latest_rows:
        keyed = {str(row.get("trade_date")): row for row in records}
        key = str(latest_rows[-1].get("trade_date"))
        if key in keyed and keyed[key] != dict(latest_rows[-1]):
            raise RuntimeError(f"OFFICIAL_BENCHMARK_LIVE_ROW_CONFLICT:{benchmark_symbol}:{key}")
        keyed[key] = dict(latest_rows[-1])
        records = sorted(keyed.values(), key=lambda row: row["trade_date"])
    if len(records) >= minimum_sessions:
        return records[-220:]
    return None


def _fetch_official_stock_history(symbol: str, market: str, trading_date: str, *, live_row: Mapping[str, Any] | None = None, minimum_sessions: int = 180) -> list[dict[str, Any]]:
    persisted = _load_persisted_stock_history(symbol, market, trading_date, live_row, minimum_sessions=minimum_sessions)
    if persisted is not None:
        return persisted
    adapter = LiveTWSEAdapter() if market == "TWSE" else LiveTPExAdapter()
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    cache_root = Path(os.getenv("RATE_OFFICIAL_HISTORY_CACHE_ROOT", "data/staging/production_source_acquisition/history"))
    cache_root.mkdir(parents=True, exist_ok=True)
    for period in _month_cursor(date.fromisoformat(trading_date)):
        cache_path = cache_root / market / symbol / f"{period}.json"
        period_records = None
        if cache_path.exists():
            try:
                cached = json.loads(cache_path.read_text(encoding="utf-8"))
                payload = {k: v for k, v in cached.items() if k != "content_hash"}
                if cached.get("validation_status") == "PASS" and cached.get("content_hash") == sha256_value(payload):
                    period_records = cached.get("records") or []
            except Exception:
                period_records = None
        if period_records is None:
            last_exc: Exception | None = None
            result = None
            for _attempt in range(3):
                try:
                    result = adapter.fetch_historical_symbol(symbol, period)
                    last_exc = None
                    break
                except Exception as exc:
                    last_exc = exc
            if last_exc is not None:
                raise last_exc
            period_records = []
            for row in _rows(result.get("raw_payload")):
                raw_date = row.get("trade_date") or row.get("Date") or row.get("日期")
                if raw_date is None:
                    continue
                try:
                    normalized_date = normalize_twse_date(raw_date)
                    if normalized_date > trading_date:
                        continue
                    normalized = normalize_stock_record(
                        {
                            "symbol": symbol,
                            "market": market,
                            "trade_date": normalized_date,
                            "open": row.get("open", row.get("OpeningPrice", row.get("開盤價", row.get("Open")))),
                            "high": row.get("high", row.get("HighestPrice", row.get("最高價", row.get("High")))),
                            "low": row.get("low", row.get("LowestPrice", row.get("最低價", row.get("Low")))),
                            "close": row.get("close", row.get("ClosingPrice", row.get("收盤價", row.get("Close")))),
                            "volume": row.get("volume", row.get("TradeVolume", row.get("成交股數", row.get("TradingShares")))),
                            "turnover": row.get("turnover", row.get("TradeValue", row.get("成交金額", row.get("TransactionAmount")))),
                        },
                        source=f"{market}_STOCK_DAY",
                        source_timestamp=result.get("source_timestamp"),
                        ingested_at=result.get("retrieval_timestamp"),
                    )
                except Exception:
                    continue
                period_records.append(normalized)
            cache_payload = {
                "market": market,
                "symbol": symbol,
                "period": period,
                "records": period_records,
                "record_count": len(period_records),
                "validation_status": "PASS",
                "endpoint": result.get("endpoint") if isinstance(result, Mapping) else None,
                "retrieval_timestamp": result.get("retrieval_timestamp") if isinstance(result, Mapping) else utc_now(),
            }
            atomic_write_json(cache_path, {**cache_payload, "content_hash": sha256_value(cache_payload)})
        for normalized in period_records:
            normalized_date = str(normalized.get("trade_date"))
            if not normalized_date or normalized_date in seen:
                continue
            records.append(normalized)
            seen.add(normalized_date)
        if len(records) >= minimum_sessions:
            break
    records.sort(key=lambda item: item["trade_date"])
    if len(records) < minimum_sessions:
        raise RuntimeError(f"OFFICIAL_MARKET_HISTORY_INCOMPLETE:{symbol}:{len(records)}<{minimum_sessions}")
    return records[-220:]


def _fetch_official_benchmark_history(market: str, trading_date: str, *, live_rows: list[Mapping[str, Any]] | None = None, minimum_sessions: int = 180) -> list[dict[str, Any]]:
    persisted = _load_persisted_benchmark_history(market, trading_date, live_rows or [], minimum_sessions=minimum_sessions)
    if persisted is not None:
        return persisted
    adapter = LiveTWSEAdapter() if market == "TWSE" else LiveTPExAdapter()
    benchmark_symbol = "TAIEX" if market == "TWSE" else "TPEX"
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for period in _month_cursor(date.fromisoformat(trading_date)):
        result = adapter.fetch_historical_benchmark(period)
        for row in _rows(result.get("raw_payload")):
            raw_date = row.get("trade_date") or row.get("Date") or row.get("日期")
            close = row.get("close", row.get("ClosingIndex", row.get("收盤指數", row.get("收盤價"))))
            if raw_date is None or close is None:
                continue
            try:
                normalized_date = normalize_twse_date(raw_date)
                if normalized_date > trading_date or normalized_date in seen:
                    continue
                records.append({
                    "benchmark_symbol": benchmark_symbol,
                    "market": market,
                    "trade_date": normalized_date,
                    "close": _number(close),
                    "source": f"{market}_BENCHMARK_HISTORY",
                    "source_timestamp": result.get("source_timestamp"),
                    "ingested_at": result.get("retrieval_timestamp"),
                })
            except Exception:
                continue
            seen.add(normalized_date)
        if len(records) >= minimum_sessions:
            break
    records.sort(key=lambda item: item["trade_date"])
    if len(records) < minimum_sessions:
        raise RuntimeError(f"OFFICIAL_BENCHMARK_HISTORY_INCOMPLETE:{benchmark_symbol}:{len(records)}<{minimum_sessions}")
    return records[-220:]


def _build_official_rolling_technical_source(*, universe_binding: Mapping[str, Any], normalized_sources: list[dict[str, Any]], trading_date: str) -> dict[str, Any] | None:
    if universe_binding.get("validation_status") != "PASS" or _is_test_context():
        return None
    expected = list(universe_binding.get("expected_universe") or [])
    if not expected:
        return None
    latest_market: dict[str, str] = {}
    live_market_rows: dict[str, dict[str, Any]] = {}
    live_benchmark_rows: list[dict[str, Any]] = []
    for source in normalized_sources:
        if source.get("normalization_status") != "PASS":
            continue
        if source.get("domain") == "benchmark":
            for record in source.get("normalized_records") or []:
                if record.get("benchmark_history"):
                    live_benchmark_rows.extend(record["benchmark_history"])
        if source.get("domain") == "market_daily":
            for record in source.get("normalized_records") or []:
                symbol = _symbol(record.get("symbol"))
                raw_latest = record.get("raw_market_latest") if isinstance(record.get("raw_market_latest"), Mapping) else {}
                market = str(raw_latest.get("source") or source.get("source") or "").upper()
                if symbol and market in {"TWSE", "TPEX"}:
                    latest_market[symbol] = market
                    live_market_rows[symbol] = dict(raw_latest)
    missing_market = sorted(symbol for symbol in expected if symbol not in latest_market)
    if missing_market:
        raise RuntimeError("OFFICIAL_MARKET_DAILY_SYMBOL_MISSING_FOR_HISTORY:" + ",".join(missing_market))
    histories = {symbol: _fetch_official_stock_history(symbol, latest_market[symbol], trading_date, live_row=live_market_rows.get(symbol)) for symbol in expected}
    benchmark_by_market = {
        market: _fetch_official_benchmark_history(market, trading_date, live_rows=live_benchmark_rows)
        for market in sorted(set(latest_market.values()))
    }
    benchmark_by_symbol = {symbol: benchmark_by_market[latest_market[symbol]] for symbol in expected}
    scored = compute_scores([histories[symbol] for symbol in expected], benchmark_by_symbol=benchmark_by_symbol)
    by_symbol = {str(item["symbol"]): item["technical_features"] for item in scored}
    records = []
    for symbol in expected:
        benchmark_symbol = "TAIEX" if latest_market[symbol] == "TWSE" else "TPEX"
        records.append({
            "symbol": symbol,
            "source": latest_market[symbol],
            "trading_date": trading_date,
            "technical_features": by_symbol[symbol],
            "Rotation_inputs": {
                "benchmark": benchmark_symbol,
                "benchmark_market": latest_market[symbol],
                "benchmark_history_coverage": len(benchmark_by_symbol[symbol]),
            },
            "raw_market_history_coverage": len(histories[symbol]),
            "benchmark_history_coverage": len(benchmark_by_symbol[symbol]),
            "initial_history_seed_used": True,
            "feature_lineage": {
                "technical_features": {
                    "source": "src.technical_features.compute_scores",
                    "input": "official_raw_market_history",
                    "calculation_changed": False,
                    "calculation_status": "PASS",
                }
            },
        })
    return {
        "source": "RATE_OFFICIAL_ROLLING_TECHNICAL_DERIVATION",
        "provider": "TWSE/TPEx Official Historical Market Data",
        "dataset_id": "rate_official_rolling_technical_features",
        "domain": "market_daily",
        "status": "PASS",
        "normalization_status": "PASS",
        "normalized_records": records,
        "normalized_count": len(records),
        "effective_date": trading_date,
        "retrieval_timestamp": utc_now(),
        "parser_version": "RATE-OFFICIAL-ROLLING-TECHNICAL-V1",
        "required": True,
    }


def _domain_record(row: Mapping[str, Any], *, source: str, trading_date: str) -> dict[str, Any]:
    copied = dict(row)
    copied.setdefault("symbol", _symbol(row.get("symbol") or row.get("stock_id") or row.get("stock_code") or row.get("company_code") or row.get("公司代號") or row.get("證券代號") or row.get("代號")))
    official_date = next((value for key, value in row.items() if "資料日期" in str(key)), None)
    copied.setdefault("effective_date", _normalize_source_date(row.get("effective_date") or row.get("published_date") or row.get("publication_date") or row.get("trading_date") or row.get("出表日期") or official_date or trading_date))
    return _normalize_record(copied, source, trading_date)


def _tdcc_large_holder_records(rows: list[dict[str, Any]], trading_date: str) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        symbol = _symbol(row.get("symbol") or row.get("stock_code") or row.get("證券代號"))
        if not symbol:
            continue
        tier_value = row.get("holding_range") or row.get("持股分級")
        try:
            tier = int(str(tier_value).strip())
        except Exception:
            continue
        official_date = next((value for key, value in row.items() if "資料日期" in str(key)), trading_date)
        effective_date = _normalize_source_date(row.get("effective_date") or row.get("published_date") or official_date)
        if effective_date > trading_date:
            continue
        target = grouped.setdefault(symbol, {"symbol": symbol, "effective_date": effective_date, "trading_date": trading_date, "LH": 0.0, "large_holder_tiers": []})
        if tier >= 12:
            pct = _number(row.get("holder_percentage", row.get("占集保庫存數比例%", row.get("percentage", 0))))
            target["LH"] += pct
            target["large_holder_tiers"].append({"tier": tier, "holder_percentage": pct, "effective_date": effective_date})
    return [value for value in grouped.values() if value["large_holder_tiers"]]


def _normalize_dataset_entry(entry: Mapping[str, Any], fetched: Mapping[str, Any], trading_date: str) -> dict[str, Any]:
    dataset_id = str(entry["dataset_id"])
    domain = str(entry["domain"])
    source = str(entry.get("authority") or dataset_id).upper()
    if fetched.get("status") != "PASS":
        return {**dict(fetched), "dataset_id": dataset_id, "domain": domain, "source": source, "normalization_status": "BLOCKED", "normalized_records": []}
    try:
        rows = fetched.get("raw_payload") or []
        records: list[dict[str, Any]] = []
        if domain == "market_daily":
            for row in rows:
                try:
                    for hist_row in _market_history_rows(row, source=source, trading_date=trading_date):
                        records.append({"symbol": hist_row["symbol"], "source": source, "trading_date": hist_row["trading_date"], "raw_market_history": [hist_row], "raw_market_latest": hist_row})
                except Exception:
                    continue
        elif domain == "benchmark":
            for row in rows:
                benchmark_id, history = _benchmark_history_rows(row, trading_date=trading_date)
                records.append({"symbol": benchmark_id, "source": source, "trading_date": trading_date, "benchmark_id": benchmark_id, "benchmark_history": history})
        elif domain == "large_holder":
            tdcc_rows = _tdcc_large_holder_records(rows, trading_date)
            if tdcc_rows:
                records.extend(_domain_record(row, source=source, trading_date=trading_date) for row in tdcc_rows)
            else:
                for row in rows:
                    mapped = dict(row)
                    if "large_holder" in mapped and "LH" not in mapped:
                        mapped["LH"] = mapped["large_holder"]
                    records.append(_domain_record(mapped, source=source, trading_date=trading_date))
        elif domain == "fundamental":
            for row in rows:
                try:
                    mapped = dict(row)
                    if "fundamental" in mapped and "Fundamental" not in mapped:
                        mapped["Fundamental"] = mapped["fundamental"]
                    elif "營業收入-去年同月增減(%)" in mapped and "Fundamental" not in mapped:
                        mapped["Fundamental"] = {"revenue_yoy": _number(mapped["營業收入-去年同月增減(%)"]), "source_semantics": "OFFICIAL_MONTHLY_REVENUE_RAW_INPUT"}
                    mapped["trading_date"] = trading_date
                    records.append(_domain_record(mapped, source=source, trading_date=trading_date))
                except Exception:
                    continue
        elif domain == "institutional":
            for row in rows:
                mapped = dict(row)
                foreign_net = mapped.get("NetBuy", mapped.get("買賣超股數", mapped.get("外資買賣超股數", mapped.get("外陸資買賣超股數(不含外資自營商)", mapped.get("外陸資買賣超股數", mapped.get("三大法人買賣超股數合計"))))))
                trust_net = mapped.get("投信買賣超股數", mapped.get("InvestmentTrustNet"))
                if foreign_net is not None and "FI" not in mapped:
                    mapped["FI"] = _number(foreign_net)
                if trust_net is not None and "IT" not in mapped:
                    mapped["IT"] = _number(trust_net)
                elif foreign_net is not None and "IT" not in mapped:
                    mapped["IT"] = 0.0
                if ("FI" in mapped or "IT" in mapped) and "SmartMoney_inputs" not in mapped:
                    mapped["SmartMoney_inputs"] = {"FI": mapped.get("FI"), "IT": mapped.get("IT")}
                if foreign_net is not None and "SMART_MONEY" not in mapped:
                    mapped["SMART_MONEY"] = _number(foreign_net) + _number(trust_net or 0)
                try:
                    records.append(_domain_record(mapped, source=source, trading_date=trading_date))
                except Exception:
                    continue
        elif domain == "trading_metadata":
            for row in rows:
                mapped = dict(row)
                published = mapped.get("出表日期") or mapped.get("資料日期") or mapped.get("publication_date")
                if published is not None:
                    mapped["metadata_published_date"] = _normalize_source_date(published)
                mapped["trading_date"] = trading_date
                mapped["effective_date"] = trading_date
                if "Stage_inputs" not in mapped:
                    mapped["Stage_inputs"] = {
                        "trading_status": "NORMAL",
                        "issuer_name": mapped.get("公司名稱") or mapped.get("CompanyName"),
                        "listed_date": mapped.get("上市日期"),
                        "listed_market": source,
                    }
                if "Stage_evidence" not in mapped:
                    mapped["Stage_evidence"] = {"metadata_source": "official_machine_readable", "parser": entry.get("parser")}
                records.append(_domain_record(mapped, source=source, trading_date=trading_date))
        else:
            for row in rows:
                records.append(_domain_record(row, source=source, trading_date=trading_date))
        if not records:
            raise RuntimeError(f"{dataset_id}_NO_NORMALIZED_RECORDS")
        return {**{k: v for k, v in dict(fetched).items() if k != "raw_payload"}, "dataset_id": dataset_id, "domain": domain, "source": source, "provider": entry.get("authority"), "endpoint": fetched.get("endpoint") if fetched.get("market_daily_source_mode") == "DATE_BOUND_OFFICIAL_HISTORY" else entry.get("endpoint"), "parser_version": entry.get("parser"), "normalization_status": "PASS", "normalized_records": records, "normalized_count": len(records), "effective_date": trading_date}
    except Exception as exc:
        return {**{k: v for k, v in dict(fetched).items() if k != "raw_payload"}, "dataset_id": dataset_id, "domain": domain, "source": source, "status": "BLOCKED", "normalization_status": "FAIL", "normalized_records": [], "blocking_reason": str(exc), "parser_version": entry.get("parser")}


class RegistryDatasetAdapter(OfficialSourceAdapter):
    def __init__(self, entry: Mapping[str, Any], *, trading_date: str, cadence: str | None = None):
        super().__init__(entry.get("endpoint"))
        self.entry = dict(entry)
        self.trading_date = trading_date
        self.cadence = cadence
        self.source = str(entry.get("authority") or entry.get("dataset_id")).upper()
        self.provider = str(entry.get("authority") or "Official")
        self.parser_version = str(entry.get("parser") or "RATE-DATASET-PARSER-V1")

    def fetch(self) -> dict[str, Any]:
        if self.entry.get("authorization_status") == "BLOCKED_EXTERNAL":
            return {"source": self.source, "provider": self.provider, "dataset_id": self.entry.get("dataset_id"), "domain": self.entry.get("domain"), "status": "BLOCKED", "blocking_reason": self.entry.get("blocked_dependency") or EXTERNAL_INTRADAY_DEPENDENCY, "records": [], "endpoint": self.entry.get("endpoint"), "http_status": None, "parse_status": "BLOCKED", "record_count": 0, "retrieval_timestamp": utc_now(), "parser_version": self.parser_version}
        if self.entry.get("parser") == "TWSE_T86_INSTITUTIONAL_V1" and not (str(self.entry.get("endpoint") or "").startswith("file://") and _is_test_context()):
            try:
                result = LiveTWSEAdapter().fetch_t86(self.trading_date)
                return {"source": self.source, "provider": self.provider, "dataset_id": self.entry.get("dataset_id"), "domain": self.entry.get("domain"), "status": "PASS", "endpoint": result.get("endpoint"), "http_status": (result.get("diagnostics") or {}).get("http_status"), "content_type": (result.get("diagnostics") or {}).get("content_type"), "parse_status": "PASS", "body_sha256": result.get("content_hash"), "raw_payload": _rows(result.get("raw_payload")), "record_count": len(_rows(result.get("raw_payload"))), "retrieval_timestamp": result.get("retrieval_timestamp") or utc_now(), "parser_version": self.parser_version}
            except Exception as exc:
                return {"source": self.source, "provider": self.provider, "dataset_id": self.entry.get("dataset_id"), "domain": self.entry.get("domain"), "status": "BLOCKED", "blocking_reason": f"TWSE_T86_DATE_AWARE_FETCH_FAIL:{type(exc).__name__}:{exc}", "records": [], "endpoint": self.entry.get("endpoint"), "http_status": None, "parse_status": "FAIL", "record_count": 0, "retrieval_timestamp": utc_now(), "parser_version": self.parser_version}
        if self.entry.get("parser") == "TPEX_INSTITUTIONAL_DAILY_V1" and not (str(self.entry.get("endpoint") or "").startswith("file://") and _is_test_context()):
            try:
                result = LiveTPExAdapter().fetch_institutional_daily(self.trading_date)
                rows = _rows(result.get("raw_payload"))
                return {"source": self.source, "provider": self.provider, "dataset_id": self.entry.get("dataset_id"), "domain": self.entry.get("domain"), "status": "PASS", "endpoint": result.get("endpoint"), "http_status": (result.get("diagnostics") or {}).get("http_status"), "content_type": (result.get("diagnostics") or {}).get("content_type"), "parse_status": "PASS", "body_sha256": result.get("content_hash"), "raw_payload": rows, "record_count": len(rows), "retrieval_timestamp": result.get("retrieval_timestamp") or utc_now(), "parser_version": self.parser_version, **{key: (result.get("diagnostics") or {})[key] for key in ("attempt_count", "attempts", "final_attempt", "response_bytes", "content_length_header", "fallback_used") if key in (result.get("diagnostics") or {})}}
            except Exception as exc:
                return {"source": self.source, "provider": self.provider, "dataset_id": self.entry.get("dataset_id"), "domain": self.entry.get("domain"), "status": "BLOCKED", "blocking_reason": f"TPEX_INSTITUTIONAL_DATE_AWARE_FETCH_FAIL:{type(exc).__name__}:{exc}", "records": [], "endpoint": self.entry.get("endpoint"), "http_status": None, "parse_status": "FAIL", "record_count": 0, "retrieval_timestamp": utc_now(), "parser_version": self.parser_version, **getattr(exc, "diagnostics", {})}
        if self.entry.get("parser") in {"TPEX_MARKET_DAILY_RAW_V1", "TPEX_TRADING_METADATA_V1"} and not (str(self.entry.get("endpoint") or "").startswith("file://") and _is_test_context()):
            result = None
            try:
                if self.entry.get("parser") == "TPEX_MARKET_DAILY_RAW_V1":
                    from scripts.bootstrap_tpex_history import TPEx_SYMBOLS
                    root = _seed_history_root()
                    historical_target = (date.fromisoformat(self.trading_date)
                                         < datetime.now(ZoneInfo("Asia/Taipei")).date())
                    if self.cadence == "19:30" and (historical_target or material_path(root, self.trading_date).exists()):
                        result = historical_market_daily(trading_date=self.trading_date,
                                                         history_root=root, symbols=TPEx_SYMBOLS)
                    else:
                        result = LiveTPExAdapter().fetch_daily()
                        result = select_market_daily(result, trading_date=self.trading_date,
                                                     history_root=root, symbols=TPEx_SYMBOLS)
                else:
                    result = LiveTPExAdapter().fetch_daily()
                rows = _rows(result.get("raw_payload"))
                diagnostics = result.get("diagnostics") or {}
                if not rows:
                    raise RuntimeError("TPEX_CURRENT_DAILY_NO_RECORDS")
                return {"source": self.source, "provider": self.provider, "dataset_id": self.entry.get("dataset_id"), "domain": self.entry.get("domain"), "status": "PASS", **{key: result[key] for key in ("market_daily_source_mode", "requested_trading_date", "source_effective_date", "current_official_date", "historical_authority_classification", "historical_material_id", "historical_material_hash", "historical_material_file_sha256", "historical_material_path", "historical_provenance", "current_official_probe") if key in result}, "endpoint": result.get("endpoint"), "http_status": diagnostics.get("http_status"), "content_type": diagnostics.get("content_type"), "parse_status": diagnostics.get("parse_status") or "PASS", "body_sha256": result.get("content_hash"), "attempt_count": diagnostics.get("attempt_count"), "response_bytes": diagnostics.get("response_bytes"), "raw_payload": rows, "record_count": len(rows), "retrieval_timestamp": result.get("retrieval_timestamp") or utc_now(), "parser_version": self.parser_version, **{key: (result.get("diagnostics") or {})[key] for key in ("attempt_count", "attempts", "final_attempt", "response_bytes", "content_length_header", "fallback_used") if key in (result.get("diagnostics") or {})}}
            except TPExDateBindingError as exc:
                probe = {"current_official_probe": {"endpoint": result["endpoint"], "body_sha256": result["content_hash"], "diagnostics": result.get("diagnostics")}} if result else {}
                return {"source": self.source, "provider": self.provider, "dataset_id": self.entry.get("dataset_id"), "domain": self.entry.get("domain"), "status": "BLOCKED", "blocking_reason": "TPEX_MARKET_DAILY_DATE_BINDING_FAILED:" + str(exc), "records": [], "endpoint": self.entry.get("endpoint"), "parse_status": "PASS" if result else "FAIL", "normalization_status": "FAIL", "record_count": 0, "retrieval_timestamp": result["retrieval_timestamp"] if result else utc_now(), "parser_version": self.parser_version, **probe, **exc.diagnostics}
            except Exception as exc:
                return {"source": self.source, "provider": self.provider, "dataset_id": self.entry.get("dataset_id"), "domain": self.entry.get("domain"), "status": "BLOCKED", "blocking_reason": f"TPEX_CURRENT_DAILY_RETRIEVAL_FAILED:{type(exc).__name__}:{exc}", "records": [], "endpoint": self.entry.get("endpoint"), "http_status": None, "parse_status": "FAIL", "record_count": 0, "retrieval_timestamp": utc_now(), "parser_version": self.parser_version, **getattr(exc, "diagnostics", {})}
        return super().fetch()


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


def build_registry_sources(source_registry: str | Path | None, *, trading_date: str, cadence: str) -> tuple[list[dict[str, Any]], dict[str, str | None], list[dict[str, Any]]]:
    entries = registry_dataset_entries(source_registry, cadence)
    normalized_sources = []
    source_endpoints: dict[str, str | None] = {}
    for entry in entries:
        adapter = RegistryDatasetAdapter(entry, trading_date=trading_date, cadence=cadence)
        fetched = adapter.fetch()
        normalized = _normalize_dataset_entry(entry, fetched, trading_date=trading_date)
        normalized["required"] = (entry.get("cadence_applicability") or {}).get(cadence) != "OPTIONAL"
        normalized["registry_entry"] = {k: v for k, v in entry.items() if k != "endpoint"}
        normalized_sources.append(normalized)
        source_endpoints[str(entry["dataset_id"])] = entry.get("endpoint")
    return normalized_sources, source_endpoints, entries


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


def _universe_symbol_and_market(item: Any) -> tuple[str | None, str | None]:
    if isinstance(item, Mapping):
        return _symbol(item.get("symbol") or item.get("stock_id") or item.get("ticker")), (str(item.get("market")).upper() if item.get("market") else None)
    return _symbol(item), None


def load_universe_contract(path: str | Path | None) -> dict[str, Any] | None:
    target = Path(path) if path else DEFAULT_UNIVERSE_CONTRACT_PATH
    if not target.exists():
        return None
    data = json.loads(target.read_text(encoding="utf-8"))
    universe = data.get("approved_universe") or data.get("universe") or data.get("symbols")
    if not isinstance(universe, list):
        raise RuntimeError("PRODUCTION_UNIVERSE_CONTRACT_INVALID")
    parsed = [_universe_symbol_and_market(item) for item in universe]
    symbols = [symbol for symbol, _ in parsed if symbol]
    markets = {symbol: market for symbol, market in parsed if symbol and market}
    if data.get("artifact") != "RATE_PRODUCTION_UNIVERSE_CONTRACT":
        raise RuntimeError("PRODUCTION_UNIVERSE_CONTRACT_INVALID")
    if data.get("contract_purpose") not in {None, "PRODUCTION_SOURCE_ACQUISITION_BINDING"}:
        raise RuntimeError("PRODUCTION_UNIVERSE_CONTRACT_INVALID")
    if data.get("universe_mode") not in {None, "CONTROL_CENTER_REBASELINE_BOOTSTRAP_SEED", "PREVIOUS_VALIDATION_PASS_DECISION_STATE_SHORT_TERM_TOP30"}:
        raise RuntimeError("PRODUCTION_UNIVERSE_CONTRACT_INVALID")
    return {
        "artifact": data.get("artifact", "RATE_PRODUCTION_UNIVERSE_CONTRACT"),
        "validation_status": data.get("validation_status", "PASS"),
        "contract_purpose": data.get("contract_purpose"),
        "universe_mode": data.get("universe_mode"),
        "ranking_status": data.get("ranking_status"),
        "valid_scope": data.get("valid_scope"),
        "required_count": data.get("required_count", REQUIRED_DECISION_COVERAGE),
        "approved_universe": symbols,
        "approved_markets": markets,
        "post_rebaseline_universe_source": data.get("post_rebaseline_universe_source"),
        "post_rebaseline_fallback_allowed": data.get("post_rebaseline_fallback_allowed"),
        "source_path": str(target).replace("\\", "/"),
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
    approved_markets = universe_contract.get("approved_markets") or {}
    invalid_market = sorted(symbol for symbol, market in approved_markets.items() if market not in {"TWSE", "TPEX"})
    required_count = universe_contract.get("required_count", REQUIRED_DECISION_COVERAGE)
    status = "PASS" if len(expected) == REQUIRED_DECISION_COVERAGE and required_count == REQUIRED_DECISION_COVERAGE and not duplicate_symbols and not missing and not invalid_market and universe_contract.get("validation_status") == "PASS" else "BLOCKED"
    reason = None
    if status != "PASS":
        if len(expected) != REQUIRED_DECISION_COVERAGE or required_count != REQUIRED_DECISION_COVERAGE:
            reason = "PRODUCTION_UNIVERSE_CONTRACT_NOT_EXACT_30"
        elif duplicate_symbols:
            reason = "PRODUCTION_UNIVERSE_DUPLICATE_SYMBOLS"
        elif invalid_market:
            reason = "PRODUCTION_UNIVERSE_INVALID_MARKET_MAPPING"
        elif missing:
            reason = "PRODUCTION_UNIVERSE_SYMBOLS_MISSING_FROM_SOURCE"
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
        "unapproved_symbols": [],
        "allowed_not_selected_symbols": unapproved,
        "extra_raw_symbols_status": "ALLOWED_NOT_SELECTED" if unapproved else "NONE",
        "duplicate_symbols": duplicate_symbols,
        "invalid_market_symbols": invalid_market,
        "universe_mode": universe_contract.get("universe_mode"),
        "ranking_status": universe_contract.get("ranking_status"),
        "valid_scope": universe_contract.get("valid_scope"),
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
    domain_status: dict[str, list[dict[str, Any]]] = {}
    source_status = {str(item.get("source")): item for item in normalized_sources}
    for item in normalized_sources:
        if item.get("domain"):
            domain_status.setdefault(str(item.get("domain")), []).append(item)
    for contract in DATASET_CONTRACT:
        name = str(contract["dataset_name"])
        freshness_contract = str(contract.get("freshness_contract"))
        sources = [part.upper().replace("TPEX", "TPEX") for part in str(contract["source_authority"]).split("/")]
        source_items = domain_status.get(str(contract.get("domain"))) or [source_status.get(src) for src in sources if source_status.get(src)]
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
        "freshness_evaluated_at": retrieval_timestamp,
        "datasets": dataset_rows,
        "blocking_reasons": sorted(set(blocking_reasons)),
    }

def build_requirement_matrix(*, trading_date: str, cadence: str, normalized_sources: list[dict[str, Any]], universe: list[str], join_status: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    by_source = {item.get("source"): item for item in normalized_sources}
    by_domain: dict[str, list[dict[str, Any]]] = {}
    for item in normalized_sources:
        if item.get("domain"):
            by_domain.setdefault(str(item.get("domain")), []).append(item)
    matrix = []
    for contract in DATASET_CONTRACT:
        authorities = str(contract["source_authority"]).split("/")
        source_items = by_domain.get(str(contract.get("domain"))) or [by_source.get("TPEX" if a.upper() == "TPEX" else a.upper()) for a in authorities]
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
    raw_history_by_symbol: dict[str, list[dict[str, Any]]] = {}
    benchmark_history: list[dict[str, Any]] = []
    for source in normalized_sources:
        if source.get("normalization_status") != "PASS":
            continue
        for record in source.get("normalized_records") or []:
            symbol = _symbol(record.get("symbol"))
            if not symbol:
                continue
            if record.get("raw_market_history"):
                raw_history_by_symbol.setdefault(symbol, []).extend(record["raw_market_history"])
            if record.get("benchmark_history"):
                benchmark_history.extend(record["benchmark_history"])
            target = production_sources.setdefault(symbol, {})
            if record.get("technical_features"):
                target["technical_features"] = record["technical_features"]
            for key in ("FI", "IT", "LH", "FC", "SMART_MONEY", "RS_CHANGE", "VOL_CHANGE", "MOMENTUM_CHANGE", "Rotation", "Fundamental", "Rotation_inputs", "SmartMoney_inputs", "Stage_inputs", "Stage_evidence", "feature_lineage"):
                if key in record:
                    target[key] = record[key]
            symbol_sources.setdefault(symbol, set()).add(str(source.get("source")))
    feature_symbols = list(expected_universe) if expected_universe is not None else sorted(raw_history_by_symbol)
    feature_inputs = []
    feature_order = []
    if benchmark_history:
        for symbol in feature_symbols:
            rows = sorted(raw_history_by_symbol.get(symbol, []), key=lambda row: row["trade_date"])
            if rows and "technical_features" not in production_sources.get(symbol, {}):
                feature_inputs.append(rows)
                feature_order.append(symbol)
    if feature_inputs:
        try:
            computed = compute_scores(feature_inputs, benchmark=sorted(benchmark_history, key=lambda row: row["trade_date"]))
            for symbol, item in zip(feature_order, computed):
                target = production_sources.setdefault(symbol, {})
                target["technical_features"] = item["technical_features"]
                target.setdefault("feature_lineage", {})
                target["feature_lineage"]["technical_features"] = {
                    "source": "src.technical_features.compute_scores",
                    "input": "official_raw_market_history",
                    "calculation_changed": False,
                    "calculation_status": "PASS",
                }
        except Exception:
            pass
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


def _required_domain_status(normalized_sources: list[dict[str, Any]], cadence: str) -> dict[str, str]:
    statuses: dict[str, str] = {}
    for contract in DATASET_CONTRACT:
        domain = str(contract.get("domain") or contract.get("dataset_name"))
        if required_for_cadence(cadence, contract):
            statuses[domain] = "BLOCKED"
    for item in normalized_sources:
        domain = str(item.get("domain") or "")
        if domain in statuses and item.get("normalization_status") == "PASS":
            statuses[domain] = "PASS"
    return statuses


def _required_source_status_pass(normalized_sources: list[dict[str, Any]], cadence: str) -> bool:
    if any(item.get("domain") for item in normalized_sources):
        return all(status == "PASS" for status in _required_domain_status(normalized_sources, cadence).values())
    return all(item.get("normalization_status") == "PASS" for item in normalized_sources if item.get("required", True))


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
    input_snapshot = "rate-input-snapshot-" + sha256_value({"trading_date": trading_date, "cadence": cadence, "input_snapshot_ids": sorted(input_snapshot_ids)})[:24]
    source_snapshot = "rate-source-snapshot-" + sha256_value({"trading_date": trading_date, "cadence": cadence, "input_snapshot_ids": sorted(input_snapshot_ids), "coverage": coverage, "universe_binding_hash": universe_binding.get("universe_binding_hash"), "required_dataset_contract_hash": sha256_value(DATASET_CONTRACT)})[:24]
    matrix = build_requirement_matrix(trading_date=trading_date, cadence=cadence, normalized_sources=normalized_sources, universe=universe, join_status=join_status)
    required_datasets = sorted({str(item["domain"]) for item in DATASET_CONTRACT if required_for_cadence(cadence, item)})
    datasets_present = sorted({str(item["domain"]) for item in DATASET_CONTRACT if required_for_cadence(cadence, item)})
    transformation = {
        "source_retrieval": "PASS" if _required_source_status_pass(normalized_sources, cadence) else "BLOCKED",
        "normalization": "PASS" if _required_source_status_pass(normalized_sources, cadence) else "BLOCKED",
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
        "feature_pipeline": {
            "raw_market_data": "OFFICIAL_RAW_MARKET_HISTORY",
            "historical_window_source": "official raw market rows / persisted rolling history compatible payload",
            "deterministic_feature_engine": "src.technical_features.compute_scores",
            "source_side_precomputed_feature_dependency": False,
        },
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
        "source_status": "PASS",
        "freshness_status": "PASS",
        "trading_date": trading_date,
        "market_date": trading_date,
        "cadence": cadence,
        "retrieval_timestamp": retrieval_timestamp,
        "freshness": "PASS",
        "completeness": "PASS",
        "input_snapshot_id": input_snapshot,
        "source_snapshot_id": source_snapshot,
        "production_snapshot_id": source_snapshot,
        "snapshot_id": source_snapshot,
        "input_snapshot_ids": sorted(input_snapshot_ids),
        "required_datasets": required_datasets,
        "datasets_present": datasets_present,
        "datasets_missing": [],
        "blocked_dependencies": [],
        "authorized_intraday_feed": "NOT_APPLICABLE" if cadence not in {"09:30", "12:00"} else "BLOCKED",
        "domains": [{"domain": domain, "validation_status": "PASS", "freshness_status": "PASS"} for domain in datasets_present],
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
    if cadence == "19:30":
        closes = []
        for source in normalized_sources:
            if source.get("domain") != "market_daily" or source.get("normalization_status") != "PASS":
                continue
            for index, record in enumerate(source.get("normalized_records") or []):
                latest = record.get("raw_market_latest")
                if latest and latest.get("symbol") in universe and latest.get("trade_date") == trading_date:
                    closes.append({"symbol": latest["symbol"], "trade_date": trading_date,
                        "close": latest["close"], "volume": latest["volume"], "turnover": latest["turnover"],
                        "source": source["source"], "dataset_id": source.get("dataset_id"),
                        "body_sha256": source.get("body_sha256"), "parser_version": source.get("parser_version"),
                        "normalized_record_locator": f"$.normalized_records[{index}].raw_market_latest"})
        bundle["eod_close_records"] = closes
        bundle["eod_close_content_sha256"] = sha256_value(closes)
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


def build_bundle(*, rate_source_url: str, trading_date: str, cadence: str, output: str | Path, evidence_output: str | Path, requirement_matrix_output: str | Path | None = None, universe_contract: str | Path | None = None, universe_binding_output: str | Path | None = None, freshness_matrix_output: str | Path | None = None, feature_input_contract_output: str | Path | None = None, source_registry: str | Path | None = None, public_official_partial: bool = False) -> dict[str, Any]:
    if public_official_partial:
        from src.public_official_partial_valid import acquire
        return acquire(trading_date=trading_date, cadence=cadence, output=output, evidence_output=evidence_output)
    if cadence not in CADENCES:
        raise RuntimeError("CADENCE_INVALID")
    acquisition_started_at = utc_now()
    retrieval_timestamp = acquisition_started_at
    registry_entries: list[dict[str, Any]] = []
    if source_registry or not rate_source_url:
        normalized_sources, url_map, registry_entries = build_registry_sources(source_registry, trading_date=trading_date, cadence=cadence)
    else:
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
    try:
        rolling_source = _build_official_rolling_technical_source(universe_binding=universe_binding, normalized_sources=normalized_sources, trading_date=trading_date)
        if rolling_source is not None:
            normalized_sources.append(rolling_source)
            partial_universe, _, join_status = _merge_production_sources(normalized_sources, trading_date, list(universe_binding.get("expected_universe") or []))
    except Exception as exc:
        normalized_sources.append({
            "source": "RATE_OFFICIAL_ROLLING_TECHNICAL_DERIVATION",
            "provider": "TWSE/TPEx Official Historical Market Data",
            "dataset_id": "rate_official_rolling_technical_features",
            "domain": "market_daily",
            "status": "BLOCKED",
            "normalization_status": "FAIL",
            "normalized_records": [],
            "normalized_count": 0,
            "effective_date": trading_date,
            "retrieval_timestamp": utc_now(),
            "parser_version": "RATE-OFFICIAL-ROLLING-TECHNICAL-V1",
            "required": True,
            "blocking_reason": str(exc),
        })
    freshness_evaluation_timestamp = utc_now()
    freshness_matrix = build_freshness_matrix(trading_date=trading_date, cadence=cadence, normalized_sources=normalized_sources, retrieval_timestamp=freshness_evaluation_timestamp)
    freshness_matrix["acquisition_started_at"] = acquisition_started_at
    try:
        external_block = cadence_blocking_reason(cadence)
        if external_block:
            raise RuntimeError(external_block)
        if not _required_source_status_pass(normalized_sources, cadence):
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
        "acquisition_started_at": acquisition_started_at,
        "freshness_evaluated_at": freshness_evaluation_timestamp,
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
        "source_registry_path": str(source_registry or (DEFAULT_SOURCE_REGISTRY_PATH if not rate_source_url else "")).replace("\\", "/") or None,
        "source_registry_entries": [{k: v for k, v in entry.items() if k != "endpoint"} for entry in registry_entries],
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
    parser.add_argument("--source-registry", default=os.getenv("RATE_SOURCE_REGISTRY_PATH", str(DEFAULT_SOURCE_REGISTRY_PATH)))
    parser.add_argument("--output", required=True)
    parser.add_argument("--evidence-output", required=True)
    parser.add_argument("--requirement-matrix-output", default=None)
    parser.add_argument("--universe-contract", default=None)
    parser.add_argument("--universe-binding-output", default=None)
    parser.add_argument("--freshness-matrix-output", default=None)
    parser.add_argument("--feature-input-contract-output", default=None)
    parser.add_argument("--public-official-partial", action="store_true")
    args = parser.parse_args()
    evidence = build_bundle(rate_source_url=args.rate_source_url, trading_date=args.trading_date, cadence=args.cadence, output=args.output, evidence_output=args.evidence_output, requirement_matrix_output=args.requirement_matrix_output, universe_contract=args.universe_contract, universe_binding_output=args.universe_binding_output, freshness_matrix_output=args.freshness_matrix_output, feature_input_contract_output=args.feature_input_contract_output, source_registry=args.source_registry, public_official_partial=args.public_official_partial)
    print(json.dumps(evidence, ensure_ascii=False, sort_keys=True))
    return 0 if evidence["validation_status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
