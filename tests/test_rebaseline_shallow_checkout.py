"""Approval-history availability in isolated checkouts; never execute bootstrap."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml

from scripts.bootstrap_production_rebaseline_state import _canonical_hash, _validate_approval_commit

ROOT = Path(__file__).resolve().parents[1]
BASE = "5e8f66a392c24232dfc16a2878e674366e2c9ecd"
APPROVAL = "daf109c0575bb67f13f502a66d64eac6e0db7baa"
AUTH_PATH = Path("control/rebaseline_authorizations/CC-RATE-REBASELINE-20261002-1930-V3/RATE_PRODUCTION_REBASELINE_AUTHORIZATION_MANIFEST.json")
WORKFLOW = Path(".github/workflows/rate_production_rebaseline_bootstrap.yml")
HASH = "ffe6abbc86b882987afb90d1c706af0db45f7d7fb80443e7b4761813c4ce5055"


def git(root, *args, check=True):
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, check=check)


class RebaselineShallowCheckoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="rate-checkout-history-tests-")
        cls.addClassCleanup(cls.temp.cleanup)
        cls.authority = json.loads((ROOT / AUTH_PATH).read_text(encoding="utf-8"))
        cls.head = git(ROOT, "rev-parse", "HEAD").stdout.decode().strip()
        for name, depth in (("shallow", ["--depth=1"]), ("full", [])):
            root = Path(cls.temp.name) / name
            root.mkdir()
            git(root, "init")
            git(root, "fetch", "--no-tags", *depth, ROOT.resolve().as_uri(), "HEAD")
            git(root, "checkout", "--detach", "FETCH_HEAD")
            setattr(cls, name, root)
            if git(root, "rev-parse", "HEAD").stdout.decode().strip() != cls.head:
                raise AssertionError("CHECKOUT_HEAD_MISMATCH")

    def test_shallow_checkout_reproduces_missing_approval_object(self):
        self.assertEqual(git(self.shallow, "rev-parse", "--is-shallow-repository").stdout.strip(), b"true")
        self.assertNotEqual(git(self.shallow, "cat-file", "-e", f"{APPROVAL}^{{commit}}", check=False).returncode, 0)
        with self.assertRaisesRegex(RuntimeError, "REBASELINE_APPROVAL_COMMIT_INVALID"):
            _validate_approval_commit(self.shallow, AUTH_PATH, self.authority, self.head)

    def test_full_checkout_approval_commit_cat_file_passes(self):
        self.assertEqual(git(self.full, "rev-parse", "--is-shallow-repository").stdout.strip(), b"false")
        self.assertEqual(git(self.full, "cat-file", "-e", f"{APPROVAL}^{{commit}}").returncode, 0)

    def test_full_checkout_merge_base_ancestry_passes(self):
        self.assertEqual(git(self.full, "merge-base", "--is-ancestor", APPROVAL, self.head).returncode, 0)

    def test_full_checkout_git_show_manifest_and_v3_immutable_hash_pass(self):
        committed = json.loads(git(self.full, "show", f"{APPROVAL}:{AUTH_PATH.as_posix()}").stdout)
        self.assertEqual(_canonical_hash(committed), HASH)
        self.assertEqual(_canonical_hash(self.authority), HASH)
        self.assertEqual(self.authority["manifest_integrity_hash"], HASH)
        self.assertEqual(self.authority["authorization_blob_sha256"], HASH)
        _validate_approval_commit(self.full, AUTH_PATH, self.authority, self.head)

    def test_wrong_approval_commit_still_fails_closed(self):
        wrong = copy.deepcopy(self.authority)
        wrong["approval_commit_sha"] = "f" * 40
        with self.assertRaisesRegex(RuntimeError, "REBASELINE_APPROVAL_COMMIT_INVALID"):
            _validate_approval_commit(self.full, AUTH_PATH, wrong, self.head)

    def test_existing_non_ancestor_approval_still_fails_closed(self):
        git(self.full, "config", "user.name", "RATE isolated test")
        git(self.full, "config", "user.email", "rate-test@example.invalid")
        tree = git(self.full, "rev-parse", "HEAD^{tree}").stdout.decode().strip()
        orphan = git(self.full, "commit-tree", tree, "-m", "Isolated non-ancestor test").stdout.decode().strip()
        wrong = copy.deepcopy(self.authority)
        wrong["approval_commit_sha"] = orphan
        with self.assertRaisesRegex(RuntimeError, "REBASELINE_APPROVAL_COMMIT_NOT_MAIN_ANCESTOR"):
            _validate_approval_commit(self.full, AUTH_PATH, wrong, self.head)

    def test_workflow_only_adds_full_history_checkout_and_yaml_parses(self):
        old = git(ROOT, "show", f"{BASE}:{WORKFLOW.as_posix()}").stdout.decode()
        new = (ROOT / WORKFLOW).read_text(encoding="utf-8")
        ref = "          ref: ${{ github.ref_name }}\n"
        self.assertEqual(old.count(ref), 1)
        self.assertEqual(new, old.replace(ref, ref + "          fetch-depth: 0\n", 1))
        expected = yaml.safe_load(old)
        actual = yaml.safe_load(new)
        expected["jobs"]["rebaseline-bootstrap"]["steps"][0]["with"]["fetch-depth"] = 0
        self.assertEqual(actual, expected)

    def test_validator_runtime_materials_and_all_authorizations_unchanged(self):
        names = git(ROOT, "ls-tree", "-r", "--name-only", BASE,
                    "scripts", "src", "artifacts", "data", "control").stdout.decode().splitlines()
        self.assertTrue(names)
        for name in names:
            with self.subTest(path=name):
                self.assertEqual((ROOT / name).read_bytes(), git(ROOT, "show", f"{BASE}:{name}").stdout)

    def test_checkout_regression_does_not_write_production_live_or_latest(self):
        for path in ("artifacts/production_state/live", "artifacts/RATE_PRODUCTION_STATE_LATEST.json"):
            before = git(ROOT, "ls-tree", "-r", "--name-only", BASE, path).stdout.decode().splitlines()
            local = ROOT / path
            actual = [local] if local.is_file() else list(local.rglob("*")) if local.exists() else []
            self.assertEqual(sorted(p.relative_to(ROOT).as_posix() for p in actual if p.is_file()), sorted(before))
            for name in before:
                self.assertEqual(hashlib.sha256((ROOT / name).read_bytes()).hexdigest(),
                                 hashlib.sha256(git(ROOT, "show", f"{BASE}:{name}").stdout).hexdigest())


if __name__ == "__main__":
    unittest.main()
