from __future__ import annotations
from .base import fetch_json, provenance

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
    def fetch_historical_symbol(self, stock_no: str, year_month: str):
        endpoint = f"https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?date={year_month}01&stockNo={stock_no}&response=json"
        payload, digest = fetch_json(endpoint)
        return provenance("market_daily_history", self.provider, endpoint, digest, payload)
    @staticmethod
    def normalize_daily(record: dict) -> dict:
        return {"symbol":record.get("Code"), "trade_date":record.get("Date"),
                "open":record.get("OpeningPrice"), "high":record.get("HighestPrice"),
                "low":record.get("LowestPrice"), "close":record.get("ClosingPrice"),
                "volume":record.get("TradeVolume"), "turnover":record.get("TradeValue"),
                "source":"TWSE Official OpenAPI"}
