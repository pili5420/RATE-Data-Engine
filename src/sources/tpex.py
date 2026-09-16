from __future__ import annotations
from .base import fetch_json, provenance
import os

BASE = "https://www.tpex.org.tw/openapi/v1"
class TPExAdapter:
    provider = "TPEx Official OpenAPI"
    def _fetch(self, path: str, domain: str):
        endpoint = BASE + "/" + path
        payload, digest = fetch_json(endpoint)
        return provenance(domain, self.provider, endpoint, digest, payload)
    def fetch_daily(self): return self._fetch("tpex_mainboard_daily_close_quotes", "market_daily")
    def fetch_quotes(self): return self._fetch("tpex_mainboard_quotes", "market_intraday")
    def fetch_institutional(self): return self._fetch("tpex_3insti_trading", "institutional")
    def fetch_qfii(self): return self._fetch("tpex_3insti_qfii_trading", "institutional_qfii")
    def fetch_historical_symbol(self, symbol: str, period: str):
        endpoint = os.getenv('TPEX_HISTORICAL_ENDPOINT')
        if not endpoint: raise RuntimeError('MISSING_REQUIRED_SOURCE_CONFIGURATION:TPEX_HISTORICAL_ENDPOINT')
        payload, digest = fetch_json(endpoint.format(symbol=symbol, period=period))
        return provenance('market_daily_history', self.provider, endpoint, digest, payload)
    def fetch_historical_benchmark(self, period: str):
        endpoint = os.getenv('TPEX_BENCHMARK_HISTORY_ENDPOINT')
        if not endpoint: raise RuntimeError('MISSING_REQUIRED_SOURCE_CONFIGURATION:TPEX_BENCHMARK_HISTORY_ENDPOINT')
        payload, digest = fetch_json(endpoint.format(period=period))
        return provenance('benchmark_history', self.provider, endpoint, digest, payload)
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
