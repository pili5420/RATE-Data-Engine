from __future__ import annotations
import os
from .base import fetch_json, provenance

class FundamentalAdapter:
    provider = "TWSE/MOPS official open data"
    def fetch(self):
        endpoint = os.environ.get("MOPS_FUNDAMENTAL_ENDPOINT")
        if not endpoint:
            raise RuntimeError("DATA_SOURCE_UNAVAILABLE:MOPS_FUNDAMENTAL_ENDPOINT not configured")
        payload, digest = fetch_json(endpoint)
        return provenance("fundamental", self.provider, endpoint, digest, payload)
