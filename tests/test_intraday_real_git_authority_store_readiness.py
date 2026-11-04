import unittest
from src.intraday_activation_candidate_review import canonical_digest
from src.intraday_real_git_execution_authorization import EXPECTED_BUDGET
from src.intraday_real_git_authority_store_readiness import (
    RealGitAuthorityStoreReadinessError,
    validate_real_git_authority_store_readiness,
)

MAIN="1"*40
BRANCH="activation/rate-v11-intraday-cc-test"
INTRADAY_PROVIDER="Fugle"

def store_acceptance():
    return {
      "artifact":"RATE_CLOUDFLARE_AUTHORITY_STORE_PROVIDER_ACCEPTANCE_V1",
      "validation_status":"PASS",
      "control_center_decision_id":"CC-CF-STORE",
      "decision_sha256":"2"*64,
      "evidence_review_sha256":"3"*64,
      "current_main_sha":MAIN,
      "provider":"CLOUDFLARE_WORKERS_D1",
      "plan":"WORKERS_FREE",
      "accepted_role":"REAL_GIT_EXECUTION_CONSUMPTION_RECEIPT_STORE",
      "authority_store_provider_accepted":True,
      "authority_store_provider_qualified":True,
      "intraday_market_data_provider_accepted":False,
      "real_git_transaction_execution_allowed":False,
      "production_activation_allowed":False,
      "external_intraday_dependency_resolved":False,
      "production_credit":0,
      "cer081_credit":0,
      "next_gate":"REAL_GIT_EXECUTION_WITH_ACCEPTED_AUTHORITY_STORE_READINESS",
    }

def git_auth():
    return {
      "artifact":"RATE_INTRADAY_REAL_GIT_TRANSACTION_EXECUTION_AUTHORIZATION_QUALIFICATION_V1",
      "validation_status":"PASS",
      "control_center_decision_id":"CC-GIT",
      "authorization_sha256":"4"*64,
      "transaction_plan_sha256":"5"*64,
      "rehearsal_sha256":"6"*64,
      "base_main_sha":MAIN,
      "candidate_manifest_sha256":"7"*64,
      "target_branch":BRANCH,
      "target_base":"main",
      "provider_name":INTRADAY_PROVIDER,
      "operation_budget":dict(EXPECTED_BUDGET),
      "single_use":True,
      "retry_allowed":False,
      "draft_pull_request_required":True,
      "direct_main_update_allowed":False,
      "merge_allowed":False,
      "authorization_valid":True,
      "execution_performed":False,
      "real_git_operations":0,
      "live_provider_requests":0,
      "external_dependency_resolved":False,
      "registry_activation_allowed":False,
      "production_credit":0,
      "cer081_credit":0,
      "next_gate":"SEPARATE_REAL_GIT_TRANSACTION_EXECUTOR",
    }

class Tests(unittest.TestCase):
    def review(self,store=None,auth=None,**overrides):
        store=store or store_acceptance()
        auth=auth or git_auth()
        return validate_real_git_authority_store_readiness(
            store,auth,
            expected_authority_store_acceptance_sha256=overrides.get("store_hash",canonical_digest(store)),
            expected_real_git_authorization_sha256=overrides.get("git_hash",canonical_digest(auth)),
            expected_current_main_sha=overrides.get("main",MAIN),
            expected_target_branch=overrides.get("branch",BRANCH),
            expected_intraday_provider_name=overrides.get("provider",INTRADAY_PROVIDER),
        )

    def test_exact_chain_is_readiness_only(self):
        r=self.review()
        self.assertEqual(r["validation_status"],"PASS")
        self.assertTrue(r["authority_store_provider_accepted"])
        self.assertTrue(r["persist_receipt_before_first_git_mutation"])
        self.assertFalse(r["receipt_consumed"])
        self.assertFalse(r["real_git_transaction_execution_allowed"])
        self.assertEqual(r["real_git_operations"],0)

    def test_external_hashes_are_trust_roots(self):
        with self.assertRaisesRegex(RealGitAuthorityStoreReadinessError,"ACCEPTANCE_HASH_MISMATCH"):
            self.review(store_hash="f"*64)
        with self.assertRaisesRegex(RealGitAuthorityStoreReadinessError,"GIT_AUTH_HASH_MISMATCH"):
            self.review(git_hash="e"*64)

    def test_unqualified_or_wrong_role_store_blocks(self):
        store=store_acceptance(); store["authority_store_provider_qualified"]=False
        with self.assertRaisesRegex(RealGitAuthorityStoreReadinessError,"STORE_ROLE_INVALID"):
            self.review(store=store)
        store=store_acceptance(); store["accepted_role"]="MARKET_DATA_PROVIDER"
        with self.assertRaisesRegex(RealGitAuthorityStoreReadinessError,"STORE_ROLE_INVALID"):
            self.review(store=store)

    def test_git_target_main_and_provider_are_exact(self):
        with self.assertRaisesRegex(RealGitAuthorityStoreReadinessError,"GIT_TARGET_BINDING_INVALID"):
            self.review(main="f"*40)
        with self.assertRaisesRegex(RealGitAuthorityStoreReadinessError,"GIT_TARGET_BINDING_INVALID"):
            self.review(branch=BRANCH+"-other")
        with self.assertRaisesRegex(RealGitAuthorityStoreReadinessError,"INTRADAY_PROVIDER_BINDING_INVALID"):
            self.review(provider="Other")

    def test_operation_budget_and_single_use_boundary_are_exact(self):
        auth=git_auth(); auth["operation_budget"]["create_blob_count"]=10
        with self.assertRaisesRegex(RealGitAuthorityStoreReadinessError,"GIT_OPERATION_BOUNDARY_INVALID"):
            self.review(auth=auth)
        auth=git_auth(); auth["retry_allowed"]=True
        with self.assertRaisesRegex(RealGitAuthorityStoreReadinessError,"GIT_OPERATION_BOUNDARY_INVALID"):
            self.review(auth=auth)

    def test_premature_git_or_market_state_blocks(self):
        auth=git_auth(); auth["execution_performed"]=True
        with self.assertRaisesRegex(RealGitAuthorityStoreReadinessError,"GIT_PREMATURE_STATE"):
            self.review(auth=auth)
        store=store_acceptance(); store["real_git_transaction_execution_allowed"]=True
        with self.assertRaisesRegex(RealGitAuthorityStoreReadinessError,"ACCEPTANCE_SCOPE_DRIFT"):
            self.review(store=store)
        store=store_acceptance(); store["intraday_market_data_provider_accepted"]=True
        with self.assertRaisesRegex(RealGitAuthorityStoreReadinessError,"ACCEPTANCE_SCOPE_DRIFT"):
            self.review(store=store)

if __name__=="__main__": unittest.main()
