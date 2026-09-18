import json
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.bootstrap_cache import compatibility_prefix, versioned_cache_key
from scripts import bootstrap_live_history as bootstrap
from scripts import build_live_source_bundle as builder


class CER062BootstrapTests(unittest.TestCase):
    def test_versioned_cache_key_and_restore_prefix(self):
        prefix = compatibility_prefix('u')
        key = versioned_cache_key('u', '123', '2')
        self.assertTrue(key.startswith(prefix)); self.assertTrue(key.endswith('123-2'))
        self.assertNotEqual(key, versioned_cache_key('u', '124', '1'))

    def test_checkpoint_compatibility_and_atomic_evidence(self):
        root = Path('artifacts/test_cer062_atomic'); shutil.rmtree('artifacts/test_cer062_atomic', ignore_errors=True); root.mkdir(parents=True)
        try:
            cp = root / 'checkpoint.json'; ev = root / 'evidence.json'
            obj = builder._load_checkpoint(cp, 'u'); builder._save_checkpoint(cp, obj)
            self.assertEqual(builder.validate_checkpoint(cp, 'u')['status'], 'PASS')
            bootstrap._evidence(ev, {'checkpoint': obj, 'checkpoint_path': cp, 'checkpoint_digest_before': obj.get('content_hash'), 'chunk_sequence': 1, 'loaded': 0, 'retrieved': 0, 'validated': 0, 'required_periods': 1, 'progress': {'current_symbol': None, 'current_period': None, 'last_successful_period': None, 'raw_sessions_by_symbol': {}, 'aligned_sessions_by_symbol': {}}}, 'CHUNK_COMPLETE_MORE_WORK')
            self.assertEqual(json.loads(ev.read_text())['status'], 'CHUNK_COMPLETE_MORE_WORK')
        finally: shutil.rmtree(root, ignore_errors=True)

    def test_bounded_chunk_does_not_redownload_completed_period(self):
        root = Path('artifacts/test_cer062_resume'); shutil.rmtree('artifacts/test_cer062_resume', ignore_errors=True); root.mkdir(parents=True)
        try:
            universe = root / 'universe.json'; cp = root / 'checkpoint.json'; ev = root / 'evidence.json'
            universe.write_text(json.dumps({'universe_symbol_digest': 'u', 'symbols': [{'symbol': '3036', 'market': 'TWSE'}]}), encoding='utf-8')
            obj = builder._load_checkpoint(cp, 'u'); obj['months']['3036:202601'] = {'symbol': '3036', 'market': 'TWSE', 'year_month': '202601', 'provider': 'TWSE', 'dataset': 'STOCK_DAY', 'records': [], 'content_hash': 'x', 'validation_status': 'PASS'}
            # Make the fixture hash valid.
            import hashlib
            obj['months']['3036:202601']['content_hash'] = hashlib.sha256(b'[]').hexdigest(); builder._save_checkpoint(cp, obj)
            with patch.object(bootstrap, '_periods', return_value=['202601']), patch.object(bootstrap, '_normalized_period') as fetch:
                out = bootstrap.run(trading_date='2026-01-31', universe_file=universe, checkpoint_path=cp, evidence_path=ev, max_new_periods=1, max_runtime_seconds=60)
            fetch.assert_not_called(); self.assertGreaterEqual(out['loaded'], 1)
        finally: shutil.rmtree(root, ignore_errors=True)


if __name__ == '__main__': unittest.main()
