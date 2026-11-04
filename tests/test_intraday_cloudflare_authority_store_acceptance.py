"""Tests for Cloudflare authority-store Control Center acceptance."""
import unittest

from src.intraday_activation_candidate_review import canonical_digest
from src.intraday_cloudflare_authority_store_acceptance import (
    CloudflareAuthorityStoreAcceptanceError,
    validate_cloudflare_authority_store_acceptance,
)

MAIN="1"*40
DECISION_ID="CC-CF-AUTHORITY-STORE-ACCEPT-2026-11-04"


def evidence():
    return {
      "artifact":"RATE_CLOUDFLARE_D1_REAL_QUALIFICATION_EVIDENCE_REVIEW_V1",
      "validation_status":"PASS",
      "review_disposition":"READY_FOR_CONTROL_CENTER_CLOUDFLARE_PROVIDER_ACCEPTANCE",
      "workflow_run_id":123,
      "workflow_job_id":456,
      "cloudflare_authorization_qualification_sha256":"2"*64,
      "marker_execution_result_sha256":"3"*64,
      "current_main_sha":MAIN,
      "d1_database_id":"11111111-1111-1111-1111-111111111111",
      "worker_script_id":"rate-v11-qual-222222222222",
      "worker_script_sha256":"4"*64,
      "schema_sha256":"5"*64,
      "request_count":17,
      "runtime_statuses":{
        "UNAUTHORIZED_GET":401,
        "MISSING_GET":404,
        "CREATE_POST":201,
        "READBACK_GET":200,
        "DUPLICATE_POST":409,
        "UNSUPPORTED_METHOD":405,
      },
      "cleanup_closed":True,
      "residual_resource_count":0,
      "provider_accepted":False,
      "provider_qualified":False,
      "production_eligible":False,
      "external_dependency_resolved":False,
      "production_credit":0,
      "cer081_credit":0,
    }


def decision(evidence_hash):
    return {
      "artifact":"RATE_CLOUDFLARE_AUTHORITY_STORE_PROVIDER_ACCEPTANCE_DECISION_V1",
      "status":"AUTHORITY_STORE_PROVIDER_ACCEPTANCE_AUTHORIZED",
      "control_center_decision_id":DECISION_ID,
      "evidence_review_sha256":evidence_hash,
      "current_main_sha":MAIN,
      "provider":"CLOUDFLARE_WORKERS_D1",
      "plan":"WORKERS_FREE",
      "accepted_role":"REAL_GIT_EXECUTION_CONSUMPTION_RECEIPT_STORE",
      "authority_store_provider_acceptance":True,
      "intraday_market_data_provider_acceptance":False,
      "real_git_transaction_execution_allowed":False,
      "production_activation_allowed":False,
      "external_intraday_dependency_resolved":False,
      "production_credit":0,
      "cer081_credit":0,
    }


class AcceptanceTests(unittest.TestCase):
    def review(self,dec=None,ev=None,**overrides):
        ev=ev or evidence()
        eh=canonical_digest(ev)
        dec=dec or decision(eh)
        return validate_cloudflare_authority_store_acceptance(
            dec,ev,
            expected_decision_sha256=overrides.get("decision_hash",canonical_digest(dec)),
            expected_evidence_review_sha256=overrides.get("evidence_hash",eh),
            expected_current_main_sha=overrides.get("main",MAIN),
            expected_control_center_decision_id=overrides.get("decision_id",DECISION_ID),
        )

    def test_exact_acceptance_is_role_specific_only(self):
        r=self.review()
        self.assertEqual(r["validation_status"],"PASS")
        self.assertTrue(r["authority_store_provider_accepted"])
        self.assertTrue(r["authority_store_provider_qualified"])
        self.assertFalse(r["intraday_market_data_provider_accepted"])
        self.assertFalse(r["real_git_transaction_execution_allowed"])
        self.assertFalse(r["external_intraday_dependency_resolved"])

    def test_external_hashes_are_trust_roots(self):
        with self.assertRaisesRegex(CloudflareAuthorityStoreAcceptanceError,"DECISION_HASH_MISMATCH"):
            self.review(decision_hash="f"*64)
        with self.assertRaisesRegex(CloudflareAuthorityStoreAcceptanceError,"EVIDENCE_HASH_MISMATCH"):
            self.review(evidence_hash="e"*64)

    def test_cleanup_or_residual_evidence_blocks_acceptance(self):
        ev=evidence(); ev["cleanup_closed"]=False
        with self.assertRaisesRegex(CloudflareAuthorityStoreAcceptanceError,"EVIDENCE_BOUNDARY_INVALID"):
            self.review(ev=ev)
        ev=evidence(); ev["residual_resource_count"]=1
        with self.assertRaisesRegex(CloudflareAuthorityStoreAcceptanceError,"EVIDENCE_BOUNDARY_INVALID"):
            self.review(ev=ev)

    def test_decision_cannot_accept_market_data_provider(self):
        ev=evidence(); eh=canonical_digest(ev); dec=decision(eh)
        dec["intraday_market_data_provider_acceptance"]=True
        with self.assertRaisesRegex(CloudflareAuthorityStoreAcceptanceError,"PROVIDER_ROLE_SCOPE_INVALID"):
            self.review(dec=dec,ev=ev)

    def test_decision_cannot_authorize_git_or_production(self):
        ev=evidence(); eh=canonical_digest(ev)
        for field in (
            "real_git_transaction_execution_allowed",
            "production_activation_allowed",
            "external_intraday_dependency_resolved",
        ):
            dec=decision(eh); dec[field]=True
            with self.subTest(field=field), self.assertRaisesRegex(
                CloudflareAuthorityStoreAcceptanceError,"FORBIDDEN_DOWNSTREAM_STATE"
            ):
                self.review(dec=dec,ev=ev)

    def test_provider_role_and_main_are_exact(self):
        ev=evidence(); eh=canonical_digest(ev); dec=decision(eh)
        dec["accepted_role"]="MARKET_DATA_PROVIDER"
        with self.assertRaisesRegex(CloudflareAuthorityStoreAcceptanceError,"ROLE_BINDING_INVALID"):
            self.review(dec=dec,ev=ev)
        with self.assertRaisesRegex(CloudflareAuthorityStoreAcceptanceError,"EVIDENCE_BOUNDARY_INVALID"):
            self.review(main="f"*40)


if __name__=="__main__": unittest.main()
