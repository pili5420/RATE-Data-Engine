from __future__ import annotations

import json
import shutil
import unittest
from pathlib import Path

from scripts.resolve_production_runtime_context import resolve_context
from scripts.validate_production_scheduler_safety import validate
from scripts.publish_production_state_latest import publish_state

WORKFLOWS = [
    Path('.github/workflows/rate_production_0730_scheduler.yml'),
    Path('.github/workflows/rate_production_0930_scheduler.yml'),
    Path('.github/workflows/rate_production_1200_scheduler.yml'),
    Path('.github/workflows/rate_production_1930_scheduler.yml'),
]

class ProductionSchedulerChangeControlTests(unittest.TestCase):
    def test_scheduler_safety_validation_passes(self):
        result = validate()
        self.assertEqual(result['validation_status'], 'PASS')
        self.assertEqual(result['dynamic_trading_date_resolution'], 'PASS')
        self.assertEqual(result['live_previous_state_resolver'], 'PASS')
        self.assertEqual(result['persistent_state_no_reset'], 'PASS')
        self.assertEqual(result['production_persistent_state_reset_count'], 0)
        self.assertEqual(result['cer081_read_only'], 'PASS')
        self.assertEqual(result['push_workflow_dispatch_not_soak_evidence'], 'PASS')

    def test_no_historical_acceptance_date_fallback_or_fixed_main_guard(self):
        for path in WORKFLOWS:
            text = path.read_text(encoding='utf-8')
            self.assertNotIn("inputs.trading_date || '2026-09-18'", text)
            self.assertNotIn('default: "2026-09-18"', text)
            self.assertNotIn('beae3ed542888cc647d64bbcecab7d907a7744aa', text)
            self.assertNotIn('--reset-state-root', text)
            self.assertNotRegex(text, r'RATE_CER07[45678].*ARTIFACT_ID')

    def test_schedule_resolves_dynamic_taiwan_trading_date_and_blocks_missing_live_predecessor(self):
        root = Path("artifacts/test-production-scheduler-change-control")
        try:
            shutil.rmtree(root, ignore_errors=True)
            root.mkdir(parents=True, exist_ok=True)
            context = resolve_context(cadence='09:30', event_name='schedule', dispatch_trading_date=None, state_root=root)
            self.assertEqual(context['trading_date_resolution'], 'DYNAMIC_TAIWAN_TRADING_DATE')
            self.assertNotEqual(context['trading_date'], '2026-09-18')
            self.assertEqual(context['previous_state_resolution'], 'LIVE_PRODUCTION_STATE_STORE')
            if context['runtime_mode'] == 'RUN':
                self.assertEqual(context['validation_status'], 'BLOCKED')
                self.assertEqual(context['blocking_reason'], 'LIVE_PREVIOUS_PRODUCTION_STATE_MISSING')
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_non_trading_day_noop_does_not_require_predecessor(self):
        root = Path("artifacts/test-production-scheduler-change-control")
        try:
            shutil.rmtree(root, ignore_errors=True)
            root.mkdir(parents=True, exist_ok=True)
            context = resolve_context(cadence='07:30', event_name='workflow_dispatch', dispatch_trading_date='2026-09-28', state_root=root)
            self.assertEqual(context['runtime_mode'], 'NOOP_NON_TRADING_DAY')
            self.assertEqual(context['validation_status'], 'PASS')
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_live_state_publish_requires_pass_and_writes_live_pointer(self):
        root = Path("artifacts/test-production-scheduler-change-control")
        try:
            shutil.rmtree(root, ignore_errors=True)
            root.mkdir(parents=True, exist_ok=True)
            evidence = root / 'persist.json'
            evidence.write_text(json.dumps({
                'artifact': 'RATE_CER076_PERSIST_RESULT_EVIDENCE',
                'validation_status': 'PASS',
                'current_state_id': 'rate-state-x',
                'current_state_hash': 'hash-x',
                'previous_state_id': 'rate-state-prev',
                'persist_result': {'status': 'PERSISTED', 'state_entry': {'current_state_id': 'rate-state-x', 'decision_payload_hash': 'hash-x', 'trading_date': '2026-09-29', 'cadence': '09:30'}}
            }), encoding='utf-8')
            result = publish_state(persist_evidence_path=evidence, trading_date='2026-09-29', cadence='09:30', artifacts_root=root)
            self.assertEqual(result['validation_status'], 'PASS')
            self.assertTrue((root / 'production_state/live/2026-09-29/0930/RATE_PRODUCTION_PERSIST_RESULT_EVIDENCE.json').exists())
            latest = json.loads((root / 'RATE_PRODUCTION_STATE_LATEST.json').read_text(encoding='utf-8'))
            self.assertEqual(latest['current_state_id'], 'rate-state-x')
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_live_state_publish_blocks_wrong_date_without_writing_latest(self):
        root = Path("artifacts/test-production-scheduler-change-control")
        try:
            shutil.rmtree(root, ignore_errors=True)
            root.mkdir(parents=True, exist_ok=True)
            evidence = root / 'persist.json'
            evidence.write_text(json.dumps({
                'artifact': 'RATE_CER077_PERSIST_RESULT_EVIDENCE',
                'validation_status': 'PASS',
                'persist_result': {'status': 'PERSISTED', 'state_entry': {'trading_date': '2026-09-29', 'cadence': '12:00'}}
            }), encoding='utf-8')
            result = publish_state(persist_evidence_path=evidence, trading_date='2026-09-30', cadence='12:00', artifacts_root=root)
            self.assertEqual(result['validation_status'], 'BLOCKED')
            self.assertFalse((root / 'RATE_PRODUCTION_STATE_LATEST.json').exists())
        finally:
            shutil.rmtree(root, ignore_errors=True)

if __name__ == '__main__':
    unittest.main()


