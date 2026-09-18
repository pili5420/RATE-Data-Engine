"""Bounded, resumable TWSE historical bootstrap.

This command owns only historical source acquisition.  It deliberately does
not import or execute any RATE feature/model calculation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import build_live_source_bundle as bundle
from src.historical_store import normalize_stock_record
from src.benchmark_history import normalize_twse_date
from src.sources.twse import TWSEAdapter, reset_transport_metrics, get_transport_metrics

TARGET_RAW_SESSIONS = 190
DEFAULT_MAX_PERIODS = 12
DEFAULT_MAX_RUNTIME_SECONDS = 600


def _periods(end: date):
    return list(bundle._month_cursor(end))


def _normalized_period(adapter, symbol: str, period: str):
    result = adapter.fetch_historical_symbol(symbol, period)
    rows = bundle._rows(result.get('raw_payload'))
    records, seen = [], set()
    for row in rows:
        raw_date = bundle._pick(row, 'trade_date', 'Date', '日期')
        if raw_date is None:
            continue
        trade_date = normalize_twse_date(raw_date)
        if trade_date in seen:
            continue
        try:
            record = normalize_stock_record({
                'symbol': symbol, 'market': 'TWSE', 'trade_date': trade_date,
                'open': bundle._pick(row, 'open', 'OpeningPrice', '開盤價', 'Open'),
                'high': bundle._pick(row, 'high', 'HighestPrice', '最高價', 'High'),
                'low': bundle._pick(row, 'low', 'LowestPrice', '最低價', 'Low'),
                'close': bundle._pick(row, 'close', 'ClosingPrice', '收盤價', 'Close'),
                'volume': bundle._pick(row, 'volume', 'TradeVolume', '成交股數', 'TradingShares'),
                'turnover': bundle._pick(row, 'turnover', 'TradeValue', '成交金額', 'TransactionAmount'),
            }, source='TWSE_STOCK_DAY', source_timestamp=result.get('source_timestamp'),
               ingested_at=result.get('retrieval_timestamp'))
        except (ValueError, TypeError):
            continue
        records.append(record); seen.add(trade_date)
    records.sort(key=lambda row: row['trade_date'])
    return records


def _entry_key(symbol, period):
    return f'{symbol}:{period}'


def _records_for_symbol(checkpoint, symbol):
    rows = {}
    for entry in checkpoint.get('months', {}).values():
        if isinstance(entry, dict) and entry.get('symbol') == symbol:
            for row in entry.get('records', []):
                rows[row.get('trade_date')] = row
    return sorted((x for x in rows.values() if x.get('trade_date')), key=lambda row: row['trade_date'])


def _evidence(path, context, status, reason=None):
    progress = context['progress']
    checkpoint = context['checkpoint']
    completed = [s for s, n in progress['raw_sessions_by_symbol'].items() if n >= TARGET_RAW_SESSIONS]
    payload = {
        'artifact': 'RATE_TWSE_HISTORY_BOOTSTRAP_EVIDENCE', 'status': status, 'blocking_reason': reason,
        'chunk_sequence': context['chunk_sequence'],
        'checkpoint_digest_before': context['checkpoint_digest_before'],
        'checkpoint_digest_after': checkpoint.get('content_hash'),
        'periods_loaded_from_checkpoint': context['loaded'],
        'periods_retrieved_this_chunk': context['retrieved'],
        'periods_newly_validated': context['validated'],
        'periods_remaining': max(0, context['required_periods'] - context['loaded'] - context['retrieved']),
        'completed_symbols': sorted(completed),
        'current_symbol': progress.get('current_symbol'), 'current_period': progress.get('current_period'),
        'last_successful_period': progress.get('last_successful_period'),
        'raw_sessions_by_symbol': progress['raw_sessions_by_symbol'],
        'aligned_sessions_by_symbol': progress['aligned_sessions_by_symbol'],
        'transport_request_metrics': get_transport_metrics(),
        'run_id': os.getenv('GITHUB_RUN_ID'), 'run_attempt': os.getenv('GITHUB_RUN_ATTEMPT'),
        'head_sha': os.getenv('GITHUB_SHA'), 'retrieval_timestamp': bundle._now(),
        'checkpoint_namespace': str(context['checkpoint_path']), 'production_state_modified': 'NO',
    }
    bundle._atomic_write_json(Path(path), payload)
    return payload


def validate_checkpoint(path, universe_digest):
    return bundle.validate_checkpoint(Path(path), universe_digest)


def run(*, trading_date: str, universe_file: Path, checkpoint_path: Path, evidence_path: Path,
        max_new_periods: int = DEFAULT_MAX_PERIODS, max_runtime_seconds: int = DEFAULT_MAX_RUNTIME_SECONDS,
        chunk_sequence: int = 1):
    reset_transport_metrics()
    universe_obj = json.loads(Path(universe_file).read_text(encoding='utf-8'))
    universe = [x['symbol'] for x in universe_obj.get('symbols', []) if x.get('market') == 'TWSE']
    universe_digest = universe_obj.get('universe_symbol_digest')
    if not universe or not universe_digest:
        raise RuntimeError('INVALID_PRODUCTION_UNIVERSE_AUTHORITY')
    checkpoint = bundle._load_checkpoint(Path(checkpoint_path), universe_digest)
    context = {
        'checkpoint_path': Path(checkpoint_path), 'checkpoint': checkpoint,
        'checkpoint_digest_before': checkpoint.get('content_hash'), 'chunk_sequence': chunk_sequence,
        'loaded': 0, 'retrieved': 0, 'validated': 0,
        'required_periods': max(1, len(universe) * len(_periods(date.fromisoformat(trading_date)))),
        'progress': {'current_symbol': None, 'current_period': None, 'last_successful_period': None,
                     'raw_sessions_by_symbol': {}, 'aligned_sessions_by_symbol': {}},
    }
    # Evidence exists before the first network request and is atomically updated.
    _evidence(evidence_path, context, 'CHUNK_COMPLETE_MORE_WORK')
    adapter = TWSEAdapter(); started = time.monotonic()
    periods = _periods(date.fromisoformat(trading_date))
    try:
        for symbol in sorted(universe):
            existing = _records_for_symbol(checkpoint, symbol)
            context['progress']['raw_sessions_by_symbol'][symbol] = len(existing)
            context['progress']['aligned_sessions_by_symbol'][symbol] = len(existing)
            for period in periods:
                context['progress']['current_symbol'] = symbol; context['progress']['current_period'] = period
                key = _entry_key(symbol, period)
                cached = checkpoint.get('months', {}).get(key)
                if isinstance(cached, dict) and cached.get('validation_status') == 'PASS':
                    context['loaded'] += 1
                    context['progress']['last_successful_period'] = period
                    if len(_records_for_symbol(checkpoint, symbol)) >= TARGET_RAW_SESSIONS:
                        break
                    continue
                if context['retrieved'] >= max_new_periods or time.monotonic() - started >= max_runtime_seconds:
                    _evidence(evidence_path, context, 'CHUNK_COMPLETE_MORE_WORK'); return context
                records = _normalized_period(adapter, symbol, period)
                canonical = json.dumps(records, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
                checkpoint.setdefault('months', {})[key] = {
                    'symbol': symbol, 'market': 'TWSE', 'year_month': period, 'provider': 'TWSE',
                    'dataset': 'STOCK_DAY', 'records': records,
                    'content_hash': hashlib.sha256(canonical).hexdigest(), 'validation_status': 'PASS',
                }
                bundle._save_checkpoint(checkpoint_path, checkpoint)
                context['retrieved'] += 1; context['validated'] += 1
                context['progress']['last_successful_period'] = period
                context['progress']['raw_sessions_by_symbol'][symbol] = len(_records_for_symbol(checkpoint, symbol))
                context['progress']['aligned_sessions_by_symbol'][symbol] = context['progress']['raw_sessions_by_symbol'][symbol]
                _evidence(evidence_path, context, 'CHUNK_COMPLETE_MORE_WORK')
                if context['retrieved'] >= max_new_periods or time.monotonic() - started >= max_runtime_seconds:
                    _evidence(evidence_path, context, 'CHUNK_COMPLETE_MORE_WORK'); return context
                if all(context['progress']['raw_sessions_by_symbol'].get(s, 0) >= TARGET_RAW_SESSIONS for s in universe):
                    _evidence(evidence_path, context, 'BOOTSTRAP_COMPLETE'); return context
        status = 'BOOTSTRAP_COMPLETE' if all(context['progress']['raw_sessions_by_symbol'].get(s, 0) >= TARGET_RAW_SESSIONS for s in universe) else 'CHUNK_COMPLETE_MORE_WORK'
        _evidence(evidence_path, context, status); return context
    except Exception as exc:
        bundle._save_checkpoint(checkpoint_path, checkpoint)
        status = 'TEMPORARY_SOURCE_UNAVAILABLE' if 'TWSE_HOST_TEMPORARILY_UNAVAILABLE' in str(exc) else 'FATAL_DATA_INTEGRITY_FAILURE'
        _evidence(evidence_path, context, status, str(exc))
        if status == 'TEMPORARY_SOURCE_UNAVAILABLE':
            return context | {'status': status, 'blocking_reason': str(exc)}
        raise


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--trading-date', required=True); ap.add_argument('--universe-file', required=True)
    ap.add_argument('--checkpoint', default=os.getenv('RATE_TWSE_BOOTSTRAP_CHECKPOINT', 'data/staging/history_bootstrap/RATE_TWSE_HISTORY_BOOTSTRAP_CHECKPOINT_V1.json'))
    ap.add_argument('--evidence-output', default='artifacts/RATE_TWSE_HISTORY_BOOTSTRAP_EVIDENCE.json')
    ap.add_argument('--max-new-periods', type=int, default=int(os.getenv('MAX_NEW_PERIODS_PER_CHUNK', DEFAULT_MAX_PERIODS)))
    ap.add_argument('--max-runtime-seconds', type=int, default=int(os.getenv('MAX_CHUNK_RUNTIME_SECONDS', DEFAULT_MAX_RUNTIME_SECONDS)))
    ap.add_argument('--chunk-sequence', type=int, default=int(os.getenv('BOOTSTRAP_CHUNK_SEQUENCE', '1')))
    args = ap.parse_args()
    try:
        result = run(trading_date=args.trading_date, universe_file=Path(args.universe_file), checkpoint_path=Path(args.checkpoint), evidence_path=Path(args.evidence_output), max_new_periods=args.max_new_periods, max_runtime_seconds=args.max_runtime_seconds, chunk_sequence=args.chunk_sequence)
        status = result.get('status') or 'BOOTSTRAP_COMPLETE'
        print(json.dumps({'status': status, 'periods_retrieved': result['retrieved'], 'periods_loaded': result['loaded']}))
        return 0
    except Exception as exc:
        print(json.dumps({'status': 'FATAL_DATA_INTEGRITY_FAILURE', 'reason': str(exc)})); return 1


if __name__ == '__main__':
    raise SystemExit(main())
