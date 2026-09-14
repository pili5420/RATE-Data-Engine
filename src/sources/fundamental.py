from __future__ import annotations

class FundamentalAdapter:
    provider = "TWSE/MOPS official open data"
    def fetch(self):
        raise RuntimeError("DATA_SOURCE_UNAVAILABLE:MOPS fundamental endpoint not configured")
