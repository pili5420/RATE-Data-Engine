"""Live-source normalization and acceptance helpers for CER-072."""
from __future__ import annotations

from datetime import date
import hashlib
import json
import math

from .benchmark_history import normalize_twse_date
from .sources.tpex import normalize_tpex_date

INSTITUTIONAL_HISTORY_MINIMUM = 26
TWSE_SYMBOLS = 25
TPEX_SYMBOLS = ("6274", "3081", "6187", "6510", "3227")
T86_OFFICIAL_SOURCE = "TWSE T86 date-aware official endpoint"
TPEX_OFFICIAL_SOURCE = "TPEx official Foreign & Institutional Investors Trading Detail daily dataset"
TPEX_PROBE_DATES = ("2026-09-18", "2026-09-17", "2026-08-14")


def canonical_digest(value) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _rows(payload):
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if not isinstance(payload, dict):
        return []
    data = payload.get("data") or payload.get("records") or payload.get("aaData") or []
    fields = payload.get("fields") or []
    if not data and payload.get("tables"):
        table = payload["tables"][0]
        if isinstance(table, dict):
            data = table.get("data") or table.get("records") or table.get("aaData") or []
            fields = table.get("fields") or fields
    if fields:
        return [dict(zip(fields, row)) if isinstance(row, (list, tuple)) else row
                for row in data if isinstance(row, (list, tuple, dict))]
    return [x for x in data if isinstance(x, dict)] if isinstance(data, list) else []


def _pick(row, *fields):
    for field in fields:
        value = row.get(field)
        if value not in (None, "", "-", "--"):
            return value
    return None


def _number(value, field):
    if value is None:
        raise ValueError(f"MISSING_REQUIRED_INSTITUTIONAL_FIELD:{field}")
    try:
        number = float(str(value).strip().replace(",", "").replace("(", "-").replace(")", ""))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"INVALID_INSTITUTIONAL_NUMBER:{field}") from exc
    if not math.isfinite(number):
        raise ValueError(f"INVALID_INSTITUTIONAL_NUMBER:{field}")
    return number


def valid_stock_session_dates(stock_histories, symbols, end_date=None, limit=26):
    """Return true common stock/benchmark sessions; reject duplicate or empty rows."""
    per_symbol = []
    for symbol in symbols:
        rows = stock_histories.get(symbol)
        if not isinstance(rows, list):
            raise ValueError(f"STOCK_HISTORY_MISSING:{symbol}")
        dates = set()
        for row in rows:
            day = str(row.get("trade_date", ""))
            if end_date and day > end_date:
                continue
            if not day or day in dates:
                raise ValueError(f"STOCK_SESSION_DUPLICATE_OR_INVALID:{symbol}:{day}")
            if row.get("close") is None or row.get("turnover") is None:
                continue
            dates.add(day)
        per_symbol.append(dates)
    common = sorted(set.intersection(*per_symbol)) if per_symbol else []
    if len(common) < limit:
        raise ValueError(f"DATA_INCOMPLETE:COMMON_STOCK_SESSIONS:{len(common)}<{limit}")
    return common[-limit:]


def normalize_t86_response(result, requested_date, stock_rows_by_symbol, required_symbols):
    """Validate official payload identity before binding records to the request date."""
    diagnostics = result.get("diagnostics") or {}
    if diagnostics.get("http_status") != 200:
        raise ValueError(f"T86_HTTP_STATUS:{diagnostics.get('http_status')}")
    payload = result.get("raw_payload")
    if not isinstance(payload, dict):
        raise ValueError("T86_RESPONSE_SCHEMA_INVALID")
    response_date = _pick(payload, "date", "dataDate", "資料日期", "交易日期")
    if response_date is None:
        raise ValueError("T86_RESPONSE_DATE_MISSING")
    try:
        response_date = normalize_twse_date(response_date)
    except Exception as exc:
        raise ValueError("T86_RESPONSE_DATE_INVALID") from exc
    if response_date != requested_date:
        raise ValueError("T86_RESPONSE_DATE_IDENTITY_MISMATCH")
    rows = _rows(payload)
    if not rows:
        raise ValueError("T86_EMPTY_TRADING_SESSION_RESPONSE")
    aliases = {
        "symbol": ("證券代號", "symbol"),
        "foreign_buy": ("外陸資買進股數(不含外資自營商)", "外陸資買進股數", "外資買進股數", "foreign_buy"),
        "foreign_sell": ("外陸資賣出股數(不含外資自營商)", "外陸資賣出股數", "外資賣出股數", "foreign_sell"),
        "foreign_net": ("外陸資買賣超股數(不含外資自營商)", "外陸資買賣超股數", "外資買賣超股數", "foreign_net"),
        "investment_trust_buy": ("投信買進股數", "investment_trust_buy"),
        "investment_trust_sell": ("投信賣出股數", "investment_trust_sell"),
        "investment_trust_net": ("投信買賣超股數", "investment_trust_net"),
    }
    by_symbol = {}
    for row in rows:
        symbol = str(_pick(row, *aliases["symbol"]) or "").strip()
        if symbol not in required_symbols:
            continue
        if symbol in by_symbol:
            raise ValueError(f"T86_DUPLICATE_SYMBOL_DATE:{symbol}:{requested_date}")
        item = {key: _number(_pick(row, *fields), key) for key, fields in aliases.items() if key != "symbol"}
        if item["foreign_buy"] - item["foreign_sell"] != item["foreign_net"]:
            raise ValueError(f"T86_FOREIGN_ARITHMETIC_MISMATCH:{symbol}:{requested_date}")
        if item["investment_trust_buy"] - item["investment_trust_sell"] != item["investment_trust_net"]:
            raise ValueError(f"T86_IT_ARITHMETIC_MISMATCH:{symbol}:{requested_date}")
        dealer = {}
        for out, own_label, hedge_label in (
            ("dealer_buy", "自營商買進股數(自行買賣)", "自營商買進股數(避險)"),
            ("dealer_sell", "自營商賣出股數(自行買賣)", "自營商賣出股數(避險)"),
            ("dealer_net", "自營商買賣超股數(自行買賣)", "自營商買賣超股數(避險)"),
        ):
            own, hedge = _pick(row, own_label), _pick(row, hedge_label)
            if own is not None and hedge is not None:
                dealer[out] = _number(own, out) + _number(hedge, out)
        stock = next((x for x in stock_rows_by_symbol[symbol] if x.get("trade_date") == requested_date), None)
        if stock is None:
            raise ValueError(f"INSTITUTIONAL_STOCK_DATE_MISMATCH:{symbol}:{requested_date}")
        item.update({"symbol": symbol, "trading_date": requested_date,
                     "close": _number(stock.get("close"), "close"),
                     "turnover": _number(stock.get("turnover"), "turnover"),
                     "source_timestamp": result.get("source_timestamp"),
                     "official_source": T86_OFFICIAL_SOURCE})
        item.update(dealer)
        by_symbol[symbol] = item
    missing = sorted(set(required_symbols) - set(by_symbol))
    if missing:
        raise ValueError("T86_REQUIRED_SYMBOLS_MISSING:" + ",".join(missing))
    return by_symbol


def fetch_t86_sessions(adapter, stock_rows_by_symbol, symbols, candidate_dates):
    """One market-wide T86 request per candidate stock date, never per symbol."""
    if len(candidate_dates) != len(set(candidate_dates)):
        raise ValueError("T86_DUPLICATE_CANDIDATE_TRADING_DATE")
    requests = 0
    valid = {s: [] for s in symbols}
    accepted_dates, empty_dates, identities = [], [], []
    for session in reversed(candidate_dates):
        result = adapter.fetch_t86(session)
        requests += 1
        try:
            mapped = normalize_t86_response(result, session, stock_rows_by_symbol, symbols)
        except ValueError as exc:
            if str(exc) == "T86_EMPTY_TRADING_SESSION_RESPONSE":
                empty_dates.append(session)
                continue
            raise
        for symbol in symbols:
            valid[symbol].append(mapped[symbol])
        accepted_dates.append(session)
        identities.append({"requested_date": session, "response_date": session,
                           "status": "PASS", "response_hash": result.get("content_hash"),
                           "record_count": len(_rows(result.get("raw_payload")))})
        if len(accepted_dates) >= INSTITUTIONAL_HISTORY_MINIMUM:
            break
    if len(accepted_dates) < INSTITUTIONAL_HISTORY_MINIMUM:
        raise ValueError(f"T86_VALID_SESSIONS_INSUFFICIENT:{len(accepted_dates)}<26")
    accepted_dates = sorted(accepted_dates)
    for symbol in symbols:
        valid[symbol].sort(key=lambda row: row["trading_date"])
    return {"records": valid, "session_dates": accepted_dates, "request_count": requests,
            "empty_nontrading_dates": empty_dates, "response_date_identity_status": "PASS",
            "daily_request_deduplication": "PASS", "identity_evidence": identities}


def fetch_tpex_monthly_history(adapter, symbols, stock_rows_by_symbol, candidate_dates):
    """Fetch each official YYYYMM dataset once and require explicit row dates."""
    months = sorted({day[:7].replace("-", "") for day in candidate_dates})
    payloads = {}
    request_count = 0
    for month in months:
        result = adapter.fetch_institutional_history("", month)
        request_count += 1
        payloads[month] = result
    per = {s: {} for s in symbols}
    for month, result in payloads.items():
        for row in _rows(result.get("raw_payload")):
            symbol = str(_pick(row, "SecuritiesCompanyCode", "證券代號", "symbol") or "").strip()
            if symbol not in per:
                continue
            raw_date = _pick(row, "Date", "trade_date", "交易日期", "日期")
            if raw_date is None:
                raise ValueError("TPEX_INSTITUTIONAL_ROW_DATE_MISSING")
            session = normalize_tpex_date(raw_date)
            if session[:7].replace("-", "") != month:
                raise ValueError("TPEX_INSTITUTIONAL_RESPONSE_PERIOD_MISMATCH")
            if session not in candidate_dates:
                continue
            if session in per[symbol]:
                raise ValueError(f"TPEX_DUPLICATE_SYMBOL_DATE:{symbol}:{session}")
            aliases = {
                "foreign_buy": ("ForeignBuy", "ForeignBuyShares", "外資及陸資買進股數", "外資及陸資買股數", "外陸資買進股數"),
                "foreign_sell": ("ForeignSell", "ForeignSellShares", "外資及陸資賣出股數", "外資及陸資賣股數", "外陸資賣出股數"),
                "foreign_net": ("ForeignNet", "ForeignNetBuySell", "外資及陸資買賣超股數", "外資及陸資淨買股數", "外陸資買賣超股數"),
                "investment_trust_buy": ("InvestmentTrustBuy", "投信買進股數", "投信買股數"),
                "investment_trust_sell": ("InvestmentTrustSell", "投信賣出股數", "投信賣股數"),
                "investment_trust_net": ("InvestmentTrustNet", "投信買賣超股數", "投信淨買股數"),
            }
            values = {key: _number(_pick(row, *fields), key) for key, fields in aliases.items()}
            if values["foreign_buy"] - values["foreign_sell"] != values["foreign_net"]:
                raise ValueError(f"TPEX_FOREIGN_ARITHMETIC_MISMATCH:{symbol}:{session}")
            if values["investment_trust_buy"] - values["investment_trust_sell"] != values["investment_trust_net"]:
                raise ValueError(f"TPEX_IT_ARITHMETIC_MISMATCH:{symbol}:{session}")
            stock = next((x for x in stock_rows_by_symbol[symbol] if x.get("trade_date") == session), None)
            if stock is None:
                raise ValueError(f"INSTITUTIONAL_STOCK_DATE_MISMATCH:{symbol}:{session}")
            values.update({"symbol": symbol, "trading_date": session,
                           "foreign_net_shares": values["foreign_net"],
                           "investment_trust_net_shares": values["investment_trust_net"],
                           "close": _number(stock.get("close"), "close"),
                           "turnover": _number(stock.get("turnover"), "turnover"),
                           "source_timestamp": result.get("source_timestamp"),
                           "official_source": TPEX_OFFICIAL_SOURCE})
            per[symbol][session] = values
    rows = {s: sorted(v.values(), key=lambda row: row["trading_date"]) for s, v in per.items()}
    missing = [s for s in symbols if len(rows[s]) < INSTITUTIONAL_HISTORY_MINIMUM]
    if missing:
        raise ValueError("TPEX_INSTITUTIONAL_26_SESSIONS_MISSING:" + ",".join(f"{s}={len(rows[s])}" for s in missing))
    return {"records": rows, "request_count": request_count, "months_requested": months,
            "monthly_request_deduplication": "PASS"}


def _tpex_daily_schema(result):
    """Validate JSON rows against unique labels joined from TPEx's official grouped headers."""
    payload = result.get("raw_payload")
    if not isinstance(payload, dict):
        raise ValueError("TPEX_INSTITUTIONAL_RESPONSE_SCHEMA_INVALID")
    tables = payload.get("tables")
    table = tables[0] if isinstance(tables, list) and tables and isinstance(tables[0], dict) else payload
    raw_date = table.get("date") or payload.get("date")
    if raw_date is None:
        raise ValueError("TPEX_INSTITUTIONAL_RESPONSE_DATE_MISSING")
    response_date = normalize_tpex_date(raw_date)
    api_fields = table.get("fields") or payload.get("fields")
    data = table.get("data") or table.get("records") or payload.get("data") or payload.get("records")
    semantic_fields = (result.get("diagnostics") or {}).get("semantic_field_names")
    if not isinstance(api_fields, list) or not api_fields or not isinstance(data, list):
        raise ValueError("TPEX_INSTITUTIONAL_RESPONSE_SCHEMA_INVALID")
    if not isinstance(semantic_fields, list) or len(semantic_fields) != len(api_fields):
        raise ValueError("TPEX_INSTITUTIONAL_SEMANTIC_HEADER_SCHEMA_MISSING")
    def token(value):
        return "".join(str(value).lower().replace("（", "(").replace("）", ")").split())
    if len(set(semantic_fields)) != len(semantic_fields):
        raise ValueError("TPEX_INSTITUTIONAL_SEMANTIC_HEADER_SCHEMA_DUPLICATE")
    if any(token(qualified.rsplit(".", 1)[-1]) != token(api)
           for qualified, api in zip(semantic_fields, api_fields)):
        raise ValueError("TPEX_INSTITUTIONAL_SEMANTIC_HEADER_SCHEMA_MISMATCH")
    records = []
    for row in data:
        if isinstance(row, dict):
            if not set(semantic_fields).issubset(row):
                raise ValueError("TPEX_INSTITUTIONAL_RESPONSE_ROW_SCHEMA_INVALID")
            records.append(row)
        elif isinstance(row, (list, tuple)) and len(row) == len(semantic_fields):
            records.append(dict(zip(semantic_fields, row)))
        else:
            raise ValueError("TPEX_INSTITUTIONAL_RESPONSE_ROW_SCHEMA_INVALID")
    return response_date, semantic_fields, records, table


def _label_key(value):
    return "".join(str(value).lower().replace("（", "(").replace("）", ")").split())


def _daily_field_mapping(fields):
    """Map required RATE fields from fully qualified official grouped-header labels."""
    mapping = {}
    for field in fields:
        label = _label_key(field)
        foreign_prefix = _label_key("外資及陸資(不含外資自營商)") + "."
        trust_prefix = _label_key("投信") + "."
        if label.startswith(foreign_prefix):
            group, action_label = "foreign_ex_dealer", label[len(foreign_prefix):]
        elif label.startswith(trust_prefix):
            group, action_label = "investment_trust", label[len(trust_prefix):]
        else:
            continue
        if action_label in ("買進股數", "買股數", "buy", "totalbuy"):
            action = "buy"
        elif action_label in ("賣出股數", "賣股數", "sell", "totalsell"):
            action = "sell"
        elif action_label in ("買賣超股數", "淨買股數", "difference", "net"):
            action = "net"
        else:
            continue
        key = f"{group}.{action}"
        if key in mapping:
            raise ValueError(f"TPEX_INSTITUTIONAL_AMBIGUOUS_FIELD:{group}:{action}")
        mapping[key] = str(field)
    required = [(group, action) for group in ("foreign_ex_dealer", "investment_trust")
                for action in ("buy", "sell", "net")]
    missing = [f"{group}.{action}" for group, action in required if f"{group}.{action}" not in mapping]
    if missing:
        raise ValueError("TPEX_INSTITUTIONAL_REQUIRED_FIELDS_MISSING:" + ",".join(missing))
    return mapping

def normalize_tpex_daily_response(result, requested_date, stock_rows_by_symbol, required_symbols):
    diagnostics = result.get("diagnostics") or {}
    if diagnostics.get("http_status") != 200:
        raise ValueError(f"TPEX_INSTITUTIONAL_HTTP_STATUS:{diagnostics.get('http_status')}")
    payload = result.get("raw_payload")
    response_date, fields, rows, table = _tpex_daily_schema(result)
    if response_date != requested_date:
        raise ValueError("TPEX_INSTITUTIONAL_RESPONSE_DATE_MISMATCH")
    mapping = _daily_field_mapping(fields)
    out = {}
    for row in rows:
        symbol = str(_pick(row, "代號", "證券代號", "SecuritiesCompanyCode", "symbol") or "").strip()
        if symbol not in required_symbols:
            continue
        if symbol in out:
            raise ValueError(f"TPEX_DUPLICATE_SYMBOL_DATE:{symbol}:{requested_date}")
        vals = {}
        for group, target in (("foreign_ex_dealer", "foreign"), ("investment_trust", "investment_trust")):
            vals[f"{target}_buy"] = _number(_pick(row, mapping[f"{group}.buy"]), f"{target}_buy")
            vals[f"{target}_sell"] = _number(_pick(row, mapping[f"{group}.sell"]), f"{target}_sell")
            vals[f"{target}_net"] = _number(_pick(row, mapping[f"{group}.net"]), f"{target}_net")
        if vals["foreign_buy"] - vals["foreign_sell"] != vals["foreign_net"]:
            raise ValueError(f"TPEX_FOREIGN_ARITHMETIC_MISMATCH:{symbol}:{requested_date}")
        if vals["investment_trust_buy"] - vals["investment_trust_sell"] != vals["investment_trust_net"]:
            raise ValueError(f"TPEX_IT_ARITHMETIC_MISMATCH:{symbol}:{requested_date}")
        stock = next((x for x in stock_rows_by_symbol[symbol] if x.get("trade_date") == requested_date), None)
        if stock is None:
            raise ValueError(f"INSTITUTIONAL_STOCK_DATE_MISMATCH:{symbol}:{requested_date}")
        vals.update({"symbol": symbol, "trading_date": requested_date,
                     "foreign_net_shares": vals["foreign_net"],
                     "investment_trust_net_shares": vals["investment_trust_net"],
                     "close": _number(stock.get("close"), "close"),
                     "turnover": _number(stock.get("turnover"), "turnover"),
                     "source_timestamp": result.get("source_timestamp"),
                     "official_source": TPEX_OFFICIAL_SOURCE})
        out[symbol] = vals
    missing_symbols = sorted(set(required_symbols) - set(out))
    if missing_symbols:
        raise ValueError("TPEX_INSTITUTIONAL_SYMBOLS_MISSING:" + ",".join(missing_symbols))
    return {"records": out, "response_date": response_date, "field_mapping": mapping,
            "field_names": fields, "table_title": table.get("title") or table.get("subtitle") or table.get("name"),
            "record_count": len(rows), "sample_symbols": sorted(out)}


def fetch_tpex_daily_sessions(adapter, symbols, stock_rows_by_symbol, candidate_dates,
                              probe_dates=TPEX_PROBE_DATES, evidence_writer=None):
    """Probe three required dates, reuse their cached responses, then fetch 26 daily market-wide tables."""
    if len(candidate_dates) != len(set(candidate_dates)):
        raise ValueError("TPEX_DUPLICATE_CANDIDATE_TRADING_DATE")
    dates = sorted(candidate_dates)
    if len(dates) != 26:
        raise ValueError(f"TPEX_SESSION_CALENDAR_COUNT:{len(dates)}!=26")
    missing_probes = sorted(set(probe_dates) - set(dates))
    if missing_probes:
        raise ValueError("TPEX_PROBE_DATE_OUTSIDE_ACCEPTED_SESSION_CALENDAR:" + ",".join(missing_probes))
    probe_results = {}
    probe_evidence = []
    contract = {"artifact": "RATE_TPEX_INSTITUTIONAL_DAILY_CONTRACT_EVIDENCE", "transport_status": "NOT_RUN",
        "official_product": "Foreign & Institutional Investors Trading Detail", "endpoint": None,
        "official_page": "https://www.tpex.org.tw/zh-tw/mainboard/trading/major-institutional/detail/day.html",
        "request_method": "POST", "request_params": None, "sample_dates": list(probe_dates),
        "http_statuses": [], "content_types": [], "response_schema": None, "response_date_identity": "NOT_RUN",
        "field_mapping": None, "FI_semantic_equivalence": "NOT_RUN", "probes": [], "blocking_reason": None}
    def save():
        if evidence_writer:
            evidence_writer(contract)
    try:
        for day in probe_dates:
            result = adapter.fetch_institutional_daily(day)
            diag = result.get("diagnostics", {})
            fetched_probe = {"requested_date": day, "status": "FETCHED",
                "http_status": diag.get("http_status"), "final_url": diag.get("final_url"),
                "redirect_count": diag.get("redirect_count"), "content_type": diag.get("content_type"),
                "content_length": diag.get("content_length"), "response_bytes": diag.get("response_bytes"),
                "body_sha256": diag.get("body_sha256"), "body_prefix_class": diag.get("body_prefix_class"),
                "json_decode_status": diag.get("json_decode_status"), "top_level_keys": diag.get("top_level_keys"),
                "table_count": diag.get("table_count"), "response_field_names": diag.get("response_field_names"),
                "response_date": diag.get("response_date"),
                "response_date_location": diag.get("response_date_location"),
                "table_title": diag.get("table_title"), "record_count": diag.get("record_count"),
                "semantic_schema_source": diag.get("semantic_schema_source"),
                "semantic_schema_status": diag.get("semantic_schema_status"),
                "semantic_schema_sha256": diag.get("semantic_schema_sha256"),
                "semantic_field_names": diag.get("semantic_field_names")}
            probe_evidence.append(fetched_probe)
            contract.update({"endpoint": result.get("endpoint"), "request_params": result.get("request_params"),
                "http_statuses": [x.get("http_status") for x in probe_evidence],
                "content_types": [x.get("content_type") for x in probe_evidence],
                "response_schema": diag.get("response_field_names"), "probes": probe_evidence})
            save()
            try:
                parsed = normalize_tpex_daily_response(result, day, stock_rows_by_symbol, symbols)
            except Exception as parse_exc:
                fetched_probe.update({"status": "FAIL", "contract_error": str(parse_exc)})
                contract["blocking_reason"] = str(parse_exc)
                if "RESPONSE_DATE" in str(parse_exc):
                    contract["response_date_identity"] = "FAIL"
                if "REQUIRED_FIELDS" in str(parse_exc) or "AMBIGUOUS_FIELD" in str(parse_exc):
                    contract["FI_semantic_equivalence"] = "FAIL"
                save()
                raise
            probe_results[day] = (result, parsed)
            fetched_probe.update({"response_date": parsed["response_date"], "status": "PASS",
                "record_count": parsed["record_count"],
                "field_names": parsed["field_names"], "table_title": parsed["table_title"],
                "sample_symbols": parsed["sample_symbols"], "field_mapping": parsed["field_mapping"]})
            contract["probes"] = probe_evidence
            contract.update({"endpoint": result.get("endpoint"), "request_params": result.get("request_params"),
                "http_statuses": [x.get("http_status") for x in probe_evidence],
                "content_types": [x.get("content_type") for x in probe_evidence], "response_schema": parsed["field_names"],
                "response_date_identity": "PASS", "field_mapping": parsed["field_mapping"],
                "FI_semantic_equivalence": "PASS", "probes": probe_evidence,
                "transport_status": f"{len(probe_evidence)}/3 PASS"})
            save()
        if len(probe_evidence) != 3:
            raise ValueError("TPEX_INSTITUTIONAL_PROBE_COUNT_NOT_3")
        per = {s: [] for s in symbols}; identity = []; arithmetic_count = 0; successful = 0
        all_fields, mapping, title = None, None, None
        for day in dates:
            result, parsed = probe_results[day] if day in probe_results else (adapter.fetch_institutional_daily(day), None)
            if parsed is None:
                parsed = normalize_tpex_daily_response(result, day, stock_rows_by_symbol, symbols)
            successful += 1
            all_fields, mapping, title = parsed["field_names"], parsed["field_mapping"], parsed["table_title"]
            arithmetic_count += len(parsed["records"])
            for symbol in symbols:
                per[symbol].append(parsed["records"][symbol])
            identity.append({"requested_date": day, "response_date": parsed["response_date"],
                "status": "PASS", "body_sha256": result.get("content_hash"), "record_count": parsed["record_count"]})
            save_daily = {"requested_dates": 26, "successful_requests": successful, "request_count": successful,
                "daily_request_deduplication": "PASS", "response_date_identity": "PASS",
                "identity_evidence": identity, "session_count_by_symbol": {s: len(per[s]) for s in symbols},
                "field_coverage": {"foreign_buy_sell_net": "PASS", "investment_trust_buy_sell_net": "PASS"},
                "arithmetic_validation": f"PASS:{arithmetic_count}", "blocking_reason": None}
            if evidence_writer:
                evidence_writer(save_daily, daily=True)
        counts = {s: len(per[s]) for s in symbols}
        if any(counts[s] != 26 for s in symbols):
            raise ValueError("TPEX_INSTITUTIONAL_26_SESSION_COVERAGE_FAILED")
        result = {"records": per, "request_count": successful, "successful_requests": successful,
            "valid_responses": successful, "session_dates": dates, "session_calendar": "26/26",
            "daily_request_deduplication": "PASS", "response_date_identity": "PASS",
            "session_count_by_symbol": counts, "minimum_sessions": min(counts.values()),
            "maximum_sessions": max(counts.values()), "field_mapping": mapping,
            "field_names": all_fields, "table_title": title, "arithmetic_validation": f"PASS:{arithmetic_count}"}
        contract.update({"transport_status": "PASS", "daily_request_granularity": "DAILY_MARKET_WIDE",
            "response_schema": all_fields, "response_date_identity": "PASS", "field_mapping": mapping,
            "FI_semantic_equivalence": "PASS", "probes": probe_evidence})
        save()
        if evidence_writer:
            evidence_writer({**result, "artifact": "RATE_CER072_TPEX_26_SESSION_EVIDENCE",
                "requested_dates": 26, "request_count": successful, "successful_requests": successful,
                "daily_request_deduplication": "PASS", "response_date_identity": "PASS",
                "session_count_by_symbol": counts, "minimum_sessions": min(counts.values()),
                "maximum_sessions": max(counts.values()), "field_coverage": {"FI": "PASS", "IT": "PASS"},
                "arithmetic_validation": result["arithmetic_validation"], "identity_evidence": identity}, daily=True)
        return result
    except Exception as exc:
        contract["transport_status"] = "FAIL"
        contract["blocking_reason"] = str(exc)
        diagnostics = getattr(exc, "diagnostics", None)
        if diagnostics:
            contract.setdefault("transport_diagnostics", []).append(diagnostics)
        contract["probes"] = probe_evidence
        save()
        if evidence_writer:
            evidence_writer({"artifact": "RATE_CER072_TPEX_26_SESSION_EVIDENCE", "validation_status": "FAIL",
                "requested_dates": 26, "request_count": len(probe_evidence), "successful_requests": len(probe_evidence),
                "blocking_reason": str(exc), "daily_request_deduplication": "NOT_COMPLETE"}, daily=True)
        raise


def validate_history_rows(rows_by_symbol, symbols, dates, minimum=26):
    accepted = {}
    for symbol in symbols:
        rows = rows_by_symbol.get(symbol, [])
        by_date = {str(row.get("trading_date")): row for row in rows}
        if len(by_date) != len(rows):
            raise ValueError(f"INSTITUTIONAL_DUPLICATE_SESSION:{symbol}")
        selected = [by_date[d] for d in dates if d in by_date]
        if len(selected) < minimum:
            raise ValueError(f"INSTITUTIONAL_SESSION_COUNT:{symbol}:{len(selected)}<{minimum}")
        for row in selected:
            for field in ("foreign_buy", "foreign_sell", "foreign_net", "investment_trust_buy", "investment_trust_sell", "investment_trust_net", "close", "turnover", "source_timestamp", "official_source"):
                if row.get(field) is None:
                    raise ValueError(f"INSTITUTIONAL_FIELD_MISSING:{symbol}:{row.get('trading_date')}:{field}")
        accepted[symbol] = selected[-minimum:]
    return accepted
