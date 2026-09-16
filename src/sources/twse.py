from __future__ import annotations
from .base import fetch_json, provenance
from urllib.request import Request, urlopen
import hashlib, json
import os

BASE = "https://openapi.twse.com.tw/v1"
class TWSEAdapter:
    provider = "TWSE Official OpenAPI"
    def fetch_daily(self):
        endpoint = BASE + "/exchangeReport/STOCK_DAY_ALL"
        payload, digest = fetch_json(endpoint)
        return provenance("market_daily", self.provider, endpoint, digest, payload)
    def fetch_benchmark(self):
        endpoint = BASE + "/exchangeReport/MI_INDEX"
        payload, digest = fetch_json(endpoint)
        return provenance("benchmark", self.provider, endpoint, digest, payload)
    def fetch_t86(self, trading_date: str):
        date = trading_date.replace('-', '')
        endpoint = f"https://www.twse.com.tw/rwd/zh/fund/T86?date={date}&selectType=ALLBUT0999&response=json"
        req = Request(endpoint, headers={"Accept":"application/json"})
        try:
            with urlopen(req, timeout=30) as resp:
                body = resp.read(); status = resp.status; ctype = resp.headers.get('Content-Type','')
        except Exception as exc:
            raise RuntimeError(f"FAIL:T86_HTTP_ERROR:{type(exc).__name__}") from exc
        diag = {'http_status':status,'content_type':ctype,'response_received':bool(body),'body_sha256':hashlib.sha256(body).hexdigest(),'response_bytes':len(body)}
        if not body: raise RuntimeError('FAIL:T86_EMPTY_RESPONSE')
        if 'json' not in ctype.lower(): raise RuntimeError('FAIL:T86_NON_JSON_RESPONSE')
        try: payload=json.loads(body.decode('utf-8'))
        except (UnicodeDecodeError,json.JSONDecodeError) as exc: raise RuntimeError('FAIL:T86_NON_JSON_RESPONSE') from exc
        out = provenance('institutional_listed', self.provider, endpoint, diag['body_sha256'], payload); out['diagnostics']=diag; out['trading_date']=trading_date; return out
    def fetch_symbol_master(self):
        endpoint = BASE + "/opendata/t187ap03_L"
        payload, digest = fetch_json(endpoint)
        return provenance("trading_symbol_master", self.provider, endpoint, digest, payload)
    def fetch_monthly_revenue(self):
        endpoint = BASE + "/opendata/t187ap05_L"
        payload, digest = fetch_json(endpoint)
        return provenance("fundamental_revenue", self.provider, endpoint, digest, payload)
    def fetch_historical_symbol(self, stock_no: str, year_month: str):
        endpoint = f"https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?date={year_month}01&stockNo={stock_no}&response=json"
        payload, digest = fetch_json(endpoint)
        return provenance("market_daily_history", self.provider, endpoint, digest, payload)
    def fetch_historical_benchmark(self, year_month: str):
        endpoint = os.getenv('TWSE_BENCHMARK_HISTORY_ENDPOINT', 'https://www.twse.com.tw/rwd/zh/indicesReport/MI_5MINS_HIST')
        endpoint = endpoint + ('&' if '?' in endpoint else '?') + f'date={year_month}01&response=json'
        payload, digest = fetch_json(endpoint)
        return provenance('benchmark_history', self.provider, endpoint, digest, payload)
    @staticmethod
    def normalize_daily(record: dict) -> dict:
        return {"symbol":record.get("Code"), "trade_date":record.get("Date"),
                "open":record.get("OpeningPrice"), "high":record.get("HighestPrice"),
                "low":record.get("LowestPrice"), "close":record.get("ClosingPrice"),
                "volume":record.get("TradeVolume"), "turnover":record.get("TradeValue"),
                "source":"TWSE Official OpenAPI"}
