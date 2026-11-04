import unittest
from src.intraday_activation_candidate_review import canonical_digest
from src.intraday_activation_apply_authorization import EXPECTED_PATHS
from src.intraday_activation_draft_pr_independent_acceptance import ActivationDraftPRAcceptanceError, validate_activation_draft_pr_acceptance

MAIN="1"*40; BR="activation/rate-v11-intraday-test"; COMMIT="2"*40
def review():
 return {"artifact":"RATE_REAL_GIT_TRANSACTION_EXECUTION_REVIEW_V1","validation_status":"PASS",
 "review_disposition":"READY_FOR_ACTIVATION_DRAFT_PR_INDEPENDENT_REVIEW","pre_execution_main_sha":MAIN,
 "activation_commit_sha":COMMIT,"target_branch":BR,"receipt_sha256":"3"*64,
 "main_ref_unchanged":True,"merge_performed":False,"production_credit":0,"cer081_credit":0}
def pr():
 return {"artifact":"RATE_REAL_ACTIVATION_DRAFT_PR_EVIDENCE_V1","status":"OPEN","pull_request_number":999,
 "head_branch":BR,"base_branch":"main","head_sha":COMMIT,"draft":True,"ready_for_review":False,
 "merged":False,"auto_merge_enabled":False,"merge_queue_enabled":False,
 "changed_files":list(EXPECTED_PATHS),"changed_file_count":len(EXPECTED_PATHS),"unexpected_files":[],
 "ci":{"exact_head_sha":COMMIT,"required_checks_total":3,"required_checks_success":3,
       "required_checks_failure":0,"required_checks_pending":0},
 "main_sha_at_review":MAIN,"merge_performed":False,"production_credit":0,"cer081_credit":0}
class T(unittest.TestCase):
 def q(self,r=None,p=None,**kw):
  r=r or review(); p=p or pr()
  return validate_activation_draft_pr_acceptance(r,p,
    expected_execution_review_sha256=kw.get("rh",canonical_digest(r)),
    expected_draft_pr_evidence_sha256=kw.get("ph",canonical_digest(p)),
    expected_target_branch=kw.get("branch",BR),
    expected_activation_commit_sha=kw.get("commit",COMMIT))
 def test_pass(self): self.assertEqual(self.q()["review_disposition"],"READY_FOR_CONTROL_CENTER_ACTIVATION_MERGE_AUTHORIZATION")
 def test_hash_drift(self):
  with self.assertRaisesRegex(ActivationDraftPRAcceptanceError,"REVIEW_HASH_MISMATCH"): self.q(rh="f"*64)
  with self.assertRaisesRegex(ActivationDraftPRAcceptanceError,"EVIDENCE_HASH_MISMATCH"): self.q(ph="e"*64)
 def test_draft_boundary(self):
  p=pr(); p["ready_for_review"]=True
  with self.assertRaisesRegex(ActivationDraftPRAcceptanceError,"DRAFT_BOUNDARY_INVALID"): self.q(p=p)
 def test_file_scope(self):
  p=pr(); p["changed_files"]=p["changed_files"][:-1]; p["changed_file_count"]-=1
  with self.assertRaisesRegex(ActivationDraftPRAcceptanceError,"FILE_SET_INVALID"): self.q(p=p)
 def test_ci_green_required(self):
  p=pr(); p["ci"]["required_checks_failure"]=1; p["ci"]["required_checks_success"]=2
  with self.assertRaisesRegex(ActivationDraftPRAcceptanceError,"CI_NOT_GREEN"): self.q(p=p)
 def test_main_base_drift(self):
  p=pr(); p["main_sha_at_review"]="f"*40
  with self.assertRaisesRegex(ActivationDraftPRAcceptanceError,"MAIN_BASE_DRIFT"): self.q(p=p)
if __name__=="__main__": unittest.main()
