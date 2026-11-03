"""Tests for one exact full synthetic intraday activation candidate chain."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import unittest

from src.intraday_activation_candidate_materialization import (
    candidate_manifest_sha256,
)
from src.intraday_activation_candidate_review import canonical_digest
from src.intraday_activation_candidate_scaffold import (
    build_activation_candidate_scaffold,
)
from src.intraday_activation_delta_plan import NEW_RUNTIME_FILES
from src.intraday_activation_readiness import (
    ALLOWED_EXISTING_MUTATION_PATHS,
    repo_preimage_hashes,
)
from src.intraday_full_synthetic_activation_review import (
    FullSyntheticActivationReviewError,
    review_full_synthetic_activation_candidate,
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


def expected_hashes():
    delta = plan()
    scaffold = build_activation_candidate_scaffold(
        delta,
        expected_delta_plan_sha256=canonical_digest(delta),
        expected_main_sha=MAIN,
        expected_provider_name=PROVIDER,
        expected_endpoint_template=ENDPOINT,
        expected_secret_name=SECRET,
    )
    files = scaffold["candidate_files"]
    return {
        "plan": canonical_digest(delta),
        "manifest": candidate_manifest_sha256(files),
        "runtime": hashlib.sha256(
            files["src/intraday_provider_runtime.py"].encode("utf-8")
        ).hexdigest(),
        "acquisition": hashlib.sha256(
            files["scripts/acquire_intraday_provider_feed.py"].encode("utf-8")
        ).hexdigest(),
    }


class FullSyntheticActivationReviewTests(unittest.TestCase):
    def review(self, *, cadence="09:30", now_utc=NOW_0930, **overrides):
        hashes = expected_hashes()
        return review_full_synthetic_activation_candidate(
            plan(),
            expected_delta_plan_sha256=overrides.get("plan_hash", hashes["plan"]),
            expected_main_sha=overrides.get("main", MAIN),
            expected_provider_name=overrides.get("provider", PROVIDER),
            expected_endpoint_template=overrides.get("endpoint", ENDPOINT),
            expected_secret_name=overrides.get("secret", SECRET),
            expected_candidate_manifest_sha256=overrides.get(
                "manifest", hashes["manifest"]
            ),
            expected_runtime_sha256=overrides.get("runtime", hashes["runtime"]),
            expected_acquisition_sha256=overrides.get(
                "acquisition", hashes["acquisition"]
            ),
            trading_date=DAY,
            cadence=cadence,
            now_utc=now_utc,
        )

    def test_0930_full_chain_passes_same_candidate_all_review_layers(self):
        result = self.review()
        self.assertEqual(result["validation_status"], "PASS")
        self.assertEqual(
            result["review_disposition"],
            "READY_FOR_LIVE_EVIDENCE_BOUND_ACTIVATION_REVIEW",
        )
        self.assertEqual(result["coverage"], "30/30")
        self.assertEqual(result["market_counts"], {"TWSE": 25, "TPEX": 5})
        self.assertEqual(len(result["subreview_sha256"]), 6)
        self.assertEqual(result["real_network_requests"], 0)
        self.assertEqual(result["repository_writes"], 0)

    def test_1200_full_chain_passes_same_candidate_all_review_layers(self):
        result = self.review(cadence="12:00", now_utc=NOW_1200)
        self.assertEqual(result["validation_status"], "PASS")
        self.assertEqual(result["cadence"], "12:00")
        self.assertEqual(result["coverage"], "30/30")

    def test_candidate_manifest_is_externally_bound(self):
        with self.assertRaisesRegex(
            FullSyntheticActivationReviewError, "CANDIDATE_MANIFEST_HASH_MISMATCH"
        ):
            self.review(manifest="f" * 64)

    def test_runtime_and_acquisition_sources_are_externally_bound(self):
        with self.assertRaisesRegex(
            FullSyntheticActivationReviewError, "RUNTIME_HASH_MISMATCH"
        ):
            self.review(runtime="f" * 64)
        with self.assertRaisesRegex(
            FullSyntheticActivationReviewError, "ACQUISITION_HASH_MISMATCH"
        ):
            self.review(acquisition="e" * 64)

    def test_delta_plan_hash_and_main_are_externally_bound(self):
        with self.assertRaises(Exception):
            self.review(plan_hash="f" * 64)
        with self.assertRaises(Exception):
            self.review(main="f" * 40)

    def test_full_chain_never_claims_acceptance_or_activation(self):
        result = self.review()
        self.assertFalse(result["provider_accepted"])
        self.assertFalse(result["apply_allowed"])
        self.assertFalse(result["activation_execution_allowed"])
        self.assertFalse(result["external_dependency_resolved"])
        self.assertFalse(result["registry_activation_allowed"])
        self.assertEqual(result["production_credit"], 0)
        self.assertEqual(result["cer081_credit"], 0)
        self.assertEqual(result["next_gate"], "LIVE_PROVIDER_EVIDENCE_BINDING")


if __name__ == "__main__":
    unittest.main()
