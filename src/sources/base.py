from __future__ import annotations
import hashlib, json
from datetime import datetime, timezone
from urllib.request import Request, urlopen

class AdapterResult(dict):
    pass

def fetch_json(endpoint: str) -> tuple[object, str]:
    request = Request(endpoint, headers={"User-Agent": "RATE-Data-Engine/1.0"})
    with urlopen(request, timeout=30) as response:
        body = response.read()
    return json.loads(body.decode("utf-8-sig")), hashlib.sha256(body).hexdigest()

def provenance(domain: str, provider: str, endpoint: str, content_hash: str, payload: object) -> AdapterResult:
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return AdapterResult(domain=domain, provider=provider, source_type="OFFICIAL_PRIMARY",
        endpoint=endpoint, source_timestamp=now, retrieval_timestamp=now,
        content_hash=content_hash, record_count=len(payload) if isinstance(payload, list) else 1,
        raw_payload=payload)
