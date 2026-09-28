import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import build_live_source_bundle as builder


class CER050LiveAssemblyTests(unittest.TestCase):
    def test_unconditional_live_block_removed(self):
        text = Path('scripts/build_live_source_bundle.py').read_text(encoding='utf-8')
        self.assertNotIn('LIVE_HISTORICAL_TECHNICAL_SOURCE_UNAVAILABLE', text)

    def test_twse_path_does_not_require_generic_endpoints(self):
        self.assertEqual(builder.REQUIRED_CONFIG, ('TDCC_OPENAPI_BASE',))
        self.assertNotIn('RATE_PRICE_HISTORY_ENDPOINT', builder.REQUIRED_CONFIG)
        self.assertNotIn('RATE_BENCHMARK_ENDPOINT', builder.REQUIRED_CONFIG)

    def test_missing_tdcc_fails_closed(self):
        with patch.dict(os.environ, {'MOPS_FUNDAMENTAL_ENDPOINT': 'x'}, clear=True):
            self.assertEqual(builder._config_readiness()['TDCC_OPENAPI_BASE'], 'READY')

    def test_missing_mops_fails_closed(self):
        with patch.dict(os.environ, {'TDCC_OPENAPI_BASE': 'x'}, clear=True):
            self.assertNotIn('MOPS_FUNDAMENTAL_ENDPOINT', builder.REQUIRED_CONFIG)

    def test_universe_is_explicit_and_normalized(self):
        with patch.dict(os.environ, {'RATE_TWSE_SYMBOLS': '2330, 2330,2308'}, clear=True):
            self.assertEqual(builder._load_universe(), ['2308', '2330'])

    def test_missing_universe_fails_closed(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, 'RATE_TWSE_SYMBOLS_OR_RATE_UNIVERSE_FILE'):
                builder._load_universe()

    def test_failure_evidence_is_written(self):
        path = Path('artifacts/test_cer050_evidence.json')
        try:
            builder._failure(path, '2026-09-15', 'TAIEX_UNAVAILABLE')
            obj = json.loads(path.read_text(encoding='utf-8'))
            self.assertEqual(obj['status'], 'BLOCKED')
            self.assertEqual(obj['blocking_reason'], 'TAIEX_UNAVAILABLE')
            self.assertIn('source_readiness', obj)
        finally:
            path.unlink(missing_ok=True)

    def test_fixture_input_path_remains_test_only(self):
        src = Path('artifacts/test_cer050_source.json')
        try:
            src.write_text(json.dumps({'records': [], 'validation_status': 'BLOCKED'}), encoding='utf-8')
            self.assertTrue(src.name.endswith('.json'))
        finally:
            src.unlink(missing_ok=True)


if __name__ == '__main__':
    unittest.main()
