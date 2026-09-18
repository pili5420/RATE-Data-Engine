"""Exact-date inner join of canonical TWSE stock and TAIEX histories."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.build_live_source_bundle import _atomic_write_json

TARGET = 180


def align(*, universe_file: Path, history_root: Path, output: Path):
    universe = json.loads(universe_file.read_text(encoding="utf-8"))
    symbols = [str(x["symbol"]) for x in universe.get("symbols", []) if x.get("market") == "TWSE"]
    benchmark_path = history_root / "benchmark" / "TAIEX.json"
    benchmark = json.loads(benchmark_path.read_text(encoding="utf-8")) if benchmark_path.exists() else []
    benchmark_dates = {str(row.get("trade_date")) for row in benchmark}
    rows = []
    for symbol in symbols:
        path = history_root / "market_daily" / f"{symbol}.json"
        stock = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        stock_dates = {str(row.get("trade_date")) for row in stock}
        aligned = sorted(stock_dates & benchmark_dates)
        rows.append({
            "symbol": symbol,
            "market": "TWSE",
            "stock_record_count": len(stock),
            "benchmark_record_count": len(benchmark),
            "aligned_record_count": len(aligned),
            "stock_earliest_date": min(stock_dates) if stock_dates else None,
            "stock_latest_date": max(stock_dates) if stock_dates else None,
            "aligned_earliest_date": aligned[0] if aligned else None,
            "aligned_latest_date": aligned[-1] if aligned else None,
            "missing_stock_dates_vs_benchmark": sorted(stock_dates - benchmark_dates),
            "missing_benchmark_dates_vs_stock": sorted(benchmark_dates - stock_dates),
        })
    minimum = min((row["aligned_record_count"] for row in rows), default=0)
    maximum = max((row["aligned_record_count"] for row in rows), default=0)
    payload = {
        "artifact": "RATE_TWSE_TAIEX_ALIGNMENT_EVIDENCE",
        "status": "PASS" if len(rows) == 25 and minimum >= TARGET else "FAIL",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "symbol_rows": rows,
        "minimum_aligned_sessions": minimum,
        "maximum_aligned_sessions": maximum,
        "all_symbols_ge_180": len(rows) == 25 and minimum >= TARGET,
        "twse_taiex_alignment": f"{sum(row['aligned_record_count'] >= TARGET for row in rows)}/25",
        "exact_date_inner_join": True,
        "carry_forward_used": False,
        "synthetic_benchmark_rows": False,
        "blocking_reason": None if len(rows) == 25 and minimum >= TARGET else next((f"DATA_INCOMPLETE:EXACT_DATE_BENCHMARK_ALIGNMENT:{row['symbol']}" for row in rows if row["aligned_record_count"] < TARGET), "DATA_INCOMPLETE:EXACT_DATE_BENCHMARK_ALIGNMENT"),
        "production_state_modified": "NO",
    }
    _atomic_write_json(output, payload)
    if payload["status"] != "PASS":
        raise RuntimeError(payload["blocking_reason"])
    return payload


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--universe-file", required=True)
    ap.add_argument("--history-root", default="data/staging/history")
    ap.add_argument("--output", default="artifacts/RATE_TWSE_TAIEX_ALIGNMENT_EVIDENCE.json")
    args = ap.parse_args()
    try:
        result = align(universe_file=Path(args.universe_file), history_root=Path(args.history_root), output=Path(args.output))
        print(json.dumps({"status": result["status"], "alignment": result["twse_taiex_alignment"], "minimum": result["minimum_aligned_sessions"]}))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "FAIL", "reason": str(exc)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
