
import json
import shutil
import unittest
from datetime import datetime, timezone
from pathlib import Path

from scripts.publish_production_source_bundle_latest import load_json, publish_latest


class ProductionSourceLatestPublisherTests(unittest.TestCase):
    def setUp(self):
        self.root = Path("artifacts/test-production-source-latest")
        shutil.rmtree(self.root, ignore_errors=True)
        self.root.mkdir(parents=True, exist_ok=True)
        self.bundle_path = self.root / "bundle.json"
        self.evidence_path = self.root / "evidence.json"

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def bundle(self, status="PASS"):
        records = [{"symbol": f"{1000 + idx}"} for idx in range(30)]
        return {
            "schema_version": "RATE-CER073-SOURCE-BUNDLE-V1",
            "validation_status": status,
            "source_bundle_validation": status,
            "trading_date": "2026-09-21",
            "source_provenance": {"source": "AUTHORIZED_LIVE", "retrieval_timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")},
            "input_snapshot_id": "rate-prod-source-snapshot-test",
            "coverage": "30/30",
            "decision_records": records,
            "records": records,
        }

    def write_bundle(self, obj):
        self.bundle_path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")

    def test_pass_writes_immutable_snapshot_and_latest(self):
        self.write_bundle(self.bundle())
        ev = publish_latest(source_bundle_path=self.bundle_path, trading_date="2026-09-21", cadence="07:30", artifacts_root=self.root, workflow_run_id="run-1", workflow_job_id="job-1", evidence_output=self.evidence_path)
        self.assertEqual(ev["publish_result"], "PASS")
        latest = load_json(self.root / "RATE_PRODUCTION_SOURCE_BUNDLE_LATEST.json")
        self.assertEqual(latest["validation_status"], "PASS")
        for key in ("snapshot_id", "trading_date", "cadence", "retrieval_timestamp", "workflow_run_id", "previous_snapshot_id"):
            self.assertIn(key, latest)
        self.assertEqual(latest["workflow_run_id"], "run-1")
        self.assertTrue((self.root / latest["immutable_snapshot_path"].replace("artifacts/test-production-source-latest/", "")).exists() or Path(latest["immutable_snapshot_path"]).exists())

    def test_second_pass_links_previous_snapshot_id(self):
        self.write_bundle(self.bundle())
        first = publish_latest(source_bundle_path=self.bundle_path, trading_date="2026-09-21", cadence="07:30", artifacts_root=self.root, workflow_run_id="run-1", workflow_job_id="job-1", evidence_output=self.evidence_path)
        second = publish_latest(source_bundle_path=self.bundle_path, trading_date="2026-09-21", cadence="09:30", artifacts_root=self.root, workflow_run_id="run-2", workflow_job_id="job-2", evidence_output=self.evidence_path)
        latest = load_json(self.root / "RATE_PRODUCTION_SOURCE_BUNDLE_LATEST.json")
        self.assertEqual(second["previous_snapshot_id"], first["snapshot_id"])
        self.assertEqual(latest["previous_snapshot_id"], first["snapshot_id"])
        self.assertEqual(latest["cadence"], "09:30")

    def test_fail_does_not_overwrite_latest(self):
        self.write_bundle(self.bundle())
        publish_latest(source_bundle_path=self.bundle_path, trading_date="2026-09-21", cadence="07:30", artifacts_root=self.root, workflow_run_id="run-1", workflow_job_id="job-1", evidence_output=self.evidence_path)
        before = (self.root / "RATE_PRODUCTION_SOURCE_BUNDLE_LATEST.json").read_text(encoding="utf-8")
        self.write_bundle(self.bundle(status="BLOCKED"))
        ev = publish_latest(source_bundle_path=self.bundle_path, trading_date="2026-09-21", cadence="12:00", artifacts_root=self.root, workflow_run_id="run-2", workflow_job_id="job-2", evidence_output=self.evidence_path)
        after = (self.root / "RATE_PRODUCTION_SOURCE_BUNDLE_LATEST.json").read_text(encoding="utf-8")
        self.assertEqual(ev["publish_result"], "BLOCKED")
        self.assertEqual(before, after)
        self.assertEqual(load_json(self.evidence_path)["publish_result"], "BLOCKED")

    def test_missing_completeness_does_not_overwrite_latest(self):
        self.write_bundle(self.bundle())
        publish_latest(source_bundle_path=self.bundle_path, trading_date="2026-09-21", cadence="07:30", artifacts_root=self.root, workflow_run_id="run-1", workflow_job_id="job-1", evidence_output=self.evidence_path)
        before = load_json(self.root / "RATE_PRODUCTION_SOURCE_BUNDLE_LATEST.json")
        bad = self.bundle(); bad["decision_records"] = []
        self.write_bundle(bad)
        ev = publish_latest(source_bundle_path=self.bundle_path, trading_date="2026-09-21", cadence="19:30", artifacts_root=self.root, workflow_run_id="run-3", workflow_job_id="job-3", evidence_output=self.evidence_path)
        after = load_json(self.root / "RATE_PRODUCTION_SOURCE_BUNDLE_LATEST.json")
        self.assertEqual(ev["publish_result"], "BLOCKED")
        self.assertEqual(before["snapshot_id"], after["snapshot_id"])


if __name__ == "__main__":
    unittest.main()
