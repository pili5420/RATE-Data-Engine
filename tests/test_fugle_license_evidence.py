from __future__ import annotations
import json
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
EVIDENCE=ROOT/"docs/contracts/RATE_FUGLE_BASIC_PERSONAL_INTERNAL_USE_LICENSE_EVIDENCE_V1.json"
ROUTE_B=ROOT/"config/RATE_ROUTE_B_ACTIVATION_BASELINE_V1.json"

class FugleLicenseEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.e=json.loads(EVIDENCE.read_text(encoding="utf-8"))
        self.route=json.loads(ROUTE_B.read_text(encoding="utf-8"))

    def test_provider_written_scope_is_explicit(self):
        self.assertEqual(self.e["provider_license_gate"],"PASS_CONFIRMED_IN_WRITING")
        scope=self.e["confirmation_scope"]
        for key in (
            "single_user_personal_use","automated_non_display_analysis",
            "internal_analysis_only",
            "approximately_30_individual_intraday_quote_requests_per_cadence_allowed",
            "technical_indicators_allowed","rankings_scores_decision_logic_allowed",
            "derived_results_retention_for_personal_use_allowed",
            "user_controlled_private_cloud_runtime_allowed",
        ):
            self.assertIs(scope[key],True,key)
        self.assertEqual(scope["current_intraday_rate_limit_requests_per_minute"],60)

    def test_public_custody_and_redistribution_remain_forbidden(self):
        custody=self.e["custody_boundaries"]
        for key in (
            "public_repository_raw_market_data_forbidden",
            "public_repository_derived_analysis_forbidden",
            "public_repository_market_data_logs_forbidden",
            "redistribution_forbidden","resale_forbidden",
        ):
            self.assertIs(custody[key],True,key)

    def test_exchange_authority_remains_separate_and_unresolved(self):
        boundary=self.e["provider_scope_boundary"]
        self.assertIs(boundary["exchange_authority_confirmed_by_provider"],False)
        self.assertEqual(
            boundary["twse_tpex_exchange_authority_gate"],
            "UNRESOLVED_REQUIRES_SEPARATE_EXCHANGE_EVIDENCE",
        )
        governance=self.e["rate_v11_governance"]
        self.assertIs(governance["exchange_authority_bypass_allowed"],False)
        self.assertIs(governance["production_activation_allowed"],False)

    def test_route_b_architecture_is_not_changed_or_activated_by_this_evidence(self):
        governance=self.e["rate_v11_governance"]
        self.assertIs(governance["route_b_source_architecture_changed"],False)
        self.assertIs(governance["route_b_source_activation_from_fugle_evidence"],False)
        self.assertEqual(governance["fugle_status"],"QUALIFIED_PROVIDER_OPTION_NOT_ACTIVE_IN_ROUTE_B")
        self.assertEqual(self.route["route"],"B_ZERO_FEE")
        self.assertEqual(self.route["status"],"ACTIVE")

if __name__=="__main__":
    unittest.main()
