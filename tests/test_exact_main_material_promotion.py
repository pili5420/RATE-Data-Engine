"""Verify approved material bytes and bindings without building or publishing state."""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

import yaml

from scripts import bootstrap_production_rebaseline_state as runtime


ROOT = Path(__file__).resolve().parents[1]
BASE = "f2e2349a5fafd47d7adb6141ed8d164fbb663d2b"
MATERIAL = Path("artifacts/rebaseline_material/rate-rebaseline-20261002-1930-cc-approved-v1")
AUTH_PATH = Path("control/rebaseline_authorizations/CC-RATE-REBASELINE-20261002-1930-V3") / runtime.AUTHORIZATION_NAME
CI_PATH = Path(".github/workflows/rate_exact_main_material_promotion_ci.yml")
PROMOTED = {
    "RATE_PRODUCTION_SOURCE_BUNDLE.json": "0f6b1ddbedf5989de6b922fa71f767f753ef60c9b4dd8f7526415a380858453d",
    "RATE_PRODUCTION_REBASELINE_DECISION_STATE.json": "1a79132ae2df3b4c34007a16abd7dcf19375719353669fbba407d2b55d2384ba",
    "RATE_PRODUCTION_REBASELINE_MANIFEST.json": "c8efedfc977c026355ddf787cf273ccabbbecdd9e5911267a540081d71ca0074",
}
ACCOUNTS = {
    "CONTROL_CENTER_REBASELINE_ROY_OPENING_STATE.json": "c09dcf4252c46b35ccfd5f84c584dfa1bc6f0ed341cba51cb31f77787c3b02d6",
    "CONTROL_CENTER_REBASELINE_AI_OPENING_STATE.json": "d6bb9021e2164fa150807c637d47b1fa3430cdeea171038a42b00115b32e4f35",
    "RATE_LEDGER_REBASELINE_BOUNDARY.json": "aa265a6831552b33a5b1793bd1c1247e693e6b74d254813ecbf2821b91ed8071",
}
BINDINGS = {
    "RATE_PRODUCTION_SOURCE_BUNDLE.json": "production_source_bundle_sha256",
    "RATE_PRODUCTION_REBASELINE_DECISION_STATE.json": "canonical_rebaseline_state_sha256",
    "RATE_PRODUCTION_REBASELINE_MANIFEST.json": "source_material_manifest_sha256",
    "CONTROL_CENTER_REBASELINE_ROY_OPENING_STATE.json": "roy_opening_state_sha256",
    "CONTROL_CENTER_REBASELINE_AI_OPENING_STATE.json": "ai_opening_state_sha256",
    "RATE_LEDGER_REBASELINE_BOUNDARY.json": "ledger_boundary_sha256",
}
STATE_ID = "rate-state-baa7113253efcaf5d448e431"
STATE_HASH = "baa7113253efcaf5d448e4319318e070da6f6a680d55303e209cd3d64d2d7fec"
V3_HASH = "ffe6abbc86b882987afb90d1c706af0db45f7d7fb80443e7b4761813c4ce5055"
STOP = "READ_ONLY_STOP_BEFORE_STATE_DERIVATION"


def git(*args):
    return subprocess.check_output(["git", "-C", str(ROOT), *args])


def read(path):
    return json.loads((ROOT / path).read_bytes())


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def protected_fingerprint():
    names = git("ls-tree", "-r", "--name-only", BASE, "artifacts", "data", "control").decode().splitlines()
    paths = {ROOT / name for name in names}
    live = ROOT / "artifacts/production_state"
    if live.exists():
        paths.update(path for path in live.rglob("*") if path.is_file())
    return {path.relative_to(ROOT).as_posix(): digest(path.read_bytes()) for path in sorted(paths)}


class ExactMainMaterialPromotionTests(unittest.TestCase):
    def setUp(self):
        self.authorization = read(AUTH_PATH)
        self.manifest = read(MATERIAL / "RATE_PRODUCTION_REBASELINE_MANIFEST.json")
        self.state = read(MATERIAL / "RATE_PRODUCTION_REBASELINE_DECISION_STATE.json")
        self.source = read(MATERIAL / "RATE_PRODUCTION_SOURCE_BUNDLE.json")
        self.hashes = {name: digest((ROOT / MATERIAL / name).read_bytes()) for name in (*PROMOTED, *ACCOUNTS)}
        self.before = protected_fingerprint()
        self.addCleanup(self.assert_no_mutation)

    def assert_no_mutation(self):
        self.assertEqual(protected_fingerprint(), self.before)

    def test_exact_promoted_bytes_match_all_v3_material_bindings(self):
        for name, expected in {**PROMOTED, **ACCOUNTS}.items():
            with self.subTest(material=name):
                self.assertEqual(self.hashes[name], expected)
                self.assertEqual(self.authorization[BINDINGS[name]], self.hashes[name])

    def test_manifest_internal_file_hashes_use_canonical_gate(self):
        hashes = {name: value for name, value in self.hashes.items()
                  if name != "RATE_PRODUCTION_REBASELINE_MANIFEST.json"}
        self.assertEqual(self.manifest["files"], hashes)
        runtime._check_hashes(self.manifest, hashes)

    def test_existing_state_identity_is_bound_without_rederivation(self):
        for payload in (self.state, self.manifest):
            self.assertEqual(payload["state_id"], STATE_ID)
            self.assertEqual(payload["state_hash"], STATE_HASH)
            self.assertEqual(payload["state_id"], self.authorization["expected_state_id"])
            self.assertEqual(payload["state_hash"], self.authorization["expected_state_hash"])
            self.assertEqual(payload["baseline_id"], self.authorization["baseline_id"])
            self.assertEqual(payload["validation_status"], "PASS")

    def test_canonical_read_only_validation_reaches_gate_before_any_derivation(self):
        # Exercise existing canonical binding checks, stopping before state construction.
        with patch.object(runtime, "_build_rebaseline_persist_and_state", side_effect=RuntimeError(STOP)) as build, \
             patch.object(runtime, "_stage_package", side_effect=AssertionError("LIVE_WRITE_FORBIDDEN")) as stage, \
             patch.object(runtime, "_write_latest_atomic", side_effect=AssertionError("LATEST_WRITE_FORBIDDEN")) as latest:
            with self.assertRaisesRegex(RuntimeError, STOP):
                runtime.validate_material_package(
                    manifest=self.manifest, rebaseline_state=self.state, source_bundle=self.source,
                    roy=read(MATERIAL / "CONTROL_CENTER_REBASELINE_ROY_OPENING_STATE.json"),
                    ai=read(MATERIAL / "CONTROL_CENTER_REBASELINE_AI_OPENING_STATE.json"),
                    ledger=read(MATERIAL / "RATE_LEDGER_REBASELINE_BOUNDARY.json"),
                    hashes={name: value for name, value in self.hashes.items()
                            if name != "RATE_PRODUCTION_REBASELINE_MANIFEST.json"},
                    trading_date="2026-10-02", cadence="19:30", authorization=self.authorization)
            build.assert_called_once()
            stage.assert_not_called()
            latest.assert_not_called()

    def test_failed_run_old_main_bundle_hash_reproduces_exact_blocker(self):
        old = digest(git("show", f"{BASE}:{(MATERIAL / 'RATE_PRODUCTION_SOURCE_BUNDLE.json').as_posix()}"))
        self.assertEqual(old, "8880bff186eebb4673e9d429ce61eafb8375ce93f80b437bb1a6d723fd80a096")
        with self.assertRaisesRegex(RuntimeError, "^REBASELINE_PRODUCTION_BUNDLE_HASH_MISMATCH$"):
            runtime.require(old == self.authorization["production_source_bundle_sha256"],
                            "REBASELINE_PRODUCTION_BUNDLE_HASH_MISMATCH")
        runtime.require(self.hashes["RATE_PRODUCTION_SOURCE_BUNDLE.json"] ==
                        self.authorization["production_source_bundle_sha256"],
                        "REBASELINE_PRODUCTION_BUNDLE_HASH_MISMATCH")

    def test_tampered_manifest_internal_binding_still_fails_closed(self):
        tampered = copy.deepcopy(self.manifest)
        tampered["files"]["RATE_PRODUCTION_SOURCE_BUNDLE.json"] = "0" * 64
        with self.assertRaisesRegex(RuntimeError, "^REBASELINE_MATERIAL_FILE_HASH_MISMATCH$"):
            runtime._check_hashes(tampered, {"RATE_PRODUCTION_SOURCE_BUNDLE.json": self.hashes["RATE_PRODUCTION_SOURCE_BUNDLE.json"]})

    def test_tampered_embedded_source_binding_still_fails_closed(self):
        tampered = copy.deepcopy(self.state["decision"])
        tampered["production_source_bundle_sha256"] = "0" * 64
        with self.assertRaisesRegex(RuntimeError, "^REBASELINE_PRODUCTION_EVIDENCE_BINDING_MISMATCH$"):
            runtime._validate_embedded_production_evidence(
                tampered, self.source, self.hashes["RATE_PRODUCTION_SOURCE_BUNDLE.json"], "2026-10-02", "19:30")

    def test_roy_ai_ledger_are_byte_identical_to_main(self):
        for name, expected in ACCOUNTS.items():
            raw = (ROOT / MATERIAL / name).read_bytes()
            self.assertEqual(raw, git("show", f"{BASE}:{(MATERIAL / name).as_posix()}"))
            self.assertEqual(digest(raw), expected)

    def test_authorizations_v1_v2_v3_and_approval_unchanged(self):
        names = git("ls-tree", "-r", "--name-only", BASE, "control/rebaseline_authorizations").decode().splitlines()
        self.assertTrue(names)
        for name in names:
            self.assertEqual((ROOT / name).read_bytes(), git("show", f"{BASE}:{name}"), name)
        self.assertEqual(self.authorization["approval_commit_sha"], "daf109c0575bb67f13f502a66d64eac6e0db7baa")
        self.assertEqual(runtime._canonical_hash(self.authorization), V3_HASH)
        runtime._validate_approval_commit(ROOT, AUTH_PATH, self.authorization, git("rev-parse", "HEAD").decode().strip())
        runtime._validate_dispatch_policy(self.authorization)

    def test_authoritative_run_commit_snapshots_and_thin_manifest_unchanged(self):
        expected = {
            "authoritative_run_id": "37337863008",
            "authoritative_artifact_commit_sha": "f3069b238ebc9ce2ef572b767723ec4ecd9a662f",
            "production_snapshot_id": "rate-source-snapshot-3bbe73c100b02f32a57d6443",
            "input_snapshot_id": "rate-input-snapshot-6204bcd8d0f4da477857e3ae",
            "previous_snapshot_id": "rate-source-snapshot-a8d2427c8aab195c3af1debf",
            "thin_work_manifest_sha256": "d1ba5af279b4909f45da855bdabd4d0c37ea7979e721d0107b7a05013a9d0fee",
        }
        for key, value in expected.items():
            self.assertEqual(self.authorization[key], value)
        for key in ("production_snapshot_id", "input_snapshot_id"):
            self.assertEqual(self.source[key], expected[key])
        latest = read("artifacts/RATE_PRODUCTION_SOURCE_BUNDLE_LATEST.json")
        thin_latest = read("artifacts/RATE_THIN_WORK_PRODUCTION_BUNDLE_MANIFEST_LATEST.json")
        thin = read(thin_latest["manifest_path"])
        self.assertEqual(latest["workflow_run_id"], expected["authoritative_run_id"])
        self.assertEqual(thin["run_id"], expected["authoritative_run_id"])
        self.assertEqual(thin["manifest_sha256"], expected["thin_work_manifest_sha256"])
        self.assertEqual(read(latest["immutable_snapshot_path"])["previous_snapshot_id"], expected["previous_snapshot_id"])

    def test_only_three_existing_files_change_and_no_other_material_is_promoted(self):
        allowed = {(MATERIAL / name).as_posix() for name in PROMOTED}
        changed = []
        for name in git("ls-tree", "-r", "--name-only", BASE).decode().splitlines():
            if (ROOT / name).read_bytes() != git("show", f"{BASE}:{name}"):
                changed.append(name)
        self.assertEqual(sorted(changed), sorted(allowed))

    def test_runtime_validators_and_all_existing_workflows_unchanged(self):
        for name in git("ls-tree", "-r", "--name-only", BASE, "scripts", "src", "config", ".github/workflows").decode().splitlines():
            self.assertEqual((ROOT / name).read_bytes(), git("show", f"{BASE}:{name}"), name)

    def test_no_fallback_and_validated_official_source(self):
        runtime._validate_source_bundle(self.source, "2026-10-02", "19:30")
        for key in ("validation_status", "freshness_status", "source_status"):
            self.assertEqual(self.source[key], "PASS")
        self.assertEqual(self.source["source_provenance"]["execution_authority"], "MAIN_ONLY")
        self.assertIs(self.source["source_provenance"]["production_evidence_authoritative"], True)

    def test_verification_ci_is_pr_only_read_only_and_exact_head(self):
        workflow = yaml.safe_load((ROOT / CI_PATH).read_text(encoding="utf-8"))
        events = workflow.get("on", workflow.get(True))
        self.assertEqual(list(events), ["pull_request"])
        self.assertEqual(workflow["permissions"], {"contents": "read"})
        checkout = workflow["jobs"]["verify"]["steps"][0]
        self.assertEqual(checkout["with"]["ref"], "${{ github.event.pull_request.head.sha }}")
        self.assertEqual(checkout["with"]["fetch-depth"], 0)
        if os.getenv("RATE_MATERIAL_PROMOTION_CI_HEAD_SHA"):
            self.assertEqual(git("rev-parse", "HEAD").decode().strip(), os.environ["RATE_MATERIAL_PROMOTION_CI_HEAD_SHA"])

    def test_zero_live_latest_portfolio_ledger_mutation(self):
        self.assert_no_mutation()
        for path in ("artifacts/production_state", "artifacts/RATE_PRODUCTION_STATE_LATEST.json"):
            names = git("ls-tree", "-r", "--name-only", BASE, path).decode().splitlines()
            local = ROOT / path
            actual = [local] if local.is_file() else list(local.rglob("*")) if local.exists() else []
            self.assertEqual(sorted(p.relative_to(ROOT).as_posix() for p in actual if p.is_file()), sorted(names))
            for name in names:
                self.assertEqual((ROOT / name).read_bytes(), git("show", f"{BASE}:{name}"))


if __name__ == "__main__":
    unittest.main()
