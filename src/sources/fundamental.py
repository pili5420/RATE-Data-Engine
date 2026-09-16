from __future__ import annotations
import os
from .base import fetch_json, provenance

class FundamentalAdapter:
    provider = "TWSE Official OpenAPI"
    REVENUE_ENDPOINT = "https://openapi.twse.com.tw/v1/opendata/t187ap05_L"
    EPS_ENDPOINTS = (
        "https://openapi.twse.com.tw/v1/opendata/t187ap06_L_basi",
        "https://openapi.twse.com.tw/v1/opendata/t187ap06_L_bd",
        "https://openapi.twse.com.tw/v1/opendata/t187ap06_L_ci",
        "https://openapi.twse.com.tw/v1/opendata/t187ap06_L_fh",
        "https://openapi.twse.com.tw/v1/opendata/t187ap06_L_ins",
        "https://openapi.twse.com.tw/v1/opendata/t187ap06_L_mim",
    )
    def fetch_monthly_revenue(self):
        payload, digest = fetch_json(self.REVENUE_ENDPOINT)
        return provenance("fundamental_revenue", self.provider, self.REVENUE_ENDPOINT, digest, payload)
    def fetch_quarterly_eps(self, endpoint=None):
        endpoint = endpoint or self.EPS_ENDPOINTS[0]
        payload, digest = fetch_json(endpoint)
        return provenance("fundamental_eps", self.provider, endpoint, digest, payload)
    def fetch(self):
        """Compatibility method returning the official revenue dataset."""
        return self.fetch_monthly_revenue()
