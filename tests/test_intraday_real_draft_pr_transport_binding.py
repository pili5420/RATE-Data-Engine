import unittest
from src.intraday_real_draft_pr_transport_binding import (
    DraftPRTransportBindingError,
    EXPECTED_REQUESTS,
    validate_real_draft_pr_transport_binding,
)

def policy():
    return {
      "artifact":"RATE_REAL_DRAFT_ACTIVATION_PR_TRANSPORT_BINDING_V1",
      "repository":"pili5420/RATE-Data-Engine",
      "token_source":"GITHUB_TOKEN",
      "custom_pat_secret":None,
      "workflow_permissions":{"contents":"read","pull-requests":"write"},
      "repo_actions_pr_creation_policy":"EXTERNALLY_VERIFIED_ENABLED",
      "scheme":"https","api_host":"api.github.com",
      "tls_hostname_verification":True,"tls_certificate_verification":True,
      "redirect_following":False,"automatic_retry":False,"fallback":False,
      "allowed_requests":EXPECTED_REQUESTS,
      "patch_pull_request_allowed":False,"ready_for_review_allowed":False,
      "merge_endpoint_allowed":False,"auto_merge_allowed":False,
      "merge_queue_allowed":False,"issue_comment_write_allowed":False,
      "required_headers":{
        "Accept":"application/vnd.github+json",
        "X-GitHub-Api-Version":"2022-11-28",
        "Authorization":"Bearer ${GITHUB_TOKEN}",
      },
      "auto_ci_trigger_expected":False,
      "manual_workflow_approval_may_be_required":True,
      "real_github_requests":0,"real_pull_request_created":False,"merge_performed":False,
    }

class Tests(unittest.TestCase):
    def test_exact_policy_passes(self):
        r=validate_real_draft_pr_transport_binding(policy())
        self.assertEqual(r["validation_status"],"PASS")
        self.assertEqual(r["workflow_permissions"],{"contents":"read","pull-requests":"write"})
        self.assertFalse(r["auto_ci_trigger_expected"])

    def test_repo_policy_must_be_verified(self):
        p=policy(); p["repo_actions_pr_creation_policy"]="UNPROVEN"
        with self.assertRaisesRegex(DraftPRTransportBindingError,"REPO_POLICY_UNPROVEN"):
            validate_real_draft_pr_transport_binding(p)

    def test_pat_forbidden_and_permissions_minimal(self):
        p=policy(); p["custom_pat_secret"]="GH_PAT"
        with self.assertRaisesRegex(DraftPRTransportBindingError,"PAT_FORBIDDEN"):
            validate_real_draft_pr_transport_binding(p)
        p=policy(); p["workflow_permissions"]["contents"]="write"
        with self.assertRaisesRegex(DraftPRTransportBindingError,"PERMISSIONS_NOT_MINIMAL"):
            validate_real_draft_pr_transport_binding(p)

    def test_request_surface_exact(self):
        p=policy(); p["allowed_requests"]=list(EXPECTED_REQUESTS)+[{"method":"PATCH","path":"/x"}]
        with self.assertRaisesRegex(DraftPRTransportBindingError,"REQUEST_SURFACE_INVALID"):
            validate_real_draft_pr_transport_binding(p)

    def test_ready_merge_comment_paths_forbidden(self):
        for field in (
            "patch_pull_request_allowed","ready_for_review_allowed","merge_endpoint_allowed",
            "auto_merge_allowed","merge_queue_allowed","issue_comment_write_allowed",
        ):
            p=policy(); p[field]=True
            with self.subTest(field=field), self.assertRaisesRegex(
                DraftPRTransportBindingError,"FORBIDDEN_ACTION"
            ):
                validate_real_draft_pr_transport_binding(p)

    def test_recursive_ci_assumption_is_fail_closed(self):
        p=policy(); p["auto_ci_trigger_expected"]=True
        with self.assertRaisesRegex(DraftPRTransportBindingError,"RECURSIVE_WORKFLOW_ASSUMPTION_INVALID"):
            validate_real_draft_pr_transport_binding(p)
        p=policy(); p["manual_workflow_approval_may_be_required"]=False
        with self.assertRaisesRegex(DraftPRTransportBindingError,"RECURSIVE_WORKFLOW_ASSUMPTION_INVALID"):
            validate_real_draft_pr_transport_binding(p)

if __name__=="__main__": unittest.main()
