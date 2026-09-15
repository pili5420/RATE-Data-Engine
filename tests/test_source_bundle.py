import json, shutil, unittest
from pathlib import Path
from src.source_bundle import create_input_snapshot_id, validate_records

class SourceBundleTests(unittest.TestCase):
    def test_snapshot_id_is_replayable(self):
        root = Path(__file__).resolve().parent / ".tmp_bundle"
        root.mkdir(exist_ok=True)
        try:
            payload = [{"symbol":"AAA","market_date":"2026-09-15"}]
            (root / "rows.json").write_text(json.dumps(payload), encoding="utf-8")
            manifest = {"bundle_version":"RATE-PRODUCTION-SOURCE-V1","files":[{"path":"rows.json"}]}
            self.assertEqual(create_input_snapshot_id(root, manifest), create_input_snapshot_id(root, manifest))
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_missing_required_data_fails(self):
        errors = validate_records([{"symbol":"AAA"}], input_snapshot_id="rate-snapshot-test")
        self.assertTrue(any(error.startswith("MISSING_REQUIRED_DATA") for error in errors))
