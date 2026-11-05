"""Offline synthetic R2 evidence inventory, privacy, and execution binding."""
import json
import unittest

from src.intraday_fugle_live_consumption_fence import canonical_digest
from src.intraday_fugle_r2_evidence import (
    FugleR2EvidenceError,
    build_r2_evidence_manifest,
    verify_r2_evidence_manifest,
)


class FugleR2EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.binding = {
            "source_sha": "a" * 40, "workflow_sha256": "b" * 64,
            "permit_id": "SYNTHETIC_R2_PERMIT", "trigger_id": "SYNTHETIC_R2_TRIGGER",
            "run_id": 123, "job_id": 456, "run_attempt": 1,
        }
        self.custody = {
            "artifact": "RATE_FUGLE_R2_PRIVATE_CUSTODY_ATTESTATION_V1",
            "custody_id": "SYNTHETIC_PRIVATE_STORE",
            "control_center_decision_id": "SYNTHETIC_CUSTODY_DECISION",
            "visibility": "PRIVATE", "access_control_verified": True,
            "public_upload_allowed": False, "credential_persistence_allowed": False,
        }
        self.pin = canonical_digest(self.custody)
        self.artifacts = {"admission.json": b'{"status":"PASS"}',
                          "result.json": b'{"synthetic_value":123}'}
        self.expected = tuple(self.artifacts)

    def build(self, **overrides):
        args = dict(expected_artifacts=self.expected, binding=self.binding,
                    custody=self.custody, expected_custody_sha256=self.pin, status="COMPLETE")
        args.update(overrides)
        return build_r2_evidence_manifest(self.artifacts, **args)

    def verify(self, manifest, **overrides):
        args = dict(expected_binding=self.binding, expected_artifacts=self.expected,
                    custody=self.custody, expected_custody_sha256=self.pin,
                    expected_manifest_sha256=manifest["manifest_sha256"])
        args.update(overrides)
        return verify_r2_evidence_manifest(manifest, self.artifacts, **args)

    def test_complete_inventory_sha256_and_run_binding_round_trip(self):
        manifest = self.build()
        self.assertEqual(self.verify(manifest), manifest)
        self.assertEqual(manifest["binding"], self.binding)
        self.assertEqual(len(manifest["artifacts"]), 2)
        self.assertTrue(all(len(entry["sha256"]) == 64 for entry in manifest["artifacts"]))

    def test_manifest_contains_no_private_payload(self):
        manifest = self.build()
        self.assertNotIn("synthetic_value", json.dumps(manifest))
        self.assertFalse(manifest["artifact_contents_embedded"])
        self.assertFalse(manifest["public_upload_allowed"])

    def test_artifact_mutation_fails_integrity(self):
        manifest = self.build()
        self.artifacts["result.json"] = b'{"synthetic_value":124}'
        with self.assertRaisesRegex(FugleR2EvidenceError, "INTEGRITY"):
            self.verify(manifest)

    def test_manifest_mutation_fails_integrity(self):
        manifest = self.build()
        manifest["artifacts"][0]["sha256"] = "c" * 64
        with self.assertRaisesRegex(FugleR2EvidenceError, "INTEGRITY"):
            self.verify(manifest)

    def test_rehashed_replacement_rejected_by_external_manifest_pin(self):
        original_pin = self.build()["manifest_sha256"]
        self.artifacts["result.json"] = b'{"synthetic_value":999}'
        replacement = self.build()
        with self.assertRaisesRegex(FugleR2EvidenceError, "MANIFEST_PIN_MISMATCH"):
            self.verify(replacement, expected_manifest_sha256=original_pin)

    def test_source_workflow_permit_trigger_run_and_job_mismatch_fail(self):
        manifest = self.build()
        for key, replacement in (("source_sha", "c" * 40), ("workflow_sha256", "c" * 64),
                                 ("permit_id", "OTHER_PERMIT"), ("trigger_id", "OTHER_TRIGGER"),
                                 ("run_id", 789), ("job_id", 789)):
            with self.subTest(key=key), self.assertRaisesRegex(FugleR2EvidenceError, "INTEGRITY"):
                self.verify(manifest, expected_binding={**self.binding, key: replacement})

    def test_reentry_attempt_forbidden(self):
        with self.assertRaisesRegex(FugleR2EvidenceError, "REENTRY"):
            self.build(binding={**self.binding, "run_attempt": 2})

    def test_missing_artifact_cannot_be_complete(self):
        del self.artifacts["result.json"]
        with self.assertRaisesRegex(FugleR2EvidenceError, "INCOMPLETE"):
            self.build()

    def test_partial_and_unknown_never_become_review_eligible(self):
        del self.artifacts["result.json"]
        for status in ("PARTIAL", "UNKNOWN"):
            with self.subTest(status=status):
                manifest = self.build(status=status)
                self.assertFalse(manifest["review_eligible"])
                self.assertEqual(manifest["missing_artifacts"], ["result.json"])
                with self.assertRaisesRegex(FugleR2EvidenceError, "PARTIAL_OR_UNKNOWN"):
                    self.verify(manifest)

    def test_extra_artifact_and_inventory_traversal_forbidden(self):
        self.artifacts["extra.json"] = b"{}"
        with self.assertRaisesRegex(FugleR2EvidenceError, "UNEXPECTED"):
            self.build()
        with self.assertRaisesRegex(FugleR2EvidenceError, "INVENTORY_INVALID"):
            self.build(expected_artifacts=("../result.json",))

    def test_public_unknown_or_unpinned_custody_fails(self):
        with self.assertRaisesRegex(FugleR2EvidenceError, "PIN_MISMATCH"):
            self.build(expected_custody_sha256="c" * 64)
        for key, value in (("visibility", "PUBLIC"), ("visibility", "UNKNOWN"),
                           ("access_control_verified", False), ("public_upload_allowed", True)):
            with self.subTest(key=key, value=value):
                custody = {**self.custody, key: value}
                with self.assertRaisesRegex(FugleR2EvidenceError, "PRIVATE_CUSTODY_UNPROVEN"):
                    self.build(custody=custody, expected_custody_sha256=canonical_digest(custody))

    def test_credentials_and_raw_payload_rejected_without_echo(self):
        for payload in ({"api_key": "SYNTHETIC_SECRET"},
                        {"apiKey": "SYNTHETIC_SECRET"},
                        {"nested": [{"headers": {"Authorization": "SYNTHETIC_SECRET"}}]},
                        {"raw_response": "SYNTHETIC_PRIVATE_DATA"},
                        {"message": "Bearer SYNTHETIC_SECRET"}):
            with self.subTest(payload=payload):
                self.artifacts["result.json"] = json.dumps(payload).encode()
                with self.assertRaisesRegex(FugleR2EvidenceError, "PAYLOAD_FORBIDDEN") as caught:
                    self.build()
                self.assertNotIn("SYNTHETIC_SECRET", str(caught.exception))

    def test_malformed_json_fails_without_echo(self):
        self.artifacts["result.json"] = b"SYNTHETIC_SECRET_INVALID_JSON"
        with self.assertRaisesRegex(FugleR2EvidenceError, "JSON_INVALID") as caught:
            self.build()
        self.assertNotIn("SYNTHETIC_SECRET", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
