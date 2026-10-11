"""Synthetic only: real file replacement, OS locks and process crash boundaries."""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts import publish_production_source_bundle_latest as owner
from src import production_refresh_commit as commit
from tests import test_production_source_latest_publisher as fixtures


class AtomicRefreshTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="at-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "a"
        self.root.mkdir()
        self.source = Path(self.temp.name) / "input.json"
        self.source.write_bytes(commit.encode(fixtures.ProductionSourceLatestPublisherTests().bundle()))
        self.latest = self.root / commit.LATEST

    def publish(self, **extra):
        return owner.publish_latest(source_bundle_path=self.source, trading_date="2026-09-21", cadence="19:30",
                                    artifacts_root=self.root, workflow_run_id="synthetic", **extra)

    def initial(self):
        self.assertEqual(self.publish()["publish_result"], "PASS")
        return self.latest.read_bytes()

    def test_single_authoritative_commit(self):
        with patch.object(owner, "atomic_write_json", wraps=owner.atomic_write_json) as writes:
            result = self.publish()
        authoritative = [c for c in writes.call_args_list if c.args[0] == self.latest]
        self.assertEqual(len(authoritative), 1)
        self.assertEqual(result["authoritative_commit_points"], 1)
        self.assertFalse(result["compatibility_authoritative"])
        view = commit.decode((self.root / owner.MANIFEST_LATEST_NAME).read_bytes())
        self.assertFalse(view["authoritative"])

    def test_cold_consumer_reconstructs_all_artifacts(self):
        self.initial()
        run = subprocess.run([sys.executable, "-B", "scripts/read_production_refresh.py", "--latest", str(self.latest),
                              "--expected-sha256", commit.digest(self.latest.read_bytes())], capture_output=True, text=True,
                             encoding="utf-8")
        self.assertEqual(run.returncode, 0, run.stderr)
        data = json.loads(run.stdout)
        self.assertEqual(set(data["artifacts"]), set(commit.FILES))
        self.assertEqual(data["artifacts"]["source_snapshot"]["bundle"], data["artifacts"]["source_bundle"])

    def test_first_pointer_failure_preserves_previous(self):
        before = self.initial()
        with patch.object(owner, "atomic_write_json", side_effect=OSError("first pointer injected")):
            with self.assertRaises(OSError): self.publish()
        self.assertEqual(self.latest.read_bytes(), before)
        commit.read_committed(self.latest, commit.digest(before))

    def test_old_second_pointer_failure_is_committed(self):
        before = self.initial(); write = owner.atomic_write_json
        def fail_second(path, value):
            if path.name == owner.MANIFEST_LATEST_NAME: raise OSError("old second pointer injected")
            write(path, value)
        with patch.object(owner, "atomic_write_json", side_effect=fail_second): result = self.publish()
        self.assertEqual(result["publish_result"], "PASS")
        self.assertEqual(result["transaction_status"], "COMMITTED")
        self.assertNotEqual(self.latest.read_bytes(), before)
        self.assertTrue(result["post_commit_warnings"])
        commit.read_committed(self.latest)

    def test_staging_write_failure_preserves_previous(self):
        before = self.initial()
        with patch.object(commit, "put_object", side_effect=OSError("staging write")):
            with self.assertRaises(OSError): self.publish()
        self.assertEqual(self.latest.read_bytes(), before)

    def test_staging_verification_failure_preserves_previous(self):
        before = self.initial()
        with patch.object(commit, "verify_manifest", side_effect=commit.PublicationError("staging verification")):
            with self.assertRaises(commit.PublicationError): self.publish()
        self.assertEqual(self.latest.read_bytes(), before)

    def test_stale_cas_preserves_other_writer(self):
        before = self.initial()
        with self.assertRaisesRegex(commit.PublicationError, "CAS_STALE_CURRENT"):
            self.publish(expected_previous_latest="0" * 64)
        self.assertEqual(self.latest.read_bytes(), before)

    def test_expected_absence_rejects_existing_latest(self):
        before = self.initial()
        with self.assertRaisesRegex(commit.PublicationError, "CAS_STALE_CURRENT"):
            self.publish(expected_previous_latest=None)
        self.assertEqual(self.latest.read_bytes(), before)

    def test_os_lock_refuses_second_process(self):
        self.initial()
        code = "from src.production_refresh_commit import writer_lock; import sys;\nwith writer_lock(sys.argv[1]): print('WRITER_ENTERED')"
        with commit.writer_lock(self.root):
            run = subprocess.run([sys.executable, "-B", "-c", code, str(self.root)], capture_output=True, text=True)
        self.assertNotEqual(run.returncode, 0)
        self.assertIn("REFRESH_WRITER_CONFLICT", run.stderr)
        self.assertNotIn("WRITER_ENTERED", run.stdout)

    def test_manifest_mutation_rejected(self):
        self.initial(); data = commit.decode(self.latest.read_bytes()); data["snapshot_id"] = "tampered"
        self.latest.write_bytes(commit.encode(data))
        with self.assertRaises(commit.PublicationError): commit.read_committed(self.latest)

    def test_resigned_scope_mutation_rejected(self):
        self.initial(); data = commit.decode(self.latest.read_bytes()); data["cadence"] = "12:00"
        data["refresh_manifest_sha256"] = commit.manifest_digest(data)
        with self.assertRaisesRegex(commit.PublicationError, "SCOPE_BINDING_INVALID"):
            commit.verify_manifest(self.root, data)

    def test_staged_artifact_mutation_rejected(self):
        self.initial(); data = commit.decode(self.latest.read_bytes())
        path = self.root / data["required_artifacts"]["source_bundle"]["path"]
        path.write_bytes(path.read_bytes() + b" ")
        with self.assertRaisesRegex(commit.PublicationError, "ARTIFACT_TAMPER"): commit.read_committed(self.latest)

    def test_missing_artifact_rejected(self):
        self.initial(); data = commit.decode(self.latest.read_bytes())
        (self.root / data["required_artifacts"]["source_snapshot"]["path"]).unlink()
        with self.assertRaisesRegex(commit.PublicationError, "REQUIRED_ARTIFACT_MISSING"): commit.read_committed(self.latest)

    def test_wrong_hash_rejected(self):
        self.initial(); data = commit.decode(self.latest.read_bytes())
        ref = deepcopy(data["required_artifacts"]["source_bundle"]); ref["sha256"] = "0" * 64
        with self.assertRaises(commit.PublicationError): commit.object_at(self.root, "source_bundle", ref)

    def test_immutable_object_never_overwritten(self):
        ref = commit.put_object(self.root, "source_bundle", {"x": 1})
        path = self.root / ref["path"]; path.write_bytes(b"corrupt")
        with self.assertRaisesRegex(commit.PublicationError, "IMMUTABLE_OBJECT_CONFLICT"):
            commit.put_object(self.root, "source_bundle", {"x": 1})
        self.assertEqual(path.read_bytes(), b"corrupt")

    def test_existing_objects_reused_without_byte_changes(self):
        ref = commit.put_object(self.root, "source_bundle", {"x": 1}); before = (self.root / ref["path"]).read_bytes()
        self.assertEqual(commit.put_object(self.root, "source_bundle", {"x": 1}), ref)
        self.assertEqual((self.root / ref["path"]).read_bytes(), before)

    def crash(self, when):
        before = self.initial()
        code = '''import os, sys
from pathlib import Path
from scripts import publish_production_source_bundle_latest as owner
original = owner.atomic_write_json
def crash(path, value):
    if path.name == "RATE_PRODUCTION_SOURCE_BUNDLE_LATEST.json":
        if sys.argv[3] == "before": os._exit(77)
        original(path, value)
        os._exit(78)
    original(path, value)
owner.atomic_write_json = crash
owner.publish_latest(source_bundle_path=sys.argv[1], artifacts_root=sys.argv[2], trading_date="2026-09-21", cadence="19:30", workflow_run_id="crash")
'''
        run = subprocess.run([sys.executable, "-B", "-c", code, str(self.source), str(self.root), when], capture_output=True)
        self.assertEqual(run.returncode, 77 if when == "before" else 78, run.stderr)
        data = commit.read_committed(self.latest)
        if when == "before": self.assertEqual(self.latest.read_bytes(), before)
        else: self.assertEqual(data["manifest"]["workflow_run_id"], "crash")
        return data

    def test_process_crash_before_commit_preserves_previous(self): self.crash("before")

    def test_process_crash_at_commit_boundary_is_cold_readable(self): self.crash("after")

    def test_post_replace_error_remains_committed(self):
        write = owner.atomic_write_json
        def after_replace(path, value):
            write(path, value)
            if path == self.latest: raise OSError("after replace")
        with patch.object(owner, "atomic_write_json", side_effect=after_replace): result = self.publish()
        self.assertEqual(result["publish_result"], "PASS")
        self.assertIn("POST_COMMIT_WRITER_ERROR:OSError", result["post_commit_warnings"])
        commit.read_committed(self.latest)

    def test_post_commit_evidence_error_remains_committed(self):
        output = Path(self.temp.name) / "evidence.json"; write = owner.atomic_write_json
        def fail_evidence(path, value):
            if path == output: raise OSError("evidence failed")
            write(path, value)
        with patch.object(owner, "atomic_write_json", side_effect=fail_evidence): result = self.publish(evidence_output=output)
        self.assertEqual(result["publish_result"], "PASS")
        self.assertTrue(any("EVIDENCE_WRITE_FAILED" in w for w in result["post_commit_warnings"]))

    def test_consumer_ignores_corrupt_compatibility_view(self):
        before = self.initial(); (self.root / owner.MANIFEST_LATEST_NAME).write_bytes(b"corrupt")
        self.assertEqual(commit.read_committed(self.latest)["latest_identity"], commit.digest(before))

    def test_legacy_prior_pointer_migration(self):
        self.latest.write_bytes(commit.encode({"snapshot_id": "legacy", "validation_status": "PASS"}))
        prior = commit.digest(self.latest.read_bytes()); result = self.publish(expected_previous_latest=prior)
        self.assertEqual(result["previous_snapshot_id"], "legacy")
        self.assertEqual(commit.read_committed(self.latest)["manifest"]["prior_latest_identity"], prior)

    def test_invalid_prior_pointer_rejected(self):
        self.latest.write_bytes(b"{}"); before = self.latest.read_bytes()
        with self.assertRaisesRegex(commit.PublicationError, "PRIOR_LATEST_INVALID"): self.publish()
        self.assertEqual(self.latest.read_bytes(), before)

    def test_evidence_cannot_overwrite_authoritative_or_immutable_files(self):
        for path in (self.latest, self.root / owner.MANIFEST_LATEST_NAME, self.root / "production_source_snapshots" / "x"):
            with self.subTest(path=path), self.assertRaisesRegex(commit.PublicationError, "EVIDENCE_PATH_COLLISION"):
                self.publish(evidence_output=path)

    def test_future_commit_timestamp_rejected(self):
        self.initial(); data = commit.decode(self.latest.read_bytes()); data["commit_timestamp"] = "2999-01-01T00:00:00Z"
        data["refresh_manifest_sha256"] = commit.manifest_digest(data)
        with self.assertRaisesRegex(commit.PublicationError, "COMMIT_TIME_INVALID"): commit.verify_manifest(self.root, data)

    def test_expected_identity_rejected(self):
        self.initial()
        with self.assertRaisesRegex(commit.PublicationError, "LATEST_IDENTITY_MISMATCH"):
            commit.read_committed(self.latest, "0" * 64)

    def test_immutable_refresh_manifest_retained(self):
        before = self.initial(); self.publish()
        path = self.root / "production_source_snapshots" / "objects" / commit.digest(before) / commit.OBJECT_FILES["refresh_manifest"]
        self.assertEqual(path.read_bytes(), before)

    def test_duplicate_json_key_rejected(self):
        with self.assertRaisesRegex(commit.PublicationError, "DUPLICATE_JSON_KEY"): commit.decode(b'{"a":1,"a":2}')

    def test_nonfinite_json_rejected(self):
        for raw in (b'{"a":NaN}', b'{"a":Infinity}', b'{"a":1e999}'):
            with self.subTest(raw=raw), self.assertRaises(commit.PublicationError): commit.decode(raw)


if __name__ == "__main__": unittest.main()
