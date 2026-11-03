"""Tests for isolated activation candidate materialization and disk readback review."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import tempfile
import unittest

from src.intraday_activation_candidate_materialization import (
    CandidateMaterializationError,
    candidate_manifest_sha256,
    materialize_candidate_workspace,
    review_materialized_candidate_workspace,
)
from src.intraday_activation_candidate_review import canonical_digest
from src.intraday_activation_candidate_scaffold import (
    build_activation_candidate_scaffold,
)
from src.intraday_activation_delta_plan import NEW_RUNTIME_FILES
from src.intraday_activation_readiness import (
    ALLOWED_EXISTING_MUTATION_PATHS,
    ROOT,
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


def scaffold():
    delta = plan()
    return build_activation_candidate_scaffold(
        delta,
        expected_delta_plan_sha256=canonical_digest(delta),
        expected_main_sha=MAIN,
        expected_provider_name=PROVIDER,
        expected_endpoint_template=ENDPOINT,
        expected_secret_name=SECRET,
    )


class CandidateMaterializationTests(unittest.TestCase):
    def review(self, root, candidate, delta):
        runtime_source = candidate["src/intraday_provider_runtime.py"]
        return review_materialized_candidate_workspace(
            delta,
            workspace_root=root,
            expected_candidate_manifest_sha256=candidate_manifest_sha256(candidate),
            expected_delta_plan_sha256=canonical_digest(delta),
            expected_main_sha=MAIN,
            expected_provider_name=PROVIDER,
            expected_endpoint_template=ENDPOINT,
            expected_secret_name=SECRET,
            expected_runtime_sha256=hashlib.sha256(runtime_source.encode("utf-8")).hexdigest(),
            trading_date=DAY,
            cadence=CADENCE,
            now_utc=NOW,
        )

    def test_exact_candidate_materializes_and_passes_disk_readback_reviews(self):
        delta = plan()
        candidate = scaffold()["candidate_files"]
        before = repo_preimage_hashes()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = materialize_candidate_workspace(
                candidate,
                workspace_root=root,
                expected_candidate_manifest_sha256=candidate_manifest_sha256(candidate),
            )
            reviewed = self.review(root, candidate, delta)
            self.assertEqual(result["validation_status"], "PASS")
            self.assertEqual(reviewed["validation_status"], "PASS")
            self.assertEqual(reviewed["runtime_semantic_review"]["coverage"], "30/30")
            self.assertEqual(reviewed["runtime_semantic_review"]["real_network_requests"], 0)
            self.assertEqual(reviewed["runtime_semantic_review"]["synthetic_success_requests"], 30)
        self.assertEqual(repo_preimage_hashes(), before)

    def test_external_manifest_hash_mismatch_fails_before_write(self):
        candidate = scaffold()["candidate_files"]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaisesRegex(
                CandidateMaterializationError, "EXTERNAL_MANIFEST_HASH_MISMATCH"
            ):
                materialize_candidate_workspace(
                    candidate,
                    workspace_root=root,
                    expected_candidate_manifest_sha256="f" * 64,
                )
            self.assertEqual(list(root.rglob("*")), [])

    def test_nonempty_workspace_fails_without_overwrite(self):
        candidate = scaffold()["candidate_files"]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            protected = root / "protected.txt"
            protected.write_text("keep", encoding="utf-8")
            with self.assertRaisesRegex(
                CandidateMaterializationError, "WORKSPACE_NOT_EMPTY"
            ):
                materialize_candidate_workspace(
                    candidate,
                    workspace_root=root,
                    expected_candidate_manifest_sha256=candidate_manifest_sha256(candidate),
                )
            self.assertEqual(protected.read_text(encoding="utf-8"), "keep")

    def test_repository_root_is_rejected_before_write(self):
        candidate = scaffold()["candidate_files"]
        before = repo_preimage_hashes()
        with self.assertRaisesRegex(
            CandidateMaterializationError, "REPOSITORY_WRITE_FORBIDDEN"
        ):
            materialize_candidate_workspace(
                candidate,
                workspace_root=ROOT,
                expected_candidate_manifest_sha256=candidate_manifest_sha256(candidate),
            )
        self.assertEqual(repo_preimage_hashes(), before)

    def test_extra_or_path_escape_candidate_is_rejected(self):
        candidate = scaffold()["candidate_files"]
        candidate = dict(candidate)
        candidate["../escape.txt"] = "x"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaisesRegex(
                CandidateMaterializationError, "FILE_SET_INVALID"
            ):
                materialize_candidate_workspace(
                    candidate,
                    workspace_root=root,
                    expected_candidate_manifest_sha256="0" * 64,
                )
            self.assertFalse((root.parent / "escape.txt").exists())

    def test_tamper_after_materialization_is_detected_on_readback(self):
        delta = plan()
        candidate = scaffold()["candidate_files"]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = candidate_manifest_sha256(candidate)
            materialize_candidate_workspace(
                candidate,
                workspace_root=root,
                expected_candidate_manifest_sha256=manifest,
            )
            target = root / "src/intraday_provider_runtime.py"
            target.write_text(target.read_text(encoding="utf-8") + "\n# tamper\n", encoding="utf-8")
            with self.assertRaisesRegex(
                CandidateMaterializationError, "READBACK_MANIFEST_HASH_MISMATCH"
            ):
                review_materialized_candidate_workspace(
                    delta,
                    workspace_root=root,
                    expected_candidate_manifest_sha256=manifest,
                    expected_delta_plan_sha256=canonical_digest(delta),
                    expected_main_sha=MAIN,
                    expected_provider_name=PROVIDER,
                    expected_endpoint_template=ENDPOINT,
                    expected_secret_name=SECRET,
                    expected_runtime_sha256="0" * 64,
                    trading_date=DAY,
                    cadence=CADENCE,
                    now_utc=NOW,
                )

    def test_second_materialization_is_rejected_by_nonempty_boundary(self):
        candidate = scaffold()["candidate_files"]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = candidate_manifest_sha256(candidate)
            materialize_candidate_workspace(
                candidate, workspace_root=root,
                expected_candidate_manifest_sha256=manifest,
            )
            with self.assertRaisesRegex(
                CandidateMaterializationError, "WORKSPACE_NOT_EMPTY"
            ):
                materialize_candidate_workspace(
                    candidate, workspace_root=root,
                    expected_candidate_manifest_sha256=manifest,
                )

    def test_materialized_path_set_is_exact_nine_files(self):
        candidate = scaffold()["candidate_files"]
        self.assertEqual(
            set(candidate),
            set(ALLOWED_EXISTING_MUTATION_PATHS) | set(NEW_RUNTIME_FILES),
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = materialize_candidate_workspace(
                candidate,
                workspace_root=root,
                expected_candidate_manifest_sha256=candidate_manifest_sha256(candidate),
            )
            self.assertEqual(len(result["materialized_paths"]), 9)
            self.assertEqual(
                set(result["materialized_paths"]),
                set(ALLOWED_EXISTING_MUTATION_PATHS) | set(NEW_RUNTIME_FILES),
            )


if __name__ == "__main__":
    unittest.main()
