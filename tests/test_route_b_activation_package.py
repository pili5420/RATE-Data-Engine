from __future__ import annotations

from unittest.mock import patch
import unittest

from src.route_b_activation_package import build_runtime_package, baseline_policy


class PackageTests(unittest.TestCase):
    def test_repository_baseline_policy_is_valid_for_current_mode(self):
        p=baseline_policy()
        self.assertIn(p["status"],{"PENDING_BINDING","ACTIVE"})
        if p["status"]=="PENDING_BINDING":
            out=build_runtime_package(".", "artifacts", source_1200_run_id="1")
            self.assertEqual(out["runtime_mode"],"NOOP_PENDING_BASELINE_BINDING")
            self.assertEqual(out["production_credit"],0)
            self.assertFalse(out["session_opened"])
        else:
            self.assertEqual(p["activation_binding_mode"],"DERIVE_FROM_GIT_HISTORY")
            self.assertEqual(len(p["activation_merge_sha"]),40)
            self.assertEqual(len(p["activation_binding_sha"]),40)
            self.assertNotEqual(p["activation_merge_sha"],p["activation_binding_sha"])
            self.assertTrue(p["production_credit_allowed"])

    @patch("src.route_b_activation_package.baseline_policy")
    @patch("src.route_b_activation_package._find_slot")
    @patch("src.route_b_activation_package.load_live_state")
    @patch("src.route_b_activation_package.validate_overlay")
    @patch("src.route_b_activation_package.build_ancestry_evidence")
    @patch("src.route_b_activation_package.build_activation_and_open_session")
    def test_active_package_composes_all_gates(self,bridge,ancestry,overlay,load,find,policy):
        policy.return_value={
            "artifact":"RATE_ROUTE_B_ACTIVATION_BASELINE_V1",
            "status":"ACTIVE","activation_merge_sha":"a"*40,
            "activation_binding_sha":"d"*40,
            "route":"B_ZERO_FEE","production_credit_allowed":True
        }
        find.return_value=("2026-11-05",{"workflow_run_id":"120","cadence":"12:00"})
        load.side_effect=[
            {"state":{"id":"1200"}},
            {"state":{"id":"0930"}},
            {"state":{"id":"0730"}},
            {"manifest":{"workflow_run_id":"93","cadence":"09:30"}}
        ]
        overlay.side_effect=[
            {"source_head_sha":"b"*40},
            {"source_head_sha":"c"*40}
        ]
        ancestry.return_value={"validation_status":"PASS"}
        bridge.return_value={
            "activation":{"final_disposition":"PRODUCTION_ACTIVATION_VERIFIED"},
            "session":{"artifact":"RATE_V11_PRODUCTION_ACCEPTANCE_SESSION_V1"},
            "trading_calendar_evidence":{"status":"PASS"}
        }
        out=build_runtime_package(".", "artifacts", source_1200_run_id="120")
        self.assertEqual(out["runtime_mode"],"ACTIVE")
        self.assertEqual(out["production_credit"],1)
        self.assertTrue(out["session_opened"])

if __name__=="__main__":
    unittest.main()
