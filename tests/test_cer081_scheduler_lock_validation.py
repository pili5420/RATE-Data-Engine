"""Synthetic scheduler definition checks; no scheduled-soak or live evidence."""
from pathlib import Path
import unittest
from unittest.mock import patch

from src import cer081_unattended_soak as soak


class SchedulerLockValidationTests(unittest.TestCase):
    block = "concurrency:\n  group: rate-production-0730-0930-1200-1930-${{ github.ref }}\n  cancel-in-progress: false\n"

    def test_all_actual_workflows_share_lock(self):
        self.assertEqual(soak.scheduler_definition_evidence()["scheduler_coverage"], "PASS")

    def test_per_cadence_lock_is_rejected(self):
        for cadence in soak.CADENCES:
            self.assertFalse(soak._shared_writer_concurrency(self.block.replace("0730-0930-1200-1930", cadence.replace(":", ""))))

    def test_cancel_in_progress_rejected(self):
        self.assertFalse(soak._shared_writer_concurrency(self.block.replace("false", "true")))

    def test_missing_cancel_policy_rejected(self):
        self.assertFalse(soak._shared_writer_concurrency(self.block.split("  cancel")[0]))

    def test_duplicate_concurrency_rejected(self):
        self.assertFalse(soak._shared_writer_concurrency(self.block + self.block))

    def test_comment_or_job_substring_cannot_pass(self):
        self.assertFalse(soak._shared_writer_concurrency("# " + self.block.replace("\n", " ")))
        self.assertFalse(soak._shared_writer_concurrency("jobs:\n  sample:\n    " + self.block.replace("\n", "\n    ")))

    def test_one_mismatched_workflow_fails_whole_gate(self):
        original = Path.read_text
        def read(path, *args, **kwargs):
            text = original(path, *args, **kwargs)
            return text.replace("0730-0930-1200-1930", "1930") if path.name == "rate_production_1930_scheduler.yml" else text
        with patch.object(Path, "read_text", read):
            self.assertEqual(soak.scheduler_definition_evidence()["scheduler_coverage"], "FAIL")

    def test_changed_ref_scope_rejected(self):
        self.assertFalse(soak._shared_writer_concurrency(self.block.replace("github.ref", "github.run_id")))


if __name__ == "__main__":
    unittest.main()
