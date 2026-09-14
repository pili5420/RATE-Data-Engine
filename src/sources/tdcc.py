from __future__ import annotations
from .base import fetch_json, provenance

class TDCCAdapter:
    provider = "TDCC Official OpenAPI"
    endpoint_path = "/v1/opendata/1-5"
    def fetch(self):
        raise RuntimeError("DATA_SOURCE_UNAVAILABLE:TDCC endpoint base/authorization not configured")
