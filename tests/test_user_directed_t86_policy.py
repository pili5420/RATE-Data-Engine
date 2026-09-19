import json
import unittest
from pathlib import Path

from src.production_layer import production_gate_status


class UserDirectedT86PolicyTests(unittest.TestCase):
    def setUp(self):
        self.registry = json.loads(Path("config/SOURCE_REGISTRY.json").read_text(encoding="utf-8"))

    def test_matrix_keeps_formal_authorization_unverified(self):
        matrix = json.loads(Path("artifacts/SOURCE_AUTHORIZATION_MATRIX_V1.json").read_text(encoding="utf-8"))
        t86 = next(x for x in matrix["entries"] if x["dataset_name"] == "三大法人買賣超日報 T86")
        self.assertEqual(t86["authorization_status"], "USER_ASSUMPTION")
        self.assertEqual(t86["authorization_basis"], "USER_DIRECTED_ASSUMPTION")
        self.assertFalse(t86["formal_license_verified"])
        self.assertTrue(t86["operational_use_allowed"])
        self.assertIsNone(t86["blocking_reason"])
        self.assertEqual(matrix["authorization_gate"], "PASS_WITH_USER_ASSUMPTION")

    def test_morning_evening_operational_gate_keeps_legal_status_separate(self):
        morning = production_gate_status(self.registry, slot="0730")
        evening = production_gate_status(self.registry, slot="1930")
        for result in (morning, evening):
            self.assertEqual(result["source_authorization"], "PASS_WITH_USER_ASSUMPTION")
            self.assertEqual(result["formal_authorization_status"], "UNVERIFIED")
            self.assertIn("institutional", result["assumption_authorized_domains"])
            self.assertNotEqual(result["e2e"], "PASS")

    def test_intraday_slots_remain_blocked(self):
        for slot in ("0930", "1200"):
            result = production_gate_status(self.registry, slot=slot)
            self.assertEqual(result["e2e"], "BLOCKED:INTRADAY_SOURCE_UNAVAILABLE")

    def test_cer070_operational_policy_and_formal_authorization_are_separate(self):
        policy = json.loads(Path('artifacts/RATE_T86_USER_DIRECTED_OPERATION_POLICY_V1.json').read_text(encoding='utf-8'))
        self.assertEqual(policy['rate_operation_policy_gate'], 'PASS_WITH_USER_ASSUMPTION')
        self.assertEqual(policy['formal_authorization_status'], 'UNVERIFIED')
        self.assertFalse(policy['formal_license_verified'])
        self.assertFalse(policy['raw_data_redistribution'])

    def test_phase_a2_is_disabled_for_cer070(self):
        workflow = Path('.github/workflows/rate_phase_a2_validation.yml').read_text(encoding='utf-8')
        cer070 = Path('.github/workflows/rate_cer070_evidence_purity.yml').read_text(encoding='utf-8')
        self.assertIn('RATE_LIVE_E2E_ENABLED: "false"', workflow)
        self.assertIn("env.RATE_LIVE_E2E_ENABLED == 'true'", workflow)
        self.assertIn('RATE_LIVE_E2E_ENABLED: "false"', cer070)
        self.assertNotIn('scripts/run_phase_a2.py', cer070)


if __name__ == "__main__":
    unittest.main()
