import json
import re
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import bootstrap_live_history as bootstrap
from scripts import build_live_source_bundle as builder


class CER064CampaignTests(unittest.TestCase):
    def test_status_propagation_matches_evidence(self):
        root = Path('artifacts/test_cer064_status'); shutil.rmtree(root, ignore_errors=True); root.mkdir(parents=True)
        try:
            universe = root / 'universe.json'; checkpoint = root / 'checkpoint.json'; evidence = root / 'evidence.json'; campaign = root / 'campaign.json'
            universe.write_text(json.dumps({'universe_symbol_digest': 'u', 'symbols': [{'symbol': '2313', 'market': 'TWSE'}]}), encoding='utf-8')
            with patch.object(bootstrap, '_periods', return_value=['202601']), patch.object(bootstrap, '_normalized_period', side_effect=RuntimeError('TWSE_HOST_TEMPORARILY_UNAVAILABLE')):
                result = bootstrap.run(trading_date='2026-01-31', universe_file=universe, checkpoint_path=checkpoint, evidence_path=evidence, campaign_status_path=campaign, max_new_periods=12, max_runtime_seconds=60)
            self.assertEqual(result['status'], 'TEMPORARY_SOURCE_UNAVAILABLE')
            self.assertEqual(json.loads(evidence.read_text())['status'], 'TEMPORARY_SOURCE_UNAVAILABLE')
            self.assertEqual(json.loads(campaign.read_text())['campaign_status'], 'TEMPORARILY_PAUSED')
        finally: shutil.rmtree(root, ignore_errors=True)

    def test_serialization_and_authorization_gate_configuration(self):
        workflow = Path('.github/workflows/rate_phase_a2_validation.yml').read_text(encoding='utf-8')
        self.assertIn('cancel-in-progress: false', workflow)
        self.assertIn('SOURCE_AUTHORIZATION_GATE', workflow)
        self.assertIn('BLOCKED:T86_LICENSE_EVIDENCE', workflow)

    def test_checkpoint_lineage_is_explicit(self):
        root = Path('artifacts/test_cer064_lineage'); shutil.rmtree(root, ignore_errors=True); root.mkdir(parents=True)
        try:
            path = root / 'checkpoint.json'; obj = builder._load_checkpoint(path, 'u'); builder._save_checkpoint(path, obj)
            before = builder._load_checkpoint(path, 'u')['content_hash']; self.assertTrue(before)
            builder._save_checkpoint(path, builder._load_checkpoint(path, 'u'))
            after = builder._load_checkpoint(path, 'u')['content_hash']; self.assertTrue(after)
        finally: shutil.rmtree(root, ignore_errors=True)


if __name__ == '__main__': unittest.main()
