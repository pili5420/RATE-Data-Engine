import unittest
from src.live_decision_inputs import build_live_decision_records
class LiveDecisionInputTests(unittest.TestCase):
 def test_missing_fails_closed(self): self.assertEqual(build_live_decision_records({},'2026-09-15',['2330'])['feature_validation']['status'],'BLOCKED:PRODUCTION_DECISION_INPUT_UNAVAILABLE')
