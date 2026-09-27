from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.cer074_acceptance import atomic_write_json
from scripts.publish_production_source_bundle_latest import validate_production_source_bundle


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def fetch_url(url: str, timeout: int = 20) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": "RATE-Production-Scheduler/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read(2_000_000)
        content_type = response.headers.get("content-type", "")
        text = body.decode("utf-8", errors="replace")
        parsed = None
        if "json" in content_type.lower() or text.strip().startswith(("{", "[")):
            parsed = json.loads(text)
        return {
            "url": url,
            "http_status": response.status,
            "content_type": content_type,
            "retrieval_timestamp": utc_now(),
            "record_count": len(parsed) if isinstance(parsed, list) else (len(parsed.get("data", [])) if isinstance(parsed, dict) else 0),
            "json_parse_status": "PASS" if parsed is not None else "FAIL",
            "raw_payload": parsed,
        }


def build_bundle(*, rate_source_url: str, trading_date: str, cadence: str, output: str | Path, evidence_output: str | Path) -> dict[str, Any]:
    if not rate_source_url or not rate_source_url.strip():
        raise RuntimeError("RATE_SOURCE_URL_MISSING")
    urls = [u.strip() for u in rate_source_url.split(";") if u.strip()]
    if not urls:
        raise RuntimeError("RATE_SOURCE_URL_EMPTY")
    retrieval_timestamp = utc_now()
    sources = []
    for url in urls:
        try:
            result = fetch_url(url)
            result.pop("raw_payload", None)
            result["status"] = "PASS" if result["json_parse_status"] == "PASS" and result["record_count"] > 0 else "FAIL"
            sources.append(result)
        except Exception as exc:
            sources.append({"url": url, "status": "FAIL", "retrieval_timestamp": utc_now(), "error": str(exc)})
    bundle = {
        "artifact": "RATE_PRODUCTION_SOURCE_BUNDLE",
        "bundle_version": "RATE-PRODUCTION-SOURCE-V1",
        "schema_version": "RATE-PRODUCTION-SOURCE-BUNDLE-V1",
        "validation_status": "BLOCKED",
        "source_bundle_validation": "BLOCKED",
        "trading_date": trading_date,
        "cadence": cadence,
        "retrieval_timestamp": retrieval_timestamp,
        "source_provenance": {
            "source": "RATE_OFFICIAL_TW_MARKET_DATA_SSOT",
            "retrieval_timestamp": retrieval_timestamp,
            "rate_source_url_configured": True,
            "fixture_fallback": "FORBIDDEN",
            "historical_acceptance_bundle_fallback": "FORBIDDEN",
            "stale_snapshot_fallback": "FORBIDDEN",
            "local_desktop_dependency": "FORBIDDEN",
        },
        "sources": sources,
        "records": [],
        "decision_records": [],
        "coverage": "0/30",
        "blocking_reason": "OFFICIAL_SOURCE_DECISION_BUNDLE_NOT_COMPLETE",
    }
    validation = validate_production_source_bundle(bundle, trading_date=trading_date, cadence=cadence)
    bundle["official_source_runtime_validation"] = validation
    if validation["validation_status"] == "PASS":
        bundle["validation_status"] = "PASS"
        bundle["source_bundle_validation"] = "PASS"
        bundle.pop("blocking_reason", None)
    atomic_write_json(Path(output), bundle)
    evidence = {
        "artifact": "RATE_PRODUCTION_OFFICIAL_SOURCE_INGESTION_EVIDENCE",
        "validation_status": "PASS" if bundle["validation_status"] == "PASS" else "BLOCKED",
        "trading_date": trading_date,
        "cadence": cadence,
        "source": "RATE_OFFICIAL_TW_MARKET_DATA_SSOT",
        "rate_source_url_configured": True,
        "source_count": len(urls),
        "fixture_fallback": "FORBIDDEN",
        "historical_acceptance_bundle_fallback": "FORBIDDEN",
        "stale_snapshot_fallback": "FORBIDDEN",
        "local_desktop_dependency": "FORBIDDEN",
        "source_bundle_path": str(output).replace("\\", "/"),
        "validation": validation,
        "blocking_reason": bundle.get("blocking_reason"),
    }
    atomic_write_json(Path(evidence_output), evidence)
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(description="Build current-cadence RATE production source bundle from official configured RATE_SOURCE_URL only.")
    parser.add_argument("--trading-date", required=True)
    parser.add_argument("--cadence", required=True, choices=["07:30", "09:30", "12:00", "19:30"])
    parser.add_argument("--rate-source-url", default=os.getenv("RATE_SOURCE_URL", ""))
    parser.add_argument("--output", required=True)
    parser.add_argument("--evidence-output", required=True)
    args = parser.parse_args()
    evidence = build_bundle(rate_source_url=args.rate_source_url, trading_date=args.trading_date, cadence=args.cadence, output=args.output, evidence_output=args.evidence_output)
    print(json.dumps(evidence, ensure_ascii=False, sort_keys=True))
    return 0 if evidence["validation_status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
