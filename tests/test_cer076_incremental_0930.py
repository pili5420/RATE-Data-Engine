import copy
import json
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch

import src.cer076_incremental_0930 as cer076
from tests.test_cer074_acceptance import fixture_bundle
from tests.test_cer075_scheduler import cer075_previous_state_fixture

SOURCE_BUNDLES = [
    Path('artifacts/accepted/cer073/source_bundle/RATE_CER073_FINAL_SOURCE_BUNDLE.json'),
    Path('artifacts/remote-36281974051/RATE_CER073_FINAL_SOURCE_BUNDLE/RATE_CER073_FINAL_SOURCE_BUNDLE.json'),
]
CER074_PERSISTED = [
    Path('artifacts/accepted/cer074/persisted_state/RATE_CER074_PERSISTED_DECISION_STATE_EVIDENCE.json'),
    Path('artifacts/remote-36283374552/RATE_CER074_PERSISTED_DECISION_STATE_EVIDENCE/RATE_CER074_PERSISTED_DECISION_STATE_EVIDENCE.json'),
]
CER075_PERSISTED = [
    Path('artifacts/accepted/cer075/persist_result/RATE_CER075_PERSIST_RESULT_EVIDENCE.json'),
    Path('artifacts/remote-36303940988/RATE_CER075_PERSIST_RESULT_EVIDENCE/RATE_CER075_PERSIST_RESULT_EVIDENCE.json'),
]


def cer076_source_bundle_fixture():
    for path in SOURCE_BUNDLES:
        if path.exists():
            return json.loads(path.read_text(encoding='utf-8'))
    return fixture_bundle()


def cer076_cer074_persisted_fixture(bundle):
    for path in CER074_PERSISTED:
        if path.exists():
            return json.loads(path.read_text(encoding='utf-8'))
    return cer075_previous_state_fixture(bundle)


def cer075_persisted_fixture():
    for path in CER075_PERSISTED:
        if path.exists():
            return json.loads(path.read_text(encoding='utf-8'))
    return {
        'validation_status': 'PASS',
        'current_state_id': cer076.PREVIOUS_0730_STATE_ID,
        'current_state_hash': cer076.PREVIOUS_0730_STATE_HASH,
        'persist_result': {
            'status': 'PERSISTED',
            'new_record_count': 1,
            'state_entry': {
                'current_state_id': cer076.PREVIOUS_0730_STATE_ID,
                'decision_payload_hash': cer076.PREVIOUS_0730_STATE_HASH,
                'decision_time': '07:30',
                'execution_scope': cer076.EXECUTION_SCOPE,
                'input_snapshot_id': cer076.PREVIOUS_0730_INPUT_SNAPSHOT_ID,
                'input_snapshot_hash': cer076.PREVIOUS_0730_INPUT_SNAPSHOT_HASH,
                'previous_state_id': cer076.CER074_STATE_ID,
                'previous_state_resolution': 'PERSISTED_PRODUCTION_STATE',
                'source_bundle_hash': cer076.CER073_SOURCE_BUNDLE_HASH,
                'fundamental_analytical_hash': cer076.FUNDAMENTAL_HASH,
                'prior_stage_package_digest': cer076.PRIOR_STAGE_DIGEST,
                'historical_state_digest': cer076.HISTORICAL_STATE_DIGEST,
                'trading_date': cer076.AS_OF_DATE,
            },
        },
    }


class CER076Incremental0930Tests(unittest.TestCase):
    def setUp(self):
        self.state = Path('data/production/test-cer076')
        shutil.rmtree(self.state, ignore_errors=True)
        self.bundle = cer076_source_bundle_fixture()
        self.cer074 = cer076_cer074_persisted_fixture(self.bundle)
        self.cer075 = cer075_persisted_fixture()
        self.freeze = patch('src.cer076_incremental_0930._verify_model_freeze', return_value={'status':'PASS'})
        self.freeze_075 = patch('src.cer075_scheduler._verify_model_freeze', return_value={'status':'PASS'})
        self.freeze_074 = patch('src.cer074_acceptance._verify_model_freeze', return_value={'status':'PASS'})
        self.freeze.start(); self.freeze_075.start(); self.freeze_074.start()

    def tearDown(self):
        self.freeze.stop(); self.freeze_075.stop(); self.freeze_074.stop()
        shutil.rmtree(self.state, ignore_errors=True)

    def test_previous_state_binding_uses_cer075_0730_state(self):
        previous = cer076.previous_0730_state_from_cer075(self.cer075)
        self.assertEqual(previous['current_state_id'], cer076.PREVIOUS_0730_STATE_ID)
        self.assertEqual(previous['decision_payload_hash'], cer076.PREVIOUS_0730_STATE_HASH)
        self.assertEqual(previous['previous_state_resolution'], 'PERSISTED_PRODUCTION_STATE')

    def test_reconstructed_0730_baseline_matches_accepted_cer075_state(self):
        baseline = cer076.reconstruct_0730_baseline(self.bundle, self.cer074)['baseline']
        self.assertEqual(baseline['current_state_id'], cer076.PREVIOUS_0730_STATE_ID)
        self.assertEqual(baseline['decision_payload_hash'], cer076.PREVIOUS_0730_STATE_HASH)

    def test_incremental_acceptance_artifacts_pass(self):
        arts = cer076.build_cer076_artifacts(source_bundle=self.bundle, cer074_persisted=self.cer074, cer075_persisted=self.cer075, state_root=self.state, run_head_sha='h', actions_run_id='r', actions_job_id='j', event_name='workflow_dispatch')
        lineage = arts['RATE_CER076_LINEAGE_EVIDENCE.json']
        delta = arts['RATE_CER076_INCREMENTAL_EVIDENCE_DELTA.json']
        dry_a = arts['RATE_CER076_DRY_RUN_A.json']
        dry_b = arts['RATE_CER076_DRY_RUN_B.json']
        persist = arts['RATE_CER076_PERSIST_RESULT_EVIDENCE.json']
        replay = arts['RATE_CER076_REPLAY_IDEMPOTENCY_EVIDENCE.json']
        continuity = arts['RATE_CER076_PORTFOLIO_LEDGER_CONTINUITY_EVIDENCE.json']
        failure = arts['RATE_CER076_FAILURE_GATE_EVIDENCE.json']
        self.assertEqual(lineage['decision_state_lineage'], 'PASS')
        self.assertEqual(lineage['decision_state_coverage'], '30/30')
        self.assertEqual(delta['incremental_evidence_boundary'], 'PASS')
        self.assertEqual(delta['protected_baseline_integrity'], 'PASS')
        self.assertGreater(delta['changed_field_count'], 0)
        self.assertEqual(delta['protected_field_violation_count'], 0)
        self.assertEqual(dry_a['decision_state_id'], dry_b['decision_state_id'])
        self.assertEqual(dry_a['decision_state_hash'], dry_b['decision_state_hash'])
        self.assertEqual(dry_a['persist_count'], 0)
        self.assertEqual(dry_b['persist_count'], 0)
        self.assertEqual(persist['first_persist_new_record_count'], 1)
        self.assertEqual(replay['replay_new_record_count'], 0)
        self.assertEqual(replay['production_state_idempotency'], 'PASS')
        self.assertEqual(continuity['portfolio_continuity'], 'PASS')
        self.assertEqual(continuity['ledger_continuity'], 'PASS')
        self.assertEqual(failure['failure_closed_behavior'], 'PASS')

    def test_protected_baseline_violation_is_blocked(self):
        previous = cer076.previous_0730_state_from_cer075(self.cer075)
        reconstructed = cer076.reconstruct_0730_baseline(self.bundle, self.cer074)
        snapshot = cer076.create_0930_snapshot(reconstructed['baseline'], previous)
        snapshot['records'][0]['Fundamental'] = snapshot['records'][0]['Fundamental'] + 1
        with self.assertRaisesRegex(RuntimeError, 'INCREMENTAL_BOUNDARY_FAIL'):
            cer076.run_incremental_decision(snapshot, reconstructed['baseline'], self.bundle)

    def test_wrong_previous_state_is_blocked(self):
        bad = copy.deepcopy(self.cer075)
        bad['current_state_id'] = cer076.CER074_STATE_ID
        with self.assertRaisesRegex(RuntimeError, 'CER075_PREVIOUS_STATE_BINDING_MISMATCH'):
            cer076.previous_0730_state_from_cer075(bad)


if __name__ == '__main__':
    unittest.main()
