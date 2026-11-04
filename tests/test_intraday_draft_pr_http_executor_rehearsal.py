import unittest
from src.intraday_activation_candidate_review import canonical_digest
from src.intraday_draft_pr_http_executor_rehearsal import (
    DraftPRHTTPRehearsalError, SyntheticGitHubPRHTTP,
    rehearse_draft_pr_http_execution,
)

HEAD="activation/rate-v11-intraday-test"; REC="1"*64
def auth():
    return {
      "artifact":"RATE_REAL_DRAFT_PR_TRANSPORT_EXECUTION_AUTHORIZATION_QUALIFICATION_V1",
      "validation_status":"PASS","head":HEAD,"base":"main","receipt_sha256":REC,
      "single_use":True,"execution_consumed":False,"create_attempts":1,
      "automatic_retry_allowed":False,"fallback_allowed":False,
      "real_github_requests":0,"real_pull_request_created":False,
    }

class Tests(unittest.TestCase):
    def test_success(self):
        a=auth(); t=SyntheticGitHubPRHTTP()
        h=canonical_digest(a)
        r=rehearse_draft_pr_http_execution(a,t,expected_execution_authorization_sha256=h)
        self.assertEqual(r["outcome"],"CREATED")
        self.assertEqual(r["post_attempts"],1); self.assertEqual(r["post_retries"],0)
        self.assertIn("RATE-Activation-Receipt-SHA256: "+REC,t.prs[0]["body"])

    def test_preexisting_same_is_consumed(self):
        a=auth(); h=canonical_digest(a); t=SyntheticGitHubPRHTTP()
        t.prs.append({"number":1,"state":"open","head":HEAD,"base":"main","draft":True,
          "body":"RATE-Activation-Receipt-SHA256: "+REC+"\nRATE-Draft-PR-Execution-Authorization-SHA256: "+h})
        with self.assertRaisesRegex(DraftPRHTTPRehearsalError,"ALREADY_CONSUMED"):
            rehearse_draft_pr_http_execution(a,t,expected_execution_authorization_sha256=h)
        self.assertEqual(sum(c["method"]=="POST" for c in t.calls),0)

    def test_preexisting_conflict(self):
        a=auth(); h=canonical_digest(a); t=SyntheticGitHubPRHTTP()
        t.prs.append({"number":1,"state":"open","head":HEAD,"base":"main","draft":True,"body":"other"})
        with self.assertRaisesRegex(DraftPRHTTPRehearsalError,"EXISTING_PR_CONFLICT"):
            rehearse_draft_pr_http_execution(a,t,expected_execution_authorization_sha256=h)

    def test_ambiguous_after_create_reads_back_no_retry(self):
        a=auth(); h=canonical_digest(a); t=SyntheticGitHubPRHTTP(fail_mode="AMBIGUOUS_AFTER_CREATE")
        r=rehearse_draft_pr_http_execution(a,t,expected_execution_authorization_sha256=h)
        self.assertEqual(r["outcome"],"AMBIGUOUS_CREATE_CONFIRMED_BY_READBACK")
        self.assertEqual(r["post_attempts"],1); self.assertEqual(r["post_retries"],0)

    def test_failure_before_create_has_no_pr(self):
        a=auth(); h=canonical_digest(a); t=SyntheticGitHubPRHTTP(fail_mode="BEFORE_CREATE")
        with self.assertRaisesRegex(RuntimeError,"FAIL_BEFORE_CREATE"):
            rehearse_draft_pr_http_execution(a,t,expected_execution_authorization_sha256=h)
        self.assertEqual(t.prs,[])

    def test_hash_drift_before_calls(self):
        a=auth(); t=SyntheticGitHubPRHTTP()
        with self.assertRaisesRegex(DraftPRHTTPRehearsalError,"AUTH_HASH_MISMATCH"):
            rehearse_draft_pr_http_execution(a,t,expected_execution_authorization_sha256="f"*64)
        self.assertEqual(t.calls,[])

if __name__=="__main__": unittest.main()
