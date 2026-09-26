"""Official TDCC historical shareholder-distribution query transport.

The public historical page is form-backed (symbol x official period); the
OpenAPI 1-5 endpoint is a current snapshot and cannot provide historical
as-of rows. This adapter follows the official form contract and validates each
response's security and period identity before normalizing its tier rows.
"""
from __future__ import annotations

import hashlib
import re
import time
from datetime import datetime, timezone
from html import unescape
from http.client import IncompleteRead
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, Request, build_opener
from http.cookiejar import CookieJar


TDCC_HISTORICAL_PAGE = "https://www.tdcc.com.tw/portal/zh/smWeb/qryStock"
TDCC_OFFICIAL_PRODUCT = "集保戶股權分散表"
EXPECTED_RANGES = {
    1: "1-999", 2: "1,000-5,000", 3: "5,001-10,000",
    4: "10,001-15,000", 5: "15,001-20,000", 6: "20,001-30,000",
    7: "30,001-40,000", 8: "40,001-50,000", 9: "50,001-100,000",
    10: "100,001-200,000", 11: "200,001-400,000",
    12: "400,001-600,000", 13: "600,001-800,000",
    14: "800,001-1,000,000", 15: "1,000,001以上",
}


def _now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _plain(value):
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", value))).strip()


def normalize_period(value):
    value = str(value).strip()
    if re.fullmatch(r"\d{8}", value):
        return f"{value[:4]}-{value[4:6]}-{value[6:8]}"
    m = re.search(r"(\d{2,3})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日", value)
    if m:
        year, month, day = int(m.group(1)) + 1911, int(m.group(2)), int(m.group(3))
        return f"{year:04d}-{month:02d}-{day:02d}"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return value
    raise ValueError(f"TDCC_HISTORICAL_DATE_UNPARSEABLE:{value}")


def select_required_period_union(replay_sessions, available_periods, periods_per_session=5):
    """Use official listed dates; no weekday or calendar-step assumptions."""
    available = sorted({normalize_period(x) for x in available_periods})
    result = {}
    required = set()
    for session in sorted({normalize_period(x) for x in replay_sessions}):
        eligible = [x for x in available if x <= session]
        if len(eligible) < periods_per_session:
            raise ValueError(f"DATA_INCOMPLETE:TDCC_ASOF_FIVE_PERIODS:{session}")
        chosen = eligible[-periods_per_session:]
        result[session] = chosen
        required.update(chosen)
    return sorted(required), result


def normalize_historical_response(html, requested_period, requested_symbol, *, source_timestamp=None,
                                  retrieval_timestamp=None, response_sha256=None):
    """Parse official HTML and fail on response-date, symbol, or schema drift."""
    requested_period = normalize_period(requested_period)
    requested_symbol = str(requested_symbol).strip()
    plain = _plain(html)
    symbol_match = re.search(r"證券代號\s*[：:]\s*([A-Za-z0-9]+)", plain)
    date_match = re.search(r"資料日期\s*[：:]\s*([^\s<]+)", plain)
    if not symbol_match or symbol_match.group(1).strip() != requested_symbol:
        actual = symbol_match.group(1).strip() if symbol_match else None
        raise ValueError(f"TDCC_HISTORICAL_SYMBOL_MISMATCH:{requested_symbol}:{actual}")
    if not date_match:
        raise ValueError(f"TDCC_HISTORICAL_RESPONSE_DATE_MISMATCH:{requested_period}:MISSING")
    actual_date = normalize_period(date_match.group(1))
    if actual_date != requested_period:
        raise ValueError(f"TDCC_HISTORICAL_RESPONSE_DATE_MISMATCH:{requested_period}:{actual_date}")

    tables = re.findall(r"<table\b[^>]*class=[\"'][^\"']*\btable\b[^\"']*[\"'][^>]*>(.*?)</table>",
                        html, flags=re.I | re.S)
    table = next((x for x in tables if "持股/單位數分級" in _plain(x)), None)
    if table is None:
        raise ValueError("TDCC_HISTORICAL_SCHEMA_MISSING_TIER_TABLE")
    normalized = []
    for tr in re.findall(r"<tr\b[^>]*>(.*?)</tr>", table, flags=re.I | re.S):
        cells = [_plain(x) for x in re.findall(r"<td\b[^>]*>(.*?)</td>", tr, flags=re.I | re.S)]
        if len(cells) < 5 or not cells[0].isdigit():
            continue
        tier = int(cells[0])
        if tier in (16, 17):  # Official adjustment and total rows are excluded.
            continue
        if tier not in EXPECTED_RANGES:
            raise ValueError(f"TDCC_HISTORICAL_UNKNOWN_TIER:{tier}")
        expected = EXPECTED_RANGES[tier]
        actual_range = cells[1].replace(" ", "")
        if actual_range != expected.replace(" ", ""):
            raise ValueError(f"TDCC_HISTORICAL_TIER_LABEL_MISMATCH:{tier}:{actual_range}")
        try:
            holder_count = int(cells[2].replace(",", ""))
            shares = int(cells[3].replace(",", ""))
            percentage = float(cells[4].replace(",", "").replace("%", ""))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"TDCC_HISTORICAL_TIER_TYPE_INVALID:{tier}") from exc
        if holder_count < 0 or shares < 0 or not 0 <= percentage <= 100:
            raise ValueError(f"TDCC_HISTORICAL_TIER_RANGE_INVALID:{tier}")
        normalized.append({
            "period_end": requested_period, "symbol": requested_symbol,
            "holding_range": tier, "holder_count": holder_count, "shares": shares,
            "holder_percentage": percentage, "source": TDCC_HISTORICAL_PAGE,
            "source_timestamp": source_timestamp or requested_period,
            "retrieval_timestamp": retrieval_timestamp or _now(),
            "response_sha256": response_sha256,
        })
    tiers = [x["holding_range"] for x in normalized]
    if len(tiers) != 15 or set(tiers) != set(range(1, 16)) or len(tiers) != len(set(tiers)):
        raise ValueError(f"TDCC_HISTORICAL_REQUIRED_TIERS_INVALID:{requested_symbol}:{requested_period}")
    return normalized


def holder_pct_400_from_tiers(rows):
    """Sum official 400,001+ tier percentages (levels 12-15), fail closed."""
    values = {}
    for row in rows:
        tier = int(row["holding_range"])
        if tier not in range(1, 16) or tier in values:
            raise ValueError(f"TDCC_DUPLICATE_OR_INVALID_TIER:{tier}")
        value = row.get("holder_percentage")
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 100:
            raise ValueError(f"TDCC_TIER_PERCENTAGE_INVALID:{tier}")
        values[tier] = float(value)
    if set(values) != set(range(1, 16)):
        raise ValueError("TDCC_MISSING_REQUIRED_TIER")
    return sum(values[tier] for tier in range(12, 16))


class TDCCHistoricalAdapter:
    provider = "TDCC Official Historical Query"
    endpoint = TDCC_HISTORICAL_PAGE
    request_method = "POST"
    request_granularity = "SYMBOL_DATE"

    def __init__(self, opener=None, min_interval_seconds=None):
        self.opener = opener or build_opener(HTTPCookieProcessor(CookieJar()))
        self.min_interval_seconds = (float(min_interval_seconds) if min_interval_seconds is not None
                                     else float(__import__("os").environ.get("TDCC_MIN_INTERVAL_SECONDS", "0.15")))
        self.request_count = 0
        self._last_request = None
        self._token = None
        self._first_date = None
        self._available = None

    def _open(self, request):
        last_transport_error = None
        for attempt in range(1, 4):
            if self._last_request is not None and self.min_interval_seconds > 0:
                time.sleep(max(0.0, self.min_interval_seconds - (time.monotonic() - self._last_request)))
            if attempt > 1:
                time.sleep(min(2.0 * (attempt - 1), 4.0))
            self._last_request = time.monotonic()
            try:
                response = self.opener.open(request, timeout=40)
            except HTTPError as exc:
                raise RuntimeError(f"TDCC_HISTORICAL_HTTP_{exc.code}") from exc
            except (IncompleteRead, URLError, TimeoutError, OSError) as exc:
                last_transport_error = exc
                continue
            self.request_count += 1
            status = getattr(response, "status", response.getcode())
            if status != 200:
                raise RuntimeError(f"TDCC_HISTORICAL_HTTP_{status}")
            try:
                body = response.read()
            except (IncompleteRead, TimeoutError, OSError) as exc:
                last_transport_error = exc
                continue
            if not body:
                raise RuntimeError("TDCC_HISTORICAL_EMPTY_RESPONSE")
            return body
        raise RuntimeError(f"TDCC_HISTORICAL_TRANSPORT_ERROR:{type(last_transport_error).__name__}") from last_transport_error

    def _initialize(self):
        if self._available is not None:
            return
        req = Request(self.endpoint, headers={"User-Agent": "RATE-Data-Engine/1.0"})
        body = self._open(req)
        html = body.decode("utf-8-sig", errors="strict")
        token = re.search(r'name="SYNCHRONIZER_TOKEN"\s+value="([^"]+)"', html)
        form = re.search(r'<select\b[^>]*name="scaDate"[^>]*>(.*?)</select>', html, re.I | re.S)
        dates = re.findall(r'<option\b[^>]*value="(\d{8})"', form.group(1), re.I) if form else []
        if not token or not dates:
            raise RuntimeError("TDCC_HISTORICAL_FORM_CONTRACT_CHANGED")
        self._token = token.group(1)
        self._first_date = dates[0]
        self._available = sorted({normalize_period(x) for x in dates})
        self._token_field = "SYNCHRONIZER_TOKEN"

    @property
    def available_periods(self):
        self._initialize()
        return list(self._available)

    def fetch_period(self, symbol, period):
        self._initialize()
        period = normalize_period(period)
        date_value = period.replace("-", "")
        if period not in self._available:
            raise ValueError(f"TDCC_PERIOD_NOT_AVAILABLE:{period}")
        symbol = str(symbol).strip()
        if not re.fullmatch(r"[A-Za-z0-9]{4,6}", symbol):
            raise ValueError(f"TDCC_SYMBOL_INVALID:{symbol}")
        fields = {
            self._token_field: self._token,
            "SYNCHRONIZER_URI": "/portal/zh/smWeb/qryStock",
            "method": "submit", "firDate": self._first_date, "scaDate": date_value,
            "sqlMethod": "StockNo", "stockNo": symbol, "stockName": "",
        }
        body = urlencode(fields).encode("utf-8")
        req = Request(self.endpoint, data=body, method="POST", headers={
            "User-Agent": "RATE-Data-Engine/1.0",
            "Referer": self.endpoint,
            "Content-Type": "application/x-www-form-urlencoded",
        })
        raw = self._open(req)
        html = raw.decode("utf-8-sig", errors="strict")
        digest = hashlib.sha256(raw).hexdigest()
        next_token = re.search(r'name="SYNCHRONIZER_TOKEN"\s+value="([^"]+)"', html)
        if not next_token:
            raise RuntimeError("TDCC_HISTORICAL_RESPONSE_TOKEN_MISSING")
        self._token = next_token.group(1)
        return normalize_historical_response(html, period, symbol,
            source_timestamp=period, retrieval_timestamp=_now(), response_sha256=digest)

    def fetch_period_union(self, symbols, periods):
        self._initialize()
        normalized_symbols = sorted({str(x).strip() for x in symbols})
        normalized_periods = sorted({normalize_period(x) for x in periods})
        rows = []
        for period in normalized_periods:
            for symbol in normalized_symbols:
                rows.extend(self.fetch_period(symbol, period))
        return {
            "provider": self.provider, "official_product": TDCC_OFFICIAL_PRODUCT,
            "official_historical_page": self.endpoint,
            "transport_contract": {
                "method": self.request_method, "endpoint": self.endpoint,
                "date_parameter": "scaDate (YYYYMMDD)",
                "symbol_parameter": "stockNo", "response_format": "HTML",
                "encoding": "UTF-8", "response_date": "result label 資料日期 (ROC year)",
                "schema": ["序", "持股/單位數分級", "人數", "股數/單位數", "占集保庫存數比例 (%)"],
                "request_granularity": self.request_granularity,
                "form_fields": ["SYNCHRONIZER_TOKEN", "SYNCHRONIZER_URI", "method",
                                "firDate", "scaDate", "sqlMethod", "stockNo", "stockName"],
            },
            "available_periods": list(self.available_periods),
            "requested_periods": normalized_periods,
            "request_count": self.request_count, "normalized_rows": rows,
            "source_timestamp": max((x["source_timestamp"] for x in rows), default=None),
            "retrieval_timestamp": _now(),
            "response_date_identity_status": "PASS",
            "symbols_required": len(normalized_symbols), "symbols_complete": len(normalized_symbols),
        }
