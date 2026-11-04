import unittest
from src.intraday_activation_candidate_review import canonical_digest
from src.intraday_draft_activation_pr_rehearsal import SyntheticDraftPRBackend, rehearse_draft_activation_pr

def orchestration():
    return {
      "artifact":"RATE_DURABLE_RECEIPT_THEN_GIT_ORCHESTRATION_REHEARSAL_V1","validation_status":"PASS",
      "execution_id":"E1","current_main_sha":"1"*40,"target_branch":"activation/rate-v11-intraday-test",
      "receipt_sha256":"2"*64,"receipt_state":"CONSUMED_BEFORE_GIT_MUTATION",
      "receipt_persisted_before_git":True,"git_mutations_before_receipt":0,
      "synthetic_blob_count":9,"synthetic_tree_sha":"3"*40,"synthetic_commit_sha":"4"*40,
      "synthetic_branch_created":True,"synthetic_branch_ref_created_last":True,
      "real_git_operations":0,"real_repository_writes":0,"real_branch_created":False,
      "real_pull_request_created":False,"merge_performed":False,"live_provider_requests":0,
      "production_credit":0,"cer081_credit":0
    }

class Tests(unittest.TestCase):
    def test_success(self):
        o=orchestration(); b=SyntheticDraftPRBackend()
        r=rehearse_draft_activation_pr(o,b,expected_orchestration_sha256=canonical_digest(o))
        self.assertEqual(r["validation_status"],"PASS"); self.assertTrue(r["draft"]); self.assertFalse(r["merge_allowed"])
        self.assertEqual(len(b.prs),1)
    def test_hash_drift(self):
        o=orchestration(); b=SyntheticDraftPRBackend()
        with self.assertRaisesRegex(Exception,"HASH_MISMATCH"):
            rehearse_draft_activation_pr(o,b,expected_orchestration_sha256="f"*64)
        self.assertEqual(b.calls,[])
    def test_failure_is_nonretryable(self):
        o=orchestration(); b=SyntheticDraftPRBackend(fail_create=True)
        r=rehearse_draft_activation_pr(o,b,expected_orchestration_sha256=canonical_digest(o))
        self.assertEqual(r["disposition"],"NON_RETRYABLE_AFTER_DURABLE_CONSUMPTION")
        b.fail_create=False
        with self.assertRaisesRegex(Exception,"ALREADY_ATTEMPTED"):
            rehearse_draft_activation_pr(o,b,expected_orchestration_sha256=canonical_digest(o))
    def test_real_backend_forbidden(self):
        class Sub(SyntheticDraftPRBackend): pass
        o=orchestration()
        with self.assertRaisesRegex(Exception,"REAL_BACKEND_FORBIDDEN"):
            rehearse_draft_activation_pr(o,Sub(),expected_orchestration_sha256=canonical_digest(o))
if __name__=="__main__": unittest.main()
