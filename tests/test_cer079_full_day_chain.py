import copy, json, shutil, unittest
from pathlib import Path
from unittest.mock import patch

import src.cer079_full_day_chain as cer079
from tests.test_cer078_evening_1930 import cer076_source_bundle_fixture, cer076_cer074_persisted_fixture, cer075_persisted_fixture, cer076_persisted_fixture, cer077_persisted_fixture

CER078_PERSISTED=[Path('artifacts/accepted/cer078/persist_result/RATE_CER078_PERSIST_RESULT_EVIDENCE.json'), Path('artifacts/remote-36308118557/RATE_CER078_PERSIST_RESULT_EVIDENCE/RATE_CER078_PERSIST_RESULT_EVIDENCE.json')]

def cer078_persisted_fixture():
    for path in CER078_PERSISTED:
        if path.exists(): return json.loads(path.read_text(encoding='utf-8'))
    return {'validation_status':'PASS','current_state_id':cer079.STATE_IDS['19:30'],'current_state_hash':cer079.STATE_HASHES['19:30'],'persist_result':{'state_entry':{'current_state_id':cer079.STATE_IDS['19:30'],'decision_payload_hash':cer079.STATE_HASHES['19:30'],'trading_date':cer079.TRADING_DATE,'decision_time':'19:30','previous_state_id':cer079.STATE_IDS['12:00'],'previous_state_resolution':'PERSISTED_PRODUCTION_STATE'}}}

class CER079FullDayChainTests(unittest.TestCase):
    def setUp(self):
        self.state=Path('data/production/test-cer079'); shutil.rmtree(self.state, ignore_errors=True)
        self.bundle=cer076_source_bundle_fixture(); self.cer074=cer076_cer074_persisted_fixture(self.bundle); self.cer075=cer075_persisted_fixture(); self.cer076=cer076_persisted_fixture(); self.cer077=cer077_persisted_fixture(); self.cer078=cer078_persisted_fixture()
        self.patches=[patch('src.cer079_full_day_chain._verify_model_freeze', return_value={'status':'PASS'}), patch('src.cer078_evening_1930._verify_model_freeze', return_value={'status':'PASS'}), patch('src.cer077_incremental_1200._verify_model_freeze', return_value={'status':'PASS'}), patch('src.cer076_incremental_0930._verify_model_freeze', return_value={'status':'PASS'}), patch('src.cer075_scheduler._verify_model_freeze', return_value={'status':'PASS'}), patch('src.cer074_acceptance._verify_model_freeze', return_value={'status':'PASS'})]
        for p in self.patches: p.start()
    def tearDown(self):
        for p in reversed(self.patches): p.stop()
        shutil.rmtree(self.state, ignore_errors=True)
    def test_persisted_chain_validation(self):
        chain=cer079.validate_persisted_chain(self.cer075,self.cer076,self.cer077,self.cer078)
        self.assertEqual(chain['full_day_state_chain'],'PASS')
        self.assertEqual(chain['duplicate_cadence_state_count'],0)
    def test_full_day_acceptance_artifacts_pass(self):
        arts=cer079.build_cer079_artifacts(source_bundle=self.bundle, cer074_persisted=self.cer074, cer075_persisted=self.cer075, cer076_persisted=self.cer076, cer077_persisted=self.cer077, cer078_persisted=self.cer078, state_root=self.state, run_head_sha='h', actions_run_id='r', actions_job_id='j', event_name='workflow_dispatch')
        self.assertEqual(arts['RATE_CER079_FULL_DAY_LINEAGE_EVIDENCE.json']['full_day_state_chain'],'PASS')
        self.assertEqual(arts['RATE_CER079_TRADING_DAY_INTEGRITY_EVIDENCE.json']['trading_day_integrity'],'PASS')
        self.assertEqual(arts['RATE_CER079_NO_RESET_EVIDENCE.json']['reset_violation_count'],0)
        self.assertEqual(arts['RATE_CER079_FULL_DAY_EVIDENCE_CONTINUITY.json']['protected_field_violation_count'],0)
        self.assertEqual(arts['RATE_CER079_DETERMINISTIC_FULL_DAY_REPLAY.json']['replay_state_match_count'],4)
        self.assertEqual(arts['RATE_CER079_DETERMINISTIC_FULL_DAY_REPLAY.json']['full_day_replay_new_record_count'],0)
        self.assertEqual(arts['RATE_CER079_FULL_DAY_IDEMPOTENCY_EVIDENCE.json']['full_day_idempotency'],'PASS')
        self.assertEqual(arts['RATE_CER079_END_OF_DAY_CLOSURE_EVIDENCE.json']['end_of_day_closure'],'PASS')
        self.assertEqual(arts['RATE_CER079_NEXT_DAY_HANDOFF_READINESS_EVIDENCE.json']['NEXT_TRADING_DAY_PREDECESSOR_READY'],'PASS')
        self.assertEqual(arts['RATE_CER079_SCHEDULER_COMPATIBILITY_EVIDENCE.json']['scheduler_compatibility'],'PASS')
        self.assertEqual(arts['RATE_CER079_FAILURE_GATE_EVIDENCE.json']['failure_closed_behavior'],'PASS')
    def test_wrong_previous_state_is_blocked(self):
        bad=copy.deepcopy(self.cer078); bad['persist_result']['state_entry']['previous_state_id']=cer079.STATE_IDS['09:30']
        with self.assertRaisesRegex(RuntimeError,'PREVIOUS_STATE_MISMATCH'):
            cer079.validate_persisted_chain(self.cer075,self.cer076,self.cer077,bad)

if __name__=='__main__': unittest.main()
