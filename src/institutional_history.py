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
TPEX_OFFICIAL_SOURCE = "TPEx official monthly 3insti dataset"


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
