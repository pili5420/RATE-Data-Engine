from pathlib import Path
import unittest


class CER072WorkflowContractTests(unittest.TestCase):
    def test_dedicated_workflow_is_staging_only_and_live_phase_a2_disabled(self):
        text=Path('.github/workflows/rate_cer072_validation.yml').read_text(encoding='utf-8')
        self.assertIn('rate-v2-6-1r2-staging',text)
        self.assertIn('RATE_LIVE_E2E_ENABLED: "false"',text)
        self.assertNotIn('RATE_STAGING_REALTIME',text)
        self.assertNotIn('run_phase_a2.py',text)
        self.assertIn('scripts/run_cer072_acceptance.py',text)

    def test_all_four_cer072_artifacts_upload_unconditionally(self):
        text=Path('.github/workflows/rate_cer072_validation.yml').read_text(encoding='utf-8')
        for artifact in (
            'RATE_CER072_T86_26_SESSION_EVIDENCE',
            'RATE_CER072_INSTITUTIONAL_HISTORY_EVIDENCE',
            'RATE_FIRST_PRODUCTION_PRIOR_STAGE_PACKAGE_V1',
            'RATE_CER072_PRIOR_STAGE_RECONSTRUCTION_EVIDENCE',
        ):
            self.assertIn(f'name: {artifact}',text)
            self.assertIn('if: always()',text)


if __name__=='__main__': unittest.main()
