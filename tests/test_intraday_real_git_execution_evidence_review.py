import unittest
from src.intraday_activation_candidate_review import canonical_digest
from src.intraday_real_git_execution_evidence_review import RealGitExecutionEvidenceReviewError, validate_real_git_execution_evidence
MAIN="1"*40; BR="activation/rate-v11-intraday-test"; PLAN="2"*64; MAN="3"*64; REC="4"*64; COMMIT="5"*40
def ev():
 return {"artifact":"RATE_REAL_GIT_TRANSACTION_EXECUTION_EVIDENCE_V1","execution_status":"PASS",
 "pre_execution_main_sha":MAIN,"post_execution_main_sha":MAIN,"main_ref_unchanged":True,
 "target_branch":BR,"transaction_plan_sha256":PLAN,"candidate_manifest_sha256":MAN,
 "receipt_sha256":REC,"receipt_state":"CONSUMED_BEFORE_GIT_MUTATION","receipt_persisted_before_first_git_mutation":True,
 "blob_count":9,"tree_count":1,"commit_count":1,"branch_ref_create_count":1,
 "branch_ref_readback_verified":True,"branch_ref_target_sha":COMMIT,"commit_sha":COMMIT,"commit_parent_sha":MAIN,
 "automatic_retry_count":0,"fallback_used":False,"merge_performed":False,
 "draft_pull_request_created":True,"draft_pull_request_draft":True,"draft_pull_request_base":"main",
 "draft_pull_request_head":BR,"production_credit":0,"cer081_credit":0}
class T(unittest.TestCase):
 def q(self,e=None,**kw):
  e=e or ev()
  return validate_real_git_execution_evidence(e,expected_evidence_sha256=kw.get("hash",canonical_digest(e)),
   expected_pre_execution_main_sha=kw.get("main",MAIN),expected_target_branch=kw.get("branch",BR),
   expected_transaction_plan_sha256=PLAN,expected_candidate_manifest_sha256=MAN,expected_receipt_sha256=REC)
 def test_pass(self): self.assertEqual(self.q()["validation_status"],"PASS")
 def test_main_mutation_fails(self):
  e=ev(); e["post_execution_main_sha"]="f"*40
  with self.assertRaisesRegex(RealGitExecutionEvidenceReviewError,"MAIN_MUTATED"): self.q(e)
 def test_branch_readback_fails(self):
  e=ev(); e["branch_ref_target_sha"]="f"*40
  with self.assertRaisesRegex(RealGitExecutionEvidenceReviewError,"BRANCH_READBACK_INVALID"): self.q(e)
 def test_retry_or_merge_fails(self):
  for k,v in (("automatic_retry_count",1),("fallback_used",True),("merge_performed",True)):
   e=ev(); e[k]=v
   with self.subTest(k=k), self.assertRaisesRegex(RealGitExecutionEvidenceReviewError,"RETRY_OR_MERGE_INVALID"): self.q(e)
 def test_receipt_binding_fails(self):
  e=ev(); e["receipt_state"]="UNCONSUMED"
  with self.assertRaisesRegex(RealGitExecutionEvidenceReviewError,"RECEIPT_BINDING_INVALID"): self.q(e)
if __name__=="__main__": unittest.main()
