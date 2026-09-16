import unittest
from pathlib import Path

class PhaseA2SemanticTests(unittest.TestCase):
    def test_no_production_shortcuts(self):
        s=Path('scripts/run_phase_a2.py').read_text(encoding='utf-8')
        self.assertNotIn("query_universe_size']=4",s)
        self.assertNotIn("gates']['deterministic']='PASS",s)
        self.assertNotIn("gates']['07:30_e2e']='PASS",s)
        self.assertNotIn("decision_state']='PASS",s)
