"""Tests for the completed-real-qualification evidence review gate."""
from __future__ import annotations

from copy import deepcopy
import unittest

from src.intraday_activation_candidate_review import canonical_digest
from src.intraday_cloudflare_d1_real_qualification_evidence_review import (
    CloudflareEvidenceReviewError,
    EXPECTED_RUNTIME_STATUSES,
    REQUIRED_RESULT_EVIDENCE,
    validate_cloudflare_real_qualification_evidence,
)
from src.intraday_cloudflare_d1_real_qualification_plan import (
    ADMIN_OPERATIONS,
    CLEANUP_OPERATIONS,
    RUNTIME_PROBES,
)

AUTH = "a" * 64
MARKER = "b" * 64
MAIN = "c" * 40
RUN_ID = 123456
JOB_ID = 789012
D1_ID = "11111111-1111-1111-1111-111111111111"


def evidence_manifest():
    return {
        name: {
            "reference": "artifact://cloudflare-real-qualification/" + name.lower(),
            "sha256": (format(index + 1, "x") * 64)[:64],
        }
        for index, name in enumerate(sorted(REQUIRED_RESULT_EVIDENCE))
    }


def package():
    manifest = evidence_manifest()
    suffix = AUTH[:12]
    return {
        "artifact": "RATE_CLOUDFLARE_D1_REAL_QUALIFICATION_EVIDENCE_PACKAGE_V1",
        "status": "EXECUTION_COMPLETED",
        "execution": {
            "workflow_run_id": RUN_ID,
            "workflow_job_id": JOB_ID,
            "workflow_attempt": 1,
            "rerun_count": 0,
            "cloudflare_authorization_qualification_sha256": AUTH,
            "current_main_sha": MAIN,
            "request_count": 17,
            "admin_and_cleanup_requests": 11,
            "runtime_requests": 6,
            "automatic_retries": 0,
            "redirects_followed": 0,
            "fallback_used": False,
            "admin_operations": list(ADMIN_OPERATIONS),
            "runtime_probes": list(RUNTIME_PROBES),
            "cleanup_operations": list(CLEANUP_OPERATIONS),
        },
        "consumption_marker": {
            "marker_execution_result_sha256": MARKER,
            "marker_ref":
                "refs/tags/rate-v11-qualification-consumed/cloudflare-d1-"
                + "d" * 16,
            "marker_target_sha": MAIN,
            "marker_creation_consumed": True,
            "readback_verified": True,
            "create_attempts": 1,
            "create_retries": 0,
            "cloudflare_requests_before_marker": 0,
        },
        "resources": {
            "d1_database_id": D1_ID,
            "d1_database_name": "rate-v11-qual-" + suffix,
            "d1_read_replication": "disabled",
            "worker_script_id": "rate-v11-qual-" + suffix,
            "worker_script_sha256": "e" * 64,
            "worker_secret_metadata_present": True,
            "workers_dev_endpoint":
                "https://rate-v11-qual-" + suffix + ".account-subdomain.workers.dev",
            "schema_sha256": "f" * 64,
        },
        "runtime_probe_results": {
            "statuses": dict(EXPECTED_RUNTIME_STATUSES),
            "readback_receipt_exact": True,
            "duplicate_overwrite_allowed": False,
            "post_retry_count": 0,
        },
        "cleanup": {
            "worker_deleted": True,
            "d1_deleted": True,
            "attempts": {
                "DELETE_WORKER_SCRIPT": 1,
                "DELETE_D1_DATABASE": 1,
            },
            "retry_count": 0,
            "failures": [],
            "residual_resources": [],
        },
        "evidence_manifest": manifest,
        "evidence_manifest_sha256": canonical_digest(manifest),
        "secret_exposure": {
            "cloudflare_api_token_in_evidence": False,
            "worker_secret_value_in_evidence": False,
        },
        "real_cloudflare_requests": 17,
        "provider_qualified": False,
        "production_eligible": False,
        "external_dependency_resolved": False,
        "production_credit": 0,
        "cer081_credit": 0,
    }


class CloudflareEvidenceReviewTests(unittest.TestCase):
    def review(self, value=None, **overrides):
        value = value or package()
        return validate_cloudflare_real_qualification_evidence(
            value,
            expected_package_sha256=overrides.get("package_hash", canonical_digest(value)),
            expected_evidence_manifest_sha256=overrides.get(
                "manifest_hash", canonical_digest(value["evidence_manifest"])
            ),
            expected_cloudflare_authorization_qualification_sha256=overrides.get(
                "auth", AUTH
            ),
            expected_marker_execution_result_sha256=overrides.get("marker", MARKER),
            expected_current_main_sha=overrides.get("main", MAIN),
            expected_workflow_run_id=overrides.get("run_id", RUN_ID),
            expected_workflow_job_id=overrides.get("job_id", JOB_ID),
        )

    def test_exact_real_evidence_is_ready_for_control_center_only(self):
        r = self.review()
        self.assertEqual(r["validation_status"], "PASS")
        self.assertEqual(
            r["review_disposition"],
            "READY_FOR_CONTROL_CENTER_CLOUDFLARE_PROVIDER_ACCEPTANCE",
        )
        self.assertTrue(r["cleanup_closed"])
        self.assertEqual(r["residual_resource_count"], 0)
        self.assertFalse(r["provider_accepted"])
        self.assertFalse(r["provider_qualified"])

    def test_package_and_manifest_hashes_are_external_trust_roots(self):
        with self.assertRaisesRegex(CloudflareEvidenceReviewError, "PACKAGE_HASH_MISMATCH"):
            self.review(package_hash="1" * 64)
        with self.assertRaisesRegex(CloudflareEvidenceReviewError, "MANIFEST_HASH_MISMATCH"):
            self.review(manifest_hash="2" * 64)

    def test_workflow_must_be_first_attempt_without_rerun(self):
        for field, bad in (("workflow_attempt", 2), ("rerun_count", 1)):
            value = package()
            value["execution"][field] = bad
            with self.subTest(field=field), self.assertRaisesRegex(
                CloudflareEvidenceReviewError, "WORKFLOW_IDENTITY_INVALID"
            ):
                self.review(value)

    def test_request_budget_and_runtime_statuses_are_exact(self):
        value = package()
        value["execution"]["request_count"] = 18
        with self.assertRaisesRegex(CloudflareEvidenceReviewError, "REQUEST_BUDGET_INVALID"):
            self.review(value)
        value = package()
        value["runtime_probe_results"]["statuses"]["DUPLICATE_POST"] = 200
        with self.assertRaisesRegex(CloudflareEvidenceReviewError, "RUNTIME_STATUS_INVALID"):
            self.review(value)

    def test_marker_must_be_consumed_before_cloudflare(self):
        value = package()
        value["consumption_marker"]["cloudflare_requests_before_marker"] = 1
        with self.assertRaisesRegex(CloudflareEvidenceReviewError, "MARKER_STATE_INVALID"):
            self.review(value)
        value = package()
        value["consumption_marker"]["marker_creation_consumed"] = False
        with self.assertRaisesRegex(CloudflareEvidenceReviewError, "MARKER_STATE_INVALID"):
            self.review(value)

    def test_cleanup_failure_or_residual_resource_blocks(self):
        value = package()
        value["cleanup"]["worker_deleted"] = False
        with self.assertRaisesRegex(CloudflareEvidenceReviewError, "CLEANUP_NOT_CLOSED"):
            self.review(value)
        value = package()
        value["cleanup"]["residual_resources"] = ["worker"]
        with self.assertRaisesRegex(CloudflareEvidenceReviewError, "CLEANUP_NOT_CLOSED"):
            self.review(value)
        value = package()
        value["cleanup"]["retry_count"] = 1
        with self.assertRaisesRegex(CloudflareEvidenceReviewError, "CLEANUP_NOT_CLOSED"):
            self.review(value)

    def test_resource_identity_is_bound_to_authorization_hash(self):
        value = package()
        value["resources"]["worker_script_id"] = "rate-v11-qual-wrong"
        with self.assertRaisesRegex(CloudflareEvidenceReviewError, "WORKER_ID_INVALID"):
            self.review(value)
        value = package()
        value["resources"]["d1_database_name"] = "other"
        with self.assertRaisesRegex(CloudflareEvidenceReviewError, "D1_IDENTITY_INVALID"):
            self.review(value)

    def test_evidence_manifest_is_exact_and_hash_bound(self):
        value = package()
        value["evidence_manifest"].pop("SCHEMA_SHA256")
        value["evidence_manifest_sha256"] = canonical_digest(value["evidence_manifest"])
        with self.assertRaisesRegex(CloudflareEvidenceReviewError, "MANIFEST_SET_INVALID"):
            self.review(
                value,
                manifest_hash=canonical_digest(value["evidence_manifest"]),
            )

    def test_secret_values_and_premature_credit_are_forbidden(self):
        value = package()
        value["secret_exposure"]["cloudflare_api_token_in_evidence"] = True
        with self.assertRaisesRegex(CloudflareEvidenceReviewError, "SECRET_EXPOSURE_INVALID"):
            self.review(value)
        value = package()
        value["provider_qualified"] = True
        with self.assertRaisesRegex(
            CloudflareEvidenceReviewError, "PREMATURE_ACCEPTANCE_OR_CREDIT"
        ):
            self.review(value)


if __name__ == "__main__":
    unittest.main()
