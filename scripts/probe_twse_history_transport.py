"""Targeted, read-only probe for TWSE historical redirect transport."""
from __future__ import annotations
import argparse, json, os, sys
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.sources.twse import TWSEAdapter


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--trading-date', required=True)
    ap.add_argument('--output', required=True)
    args = ap.parse_args()
    latest = args.trading_date.replace('-', '')[:6]
    cases = [('2356', '202601'), ('3017', '202603'), ('2330', latest)]
    adapter = TWSEAdapter()
    results = []
    for symbol, period in cases:
        try:
            result = adapter.fetch_historical_symbol(symbol, period)
            diagnostics = result.get('diagnostics', {})
            requests = diagnostics.get('requests', [])
            results.append({
                'symbol': symbol, 'period': period, 'status': 'PASS',
                'final_endpoint': result.get('endpoint'),
                'redirect_count': diagnostics.get('redirect_count', 0),
                'records': len((result.get('raw_payload') or {}).get('data', [])),
                'content_digest': result.get('content_hash'),
                'parse_status': 'PASS', 'requests': requests,
            })
        except Exception as exc:
            results.append({
                'symbol': symbol, 'period': period, 'status': 'FAIL',
                'final_endpoint': None, 'redirect_count': None, 'records': 0,
                'content_digest': None, 'parse_status': str(exc),
                'requests': getattr(exc, 'diagnostics', []),
            })
    out = {
        'artifact': 'RATE_TWSE_HISTORY_TRANSPORT_EVIDENCE',
        'execution_runtime': 'github_actions' if os.getenv('GITHUB_ACTIONS') == 'true' else 'local',
        'workflow_run_id': os.getenv('GITHUB_RUN_ID'),
        'job_id': os.getenv('GITHUB_JOB'),
        'commit_sha': os.getenv('GITHUB_SHA'),
        'trading_date': args.trading_date,
        'max_redirects': 3,
        'approved_hosts': ['www.twse.com.tw'],
        'results': results,
        'status': 'PASS' if all(x['status'] == 'PASS' for x in results) else 'FAIL',
        'retrieval_timestamp': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
    }
    path = Path(args.output); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(out, ensure_ascii=False))
    return 0 if out['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
