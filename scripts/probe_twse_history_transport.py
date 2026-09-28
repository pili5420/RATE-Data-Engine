"""Targeted, read-only probe for TWSE historical redirect transport."""
from __future__ import annotations
import argparse, json, os, sys
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.sources.twse import TWSEAdapter, reset_transport_metrics, get_transport_metrics


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--trading-date', required=True)
    ap.add_argument('--output', required=True)
    args = ap.parse_args()
    latest = args.trading_date.replace('-', '')[:6]
    cases = [('2356', '202601'), ('3017', '202603'), ('3036', '202606'), ('2330', latest)]
    adapter = TWSEAdapter()
    reset_transport_metrics()
    results = []
    for symbol, period in cases:
        try:
            result = adapter.fetch_historical_symbol(symbol, period)
            diagnostics = result.get('diagnostics', {})
            requests = diagnostics.get('requests', [])
            results.append({
                'symbol': symbol, 'period': period, 'status': 'PASS',
                'final_endpoint': result.get('endpoint'),
                'final_representation': result.get('representation'),
                'candidate_index': diagnostics.get('candidate_index'),
                'candidate_attempts': diagnostics.get('candidate_attempts', []),
                'redirect_count': diagnostics.get('redirect_count', 0),
                'records': len((result.get('raw_payload') or {}).get('data', [])),
                'content_digest': result.get('content_hash'),
                'parse_status': 'PASS', 'requests': requests,
            })
        except Exception as exc:
            results.append({
                'symbol': symbol, 'period': period, 'status': 'FAIL',
                'final_endpoint': None, 'redirect_count': None, 'records': 0,
                'final_representation': None, 'candidate_index': None,
                'candidate_attempts': getattr(exc, 'candidate_attempts', []),
                'content_digest': None, 'parse_status': str(exc),
                'requests': getattr(exc, 'diagnostics', []),
            })
    csv_route_probe = None
    try:
        csv_result = adapter.fetch_historical_symbol('3036', '202606', force_representation='CSV_OFFICIAL')
        csv_route_probe = {
            'status': 'PASS', 'endpoint': csv_result.get('endpoint'),
            'representation': csv_result.get('representation'),
            'encoding': (csv_result.get('raw_payload') or {}).get('csv_encoding'),
            'headers': (csv_result.get('raw_payload') or {}).get('csv_headers'),
            'records': len((csv_result.get('raw_payload') or {}).get('data', [])),
            'content_digest': csv_result.get('content_hash'),
            'candidate_attempts': (csv_result.get('diagnostics') or {}).get('candidate_attempts', []),
        }
    except Exception as exc:
        csv_route_probe = {'status': 'FAIL', 'reason': str(exc),
                           'candidate_attempts': getattr(exc, 'candidate_attempts', []),
                           'requests': getattr(exc, 'diagnostics', [])}
    out = {
        'artifact': 'RATE_TWSE_HISTORY_TRANSPORT_EVIDENCE',
        'execution_runtime': 'github_actions' if os.getenv('GITHUB_ACTIONS') == 'true' else 'local',
        'workflow_run_id': os.getenv('GITHUB_RUN_ID'),
        'job_id': os.getenv('GITHUB_JOB'),
        'commit_sha': os.getenv('GITHUB_SHA'),
        'trading_date': args.trading_date,
        'max_redirects': 3,
        'approved_hosts': ['www.twse.com.tw'],
        'candidate_representations': ['JSON_PRIMARY', 'JSON_FALLBACK', 'CSV_OFFICIAL'],
        'official_csv_route_verification': {
            'status': csv_route_probe.get('status') if csv_route_probe else 'NOT_OBSERVED',
            'verified_cases': [x['symbol'] + ':' + x['period'] for x in results if x.get('final_representation') == 'CSV_OFFICIAL'],
            'probe': csv_route_probe,
        },
        'transport_request_metrics': get_transport_metrics(),
        'throttle_pattern_classification': ('PATTERN_CONSISTENT_WITH_HOST_THROTTLING_OR_EDGE_POLICY'
                                            if get_transport_metrics().get('bare_307_count', 0) else 'NONE_OBSERVED'),
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
