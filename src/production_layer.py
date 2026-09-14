from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from .source_bundle import SourceBundleError, create_input_snapshot_id, validate_manifest

SLOTS = ("0730", "0930", "1200", "1930")
REQUIRED_DOMAINS = ("market_daily", "market_intraday", "institutional", "large_holder", "fundamental", "benchmark", "trading_metadata")

class AdapterUnavailable(SourceBundleError):
    pass

class SourceAdapter:
    domain: str
    def __init__(self, registry_entry: Mapping[str, object]):
        self.domain = str(registry_entry["domain"])
        self.entry = dict(registry_entry)
    def fetch(self):
        if self.entry.get("authorization_status") != "PASS" or not self.entry.get("endpoint_or_path"):
            raise AdapterUnavailable(f"DATA_SOURCE_UNAVAILABLE:{self.domain}")
        raise AdapterUnavailable(f"ADAPTER_NOT_CONFIGURED:{self.domain}")

def load_source_registry(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))

def create_raw_landing_record(domain: str, payload: object, *, provider: str, source_timestamp: str) -> dict:
    """Persist raw payload with lineage before normalization; never mutates payload."""
    retrieval_timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return {"domain":domain, "provider":provider, "source_timestamp":source_timestamp,
            "retrieval_timestamp":retrieval_timestamp, "raw_payload":payload}

def production_gate_status(registry: Mapping[str, object], *, slot: str) -> dict:
    entries = {str(item["domain"]): item for item in registry.get("domains", [])}
    missing = [domain for domain in REQUIRED_DOMAINS if domain not in entries]
    unauthorized = [domain for domain, item in entries.items() if item.get("authorization_status") != "PASS"]
    result = {"slot":slot, "source_authorization":"PASS" if not unauthorized else "BLOCKED",
              "required_domains":"PASS" if not missing else "BLOCKED",
              "production_source_bundle":"BLOCKED", "input_snapshot_id":None,
              "freshness_validation":"BLOCKED", "data_quality":"BLOCKED", "e2e":"BLOCKED", "blocking_issues":[]}
    result["blocking_issues"].extend(f"DATA_SOURCE_UNAVAILABLE:{domain}" for domain in unauthorized)
    result["blocking_issues"].extend(f"DATA_SOURCE_INCOMPLETE:{domain}" for domain in missing)
    if slot in {"0930", "1200"} and entries.get("market_intraday", {}).get("authorization_status") != "PASS":
        result["e2e"] = "BLOCKED:INTRADAY_SOURCE_UNAVAILABLE"
        result["blocking_issues"].append("INTRADAY_SOURCE_UNAVAILABLE")
    return result
