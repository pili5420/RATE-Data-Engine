"""Tests for the synthetic GitHub marker adapter."""
import unittest

from src.intraday_cloudflare_github_marker_adapter import (
    GitHubMarkerAdapterError,
    SyntheticGitHubRefTransport,
    marker_ref,
    qualify_marker_adapter,
)

AUTH = "a" * 64
MAIN = "b" * 40


class GitHubMarkerAdapterTests(unittest.TestCase):
    def test_create_and_readback(self):
        t = SyntheticGitHubRefTransport()
        r = qualify_marker_adapter(t, authorization_sha256=AUTH, current_main_sha=MAIN)
        self.assertEqual(r["outcome"], "CREATED_AND_READBACK_VERIFIED")
        self.assertEqual(r["create_attempts"], 1)
        self.assertEqual(r["create_retries"], 0)
        self.assertEqual(t.refs[marker_ref(AUTH)], MAIN)

    def test_preexisting_same_marker_is_already_consumed(self):
        t = SyntheticGitHubRefTransport()
        t.refs[marker_ref(AUTH)] = MAIN
        with self.assertRaisesRegex(GitHubMarkerAdapterError, "ALREADY_CONSUMED"):
            qualify_marker_adapter(t, authorization_sha256=AUTH, current_main_sha=MAIN)
        self.assertEqual(sum(c["method"] == "POST" for c in t.calls), 0)

    def test_preexisting_conflicting_marker_fails(self):
        t = SyntheticGitHubRefTransport()
        t.refs[marker_ref(AUTH)] = "c" * 40
        with self.assertRaisesRegex(GitHubMarkerAdapterError, "EXISTING_TARGET_CONFLICT"):
            qualify_marker_adapter(t, authorization_sha256=AUTH, current_main_sha=MAIN)

    def test_ambiguous_after_create_reads_back_without_retry(self):
        t = SyntheticGitHubRefTransport(fail_mode="AMBIGUOUS_AFTER_CREATE")
        r = qualify_marker_adapter(t, authorization_sha256=AUTH, current_main_sha=MAIN)
        self.assertEqual(r["outcome"], "AMBIGUOUS_CREATE_CONFIRMED_BY_READBACK")
        self.assertEqual(r["create_attempts"], 1)
        self.assertEqual(r["create_retries"], 0)

    def test_failure_before_create_leaves_no_marker(self):
        t = SyntheticGitHubRefTransport(fail_mode="BEFORE_CREATE")
        with self.assertRaisesRegex(RuntimeError, "FAIL_BEFORE_CREATE"):
            qualify_marker_adapter(t, authorization_sha256=AUTH, current_main_sha=MAIN)
        self.assertEqual(t.refs, {})

    def test_request_surface_is_exact(self):
        t = SyntheticGitHubRefTransport()
        with self.assertRaisesRegex(GitHubMarkerAdapterError, "REQUEST_SHAPE_FORBIDDEN"):
            t.request("PATCH", "/repos/pili5420/RATE-Data-Engine/git/refs/heads/main", token="synthetic-token")

    def test_invalid_hashes_fail_before_requests(self):
        t = SyntheticGitHubRefTransport()
        with self.assertRaisesRegex(GitHubMarkerAdapterError, "AUTH_HASH_INVALID"):
            qualify_marker_adapter(t, authorization_sha256="bad", current_main_sha=MAIN)
        self.assertEqual(t.calls, [])


if __name__ == "__main__":
    unittest.main()
