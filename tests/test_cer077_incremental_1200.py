import copy
import json
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch

import src.cer077_incremental_1200 as cer077
from tests.test_cer076_incremental_0930 import cer076_source_bundle_fixture, cer076_cer074_persisted_fixture, cer075_persisted_fixture

CER076_PERSISTED = [
    Path('artifacts/accepted/cer076/persist_result/RATE_CER076_PERSIST_RESULT_EVIDENCE.json'),
    Path('artifacts/remote-36304601795/RATE_CER076_PERSIST_RESULT_EVIDENCE/RATE_CER076_PERSIST_RESULT_EVIDENCE.json'),
]


def cer076_persisted_fixture():
    for path in CER076_PERSISTED:
        if path.exists():
            return json.loads(path.read_text(encoding='utf-8'))
    return {
        'validation_status': 'PASS',
        'current_state_id': cer077.PREVIOUS_0930_STATE_ID,
        'current_state_hash': cer077.PREVIOUS_0930_STATE_HASH,
        'persist_result': {'status':'PERSISTED','new_record_count':1,'state_entry': {
            'current_state_id': cer077.PREVIOUS_0930_STATE_ID,
            'decision_payload_hash': cer077.PREVIOUS_0930_STATE_HASH,
            'decision_time': '09:30',
            'execution_scope': cer077.EXECUTION_SCOPE,
            'previous_state_id': cer077.PREVIOUS_0730_STATE_ID,
            'previous_state_resolution': 'PERSISTED_PRODUCTION_STATE',
            'source_bundle_hash': cer077.CER073_SOURCE_BUNDLE_HASH,
            'fundamental_analytical_hash': cer077.FUNDAMENTAL_HASH,
            'prior_stage_package_digest': cer077.PRIOR_STAGE_DIGEST,
            'historical_state_digest': cer077.HISTORICAL_STATE_DIGEST,
            'trading_date': cer077.AS_OF_DATE,
        }},
    }


class CER077Incremental1200Tests(unittest.TestCase):
    def setUp(self):
        self.state = Path('data/production/test-cer077')
        shutil.rmtree(self.state, ignore_errors=True)
        self.bundle = cer076_source_bundle_fixture()
        self.cer074 = cer076_cer074_persisted_fixture(self.bundle)
        self.cer075 = cer075_persisted_fixture()
        self.cer076 = cer076_persisted_fixture()
        self.patches = [
            patch('src.cer077_incremental_1200._verify_model_freeze', return_value={'status':'PASS'}),
            patch('src.cer076_incremental_0930._verify_model_freeze', return_value={'status':'PASS'}),
            patch('src.cer075_scheduler._verify_model_freeze', return_value={'status':'PASS'}),
            patch('src.cer074_acceptance._verify_model_freeze', return_value={'status':'PASS'}),
        ]
        for p in self.patches: p.start()

    def tearDown(self):
        for p in reversed(self.patches): p.stop()
        shutil.rmtree(self.state, ignore_errors=True)

    def test_previous_state_binding_uses_cer076_0930_state(self):
        previous = cer077.previous_0930_state_from_cer076(self.cer076)
        self.assertEqual(previous['current_state_id'], cer077.PREVIOUS_0930_STATE_ID)
        self.assertEqual(previous['decision_payload_hash'], cer077.PREVIOUS_0930_STATE_HASH)
        self.assertEqual(previous['previous_state_resolution'], 'PERSISTED_PRODUCTION_STATE')

    def test_reconstructed_0930_material_matches_accepted_cer076_state(self):
        state = cer077.reconstruct_0930_material(self.bundle, self.cer074, self.cer075)['state_0930']
        self.assertEqual(state['current_state_id'], cer077.PREVIOUS_0930_STATE_ID)
        self.assertEqual(state['decision_payload_hash'], cer077.PREVIOUS_0930_STATE_HASH)

    def test_incremental_acceptance_artifacts_pass(self):
        arts = cer077.build_cer077_artifacts(source_bundle=self.bundle, cer074_persisted=self.cer074, cer075_persisted=self.cer075, cer076_persisted=self.cer076, state_root=self.state, run_head_sha='h', actions_run_id='r', actions_job_id='j', event_name='workflow_dispatch')
        lineage = arts['RATE_CER077_LINEAGE_EVIDENCE.json']
        delta = arts['RATE_CER077_MIDDAY_INCREMENTAL_EVIDENCE_DELTA.json']
        dry_a = arts['RATE_CER077_DRY_RUN_A.json']
        dry_b = arts['RATE_CER077_DRY_RUN_B.json']
        persist = arts['RATE_CER077_PERSIST_RESULT_EVIDENCE.json']
        replay = arts['RATE_CER077_REPLAY_IDEMPOTENCY_EVIDENCE.json']
        portfolio = arts['RATE_CER077_PORTFOLIO_CONTINUITY_EVIDENCE.json']
        ledger = arts['RATE_CER077_TRANSACTION_LEDGER_CONTINUITY_EVIDENCE.json']
        failure = arts['RATE_CER077_FAILURE_GATE_EVIDENCE.json']
        self.assertEqual(lineage['decision_state_lineage'], 'PASS')
        self.assertEqual(lineage['decision_state_coverage'], '30/30')
        self.assertEqual(delta['midday_incremental_evidence_boundary'], 'PASS')
        self.assertEqual(delta['protected_baseline_integrity'], 'PASS')
        self.assertEqual(delta['protected_field_violation_count'], 0)
        self.assertEqual(dry_a['decision_state_id'], dry_b['decision_state_id'])
        self.assertEqual(dry_a['decision_state_hash'], dry_b['decision_state_hash'])
        self.assertEqual(dry_a['persist_count'], 0)
        self.assertEqual(dry_b['persist_count'], 0)
        self.assertEqual(persist['first_persist_new_record_count'], 1)
        self.assertEqual(replay['replay_new_record_count'], 0)
        self.assertEqual(replay['production_state_idempotency'], 'PASS')
        self.assertEqual(portfolio['portfolio_continuity'], 'PASS')
        self.assertEqual(ledger['transaction_ledger_continuity'], 'PASS')
        self.assertEqual(portfolio['ranking_model_continuity'], 'PASS')
        self.assertEqual(failure['failure_closed_behavior'], 'PASS')

    def test_protected_baseline_violation_is_blocked(self):
        previous = cer077.previous_0930_state_from_cer076(self.cer076)
        state = cer077.reconstruct_0930_material(self.bundle, self.cer074, self.cer075)['state_0930']
        snapshot = cer077.create_1200_snapshot(state, previous)
        snapshot['records'][0]['Fundamental'] = snapshot['records'][0]['Fundamental'] + 1
        with self.assertRaisesRegex(RuntimeError, 'INCREMENTAL_BOUNDARY_FAIL'):
            cer077.run_midday_decision(snapshot, state, self.bundle)

    def test_wrong_previous_state_is_blocked(self):
        bad = copy.deepcopy(self.cer076)
        bad['current_state_id'] = cer077.PREVIOUS_0730_STATE_ID
        with self.assertRaisesRegex(RuntimeError, 'CER076_PREVIOUS_STATE_BINDING_MISMATCH'):
            cer077.previous_0930_state_from_cer076(bad)


if __name__ == '__main__':
    unittest.main()
