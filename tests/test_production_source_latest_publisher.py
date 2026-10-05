
import json
import shutil
import unittest
from datetime import datetime, timezone
from pathlib import Path

import scripts.publish_production_source_bundle_latest as publisher
from scripts.publish_production_source_bundle_latest import (
    build_delivery_targets,
    load_json,
    publish_latest,
    validate_delivery_targets,
)
from src.thin_work_manifest import validate_shadow_manifest


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
            "source_status": status,
            "freshness_status": status,
            "production_snapshot_id": "rate-source-snapshot-test",
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
        self.assertEqual(ev["delivery_target_validation"]["validation_status"], "PASS")
        self.assertEqual(ev["delivery_target_validation"]["target_count"], 5)
        self.assertEqual(ev["delivery_target_validation"]["duplicate_pairs"], [])
        latest = load_json(self.root / "RATE_PRODUCTION_SOURCE_BUNDLE_LATEST.json")
        self.assertEqual(latest["validation_status"], "PASS")
        for key in ("snapshot_id", "trading_date", "cadence", "retrieval_timestamp", "workflow_run_id", "previous_snapshot_id"):
            self.assertIn(key, latest)
        self.assertEqual(latest["workflow_run_id"], "run-1")
        self.assertTrue((self.root / latest["immutable_snapshot_path"].replace("artifacts/test-production-source-latest/", "")).exists() or Path(latest["immutable_snapshot_path"]).exists())
        manifest_latest = load_json(self.root / "RATE_THIN_WORK_PRODUCTION_BUNDLE_MANIFEST_LATEST.json")
        manifest = load_json(manifest_latest["manifest_path"])
        self.assertEqual(manifest["production_snapshot_id"], latest["production_snapshot_id"])
        self.assertEqual(manifest["run_id"], "run-1")
        self.assertEqual(validate_shadow_manifest(manifest, root=Path("."), expected_run_id="run-1", expected_production_snapshot_id=latest["production_snapshot_id"])["validation_status"], "PASS")

    def test_normal_1930_publication_has_unique_delivery_targets(self):
        self.write_bundle(self.bundle())
        ev = publish_latest(source_bundle_path=self.bundle_path, trading_date="2026-09-21", cadence="19:30", artifacts_root=self.root, workflow_run_id="run-1930", workflow_job_id="job-1930", evidence_output=self.evidence_path)
        self.assertEqual(ev["publish_result"], "PASS")
        paths = [target["path"] for target in ev["delivery_targets"]]
        self.assertEqual(len(paths), len(set(paths)))
        self.assertEqual(ev["delivery_target_validation"]["validation_status"], "PASS")

    def test_artificial_duplicate_delivery_target_fails_closed(self):
        targets = build_delivery_targets(
            snapshot_path=self.root / "snapshot.json",
            immutable_bundle_path=self.root / "bundle.json",
            manifest_path=self.root / "manifest.json",
            latest_path=self.root / "latest.json",
            manifest_latest_path=self.root / "manifest-latest.json",
        )
        targets.append({"kind": "thin_work_manifest", "path": targets[1]["path"]})
        validation = validate_delivery_targets(targets)
        self.assertEqual(validation["validation_status"], "FAIL")
        self.assertIn("DUPLICATE_DELIVERY_TARGET", validation["errors"])
        self.assertEqual(validation["duplicate_pairs"][0]["canonical_path"], targets[1]["path"])

    def test_artificial_duplicate_publish_fails_closed_without_latest_update(self):
        self.write_bundle(self.bundle())
        original_builder = publisher.build_delivery_targets

        def duplicate_builder(**kwargs):
            targets = original_builder(**kwargs)
            targets.append({"kind": "thin_work_manifest", "path": targets[1]["path"]})
            return targets

        publisher.build_delivery_targets = duplicate_builder
        try:
            ev = publish_latest(source_bundle_path=self.bundle_path, trading_date="2026-09-21", cadence="19:30", artifacts_root=self.root, workflow_run_id="run-duplicate", workflow_job_id="job-duplicate", evidence_output=self.evidence_path)
        finally:
            publisher.build_delivery_targets = original_builder
        self.assertNotEqual(ev["publish_result"], "PASS")
        self.assertEqual(ev["blocking_reason"], "DUPLICATE_DELIVERY_TARGET")
        self.assertEqual(ev["delivery_target_validation"]["validation_status"], "FAIL")
        self.assertFalse((self.root / "RATE_PRODUCTION_SOURCE_BUNDLE_LATEST.json").exists())

    def test_run_37213072716_structural_replay_construction_case_no_duplicate_targets(self):
        replay_classification = "STRUCTURAL_REPLAY"
        bundle = self.bundle()
        bundle["trading_date"] = "2026-10-02"
        bundle["production_snapshot_id"] = "rate-source-snapshot-1b200fe6d2f0360447fe1926"
        self.write_bundle(bundle)
        ev = publish_latest(source_bundle_path=self.bundle_path, trading_date="2026-10-02", cadence="19:30", artifacts_root=self.root, workflow_run_id="37213072716", workflow_job_id="source-acquisition", evidence_output=self.evidence_path)
        self.assertEqual(replay_classification, "STRUCTURAL_REPLAY")
        self.assertEqual(ev["publish_result"], "PASS")
        self.assertEqual(ev["production_snapshot_id"], "rate-source-snapshot-1b200fe6d2f0360447fe1926")
        self.assertEqual(ev["delivery_target_validation"]["validation_status"], "PASS")
        self.assertEqual(ev["delivery_target_validation"]["duplicate_pairs"], [])

    def test_production_bundle_and_thin_work_manifest_target_set_complete_without_dedupe(self):
        self.write_bundle(self.bundle())
        ev = publish_latest(source_bundle_path=self.bundle_path, trading_date="2026-09-21", cadence="19:30", artifacts_root=self.root, workflow_run_id="run-targets", workflow_job_id="job-targets", evidence_output=self.evidence_path)
        self.assertEqual(ev["publish_result"], "PASS")
        kinds = [target["kind"] for target in ev["delivery_targets"]]
        self.assertEqual(kinds, [
            "production_bundle_snapshot",
            "production_bundle_immutable",
            "thin_work_manifest",
            "production_bundle_latest",
            "thin_work_manifest_latest",
        ])
        self.assertEqual(len(kinds), 5)
        self.assertEqual(len({target["path"] for target in ev["delivery_targets"]}), 5)
        self.assertEqual(ev["thin_work_manifest_path"], next(target["path"] for target in ev["delivery_targets"] if target["kind"] == "thin_work_manifest"))
        self.assertEqual(ev["immutable_bundle_path"], next(target["path"] for target in ev["delivery_targets"] if target["kind"] == "production_bundle_immutable"))

    def test_second_eod_pass_links_previous_snapshot_id(self):
        self.write_bundle(self.bundle())
        first = publish_latest(source_bundle_path=self.bundle_path, trading_date="2026-09-21", cadence="07:30", artifacts_root=self.root, workflow_run_id="run-1", workflow_job_id="job-1", evidence_output=self.evidence_path)
        second = publish_latest(source_bundle_path=self.bundle_path, trading_date="2026-09-21", cadence="19:30", artifacts_root=self.root, workflow_run_id="run-2", workflow_job_id="job-2", evidence_output=self.evidence_path)
        latest = load_json(self.root / "RATE_PRODUCTION_SOURCE_BUNDLE_LATEST.json")
        self.assertEqual(second["previous_snapshot_id"], first["snapshot_id"])
        self.assertEqual(latest["previous_snapshot_id"], first["snapshot_id"])
        self.assertEqual(latest["cadence"], "19:30")

    def test_intraday_without_authorized_feed_does_not_overwrite_latest(self):
        self.write_bundle(self.bundle())
        publish_latest(source_bundle_path=self.bundle_path, trading_date="2026-09-21", cadence="07:30", artifacts_root=self.root, workflow_run_id="run-1", workflow_job_id="job-1", evidence_output=self.evidence_path)
        before = load_json(self.root / "RATE_PRODUCTION_SOURCE_BUNDLE_LATEST.json")
        ev = publish_latest(source_bundle_path=self.bundle_path, trading_date="2026-09-21", cadence="09:30", artifacts_root=self.root, workflow_run_id="run-2", workflow_job_id="job-2", evidence_output=self.evidence_path)
        after = load_json(self.root / "RATE_PRODUCTION_SOURCE_BUNDLE_LATEST.json")
        self.assertEqual(ev["publish_result"], "BLOCKED")
        self.assertEqual(ev["blocking_reason"], "THIN_WORK_MANIFEST_VALIDATION_NOT_PASS")
        self.assertEqual(before["snapshot_id"], after["snapshot_id"])

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

    def test_missing_production_snapshot_id_does_not_publish(self):
        bundle = self.bundle()
        del bundle["production_snapshot_id"]
        self.write_bundle(bundle)
        ev = publish_latest(source_bundle_path=self.bundle_path, trading_date="2026-09-21", cadence="07:30", artifacts_root=self.root, workflow_run_id="run-1", workflow_job_id="job-1", evidence_output=self.evidence_path)
        self.assertEqual(ev["publish_result"], "BLOCKED")
        self.assertEqual(ev["blocking_reason"], "SOURCE_BUNDLE_VALIDATION_NOT_PASS")
        self.assertFalse((self.root / "RATE_PRODUCTION_SOURCE_BUNDLE_LATEST.json").exists())


if __name__ == "__main__":
    unittest.main()
