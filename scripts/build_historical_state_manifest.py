"""Build the canonical historical readiness manifest."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

TARGET_ALIGNED = 180


def _hash_file(path: Path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def _read_rows(path: Path):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def build(*, universe_file: Path, checkpoint: Path, history_root: Path, output: Path,
          taiex_file: Path | None = None, tpex_benchmark_file: Path | None = None):
    universe = json.loads(universe_file.read_text(encoding="utf-8"))
    cp = json.loads(checkpoint.read_text(encoding="utf-8")) if checkpoint.exists() else {}
    entries = universe.get("symbols", [])
    symbols = [str(x["symbol"]) for x in entries]
    markets = {str(x["symbol"]): x.get("market") for x in entries}
    twse = [s for s in symbols if markets.get(s) == "TWSE"]
    tpex = [s for s in symbols if markets.get(s) == "TPEX"]
    taiex_path = taiex_file or (history_root / "benchmark" / "TAIEX.json")
    taiex_rows = _read_rows(Path(taiex_path))
    taiex_dates = {str(row.get("trade_date")) for row in taiex_rows}
    stock_counts, aligned_counts, hashes = {}, {}, {}
    stock_evidence = {}
    for symbol in symbols:
        path = history_root / "market_daily" / f"{symbol}.json"
        rows = _read_rows(path)
        dates = {str(row.get("trade_date")) for row in rows if row.get("trade_date")}
        stock_counts[symbol] = len(rows)
        aligned_counts[symbol] = len(dates & taiex_dates) if markets.get(symbol) == "TWSE" else 0
        hashes[symbol] = _hash_file(path)
        if markets.get(symbol) == "TWSE":
            stock_evidence[symbol] = {
                "record_count": len(rows),
                "aligned_record_count": aligned_counts[symbol],
                "content_hash": hashes[symbol],
            }
    twse_stock_pass = len(twse) == 25 and all(stock_counts[s] >= TARGET_ALIGNED for s in twse)
    taiex_pass = len(taiex_rows) >= TARGET_ALIGNED
    alignment_pass = len(twse) == 25 and all(aligned_counts[s] >= TARGET_ALIGNED for s in twse)
    result = {
        "artifact": "RATE_STAGING_HISTORICAL_STATE_MANIFEST_V1",
        "status": "PASS" if twse_stock_pass and taiex_pass and alignment_pass else "BLOCKED",
        "historical_acceptance_semantics": "PASS" if twse_stock_pass and taiex_pass and alignment_pass else "BLOCKED",
        "twse_stock_bootstrap_acceptance": "PASS" if twse_stock_pass else "BLOCKED",
        "taiex_benchmark_acceptance": "PASS" if taiex_pass else "BLOCKED",
        "twse_alignment_acceptance": "PASS" if alignment_pass else "BLOCKED",
        "tpex_historical_acceptance": "NOT_RUN",
        "full_historical_acceptance": "HOLD",
        "TWSE_stock_component": "PASS" if twse_stock_pass else "FAIL",
        "TAIEX_benchmark_component": "PASS" if taiex_pass else "FAIL",
        "TWSE_alignment_component": "PASS" if alignment_pass else "FAIL",
        "TPEx_stock_component": "NOT_RUN",
        "TPEx_benchmark_component": "NOT_RUN",
        "universe_digest": universe.get("universe_symbol_digest"),
        "TWSE_symbol_coverage": f"{sum(stock_counts[s] >= TARGET_ALIGNED for s in twse)}/{len(twse)}",
        "TPEx_symbol_coverage": "NOT_RUN",
        "TAIEX_coverage": f"{len(taiex_rows)}/{TARGET_ALIGNED}",
        "TPEx_Index_coverage": "NOT_RUN",
        "raw_session_counts": stock_counts,
        "aligned_session_counts": aligned_counts,
        "content_hashes": hashes,
        "taiex_content_hash": _hash_file(Path(taiex_path)),
        "taiex_record_count": len(taiex_rows),
        "taiex_earliest_date": taiex_rows[0].get("trade_date") if taiex_rows else None,
        "taiex_latest_date": taiex_rows[-1].get("trade_date") if taiex_rows else None,
        "TWSE_alignment_minimum": min((aligned_counts[s] for s in twse), default=0),
        "TWSE_alignment_maximum": max((aligned_counts[s] for s in twse), default=0),
        "stock_evidence": stock_evidence,
        "checkpoint_content_hash": cp.get("content_hash"),
        "materialized_source_checkpoint_digest": cp.get("content_hash"),
        "store_provenance_binding": "PASS" if cp.get("content_hash") else "FAIL",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "production_state_modified": "NO",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--universe-file", required=True)
    ap.add_argument("--checkpoint", required=True)
    ap.add_argument("--history-root", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--taiex-file")
    ap.add_argument("--tpex-benchmark-file")
    args = ap.parse_args()
    result = build(universe_file=Path(args.universe_file), checkpoint=Path(args.checkpoint), history_root=Path(args.history_root), output=Path(args.output), taiex_file=Path(args.taiex_file) if args.taiex_file else None, tpex_benchmark_file=Path(args.tpex_benchmark_file) if args.tpex_benchmark_file else None)
    print(json.dumps({"status": result["status"], "historical_acceptance_semantics": result["historical_acceptance_semantics"]}))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
