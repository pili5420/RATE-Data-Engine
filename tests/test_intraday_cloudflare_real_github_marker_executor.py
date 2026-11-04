import unittest
from src.intraday_activation_candidate_review import canonical_digest
from src.intraday_cloudflare_github_marker_adapter import SyntheticGitHubRefTransport, marker_ref
from src.intraday_cloudflare_real_github_marker_executor import MarkerExecutorError, execute_marker

MAIN="1"*40
CF_HASH="2"*64

def qual():
    return {
      "artifact":"RATE_CLOUDFLARE_REAL_GITHUB_MARKER_CREATION_AUTHORIZATION_QUALIFICATION_V1",
      "validation_status":"PASS",
      "authorization_sha256":"3"*64,
      "cloudflare_authorization_qualification_sha256":CF_HASH,
      "current_main_sha":MAIN,
      "marker_ref":marker_ref(CF_HASH),
      "marker_target_sha":MAIN,
      "single_use":True,
      "marker_creation_consumed":False,
      "automatic_retry_allowed":False,
      "fallback_allowed":False,
      "allowed_operations":["GET_MARKER_PREFLIGHT","CREATE_MARKER_REF","GET_MARKER_READBACK"],
      "create_count":1,"update_count":0,"delete_count":0,"readback_required":True,
      "execution_performed":False,
      "real_github_requests":0,"real_git_ref_created":False,"real_cloudflare_requests":0,
      "production_credit":0,"cer081_credit":0,
      "next_gate":"SEPARATE_REAL_GITHUB_MARKER_EXECUTOR",
    }

class Tests(unittest.TestCase):
    def test_success(self):
        q=qual(); t=SyntheticGitHubRefTransport()
        r=execute_marker(q,t,expected_authorization_qualification_sha256=canonical_digest(q))
        self.assertEqual(r["validation_status"],"PASS")
        self.assertEqual(r["create_attempts"],1)
        self.assertTrue(r["marker_creation_consumed"])
        self.assertEqual(r["cloudflare_requests_before_marker"],0)

    def test_hash_drift_fails_before_calls(self):
        q=qual(); t=SyntheticGitHubRefTransport()
        with self.assertRaisesRegex(MarkerExecutorError,"HASH_MISMATCH"):
            execute_marker(q,t,expected_authorization_qualification_sha256="f"*64)
        self.assertEqual(t.calls,[])

    def test_preexisting_marker_fails(self):
        q=qual(); t=SyntheticGitHubRefTransport()
        t.refs[q["marker_ref"]]=MAIN
        with self.assertRaises(Exception):
            execute_marker(q,t,expected_authorization_qualification_sha256=canonical_digest(q))
        self.assertEqual(sum(c["method"]=="POST" for c in t.calls),0)

    def test_ambiguous_create_no_retry(self):
        q=qual(); t=SyntheticGitHubRefTransport(fail_mode="AMBIGUOUS_AFTER_CREATE")
        r=execute_marker(q,t,expected_authorization_qualification_sha256=canonical_digest(q))
        self.assertEqual(r["outcome"],"AMBIGUOUS_CREATE_CONFIRMED_BY_READBACK")
        self.assertEqual(r["create_attempts"],1)
        self.assertEqual(r["create_retries"],0)

    def test_consumed_auth_rejected(self):
        q=qual(); q["marker_creation_consumed"]=True; t=SyntheticGitHubRefTransport()
        with self.assertRaisesRegex(MarkerExecutorError,"SINGLE_USE_BOUNDARY_INVALID"):
            execute_marker(q,t,expected_authorization_qualification_sha256=canonical_digest(q))
        self.assertEqual(t.calls,[])

if __name__=="__main__": unittest.main()
