from __future__ import annotations
from .base import fetch_json, provenance
import os

class TDCCAdapter:
    provider = "TDCC Official OpenAPI"
    endpoint_path = "/v1/opendata/1-5"
    def fetch(self):
        base = os.environ.get("TDCC_OPENAPI_BASE", "https://openapi.tdcc.com.tw")
        endpoint = base.rstrip("/") + self.endpoint_path
        payload, digest = fetch_json(endpoint)
        return provenance("large_holder", self.provider, endpoint, digest, payload)
