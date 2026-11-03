"""Tests for synthetic semantic review of the activation acquisition CLI."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import unittest

from src.intraday_activation_candidate_acquisition_review import (
    AcquisitionSemanticReviewError,
    review_candidate_acquisition_synthetic,
)
from src.intraday_activation_candidate_review import canonical_digest
from src.intraday_activation_candidate_scaffold import build_activation_candidate_scaffold
from src.intraday_activation_delta_plan import NEW_RUNTIME_FILES
from src.intraday_activation_readiness import (
    ALLOWED_EXISTING_MUTATION_PATHS,
    repo_preimage_hashes,
)

MAIN = "1" * 40
PROVIDER = "Fugle"
ENDPOINT = "https://api.fugle.tw/marketdata/v1.0/stock/intraday/quote/{symbol}"
SECRET = "FUGLE_API_KEY"
DAY = "2026-11-04"
NOW_0930 = datetime(2026, 11, 4, 1, 35, 30, tzinfo=timezone.utc)
NOW_1200 = datetime(2026, 11, 4, 4, 5, 30, tzinfo=timezone.utc)


def plan():
    return {
        "artifact": "RATE_INTRADAY_ACTIVATION_DELTA_PLAN_V1",
        "validation_status": "PASS",
        "plan_status": "READY_FOR_SEPARATE_ACTIVATION_IMPLEMENTATION_REVIEW",
        "main_sha": MAIN,
        "control_center_activation_decision_id": "CC-ACTIVATION",
        "provider_name": PROVIDER,
        "license_basis": "OWNER_ASSUMED_AUTHORIZED",
        "provider_endpoint_template": ENDPOINT,
        "credential_boundary": {
            "store": "GITHUB_ACTIONS_SECRET",
            "secret_name": SECRET,
            "secret_value_embedded": False,
        },
        "existing_file_preimage_sha256": repo_preimage_hashes(),
        "existing_mutation_paths": list(ALLOWED_EXISTING_MUTATION_PATHS),
        "new_runtime_files": list(NEW_RUNTIME_FILES),
        "mutation_specs": {},
        "required_markets": ["TWSE", "TPEX"],
        "authorized_cadences": ["09:30", "12:00"],
        "fallback_allowed": False,
        "automatic_retry_allowed": False,
        "apply_allowed": False,
        "activation_execution_allowed": False,
        "external_dependency_resolved": False,
        "registry_activation_allowed": False,
        "network_requests": 0,
        "credential_access": 0,
        "registry_mutations": 0,
        "scheduler_mutations": 0,
        "production_state_mutations": 0,
        "production_credit": 0,
        "cer081_credit": 0,
    }


def candidates():
    delta = plan()
    return build_activation_candidate_scaffold(
        delta,
        expected_delta_plan_sha256=canonical_digest(delta),
        expected_main_sha=MAIN,
        expected_provider_name=PROVIDER,
        expected_endpoint_template=ENDPOINT,
        expected_secret_name=SECRET,
    )["candidate_files"]


class AcquisitionSemanticReviewTests(unittest.TestCase):
    def review(self, files=None, *, cadence="09:30", now_utc=NOW_0930, source_hash=None):
        value = files or candidates()
        source = value["scripts/acquire_intraday_provider_feed.py"]
        return review_candidate_acquisition_synthetic(
            value,
            expected_acquisition_sha256=source_hash or hashlib.sha256(source.encode()).hexdigest(),
            expected_provider_name=PROVIDER,
            expected_secret_name=SECRET,
            trading_date=DAY,
            cadence=cadence,
            now_utc=now_utc,
        )

    def test_0930_acquisition_passes_fixed_path_hash_and_phase2_admission(self):
        result = self.review()
        self.assertEqual(result["validation_status"], "PASS")
        self.assertEqual(result["real_provider_requests"], 0)
        self.assertEqual(result["output_path"],
                         "artifacts/production_0930/RATE_AUTHORIZED_INTRADAY_FEED.json")
        self.assertEqual(result["raw_evidence_output_path"],
                         "artifacts/production_0930/RATE_AUTHORIZED_INTRADAY_RAW_EVIDENCE.json")
        self.assertEqual(result["phase2_admission_coverage"], "30/30")
        self.assertEqual(result["market_counts"], {"TWSE": 25, "TPEX": 5})
        self.assertFalse(result["secret_persisted"])

    def test_1200_acquisition_uses_1200_fixed_paths(self):
        result = self.review(cadence="12:00", now_utc=NOW_1200)
        self.assertEqual(result["validation_status"], "PASS")
        self.assertEqual(result["output_path"],
                         "artifacts/production_1200/RATE_AUTHORIZED_INTRADAY_FEED.json")
        self.assertEqual(result["raw_evidence_output_path"],
                         "artifacts/production_1200/RATE_AUTHORIZED_INTRADAY_RAW_EVIDENCE.json")

    def test_source_hash_is_externally_bound_before_execution(self):
        with self.assertRaisesRegex(
            AcquisitionSemanticReviewError, "SOURCE_HASH_MISMATCH"
        ):
            self.review(source_hash="f" * 64)

    def test_removed_output_custody_is_caught_semantically(self):
        value = candidates()
        source = value["scripts/acquire_intraday_provider_feed.py"]
        source = source.replace(
            '    output = _bounded_output(\n'
            '        args.output, expected_output, "INTRADAY_RUNTIME_OUTPUT_PATH_FORBIDDEN"\n'
            '    )\n',
            '    output = Path(args.output)\n',
        )
        value["scripts/acquire_intraday_provider_feed.py"] = source
        with self.assertRaises(AcquisitionSemanticReviewError):
            self.review(value, source_hash=hashlib.sha256(source.encode()).hexdigest())

    def test_review_proves_zero_runtime_calls_for_preflight_failures(self):
        result = self.review()
        self.assertEqual(result["missing_key_runtime_calls"], 0)
        self.assertEqual(result["bad_path_runtime_calls"], 0)
        self.assertEqual(result["existing_output_runtime_calls"], 0)

    def test_review_never_claims_provider_acceptance_or_activation(self):
        result = self.review()
        self.assertFalse(result["provider_accepted"])
        self.assertFalse(result["activation_execution_allowed"])
        self.assertFalse(result["external_dependency_resolved"])
        self.assertFalse(result["registry_activation_allowed"])
        self.assertEqual(result["repository_writes"], 0)
        self.assertEqual(result["production_credit"], 0)
        self.assertEqual(result["cer081_credit"], 0)


if __name__ == "__main__":
    unittest.main()
