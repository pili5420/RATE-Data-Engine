"""Activation preflight only; never publish production state or rebuild material."""
import ast
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import unittest
from unittest.mock import patch

import yaml

from scripts import bootstrap_production_rebaseline_state as runtime

ROOT = Path(__file__).resolve().parents[1]
BASE = "4091284be227540b36a1b5b4cce5a4540debe037"
V2_ID = "CC-RATE-REBASELINE-20261002-1930-V2"
V3_ID = "CC-RATE-REBASELINE-20261002-1930-V3"
AUTH_NAME = "RATE_PRODUCTION_REBASELINE_AUTHORIZATION_MANIFEST.json"
V2_PATH = Path("control/rebaseline_authorizations") / V2_ID / AUTH_NAME
V3_PATH = Path("control/rebaseline_authorizations") / V3_ID / AUTH_NAME
WORKFLOW = Path(".github/workflows/rate_production_rebaseline_bootstrap.yml")
EXPECTED_HASH = "ffe6abbc86b882987afb90d1c706af0db45f7d7fb80443e7b4761813c4ce5055"
STOP = "READ_ONLY_TEST_STOP_AFTER_AUTHORIZATION"


def git(*args):
    return subprocess.check_output(["git", "-C", str(ROOT), *args])


def read(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def protected_fingerprint():
    paths = [ROOT / name for name in git("ls-tree", "-r", "--name-only", BASE,
                                       "artifacts", "data", "control/rebaseline_inputs",
                                       V2_PATH.as_posix()).decode().splitlines()]
    for folder in (ROOT / "artifacts/production_state",):
        if folder.exists():
            paths.extend(p for p in folder.rglob("*") if p.is_file())
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


class RebaselineActivationClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.before = protected_fingerprint()

    @classmethod
    def tearDownClass(cls):
        if protected_fingerprint() != cls.before:
            raise AssertionError("PRODUCTION_MATERIAL_MUTATED")

    def preflight(self, authorization_id):
        # Explicit unit-test context, no GITHUB_REF/environment spoofing or dispatch.
        # Stop before material loading, persistence, account writes, or consumption.
        with patch.object(runtime, "_safe_material_path", side_effect=RuntimeError(STOP)) as material_gate, \
             patch.object(runtime, "_stage_package", side_effect=AssertionError("LIVE_WRITE_FORBIDDEN")) as stage, \
             patch.object(runtime, "_write_latest_atomic", side_effect=AssertionError("LATEST_WRITE_FORBIDDEN")) as latest:
            result = runtime.bootstrap_rebaseline_state(
                rebaseline_manifest_path="unused", rebaseline_state_path="unused", source_bundle_path="unused",
                roy_opening_state_path="unused", ai_opening_state_path="unused", ledger_boundary_path="unused",
                trading_date="2026-10-02", cadence="19:30", rebaseline_authorization_id=authorization_id,
                repository_root=ROOT, artifacts_root=ROOT / "artifacts",
                workflow_run_id="101", workflow_job_id="202", event_name="workflow_dispatch",
                ref="refs/heads/main", commit_sha=git("rev-parse", "HEAD").decode().strip(),
                evidence_output=None)
            stage.assert_not_called()
            latest.assert_not_called()
            return result, material_gate.call_count

    def test_v2_runtime_rejects_dispatch_false_before_material_loading(self):
        result, calls = self.preflight(V2_ID)
        self.assertEqual(result["blocking_reason"], "REBASELINE_DISPATCH_NOT_ALLOWED", result)
        self.assertEqual(result["validation_status"], "BLOCKED")
        self.assertEqual(calls, 0)

    def test_v3_runtime_passes_executable_policy_gate_without_any_write(self):
        result, calls = self.preflight(V3_ID)
        self.assertEqual(result["blocking_reason"], STOP, result)
        self.assertEqual(calls, 1)
        self.assertEqual(protected_fingerprint(), self.before)

    def test_v3_policy_pass_and_strict_negative_matrix(self):
        auth = read(V3_PATH)
        runtime._validate_dispatch_policy(auth)
        cases = [
            ("dispatch_allowed", False, "REBASELINE_DISPATCH_NOT_ALLOWED"),
            ("dispatch_allowed", None, "REBASELINE_DISPATCH_NOT_ALLOWED"),
            ("dispatch_allowed", "true", "REBASELINE_DISPATCH_NOT_ALLOWED"),
            ("dispatch_allowed", 1, "REBASELINE_DISPATCH_NOT_ALLOWED"),
            ("candidate_only", True, "REBASELINE_CANDIDATE_ONLY_FORBIDDEN"),
            ("candidate_only", None, "REBASELINE_CANDIDATE_ONLY_FORBIDDEN"),
            ("candidate_only", "false", "REBASELINE_CANDIDATE_ONLY_FORBIDDEN"),
            ("candidate_only", 0, "REBASELINE_CANDIDATE_ONLY_FORBIDDEN"),
            ("authority_scope", "OTHER", "REBASELINE_AUTHORITY_SCOPE_INVALID"),
            ("authority_scope", None, "REBASELINE_AUTHORITY_SCOPE_INVALID"),
        ]
        for key, value, reason in cases:
            with self.subTest(field=key, value=value):
                mutated = copy.deepcopy(auth)
                if value is None:
                    del mutated[key]
                else:
                    mutated[key] = value
                with self.assertRaisesRegex(RuntimeError, reason):
                    runtime._validate_dispatch_policy(mutated)

    def test_v3_only_three_canonical_changes_and_exact_hash(self):
        v2 = read(V2_PATH)
        v3 = read(V3_PATH)
        expected = {**v2, "authorization_id": V3_ID, "supersedes": V2_ID, "dispatch_allowed": True}
        excluded = {"approval_commit_sha", "authorization_blob_sha256", "manifest_integrity_hash"}
        self.assertEqual({k: v for k, v in v3.items() if k not in excluded},
                         {k: v for k, v in expected.items() if k not in excluded})
        self.assertEqual(runtime._canonical_hash(v3), EXPECTED_HASH)
        self.assertEqual(v3["manifest_integrity_hash"], EXPECTED_HASH)
        self.assertEqual(v3["authorization_blob_sha256"], EXPECTED_HASH)
        runtime._validate_approval_commit(ROOT, V3_PATH, v3, git("rev-parse", "HEAD").decode().strip())

    def test_v3_approval_not_current_main_ancestor_fails_closed(self):
        with self.assertRaisesRegex(RuntimeError, "REBASELINE_APPROVAL_COMMIT_NOT_MAIN_ANCESTOR"):
            runtime._validate_approval_commit(ROOT, V3_PATH, read(V3_PATH), BASE)

    def test_existing_approval_and_integrity_validators_unchanged(self):
        before = ast.parse(git("show", f"{BASE}:scripts/bootstrap_production_rebaseline_state.py").decode())
        after = ast.parse((ROOT / "scripts/bootstrap_production_rebaseline_state.py").read_text())
        for name in ("_canonical_hash", "_validate_approval_commit", "validate_material_package", "_safe_material_path"):
            old = next(n for n in before.body if isinstance(n, ast.FunctionDef) and n.name == name)
            new = next(n for n in after.body if isinstance(n, ast.FunctionDef) and n.name == name)
            self.assertEqual(ast.dump(old), ast.dump(new), name)

    def test_tampered_dispatch_cannot_bypass_immutable_approval(self):
        auth = read(V2_PATH)
        auth["dispatch_allowed"] = True
        with self.assertRaisesRegex(RuntimeError, "REBASELINE_AUTHORIZATION_BYTES_CHANGED_AFTER_APPROVAL"):
            runtime._validate_approval_commit(ROOT, V2_PATH, auth, git("rev-parse", "HEAD").decode().strip())

    def test_v1_v2_and_all_materials_unchanged(self):
        names = git("ls-tree", "-r", "--name-only", BASE, "artifacts", "data", "control/rebaseline_inputs",
                    "control/rebaseline_authorizations/CC-RATE-REBASELINE-20261002-1930-V1", V2_PATH.as_posix()).decode().splitlines()
        self.assertTrue(names)
        for name in names:
            with self.subTest(path=name):
                self.assertEqual((ROOT / name).read_bytes(), git("show", f"{BASE}:{name}"))

    def test_workflow_previous_exact_failure_and_fixed_yaml(self):
        old = git("show", f"{BASE}:{WORKFLOW.as_posix()}").decode()
        with self.assertRaises(yaml.YAMLError):
            yaml.safe_load(old)
        new = (ROOT / WORKFLOW).read_text()
        workflow = yaml.safe_load(new)
        # The separately tested checkout-history fix is additive to the heredoc repair.
        heredoc_repair = new.replace("          fetch-depth: 0\n", "", 1)
        self.assertEqual([line.strip() for line in old.splitlines()], [line.strip() for line in heredoc_repair.splitlines()])
        events = workflow.get("on", workflow.get(True))
        self.assertEqual(list(events), ["workflow_dispatch"])
        job = workflow["jobs"]["rebaseline-bootstrap"]
        self.assertEqual(job["if"], "${{ github.ref == 'refs/heads/main' }}")
        script = next(s["run"] for s in job["steps"] if s.get("name") == "Commit authorized rebaseline state")
        bodies = re.findall(r"python - <<'PY'\n(.*?)\nPY(?:\n|$)", script, re.DOTALL)
        self.assertEqual(len(bodies), 5)
        self.assertEqual(bodies, re.findall(r"python - <<'PY'\n(.*?)\nPY(?:\n|$)", old, re.DOTALL))
        for body in bodies:
            compile(body, "<workflow-heredoc>", "exec")

    @unittest.skipUnless(shutil.which("bash"), "bash syntax check runs on Linux PR CI")
    def test_decoded_workflow_bash_syntax(self):
        workflow = yaml.safe_load((ROOT / WORKFLOW).read_text())
        steps = workflow["jobs"]["rebaseline-bootstrap"]["steps"]
        for step in steps:
            if "run" in step:
                result = subprocess.run(["bash", "-n"], input=step["run"], text=True, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_zero_production_live_latest_account_ledger_mutation(self):
        self.assertEqual(protected_fingerprint(), self.before)

    def test_ci_checks_exact_head(self):
        expected = os.getenv("RATE_ACTIVATION_CI_HEAD_SHA")
        if expected:
            self.assertEqual(git("rev-parse", "HEAD").decode().strip(), expected)


if __name__ == "__main__":
    unittest.main()
