"""Exact-date TPEx stock ↔ TPEx Index alignment (no carry-forward)."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.bootstrap_tpex_history import TPEx_SYMBOLS
from scripts.build_live_source_bundle import _atomic_write_json

TARGET = 180


def align(*, history_root: Path, output: Path):
    bench_path = history_root / "benchmark" / "TPEX.json"
    benchmark = json.loads(bench_path.read_text(encoding="utf-8")) if bench_path.exists() else []
    benchmark_dates = {str(row.get("trade_date")) for row in benchmark if row.get("trade_date")}
    rows = []
    try:
        for symbol in TPEx_SYMBOLS:
            path = history_root / "market_daily" / f"{symbol}.json"
            stock = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
            if any(row.get("market") != "TPEX" for row in stock):
                raise RuntimeError(f"TPEX_MARKET_IDENTITY_FAILURE:{symbol}")
            stock_dates = {str(row.get("trade_date")) for row in stock if row.get("trade_date")}
            aligned = sorted(stock_dates & benchmark_dates)
            row = {"symbol": symbol, "market": "TPEX", "stock_record_count": len(stock), "benchmark_record_count": len(benchmark), "aligned_record_count": len(aligned), "stock_only_dates": sorted(stock_dates - benchmark_dates), "benchmark_only_dates": sorted(benchmark_dates - stock_dates), "earliest_aligned_date": aligned[0] if aligned else None, "latest_aligned_date": aligned[-1] if aligned else None}
            rows.append(row)
            if len(aligned) < TARGET:
                raise RuntimeError(f"DATA_INCOMPLETE:TPEX_EXACT_DATE_BENCHMARK_ALIGNMENT:{symbol}")
        minimum = min(row["aligned_record_count"] for row in rows); maximum = max(row["aligned_record_count"] for row in rows)
        payload = {"artifact": "RATE_TPEX_INDEX_ALIGNMENT_EVIDENCE", "status": "PASS", "symbol_rows": rows, "tpex_index_alignment": "5/5", "minimum_aligned_sessions": minimum, "maximum_aligned_sessions": maximum, "all_symbols_ge_180": True, "exact_date_inner_join": True, "carry_forward_used": False, "synthetic_benchmark_rows": False, "production_state_modified": "NO", "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")}
    except Exception as exc:
        minimum = min((row["aligned_record_count"] for row in rows), default=0); maximum = max((row["aligned_record_count"] for row in rows), default=0)
        payload = {"artifact": "RATE_TPEX_INDEX_ALIGNMENT_EVIDENCE", "status": "FAIL", "symbol_rows": rows, "tpex_index_alignment": f"{sum(row['aligned_record_count'] >= TARGET for row in rows)}/5", "minimum_aligned_sessions": minimum, "maximum_aligned_sessions": maximum, "all_symbols_ge_180": False, "exact_date_inner_join": True, "carry_forward_used": False, "synthetic_benchmark_rows": False, "blocking_reason": str(exc), "production_state_modified": "NO", "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")}
    _atomic_write_json(output, payload)
    return payload


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--history-root", default="data/staging/history"); ap.add_argument("--output", default="artifacts/RATE_TPEX_INDEX_ALIGNMENT_EVIDENCE.json"); args = ap.parse_args()
    result = align(history_root=Path(args.history_root), output=Path(args.output)); print(json.dumps({"status": result["status"], "alignment": result["tpex_index_alignment"], "minimum": result["minimum_aligned_sessions"]})); return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__": raise SystemExit(main())
