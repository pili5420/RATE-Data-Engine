import copy, json, shutil, unittest
from pathlib import Path
from unittest.mock import patch

import src.cer078_evening_1930 as cer078
from tests.test_cer077_incremental_1200 import cer076_source_bundle_fixture, cer076_cer074_persisted_fixture, cer075_persisted_fixture, cer076_persisted_fixture

CER077_PERSISTED = [Path('artifacts/accepted/cer077/persist_result/RATE_CER077_PERSIST_RESULT_EVIDENCE.json'), Path('artifacts/remote-36305190527/RATE_CER077_PERSIST_RESULT_EVIDENCE/RATE_CER077_PERSIST_RESULT_EVIDENCE.json')]

def cer077_persisted_fixture():
    for path in CER077_PERSISTED:
        if path.exists(): return json.loads(path.read_text(encoding='utf-8'))
    return {'validation_status':'PASS','current_state_id':cer078.PREVIOUS_1200_STATE_ID,'current_state_hash':cer078.PREVIOUS_1200_STATE_HASH,'persist_result':{'status':'PERSISTED','new_record_count':1,'state_entry':{'current_state_id':cer078.PREVIOUS_1200_STATE_ID,'decision_payload_hash':cer078.PREVIOUS_1200_STATE_HASH,'decision_time':'12:00','execution_scope':cer078.EXECUTION_SCOPE,'previous_state_id':cer078.PREVIOUS_0930_STATE_ID,'previous_state_resolution':'PERSISTED_PRODUCTION_STATE','trading_date':cer078.AS_OF_DATE}}}

class CER078Evening1930Tests(unittest.TestCase):
    def setUp(self):
        self.state=Path('data/production/test-cer078'); shutil.rmtree(self.state, ignore_errors=True)
        self.bundle=cer076_source_bundle_fixture(); self.cer074=cer076_cer074_persisted_fixture(self.bundle); self.cer075=cer075_persisted_fixture(); self.cer076=cer076_persisted_fixture(); self.cer077=cer077_persisted_fixture()
        self.patches=[patch('src.cer078_evening_1930._verify_model_freeze', return_value={'status':'PASS'}), patch('src.cer077_incremental_1200._verify_model_freeze', return_value={'status':'PASS'}), patch('src.cer076_incremental_0930._verify_model_freeze', return_value={'status':'PASS'}), patch('src.cer075_scheduler._verify_model_freeze', return_value={'status':'PASS'}), patch('src.cer074_acceptance._verify_model_freeze', return_value={'status':'PASS'})]
        for p in self.patches: p.start()
    def tearDown(self):
        for p in reversed(self.patches): p.stop()
        shutil.rmtree(self.state, ignore_errors=True)
    def test_previous_state_binding_uses_cer077_1200_state(self):
        previous=cer078.previous_1200_state_from_cer077(self.cer077)
        self.assertEqual(previous['current_state_id'], cer078.PREVIOUS_1200_STATE_ID)
        self.assertEqual(previous['decision_payload_hash'], cer078.PREVIOUS_1200_STATE_HASH)
    def test_reconstructed_1200_material_matches_accepted_cer077_state(self):
        state=cer078.reconstruct_1200_material(self.bundle,self.cer074,self.cer075,self.cer076)['state_1200']
        self.assertEqual(state['current_state_id'], cer078.PREVIOUS_1200_STATE_ID)
        self.assertEqual(state['decision_payload_hash'], cer078.PREVIOUS_1200_STATE_HASH)
    def test_evening_acceptance_artifacts_pass(self):
        arts=cer078.build_cer078_artifacts(source_bundle=self.bundle, cer074_persisted=self.cer074, cer075_persisted=self.cer075, cer076_persisted=self.cer076, cer077_persisted=self.cer077, state_root=self.state, run_head_sha='h', actions_run_id='r', actions_job_id='j', event_name='workflow_dispatch')
        lineage=arts['RATE_CER078_FULL_LINEAGE_EVIDENCE.json']; delta=arts['RATE_CER078_EVENING_INCREMENTAL_EVIDENCE_DELTA.json']; dry_a=arts['RATE_CER078_DRY_RUN_A.json']; dry_b=arts['RATE_CER078_DRY_RUN_B.json']; persist=arts['RATE_CER078_PERSIST_RESULT_EVIDENCE.json']; replay=arts['RATE_CER078_REPLAY_IDEMPOTENCY_EVIDENCE.json']; port=arts['RATE_CER078_PORTFOLIO_CLOSING_CONTINUITY_EVIDENCE.json']; ledger=arts['RATE_CER078_TRANSACTION_LEDGER_CONTINUITY_EVIDENCE.json']; ranking=arts['RATE_CER078_RANKING_MODEL_CONTINUITY_EVIDENCE.json']; learning=arts['RATE_CER078_MODEL_LEARNING_LOG_EVIDENCE.json']; watch=arts['RATE_CER078_TOMORROW_WATCHLIST_EVIDENCE.json']; failure=arts['RATE_CER078_FAILURE_GATE_EVIDENCE.json']
        self.assertEqual(lineage['full_lineage'], 'PASS'); self.assertEqual(lineage['decision_state_coverage'], '30/30'); self.assertEqual(delta['evening_incremental_evidence_boundary'], 'PASS'); self.assertEqual(delta['protected_field_violation_count'], 0)
        self.assertEqual(dry_a['decision_state_id'], dry_b['decision_state_id']); self.assertEqual(dry_a['decision_state_hash'], dry_b['decision_state_hash']); self.assertEqual(dry_a['persist_count'], 0); self.assertEqual(dry_b['persist_count'], 0)
        self.assertEqual(persist['first_persist_new_record_count'], 1); self.assertEqual(replay['replay_new_record_count'], 0); self.assertEqual(replay['production_state_idempotency'], 'PASS')
        self.assertEqual(port['roy_portfolio_continuity'], 'PASS'); self.assertEqual(port['ai_paper_portfolio_continuity'], 'PASS'); self.assertEqual(ledger['transaction_ledger_continuity'], 'PASS'); self.assertEqual(ranking['ranking_model_continuity'], 'PASS'); self.assertEqual(learning['model_learning_log_integrity'], 'PASS'); self.assertEqual(watch['tomorrow_watchlist_integrity'], 'PASS'); self.assertEqual(failure['failure_closed_behavior'], 'PASS')
    def test_protected_baseline_violation_is_blocked(self):
        previous=cer078.previous_1200_state_from_cer077(self.cer077); state=cer078.reconstruct_1200_material(self.bundle,self.cer074,self.cer075,self.cer076)['state_1200']; snapshot=cer078.create_1930_snapshot(state,previous); snapshot['records'][0]['Fundamental'] += 1
        with self.assertRaisesRegex(RuntimeError,'INCREMENTAL_BOUNDARY_FAIL'): cer078.run_evening_decision(snapshot,state,self.bundle)
    def test_wrong_previous_state_is_blocked(self):
        bad=copy.deepcopy(self.cer077); bad['current_state_id']=cer078.PREVIOUS_0930_STATE_ID
        with self.assertRaisesRegex(RuntimeError,'CER077_PREVIOUS_STATE_BINDING_MISMATCH'): cer078.previous_1200_state_from_cer077(bad)

if __name__=='__main__': unittest.main()
