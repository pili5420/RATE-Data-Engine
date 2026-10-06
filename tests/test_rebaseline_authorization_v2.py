"""Read-only checks for the exact Control Center approved V2 authorization."""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import unittest

from scripts.bootstrap_production_rebaseline_state import (
    _canonical_hash, _validate_approval_commit,
)
from src.production_live_state import require


ROOT = Path(__file__).resolve().parents[1]
BASE = "f3069b238ebc9ce2ef572b767723ec4ecd9a662f"
APPROVAL = "aab70306b214d5213b27b25550abae202db2a536"
APPROVED_HASH = "c317b5e0c4ca14d9c0044b2c9e34c6ba5ed5e7b21d7b3dab17922ca8dcfda8d3"
CANDIDATE_HASH = "e03eaaa9c3fd1a8e4d3733e75e781303261bb34ca4d6d7e54ef3b626cdd64088"
AUTH_ID = "CC-RATE-REBASELINE-20261002-1930-V2"
V1_ID = "CC-RATE-REBASELINE-20261002-1930-V1"
AUTH_NAME = "RATE_PRODUCTION_REBASELINE_AUTHORIZATION_MANIFEST.json"
AUTH_PATH = Path("control/rebaseline_authorizations") / AUTH_ID / AUTH_NAME
V1_PATH = Path("control/rebaseline_authorizations") / V1_ID / AUTH_NAME
EXPECTED_BINDINGS = {
    "production_source_bundle_sha256": "0f6b1ddbedf5989de6b922fa71f767f753ef60c9b4dd8f7526415a380858453d",
    "canonical_rebaseline_state_sha256": "1a79132ae2df3b4c34007a16abd7dcf19375719353669fbba407d2b55d2384ba",
    "source_material_manifest_sha256": "c8efedfc977c026355ddf787cf273ccabbbecdd9e5911267a540081d71ca0074",
    "expected_state_id": "rate-state-baa7113253efcaf5d448e431",
    "expected_state_hash": "baa7113253efcaf5d448e4319318e070da6f6a680d55303e209cd3d64d2d7fec",
}
EXPECTED_AUTHORITY = {
    "authoritative_run_id": "37337863008",
    "authoritative_artifact_commit_sha": BASE,
    "production_snapshot_id": "rate-source-snapshot-3bbe73c100b02f32a57d6443",
    "input_snapshot_id": "rate-input-snapshot-6204bcd8d0f4da477857e3ae",
    "previous_snapshot_id": "rate-source-snapshot-a8d2427c8aab195c3af1debf",
    "baseline_id": "rate-rebaseline-20261002-1930-cc-approved-v1",
}
ACCOUNT_HASHES = {
    "roy_opening_state_sha256": "c09dcf4252c46b35ccfd5f84c584dfa1bc6f0ed341cba51cb31f77787c3b02d6",
    "ai_opening_state_sha256": "d6bb9021e2164fa150807c637d47b1fa3430cdeea171038a42b00115b32e4f35",
    "ledger_boundary_sha256": "aa265a6831552b33a5b1793bd1c1247e693e6b74d254813ecbf2821b91ed8071",
}
THIN_HASH = "d1ba5af279b4909f45da855bdabd4d0c37ea7979e721d0107b7a05013a9d0fee"
ALLOWED_FILES = {
    AUTH_PATH.as_posix(), "tests/test_rebaseline_authorization_v2.py",
    ".github/workflows/rate_rebaseline_authorization_v2_pr_ci.yml",
}


def git(*args):
    return subprocess.check_output(["git", "-C", str(ROOT), *args])


def read(relative):
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def protected_fingerprint():
    names = [p for p in git("ls-tree", "-r", "--name-only", BASE).decode().splitlines() if p]
    paths = {ROOT / name for name in names}
    for folder in (ROOT / "artifacts", ROOT / "data"):
        if folder.exists():
            paths.update(p for p in folder.rglob("*") if p.is_file())
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}


def verify_integrity(authorization):
    # Compose only the existing integrity and approval-commit gates, never bootstrap.
    require(authorization.get("manifest_integrity_hash") == _canonical_hash(authorization),
            "REBASELINE_AUTHORIZATION_MANIFEST_TAMPERED")
    _validate_approval_commit(ROOT, AUTH_PATH, authorization, git("rev-parse", "HEAD").decode().strip())
    require(authorization.get("authorization_status") == "APPROVED"
            and authorization.get("approved_by") == "CONTROL_CENTER",
            "REBASELINE_AUTHORIZATION_NOT_APPROVED")


class RebaselineAuthorizationV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.authorization = read(AUTH_PATH)
        cls.protected_before = protected_fingerprint()

    @classmethod
    def tearDownClass(cls):
        if protected_fingerprint() != cls.protected_before:
            raise AssertionError("PROTECTED_PRODUCTION_MATERIAL_MUTATED")

    def test_approved_status_and_candidate_only_false(self):
        self.assertEqual(self.authorization["authorization_status"], "APPROVED")
        self.assertEqual(self.authorization["approved_by"], "CONTROL_CENTER")
        self.assertIs(self.authorization["candidate_only"], False)

    def test_exact_approved_blob_and_manifest_integrity(self):
        verify_integrity(self.authorization)
        self.assertEqual(_canonical_hash(self.authorization), APPROVED_HASH)
        self.assertEqual(self.authorization["manifest_integrity_hash"], APPROVED_HASH)
        self.assertEqual(self.authorization["authorization_blob_sha256"], APPROVED_HASH)

    def test_all_five_exact_bindings(self):
        for key, value in EXPECTED_BINDINGS.items():
            with self.subTest(binding=key):
                self.assertEqual(self.authorization[key], value)

    def test_all_authoritative_bindings(self):
        for key, value in EXPECTED_AUTHORITY.items():
            with self.subTest(binding=key):
                self.assertEqual(self.authorization[key], value)

    def test_account_ledger_and_thin_manifest_hash_bindings(self):
        for key, value in ACCOUNT_HASHES.items():
            self.assertEqual(self.authorization[key], value)
        self.assertEqual(self.authorization["thin_work_manifest_sha256"], THIN_HASH)

    def test_successor_scope_and_no_dispatch_policy(self):
        self.assertEqual(self.authorization["authorization_id"], AUTH_ID)
        self.assertEqual(self.authorization["supersedes"], V1_ID)
        self.assertEqual(self.authorization["authority_scope"], "RATE_EXACT_MAIN_REBASELINE_BOOTSTRAP_ONLY")
        self.assertIs(self.authorization["dispatch_allowed"], False)
        self.assertIs(self.authorization["single_use"], True)
        self.assertIs(self.authorization["scheduled_soak_credit"], False)
        self.assertIs(self.authorization["acceptance_counter_reset"], False)

    def test_approval_commit_contains_same_immutable_blob(self):
        self.assertEqual(self.authorization["approval_commit_sha"], APPROVAL)
        committed = json.loads(git("show", f"{APPROVAL}:{AUTH_PATH.as_posix()}"))
        self.assertEqual(_canonical_hash(committed), APPROVED_HASH)
        verify_integrity(self.authorization)

    def test_unmerged_approval_cannot_use_current_main_authority(self):
        with self.assertRaisesRegex(RuntimeError, "REBASELINE_APPROVAL_COMMIT_NOT_MAIN_ANCESTOR"):
            _validate_approval_commit(ROOT, AUTH_PATH, self.authorization, BASE)

    def test_v1_unchanged_exact_bytes_and_integrity(self):
        raw = (ROOT / V1_PATH).read_bytes()
        self.assertEqual(raw, git("show", f"{BASE}:{V1_PATH.as_posix()}"))
        self.assertEqual(hashlib.sha256(raw).hexdigest(),
                         "417f42ead3bb14551eeed8301de2dce267959c93942f02a025486285e34fe249")
        v1 = json.loads(raw)
        self.assertEqual(v1["manifest_integrity_hash"], _canonical_hash(v1))
        _validate_approval_commit(ROOT, V1_PATH, v1, BASE)

    def test_repository_canonical_materials_unchanged(self):
        names = git("ls-tree", "-r", "--name-only", BASE, "artifacts/rebaseline_material").decode().splitlines()
        self.assertEqual(len(names), 7)
        for name in names:
            with self.subTest(material=name):
                self.assertEqual((ROOT / name).read_bytes(), git("show", f"{BASE}:{name}"))

    def test_production_bundle_and_thin_manifest_unchanged_binding(self):
        latest = read("artifacts/RATE_PRODUCTION_SOURCE_BUNDLE_LATEST.json")
        thin_latest = read("artifacts/RATE_THIN_WORK_PRODUCTION_BUNDLE_MANIFEST_LATEST.json")
        source = read(latest["immutable_bundle_path"])
        thin = read(thin_latest["manifest_path"])
        snapshot = read(latest["immutable_snapshot_path"])
        self.assertEqual(latest["workflow_run_id"], EXPECTED_AUTHORITY["authoritative_run_id"])
        self.assertEqual(thin["run_id"], latest["workflow_run_id"])
        for payload in (latest, source, thin):
            self.assertEqual(payload["production_snapshot_id"], EXPECTED_AUTHORITY["production_snapshot_id"])
            self.assertEqual(payload["input_snapshot_id"], EXPECTED_AUTHORITY["input_snapshot_id"])
        self.assertEqual(snapshot["previous_snapshot_id"], EXPECTED_AUTHORITY["previous_snapshot_id"])
        self.assertEqual(latest["previous_snapshot_id"], snapshot["previous_snapshot_id"])
        self.assertEqual(thin["manifest_sha256"], THIN_HASH)
        self.assertEqual(thin["commit_sha"], "f0b32d424f7ad6d800a8c0efdf20de37b17e2fa1")
        self.assertEqual(self.authorization["authoritative_artifact_commit_sha"], BASE)
        for path in ("artifacts/RATE_PRODUCTION_SOURCE_BUNDLE_LATEST.json",
                     "artifacts/RATE_THIN_WORK_PRODUCTION_BUNDLE_MANIFEST_LATEST.json",
                     latest["immutable_bundle_path"], latest["immutable_snapshot_path"], thin_latest["manifest_path"]):
            self.assertEqual((ROOT / path).read_bytes(), git("show", f"{BASE}:{path}"))

    def test_tampered_bindings_fail_closed(self):
        for key in (*EXPECTED_BINDINGS, *EXPECTED_AUTHORITY, *ACCOUNT_HASHES,
                    "supersedes", "authority_scope", "candidate_only", "dispatch_allowed", "thin_work_manifest_sha256"):
            with self.subTest(binding=key):
                tampered = copy.deepcopy(self.authorization)
                tampered[key] = "tampered"
                with self.assertRaisesRegex(RuntimeError, "REBASELINE_AUTHORIZATION_MANIFEST_TAMPERED"):
                    verify_integrity(tampered)

    def test_self_rehashed_wrong_bindings_fail_closed(self):
        for key in (*EXPECTED_BINDINGS, *EXPECTED_AUTHORITY, *ACCOUNT_HASHES):
            with self.subTest(binding=key):
                tampered = copy.deepcopy(self.authorization)
                tampered[key] = "tampered"
                tampered["authorization_blob_sha256"] = tampered["manifest_integrity_hash"] = _canonical_hash(tampered)
                with self.assertRaisesRegex(RuntimeError, "REBASELINE_AUTHORIZATION_BYTES_CHANGED_AFTER_APPROVAL"):
                    verify_integrity(tampered)

    def test_old_pending_candidate_hash_cannot_authorize_approved_manifest(self):
        tampered = copy.deepcopy(self.authorization)
        tampered["manifest_integrity_hash"] = tampered["authorization_blob_sha256"] = CANDIDATE_HASH
        with self.assertRaisesRegex(RuntimeError, "REBASELINE_AUTHORIZATION_MANIFEST_TAMPERED"):
            verify_integrity(tampered)

    def test_blob_hash_tamper_fails_closed(self):
        tampered = copy.deepcopy(self.authorization)
        tampered["authorization_blob_sha256"] = "0" * 64
        with self.assertRaisesRegex(RuntimeError, "REBASELINE_AUTHORIZATION_BLOB_HASH_MISMATCH"):
            verify_integrity(tampered)

    def test_missing_approval_commit_fails_closed(self):
        tampered = copy.deepcopy(self.authorization)
        tampered["approval_commit_sha"] = None
        with self.assertRaisesRegex(RuntimeError, "REBASELINE_APPROVAL_COMMIT_INVALID"):
            verify_integrity(tampered)

    def test_scope_freeze_no_production_logic_or_state_changes(self):
        changed = git("diff", "--name-only", BASE).decode().splitlines()
        self.assertTrue(changed)
        self.assertTrue(all(name in ALLOWED_FILES for name in changed), changed)
        for name in git("ls-tree", "-r", "--name-only", BASE).decode().splitlines():
            self.assertEqual((ROOT / name).read_bytes(), git("show", f"{BASE}:{name}"), name)

    def test_zero_live_state_portfolio_ledger_mutation_and_no_fallback(self):
        self.assertEqual(protected_fingerprint(), self.protected_before)
        source_latest = read("artifacts/RATE_PRODUCTION_SOURCE_BUNDLE_LATEST.json")
        provenance = read(source_latest["immutable_bundle_path"])["source_provenance"]
        self.assertEqual(provenance["execution_authority"], "MAIN_ONLY")
        for key in ("fixture", "staging", "local_cache", "synthetic", "recovery", "historical_acceptance_fallback"):
            self.assertIn(provenance.get(key), (None, False, "FORBIDDEN"), key)

    def test_ci_checks_exact_pr_head(self):
        expected = os.getenv("RATE_AUTHORIZATION_CI_HEAD_SHA")
        if expected:
            self.assertEqual(git("rev-parse", "HEAD").decode().strip(), expected)


if __name__ == "__main__":
    unittest.main()
