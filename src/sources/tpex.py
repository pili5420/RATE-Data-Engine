from __future__ import annotations
from .base import fetch_json, provenance
import base64, hashlib, json, os, time
from datetime import date
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from http.client import IncompleteRead

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
INSTITUTIONAL_HISTORY_ENDPOINT = "https://www.tpex.org.tw/web/stock/3insti/3insti.php?l=zh-tw&o=json&d={period}"

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
        template = os.getenv('TPEX_INSTITUTIONAL_HISTORY_ENDPOINT', INSTITUTIONAL_HISTORY_ENDPOINT)
        endpoint = template.format(symbol=symbol, period=_roc_period(period), yyyy_mm=period)
        cache_key = (template, _roc_period(period))
        if cache_key in self._institutional_cache:
            payload, digest, diagnostics = self._institutional_cache[cache_key]
        else:
            payload, digest, diagnostics = _resilient_json(endpoint)
            self._institutional_cache[cache_key] = (payload, digest, diagnostics)
        out = provenance('institutional_history', self.provider, endpoint, digest, payload)
        out['diagnostics'] = diagnostics
        return out
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
