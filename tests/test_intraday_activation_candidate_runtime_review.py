"""Tests for synthetic semantic review of the activation runtime scaffold."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import unittest

from src.intraday_activation_candidate_review import canonical_digest
from src.intraday_activation_candidate_runtime_review import (
    ActivationCandidateRuntimeReviewError,
    review_candidate_runtime_synthetic,
)
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
CADENCE = "09:30"
NOW = datetime(2026, 11, 4, 1, 35, 30, tzinfo=timezone.utc)


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


class ActivationCandidateRuntimeSemanticReviewTests(unittest.TestCase):
    def review(self, files=None, runtime_hash=None):
        value = files or candidates()
        source = value["src/intraday_provider_runtime.py"]
        return review_candidate_runtime_synthetic(
            value,
            expected_runtime_sha256=runtime_hash or hashlib.sha256(source.encode()).hexdigest(),
            expected_provider_name=PROVIDER,
            expected_secret_name=SECRET,
            trading_date=DAY,
            cadence=CADENCE,
            now_utc=NOW,
        )

    def test_scaffold_runtime_passes_fake_https_and_authoritative_qualification(self):
        result = self.review()
        self.assertEqual(result["validation_status"], "PASS")
        self.assertEqual(result["transport"], "SYNTHETIC_FAKE_HTTPS_ONLY")
        self.assertEqual(result["real_network_requests"], 0)
        self.assertEqual(result["synthetic_success_requests"], 30)
        self.assertEqual(result["coverage"], "30/30")
        self.assertEqual(result["market_counts"], {"TWSE": 25, "TPEX": 5})
        self.assertEqual(result["automatic_retries"], 0)
        self.assertFalse(result["fallback_used"])
        self.assertEqual(result["connections_closed"], 30)

    def test_http_302_403_429_fail_after_one_request_no_retry(self):
        result = self.review()
        for status in ("302", "403", "429"):
            self.assertEqual(result["http_fail_closed"][status]["requests"], 1)
            self.assertEqual(result["http_fail_closed"][status]["retries"], 0)
            self.assertTrue(result["http_fail_closed"][status]["connection_closed"])

    def test_empty_key_and_count_mismatch_are_zero_request_failures(self):
        result = self.review()
        self.assertEqual(result["empty_key_requests"], 0)
        self.assertEqual(result["count_mismatch_requests"], 0)

    def test_malformed_json_is_one_request_fail_closed(self):
        result = self.review()
        self.assertEqual(result["malformed_json_requests"], 1)

    def test_runtime_hash_is_externally_bound_before_execution(self):
        with self.assertRaisesRegex(
            ActivationCandidateRuntimeReviewError, "RUNTIME_HASH_MISMATCH"
        ):
            self.review(runtime_hash="f" * 64)

    def test_disallowed_runtime_import_is_rejected_before_execution(self):
        value = candidates()
        value["src/intraday_provider_runtime.py"] = (
            "import os\n" + value["src/intraday_provider_runtime.py"]
        )
        source = value["src/intraday_provider_runtime.py"]
        with self.assertRaisesRegex(
            ActivationCandidateRuntimeReviewError, "IMPORT_FORBIDDEN"
        ):
            self.review(value, hashlib.sha256(source.encode()).hexdigest())

    def test_removed_empty_key_preflight_is_caught_semantically(self):
        value = candidates()
        value["src/intraday_provider_runtime.py"] = value[
            "src/intraday_provider_runtime.py"
        ].replace(
            '    if not isinstance(api_key, str) or not api_key:\n'
            '        raise RuntimeError("INTRADAY_RUNTIME_API_KEY_MISSING")\n',
            "",
        )
        source = value["src/intraday_provider_runtime.py"]
        with self.assertRaisesRegex(
            ActivationCandidateRuntimeReviewError, "EMPTY_KEY_FAIL_CLOSED_MISSING"
        ):
            self.review(value, hashlib.sha256(source.encode()).hexdigest())

    def test_review_never_claims_acceptance_activation_or_credit(self):
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
