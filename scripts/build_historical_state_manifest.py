"""Build the auditable historical completion manifest from persisted state."""
from __future__ import annotations
import argparse, hashlib, json
from datetime import datetime, timezone
from pathlib import Path

TARGET_ALIGNED = 180

def _hash_file(path: Path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None

def build(*, universe_file: Path, checkpoint: Path, history_root: Path, output: Path,
          taiex_file: Path | None = None, tpex_benchmark_file: Path | None = None):
    universe = json.loads(universe_file.read_text(encoding='utf-8'))
    cp = json.loads(checkpoint.read_text(encoding='utf-8')) if checkpoint.exists() else {}
    symbols = [str(x['symbol']) for x in universe.get('symbols', [])]
    markets = {str(x['symbol']): x.get('market') for x in universe.get('symbols', [])}
    twse = [s for s in symbols if markets.get(s) == 'TWSE']
    tpex = [s for s in symbols if markets.get(s) == 'TPEX']
    stock_counts, aligned_counts, hashes = {}, {}, {}; all_dates = []
    benchmark_files = {
        'TWSE': taiex_file or (history_root / 'benchmark' / 'TAIEX.json'),
        'TPEX': tpex_benchmark_file or (history_root / 'benchmark' / 'TPEX.json'),
    }
    benchmark_dates = {}
    for market, path in benchmark_files.items():
        try:
            benchmark_dates[market] = {str(x.get('trade_date')) for x in json.loads(Path(path).read_text(encoding='utf-8'))}
        except (OSError, json.JSONDecodeError, TypeError):
            benchmark_dates[market] = set()
    for symbol in symbols:
        p = history_root / 'market_daily' / f'{symbol}.json'
        rows = json.loads(p.read_text(encoding='utf-8')) if p.exists() else []
        all_dates.extend(str(x.get('trade_date')) for x in rows if x.get('trade_date'))
        stock_counts[symbol] = len(rows); aligned_counts[symbol] = sum(1 for x in rows if x.get('trade_date') in benchmark_dates.get(markets.get(symbol), set()))
        hashes[symbol] = _hash_file(p)
    def benchmark(path):
        if not path or not path.exists(): return {'record_count': 0, 'hash': None}
        rows = json.loads(path.read_text(encoding='utf-8')); return {'record_count': len(rows), 'hash': _hash_file(path)}
    taiex = benchmark(Path(benchmark_files['TWSE'])); tpex_b = benchmark(Path(benchmark_files['TPEX']))
    result = {
        'artifact': 'RATE_STAGING_HISTORICAL_STATE_MANIFEST_V1',
        'status': 'PASS' if (len([s for s in twse if stock_counts[s] >= TARGET_ALIGNED]) == len(twse)
                             and len([s for s in tpex if stock_counts[s] >= TARGET_ALIGNED]) == len(tpex)
                             and taiex['record_count'] >= TARGET_ALIGNED and tpex_b['record_count'] >= TARGET_ALIGNED) else 'BLOCKED',
        'universe_digest': universe.get('universe_symbol_digest'),
        'TWSE_symbol_coverage': f"{sum(stock_counts[s] >= TARGET_ALIGNED for s in twse)}/{len(twse)}",
        'TPEx_symbol_coverage': f"{sum(stock_counts[s] >= TARGET_ALIGNED for s in tpex)}/{len(tpex)}",
        'TAIEX_coverage': f"{int(taiex['record_count'] >= TARGET_ALIGNED)}/1",
        'TPEx_Index_coverage': f"{int(tpex_b['record_count'] >= TARGET_ALIGNED)}/1",
        'raw_session_counts': stock_counts, 'aligned_session_counts': aligned_counts,
        'content_hashes': hashes, 'taiex_content_hash': taiex['hash'], 'tpex_index_content_hash': tpex_b['hash'],
        'earliest_date': min(all_dates) if all_dates else None, 'latest_date': max(all_dates) if all_dates else None,
        'generated_at': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
        'checkpoint_content_hash': cp.get('content_hash'),
    }
    output.parent.mkdir(parents=True, exist_ok=True); output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return result

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--universe-file', required=True); ap.add_argument('--checkpoint', required=True); ap.add_argument('--history-root', required=True); ap.add_argument('--output', required=True)
    a = ap.parse_args(); result = build(universe_file=Path(a.universe_file), checkpoint=Path(a.checkpoint), history_root=Path(a.history_root), output=Path(a.output)); print(json.dumps({'status': result['status']})); return 0 if result['status'] == 'PASS' else 1

if __name__ == '__main__': raise SystemExit(main())
