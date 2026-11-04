import unittest
from src.intraday_activation_candidate_review import canonical_digest
from src.intraday_draft_pr_transport_execution_authorization import DraftPRTransportExecutionAuthorizationError, validate_draft_pr_transport_execution_authorization
HEAD="activation/rate-v11-intraday-test"; REC="1"*64
def da(): return {"artifact":"RATE_REAL_DRAFT_ACTIVATION_PR_CREATION_AUTHORIZATION_QUALIFICATION_V1","validation_status":"PASS","head":HEAD,"base":"main","receipt_sha256":REC,"single_use":True,"pr_creation_consumed":False,"automatic_retry_allowed":False,"fallback_allowed":False,"create_draft_pr_count":1,"ready_for_review_allowed":False,"auto_merge_allowed":False,"merge_queue_allowed":False,"merge_allowed":False,"real_github_requests":0,"real_pull_request_created":False}
def tb(): return {"artifact":"RATE_REAL_DRAFT_ACTIVATION_PR_TRANSPORT_BINDING_QUALIFICATION_V1","validation_status":"PASS","repository":"pili5420/RATE-Data-Engine","token_source":"GITHUB_TOKEN","workflow_permissions":{"contents":"read","pull-requests":"write"},"automatic_retry":False,"fallback":False,"real_github_requests":0,"real_pull_request_created":False}
def ea(dh,th): return {"artifact":"RATE_REAL_DRAFT_PR_TRANSPORT_EXECUTION_AUTHORIZATION_V1","status":"REAL_DRAFT_PR_TRANSPORT_EXECUTION_AUTHORIZED","draft_pr_authorization_sha256":dh,"transport_binding_sha256":th,"head":HEAD,"base":"main","receipt_sha256":REC,"single_use":True,"execution_consumed":False,"create_attempts":1,"automatic_retry_allowed":False,"fallback_allowed":False,"ready_for_review_allowed":False,"merge_allowed":False,"real_github_requests":0,"real_pull_request_created":False}
class T(unittest.TestCase):
 def q(self,a=None,d=None,t=None,**kw):
  d=d or da(); t=t or tb(); dh=canonical_digest(d); th=canonical_digest(t); a=a or ea(dh,th)
  return validate_draft_pr_transport_execution_authorization(a,d,t,expected_execution_authorization_sha256=kw.get("ah",canonical_digest(a)),expected_draft_pr_authorization_sha256=kw.get("dh",dh),expected_transport_binding_sha256=kw.get("th",th))
 def test_pass(self): self.assertEqual(self.q()["validation_status"],"PASS")
 def test_hashes(self):
  with self.assertRaisesRegex(DraftPRTransportExecutionAuthorizationError,"DRAFT_AUTH_HASH_MISMATCH"): self.q(dh="f"*64)
  with self.assertRaisesRegex(DraftPRTransportExecutionAuthorizationError,"BINDING_HASH_MISMATCH"): self.q(th="e"*64)
 def test_target_drift(self):
  d=da(); t=tb(); a=ea(canonical_digest(d),canonical_digest(t)); a["head"]="activation/rate-v11-intraday-other"
  with self.assertRaisesRegex(DraftPRTransportExecutionAuthorizationError,"TARGET_BINDING_INVALID"): self.q(a=a,d=d,t=t)
 def test_retry_forbidden(self):
  d=da(); t=tb(); a=ea(canonical_digest(d),canonical_digest(t)); a["automatic_retry_allowed"]=True
  with self.assertRaisesRegex(DraftPRTransportExecutionAuthorizationError,"SINGLE_USE_INVALID"): self.q(a=a,d=d,t=t)
if __name__=="__main__": unittest.main()
