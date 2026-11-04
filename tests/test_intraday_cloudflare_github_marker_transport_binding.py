import unittest
from src.intraday_cloudflare_github_marker_transport_binding import (
    GitHubMarkerTransportBindingError,
    validate_github_marker_transport_binding,
)

def policy():
    return {
      "artifact":"RATE_CLOUDFLARE_GITHUB_MARKER_TRANSPORT_BINDING_V1",
      "repository":"pili5420/RATE-Data-Engine",
      "token_source":"GITHUB_TOKEN",
      "custom_pat_secret":None,
      "workflow_permissions":{"contents":"write"},
      "api_host":"api.github.com",
      "scheme":"https",
      "tls_hostname_verification":True,
      "tls_certificate_verification":True,
      "redirect_following":False,
      "automatic_retry":False,
      "fallback":False,
      "allowed_requests":[
        {"method":"GET","path_template":"/repos/pili5420/RATE-Data-Engine/git/ref/tags/rate-v11-qualification-consumed/cloudflare-d1-{hash_prefix}"},
        {"method":"POST","path":"/repos/pili5420/RATE-Data-Engine/git/refs"},
      ],
      "patch_ref_allowed":False,
      "delete_ref_allowed":False,
      "list_refs_allowed":False,
      "main_ref_update_allowed":False,
      "required_headers":{
        "Accept":"application/vnd.github+json",
        "X-GitHub-Api-Version":"2022-11-28",
        "Authorization":"Bearer ${GITHUB_TOKEN}",
      },
      "real_github_requests":0,
      "real_git_ref_created":False,
      "real_cloudflare_requests":0,
    }

class Tests(unittest.TestCase):
    def test_exact_policy_passes(self):
        r=validate_github_marker_transport_binding(policy())
        self.assertEqual(r["validation_status"],"PASS")
        self.assertEqual(r["workflow_permissions"],{"contents":"write"})

    def test_pat_forbidden(self):
        p=policy(); p["custom_pat_secret"]="GH_PAT"
        with self.assertRaisesRegex(GitHubMarkerTransportBindingError,"PAT_FORBIDDEN"):
            validate_github_marker_transport_binding(p)

    def test_permissions_must_be_contents_write_only(self):
        p=policy(); p["workflow_permissions"]={"contents":"write","pull-requests":"write"}
        with self.assertRaisesRegex(GitHubMarkerTransportBindingError,"PERMISSIONS_NOT_MINIMAL"):
            validate_github_marker_transport_binding(p)

    def test_patch_delete_list_forbidden(self):
        for field in ("patch_ref_allowed","delete_ref_allowed","list_refs_allowed","main_ref_update_allowed"):
            p=policy(); p[field]=True
            with self.subTest(field=field), self.assertRaisesRegex(
                GitHubMarkerTransportBindingError,"FORBIDDEN_REF_ACTION"
            ):
                validate_github_marker_transport_binding(p)

    def test_tls_redirect_retry_fail_closed(self):
        for field,bad,reason in (
            ("tls_hostname_verification",False,"TLS_INVALID"),
            ("redirect_following",True,"REDIRECT_FORBIDDEN"),
            ("automatic_retry",True,"RETRY_FORBIDDEN"),
        ):
            p=policy(); p[field]=bad
            with self.subTest(field=field), self.assertRaisesRegex(
                GitHubMarkerTransportBindingError,reason
            ):
                validate_github_marker_transport_binding(p)

    def test_request_surface_exact(self):
        p=policy(); p["allowed_requests"].append({"method":"DELETE","path":"/x"})
        with self.assertRaisesRegex(GitHubMarkerTransportBindingError,"REQUEST_SURFACE_INVALID"):
            validate_github_marker_transport_binding(p)

if __name__=="__main__": unittest.main()
