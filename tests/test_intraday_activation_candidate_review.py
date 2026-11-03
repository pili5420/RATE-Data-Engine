"""Tests for static review of a future intraday activation candidate."""
from __future__ import annotations

from copy import deepcopy
import json
import unittest

from src.intraday_activation_candidate_review import (
    ActivationCandidateReviewError,
    canonical_digest,
    validate_activation_candidate,
)
from src.intraday_activation_delta_plan import NEW_RUNTIME_FILES
from src.intraday_activation_readiness import (
    ALLOWED_EXISTING_MUTATION_PATHS,
    repo_preimage_hashes,
)

MAIN = "1" * 40
PROVIDER = "Fugle"
ENDPOINT = "https://api.fugle.tw/marketdata/v1.0/stock/intraday/quote/{symbol}"
SECRET = "FUGLE_API_KEY"


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
    dependency = {
        "artifact": "RATE_EXTERNAL_PRODUCTION_DEPENDENCIES",
        "dependencies": [{
            "dependency_id": "EXTERNAL_AUTHORIZED_INTRADAY_FEED_DEPENDENCY",
            "status": "PASS",
            "engineering_resolution_available": True,
            "required_market_coverage": ["TWSE", "TPEX"],
            "fallback_allowed": False,
        }],
    }
    source_registry = {
        "domains": [{
            "domain": "market_intraday",
            "provider": PROVIDER,
            "endpoint_or_path": ENDPOINT,
            "authorization_status": "PASS",
            "operational_use_allowed": True,
        }],
        "intraday_status": {
            "0930": "AUTHORIZED_PROVIDER_READY",
            "1200": "AUTHORIZED_PROVIDER_READY",
        },
    }
    official = {
        "datasets": [{
            "dataset_id": "authorized_market_intraday",
            "authority": PROVIDER,
            "required_market_coverage": ["TWSE", "TPEX"],
            "endpoint": ENDPOINT,
            "authorization_status": "PASS",
            "cadence_applicability": {
                "07:30": "NOT_APPLICABLE",
                "09:30": "REQUIRED",
                "12:00": "REQUIRED",
                "19:30": "NOT_APPLICABLE",
            },
            "fallback_allowed": False,
        }],
    }
    phase2 = '''
def require_intraday_authority():
    if dependency.get("status") == "PASS":
        return True
from .intraday_phase2_admission import validate_phase2_intraday_admission
'''
    builder = '''
from src.intraday_phase2_admission import qualify_phase2_intraday_feed
path = os.getenv("RATE_AUTHORIZED_INTRADAY_FEED_PATH")
raw["intraday_admission"] = qualify_phase2_intraday_feed(feed, trading_date=day, cadence=cadence)
'''
    workflow = '''
env:
  FUGLE_API_KEY: ${{ secrets.FUGLE_API_KEY }}
steps:
  - run: python scripts/acquire_intraday_provider_feed.py --output "$RATE_AUTHORIZED_INTRADAY_FEED_PATH"
  - run: python scripts/build_phase2_production_source.py
  - run: python scripts/run_phase2_production.py
RATE_AUTHORIZED_INTRADAY_FEED_PATH: artifacts/feed.json
CADENCE_PLACEHOLDER
'''
    runtime = '''
MAX_REQUESTS = 30
MAX_RETRIES = 0
FALLBACK_ALLOWED = False
API_HOST = "api.fugle.tw"
SECRET_NAME = "FUGLE_API_KEY"
def acquire_intraday_feed(symbols):
    return []
'''
    acquisition = '''
from src.intraday_provider_runtime import acquire_intraday_feed
SECRET_NAME = "FUGLE_API_KEY"
RATE_AUTHORIZED_INTRADAY_FEED_PATH = "RATE_AUTHORIZED_INTRADAY_FEED_PATH"
parser.add_argument("--output")
'''
    return {
        "config/RATE_EXTERNAL_PRODUCTION_DEPENDENCIES.json": json.dumps(dependency),
        "config/SOURCE_REGISTRY.json": json.dumps(source_registry),
        "config/RATE_PRODUCTION_OFFICIAL_SOURCE_REGISTRY_V1.json": json.dumps(official),
        "src/phase2_production.py": phase2,
        "scripts/build_phase2_production_source.py": builder,
        ".github/workflows/rate_production_0930_scheduler.yml": workflow.replace("CADENCE_PLACEHOLDER", "09:30"),
        ".github/workflows/rate_production_1200_scheduler.yml": workflow.replace("CADENCE_PLACEHOLDER", "12:00"),
        "src/intraday_provider_runtime.py": runtime,
        "scripts/acquire_intraday_provider_feed.py": acquisition,
    }


class ActivationCandidateReviewTests(unittest.TestCase):
    def review(self, delta=None, files=None, **overrides):
        current_plan = delta or plan()
        return validate_activation_candidate(
            current_plan,
            files or candidates(),
            expected_delta_plan_sha256=overrides.get(
                "plan_hash", canonical_digest(current_plan)
            ),
            expected_main_sha=overrides.get("main", MAIN),
            expected_provider_name=overrides.get("provider", PROVIDER),
            expected_endpoint_template=overrides.get("endpoint", ENDPOINT),
            expected_secret_name=overrides.get("secret", SECRET),
        )

    def test_exact_candidate_passes_static_review_without_apply(self):
        result = self.review()
        self.assertEqual(result["validation_status"], "PASS")
        self.assertFalse(result["apply_allowed"])
        self.assertFalse(result["activation_execution_allowed"])
        self.assertEqual(result["repository_writes"], 0)
        self.assertEqual(len(result["candidate_file_sha256"]), 9)

    def test_plan_hash_is_external_and_repo_preimage_is_current(self):
        with self.assertRaisesRegex(
            ActivationCandidateReviewError, "DELTA_PLAN_HASH_MISMATCH"
        ):
            self.review(plan_hash="f" * 64)
        delta = plan()
        first = ALLOWED_EXISTING_MUTATION_PATHS[0]
        delta["existing_file_preimage_sha256"][first] = "f" * 64
        with self.assertRaisesRegex(
            ActivationCandidateReviewError, "REPO_PREIMAGE_MISMATCH"
        ):
            self.review(delta=delta, plan_hash=canonical_digest(delta))

    def test_candidate_file_set_is_exact(self):
        value = candidates()
        value["extra.txt"] = "x"
        with self.assertRaisesRegex(
            ActivationCandidateReviewError, "FILE_SET_INVALID"
        ):
            self.review(files=value)
        value = candidates()
        value.pop("src/intraday_provider_runtime.py")
        with self.assertRaisesRegex(
            ActivationCandidateReviewError, "FILE_SET_INVALID"
        ):
            self.review(files=value)

    def test_dependency_and_source_registry_postconditions_are_strict(self):
        value = candidates()
        dep = json.loads(value["config/RATE_EXTERNAL_PRODUCTION_DEPENDENCIES.json"])
        dep["dependencies"][0]["status"] = "BLOCKED_EXTERNAL"
        value["config/RATE_EXTERNAL_PRODUCTION_DEPENDENCIES.json"] = json.dumps(dep)
        with self.assertRaisesRegex(
            ActivationCandidateReviewError, "DEPENDENCY_POSTCONDITION_INVALID"
        ):
            self.review(files=value)

        value = candidates()
        reg = json.loads(value["config/SOURCE_REGISTRY.json"])
        reg["domains"][0]["operational_use_allowed"] = False
        value["config/SOURCE_REGISTRY.json"] = json.dumps(reg)
        with self.assertRaisesRegex(
            ActivationCandidateReviewError, "SOURCE_REGISTRY_POSTCONDITION_INVALID"
        ):
            self.review(files=value)

    def test_official_registry_must_remove_blocked_dependency(self):
        value = candidates()
        reg = json.loads(value["config/RATE_PRODUCTION_OFFICIAL_SOURCE_REGISTRY_V1.json"])
        reg["datasets"][0]["blocked_dependency"] = "EXTERNAL_AUTHORIZED_INTRADAY_FEED_DEPENDENCY"
        value["config/RATE_PRODUCTION_OFFICIAL_SOURCE_REGISTRY_V1.json"] = json.dumps(reg)
        with self.assertRaisesRegex(
            ActivationCandidateReviewError, "OFFICIAL_REGISTRY_POSTCONDITION_INVALID"
        ):
            self.review(files=value)

    def test_phase2_must_preserve_admission_and_remove_forced_partial_runtime(self):
        value = candidates()
        value["src/phase2_production.py"] += '\nraise RuntimeError("PUBLIC_OFFICIAL_PARTIAL_RUNTIME_REQUIRED")\n'
        with self.assertRaisesRegex(
            ActivationCandidateReviewError, "FORCED_PARTIAL_RUNTIME_REMAINS"
        ):
            self.review(files=value)
        value = candidates()
        value["src/phase2_production.py"] = value["src/phase2_production.py"].replace(
            "validate_phase2_intraday_admission", "missing_gate"
        )
        with self.assertRaisesRegex(
            ActivationCandidateReviewError, "PHASE2_REQUIRED_GATES_MISSING"
        ):
            self.review(files=value)

    def test_source_builder_cannot_acquire_network_directly(self):
        value = candidates()
        value["scripts/build_phase2_production_source.py"] += "\nHTTPSConnection('api.fugle.tw')\n"
        with self.assertRaisesRegex(
            ActivationCandidateReviewError, "SOURCE_BUILDER_NETWORK_FORBIDDEN"
        ):
            self.review(files=value)

    def test_schedulers_require_secret_acquisition_and_no_public_partial(self):
        value = candidates()
        path = ".github/workflows/rate_production_0930_scheduler.yml"
        value[path] = value[path].replace(
            "scripts/acquire_intraday_provider_feed.py", "missing.py"
        )
        with self.assertRaisesRegex(
            ActivationCandidateReviewError, "SCHEDULER_WIRING_MISSING"
        ):
            self.review(files=value)
        value = candidates()
        value[path] += "\n--public-official-partial\n"
        with self.assertRaisesRegex(
            ActivationCandidateReviewError, "SCHEDULER_FORBIDDEN_WIRING"
        ):
            self.review(files=value)

    def test_runtime_forbids_retry_fallback_and_wrong_fugle_host(self):
        value = candidates()
        value["src/intraday_provider_runtime.py"] += "\ntime.sleep(1)\n"
        with self.assertRaisesRegex(
            ActivationCandidateReviewError, "RUNTIME_RETRY_OR_FALLBACK_FORBIDDEN"
        ):
            self.review(files=value)
        value = candidates()
        value["src/intraday_provider_runtime.py"] = value[
            "src/intraday_provider_runtime.py"
        ].replace('API_HOST = "api.fugle.tw"', 'API_HOST = "evil.example"')
        with self.assertRaisesRegex(
            ActivationCandidateReviewError, "FUGLE_RUNTIME_HOST_MISSING"
        ):
            self.review(files=value)

    def test_acquisition_cli_cannot_contain_secret_print_or_fallback(self):
        value = candidates()
        value["scripts/acquire_intraday_provider_feed.py"] += "\nprint(api_key)\n"
        with self.assertRaisesRegex(
            ActivationCandidateReviewError, "ACQUISITION_SECRET_OR_FALLBACK_RISK"
        ):
            self.review(files=value)


if __name__ == "__main__":
    unittest.main()
