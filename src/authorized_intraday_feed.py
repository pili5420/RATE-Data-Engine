"""Provider-neutral qualification for an already-authorized RATE intraday payload.

No network access, credential handling, provider selection, registry activation or
Production publication occurs here. The approved universe is rooted in the repository's
authoritative Production universe contract and validation-PASS immutable source bundle;
caller-supplied universe metadata is assertion-only and never establishes authority.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
UNIVERSE_CONTRACT_PATH = ROOT / "config" / "RATE_PRODUCTION_UNIVERSE_CONTRACT_V1.json"
PRODUCTION_LATEST_PATH = ROOT / "artifacts" / "RATE_PRODUCTION_SOURCE_BUNDLE_LATEST.json"
TAIPEI = timezone(timedelta(hours=8), name="Asia/Taipei")
CADENCES = {"09:30", "12:00"}
REQUIRED_FIELDS = ("symbol", "market", "timestamp", "price", "volume", "turnover")
ALLOWED_MARKETS = {"TWSE", "TPEX"}


class IntradayQualificationError(RuntimeError):
    pass


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise IntradayQualificationError(reason)


def _timestamp(value: Any) -> datetime:
    require(isinstance(value, str) and value.strip(), "INTRADAY_TIMESTAMP_MISSING")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise IntradayQualificationError("INTRADAY_TIMESTAMP_INVALID") from exc
    require(parsed.tzinfo is not None and parsed.utcoffset() is not None, "INTRADAY_TIMESTAMP_TIMEZONE_REQUIRED")
    return parsed.astimezone(timezone.utc)


def _number(value: Any, *, positive: bool) -> float:
    require(not isinstance(value, bool) and isinstance(value, (int, float)), "INTRADAY_NUMERIC_INVALID")
    number = float(value)
    require(math.isfinite(number), "INTRADAY_NUMERIC_INVALID")
    require(number > 0 if positive else number >= 0, "INTRADAY_NUMERIC_INVALID")
    return number


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_value(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _canonical_universe_sha256(universe: Mapping[str, str]) -> str:
    encoded = json.dumps(sorted(universe.items()), separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _sha256_text(value: Any, reason: str) -> str:
    require(isinstance(value, str), reason)
    normalized = value.strip().lower()
    require(len(normalized) == 64 and all(char in "0123456789abcdef" for char in normalized), reason)
    return normalized


def _load_json(path: Path, missing_reason: str, invalid_reason: str) -> Mapping[str, Any]:
    require(path.is_file(), missing_reason)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise IntradayQualificationError(invalid_reason) from exc
    require(isinstance(value, Mapping), invalid_reason)
    return value


def _authoritative_universe() -> tuple[dict[str, str], dict[str, str]]:
    contract = _load_json(
        UNIVERSE_CONTRACT_PATH,
        "INTRADAY_TRUSTED_UNIVERSE_CONTRACT_MISSING",
        "INTRADAY_TRUSTED_UNIVERSE_CONTRACT_INVALID",
    )
    require(contract.get("artifact") == "RATE_PRODUCTION_UNIVERSE_CONTRACT",
            "INTRADAY_TRUSTED_UNIVERSE_CONTRACT_INVALID")
    require(contract.get("contract_purpose") == "PRODUCTION_SOURCE_ACQUISITION_BINDING",
            "INTRADAY_TRUSTED_UNIVERSE_CONTRACT_INVALID")
    require(contract.get("validation_status") == "PASS",
            "INTRADAY_TRUSTED_UNIVERSE_CONTRACT_NOT_PASS")
    require(contract.get("required_count") == 30,
            "INTRADAY_TRUSTED_UNIVERSE_CONTRACT_COUNT_INVALID")
    require(contract.get("post_rebaseline_fallback_allowed") is False,
            "INTRADAY_TRUSTED_UNIVERSE_FALLBACK_FORBIDDEN")
    approved = contract.get("approved_universe")
    require(isinstance(approved, list) and len(approved) == 30,
            "INTRADAY_TRUSTED_UNIVERSE_CONTRACT_COUNT_INVALID")
    require(all(isinstance(symbol, str) and symbol and symbol == symbol.strip() for symbol in approved),
            "INTRADAY_TRUSTED_UNIVERSE_SYMBOL_INVALID")
    require(len(set(approved)) == 30, "INTRADAY_TRUSTED_UNIVERSE_DUPLICATE")
    contract_sha256 = _sha256_value(contract)

    latest = _load_json(
        PRODUCTION_LATEST_PATH,
        "INTRADAY_PRODUCTION_LATEST_MISSING",
        "INTRADAY_PRODUCTION_LATEST_INVALID",
    )
    require(latest.get("artifact") == "RATE_PRODUCTION_SOURCE_BUNDLE_LATEST",
            "INTRADAY_PRODUCTION_LATEST_INVALID")
    require(latest.get("validation_status") == "PASS",
            "INTRADAY_PRODUCTION_LATEST_NOT_PASS")
    snapshot_id = latest.get("production_snapshot_id")
    require(isinstance(snapshot_id, str) and snapshot_id.startswith("rate-source-snapshot-"),
            "INTRADAY_PRODUCTION_SNAPSHOT_INVALID")
    source_bundle_hash = _sha256_text(
        latest.get("source_bundle_hash"),
        "INTRADAY_PRODUCTION_SOURCE_BUNDLE_HASH_INVALID",
    )
    raw_bundle_path = latest.get("immutable_bundle_path")
    require(isinstance(raw_bundle_path, str) and raw_bundle_path,
            "INTRADAY_PRODUCTION_IMMUTABLE_BUNDLE_PATH_INVALID")
    relative = PurePosixPath(raw_bundle_path)
    require(not relative.is_absolute()
            and ".." not in relative.parts
            and relative.parts[:2] == ("artifacts", "production_source_snapshots")
            and relative.name == "RATE_PRODUCTION_SOURCE_BUNDLE.json",
            "INTRADAY_PRODUCTION_IMMUTABLE_BUNDLE_PATH_INVALID")
    require(snapshot_id in relative.parts,
            "INTRADAY_PRODUCTION_IMMUTABLE_BUNDLE_SNAPSHOT_MISMATCH")
    bundle_path = ROOT.joinpath(*relative.parts)

    bundle = _load_json(
        bundle_path,
        "INTRADAY_PRODUCTION_IMMUTABLE_BUNDLE_MISSING",
        "INTRADAY_PRODUCTION_IMMUTABLE_BUNDLE_INVALID",
    )
    require(bundle.get("artifact") == "RATE_PRODUCTION_SOURCE_BUNDLE",
            "INTRADAY_PRODUCTION_IMMUTABLE_BUNDLE_INVALID")
    require(bundle.get("validation_status") == "PASS"
            and bundle.get("source_status") == "PASS"
            and bundle.get("source_bundle_validation") == "PASS",
            "INTRADAY_PRODUCTION_IMMUTABLE_BUNDLE_NOT_PASS")
    require(bundle.get("production_snapshot_id") == snapshot_id
            and bundle.get("snapshot_id") == snapshot_id,
            "INTRADAY_PRODUCTION_IMMUTABLE_BUNDLE_SNAPSHOT_MISMATCH")
    require(_sha256_value(bundle) == source_bundle_hash,
            "INTRADAY_PRODUCTION_SOURCE_BUNDLE_HASH_MISMATCH")

    binding = bundle.get("universe_binding")
    require(isinstance(binding, Mapping), "INTRADAY_PRODUCTION_UNIVERSE_BINDING_INVALID")
    require(binding.get("artifact") == "RATE_PRODUCTION_UNIVERSE_BINDING"
            and binding.get("validation_status") == "PASS"
            and binding.get("production_authoritative") is True
            and binding.get("binding_mode") == "AUTHORITATIVE_CONTRACT_EXACT_30"
            and binding.get("approved_universe_count") == 30
            and binding.get("blocking_reason") is None,
            "INTRADAY_PRODUCTION_UNIVERSE_BINDING_NOT_AUTHORITATIVE")
    require(binding.get("expected_universe") == approved,
            "INTRADAY_PRODUCTION_UNIVERSE_CONTRACT_MISMATCH")
    require(binding.get("contract_sha256") == contract_sha256,
            "INTRADAY_PRODUCTION_UNIVERSE_CONTRACT_HASH_MISMATCH")
    binding_hash = _sha256_value({"expected_universe": approved, "contract_sha256": contract_sha256})
    require(binding.get("universe_binding_hash") == binding_hash,
            "INTRADAY_PRODUCTION_UNIVERSE_BINDING_HASH_MISMATCH")
    require(binding.get("missing_symbols") == []
            and binding.get("duplicate_symbols") == []
            and binding.get("invalid_market_symbols") == []
            and binding.get("unapproved_symbols") == [],
            "INTRADAY_PRODUCTION_UNIVERSE_BINDING_DEFECT")
    require(bundle.get("universe") == approved and bundle.get("short_term_top30") == approved,
            "INTRADAY_PRODUCTION_UNIVERSE_LIST_MISMATCH")

    records = bundle.get("records")
    require(isinstance(records, list) and len(records) == 30,
            "INTRADAY_PRODUCTION_RECORD_UNIVERSE_COUNT_INVALID")
    trusted: dict[str, str] = {}
    for row in records:
        require(isinstance(row, Mapping), "INTRADAY_PRODUCTION_RECORD_INVALID")
        symbol = row.get("symbol")
        stage = row.get("Stage_inputs")
        require(isinstance(symbol, str) and symbol and symbol == symbol.strip()
                and isinstance(stage, Mapping),
                "INTRADAY_PRODUCTION_RECORD_IDENTITY_INVALID")
        market = stage.get("listed_market")
        require(isinstance(market, str) and market in ALLOWED_MARKETS,
                "INTRADAY_PRODUCTION_RECORD_MARKET_INVALID")
        require(symbol not in trusted, "INTRADAY_PRODUCTION_RECORD_DUPLICATE:" + symbol)
        trusted[symbol] = market

    require(list(trusted) == approved, "INTRADAY_PRODUCTION_RECORD_UNIVERSE_MISMATCH")
    require(set(trusted.values()) == ALLOWED_MARKETS, "INTRADAY_DUAL_MARKET_COVERAGE_REQUIRED")

    return trusted, {
        "source_kind": "RATE_PRODUCTION_SOURCE_BUNDLE",
        "production_snapshot_id": snapshot_id,
        "source_bundle_sha256": source_bundle_hash,
        "universe_sha256": _canonical_universe_sha256(trusted),
        "universe_contract_sha256": contract_sha256,
        "universe_binding_hash": binding_hash,
        "universe_contract_path": str(UNIVERSE_CONTRACT_PATH.relative_to(ROOT)).replace("\\", "/"),
        "production_latest_path": str(PRODUCTION_LATEST_PATH.relative_to(ROOT)).replace("\\", "/"),
        "immutable_bundle_path": raw_bundle_path,
    }


def load_authoritative_universe_binding() -> tuple[dict[str, str], dict[str, str]]:
    """Return a copy of the repository-rooted approved universe and its trusted lineage."""
    trusted, lineage = _authoritative_universe()
    return dict(trusted), dict(lineage)


def _expected_universe(
    expected_universe: Mapping[str, str],
    expected_universe_binding: Mapping[str, Any],
) -> tuple[dict[str, str], dict[str, str]]:
    require(isinstance(expected_universe, Mapping), "INTRADAY_EXPECTED_UNIVERSE_INVALID")
    raw_items = list(expected_universe.items())
    require(len(raw_items) == 30, "INTRADAY_EXPECTED_UNIVERSE_COUNT_INVALID")

    normalized: dict[str, str] = {}
    for raw_symbol, raw_market in raw_items:
        require(isinstance(raw_symbol, str) and raw_symbol, "INTRADAY_EXPECTED_SYMBOL_INVALID")
        require(isinstance(raw_market, str) and raw_market, "INTRADAY_EXPECTED_MARKET_INVALID")
        symbol = raw_symbol.strip()
        market = raw_market.strip().upper()
        require(symbol, "INTRADAY_EXPECTED_SYMBOL_INVALID")
        require(symbol not in normalized, "INTRADAY_EXPECTED_UNIVERSE_NORMALIZATION_COLLISION:" + symbol)
        require(raw_symbol == symbol, "INTRADAY_EXPECTED_SYMBOL_NONCANONICAL:" + symbol)
        require(raw_market == market, "INTRADAY_EXPECTED_MARKET_NONCANONICAL:" + symbol)
        require(market in ALLOWED_MARKETS, "INTRADAY_EXPECTED_MARKET_INVALID")
        normalized[symbol] = market
    require(set(normalized.values()) == ALLOWED_MARKETS, "INTRADAY_DUAL_MARKET_COVERAGE_REQUIRED")

    trusted, trusted_binding = _authoritative_universe()
    require(normalized == trusted, "INTRADAY_EXPECTED_UNIVERSE_NOT_APPROVED")

    require(isinstance(expected_universe_binding, Mapping), "INTRADAY_EXPECTED_UNIVERSE_BINDING_REQUIRED")
    require(expected_universe_binding.get("artifact") == "RATE_APPROVED_INTRADAY_UNIVERSE_BINDING_V1",
            "INTRADAY_EXPECTED_UNIVERSE_BINDING_ARTIFACT_INVALID")
    require(expected_universe_binding.get("source_kind") == "RATE_PRODUCTION_SOURCE_BUNDLE",
            "INTRADAY_EXPECTED_UNIVERSE_SOURCE_INVALID")
    require(expected_universe_binding.get("source_validation_status") == "PASS",
            "INTRADAY_EXPECTED_UNIVERSE_SOURCE_NOT_VALIDATED")
    for key, reason in (
        ("production_snapshot_id", "INTRADAY_EXPECTED_UNIVERSE_SNAPSHOT_MISMATCH"),
        ("source_bundle_sha256", "INTRADAY_EXPECTED_UNIVERSE_SOURCE_SHA256_MISMATCH"),
        ("universe_sha256", "INTRADAY_EXPECTED_UNIVERSE_SHA256_MISMATCH"),
        ("universe_contract_sha256", "INTRADAY_EXPECTED_UNIVERSE_CONTRACT_SHA256_MISMATCH"),
        ("universe_binding_hash", "INTRADAY_EXPECTED_UNIVERSE_BINDING_HASH_MISMATCH"),
    ):
        require(expected_universe_binding.get(key) == trusted_binding[key], reason)

    return normalized, trusted_binding


def qualify_authorized_intraday_payload(
    payload: Mapping[str, Any],
    *,
    expected_universe: Mapping[str, str],
    expected_universe_binding: Mapping[str, Any],
    trading_date: str,
    cadence: str,
    now_utc: datetime,
    max_age_seconds: int = 180,
) -> dict[str, Any]:
    require(cadence in CADENCES, "INTRADAY_CADENCE_INVALID")
    require(isinstance(max_age_seconds, int) and max_age_seconds > 0, "INTRADAY_FRESHNESS_LIMIT_INVALID")
    require(now_utc.tzinfo is not None and now_utc.utcoffset() is not None, "INTRADAY_NOW_TIMEZONE_REQUIRED")
    try:
        datetime.fromisoformat(trading_date)
    except ValueError as exc:
        raise IntradayQualificationError("INTRADAY_TRADING_DATE_INVALID") from exc

    expected, universe_binding = _expected_universe(expected_universe, expected_universe_binding)
    require(isinstance(payload, Mapping), "INTRADAY_PAYLOAD_INVALID")
    require(payload.get("artifact") == "RATE_AUTHORIZED_TAIWAN_INTRADAY_FEED_V1", "INTRADAY_ARTIFACT_INVALID")
    require(payload.get("authorization_status") == "PASS", "INTRADAY_AUTHORIZATION_NOT_PASS")
    require(payload.get("validation_status") == "PASS", "INTRADAY_PROVIDER_VALIDATION_NOT_PASS")
    require(payload.get("fallback_used") is False, "INTRADAY_FALLBACK_FORBIDDEN")
    require(payload.get("trading_date") == trading_date and payload.get("cadence") == cadence,
            "INTRADAY_SCOPE_BINDING_MISMATCH")
    require(isinstance(payload.get("provider_authority"), str) and payload["provider_authority"].strip(),
            "INTRADAY_PROVIDER_AUTHORITY_MISSING")

    license_scope = payload.get("license_scope")
    require(isinstance(license_scope, Mapping)
            and license_scope.get("automated_production_use") is True,
            "INTRADAY_AUTOMATED_USE_AUTHORITY_REQUIRED")
    license_markets = license_scope.get("markets")
    require(isinstance(license_markets, list)
            and all(isinstance(value, str) and value.strip() for value in license_markets),
            "INTRADAY_LICENSE_MARKETS_FORMAT_INVALID")
    licensed_markets = {value.strip().upper() for value in license_markets}
    require(licensed_markets.issubset(ALLOWED_MARKETS), "INTRADAY_LICENSE_MARKET_INVALID")
    require(ALLOWED_MARKETS.issubset(licensed_markets), "INTRADAY_LICENSE_MARKET_COVERAGE_INCOMPLETE")

    records = payload.get("records")
    require(isinstance(records, list) and records, "INTRADAY_RECORDS_MISSING")
    by_symbol: dict[str, dict[str, Any]] = {}
    duplicates: list[str] = []
    for row in records:
        require(isinstance(row, Mapping), "INTRADAY_ROW_NOT_OBJECT")
        missing = [field for field in REQUIRED_FIELDS if field not in row]
        require(not missing, "INTRADAY_ROW_SCHEMA_MISSING:" + ",".join(missing))
        symbol = str(row["symbol"]).strip()
        market = str(row["market"]).strip().upper()
        require(symbol and market in ALLOWED_MARKETS, "INTRADAY_ROW_IDENTITY_INVALID")
        if symbol in by_symbol:
            duplicates.append(symbol)
            continue
        stamp = _timestamp(row["timestamp"])
        require(stamp.astimezone(TAIPEI).date().isoformat() == trading_date,
                "INTRADAY_TIMESTAMP_TRADING_DATE_MISMATCH")
        age = (now_utc.astimezone(timezone.utc) - stamp).total_seconds()
        require(0 <= age <= max_age_seconds, "INTRADAY_FRESHNESS_FAIL")
        normalized = {
            "symbol": symbol,
            "market": market,
            "timestamp_utc": stamp.isoformat(),
            "age_seconds": age,
            "price": _number(row["price"], positive=True),
            "volume": _number(row["volume"], positive=False),
            "turnover": _number(row["turnover"], positive=False),
        }
        by_symbol[symbol] = normalized
    require(not duplicates, "INTRADAY_DUPLICATE_SYMBOL:" + ",".join(sorted(set(duplicates))))

    selected: dict[str, dict[str, Any]] = {}
    missing_symbols: list[str] = []
    market_mismatches: list[str] = []
    for symbol, expected_market in expected.items():
        row = by_symbol.get(symbol)
        if row is None:
            missing_symbols.append(symbol)
        elif row["market"] != expected_market:
            market_mismatches.append(symbol)
        else:
            selected[symbol] = row

    require(not missing_symbols, "INTRADAY_EXPECTED_SYMBOL_MISSING:" + ",".join(sorted(missing_symbols)))
    require(not market_mismatches, "INTRADAY_MARKET_BINDING_MISMATCH:" + ",".join(sorted(market_mismatches)))

    actual_market_counts = dict(Counter(row["market"] for row in selected.values()))
    expected_market_counts = dict(Counter(expected.values()))
    require(actual_market_counts == expected_market_counts, "INTRADAY_MARKET_COVERAGE_MISMATCH")

    extras = sorted(set(by_symbol) - set(expected))
    freshest = min(row["timestamp_utc"] for row in selected.values())
    oldest_age = max(row["age_seconds"] for row in selected.values())
    return {
        "artifact": "RATE_AUTHORIZED_TAIWAN_INTRADAY_PAYLOAD_QUALIFICATION_V1",
        "validation_status": "PASS",
        "authorization_status": "INPUT_ASSERTED_PASS_NOT_ACTIVATED_BY_THIS_MODULE",
        "provider_authority": payload["provider_authority"],
        "trading_date": trading_date,
        "cadence": cadence,
        "expected_count": len(expected),
        "expected_universe_source_kind": universe_binding["source_kind"],
        "expected_universe_production_snapshot_id": universe_binding["production_snapshot_id"],
        "expected_universe_source_bundle_sha256": universe_binding["source_bundle_sha256"],
        "expected_universe_sha256": universe_binding["universe_sha256"],
        "expected_universe_contract_sha256": universe_binding["universe_contract_sha256"],
        "expected_universe_binding_hash": universe_binding["universe_binding_hash"],
        "expected_universe_contract_path": universe_binding["universe_contract_path"],
        "expected_universe_latest_pointer_path": universe_binding["production_latest_path"],
        "expected_universe_immutable_bundle_path": universe_binding["immutable_bundle_path"],
        "selected_count": len(selected),
        "coverage": f"{len(selected)}/{len(expected)}",
        "expected_market_counts": expected_market_counts,
        "selected_market_counts": actual_market_counts,
        "required_markets": sorted(ALLOWED_MARKETS),
        "licensed_markets": sorted(licensed_markets),
        "extra_raw_symbols": extras,
        "extra_raw_symbol_policy": "ALLOWED_NOT_SELECTED",
        "oldest_age_seconds": oldest_age,
        "earliest_selected_timestamp_utc": freshest,
        "fallback_used": False,
        "network_requests": 0,
        "credential_access": 0,
        "provider_selected_by_module": False,
        "registry_activated": False,
        "production_eligible": False,
        "production_admission_status": "SEPARATE_CONTROL_CENTER_AND_REGISTRY_ACTIVATION_REQUIRED",
    }
