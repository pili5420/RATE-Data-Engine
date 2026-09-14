from __future__ import annotations
import json, sys
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.sources.twse import TWSEAdapter
from src.sources.tpex import TPExAdapter

ROOT = Path(__file__).resolve().parents[1]
landing = ROOT / "data" / "raw_landing" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
landing.mkdir(parents=True, exist_ok=True)
results = []
adapters = [("twse_daily", lambda: TWSEAdapter().fetch_daily()), ("twse_benchmark", lambda: TWSEAdapter().fetch_benchmark()),
            ("tpex_daily", lambda: TPExAdapter().fetch_daily()), ("tpex_quotes", lambda: TPExAdapter().fetch_quotes()),
            ("tpex_institutional", lambda: TPExAdapter().fetch_institutional()), ("tpex_qfii", lambda: TPExAdapter().fetch_qfii())]
for name, fetch in adapters:
    try:
        result = fetch()
        path = landing / f"{name}.json"
        path.write_text(json.dumps(result["raw_payload"], ensure_ascii=False), encoding="utf-8")
        results.append({k: result[k] for k in result if k != "raw_payload"} | {"path":str(path.relative_to(ROOT))})
    except Exception as exc:
        results.append({"name":name, "status":"BLOCKED", "error":str(exc)})
manifest = {"artifact":"RATE_PRODUCTION_SOURCE_BUNDLE", "bundle_version":"RATE-PRODUCTION-SOURCE-V1",
            "retrieval_timestamp":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),
            "landing_path":str(landing.relative_to(ROOT)), "sources":results,
            "required_missing":["large_holder","fundamental","trading_metadata"],
            "input_snapshot_id":None, "validation_status":"BLOCKED"}
(landing / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
(ROOT / "artifacts" / "RATE_PRODUCTION_SOURCE_BUNDLE_LATEST.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
print(json.dumps(manifest, indent=2, ensure_ascii=False))
