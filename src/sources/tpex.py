from __future__ import annotations
from .base import fetch_json, provenance
import base64, hashlib, json, os, time
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from http.client import IncompleteRead

BASE = "https://www.tpex.org.tw/openapi/v1"
# ``stk_quote.php`` is the documented product page.  Its paired official
# result endpoint returns the complete monthly table; filtering by symbol in
# the normalizer gives a deterministic 180-session history.
HISTORICAL_ENDPOINT = "https://www.tpex.org.tw/web/stock/aftertrading/daily_close_quotes/stk_quote.php?l=zh-tw&o=json&d={period}&s={symbol}"
HISTORICAL_RESULT_ENDPOINT = "https://www.tpex.org.tw/web/stock/aftertrading/daily_close_quotes/stk_quote_result.php?l=zh-tw&o=json&d={period}&s=0,asc,0"
BENCHMARK_ENDPOINT = "https://www.tpex.org.tw/openapi/v1/tpex_index"
INSTITUTIONAL_HISTORY_ENDPOINT = "https://www.tpex.org.tw/web/stock/3insti/3insti.php?l=zh-tw&o=json&d={period}"

def _roc_period(period: str) -> str:
    year, month = int(period[:4]), int(period[4:6])
    return f"{year - 1911:03d}{month:02d}"

def _resilient_json(endpoint: str, retries: int = 3):
    last = None
    for attempt in range(retries):
        try:
            req = Request(endpoint, headers={"User-Agent": "RATE-Data-Engine/1.0", "Accept": "application/json"})
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
        template = os.getenv('TPEX_HISTORICAL_ENDPOINT', HISTORICAL_RESULT_ENDPOINT)
        endpoint = template.format(symbol=symbol, period=_roc_period(period), yyyy_mm=period)
        payload, digest, diagnostics = _resilient_json(endpoint)
        out = provenance('market_daily_history', self.provider, endpoint, digest, payload)
        out['diagnostics'] = diagnostics
        return out
    def fetch_historical_benchmark(self, period: str):
        template = os.getenv('TPEX_BENCHMARK_HISTORY_ENDPOINT', BENCHMARK_ENDPOINT)
        endpoint = template.format(period=_roc_period(period), yyyy_mm=period)
        payload, digest, diagnostics = _resilient_json(endpoint)
        out = provenance('benchmark_history', self.provider, endpoint, digest, payload)
        out['benchmark_symbol'] = 'TPEX'; out['benchmark_name'] = 'TPEx Index'; out['diagnostics'] = diagnostics
        return out
    def fetch_institutional_history(self, symbol: str, period: str):
        template = os.getenv('TPEX_INSTITUTIONAL_HISTORY_ENDPOINT', INSTITUTIONAL_HISTORY_ENDPOINT)
        endpoint = template.format(symbol=symbol, period=_roc_period(period), yyyy_mm=period)
        payload, digest, diagnostics = _resilient_json(endpoint)
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
