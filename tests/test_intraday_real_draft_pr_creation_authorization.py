import unittest
from src.intraday_activation_candidate_review import canonical_digest
from src.intraday_real_draft_pr_creation_authorization import RealDraftPRAuthorizationError, validate_real_draft_pr_creation_authorization

HEAD="activation/rate-v11-intraday-test"; RECEIPT="1"*64
def review():
    return {"artifact":"RATE_INDEPENDENT_ACTIVATION_DRAFT_PR_REVIEW_V1","validation_status":"PASS",
    "review_disposition":"READY_FOR_CONTROL_CENTER_REAL_DRAFT_PR_AUTHORIZATION","rehearsal_sha256":"2"*64,
    "head":HEAD,"base":"main","draft":True,"draft_pr_create_attempts":1,"real_pull_request_created":False,
    "merge_allowed":False,"production_credit":0,"cer081_credit":0}
def auth(rh):
    return {"artifact":"RATE_REAL_DRAFT_ACTIVATION_PR_CREATION_AUTHORIZATION_V1","status":"REAL_DRAFT_PR_CREATION_AUTHORIZED",
    "independent_review_sha256":rh,"receipt_sha256":RECEIPT,"head":HEAD,"base":"main","draft":True,
    "single_use":True,"pr_creation_consumed":False,"automatic_retry_allowed":False,"fallback_allowed":False,
    "create_draft_pr_count":1,"ready_for_review_allowed":False,"auto_merge_allowed":False,"merge_queue_allowed":False,
    "merge_allowed":False,"real_github_requests":0,"real_pull_request_created":False,"production_credit":0,"cer081_credit":0}
class Tests(unittest.TestCase):
    def qualify(self,a=None,r=None,**kw):
        r=r or review(); rh=canonical_digest(r); a=a or auth(rh)
        return validate_real_draft_pr_creation_authorization(a,r,
          expected_authorization_sha256=kw.get("ah",canonical_digest(a)),
          expected_review_sha256=kw.get("rh",rh),
          expected_head_branch=kw.get("head",HEAD),
          expected_receipt_sha256=kw.get("receipt",RECEIPT))
    def test_exact_pass(self):
        out=self.qualify(); self.assertEqual(out["validation_status"],"PASS"); self.assertFalse(out["pr_creation_consumed"])
    def test_hash_roots(self):
        with self.assertRaisesRegex(RealDraftPRAuthorizationError,"AUTH_HASH_MISMATCH"): self.qualify(ah="f"*64)
        with self.assertRaisesRegex(RealDraftPRAuthorizationError,"REVIEW_HASH_MISMATCH"): self.qualify(rh="e"*64)
    def test_branch_receipt_bindings(self):
        with self.assertRaisesRegex(RealDraftPRAuthorizationError,"REVIEW_BINDING_INVALID"): self.qualify(head="activation/rate-v11-intraday-other")
        a=auth(canonical_digest(review())); a["receipt_sha256"]="f"*64
        with self.assertRaisesRegex(RealDraftPRAuthorizationError,"RECEIPT_BINDING_MISMATCH"): self.qualify(a=a)
    def test_retry_merge_forbidden(self):
        r=review(); rh=canonical_digest(r)
        for field in ("automatic_retry_allowed","ready_for_review_allowed","auto_merge_allowed","merge_queue_allowed","merge_allowed"):
            a=auth(rh); a[field]=True
            with self.subTest(field=field), self.assertRaises(RealDraftPRAuthorizationError): self.qualify(a=a,r=r)
if __name__=="__main__": unittest.main()
