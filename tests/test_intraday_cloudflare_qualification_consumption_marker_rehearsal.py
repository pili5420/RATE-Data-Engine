"""Tests for durable Cloudflare qualification consumption marker rehearsal."""
from __future__ import annotations

import unittest

from src.intraday_activation_candidate_review import canonical_digest
from src.intraday_cloudflare_d1_real_qualification_plan import EXPECTED_CONSUMPTION_MARKER
from src.intraday_cloudflare_qualification_consumption_marker_rehearsal import (
    MarkerRehearsalError,
    SyntheticGitRefBackend,
    marker_ref_for,
    rehearse_consumption_marker,
)

MAIN="1"*40


def qualification():
    return {
        "artifact":"RATE_CLOUDFLARE_D1_REAL_PROVIDER_QUALIFICATION_AUTHORIZATION_QUALIFICATION_V1",
        "validation_status":"PASS",
        "authorization_sha256":"2"*64,
        "plan_review_sha256":"3"*64,
        "scaffold_sha256":"4"*64,
        "node_review_sha256":"5"*64,
        "current_main_sha":MAIN,
        "control_center_decision_id":"CC-CF-D1-QUAL-2026-11-04",
        "provider":"CLOUDFLARE_WORKERS_D1",
        "plan":"WORKERS_FREE",
        "single_use":True,
        "execution_consumed":False,
        "automatic_retry_allowed":False,
        "fallback_allowed":False,
        "resource_budget":{},
        "admin_operation_budget":{},
        "runtime_probe_budget":{},
        "cleanup_operation_budget":{},
        "consumption_marker":dict(EXPECTED_CONSUMPTION_MARKER),
        "cleanup_required":True,
        "qualification_credit_requires_cleanup_success":True,
        "qualification_execution_allowed_by_validator":False,
        "qualification_execution_performed":False,
        "real_cloudflare_requests":0,
        "credentials_read":0,
        "resources_created":0,
        "provider_qualified":False,
        "production_credit":0,
        "cer081_credit":0,
        "next_gate":"SEPARATE_CLOUDFLARE_REAL_QUALIFICATION_EXECUTOR",
    }


class MarkerRehearsalTests(unittest.TestCase):
    def run_rehearsal(self,backend=None,q=None,**overrides):
        q=q or qualification()
        backend=backend or SyntheticGitRefBackend(main_sha=MAIN)
        result=rehearse_consumption_marker(
            q,backend,
            expected_authorization_qualification_sha256=overrides.get("hash",canonical_digest(q)),
            expected_current_main_sha=overrides.get("main",MAIN),
        )
        return result,backend,q

    def test_exact_marker_create_and_readback_passes(self):
        result,backend,q=self.run_rehearsal()
        self.assertEqual(result["validation_status"],"PASS")
        self.assertEqual(result["outcome"],"CREATED_AND_READBACK_VERIFIED")
        self.assertEqual(result["marker_ref"],marker_ref_for(canonical_digest(q)))
        self.assertEqual(result["marker_target_sha"],MAIN)
        self.assertEqual(result["create_attempts"],1)
        self.assertEqual(result["create_retries"],0)
        self.assertEqual(result["update_attempts"],0)
        self.assertEqual(result["delete_attempts"],0)
        self.assertEqual(result["cloudflare_requests_before_marker"],0)
        self.assertFalse(result["real_git_ref_created"])

    def test_preexisting_same_marker_blocks_without_create(self):
        q=qualification()
        h=canonical_digest(q)
        ref=marker_ref_for(h)
        backend=SyntheticGitRefBackend(main_sha=MAIN)
        backend.refs[ref]=MAIN
        with self.assertRaisesRegex(MarkerRehearsalError,"ALREADY_CONSUMED"):
            rehearse_consumption_marker(
                q,backend,
                expected_authorization_qualification_sha256=h,
                expected_current_main_sha=MAIN,
            )
        self.assertEqual(backend.create_attempts,0)

    def test_preexisting_conflicting_target_fails_closed(self):
        q=qualification()
        h=canonical_digest(q)
        ref=marker_ref_for(h)
        backend=SyntheticGitRefBackend(main_sha=MAIN)
        backend.refs[ref]="f"*40
        with self.assertRaisesRegex(MarkerRehearsalError,"EXISTING_TARGET_CONFLICT"):
            rehearse_consumption_marker(
                q,backend,
                expected_authorization_qualification_sha256=h,
                expected_current_main_sha=MAIN,
            )
        self.assertEqual(backend.create_attempts,0)

    def test_ambiguous_after_create_reads_back_without_retry(self):
        backend=SyntheticGitRefBackend(main_sha=MAIN,fail_mode="AMBIGUOUS_AFTER_CREATE")
        result,backend,_=self.run_rehearsal(backend=backend)
        self.assertEqual(result["outcome"],"AMBIGUOUS_CREATE_CONFIRMED_BY_READBACK")
        self.assertEqual(backend.create_attempts,1)
        self.assertGreaterEqual(backend.read_attempts,2)
        self.assertEqual(result["create_retries"],0)

    def test_failure_before_create_leaves_no_marker(self):
        backend=SyntheticGitRefBackend(main_sha=MAIN,fail_mode="BEFORE_CREATE")
        q=qualification()
        with self.assertRaisesRegex(RuntimeError,"FAIL_BEFORE_CREATE"):
            rehearse_consumption_marker(
                q,backend,
                expected_authorization_qualification_sha256=canonical_digest(q),
                expected_current_main_sha=MAIN,
            )
        self.assertEqual(backend.refs,{})
        self.assertEqual(backend.create_attempts,1)

    def test_hash_main_and_contract_drift_fail_before_create(self):
        q=qualification()
        for kind in ("hash","main","contract"):
            backend=SyntheticGitRefBackend(main_sha=MAIN)
            value=qualification()
            kwargs={
                "expected_authorization_qualification_sha256":canonical_digest(value),
                "expected_current_main_sha":MAIN,
            }
            if kind=="hash":
                kwargs["expected_authorization_qualification_sha256"]="f"*64
            elif kind=="main":
                kwargs["expected_current_main_sha"]="f"*40
            else:
                value["consumption_marker"]["delete_count"]=1
                kwargs["expected_authorization_qualification_sha256"]=canonical_digest(value)
            with self.subTest(kind=kind), self.assertRaises(MarkerRehearsalError):
                rehearse_consumption_marker(value,backend,**kwargs)
            self.assertEqual(backend.create_attempts,0)

    def test_real_or_subclass_backend_is_forbidden(self):
        class Subclass(SyntheticGitRefBackend):
            pass
        q=qualification()
        with self.assertRaisesRegex(MarkerRehearsalError,"REAL_BACKEND_FORBIDDEN"):
            rehearse_consumption_marker(
                q,Subclass(main_sha=MAIN),
                expected_authorization_qualification_sha256=canonical_digest(q),
                expected_current_main_sha=MAIN,
            )


if __name__=="__main__":
    unittest.main()
