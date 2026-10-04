from __future__ import annotations

import copy
import hashlib
import json
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.thin_work_manifest import (
    CONTRACT_VERSION,
    INTRADAY_BLOCKED_DEPENDENCY,
    build_shadow_manifest,
    validate_shadow_manifest,
)


class RateThinWorkManifestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.artifact = self.tmp / "artifacts" / "RATE_PRODUCTION_SOURCE_BUNDLE_LATEST.json"
        self.artifact.parent.mkdir(parents=True)
        self.now = datetime(2026, 9, 15, 1, 0, tzinfo=timezone.utc)
        self.source = {
            "artifact": "RATE_PRODUCTION_SOURCE_BUNDLE",
            "input_snapshot_id": "rate-snapshot-fixture",
            "production_snapshot_id": "rate-prod-fixture",
            "validation_status": "PASS",
            "freshness_status": "PASS",
            "authorized_intraday_feed": "PASS",
            "domains": [
                {"domain": "market_daily"},
                {"domain": "market_intraday"},
                {"domain": "institutional"},
                {"domain": "large_holder"},
                {"domain": "fundamental"},
                {"domain": "benchmark"},
                {"domain": "trading_metadata"},
            ],
        }
        self.write_source(self.source)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write_source(self, payload):
        self.artifact.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")

    def resign_manifest(self, manifest):
        manifest["manifest_sha256"] = hashlib.sha256(
            json.dumps(
                {k: v for k, v in manifest.items() if k != "manifest_sha256"},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return manifest

    def manifest(self, **overrides):
        values = {
            "production_artifact_path": self.artifact,
            "cadence": "07:30",
            "run_id": "run-1",
            "event": "schedule",
            "commit_sha": "a" * 40,
            "market_date": "2026-09-15",
            "generated_at": "2026-09-15T00:30:00Z",
        }
        values.update(overrides)
        return build_shadow_manifest(**values)

    def test_contract_contains_required_fields_and_validates(self):
        manifest = self.manifest()
        self.assertEqual(manifest["version"], CONTRACT_VERSION)
        self.assertEqual(manifest["system"], "RATE")
        self.assertEqual(manifest["production_snapshot_id"], "rate-prod-fixture")
        self.assertEqual(manifest["input_snapshot_id"], "rate-snapshot-fixture")
        result = validate_shadow_manifest(manifest, root=self.tmp, expected_run_id="run-1", expected_commit_sha="a" * 40, now=self.now)
        self.assertEqual(result["validation_status"], "PASS")
        self.assertFalse(result["state_mutation_allowed"])
        self.assertFalse(result["portfolio_mutation_allowed"])
        self.assertFalse(result["ledger_mutation_allowed"])

    def test_eod_manifest_does_not_require_intraday_when_not_applicable(self):
        source = dict(self.source)
        source["required_datasets"] = ["market_daily", "institutional", "large_holder", "fundamental", "benchmark", "trading_metadata"]
        source["datasets_present"] = list(source["required_datasets"])
        source["domains"] = [{"domain": item} for item in source["required_datasets"]]
        source["authorized_intraday_feed"] = "NOT_APPLICABLE"
        self.write_source(source)
        for cadence in ("07:30", "19:30"):
            with self.subTest(cadence=cadence):
                manifest = self.manifest(cadence=cadence)
                self.assertNotIn("market_intraday", manifest["required_datasets"])
                self.assertEqual(manifest["datasets_missing"], [])
                self.assertEqual(manifest["blocked_dependencies"], [])
                self.assertEqual(validate_shadow_manifest(manifest, root=self.tmp, now=self.now)["validation_status"], "PASS")

    def test_manifest_with_contract_validation_evidence_revalidates(self):
        manifest = self.manifest()
        validation = validate_shadow_manifest(manifest, root=self.tmp, now=self.now)
        stored = {**manifest, "contract_validation": validation}
        self.assertEqual(validate_shadow_manifest(stored, root=self.tmp, now=self.now)["validation_status"], "PASS")

    def test_intraday_without_authorized_feed_blocks_without_fallback(self):
        source = dict(self.source)
        source["authorized_intraday_feed"] = "BLOCKED"
        self.write_source(source)
        manifest = self.manifest(cadence="09:30")
        self.assertIn(INTRADAY_BLOCKED_DEPENDENCY, manifest["blocked_dependencies"])
        result = validate_shadow_manifest(manifest, root=self.tmp, now=self.now)
        self.assertEqual(result["validation_status"], "FAIL_CLOSED")
        self.assertIn("MISSING_INTRADAY_BLOCKED_DEPENDENCY", validate_shadow_manifest({**manifest, "blocked_dependencies": []}, root=self.tmp, now=self.now)["errors"])

    def test_intraday_with_authorized_feed_does_not_require_blocked_dependency(self):
        for cadence in ("09:30", "12:00"):
            with self.subTest(cadence=cadence):
                manifest = self.manifest(cadence=cadence)
                self.assertNotIn(INTRADAY_BLOCKED_DEPENDENCY, manifest["blocked_dependencies"])
                result = validate_shadow_manifest(manifest, root=self.tmp, now=self.now)
                self.assertEqual(result["validation_status"], "PASS")

    def test_intraday_missing_feed_fails_closed_for_each_intraday_cadence(self):
        source = dict(self.source)
        source["authorized_intraday_feed"] = "BLOCKED"
        self.write_source(source)
        for cadence in ("09:30", "12:00"):
            with self.subTest(cadence=cadence):
                manifest = self.manifest(cadence=cadence)
                self.assertIn(INTRADAY_BLOCKED_DEPENDENCY, manifest["blocked_dependencies"])
                result = validate_shadow_manifest(manifest, root=self.tmp, now=self.now)
                self.assertEqual(result["validation_status"], "FAIL_CLOSED")

    def test_missing_production_snapshot_id_fails_closed(self):
        source = dict(self.source)
        source.pop("production_snapshot_id")
        self.write_source(source)
        manifest = self.manifest()
        self.assertIsNone(manifest["production_snapshot_id"])
        result = validate_shadow_manifest(manifest, root=self.tmp, now=self.now)
        self.assertEqual(result["validation_status"], "FAIL_CLOSED")
        self.assertIn("MISSING_PRODUCTION_SNAPSHOT_ID", result["errors"])

    def test_snapshot_id_does_not_alias_production_snapshot_id(self):
        source = dict(self.source)
        source.pop("production_snapshot_id")
        source["snapshot_id"] = "legacy-snapshot"
        self.write_source(source)
        manifest = self.manifest()
        self.assertIsNone(manifest["production_snapshot_id"])
        self.assertEqual(manifest["input_snapshot_id"], "rate-snapshot-fixture")
        result = validate_shadow_manifest(manifest, root=self.tmp, now=self.now)
        self.assertEqual(result["validation_status"], "FAIL_CLOSED")
        self.assertIn("MISSING_PRODUCTION_SNAPSHOT_ID", result["errors"])

    def test_input_snapshot_id_is_not_used_as_production_snapshot_id(self):
        source = dict(self.source)
        source["production_snapshot_id"] = "rate-prod-distinct"
        source["input_snapshot_id"] = "rate-input-distinct"
        self.write_source(source)
        manifest = self.manifest()
        self.assertEqual(manifest["production_snapshot_id"], "rate-prod-distinct")
        self.assertEqual(manifest["input_snapshot_id"], "rate-input-distinct")
        result = validate_shadow_manifest(manifest, root=self.tmp, expected_production_snapshot_id="rate-prod-distinct", now=self.now)
        self.assertEqual(result["validation_status"], "PASS")

    def test_production_snapshot_id_mismatch_fails_closed(self):
        manifest = self.manifest()
        result = validate_shadow_manifest(manifest, root=self.tmp, expected_production_snapshot_id="other-prod", now=self.now)
        self.assertEqual(result["validation_status"], "FAIL_CLOSED")
        self.assertIn("PRODUCTION_SNAPSHOT_BINDING_MISMATCH", result["errors"])

    def test_validation_status_must_be_exactly_pass(self):
        self.assertEqual(validate_shadow_manifest(self.manifest(), root=self.tmp, now=self.now)["validation_status"], "PASS")
        for status in ("FAIL", "BLOCKED", None, "UNKNOWN"):
            with self.subTest(status=status):
                manifest = copy.deepcopy(self.manifest())
                if status is None:
                    manifest.pop("validation_status")
                else:
                    manifest["validation_status"] = status
                self.resign_manifest(manifest)
                result = validate_shadow_manifest(manifest, root=self.tmp, now=self.now)
                self.assertEqual(result["validation_status"], "FAIL_CLOSED")
                self.assertIn("VALIDATION_STATUS_NOT_PASS", result["errors"])

    def test_freshness_status_must_be_exactly_pass(self):
        self.assertEqual(validate_shadow_manifest(self.manifest(), root=self.tmp, now=self.now)["validation_status"], "PASS")
        for status in ("STALE", "BLOCKED", None, "UNKNOWN"):
            with self.subTest(status=status):
                manifest = copy.deepcopy(self.manifest())
                if status is None:
                    manifest.pop("freshness_status")
                else:
                    manifest["freshness_status"] = status
                self.resign_manifest(manifest)
                result = validate_shadow_manifest(manifest, root=self.tmp, now=self.now)
                self.assertEqual(result["validation_status"], "FAIL_CLOSED")
                self.assertIn("FRESHNESS_STATUS_NOT_PASS", result["errors"])

    def test_source_status_must_be_pass(self):
        for status in ("FAIL", "BLOCKED", None, "UNKNOWN"):
            with self.subTest(status=status):
                manifest = copy.deepcopy(self.manifest())
                if status is None:
                    manifest.pop("source_status")
                else:
                    manifest["source_status"] = status
                self.resign_manifest(manifest)
                result = validate_shadow_manifest(manifest, root=self.tmp, now=self.now)
                self.assertEqual(result["validation_status"], "FAIL_CLOSED")
                self.assertIn("SOURCE_STATUS_NOT_PASS", result["errors"])

    def test_negative_paths_fail_closed(self):
        cases = {}
        base = self.manifest()
        cases["invalid_snapshot_binding"] = (copy.deepcopy(base), {"expected_production_snapshot_id": "other"})
        cases["commit_mismatch"] = (copy.deepcopy(base), {"expected_commit_sha": "b" * 40})
        cases["run_id_mismatch"] = (copy.deepcopy(base), {"expected_run_id": "other"})
        future = copy.deepcopy(base)
        future["generated_at"] = "2026-09-16T00:30:00Z"
        future["manifest_sha256"] = "bad"
        cases["future_dated_artifact"] = (future, {})
        stale = copy.deepcopy(base)
        stale["generated_at"] = (self.now - timedelta(days=3)).isoformat().replace("+00:00", "Z")
        stale["manifest_sha256"] = "bad"
        cases["stale_artifact"] = (stale, {})
        failed = copy.deepcopy(base)
        failed["validation_status"] = "FAIL"
        failed["manifest_sha256"] = "bad"
        cases["validation_fail"] = (failed, {})
        missing_dataset = copy.deepcopy(base)
        missing_dataset["datasets_missing"] = ["benchmark"]
        missing_dataset["manifest_sha256"] = "bad"
        cases["missing_required_dataset"] = (missing_dataset, {})
        bad_previous = copy.deepcopy(base)
        bad_previous["previous_state_requirement"] = "OPTIONAL"
        bad_previous["manifest_sha256"] = "bad"
        cases["invalid_previous_state_requirement"] = (bad_previous, {})
        corrupted = copy.deepcopy(base)
        corrupted["manifest_sha256"] = "0" * 64
        cases["corrupted_manifest"] = (corrupted, {})
        for name, (manifest, expectations) in cases.items():
            with self.subTest(name=name):
                result = validate_shadow_manifest(manifest, root=self.tmp, now=self.now, **expectations)
                self.assertEqual(result["validation_status"], "FAIL_CLOSED")
                self.assertFalse(result["state_mutation_allowed"])
                self.assertFalse(result["portfolio_mutation_allowed"])
                self.assertFalse(result["ledger_mutation_allowed"])

    def test_missing_artifact_fails_closed_before_manifest_creation(self):
        self.artifact.unlink()
        with self.assertRaisesRegex(ValueError, "MISSING_ARTIFACT"):
            self.manifest()

    def test_existing_v1_source_bundle_schema_is_unchanged(self):
        schema = json.loads(Path("config/RATE_PRODUCTION_SOURCE_BUNDLE_SCHEMA_V1.json").read_text(encoding="utf-8"))
        self.assertEqual(schema["schema_id"], "RATE-PRODUCTION-SOURCE-BUNDLE-V1")
        self.assertNotIn("thin_work", json.dumps(schema).lower())


if __name__ == "__main__":
    unittest.main()
