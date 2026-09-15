from __future__ import annotations
import argparse, hashlib, json, os, sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

BASE = "https://openapi.twse.com.tw/v1/exchangeReport/T86"
FIELDS = ("證券代號", "外陸資買進股數", "外陸資賣出股數", "投信買進股數", "投信賣出股數")

def main() -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("--date", required=True); args = ap.parse_args()
    out = {"execution_runtime":"github_actions" if os.getenv("GITHUB_ACTIONS")=="true" else "local",
           "workflow_run_id":os.getenv("GITHUB_RUN_ID"), "commit_sha":os.getenv("GITHUB_SHA"),
           "provider":"TWSE", "source":"TWSE_T86", "request_date":args.date,
           "authorization_status":"CONDITIONAL", "response_received":"NO", "HTTP_status":None,
           "record_count":0, "schema_detected":"FAIL", "institutional_fields":"FAIL"}
    url = BASE + "?response=json&date=" + args.date.replace("-", "")
    try:
        req = Request(url, headers={"Accept":"application/json"})
        with urlopen(req, timeout=30) as r:
            out["HTTP_status"] = r.status
            content_type = r.headers.get("Content-Type", "")
            body = r.read(); out["content_type"] = content_type
        out["response_received"] = "YES" if body else "NO"
        out["response_hash"] = hashlib.sha256(body).hexdigest()
        payload = json.loads(body.decode("utf-8"))
        rows = payload if isinstance(payload, list) else payload.get("data", [])
        out["record_count"] = len(rows) if isinstance(rows, list) else 0
        row = rows[0] if rows else {}
        keys = set(row.keys()) if isinstance(row, dict) else set()
        out["schema_detected"] = "PASS" if out["record_count"] > 0 and "證券代號" in keys else "FAIL"
        out["institutional_fields"] = "PASS" if all(k in keys for k in FIELDS[1:]) else "FAIL"
        out["trading_date"] = args.date
        out["t86_retrieval_capability"] = "PASS" if out["HTTP_status"] == 200 and out["response_received"] == "YES" and out["record_count"] > 0 and out["schema_detected"] == "PASS" else "FAIL"
        if out["t86_retrieval_capability"] == "FAIL": out["exact_blocking_reason"] = "T86_STRUCTURE_OR_CONTENT_INVALID"
    except HTTPError as e:
        out["HTTP_status"] = e.code; out["exact_blocking_reason"] = f"HTTP_{e.code}"
    except (URLError, TimeoutError) as e:
        out["exact_blocking_reason"] = "NETWORK_OR_TIMEOUT:" + type(e).__name__
    except (ValueError, UnicodeDecodeError):
        out["exact_blocking_reason"] = "INVALID_JSON_RESPONSE"
    out["retrieval_timestamp"] = datetime.now(timezone.utc).isoformat()
    path = Path("artifacts/RATE_T86_RETRIEVAL_SMOKE_TEST_EVIDENCE.json"); path.write_text(json.dumps(out, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2)); return 0 if out.get("t86_retrieval_capability") == "PASS" else 1
if __name__ == "__main__": sys.exit(main())
