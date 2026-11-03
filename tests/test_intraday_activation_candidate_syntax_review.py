"""Tests for syntax/AST review of the in-memory activation candidate."""
from __future__ import annotations

from copy import deepcopy
import unittest

from src.intraday_activation_candidate_scaffold import build_activation_candidate_scaffold
from src.intraday_activation_candidate_review import canonical_digest
from src.intraday_activation_candidate_syntax_review import (
    ActivationCandidateSyntaxError,
    validate_activation_candidate_syntax,
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
    delta = plan()
    return build_activation_candidate_scaffold(
        delta,
        expected_delta_plan_sha256=canonical_digest(delta),
        expected_main_sha=MAIN,
        expected_provider_name=PROVIDER,
        expected_endpoint_template=ENDPOINT,
        expected_secret_name=SECRET,
    )["candidate_files"]


class ActivationCandidateSyntaxReviewTests(unittest.TestCase):
    def review(self, files=None, **kwargs):
        return validate_activation_candidate_syntax(
            files or candidates(),
            expected_provider_name=kwargs.get("provider", PROVIDER),
            expected_secret_name=kwargs.get("secret", SECRET),
        )

    def test_scaffold_candidate_compiles_and_parses_on_all_surfaces(self):
        result = self.review()
        self.assertEqual(result["validation_status"], "PASS")
        self.assertEqual(len(result["python_files_compiled"]), 4)
        self.assertEqual(len(result["yaml_files_parsed"]), 2)
        self.assertEqual(len(result["json_files_parsed"]), 3)
        self.assertEqual(result["repository_writes"], 0)

    def test_invalid_python_syntax_fails(self):
        value = candidates()
        value["src/intraday_provider_runtime.py"] += "\ndef broken(:\n"
        with self.assertRaisesRegex(
            ActivationCandidateSyntaxError, "PYTHON_INVALID"
        ):
            self.review(value)

    def test_runtime_while_sleep_and_print_are_forbidden(self):
        for snippet, reason in (
            ("\nwhile True:\n    break\n", "WHILE_LOOP_FORBIDDEN"),
            ("\ntime.sleep(1)\n", "SLEEP_FORBIDDEN"),
            ("\nprint(api_key)\n", "PRINT_FORBIDDEN"),
        ):
            value = candidates()
            value["src/intraday_provider_runtime.py"] += snippet
            with self.subTest(snippet=snippet), self.assertRaisesRegex(
                ActivationCandidateSyntaxError, reason
            ):
                self.review(value)

    def test_acquisition_secret_read_is_ast_bound_and_print_forbidden(self):
        value = candidates()
        value["scripts/acquire_intraday_provider_feed.py"] = value[
            "scripts/acquire_intraday_provider_feed.py"
        ].replace("os.getenv(SECRET_NAME)", "None")
        with self.assertRaisesRegex(
            ActivationCandidateSyntaxError, "SECRET_READ_MISSING"
        ):
            self.review(value)
        value = candidates()
        value["scripts/acquire_intraday_provider_feed.py"] += "\nprint(token)\n"
        with self.assertRaisesRegex(
            ActivationCandidateSyntaxError, "ACQUISITION_PRINT_FORBIDDEN"
        ):
            self.review(value)

    def test_phase2_status_helper_ast_is_exact(self):
        value = candidates()
        value["src/phase2_production.py"] = value["src/phase2_production.py"].replace(
            'return "PASS" if cadence in {"09:30", "12:00"} else "NOT_APPLICABLE"',
            'return "PASS" if cadence in {"09:30"} else "NOT_APPLICABLE"',
        )
        with self.assertRaisesRegex(
            ActivationCandidateSyntaxError, "STATUS_HELPER_INVALID"
        ):
            self.review(value)

    def test_invalid_yaml_fails(self):
        value = candidates()
        value[".github/workflows/rate_production_0930_scheduler.yml"] = "jobs: [\n"
        with self.assertRaisesRegex(
            ActivationCandidateSyntaxError, "YAML_INVALID"
        ):
            self.review(value)

    def test_scheduler_secret_is_scoped_only_to_acquisition_step(self):
        path = ".github/workflows/rate_production_0930_scheduler.yml"

        value = candidates()
        value[path] = value[path].replace(
            '      RATE_AUTHORIZED_INTRADAY_FEED_PATH: "artifacts/production_0930/RATE_AUTHORIZED_INTRADAY_FEED.json"\n',
            '      FUGLE_API_KEY: ${{ secrets.FUGLE_API_KEY }}\n'
            '      RATE_AUTHORIZED_INTRADAY_FEED_PATH: "artifacts/production_0930/RATE_AUTHORIZED_INTRADAY_FEED.json"\n',
        )
        with self.assertRaisesRegex(
            ActivationCandidateSyntaxError, "JOB_SECRET_SCOPE_FORBIDDEN"
        ):
            self.review(value)

        value = candidates()
        value[path] = value[path].replace(
            "      - name: Build Phase2 authorized intraday production source bundle\n",
            "      - name: Build Phase2 authorized intraday production source bundle\n"
            "        env:\n"
            "          FUGLE_API_KEY: ${{ secrets.FUGLE_API_KEY }}\n",
        )
        with self.assertRaisesRegex(
            ActivationCandidateSyntaxError, "SECRET_SCOPE_LEAK"
        ):
            self.review(value)

    def test_scheduler_acquisition_build_run_order_is_exact(self):
        path = ".github/workflows/rate_production_1200_scheduler.yml"
        value = candidates()
        text = value[path]
        acquire = text.index("      - name: Acquire authorized intraday provider feed\n")
        build = text.index("      - name: Build Phase2 authorized intraday production source bundle\n")
        run = text.index("      - name: Execute Phase2 authorized intraday runtime\n")
        self.assertLess(acquire, build)
        self.assertLess(build, run)

        acquire_block = text[acquire:build]
        build_block = text[build:run]
        mutated = text[:acquire] + build_block + acquire_block + text[run:]
        value[path] = mutated
        with self.assertRaisesRegex(
            ActivationCandidateSyntaxError, "COMMAND_ORDER_INVALID"
        ):
            self.review(value)

    def test_scheduler_secret_expression_must_be_exact(self):
        value = candidates()
        path = ".github/workflows/rate_production_0930_scheduler.yml"
        value[path] = value[path].replace(
            "${{ secrets.FUGLE_API_KEY }}",
            "FUGLE_API_KEY",
        )
        with self.assertRaisesRegex(
            ActivationCandidateSyntaxError, "SECRET_EXPRESSION_INVALID"
        ):
            self.review(value)

    def test_scheduler_cron_cannot_drift(self):
        value = candidates()
        path = ".github/workflows/rate_production_0930_scheduler.yml"
        value[path] = value[path].replace(
            'cron: "30 1 * * 1-5"',
            'cron: "31 1 * * 1-5"',
        )
        with self.assertRaisesRegex(
            ActivationCandidateSyntaxError, "CRON_DRIFT"
        ):
            self.review(value)

    def test_scheduler_continue_on_error_is_forbidden(self):
        value = candidates()
        path = ".github/workflows/rate_production_1200_scheduler.yml"
        value[path] += "\nextra:\n  continue-on-error: true\n"
        with self.assertRaisesRegex(
            ActivationCandidateSyntaxError, "CONTINUE_ON_ERROR_FORBIDDEN"
        ):
            self.review(value)


if __name__ == "__main__":
    unittest.main()
