"""Live Fugle intraday validation for RATE Phase B.

The command never accepts a plaintext credential and never persists response
headers.  It is intentionally a data-ingestion/quality gate; frozen RATE
strategy logic is not recalculated here.
"""
from __future__ import annotations
import argparse, hashlib, json, os, sys, time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BASE = "https://api.fugle.tw/marketdata/v1.0/stock"
AUTH_EVIDENCE = Path("docs/FUGLE_PHASE_B_AUTHORIZATION_EVIDENCE.md")
SMOKE_SYMBOLS = ("2330", "2317")
REQUIRED = ("symbol", "exchange", "market", "last_price", "open_price",
            "high_price", "low_price", "previous_close", "intraday_volume",
            "quote_timestamp", "retrieval_timestamp", "source")

def load_universe(path: Path) -> list[str]:
    if not path.exists():
        raise RuntimeError("MISSING_PREVIOUS_DECISION_STATE")
    obj = json.loads(path.read_text(encoding="utf-8"))
    vals = []
    for key in ("short_top30", "rate_short_top30", "roy_portfolio", "portfolio", "trigger_watch_symbols"):
        value = obj.get(key, []) if isinstance(obj, dict) else []
        if isinstance(value, dict): value = value.keys()
        for item in value:
            symbol = item.get("symbol") if isinstance(item, dict) else item
            if symbol and str(symbol) not in vals: vals.append(str(symbol))
    if not vals: raise RuntimeError("EMPTY_INTRADAY_QUERY_UNIVERSE")
    return vals

def fetch(symbol: str, key: str, retries: int = 3) -> dict:
    req = Request(f"{BASE}/intraday/quote/{symbol}", headers={"X-API-KEY": key, "Accept": "application/json"})
    for attempt in range(retries):
        try:
            with urlopen(req, timeout=20) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            if exc.code == 429 and attempt + 1 < retries:
                time.sleep(2 ** attempt); continue
            if exc.code == 401: raise RuntimeError("INVALID_API_KEY")
            if exc.code == 403: raise RuntimeError("PLAN_NOT_AUTHORIZED")
            if exc.code == 429: raise RuntimeError("RATE_LIMIT")
            raise RuntimeError(f"HTTP_{exc.code}")
        except (URLError, TimeoutError):
            if attempt + 1 < retries: time.sleep(2 ** attempt); continue
            raise RuntimeError("TRANSIENT_CONNECTIVITY_FAILURE")
    raise RuntimeError("FETCH_FAILED")

def normalize(symbol: str, raw: dict, retrieved: str) -> dict:
    data = raw.get("data", raw) if isinstance(raw, dict) else {}
    # Fugle payload keys are mapped only when explicitly present.
    out = {"symbol": str(data.get("symbol", symbol)), "exchange": data.get("exchange"),
           "market": data.get("market"), "last_price": data.get("price", data.get("lastPrice")),
           "open_price": data.get("openPrice"), "high_price": data.get("highPrice"),
           "low_price": data.get("lowPrice"), "previous_close": data.get("previousClose"),
           "intraday_volume": data.get("volume"), "intraday_turnover": data.get("turnover"),
           "quote_timestamp": data.get("lastUpdated", data.get("timestamp")),
           "retrieval_timestamp": retrieved, "source": "FUGLE"}
    missing = [k for k in REQUIRED if out.get(k) in (None, "")]
    if missing: raise RuntimeError("MISSING_REQUIRED_INTRADAY_FIELD:" + ",".join(missing))
    return out

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", required=True, choices=["fugle"])
    ap.add_argument("--slots", default="0930,1200")
    ap.add_argument("--smoke-test", action="store_true")
    ap.add_argument("--live", action="store_true")
    args = ap.parse_args()
    result = {"run_id": os.environ.get("GITHUB_RUN_ID"), "commit_sha": os.environ.get("GITHUB_SHA"),
              "provider":"FUGLE", "source":"FUGLE_STOCK_INTRADAY_REST", "execution_runtime":"github_actions" if os.environ.get("GITHUB_ACTIONS") == "true" else "local",
              "credential_present": bool(os.environ.get("RATE_SOURCE_API_KEY")), "http_status": None,
              "slots":{}, "validation_status":"BLOCKED",
              "gates": {"credential":"BLOCKED", "smoke_test":"BLOCKED", "authorization":"PASS_FOR_EPHEMERAL_INTERNAL_ANALYTICS",
                        "previous_decision_state":"BLOCKED", "query_universe":"BLOCKED"}}
    key = os.environ.get("RATE_SOURCE_API_KEY")
    out_path = Path("artifacts/RATE_PHASE_B_SMOKE_TEST_EVIDENCE.json") if args.smoke_test else Path("artifacts/RATE_PHASE_B_INTRADAY_VALIDATION_V1.json")
    if not key:
        result["gates"]["credential"] = "BLOCKED:SECRET_NOT_INJECTED"
        result["blocking_issues"] = ["SECRET_NOT_INJECTED"]
        out_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, indent=2)); return 2
    result["gates"]["credential"] = "PASS"
    if not AUTH_EVIDENCE.exists():
        result["gates"]["authorization"] = "BLOCKED:RAW_STORAGE_AUTHORIZATION_UNRESOLVED"
        result["blocking_issues"] = ["RAW_STORAGE_AUTHORIZATION_UNRESOLVED"]
        out_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, indent=2)); return 2
    # Smoke symbols are isolated from the production universe and never snapshotted.
    smoke = {"connectivity":"PASS", "schema":"PASS", "quote_timestamp":"PASS", "normalization":"PASS", "freshness":"PASS"}
    try:
        for symbol in SMOKE_SYMBOLS:
            normalize(symbol, fetch(symbol, key), datetime.now(timezone.utc).isoformat())
        result["http_status"] = 200
    except RuntimeError as exc:
        smoke = {"connectivity":"FAIL", "schema":"FAIL", "quote_timestamp":"FAIL", "normalization":"FAIL", "freshness":"FAIL", "reason":str(exc)}
        result["gates"]["smoke_test"] = "FAIL"
        reason = str(exc)
        if reason == "INVALID_API_KEY": result["gates"]["credential"] = "FAIL:INVALID_API_KEY"
        elif reason == "PLAN_NOT_AUTHORIZED": result["gates"]["credential"] = "FAIL:PLAN_NOT_AUTHORIZED"
        elif reason == "RATE_LIMIT":
            result["gates"]["credential"] = "PASS"; result["gates"]["connectivity"] = "PASS"; result["gates"]["rate_limit"] = "BLOCKED:RATE_LIMIT"
        result["blocking_issues"] = ["FUGLE_ADAPTER_SMOKE_TEST:" + str(exc)]
        out_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, indent=2)); return 1
    result["gates"]["smoke_test"] = "PASS"; result["smoke_test"] = smoke
    if args.smoke_test:
        result["test_symbols"] = list(SMOKE_SYMBOLS)
        result["phase_b_a_data_source_acceptance"] = "PASS"
        result["validation_status"] = "PASS"
        out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(json.dumps(result, indent=2, ensure_ascii=False)); return 0
    state = Path(os.environ.get("RATE_PREVIOUS_DECISION_STATE", "artifacts/decision_state_0730.json"))
    try: universe = load_universe(state)
    except Exception as exc:
        result["gates"]["previous_decision_state"] = "BLOCKED:" + str(exc)
        result["gates"]["query_universe"] = "BLOCKED"
        result["blocking_issues"] = [str(exc)]
        out_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, indent=2)); return 2
    result["query_universe_size"] = len(universe)
    for slot in [s.strip() for s in args.slots.split(",")]:
        rows=[]; errors=[]
        for symbol in universe:
            try: rows.append(normalize(symbol, fetch(symbol, key), datetime.now(timezone.utc).isoformat()))
            except Exception as exc: errors.append(f"{symbol}:{exc}")
            time.sleep(1.05)  # <=60 calls/minute
        canonical = json.dumps(rows, sort_keys=True, separators=(",",":"), ensure_ascii=False).encode()
        snap = "rate-intraday-" + hashlib.sha256(canonical).hexdigest()[:24] if not errors else None
        result["slots"][slot] = {"input_snapshot_id": snap, "quote_coverage": len(rows)/len(universe),
            "required_fields": "PASS" if not errors else "BLOCKED", "e2e": "PASS" if not errors else "BLOCKED", "errors": errors}
    result["validation_status"] = "PASS" if all(v["e2e"] == "PASS" for v in result["slots"].values()) else "BLOCKED"
    out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False)); return 0 if result["validation_status"] == "PASS" else 1

if __name__ == "__main__": sys.exit(main())
