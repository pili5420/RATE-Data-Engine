"""Transport regression only. Generated test data is never production/soak evidence."""
import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.publish_production_state_latest import publish_state
from scripts.resolve_production_runtime_context import resolve_context
from src.cer074_acceptance import atomic_write_json, sha256, strip_runtime
from src.production_live_state import (ARTIFACTS, CADENCE_DIR, MANIFEST_NAME, PERSIST_NAME, STATE_NAME,
                                      file_hash, load_live_state)


class RateSoak005Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="rate-soak-005-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.artifacts = self.root / "artifacts"
        self.runtime = self.root / "runtime"

    def material(self, day, cadence, previous=None):
        previous = previous or {"current_state_id": "rate-state-" + "a" * 24, "decision_payload_hash": "a" * 64}
        accounts = copy.deepcopy({k: previous["decision"][k] for k in
                                  ("roy_portfolio", "ai_paper_portfolio", "transaction_ledger")}) if "decision" in previous else {
            "roy_portfolio": {"positions": [{"symbol": "TEST", "quantity": 27}], "cash": 123456},
            "ai_paper_portfolio": {"positions": [{"symbol": "TEST", "quantity": 19}], "cash": 654321,
                                   "realized_pl": 102, "unrealized_pl": -13, "nav": 655000},
            "transaction_ledger": {"ledger_id": "TEST_ONLY", "transactions": [{"id": "test-txn-1", "quantity": 19}]}}
        decision = {"trading_date": day, "cadence": cadence, "execution_scope": "PRODUCTION",
                    "previous_state_resolution": "PERSISTED_PRODUCTION_STATE",
                    "previous_state_id": previous["current_state_id"], "previous_state_hash": previous["decision_payload_hash"],
                    "records": [{"symbol": "TEST"}], **accounts}
        digest = sha256(strip_runtime(decision))
        state = {"current_state_id": "rate-state-" + digest[:24], "decision_payload_hash": digest,
                 "previous_state_id": previous["current_state_id"], "decision": decision}
        entry = {k: decision[k] for k in ("trading_date", "cadence", "execution_scope", "previous_state_resolution", "previous_state_id")}
        entry.update(current_state_id=state["current_state_id"], decision_payload_hash=digest)
        persist = {"artifact": ARTIFACTS[cadence], "validation_status": "PASS", "current_state_id": state["current_state_id"],
                   "current_state_hash": digest, "previous_state_id": previous["current_state_id"],
                   "persist_result": {"status": "PERSISTED", "state_entry": entry}}
        return persist, {"state_entry": entry, "decision_state": state}

    def install_test_predecessor(self, day, cadence):
        # Test setup only, deliberately bypasses publisher. There is no production bootstrap API.
        persist, material = self.material(day, cadence)
        directory = self.artifacts / "production_state/live" / day / CADENCE_DIR[cadence]
        atomic_write_json(directory / PERSIST_NAME, persist)
        atomic_write_json(directory / STATE_NAME, material)
        manifest = {"artifact": "RATE_PRODUCTION_STATE_MANIFEST", "validation_status": "PASS",
                    "trading_date": day, "cadence": cadence, "event_name": "schedule", "ref": "refs/heads/main",
                    "workflow_run_id": "100", "workflow_job_id": "200", "commit_sha": "b" * 40,
                    "current_state_id": persist["current_state_id"], "current_state_hash": persist["current_state_hash"],
                    "files": {name: file_hash(directory / name) for name in (PERSIST_NAME, STATE_NAME)}}
        atomic_write_json(directory / MANIFEST_NAME, manifest)
        return material["decision_state"], directory

    def publish(self, day, cadence, previous, **overrides):
        persist, material = self.material(day, cadence, previous)
        evidence = self.runtime / "persist.json"
        atomic_write_json(evidence, persist)
        atomic_write_json(self.runtime / "decision_state" / CADENCE_DIR[cadence] / (persist["current_state_id"] + ".json"), material)
        args = dict(persist_evidence_path=evidence, trading_date=day, cadence=cadence, artifacts_root=self.artifacts,
                    state_root=self.runtime, workflow_run_id="101", workflow_job_id="201", event_name="schedule",
                    ref="refs/heads/main", commit_sha="c" * 40)
        args.update(overrides)
        return publish_state(**args), material["decision_state"]

    def context(self, day, cadence, artifacts=None):
        with patch("scripts.resolve_production_runtime_context._today_taipei", return_value=day):
            return resolve_context(cadence=cadence, event_name="schedule", dispatch_trading_date="2026-09-18",
                                   state_root=(artifacts or self.artifacts) / "production_state")

    def transition(self, prior_day, prior_cadence, day, cadence):
        previous, _ = self.install_test_predecessor(prior_day, prior_cadence)
        result, current = self.publish(day, cadence, previous)
        self.assertEqual(result["validation_status"], "PASS", result)
        # Independent runner receives only the canonical published tree, never the local runtime directory.
        checkout = self.root / "clean-checkout/artifacts"
        shutil.copytree(self.artifacts / "production_state", checkout / "production_state")
        context = self.context(day, cadence, checkout)
        self.assertEqual(context["validation_status"], "PASS", context)
        self.assertEqual(context["previous_state_match_count"], 1)
        self.assertEqual(context["previous_state_id"], previous["current_state_id"])
        loaded = load_live_state(checkout / "production_state", day, cadence)
        self.assertEqual(loaded["state"], current)
        self.assertEqual(current["previous_state_id"], previous["current_state_id"])
        for key in ("roy_portfolio", "ai_paper_portfolio", "transaction_ledger"):
            self.assertEqual(loaded["state"]["decision"][key], previous["decision"][key])
        return previous, current

    def test_0730_to_0930_clean_runner_continuity(self):
        self.transition("2026-09-30", "07:30", "2026-09-30", "09:30")

    def test_0930_to_1200_clean_runner_continuity(self):
        self.transition("2026-09-30", "09:30", "2026-09-30", "12:00")

    def test_1200_to_1930_clean_runner_continuity(self):
        self.transition("2026-09-30", "12:00", "2026-09-30", "19:30")

    def test_1930_to_next_trading_day_0730(self):
        self.transition("2026-09-30", "19:30", "2026-10-01", "07:30")

    def test_weekend_and_existing_calendar_holiday_boundary(self):
        self.transition("2026-09-25", "19:30", "2026-09-29", "07:30")

    def test_missing_previous_never_uses_latest_acceptance_staging_cache_or_stale_state(self):
        _, directory = self.install_test_predecessor("2026-09-29", "09:30")
        for destination in ("accepted/2026-09-30/0930", "staging/2026-09-30/0930", "cache/2026-09-30/0930", "fixtures/2026-09-30/0930"):
            shutil.copytree(directory, self.artifacts / destination)
        atomic_write_json(self.artifacts / "RATE_PRODUCTION_STATE_LATEST.json", {"live_state_evidence_path": str(directory / PERSIST_NAME)})
        context = self.context("2026-09-30", "12:00")
        self.assertEqual(context["blocking_reason"], "LIVE_PREVIOUS_PRODUCTION_STATE_MISSING")
        self.assertEqual(context["trading_date"], "2026-09-30")
        self.assertEqual(context["scheduled_historical_acceptance_date_fallback"], "FORBIDDEN")

    def test_publisher_cannot_bootstrap_missing_predecessor(self):
        _, previous = self.material("2026-09-30", "07:30")
        out, _ = self.publish("2026-09-30", "09:30", previous["decision_state"])
        self.assertEqual(out["blocking_reason"], "LIVE_PREVIOUS_PRODUCTION_STATE_MISSING")
        self.assertFalse((self.artifacts / "production_state/live/2026-09-30/0930").exists())

    def test_hash_tampering_fails_closed(self):
        _, directory = self.install_test_predecessor("2026-09-30", "09:30")
        material = json.loads((directory / STATE_NAME).read_text())
        material["decision_state"]["decision"]["ai_paper_portfolio"]["cash"] = 0
        atomic_write_json(directory / STATE_NAME, material)
        self.assertEqual(self.context("2026-09-30", "12:00")["blocking_reason"], "LIVE_STATE_FILE_HASH_MISMATCH")
        manifest = json.loads((directory / MANIFEST_NAME).read_text())
        manifest["files"][STATE_NAME] = file_hash(directory / STATE_NAME)
        atomic_write_json(directory / MANIFEST_NAME, manifest)
        self.assertEqual(self.context("2026-09-30", "12:00")["blocking_reason"], "LIVE_STATE_HASH_MISMATCH")

    def test_partial_publication_and_summary_only_fail_closed(self):
        _, directory = self.install_test_predecessor("2026-09-30", "09:30")
        (directory / MANIFEST_NAME).unlink()
        self.assertEqual(self.context("2026-09-30", "12:00")["validation_status"], "BLOCKED")
        (directory / STATE_NAME).unlink()
        self.assertEqual(self.context("2026-09-30", "12:00")["validation_status"], "BLOCKED")

    def test_wrong_date_cadence_and_non_schedule_manifest_rejected(self):
        _, directory = self.install_test_predecessor("2026-09-30", "09:30")
        original = json.loads((directory / MANIFEST_NAME).read_text())
        for key, value in (("trading_date", "2026-09-18"), ("cadence", "07:30"), ("event_name", "push"),
                           ("event_name", "workflow_dispatch"), ("ref", "refs/heads/staging"), ("commit_sha", None)):
            with self.subTest(key=key, value=value):
                atomic_write_json(directory / MANIFEST_NAME, {**original, key: value})
                self.assertEqual(self.context("2026-09-30", "12:00")["validation_status"], "BLOCKED")

    def test_replay_is_immutable_and_does_not_regress_latest(self):
        previous, _ = self.install_test_predecessor("2026-09-30", "07:30")
        first, current = self.publish("2026-09-30", "09:30", previous)
        midday, _ = self.publish("2026-09-30", "12:00", current)
        self.assertEqual(midday["validation_status"], "PASS", midday)
        before = (self.artifacts / "RATE_PRODUCTION_STATE_LATEST.json").read_bytes()
        replay, _ = self.publish("2026-09-30", "09:30", previous)
        self.assertEqual(replay["idempotency_result"], "IDEMPOTENT_NOOP")
        self.assertEqual(before, (self.artifacts / "RATE_PRODUCTION_STATE_LATEST.json").read_bytes())
        fork_previous = copy.deepcopy(previous)
        fork_previous["decision"]["ai_paper_portfolio"]["cash"] += 1
        conflict, _ = self.publish("2026-09-30", "09:30", fork_previous)
        self.assertEqual(conflict["blocking_reason"], "LIVE_STATE_IMMUTABLE_CONFLICT")
        self.assertEqual(file_hash(Path(first["live_state_evidence_path"])), file_hash(Path(replay["live_state_evidence_path"])))

    def test_ledger_history_loss_rejected_before_publication(self):
        previous, _ = self.install_test_predecessor("2026-09-30", "07:30")
        changed = copy.deepcopy(previous)
        changed["decision"]["transaction_ledger"]["transactions"] = []
        out, _ = self.publish("2026-09-30", "09:30", changed)
        self.assertEqual(out["blocking_reason"], "LIVE_STATE_LEDGER_HISTORY_LOST")
        self.assertFalse((self.artifacts / "RATE_PRODUCTION_STATE_LATEST.json").exists())

    def test_invalid_provenance_never_writes_live_state(self):
        previous, _ = self.install_test_predecessor("2026-09-30", "07:30")
        for event in ("push", "workflow_dispatch", "local"):
            out, _ = self.publish("2026-09-30", "09:30", previous, event_name=event)
            self.assertEqual(out["blocking_reason"], "LIVE_STATE_SCHEDULE_PROVENANCE_REQUIRED")

    def test_workflows_transport_full_state_and_never_seed_acceptance(self):
        groups = set()
        for slot in CADENCE_DIR.values():
            text = Path(f".github/workflows/rate_production_{slot}_scheduler.yml").read_text()
            publish = text.split("- name: Publish live production state pointer", 1)[1].split("- name:", 1)[0]
            self.assertIn(f"--state-root data/production/scheduler_{slot}", publish)
            self.assertIn("artifacts/production_state/live", text)
            self.assertIn("Upload committed live production state", text)
            self.assertIn("if-no-files-found: error", text)
            self.assertNotIn("seed_live_production_state.py", text)
            self.assertNotIn("RATE_CER079_EOD_CLOSURE_ARTIFACT_ID", text)
            self.assertNotIn("--reset-state-root", text)
            groups.add(next(line.strip() for line in text.splitlines() if "group:" in line))
        self.assertEqual(len(groups), 1)


if __name__ == "__main__":
    unittest.main()
