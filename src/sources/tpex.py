from __future__ import annotations
from .base import fetch_json, provenance
import base64, hashlib, json, os, time
from datetime import date, datetime, timezone
from urllib.request import Request, urlopen, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError, URLError
from http.client import IncompleteRead
from urllib.parse import urlencode

BASE = "https://www.tpex.org.tw/openapi/v1"
# ``stk_quote.php`` is the documented product page.  Its paired official
# result endpoint returns the complete monthly table; filtering by symbol in
# the normalizer gives a deterministic 180-session history.
HISTORICAL_PAGE_URL = "https://www.tpex.org.tw/en-us/mainboard/trading/info/stock-pricing.html"
HISTORICAL_ENDPOINT = "https://www.tpex.org.tw/www/en-us/afterTrading/tradingStock"
HISTORICAL_RESULT_ENDPOINT = "https://www.tpex.org.tw/web/stock/aftertrading/daily_close_quotes/stk_quote_result.php?l=zh-tw&o=json&d={period}&s=0,asc,0"
BENCHMARK_ENDPOINT = "https://www.tpex.org.tw/openapi/v1/tpex_index"
# The OpenAPI product above is a latest-month snapshot.  TPEx's official
# historical index page exposes the month-scoped JSON contract below.
INDEX_HISTORY_ENDPOINT = "https://www.tpex.org.tw/www/en-us/indexInfo/inx?date={yyyy_mm_slash}&response=json"
LEGACY_DIAGNOSTIC_REFERENCE = "https://www.tpex.org.tw/web/stock/3insti/3insti.php?l=zh-tw&o=json&d={period}"
INSTITUTIONAL_HISTORY_ENDPOINT = LEGACY_DIAGNOSTIC_REFERENCE
INSTITUTIONAL_DAILY_OFFICIAL_PAGE = "https://www.tpex.org.tw/zh-tw/mainboard/trading/major-institutional/detail/day.html"
INSTITUTIONAL_DAILY_ENDPOINT = "https://www.tpex.org.tw/www/zh-tw/insti/dailyTrade"
INSTITUTIONAL_DAILY_LEGACY_ENDPOINT = LEGACY_DIAGNOSTIC_REFERENCE

def _roc_period(period: str) -> str:
    year, month = int(period[:4]), int(period[4:6])
    return f"{year - 1911:03d}{month:02d}"

def _period_date(period: str) -> str:
    """Return the first Gregorian day used by TPEx historical page APIs."""
    year, month = int(period[:4]), int(period[4:6])
    return f"{year:04d}/{month:02d}/01"

def normalize_tpex_date(value) -> str:
    """Normalize Gregorian/ROC TPEx date representations to YYYY-MM-DD."""
    text = str(value or '').strip().replace('-', '/').replace('.', '/')
    if not text:
        raise ValueError('INVALID_TPEX_DATE')
    digits = ''.join(ch for ch in text if ch.isdigit())
    if len(digits) == 8:
        year, month, day = int(digits[:4]), int(digits[4:6]), int(digits[6:8])
    elif len(digits) == 7:  # ROC YYYMMDD
        year, month, day = int(digits[:3]) + 1911, int(digits[3:5]), int(digits[5:7])
    else:
        parts = [p for p in text.split('/') if p]
        if len(parts) != 3:
            raise ValueError(f'INVALID_TPEX_DATE:{value}')
        year, month, day = map(int, parts)
        if year < 1000:
            year += 1911
    try:
        return date(year, month, day).isoformat()
    except ValueError as exc:
        raise ValueError(f'INVALID_TPEX_DATE:{value}') from exc

def _resilient_json(endpoint: str, retries: int = 3, *, method: str = "GET", form: dict | None = None):
    last = None
    for attempt in range(retries):
        try:
            headers = {"User-Agent": "RATE-Data-Engine/1.0", "Accept": "application/json"}
            if method == "POST":
                from urllib.parse import urlencode
                body = urlencode(form or {}).encode("utf-8")
                headers["Content-Type"] = "application/x-www-form-urlencoded"
                req = Request(endpoint, data=body, headers=headers, method="POST")
            else:
                req = Request(endpoint, headers=headers)
            with urlopen(req, timeout=30) as response:
                body = response.read()
                status = response.status
                ctype = response.headers.get("Content-Type", "")
            if not body:
                raise RuntimeError("TPEX_EMPTY_RESPONSE")
            payload = json.loads(body.decode("utf-8-sig"))
            return payload, hashlib.sha256(body).hexdigest(), {"http_status": status, "content_type": ctype, "response_bytes": len(body), "attempt": attempt + 1}
        except (IncompleteRead, ConnectionError, TimeoutError, URLError, HTTPError, json.JSONDecodeError) as exc:
            last = exc
            if attempt + 1 < retries:
                time.sleep(2 ** attempt)
    code = getattr(last, 'code', None)
    location = getattr(getattr(last, 'headers', None), 'get', lambda *_: None)('Location')
    detail = f"HTTP_{code}" if code else type(last).__name__
    if location:
        detail += ":LOCATION_PRESENT"
    raise RuntimeError(f"TPEX_HISTORICAL_RETRIEVAL_FAILED:{detail}") from last
class TPExAdapter:
    provider = "TPEx Official OpenAPI"
    def __init__(self):
        # Historical individual-stock responses are keyed by (symbol, period).
        self._historical_cache = {}
        self._institutional_cache = {}
        self._institutional_daily_cache = {}
    def _fetch(self, path: str, domain: str):
        endpoint = BASE + "/" + path
        payload, digest = fetch_json(endpoint)
        return provenance(domain, self.provider, endpoint, digest, payload)
    def fetch_daily(self): return self._fetch("tpex_mainboard_daily_close_quotes", "market_daily")
    def fetch_quotes(self): return self._fetch("tpex_mainboard_quotes", "market_intraday")
    def fetch_symbol_master(self):
        """Return the official OTC market symbol master used for classification."""
        return self._fetch("tpex_mainboard_quotes", "trading_symbol_master")
    def fetch_institutional(self): return self._fetch("tpex_3insti_trading", "institutional")
    def fetch_qfii(self): return self._fetch("tpex_3insti_qfii_trading", "institutional_qfii")
    def fetch_historical_symbol(self, symbol: str, period: str):
        endpoint = os.getenv('TPEX_HISTORICAL_ENDPOINT', HISTORICAL_ENDPOINT)
        cache_key = (endpoint, symbol, period, 'json')
        if cache_key in self._historical_cache:
            payload, digest, diagnostics = self._historical_cache[cache_key]
        else:
            # The official Daily Stock Info page submits date as the first day
            # of the requested month in Gregorian form (YYYY/MM/01).
            payload, digest, diagnostics = _resilient_json(
                endpoint, method="POST",
                form={"code": symbol, "date": _period_date(period), "response": "json"})
            self._historical_cache[cache_key] = (payload, digest, diagnostics)
        out = provenance('market_daily_history', self.provider, endpoint, digest, payload)
        out['request_method'] = 'POST'
        out['request_params'] = {'code': symbol, 'date': _period_date(period), 'response': 'json'}
        out['product_page'] = HISTORICAL_PAGE_URL
        out['historical_product'] = 'Daily Stock Info / Historical Data of Individual Mainboard Stock'
        out['diagnostics'] = diagnostics
        return out
    def fetch_historical_benchmark(self, period: str):
        template = os.getenv('TPEX_BENCHMARK_HISTORY_ENDPOINT', INDEX_HISTORY_ENDPOINT)
        endpoint = template.format(period=_roc_period(period), yyyy_mm=period, yyyy_mm_slash=_period_date(period))
        payload, digest, diagnostics = _resilient_json(endpoint)
        out = provenance('benchmark_history', self.provider, endpoint, digest, payload)
        out['benchmark_symbol'] = 'TPEX'; out['benchmark_name'] = 'TPEx Index'; out['diagnostics'] = diagnostics
        return out
    def fetch_institutional_history(self, symbol: str, period: str):
        raise RuntimeError('TPEX_LEGACY_INSTITUTIONAL_ROUTE_DISABLED:USE_FETCH_INSTITUTIONAL_DAILY')
    def fetch_institutional_daily(self, trading_date: str):
        """Fetch the current official, date-scoped, market-wide institutional table.

        The obsolete monthly 3insti.php route remains only as a diagnostic
        constant. It is deliberately never used as a fallback here.
        """
        day = date.fromisoformat(trading_date)
        params = {
            "type": "Daily", "sect": "EW",
            "date": f"{day.year - 1911:03d}/{day.month:02d}/{day.day:02d}",
            "id": "", "response": "json",
        }
        cache_key = (trading_date, tuple(params.items()))
        if cache_key in self._institutional_daily_cache:
            cached = dict(self._institutional_daily_cache[cache_key])
            cached["diagnostics"] = {**cached.get("diagnostics", {}), "cache_hit": True}
            return cached
        endpoint = os.getenv("TPEX_INSTITUTIONAL_DAILY_ENDPOINT", INSTITUTIONAL_DAILY_ENDPOINT)
        result = _resilient_tpex_daily_json(endpoint, params)
        payload, digest, diagnostics = result["payload"], result["body_sha256"], result["diagnostics"]
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        source_timestamp = diagnostics.get("http_date") or now
        out = {
            "domain": "institutional_history_daily",
            "provider": "TPEx Official OpenAPI",
            "source_type": "OFFICIAL_PRIMARY",
            "source": "TPEx official Foreign & Institutional Investors Trading Detail daily dataset",
            "endpoint": endpoint,
            "request_method": "POST",
            "request_params": params,
            "source_timestamp": source_timestamp,
            "retrieval_timestamp": now,
            "content_hash": digest,
            "record_count": diagnostics.get("record_count", 0),
            "raw_payload": payload,
            "diagnostics": diagnostics,
        }
        self._institutional_daily_cache[cache_key] = out
        return dict(out)
    @staticmethod
    def normalize_daily(record: dict) -> dict:
        return {"symbol":record.get("SecuritiesCompanyCode"), "trade_date":record.get("Date"),
                "open":record.get("Open"), "high":record.get("High"), "low":record.get("Low"),
                "close":record.get("Close"), "volume":record.get("TradingShares"),
                "turnover":record.get("TransactionAmount"), "source":"TPEx Official OpenAPI"}
    @staticmethod
    def normalize_institutional(record: dict) -> dict:
        return {"symbol":record.get("SecuritiesCompanyCode"), "trade_date":record.get("Date"),
                "foreign_net":record.get("NetBuy"), "source":"TPEx Official OpenAPI"}


class _RedirectCounter(HTTPRedirectHandler):
    def __init__(self):
        super().__init__()
        self.count = 0
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self.count += 1
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _body_prefix_class(body: bytes) -> str:
    prefix = body.lstrip()[:32].lower()
    if not prefix:
        return "EMPTY"
    if prefix.startswith(b"{"):
        return "JSON_OBJECT"
    if prefix.startswith(b"["):
        return "JSON_ARRAY"
    if prefix.startswith((b"<!doctype html", b"<html", b"<head", b"<body")):
        return "HTML"
    if prefix.startswith(b"<"):
        return "HTML"
    try:
        body[:32].decode("utf-8")
        return "TEXT"
    except UnicodeDecodeError:
        return "UNKNOWN"


def _safe_body_prefix(body: bytes, limit: int = 120) -> str:
    try:
        return body[:limit].decode("utf-8", errors="replace").replace("\r", " ").replace("\n", " ")
    except Exception:
        return "<unavailable>"


class TPExDailyTransportError(RuntimeError):
    def __init__(self, message: str, diagnostics: dict):
        super().__init__(message)
        self.diagnostics = diagnostics


def _resilient_tpex_daily_json(endpoint: str, params: dict, retries: int = 3):
    """Current dailyTrade transport with bounded transient retries and diagnostics."""
    body = urlencode(params).encode("utf-8")
    history = []
    for attempt in range(1, retries + 1):
        redirects = _RedirectCounter()
        request = Request(endpoint, data=body, headers={
            "User-Agent": "RATE-Data-Engine/1.0 (+https://github.com/pili5420/RATE-Data-Engine)",
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        }, method="POST")
        opener = build_opener(redirects)
        response_body = b""
        status = None
        headers = None
        final_url = endpoint
        try:
            with opener.open(request, timeout=30) as response:
                response_body = response.read()
                status = response.status
                headers = response.headers
                final_url = response.geturl()
        except HTTPError as exc:
            status, headers = exc.code, exc.headers
            final_url = exc.geturl() or endpoint
            try:
                response_body = exc.read(4096)
            except Exception:
                response_body = b""
            diagnostic = {
                "requested_url": endpoint, "request_path": Request(endpoint).full_url,
                "request_method": "POST", "request_params": params,
                "http_status": status, "final_url": final_url, "redirect_count": redirects.count,
                "content_type": headers.get("Content-Type", "") if headers else "",
                "content_length": headers.get("Content-Length") if headers else None,
                "response_bytes": len(response_body), "body_sha256": hashlib.sha256(response_body).hexdigest(),
                "body_prefix_class": _body_prefix_class(response_body),
                "first_safe_body_characters": _safe_body_prefix(response_body), "attempt": attempt,
            }
            history.append(diagnostic)
            if status == 429 or 500 <= status < 600:
                if attempt < retries:
                    time.sleep(min(2 ** (attempt - 1), 8))
                    continue
            diagnostic["attempt_history"] = history
            raise TPExDailyTransportError(f"TPEX_INSTITUTIONAL_DAILY_HTTP_{status}", diagnostic) from exc
        except (IncompleteRead, ConnectionError, TimeoutError, URLError, OSError) as exc:
            partial = getattr(exc, "partial", b"")
            response_body = partial if isinstance(partial, bytes) else b""
            diagnostic = {"requested_url": endpoint, "request_method": "POST", "request_params": params,
                "http_status": None, "final_url": final_url, "redirect_count": redirects.count,
                "content_type": "", "content_length": None, "response_bytes": len(response_body),
                "body_sha256": hashlib.sha256(response_body).hexdigest(),
                "body_prefix_class": _body_prefix_class(response_body),
                "first_safe_body_characters": _safe_body_prefix(response_body), "attempt": attempt,
                "transport_exception": type(exc).__name__}
            history.append(diagnostic)
            if attempt < retries:
                time.sleep(min(2 ** (attempt - 1), 8))
                continue
            diagnostic["attempt_history"] = history
            raise TPExDailyTransportError(f"TPEX_INSTITUTIONAL_DAILY_TRANSPORT_FAILED:{type(exc).__name__}", diagnostic) from exc
        diagnostic = {
            "requested_url": endpoint, "request_path": Request(endpoint).full_url,
            "request_method": "POST", "request_params": params,
            "http_status": status, "final_url": final_url, "redirect_count": redirects.count,
            "content_type": headers.get("Content-Type", "") if headers else "",
            "content_length": headers.get("Content-Length") if headers else None,
            "response_bytes": len(response_body), "body_sha256": hashlib.sha256(response_body).hexdigest(),
            "body_prefix_class": _body_prefix_class(response_body),
            "first_safe_body_characters": _safe_body_prefix(response_body), "attempt": attempt,
            "http_date": headers.get("Date") if headers else None,
        }
        history.append(diagnostic)
        if not response_body:
            diagnostic["json_decode_status"] = "FAIL:EMPTY"
            raise TPExDailyTransportError("TPEX_INSTITUTIONAL_DAILY_EMPTY_RESPONSE", diagnostic)
        try:
            payload = json.loads(response_body.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            diagnostic["json_decode_status"] = "FAIL:" + type(exc).__name__
            diagnostic["attempt_history"] = history
            raise TPExDailyTransportError("TPEX_INSTITUTIONAL_DAILY_NON_JSON_RESPONSE", diagnostic) from exc
        diagnostic["json_decode_status"] = "PASS"
        diagnostic["top_level_keys"] = list(payload.keys()) if isinstance(payload, dict) else []
        tables = payload.get("tables", []) if isinstance(payload, dict) else []
        diagnostic["table_count"] = len(tables) if isinstance(tables, list) else 0
        first_table = tables[0] if tables and isinstance(tables[0], dict) else {}
        fields = first_table.get("fields") or (payload.get("fields") if isinstance(payload, dict) else []) or []
        data = first_table.get("data") or (payload.get("data") if isinstance(payload, dict) else []) or []
        diagnostic["response_field_names"] = list(fields) if isinstance(fields, list) else []
        diagnostic["table_title"] = first_table.get("title") or first_table.get("subtitle") or first_table.get("name")
        diagnostic["record_count"] = len(data) if isinstance(data, list) else 0
        diagnostic["response_date"] = first_table.get("date") or (payload.get("date") if isinstance(payload, dict) else None)
        diagnostic["response_date_location"] = "tables[0].date" if first_table.get("date") else ("date" if diagnostic["response_date"] else None)
        diagnostic["attempt_history"] = history
        return {"payload": payload, "body_sha256": diagnostic["body_sha256"], "diagnostics": diagnostic}
    raise RuntimeError("TPEX_INSTITUTIONAL_DAILY_RETRIES_EXHAUSTED")
