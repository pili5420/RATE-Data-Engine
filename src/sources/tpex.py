from __future__ import annotations
from .base import fetch_json, provenance

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
