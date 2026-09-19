import json
import unittest
from pathlib import Path


class CER070WorkflowContractTests(unittest.TestCase):
    def test_cer070_workflow_skips_phase_a2_and_uploads_both_evidence_artifacts(self):
        workflow = Path('.github/workflows/rate_cer070_evidence_purity.yml').read_text(encoding='utf-8')
        self.assertIn('RATE_LIVE_E2E_ENABLED: "false"', workflow)
        self.assertIn('RATE_CER070_EVIDENCE_PURITY', workflow)
        self.assertIn('RATE_T86_USER_DIRECTED_OPERATION_POLICY', workflow)
        self.assertNotIn('scripts/run_phase_a2.py', workflow)

    def test_user_policy_artifact_preserves_separate_formal_status(self):
        policy = json.loads(Path('artifacts/RATE_T86_USER_DIRECTED_OPERATION_POLICY_V1.json').read_text(encoding='utf-8'))
        self.assertFalse(policy['cer070_execution_policy']['production_snapshot_created'])
        self.assertEqual(policy['cer070_execution_policy']['production_decision_state_persisted'], 0)
        self.assertEqual(policy['rate_operation_policy_gate'], 'PASS_WITH_USER_ASSUMPTION')
        self.assertEqual(policy['formal_authorization_status'], 'UNVERIFIED')


if __name__ == '__main__':
    unittest.main()
