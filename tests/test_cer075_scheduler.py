import json, shutil, unittest
from pathlib import Path
from unittest.mock import patch

import src.cer075_scheduler as cer075

SRC = Path('artifacts/remote-36283374552')

class CER075SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.state=Path('data/production/test-cer075')
        shutil.rmtree(self.state, ignore_errors=True)
        self.bundle=json.loads(Path('artifacts/remote-36281974051/RATE_CER073_FINAL_SOURCE_BUNDLE/RATE_CER073_FINAL_SOURCE_BUNDLE.json').read_text(encoding='utf-8'))
        self.prev=json.loads((SRC/'RATE_CER074_PERSISTED_DECISION_STATE_EVIDENCE'/'RATE_CER074_PERSISTED_DECISION_STATE_EVIDENCE.json').read_text(encoding='utf-8'))
        self.workflow=Path('artifacts/test-cer075-workflow.yml')
        self.workflow.parent.mkdir(exist_ok=True)
        self.workflow.write_text('''name: RATE Production 07:30 Recurring Scheduler\non:\n  schedule:\n    - cron: "30 23 * * 0-4"\n  workflow_dispatch:\nconcurrency:\n  group: rate-production-0730-${{ github.ref }}\n  cancel-in-progress: false\njobs:\n  production-0730:\n    env:\n      RATE_LIVE_E2E_ENABLED: PRODUCTION_SCHEDULER\n    steps: []\n# CER075\n''', encoding='utf-8')
        self.freeze=patch('src.cer075_scheduler._verify_model_freeze', return_value={'status':'PASS'})
        self.freeze_cer074=patch('src.cer074_acceptance._verify_model_freeze', return_value={'status':'PASS'})
        self.freeze.start(); self.freeze_cer074.start()
    def tearDown(self):
        self.freeze.stop(); self.freeze_cer074.stop(); shutil.rmtree(self.state, ignore_errors=True); self.workflow.unlink(missing_ok=True)
    def test_scheduler_definition_timezone_and_no_acceptance_flag(self):
        d=cer075.workflow_scheduler_definition(self.workflow)
        self.assertEqual(d['scheduler_cron'], '30 23 * * 0-4')
        self.assertEqual(d['correct_timezone_mapping'], 'PASS')
        self.assertEqual(d['acceptance_only_live_e2e_flag_forbidden'], 'PASS')
    def test_recurring_run_uses_persisted_previous_state_not_bootstrap(self):
        arts=cer075.build_cer075_artifacts(source_bundle=self.bundle, cer074_persisted=self.prev, workflow_path=self.workflow, state_root=self.state, run_head_sha='h', actions_run_id='r', actions_job_id='j', event_name='workflow_dispatch')
        lineage=arts['RATE_CER075_STATE_LINEAGE_EVIDENCE.json']
        self.assertEqual(lineage['previous_state_resolution'], 'PERSISTED_PRODUCTION_STATE')
        self.assertEqual(lineage['previous_state_id'], cer075.PREVIOUS_STATE_ID)
        self.assertNotEqual(lineage['current_state_id'], cer075.PREVIOUS_STATE_ID)
        self.assertEqual(lineage['decision_state_lineage'], 'PASS')
    def test_idempotency_concurrency_and_failure_gates(self):
        arts=cer075.build_cer075_artifacts(source_bundle=self.bundle, cer074_persisted=self.prev, workflow_path=self.workflow, state_root=self.state, run_head_sha='h', actions_run_id='r', actions_job_id='j', event_name='schedule')
        self.assertEqual(arts['RATE_CER075_PERSIST_RESULT_EVIDENCE.json']['first_persist_new_record_count'], 1)
        self.assertEqual(arts['RATE_CER075_REPLAY_IDEMPOTENCY_EVIDENCE.json']['replay_new_record_count'], 0)
        self.assertEqual(arts['RATE_CER075_REPLAY_IDEMPOTENCY_EVIDENCE.json']['production_state_idempotency'], 'PASS')
        self.assertEqual(arts['RATE_CER075_CONCURRENCY_EVIDENCE.json']['concurrency_protection'], 'PASS')
        self.assertEqual(arts['RATE_CER075_FAILURE_GATE_EVIDENCE.json']['failure_closed_behavior'], 'PASS')
    def test_bad_workflow_fails_scheduler_definition(self):
        self.workflow.write_text('on:\n  workflow_dispatch:\n', encoding='utf-8')
        with self.assertRaisesRegex(RuntimeError, 'SCHEDULER_DEFINITION_FAIL'):
            cer075.build_cer075_artifacts(source_bundle=self.bundle, cer074_persisted=self.prev, workflow_path=self.workflow, state_root=self.state)

if __name__ == '__main__': unittest.main()
