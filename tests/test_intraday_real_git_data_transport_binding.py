import unittest
from src.intraday_real_git_data_transport_binding import (
 RealGitDataTransportBindingError, EXPECTED_REQUESTS, validate_real_git_data_transport_binding
)
def policy():
 return {"artifact":"RATE_REAL_GIT_DATA_TRANSPORT_BINDING_V1","repository":"pili5420/RATE-Data-Engine",
 "token_source":"GITHUB_TOKEN","custom_pat_secret":None,"workflow_permissions":{"contents":"write"},
 "repo_actions_contents_write_policy":"EXTERNALLY_VERIFIED_ENABLED","scheme":"https","api_host":"api.github.com",
 "tls_hostname_verification":True,"tls_certificate_verification":True,"redirect_following":False,
 "automatic_retry":False,"fallback":False,"allowed_requests":EXPECTED_REQUESTS,
 "patch_ref_allowed":False,"delete_ref_allowed":False,"merge_endpoint_allowed":False,
 "pull_request_endpoint_allowed":False,"main_ref_update_allowed":False,
 "required_headers":{"Accept":"application/vnd.github+json","X-GitHub-Api-Version":"2022-11-28",
 "Authorization":"Bearer ${GITHUB_TOKEN}"},"real_github_requests":0,"real_git_operations":0,"real_branch_created":False}
class T(unittest.TestCase):
 def test_pass(self): self.assertEqual(validate_real_git_data_transport_binding(policy())["validation_status"],"PASS")
 def test_repo_policy(self):
  p=policy(); p["repo_actions_contents_write_policy"]="UNPROVEN"
  with self.assertRaisesRegex(RealGitDataTransportBindingError,"REPO_POLICY_UNPROVEN"): validate_real_git_data_transport_binding(p)
 def test_permissions(self):
  p=policy(); p["workflow_permissions"]={"contents":"write","pull-requests":"write"}
  with self.assertRaisesRegex(RealGitDataTransportBindingError,"PERMISSIONS_NOT_MINIMAL"): validate_real_git_data_transport_binding(p)
 def test_surface(self):
  p=policy(); p["allowed_requests"]=EXPECTED_REQUESTS+[{"method":"PATCH","path":"/x"}]
  with self.assertRaisesRegex(RealGitDataTransportBindingError,"REQUEST_SURFACE_INVALID"): validate_real_git_data_transport_binding(p)
 def test_forbidden(self):
  for f in ("patch_ref_allowed","delete_ref_allowed","merge_endpoint_allowed","pull_request_endpoint_allowed","main_ref_update_allowed"):
   p=policy(); p[f]=True
   with self.subTest(f=f), self.assertRaisesRegex(RealGitDataTransportBindingError,"FORBIDDEN_ACTION"): validate_real_git_data_transport_binding(p)
if __name__=="__main__": unittest.main()
