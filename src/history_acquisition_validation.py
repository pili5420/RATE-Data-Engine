"""Strict, opt-in historical response boundary; existing numeric owners unchanged."""
from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
import json
import math
import re

from .eps_duration_facts.model import require
from .provider_eps_metadata import _object, _constant, _finite
from .session_discovery_execution import session_date, stamp
from .historical_store import normalize_stock_record
from .benchmark_history import normalize_benchmark
from scripts.bootstrap_tpex_history import extract_symbol_month_rows

MISSING = {"", "-", "--", "---"}
FIELDS = {
    "date": ("Date", "日期", "trade_date", "交易日期"),
    "open": ("OpeningPrice", "Open", "開盤價", "開盤", "open"),
    "high": ("HighestPrice", "High", "最高價", "最高", "high"),
    "low": ("LowestPrice", "Low", "最低價", "最低", "low"),
    "close": ("ClosingPrice", "Close", "收盤價", "收盤", "close"),
    "volume": ("TradeVolume", "TradingShares", "Trade unit", "成交股數", "成交量", "volume"),
    "turnover": ("TradeValue", "TransactionAmount", "Trade Amt.(NTD1000)", "成交金額", "turnover"),
}
BENCHMARK_CLOSE = ("close", "ClosingIndex", "Close", "收盤指數", "收盤", "收市")


def numeric(value):
    require(type(value) in (str, int, float), "HISTORY_NUMERIC_INVALID")
    text = str(value).strip()
    if "," in text:
        require(re.fullmatch(r"[+-]?\d{1,3}(?:,\d{3})+(?:\.\d+)?", text), "HISTORY_NUMERIC_INVALID")
        text = text.replace(",", "")
    try:
        number = Decimal(text)
    except InvalidOperation:
        require(False, "HISTORY_NUMERIC_INVALID")
    require(number.is_finite() and math.isfinite(float(number)), "HISTORY_NUMERIC_INVALID")
    return number


def missing(value):
    return value is None or isinstance(value, str) and value.strip() in MISSING


def field(row, names, *, dates=False):
    present = [(key, row[key]) for key in names if key in row]
    require(present, "HISTORY_REQUIRED_FIELD_MISSING")
    values = [session_date(v) if dates else None if missing(v) else numeric(v) for _, v in present]
    require(all(value == values[0] for value in values), "HISTORY_FIELD_CONFLICT")
    return present[0][1], values[0], present[0][0]


def table(payload):
    require(isinstance(payload, dict), "HISTORY_SCHEMA_INVALID")
    if "tables" in payload:
        require(isinstance(payload["tables"], list) and len(payload["tables"]) == 1
                and isinstance(payload["tables"][0], dict), "HISTORY_SCHEMA_INVALID")
        selected, prefix = payload["tables"][0], "$.tables[0]"
    else:
        selected, prefix = payload, "$"
    fields, data = selected.get("fields"), selected.get("data")
    require(isinstance(fields, list) and fields and all(isinstance(f, str) and f for f in fields)
            and len(fields) == len(set(fields)) and isinstance(data, list), "HISTORY_SCHEMA_INVALID")
    rows = []
    for n, values in enumerate(data):
        require(isinstance(values, list) and len(values) == len(fields), "HISTORY_ROW_WIDTH_INVALID")
        rows.append((dict(zip(fields, values)), f"{prefix}.data[{n}]", n))
    return rows, selected, fields


def identity(payload, selected, entry):
    if "market" in payload:
        require(payload["market"] == entry["market"], "HISTORY_MARKET_MISMATCH")
    if "product" in payload:
        require(payload["product"] == entry["product"], "HISTORY_PRODUCT_MISMATCH")
    if "period" in payload:
        require(payload["period"] == entry["period"], "HISTORY_PERIOD_MISMATCH")
    if entry["product"] == "stock":
        supplied = [str(payload[key]) for key in ("code", "stockNo", "symbol") if key in payload]
        supplied += [str(selected[key]) for key in ("code", "stockNo", "symbol") if key in selected and selected is not payload]
        require(all(s == entry["symbol"] for s in supplied), "HISTORY_SYMBOL_MISMATCH")
        if not supplied:
            # Existing TPEx owner uses subtitle identity. Make token boundaries exact.
            subtitle = selected.get("subtitle") if entry["market"] == "TPEX" else None
            require(isinstance(subtitle, str) and re.search(r"(?<![A-Za-z0-9])" + re.escape(entry["symbol"]) + r"(?![A-Za-z0-9])", subtitle),
                    "HISTORY_SYMBOL_IDENTITY_REQUIRED")
    else:
        require(not any(k in payload or k in selected for k in ("code", "stockNo", "symbol", "SecuritiesCompanyCode")),
                "HISTORY_PRODUCT_MISMATCH")
        if "benchmark_symbol" in payload:
            require(payload["benchmark_symbol"] == ("TAIEX" if entry["market"] == "TWSE" else "TPEX"), "HISTORY_PRODUCT_MISMATCH")


def parse_history(raw, entry, *, observed_at, cutoff):
    try:
        payload = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_object, parse_constant=_constant)
        _finite(payload)
    except (ValueError, UnicodeError) as exc:
        raise ValueError("HISTORY_JSON_INVALID") from exc
    require(isinstance(payload, dict) and payload.get("stat", "OK") in ("OK", "ok"), "HISTORY_SCHEMA_INVALID")
    rows, selected, fields = table(payload)
    identity(payload, selected, entry)
    require(rows, "HISTORY_EMPTY_PERIOD_UNQUALIFIED")
    observed = stamp(observed_at)
    from zoneinfo import ZoneInfo
    local = observed.astimezone(ZoneInfo("Asia/Taipei"))
    cutoff_date = date.fromisoformat(cutoff)
    require(cutoff_date <= local.date(), "HISTORY_FUTURE_CUTOFF")
    seen, records, normalized = set(), [], []
    for row, locator, index in rows:
        for key in ("market", "product", "period"):
            if key in row:
                require(row[key] == entry[key], "HISTORY_ROW_" + key.upper() + "_MISMATCH")
        if entry["product"] == "benchmark" and "benchmark_symbol" in row:
            require(row["benchmark_symbol"] == ("TAIEX" if entry["market"] == "TWSE" else "TPEX"), "HISTORY_PRODUCT_MISMATCH")
        try:
            _, day, _ = field(row, FIELDS["date"], dates=True)
            actual = date.fromisoformat(day)
        except (ValueError, TypeError) as exc:
            raise ValueError("HISTORY_DATE_INVALID") from exc
        require(day[:7].replace("-", "") == entry["period"], "HISTORY_PERIOD_MISMATCH")
        require(day not in seen, "HISTORY_DUPLICATE_SESSION")
        seen.add(day)
        require(actual <= local.date(), "HISTORY_FUTURE_SESSION")
        require(actual != local.date() or local.hour * 60 + local.minute >= 810, "HISTORY_PRECLOSE_SESSION")
        item = {"trade_date": day, "raw_row_index": index, "json_locator": locator, "raw_fields": row,
                "status": "VALID", "reason": None, "normalized": None}
        if entry["product"] == "benchmark":
            require(not any(key in row for key in ("Code", "SecuritiesCompanyCode", "stockNo")), "HISTORY_PRODUCT_MISMATCH")
            raw_close, close, _ = field(row, BENCHMARK_CLOSE)
            require(close is not None and close > 0, "HISTORY_BENCHMARK_CLOSE_INVALID")
            canonical = normalize_benchmark({"Date": day, "close": str(close)}, benchmark_symbol="TAIEX" if entry["market"] == "TWSE" else "TPEX",
                market=entry["market"], source=entry["source_id"], source_timestamp=observed_at, ingested_at=observed_at)
        else:
            for key in ("Code", "SecuritiesCompanyCode", "symbol", "stockNo"):
                if key in row:
                    require(str(row[key]) == entry["symbol"], "HISTORY_SYMBOL_MISMATCH")
            values = {key: field(row, FIELDS[key])[1] for key in ("open", "high", "low", "close", "volume", "turnover")}
            require(all(v is None or v > 0 for k, v in values.items() if k in ("open", "high", "low", "close"))
                    and all(v is None or v >= 0 for k, v in values.items() if k in ("volume", "turnover")), "HISTORY_NUMERIC_RANGE_INVALID")
            if any(value is None for value in values.values()):
                item.update(status="MISSING", reason="OFFICIAL_CLOSE_NOT_REPORTED" if values["close"] is None else "OFFICIAL_VALUE_NOT_REPORTED")
                canonical = None
            else:
                require(all(values[key] > 0 for key in ("open", "high", "low", "close")) and values["volume"] >= 0 and values["turnover"] >= 0,
                        "HISTORY_NUMERIC_RANGE_INVALID")
                require(values["low"] <= min(values["open"], values["close"]) <= max(values["open"], values["close"]) <= values["high"], "HISTORY_OHLC_INVALID")
                if entry["market"] == "TWSE":
                    canonical = normalize_stock_record({"symbol": entry["symbol"], "market": "TWSE", "trade_date": day,
                        **{key: str(value) for key, value in values.items()}}, source=entry["source_id"], source_timestamp=observed_at, ingested_at=observed_at)
                else:
                    # Every row is validated first. Never use the legacy helper's silent-drop path.
                    copy_row = {key: str(value) if type(value) in (int, float) else value for key, value in row.items()}
                    response = {"raw_payload": {"code": entry["symbol"], "tables": [{"fields": fields, "data": [[copy_row[k] for k in fields]]}]},
                                "source_timestamp": observed_at, "retrieval_timestamp": observed_at}
                    converted = extract_symbol_month_rows(response, entry["symbol"], entry["period"])
                    require(len(converted) == 1, "HISTORY_NORMALIZER_ROW_LOSS")
                    canonical = converted[0]
                require(all(math.isfinite(canonical[key]) for key in values), "HISTORY_NONFINITE_NORMALIZED")
        if actual > cutoff_date:
            item.update(status="OUT_OF_SCOPE", reason="AFTER_FIXED_SOURCE_NATIVE_CUTOFF")
        elif canonical is not None:
            item["normalized"] = canonical
            normalized.append(canonical)
        records.append(item)
    require(len(records) == len(rows), "HISTORY_NORMALIZER_ROW_LOSS")
    unit = "TPEX_UNIT_SCALE_QUALIFICATION_REQUIRED" if entry["market"] == "TPEX" and entry["product"] == "stock" else "PASS"
    return {"source_validation": "PASS", "unit_scale_status": unit, "unit_scale_applied": False,
            "total_rows": len(rows), "valid_rows": sum(r["status"] == "VALID" for r in records),
            "missing_rows": sum(r["status"] == "MISSING" for r in records), "invalid_rows": 0,
            "out_of_scope_rows": sum(r["status"] == "OUT_OF_SCOPE" for r in records),
            "records": records, "normalized_sessions": normalized, "dates": sorted(r["trade_date"] for r in records if r["status"] != "OUT_OF_SCOPE")}


def benchmark_chains(events):
    chains = {market: [] for market in ("TWSE", "TPEX")}
    for event in events:
        if event["product"] != "benchmark":
            continue
        for row in event["validation"]["normalized_sessions"]:
            day = row["trade_date"]
            require(day not in chains[event["market"]], "HISTORY_DUPLICATE_BENCHMARK_SESSION")
            chains[event["market"]].append(day)
    return {market: {"sessions": sorted(days), "distinct_completed_sessions": len(days),
                    "latest_session": max(days) if days else None, "at_least_180": len(days) >= 180}
            for market, days in chains.items()}


def coverage_inventory(universe, events, cutoffs):
    chains = benchmark_chains(events)
    output = []
    stock_confirmed = {market: set() for market in chains}
    for event in events:
        if event["product"] == "stock":
            stock_confirmed[event["market"]].update(r["trade_date"] for r in event["validation"]["records"] if r["status"] == "VALID")
    for issuer in universe:
        symbol, market = issuer["symbol"], issuer["market"]
        required = chains[market]["sessions"][-180:]
        rows, unit = {}, "PASS"
        for event in events:
            if event["symbol"] != symbol or event["product"] != "stock":
                continue
            require(event["market"] == market, "HISTORY_MARKET_MISMATCH")
            unit = event["validation"]["unit_scale_status"]
            for record in event["validation"]["records"]:
                if record["status"] == "OUT_OF_SCOPE":
                    continue
                day = record["trade_date"]
                require(day not in rows, "HISTORY_DUPLICATE_STOCK_SESSION")
                rows[day] = record
        valid = sorted(day for day, row in rows.items() if row["status"] == "VALID")
        unconfirmed_dates = [day for day in valid if day not in chains[market]["sessions"]]
        missing_dates = [day for day in required if day not in valid]
        reasons = []
        if len(required) < 180 or chains[market]["latest_session"] != cutoffs[market]:
            reasons.append("INSUFFICIENT_BENCHMARK_HISTORY")
        if not rows:
            reasons.append("PERIOD_MISSING")
        elif missing_dates:
            reasons.append("SESSION_GAP")
        if len(valid) < 180:
            reasons.append("INSUFFICIENT_HISTORY")
        if unconfirmed_dates:
            reasons.append("SESSION_NOT_IN_VERIFIED_BENCHMARK_CHAIN")
        if unit != "PASS":
            reasons.append(unit)
        output.append({**issuer, "status": "NOT_READY" if reasons else "READY", "reasons": reasons,
                       "valid_sessions": valid, "partial_records": list(rows.values()), "missing_sessions": missing_dates,
                       "unconfirmed_sessions": unconfirmed_dates,
                       "unit_scale_status": unit, "ranking_eligible": False, "production_eligible": False})
    return {"issuers": output, "issuer_count": len(output), "ready": sum(r["status"] == "READY" for r in output),
            "not_ready": sum(r["status"] == "NOT_READY" for r in output), "benchmark_chains": chains,
            "calendar_180_ready": all(c["at_least_180"] and c["latest_session"] == cutoffs[m]
                and set(c["sessions"][-180:]).issubset(stock_confirmed[m])
                and stock_confirmed[m].issubset(c["sessions"]) for m, c in chains.items()),
            "source_native_cutoffs": cutoffs, "no_fill": True, "no_silent_issuer_drop": True}
