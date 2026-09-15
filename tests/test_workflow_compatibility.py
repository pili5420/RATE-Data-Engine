import unittest
from pathlib import Path
class WorkflowCompatibilityTests(unittest.TestCase):
 def test_live_workflow_uses_builder_and_source_bundle(self):
  s=Path('.github/workflows/rate_phase_a2_validation.yml').read_text(encoding='utf-8'); self.assertIn('build_live_source_bundle.py',s); self.assertIn('--source-bundle',s); self.assertNotIn('phase_a2_fixture_snapshot',s)
