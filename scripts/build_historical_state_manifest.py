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


def _market_data_identity(path: Path):
    """Hash normalized market rows without volatile lineage timestamps."""
    rows = _read_rows(path)
    stable = [{k: v for k, v in row.items() if k not in ("source_timestamp", "ingested_at")} for row in rows]
    return _stable_digest(stable) if path.exists() else None


def _read_rows(path: Path):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def _stable_digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


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
    taiex_dates = {str(row.get("trade_date")) for row in taiex_rows if row.get("trade_date")}
    tpex_path = Path(tpex_benchmark_file) if tpex_benchmark_file else (history_root / "benchmark" / "TPEX.json")
    tpex_rows = _read_rows(tpex_path)
    tpex_dates = {str(row.get("trade_date")) for row in tpex_rows if row.get("trade_date")}
    stock_counts, aligned_counts, hashes = {}, {}, {}
    stock_evidence = {}; tpex_evidence = {}
    for symbol in symbols:
        path = history_root / "market_daily" / f"{symbol}.json"
        rows = _read_rows(path)
        dates = {str(row.get("trade_date")) for row in rows if row.get("trade_date")}
        stock_counts[symbol] = len(rows)
        aligned_counts[symbol] = len(dates & (taiex_dates if markets.get(symbol) == "TWSE" else tpex_dates))
        hashes[symbol] = _hash_file(path)
        if markets.get(symbol) == "TWSE":
            stock_evidence[symbol] = {
                "record_count": len(rows),
                "aligned_record_count": aligned_counts[symbol],
                "content_hash": hashes[symbol],
            }
        elif markets.get(symbol) == "TPEX":
            tpex_evidence[symbol] = {"record_count": len(rows), "aligned_record_count": aligned_counts[symbol], "content_hash": hashes[symbol], "market": "TPEX"}
    twse_stock_pass = len(twse) == 25 and all(stock_counts[s] >= TARGET_ALIGNED for s in twse)
    taiex_pass = len(taiex_rows) >= TARGET_ALIGNED
    alignment_pass = len(twse) == 25 and all(aligned_counts[s] >= TARGET_ALIGNED for s in twse)
    tpex_present = bool(tpex_rows) or any(stock_counts.get(s, 0) > 0 for s in tpex)
    tpex_stock_pass = len(tpex) == 5 and all(stock_counts[s] >= TARGET_ALIGNED for s in tpex)
    tpex_benchmark_pass = len(tpex_rows) >= TARGET_ALIGNED
    tpex_alignment_pass = len(tpex) == 5 and all(aligned_counts[s] >= TARGET_ALIGNED for s in tpex)
    all_components_pass = twse_stock_pass and taiex_pass and alignment_pass and tpex_stock_pass and tpex_benchmark_pass and tpex_alignment_pass
    historical_digest = None
    if all_components_pass:
        historical_digest = _stable_digest({
            "universe_digest": universe.get("universe_symbol_digest"),
            "twse_store_digests": {s: _market_data_identity(history_root / "market_daily" / f"{s}.json") for s in sorted(twse)},
            "tpex_store_digests": {s: _market_data_identity(history_root / "market_daily" / f"{s}.json") for s in sorted(tpex)},
            "taiex_digest": _market_data_identity(Path(taiex_path)), "tpex_index_digest": _market_data_identity(tpex_path),
            "alignment_counts": {s: aligned_counts[s] for s in sorted(symbols)},
            "schema_versions": ["RATE-STAGING-HISTORICAL-STATE-MANIFEST-V1"],
        })
    status = "PASS" if all_components_pass else ("BLOCKED" if tpex_present or not (twse_stock_pass and taiex_pass and alignment_pass) else "PASS")
    result = {
        "artifact": "RATE_STAGING_HISTORICAL_STATE_MANIFEST_V1",
        "status": status,
        "historical_acceptance_semantics": "PASS" if all_components_pass else ("HOLD" if tpex_present else ("PASS" if twse_stock_pass and taiex_pass and alignment_pass else "BLOCKED")),
        "twse_stock_bootstrap_acceptance": "PASS" if twse_stock_pass else "BLOCKED",
        "taiex_benchmark_acceptance": "PASS" if taiex_pass else "BLOCKED",
        "twse_alignment_acceptance": "PASS" if alignment_pass else "BLOCKED",
        "tpex_historical_acceptance": "PASS" if tpex_stock_pass and tpex_benchmark_pass and tpex_alignment_pass else ("HOLD" if not tpex_present else "BLOCKED"),
        "full_historical_acceptance": "PASS" if all_components_pass else "HOLD",
        "TWSE_stock_component": "PASS" if twse_stock_pass else "FAIL",
        "TAIEX_benchmark_component": "PASS" if taiex_pass else "FAIL",
        "TWSE_alignment_component": "PASS" if alignment_pass else "FAIL",
        "TPEx_stock_component": "PASS" if tpex_stock_pass else ("NOT_RUN" if not tpex_present else "FAIL"),
        "TPEx_benchmark_component": "PASS" if tpex_benchmark_pass else ("NOT_RUN" if not tpex_present else "FAIL"),
        "TPEx_alignment_component": "PASS" if tpex_alignment_pass else ("NOT_RUN" if not tpex_present else "FAIL"),
        "universe_digest": universe.get("universe_symbol_digest"),
        "TWSE_symbol_coverage": f"{sum(stock_counts[s] >= TARGET_ALIGNED for s in twse)}/{len(twse)}",
        "TPEx_symbol_coverage": f"{sum(stock_counts[s] >= TARGET_ALIGNED for s in tpex)}/{len(tpex)}" if tpex_present else "NOT_RUN",
        "TAIEX_coverage": f"{len(taiex_rows)}/{TARGET_ALIGNED}",
        "TPEx_Index_coverage": f"{len(tpex_rows)}/{TARGET_ALIGNED}" if tpex_present else "NOT_RUN",
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
        "tpex_stock_evidence": tpex_evidence,
        "tpex_index_record_count": len(tpex_rows),
        "tpex_index_content_hash": _hash_file(tpex_path),
        "tpex_index_earliest_date": tpex_rows[0].get("trade_date") if tpex_rows else None,
        "tpex_index_latest_date": tpex_rows[-1].get("trade_date") if tpex_rows else None,
        "checkpoint_content_hash": cp.get("content_hash"),
        "materialized_source_checkpoint_digest": cp.get("content_hash"),
        "store_provenance_binding": "PASS" if cp.get("content_hash") else "FAIL",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "production_state_modified": "NO",
        "Stock_Historical_Coverage": f"{sum(stock_counts[s] >= TARGET_ALIGNED for s in symbols)}/{len(symbols)}",
        "Benchmark_Historical_Coverage": f"{sum((len(taiex_rows) >= TARGET_ALIGNED and markets.get(s) == 'TWSE') or (len(tpex_rows) >= TARGET_ALIGNED and markets.get(s) == 'TPEX') for s in symbols)}/{len(symbols)}",
        "Exact_Date_Aligned_ge_180": f"{sum(aligned_counts[s] >= TARGET_ALIGNED for s in symbols)}/{len(symbols)}",
        "TPEx_alignment_minimum": min((aligned_counts[s] for s in tpex), default=0) if tpex_present else None,
        "TPEx_alignment_maximum": max((aligned_counts[s] for s in tpex), default=0) if tpex_present else None,
        "RATE_FULL_HISTORICAL_STATE_DIGEST": historical_digest,
        "full_historical_state_digest": historical_digest,
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
