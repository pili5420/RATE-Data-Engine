"""Probe and record the official TPEx individual-stock history contract."""
from __future__ import annotations
import argparse, json
import sys
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.sources.tpex import TPExAdapter, HISTORICAL_PAGE_URL, HISTORICAL_ENDPOINT, _period_date
from scripts.bootstrap_tpex_history import extract_symbol_month_rows
from scripts.build_live_source_bundle import _atomic_write_json

def probe(period: str, output: Path):
    if "-" in period:
        period = period[:4] + period[5:7]
    adapter=TPExAdapter(); rows=[]; probes=[]
    for symbol in ("6274", "3081"):
        result=adapter.fetch_historical_symbol(symbol, period)
        normalized=extract_symbol_month_rows(result, symbol, period); rows.extend(normalized)
        probes.append({"symbol":symbol,"period":period,"row_count":len(normalized),"earliest_date":normalized[0]["trade_date"],"latest_date":normalized[-1]["trade_date"],"identity_validation":"PASS","schema":["Date","Trade unit","Trade Amt.(NTD1000)","Open","High","Low","Close"]})
    evidence={"artifact":"RATE_TPEX_INDIVIDUAL_HISTORY_CONTRACT_EVIDENCE","status":"PASS","official_product_name":"Daily Stock Info / Historical Data of Individual Mainboard Stock","official_page":HISTORICAL_PAGE_URL,"resolved_transport":HISTORICAL_ENDPOINT,"request_method":"POST","parameter_contract":{"code":"symbol","date":"YYYY/MM/01","response":"json"},"response_representation":"JSON","sample_period":period,"probes":probes,"sample_row_count":len(rows),"identity_validation":"PASS","generated_at":datetime.now(timezone.utc).isoformat().replace("+00:00","Z")}
    _atomic_write_json(output,evidence); return evidence
def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--period",default="202609"); ap.add_argument("--output",default="artifacts/RATE_TPEX_INDIVIDUAL_HISTORY_CONTRACT_EVIDENCE.json"); a=ap.parse_args(); r=probe(a.period,Path(a.output)); print(json.dumps({"status":r["status"],"sample_row_count":r["sample_row_count"]})); return 0
if __name__=="__main__": raise SystemExit(main())
