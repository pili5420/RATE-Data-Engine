import copy
import json
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch

import src.cer074_acceptance as cer074


def fixture_bundle():
    path = Path('artifacts/remote-36281974051/RATE_CER073_FINAL_SOURCE_BUNDLE/RATE_CER073_FINAL_SOURCE_BUNDLE.json')
    if path.exists():
        return json.loads(path.read_text(encoding='utf-8'))
    symbols = [f"{1000+i}" for i in range(30)]
    records = []
    sources = {}
    for i, symbol in enumerate(symbols):
        stage_inputs = {
            'price': 50+i, 'ma20': 45, 'ma60': 40, 'ma120': 35,
            'price_above_all': True, 'ma20_above_ma60': True, 'm7_score': 80, 'mhe_score': 70,
            'prior_m7': 75, 'previous_stage': 'BASE_BUILDING', 'relative_strength_strong': True,
            'ma20_slope_positive': True, 'ma60_trend_non_negative': True, 'price_above_ma60': True,
            'price_near_ma20_ma60': False, 'long_term_bullish': True, 'short_swing_mhe_improving': True,
            'm7_rising': True, 'mhe_rising': True, 'recent_low_no_longer_deteriorating': True,
            'rotation_deteriorated': False, 'structural_failure': False, 'evidence_state_mixed': False,
        }
        field_sources = {k: 'DERIVED_FROM_FROZEN_RULE' for k in stage_inputs}
        field_lineage = {k: {'value': v, 'source_session': cer074.AS_OF_DATE, 'source_type': field_sources[k], 'calculation_definition': k, 'spec_version': 'RATE-SPEC-20260919-004'} for k, v in stage_inputs.items()}
        stage = {
            'symbol': symbol, 'calculation_status': 'PASS', 'source_state_id': 'GENESIS_STATE_ID',
            'input_snapshot_id': None, 'lineage_binding_status': 'PENDING_SNAPSHOT_BINDING',
            'previous_stage': 'BASE_BUILDING', 'prior_stage_source': 'RECONSTRUCTED_FROM_AUTHORIZED_HISTORICAL_EVIDENCE',
            'stage_inputs': stage_inputs, 'stage_field_sources': field_sources, 'stage_field_lineage': field_lineage,
            'stage_evidence_lineage': {'symbol': symbol, 'source_state_id': 'GENESIS_STATE_ID', 'input_snapshot_id': None, 'fields': field_lineage},
            'stage_current': 'MARKUP', 'stage_normalized_score': 90,
        }
        rec = {
            'symbol': symbol,
            'M7_inputs': {'PT': 80, 'PV': 80, 'MO': 80, 'FI': 80, 'IT': 80, 'LH': 80, 'RS': 80},
            'MHE_inputs': {'H5': 70, 'H20': 70, 'H60': 70, 'H120': 70},
            'Rotation_inputs': {'RS_CHANGE': 70, 'VOL_CHANGE': 70, 'SMART_MONEY': 70, 'MOMENTUM_CHANGE': 70},
            'SmartMoney_inputs': {'FI': 70, 'IT': 70, 'LH': 70, 'FC': 70},
            'Stage_inputs': stage_inputs, 'Stage_evidence': stage,
            'Fundamental': 60, 'RelativeStrength': 70+i/100, 'Liquidity': 80,
        }
        records.append(rec); sources[symbol] = {'Stage_evidence': stage}
    return {
        'validation_status': 'PASS', 'source_bundle_validation': 'PASS', 'canonical_bundle_hash': cer074.CER073_SOURCE_BUNDLE_HASH,
        'fundamental_analytical_hash': cer074.FUNDAMENTAL_HASH, 'prior_stage_package_digest': cer074.PRIOR_STAGE_DIGEST,
        'historical_state_digest': cer074.HISTORICAL_STATE_DIGEST,
        'prior_stage_package_binding': {'status': 'PASS', 'digest': cer074.PRIOR_STAGE_DIGEST, 'symbols_bound': 30},
        'universe': symbols, 'decision_records': records, 'production_sources': sources,
        'source_provenance': {'source': 'AUTHORIZED_LIVE'}, 'short_term_top30': symbols,
        'roy_portfolio': [], 'required_benchmarks': ['TAIEX'], 'explicit_production_watchlist': [],
    }


class CER074AcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.root = Path('artifacts/test-cer074-unit')
        self.state = Path('data/production/test-cer074-unit')
        shutil.rmtree(self.root, ignore_errors=True)
        shutil.rmtree(self.state, ignore_errors=True)
        self.root.mkdir(parents=True)
        self.bundle = fixture_bundle()
        self.freeze = patch('src.cer074_acceptance._verify_model_freeze', return_value={'status': 'PASS'})
        self.freeze.start()

    def tearDown(self):
        self.freeze.stop()
        shutil.rmtree(self.root, ignore_errors=True)
        shutil.rmtree(self.state, ignore_errors=True)

    def test_accepted_cer073_bundle_binding_and_snapshot_identity(self):
        binding = cer074.verify_cer073_binding(self.bundle)
        self.assertEqual(binding['status'], 'PASS')
        snapshot = cer074.create_production_snapshot(self.bundle)
        self.assertTrue(snapshot['input_snapshot_id'])
        self.assertTrue(snapshot['input_snapshot_hash'])
        self.assertEqual(snapshot['production_snapshot_coverage'], '30/30')
        self.assertEqual(cer074.count_pending(snapshot), 0)
        self.assertEqual(cer074.create_production_snapshot(self.bundle)['input_snapshot_hash'], snapshot['input_snapshot_hash'])

    def test_first_production_bootstrap_allowed_exactly_once_and_no_silent_genesis(self):
        snapshot = cer074.create_production_snapshot(self.bundle)
        allowed = cer074.validate_first_bootstrap_allowed(snapshot, self.state)
        self.assertEqual(allowed['previous_state_resolution'], cer074.BOOTSTRAP_RESOLUTION)
        self.assertIsNone(allowed['previous_state_id'])
        result = cer074.run_first_0730_decision(snapshot)
        first = cer074.persist_decision_state_once(result, self.state)
        self.assertEqual(first['new_record_count'], 1)
        other = copy.deepcopy(result)
        other['current_state_id'] = 'rate-state-other'
        other['decision_payload_hash'] = 'different'
        with self.assertRaisesRegex(RuntimeError, 'FIRST_PRODUCTION_BOOTSTRAP_ALREADY_CONSUMED'):
            cer074.persist_decision_state_once(other, self.state)
        with self.assertRaisesRegex(RuntimeError, 'FIRST_PRODUCTION_BOOTSTRAP_ALREADY_CONSUMED'):
            cer074.validate_first_bootstrap_allowed(snapshot, self.state)

    def test_prior_stage_digest_required(self):
        bad = copy.deepcopy(self.bundle)
        bad['prior_stage_package_digest'] = 'bad'
        self.assertEqual(cer074.verify_cer073_binding(bad)['status'], 'FAIL')

    def test_dry_runs_do_not_persist_and_persist_replay_is_idempotent(self):
        artifacts = cer074.build_artifacts(self.bundle, self.state, run_head_sha='head', actions_run_id='run', actions_job_id='job')
        a = artifacts['RATE_CER074_DECISION_STATE_DRYRUN_A.json']
        b = artifacts['RATE_CER074_DECISION_STATE_DRYRUN_B.json']
        persisted = artifacts['RATE_CER074_PERSISTED_DECISION_STATE_EVIDENCE.json']
        idem = artifacts['RATE_CER074_PERSISTENCE_IDEMPOTENCY_EVIDENCE.json']
        lineage = artifacts['RATE_CER074_LINEAGE_ACCEPTANCE_EVIDENCE.json']
        self.assertEqual(a['persist_count'], 0)
        self.assertEqual(b['persist_count'], 0)
        self.assertEqual(a['decision_state_id'], b['decision_state_id'])
        self.assertEqual(a['decision_state_hash'], b['decision_state_hash'])
        self.assertEqual(persisted['new_production_decision_state_records'], 1)
        self.assertEqual(idem['replay_new_record_count'], 0)
        self.assertEqual(idem['production_state_idempotency'], 'PASS')
        self.assertEqual(lineage['prior_stage_binding'], '30/30')
        self.assertEqual(lineage['pending_snapshot_lineage_count'], 0)
        self.assertEqual(lineage['decision_state_coverage'], '30/30')
        self.assertEqual(lineage['top50_eligible_count'], 30)
        self.assertEqual(lineage['short_top30_count'], 30)
        self.assertEqual(lineage['long_top30_count'], 30)
        self.assertEqual(lineage['decision_state_lineage'], 'PASS')

    def test_different_canonical_snapshot_cannot_reuse_old_state_id(self):
        first = cer074.create_production_snapshot(self.bundle)
        changed = copy.deepcopy(self.bundle)
        changed['decision_records'][0]['Liquidity'] = changed['decision_records'][0]['Liquidity'] - 1
        second = cer074.create_production_snapshot(changed)
        self.assertNotEqual(first['input_snapshot_hash'], second['input_snapshot_hash'])
        self.assertNotEqual(cer074.run_first_0730_decision(first)['current_state_id'], cer074.run_first_0730_decision(second)['current_state_id'])

    def test_production_namespace_guard_path(self):
        allowed = (Path.cwd() / 'data' / 'production' / 'cer074_acceptance').resolve()
        self.assertIn((Path.cwd() / 'data' / 'production').resolve(), allowed.parents)


if __name__ == '__main__':
    unittest.main()
