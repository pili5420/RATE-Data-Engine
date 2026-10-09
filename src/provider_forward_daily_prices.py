"""Opt-in immutable market-wide archive. No HTTP or changes to formal parsers."""
from datetime import date, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
import math
import json

from .eps_duration_facts.model import require, Rejected
from .eps_duration_facts.raw import sha256
from .provider_eps_candidate import _time
from .provider_eps_metadata import read_metadata
from .provider_eps_metadata import _object, _constant, _finite
from .provider_financial_features import instant
from .provider_shadow_forward import number, validate_baseline, hash_object
from .provider_shadow_forward_prices import (verified_bytes, endpoint_ok, ArchivedAdapter, periods_between)
from .sources.tpex import CURRENT_DAILY_ENDPOINT, normalize_tpex_date
from .sources.twse import BASE as TWSE_BASE
from .benchmark_history import normalize_twse_date
from scripts.build_production_source_bundle_from_official import _rows, _number, _symbol
from scripts.materialize_production_history_store import _benchmark_month_rows

MODE = "OFFICIAL_MARKET_DAILY_FORWARD_INPUT_V1"
KIND = "RATE_OFFICIAL_FORWARD_PRICE_ARCHIVE_MANIFEST_V1"
DAILY = {"TWSE": TWSE_BASE + "/exchangeReport/STOCK_DAY_ALL", "TPEX": CURRENT_DAILY_ENDPOINT}
TAIPEI = timezone(timedelta(hours=8))


def read_payload(body):
    value = json.loads(body, object_pairs_hook=_object, parse_constant=_constant)
    _finite(value)
    require(isinstance(value, (dict, list)), "DAILY_JSON_CONTAINER_REQUIRED")
    return value


def close_at(day):
    date.fromisoformat(day)
    return day + "T13:30:00+08:00"


def post_close(day, observed_at, as_of):
    require(_time(close_at(day)) <= _time(observed_at) <= _time(as_of) <= _time(instant()), "DAILY_PRE_CLOSE_OR_FUTURE_OBSERVATION")


def daily_rows(payload, market):
    require(market in DAILY and isinstance(payload, list) and payload, "DAILY_MARKET_SCHEMA_MISMATCH")
    output, seen, dates = [], set(), set()
    for index, raw in enumerate(payload):
        require(isinstance(raw, dict), "DAILY_MARKET_SCHEMA_MISMATCH")
        # The existing parser can default a date. This bridge requires raw identity first.
        close_fields = ("ClosingPrice",) if market == "TWSE" else ("ClosingPrice", "Close")
        require("Date" in raw and ("Code" if market == "TWSE" else "SecuritiesCompanyCode") in raw and
            any(k in raw for k in close_fields), "DAILY_MARKET_SCHEMA_MISMATCH")
        day = (normalize_twse_date if market == "TWSE" else normalize_tpex_date)(raw["Date"])
        symbol = str(raw["Code"] if market == "TWSE" else raw["SecuritiesCompanyCode"]).strip()
        require(symbol and symbol not in seen, "DAILY_DUPLICATE_OR_CONFLICTING_SYMBOL")
        seen.add(symbol)
        dates.add(day)
        value = next(raw[k] for k in close_fields if k in raw)
        require(all(str(raw[k]) == str(value) for k in close_fields if k in raw), "DAILY_CONFLICTING_CLOSE_FIELDS")
        if value in (None, "", "-", "--", "---"):
            output.append({"symbol": symbol, "day": day, "close": None,
                "reason": "OFFICIAL_CLOSE_NOT_REPORTED", "raw_row_index": index, "json_locator": f"$[{index}]"})
            continue
        require(not isinstance(value, bool), "DAILY_INVALID_PRICE")
        decimal = number(str(value).replace(",", ""))
        require(decimal > 0, "DAILY_NONPOSITIVE_PRICE")
        normalized_close = _number(value)
        require(_symbol(symbol) == symbol and math.isfinite(normalized_close) and normalized_close > 0 and
            number(str(normalized_close)) == decimal, "DAILY_FORMAL_PARSER_PRICE_MISMATCH")
        output.append({"symbol": symbol, "day": day, "close": str(normalized_close),
            "raw_close": value, "raw_row_index": index, "json_locator": f"$[{index}]"})
    require(len(dates) == 1, "DAILY_MIXED_OR_WRONG_DATE")
    return next(iter(dates)), output


def source(receipt_pin, *, as_of):
    receipt = read_metadata(verified_bytes(receipt_pin["receipt_path"], receipt_pin["receipt_sha256"]))
    require(receipt["market"] in DAILY and receipt["http_status"] == 200 and receipt["final_url"] == receipt["endpoint"] and
        _time(receipt["observed_at"]) <= _time(receipt["source_validated_at"]) <= _time(as_of),
        "DAILY_HTTP_RECEIPT_OR_TIME_MISMATCH")
    body = verified_bytes(receipt["raw_path"], receipt["raw_sha256"])
    require(len(body) == receipt["bytes"], "DAILY_BYTE_COUNT_MISMATCH")
    return receipt, read_payload(body)


def reference(pin, receipt, *, day, symbol=None, index=None, locator=None):
    return {"raw_path": receipt["raw_path"], "raw_sha256": receipt["raw_sha256"],
        "receipt_path": pin["receipt_path"], "receipt_sha256": pin["receipt_sha256"],
        "symbol": symbol, "date": day, "market": receipt["market"], "endpoint": receipt["endpoint"],
        "price_source": receipt["market"] + "_OFFICIAL_MARKET_DAILY",
        "observed_at": receipt["observed_at"], "source_validated_at": receipt["source_validated_at"],
        "raw_row_index": index, "json_locator": locator}


def _benchmark_locations(payload):
    containers = [(f"$.tables[{i}]", table) for i, table in enumerate(payload["tables"])
        if isinstance(table, dict)] if isinstance(payload.get("tables"), list) else [("$", payload)]
    locations = []
    for prefix, container in containers:
        for key in ("records", "data", "decision_input_records", "normalized_records", "rows"):
            if isinstance(container.get(key), list):
                fields = container.get("fields")
                if isinstance(fields, list):
                    require(all(isinstance(f, str) for f in fields) and len(set(fields)) == len(fields),
                        "DAILY_BENCHMARK_SCHEMA_MISMATCH")
                for i, row in enumerate(container[key]):
                    if isinstance(row, dict) or isinstance(row, list) and isinstance(fields, list):
                        locations.append((f"{prefix}.{key}[{i}]", fields if isinstance(row, list) else None))
                break
    return locations


def _benchmark_close(raw, aliases):
    present = [field for field in aliases if field in raw]
    require(present, "DAILY_BENCHMARK_CLOSE_FIELD_MISSING")
    values = []
    for field in present:
        require(not isinstance(raw[field], bool), "DAILY_BENCHMARK_CLOSE_INVALID")
        try:
            value = Decimal(str(raw[field]).replace(",", ""))
            require(value.is_finite() and value > 0 and math.isfinite(float(value)) and float(value) > 0,
                "DAILY_BENCHMARK_CLOSE_INVALID")
        except (InvalidOperation, OverflowError, TypeError, ValueError) as error:
            raise Rejected("DAILY_BENCHMARK_CLOSE_INVALID") from error
        values.append(value)
    require(all(value == values[0] for value in values), "DAILY_BENCHMARK_CLOSE_FIELD_CONFLICT")
    return present, values[0]


def benchmark_rows(receipt, payload, through, as_of):
    market, period = receipt["market"], receipt["period"]
    endpoint_ok(receipt)
    raw_rows = _rows(payload)
    require(isinstance(payload, dict) and (raw_rows or payload.get("data") == [] or payload.get("tables") == []), "DAILY_BENCHMARK_SCHEMA_MISMATCH")
    locations = _benchmark_locations(payload)
    require(len(locations) == len(raw_rows), "DAILY_BENCHMARK_SCHEMA_MISMATCH")
    aliases = ("ClosingIndex", "收盤指數", "close")
    if market == "TPEX":
        aliases = ("收市", *aliases)
    seen, normalized, mappings = set(), [], {}
    for index, raw in enumerate(raw_rows):
        day = (normalize_twse_date if market == "TWSE" else normalize_tpex_date)(raw.get("Date") or raw.get("日期") or raw.get("trade_date"))
        present, value = _benchmark_close(raw, aliases)
        require(day.replace("-", "")[:6] == period and day not in seen,
            "DAILY_BENCHMARK_SESSION_IDENTITY")
        seen.add(day)
        post_close(day, receipt["observed_at"], as_of)
        locator, fields = locations[index]
        evidence = [{"original_field": field, "raw_value": raw[field],
            "json_locator": locator + (f"[{fields.index(field)}]" if fields is not None else "[" + json.dumps(field, ensure_ascii=False) + "]")}
            for field in present]
        mappings[day] = {**evidence[0], "canonical_field": "close", "raw_row_index": index,
            "trade_date": day, "mapping_rule": "BENCHMARK_EXACT_CLOSE_ALIASES_V1", "alias_evidence": evidence}
        # Separate in-memory payload for the unchanged helper; never mutate archived bytes.
        normalized.append({**raw, "close": str(value)})
    rows = _benchmark_month_rows(ArchivedAdapter(receipt, {"data": normalized}), market, period, (date.fromisoformat(through) + timedelta(days=1)).isoformat())
    require({row["trade_date"] for row in rows} == {day for day in seen if day <= through}, "DAILY_BENCHMARK_PARSER_ROW_LOSS")
    for row in rows:
        row["close_compatibility"] = mappings[row["trade_date"]]
    return rows


def load_daily_prices(pin, manifest, *, as_of, available_at):
    require(manifest["artifact_kind"] == KIND and manifest["input_mode"] == MODE, "DAILY_MANIFEST_KIND")
    require(_time(available_at) <= _time(manifest["generated_at"]) <= _time(as_of) <= _time(instant()), "DAILY_MANIFEST_TIME_INVALID")
    baseline = read_metadata(verified_bytes(manifest["baseline_pin"]["path"], manifest["baseline_pin"]["sha256"]))
    validate_baseline(baseline)
    require(baseline["shadow_snapshot_id"] == manifest["shadow_snapshot_id"] and baseline["forward_available_at"] == available_at,
        "DAILY_BASELINE_BINDING_MISMATCH")
    companies = [{"symbol": r["symbol"], "market": r["market"]} for r in baseline["companies"]]
    require(manifest["universe"] == companies and manifest["universe_id"] == baseline["universe_id"], "DAILY_UNIVERSE_MISMATCH")
    for identity in manifest["source_identities"]:
        verified_bytes(identity["path"], identity["sha256"])
    through = manifest["sessions_complete_through"]
    start = _time(available_at).astimezone(TAIPEI).date().isoformat()
    require(start <= through <= _time(as_of).astimezone(TAIPEI).date().isoformat() and
        _time(close_at(through)) <= _time(as_of), "DAILY_COVERAGE_BEFORE_CLOSE_OR_FUTURE")
    months = set(periods_between(start, through))
    sessions, daily, benchmarks = {m: {} for m in DAILY}, {}, {m: set() for m in DAILY}
    benchmark_pins, daily_pins = {}, {}
    for item in manifest["sources"]:
        receipt, payload = source(item, as_of=as_of)
        market = receipt["market"]
        require(_time(close_at(through)) <= _time(receipt["observed_at"]) or receipt["domain"] == "market_daily",
            "DAILY_SESSION_CHAIN_NOT_OBSERVED_THROUGH")
        if receipt["domain"] == "benchmark":
            endpoint_ok(receipt)
            period = receipt["period"]
            require(period in months and period not in benchmarks[market], "DAILY_DUPLICATE_BENCHMARK_OR_WRONG_MONTH")
            benchmarks[market].add(period)
            rows = benchmark_rows(receipt, payload, through, as_of)
            for i, row in enumerate(rows):
                day = row["trade_date"]
                if _time(close_at(day)) <= _time(available_at):
                    continue
                require(day not in sessions[market], "DAILY_DUPLICATE_SESSION")
                ref = reference(item, receipt, day=day, index=i, locator={"normalized_benchmark_row": i})
                ref["close_compatibility"] = row["close_compatibility"]
                sessions[market][day] = {"date": day, "close_at": close_at(day), "reference": ref}
                benchmark_pins[(market, day)] = item
        else:
            require(receipt["domain"] == "market_daily" and receipt["endpoint"] == DAILY[market] and
                receipt["request_method"] == "GET" and not receipt["request_params"], "DAILY_EXISTING_MARKET_PRODUCT_REQUIRED")
            day, rows = daily_rows(payload, market)
            post_close(day, receipt["observed_at"], as_of)
            require(day <= through and (market, day) not in daily, "DAILY_WRONG_DATE_OR_DUPLICATE_SNAPSHOT")
            daily[(market, day)] = rows
            daily_pins[(market, day)] = (item, receipt)
    require(all(benchmarks[m] == months for m in DAILY), "DAILY_BENCHMARK_MONTH_GAP")
    prices, coverage, calendar = {}, [], []
    market_of = {r["symbol"]: r["market"] for r in companies}
    cursor = date.fromisoformat(start)
    while cursor <= date.fromisoformat(through):
        day = cursor.isoformat()
        for market in DAILY:
            if _time(close_at(day)) <= _time(available_at):
                continue
            confirmed = day in sessions[market]
            market_rows = daily.get((market, day))
            if confirmed:
                require(market_rows is not None, "DAILY_REQUIRED_SESSION_MARKET_EVIDENCE_GAP:" + market + ":" + day)
            elif market_rows is not None:
                raise ValueError("DAILY_SESSION_IDENTITY_MISMATCH:" + market + ":" + day)
            else:
                # Joint absence is an observation, not proof of the reason (holiday/delay).
                diagnostic = [(d, daily_pins[(m, d)][0]) for (m, d) in daily if m == market and d < day]
                require(diagnostic, "DAILY_NO_SESSION_WITHOUT_MARKET_EVIDENCE")
                calendar.append({"market": market, "date": day, "status": "NO_SESSION_OBSERVED",
                    "reason": "BENCHMARK_ABSENT_AND_DAILY_PRODUCT_ONLY_PRIOR_DATE_NOT_HOLIDAY_PROOF",
                    "daily_evidence": max(diagnostic, key=lambda x: x[0])[1]})
                continue
            expected = sorted(s for s, m in market_of.items() if m == market)
            observed, valid, invalid = [], [], []
            item, receipt = daily_pins[(market, day)]
            for row in market_rows:
                symbol = row["symbol"]
                if symbol not in market_of:
                    continue
                require(market_of[symbol] == market, "DAILY_SYMBOL_MARKET_CONFLICT")
                observed.append(symbol)
                if row["close"] is None:
                    invalid.append({"symbol": symbol, "reason": row["reason"], "json_locator": row["json_locator"]})
                    continue
                valid.append(symbol)
                prices[(symbol, day)] = {"close": row["close"], "reference": reference(item, receipt,
                    day=day, symbol=symbol, index=row["raw_row_index"], locator=row["json_locator"])}
            coverage.append({"market": market, "trade_date": day, "status": "MARKET_SESSION_CONFIRMED",
                "expected_symbols": expected, "observed_symbols": sorted(observed), "valid_close_symbols": sorted(valid),
                "missing_symbols": sorted(set(expected) - set(observed)), "invalid_symbols": invalid,
                "market_receipt": item, "benchmark_receipt": benchmark_pins[(market, day)]})
            calendar.append({"market": market, "date": day, "status": "MARKET_SESSION_CONFIRMED"})
        cursor += timedelta(days=1)
    return {"pin": pin, "manifest_sha256": pin["manifest_sha256"], "input_mode": MODE,
        "sessions": {m: [v for _, v in sorted(s.items())] for m, s in sessions.items()},
        "prices": prices, "session_coverage": coverage, "calendar_observations": calendar,
        "calendar_reason_proven": False}
