import unittest
from src.intraday_activation_candidate_review import canonical_digest
from src.intraday_independent_draft_pr_review import DraftPRIndependentReviewError, validate_draft_pr_rehearsal_review

HEAD="activation/rate-v11-intraday-test"
def result():
    return {
      "artifact":"RATE_DRAFT_ACTIVATION_PR_EXECUTOR_REHEARSAL_V1","validation_status":"PASS",
      "receipt_sha256":"1"*64,"head":HEAD,"base":"main","draft":True,
      "draft_pr_create_attempts":1,"ready_for_review":False,"auto_merge_allowed":False,
      "merge_queue_allowed":False,"merge_allowed":False,"real_pull_request_created":False,
      "production_credit":0,"cer081_credit":0,"next_gate":"INDEPENDENT_ACTIVATION_DRAFT_PR_REVIEW"
    }

class Tests(unittest.TestCase):
    def test_exact_pass(self):
        r=result(); out=validate_draft_pr_rehearsal_review(r,expected_rehearsal_sha256=canonical_digest(r),expected_head_branch=HEAD)
        self.assertEqual(out["review_disposition"],"READY_FOR_CONTROL_CENTER_REAL_DRAFT_PR_AUTHORIZATION")
    def test_hash_drift(self):
        r=result()
        with self.assertRaisesRegex(DraftPRIndependentReviewError,"HASH_MISMATCH"):
            validate_draft_pr_rehearsal_review(r,expected_rehearsal_sha256="f"*64,expected_head_branch=HEAD)
    def test_branch_drift(self):
        r=result()
        with self.assertRaisesRegex(DraftPRIndependentReviewError,"BRANCH_BINDING_INVALID"):
            validate_draft_pr_rehearsal_review(r,expected_rehearsal_sha256=canonical_digest(r),expected_head_branch="activation/rate-v11-intraday-other")
    def test_merge_flags_fail_closed(self):
        for field in ("ready_for_review","auto_merge_allowed","merge_queue_allowed","merge_allowed"):
            r=result(); r[field]=True
            with self.subTest(field=field), self.assertRaisesRegex(DraftPRIndependentReviewError,"MERGE_BOUNDARY_INVALID"):
                validate_draft_pr_rehearsal_review(r,expected_rehearsal_sha256=canonical_digest(r),expected_head_branch=HEAD)
    def test_real_pr_claim_fails(self):
        r=result(); r["real_pull_request_created"]=True
        with self.assertRaisesRegex(DraftPRIndependentReviewError,"PREMATURE_REAL_STATE"):
            validate_draft_pr_rehearsal_review(r,expected_rehearsal_sha256=canonical_digest(r),expected_head_branch=HEAD)

if __name__=="__main__": unittest.main()
