import unittest
from src.intraday_activation_candidate_review import canonical_digest
from src.intraday_real_git_execution_authorization import EXPECTED_BUDGET
from src.intraday_final_real_git_execution_readiness import FinalRealGitReadinessError, validate_final_real_git_execution_readiness
MAIN="1"*40; BR="activation/rate-v11-intraday-test"; PLAN="2"*64; MAN="3"*64
def store(): return {"artifact":"RATE_REAL_GIT_EXECUTION_WITH_ACCEPTED_AUTHORITY_STORE_READINESS_V1","validation_status":"PASS","current_main_sha":MAIN,"target_branch":BR,"authority_store_provider_accepted":True,"authority_store_provider_qualified":True,"persist_receipt_before_first_git_mutation":True,"write_once_receipt_required":True,"receipt_retry_after_consumption_allowed":False,"receipt_consumed":False,"real_git_transaction_execution_allowed":False,"real_git_operations":0,"production_credit":0}
def auth(): return {"artifact":"RATE_INTRADAY_REAL_GIT_TRANSACTION_EXECUTION_AUTHORIZATION_QUALIFICATION_V1","validation_status":"PASS","authorization_valid":True,"base_main_sha":MAIN,"target_branch":BR,"transaction_plan_sha256":PLAN,"candidate_manifest_sha256":MAN,"operation_budget":dict(EXPECTED_BUDGET),"single_use":True,"retry_allowed":False,"draft_pull_request_required":True,"direct_main_update_allowed":False,"merge_allowed":False,"execution_performed":False,"real_git_operations":0,"production_credit":0}
def transport(): return {"artifact":"RATE_REAL_GIT_DATA_TRANSPORT_BINDING_QUALIFICATION_V1","validation_status":"PASS","token_source":"GITHUB_TOKEN","workflow_permissions":{"contents":"write"},"automatic_retry":False,"fallback":False,"real_github_requests":0}
def http(): return {"artifact":"RATE_REAL_GIT_DATA_HTTP_EXECUTOR_REHEARSAL_V1","validation_status":"PASS","base_main_sha":MAIN,"target_branch":BR,"transaction_plan_sha256":PLAN,"candidate_manifest_sha256":MAN,"blob_count":9,"tree_count":1,"commit_count":1,"ref_create_count":1,"ref_create_retries":0,"branch_readback_verified":True,"main_ref_unchanged":True,"real_github_requests":0,"real_git_operations":0,"real_branch_created":False,"production_credit":0}
class T(unittest.TestCase):
 def q(self,s=None,a=None,t=None,h=None,main=MAIN):
  s=s or store(); a=a or auth(); t=t or transport(); h=h or http()
  return validate_final_real_git_execution_readiness(s,a,t,h,expected_authority_store_readiness_sha256=canonical_digest(s),expected_real_git_authorization_sha256=canonical_digest(a),expected_transport_binding_sha256=canonical_digest(t),expected_http_rehearsal_sha256=canonical_digest(h),expected_current_main_sha=main)
 def test_pass(self):
  r=self.q(); self.assertEqual(r["readiness_disposition"],"READY_FOR_CONTROL_CENTER_EXPLICIT_REAL_GIT_EXECUTION"); self.assertFalse(r["receipt_consumed"])
 def test_main_drift(self):
  with self.assertRaisesRegex(FinalRealGitReadinessError,"STORE_MAIN_MISMATCH"): self.q(main="f"*40)
 def test_branch_drift(self):
  h=http(); h["target_branch"]="activation/rate-v11-intraday-other"
  with self.assertRaisesRegex(FinalRealGitReadinessError,"HTTP_BRANCH_MISMATCH"): self.q(h=h)
 def test_plan_manifest_drift(self):
  h=http(); h["transaction_plan_sha256"]="f"*64
  with self.assertRaisesRegex(FinalRealGitReadinessError,"PLAN_MISMATCH"): self.q(h=h)
  h=http(); h["candidate_manifest_sha256"]="e"*64
  with self.assertRaisesRegex(FinalRealGitReadinessError,"MANIFEST_MISMATCH"): self.q(h=h)
 def test_receipt_must_be_unconsumed(self):
  s=store(); s["receipt_consumed"]=True
  with self.assertRaisesRegex(FinalRealGitReadinessError,"STORE_BOUNDARY_INVALID"): self.q(s=s)
if __name__=="__main__": unittest.main()
