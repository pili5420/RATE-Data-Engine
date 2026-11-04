import unittest
from src.intraday_activation_candidate_review import canonical_digest
from src.intraday_real_draft_pr_executor import RealDraftPRExecutorError, SyntheticDraftPRTransport, execute_real_draft_pr

HEAD="activation/rate-v11-intraday-test"; RECEIPT="1"*64
def qual():
    return {"artifact":"RATE_REAL_DRAFT_ACTIVATION_PR_CREATION_AUTHORIZATION_QUALIFICATION_V1","validation_status":"PASS",
      "authorization_sha256":"2"*64,"independent_review_sha256":"3"*64,"receipt_sha256":RECEIPT,
      "head":HEAD,"base":"main","draft":True,"single_use":True,"pr_creation_consumed":False,
      "automatic_retry_allowed":False,"fallback_allowed":False,"create_draft_pr_count":1,
      "ready_for_review_allowed":False,"auto_merge_allowed":False,"merge_queue_allowed":False,"merge_allowed":False,
      "real_github_requests":0,"real_pull_request_created":False,"production_credit":0,"cer081_credit":0,
      "next_gate":"SEPARATE_REAL_DRAFT_PR_EXECUTOR"}

class Tests(unittest.TestCase):
    def test_success(self):
        q=qual(); t=SyntheticDraftPRTransport()
        r=execute_real_draft_pr(q,t,expected_authorization_qualification_sha256=canonical_digest(q))
        self.assertEqual(r["validation_status"],"PASS"); self.assertEqual(len(t.prs),1); self.assertTrue(t.prs[0]["draft"])
    def test_hash_drift(self):
        q=qual(); t=SyntheticDraftPRTransport()
        with self.assertRaisesRegex(RealDraftPRExecutorError,"HASH_MISMATCH"):
            execute_real_draft_pr(q,t,expected_authorization_qualification_sha256="f"*64)
        self.assertEqual(t.calls,[])
    def test_preexisting_draft_is_already_consumed(self):
        q=qual(); t=SyntheticDraftPRTransport()
        t.prs.append({"number":9,"head":HEAD,"base":"main","draft":True})
        with self.assertRaisesRegex(RealDraftPRExecutorError,"ALREADY_CONSUMED"):
            execute_real_draft_pr(q,t,expected_authorization_qualification_sha256=canonical_digest(q))
        self.assertEqual(sum(c["op"]=="CREATE" for c in t.calls),0)
    def test_preexisting_nondraft_conflict(self):
        q=qual(); t=SyntheticDraftPRTransport()
        t.prs.append({"number":9,"head":HEAD,"base":"main","draft":False})
        with self.assertRaisesRegex(RealDraftPRExecutorError,"EXISTING_PR_CONFLICT"):
            execute_real_draft_pr(q,t,expected_authorization_qualification_sha256=canonical_digest(q))
    def test_failure_then_replay_rejected(self):
        q=qual(); t=SyntheticDraftPRTransport(fail_create=True)
        r=execute_real_draft_pr(q,t,expected_authorization_qualification_sha256=canonical_digest(q))
        self.assertEqual(r["disposition"],"NON_RETRYABLE_AFTER_DURABLE_CONSUMPTION")
        t.fail_create=False
        with self.assertRaisesRegex(RealDraftPRExecutorError,"RECEIPT_ALREADY_ATTEMPTED"):
            execute_real_draft_pr(q,t,expected_authorization_qualification_sha256=canonical_digest(q))
    def test_real_transport_forbidden(self):
        class Sub(SyntheticDraftPRTransport): pass
        q=qual()
        with self.assertRaisesRegex(RealDraftPRExecutorError,"REAL_TRANSPORT_FORBIDDEN"):
            execute_real_draft_pr(q,Sub(),expected_authorization_qualification_sha256=canonical_digest(q))
if __name__=="__main__": unittest.main()
