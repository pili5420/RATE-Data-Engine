"""Dedicated local bare Git remote, never real repository production mutations."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts import bootstrap_full_market_history as cli
from src import full_market_history as h
from tests.test_full_market_history import cfg, material, plan


class HistoryStorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="rate-history-git-test-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.patch = patch("src.full_market_history.contract", side_effect=cfg)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.plan = plan()

    def test_durable_git_commit_cross_checkout_resume_and_idempotent_publish(self):
        remote = self.root / "remote.git"
        subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
        with patch.object(cli, "REMOTE", str(remote)):
            writer = cli.open_store(self.root / "writer")
            h.put_json(writer, "plans/" + self.plan["plan_id"] + ".json", self.plan)
            cp = h.persist_symbol(writer, material(self.plan), self.plan, "1000", "TWSE")
            head = cli.commit_store(writer, self.plan)
            self.assertEqual(cli.git(writer, "cat-file", "-t", head).stdout.strip(), "commit")
            self.assertEqual(cli.commit_store(writer, self.plan), head)
            resumed = cli.open_store(self.root / "fresh-runner", revision=head)
            self.assertEqual(h.load_checkpoint(resumed, self.plan, "1000", "TWSE")[1], cp)
            self.assertEqual(cli.git(resumed, "rev-parse", "HEAD").stdout.strip(), head)
            self.assertFalse((writer / "RATE_PRODUCTION_STATE_LATEST.json").exists())
            h.safe_path(writer, cp["material"]["path"]).write_bytes(b"tamper")
            with self.assertRaisesRegex(RuntimeError, "IMMUTABLE_HISTORY_CONFLICT"):
                cli.commit_store(writer, self.plan)

    def test_nonancestor_history_revision_rejected(self):
        remote = self.root / "remote.git"
        subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
        with patch.object(cli, "REMOTE", str(remote)):
            writer = cli.open_store(self.root / "writer")
            h.put_json(writer, "plans/" + self.plan["plan_id"] + ".json", self.plan)
            cli.commit_store(writer, self.plan)
            with self.assertRaisesRegex(RuntimeError, "HISTORY_REVISION_NOT_ANCESTOR"):
                cli.open_store(self.root / "bad-reload", revision="f" * 40)

    def test_partial_artifact_import_is_validated_then_durable_not_authoritative_snapshot(self):
        inputs = self.root / "incoming"
        source = inputs / "TWSE-000"
        h.persist_symbol(source, material(self.plan), self.plan, "1000", "TWSE")
        destination = self.root / "durable"
        cli.import_progress(destination, self.plan, inputs)
        self.assertIsNotNone(h.load_checkpoint(destination, self.plan, "1000", "TWSE"))
        self.assertEqual(h.aggregate(destination, self.plan)["validation_status"], "FAIL_CLOSED")
        self.assertFalse((destination / "snapshots").exists())

    def test_hash_mismatch_import_zero_durable_writes(self):
        inputs = self.root / "incoming"
        cp = h.persist_symbol(inputs / "shard", material(self.plan), self.plan, "1000", "TWSE")
        h.safe_path(inputs / "shard", cp["material"]["path"]).write_bytes(b"bad")
        with self.assertRaisesRegex(RuntimeError, "HISTORY_MATERIAL_HASH_MISMATCH"):
            cli.import_progress(self.root / "durable", self.plan, inputs)
        self.assertFalse((self.root / "durable").exists())

    def test_duplicate_transfer_fails_no_silent_dedupe(self):
        inputs = self.root / "incoming"
        for shard in ("one", "two"):
            h.persist_symbol(inputs / shard, material(self.plan), self.plan, "1000", "TWSE")
        with self.assertRaisesRegex(RuntimeError, "DUPLICATE_SYMBOL"):
            cli.import_progress(self.root / "durable", self.plan, inputs)
        self.assertFalse((self.root / "durable").exists())

    def test_wrong_storage_branch_and_paths_rejected_before_push(self):
        def wrong(root, *args, **kw):
            self.assertEqual(args, ("branch", "--show-current"))
            return subprocess.CompletedProcess(args, 0, "main\n", "")
        with patch.object(cli, "git", side_effect=wrong), self.assertRaisesRegex(RuntimeError, "HISTORY_STORAGE_BRANCH_INVALID"):
            cli.commit_store(self.root, self.plan)
        with self.assertRaisesRegex(RuntimeError, "WARMUP_OUTPUT_MUST_BE_OUTSIDE_CODE_CHECKOUT"):
            cli.outside_code(h.ROOT / "artifacts/production_state")

    def test_pr_cli_fails_before_network_or_production_writes(self):
        env = {**os.environ, "GITHUB_REF": "refs/pull/25/head", "GITHUB_EVENT_NAME": "pull_request"}
        command = [sys.executable, "-B", str(h.ROOT / "scripts/bootstrap_full_market_history.py"), "plan",
                   "--as-of", "2026-10-06", "--store-root", str(self.root / "ssot"), "--output-root", str(self.root / "out")]
        result = subprocess.run(command, env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn("WARMUP_MAIN_AUTHORITY_REQUIRED", result.stdout)
        self.assertFalse((self.root / "ssot").exists())

    def test_local_environment_cannot_claim_production_warmup(self):
        env = {"GITHUB_REF": "refs/heads/main", "GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_RUN_ID": "100",
               "GITHUB_SHA": "a" * 40, "GITHUB_REPOSITORY": cli.REPOSITORY, "EXECUTION_AUTHORITY": "MAIN_ONLY"}
        with patch.dict(os.environ, env, clear=True), patch.object(cli, "git", side_effect=AssertionError("LOCAL_GIT_AUTHORITY")), \
             self.assertRaisesRegex(RuntimeError, "LOCAL_EVIDENCE_NOT_PRODUCTION_AUTHORITY"):
            cli.main_authority()

    def test_actual_run_binding_is_checked_not_only_environment(self):
        env = {"GITHUB_REF": "refs/heads/main", "GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_RUN_ID": "100",
               "GITHUB_SHA": "a" * 40, "GITHUB_REPOSITORY": cli.REPOSITORY, "EXECUTION_AUTHORITY": "MAIN_ONLY",
               "GITHUB_ACTIONS": "true", "GITHUB_RUN_ATTEMPT": "1"}
        run = {"id": 100, "head_sha": "a" * 40, "head_branch": "main", "event": "workflow_dispatch", "run_attempt": 1,
               "path": ".github/workflows/rate_full_market_history_bootstrap.yml", "status": "in_progress"}
        for change in (None, "head_sha", "head_branch", "event", "path", "run_attempt", "status"):
            response = {**run}
            if change: response[change] = "INVALID"
            with self.subTest(change=change), patch.dict(os.environ, env, clear=True), \
                 patch.object(cli, "git", return_value=subprocess.CompletedProcess([], 0, "a" * 40 + "\n", "")), \
                 patch.object(cli.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, json.dumps(response), "")):
                if change:
                    with self.assertRaisesRegex(RuntimeError, "GITHUB_WARMUP_RUN_BINDING_INVALID"):
                        cli.main_authority()
                else:
                    self.assertEqual(cli.main_authority()["github_execution_evidence"]["run_id"], "100")

    def test_workflow_is_main_dispatch_only_bounded_and_history_branch_only(self):
        import yaml
        path = h.ROOT / ".github/workflows/rate_full_market_history_bootstrap.yml"
        text = path.read_text()
        value = yaml.safe_load(text)
        self.assertEqual(set(value[True]), {"workflow_dispatch"})
        self.assertEqual(value["jobs"]["acquire"]["strategy"]["max-parallel"], 4)
        self.assertFalse(value["jobs"]["acquire"]["strategy"]["fail-fast"])
        self.assertIn("needs.plan.result == 'success'", value["jobs"]["persist-and-validate"]["if"])
        self.assertNotIn("publish_production_state_latest", text)
        self.assertNotIn("run_phase2_production", text)
        self.assertIn("HEAD:refs/heads/\" + BRANCH", (h.ROOT / "scripts/bootstrap_full_market_history.py").read_text())


if __name__ == "__main__":
    unittest.main()
