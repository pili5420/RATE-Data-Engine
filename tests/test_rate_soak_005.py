"""Transport regression only. Generated test data is never production/soak evidence."""
import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.bootstrap_production_recovery_state import bootstrap_recovery_state
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

    def recovery_source_files(self, day, cadence):
        persist, material = self.material(day, cadence)
        source = self.runtime / "recovery-source" / CADENCE_DIR[cadence]
        persist_path = source / PERSIST_NAME
        state_path = source / STATE_NAME
        atomic_write_json(persist_path, persist)
        atomic_write_json(state_path, material)
        return persist_path, state_path, material["decision_state"]

    def bootstrap_recovery(self, day, cadence, **overrides):
        persist_path, state_path, state = self.recovery_source_files(day, cadence)
        args = dict(source_persist_path=persist_path, source_state_path=state_path,
                    trading_date=day, cadence=cadence, recovery_authorization_id="CC-RATE-SOAK-005",
                    recovery_source_type="FORMAL_ACCEPTED_RECOVERY_SOURCE",
                    artifacts_root=self.artifacts, workflow_run_id="301", workflow_job_id="401",
                    event_name="workflow_dispatch", ref="refs/heads/main", commit_sha="d" * 40,
                    evidence_output=self.artifacts / "production_state/RATE_PRODUCTION_RECOVERY_BOOTSTRAP_EVIDENCE.json")
        args.update(overrides)
        return bootstrap_recovery_state(**args), state

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

    def test_authorized_manual_recovery_bootstrap_writes_canonical_trio(self):
        out, state = self.bootstrap_recovery("2026-09-30", "19:30")
        self.assertEqual(out["validation_status"], "PASS", out)
        directory = self.artifacts / "production_state/live/2026-09-30/1930"
        for name in (PERSIST_NAME, STATE_NAME, MANIFEST_NAME):
            self.assertTrue((directory / name).is_file(), name)
        loaded = load_live_state(self.artifacts / "production_state", "2026-09-30", "19:30")
        self.assertEqual(loaded["state"], state)
        manifest = loaded["manifest"]
        self.assertIs(manifest["recovery_mode"], True)
        self.assertIs(manifest["scheduled_soak_credit"], False)
        self.assertIs(manifest["acceptance_counter_reset"], False)
        self.assertEqual(manifest["source_state_id"], state["current_state_id"])
        self.assertEqual(manifest["source_state_hash"], state["decision_payload_hash"])

    def test_unauthorized_and_scheduled_recovery_bootstrap_blocked(self):
        scheduled, _ = self.bootstrap_recovery("2026-09-30", "19:30", event_name="schedule")
        self.assertEqual(scheduled["blocking_reason"], "RECOVERY_BOOTSTRAP_AUTHORIZATION_REQUIRED")
        unauthorized, _ = self.bootstrap_recovery("2026-09-30", "19:30", recovery_authorization_id="LOCAL")
        self.assertEqual(unauthorized["blocking_reason"], "RECOVERY_BOOTSTRAP_AUTHORIZATION_REQUIRED")
        self.assertFalse((self.artifacts / "production_state/live/2026-09-30/1930").exists())

    def test_recovery_bootstrap_never_overwrites_existing_canonical_slot(self):
        self.install_test_predecessor("2026-09-30", "19:30")
        before = file_hash(self.artifacts / "production_state/live/2026-09-30/1930" / PERSIST_NAME)
        out, _ = self.bootstrap_recovery("2026-09-30", "19:30")
        self.assertEqual(out["blocking_reason"], "LIVE_STATE_CANONICAL_SLOT_EXISTS")
        after = file_hash(self.artifacts / "production_state/live/2026-09-30/1930" / PERSIST_NAME)
        self.assertEqual(after, before)

    def test_stale_or_tampered_recovery_source_fails_closed(self):
        persist_path, state_path, _ = self.recovery_source_files("2026-09-29", "19:30")
        stale = bootstrap_recovery_state(source_persist_path=persist_path, source_state_path=state_path,
            trading_date="2026-09-30", cadence="19:30", recovery_authorization_id="CC-RATE-SOAK-005",
            recovery_source_type="FORMAL_ACCEPTED_RECOVERY_SOURCE",
            artifacts_root=self.artifacts, workflow_run_id="301", workflow_job_id="401",
            event_name="workflow_dispatch", ref="refs/heads/main", commit_sha="d" * 40)
        self.assertEqual(stale["blocking_reason"], "LIVE_STATE_DATE_CADENCE_MISMATCH")
        persist_path, state_path, _ = self.recovery_source_files("2026-09-30", "19:30")
        material = json.loads(state_path.read_text())
        material["decision_state"]["decision"]["transaction_ledger"]["transactions"] = []
        atomic_write_json(state_path, material)
        tampered = bootstrap_recovery_state(source_persist_path=persist_path, source_state_path=state_path,
            trading_date="2026-09-30", cadence="19:30", recovery_authorization_id="CC-RATE-SOAK-005",
            recovery_source_type="FORMAL_ACCEPTED_RECOVERY_SOURCE",
            artifacts_root=self.artifacts, workflow_run_id="301", workflow_job_id="401",
            event_name="workflow_dispatch", ref="refs/heads/main", commit_sha="d" * 40)
        self.assertEqual(tampered["blocking_reason"], "LIVE_STATE_HASH_MISMATCH")

    def test_recovery_source_fixture_staging_cache_synthetic_forbidden(self):
        for segment in ("fixtures", "staging", "cache", "synthetic"):
            with self.subTest(segment=segment):
                persist, material = self.material("2026-09-30", "19:30")
                source = self.runtime / segment / "formal-looking"
                persist_path = source / PERSIST_NAME
                state_path = source / STATE_NAME
                atomic_write_json(persist_path, persist)
                atomic_write_json(state_path, material)
                out = bootstrap_recovery_state(source_persist_path=persist_path, source_state_path=state_path,
                    trading_date="2026-09-30", cadence="19:30", recovery_authorization_id="CC-RATE-SOAK-005",
                    recovery_source_type="FORMAL_ACCEPTED_RECOVERY_SOURCE",
                    artifacts_root=self.artifacts, workflow_run_id="301", workflow_job_id="401",
                    event_name="workflow_dispatch", ref="refs/heads/main", commit_sha="d" * 40)
                self.assertEqual(out["blocking_reason"], "RECOVERY_SOURCE_FALLBACK_FORBIDDEN")

    def test_recovery_manifest_tamper_fails_closed(self):
        self.bootstrap_recovery("2026-09-30", "19:30")
        directory = self.artifacts / "production_state/live/2026-09-30/1930"
        manifest = json.loads((directory / MANIFEST_NAME).read_text())
        manifest["scheduled_soak_credit"] = True
        atomic_write_json(directory / MANIFEST_NAME, manifest)
        load_context = self.context("2026-10-01", "07:30")
        self.assertEqual(load_context["validation_status"], "BLOCKED")
        self.assertEqual(load_context["blocking_reason"], "LIVE_STATE_SCHEDULE_PROVENANCE_REQUIRED")

    def test_recovery_bootstrap_to_full_scheduled_chain_continuity(self):
        boot, previous = self.bootstrap_recovery("2026-09-30", "19:30")
        self.assertEqual(boot["validation_status"], "PASS", boot)
        result_0730, state_0730 = self.publish("2026-10-01", "07:30", previous)
        self.assertEqual(result_0730["validation_status"], "PASS", result_0730)
        result_0930, state_0930 = self.publish("2026-10-01", "09:30", state_0730)
        self.assertEqual(result_0930["validation_status"], "PASS", result_0930)
        result_1200, state_1200 = self.publish("2026-10-01", "12:00", state_0930)
        self.assertEqual(result_1200["validation_status"], "PASS", result_1200)
        result_1930, state_1930 = self.publish("2026-10-01", "19:30", state_1200)
        self.assertEqual(result_1930["validation_status"], "PASS", result_1930)
        context = self.context("2026-10-02", "07:30")
        self.assertEqual(context["validation_status"], "PASS", context)
        self.assertEqual(context["previous_state_id"], state_1930["current_state_id"])
        for key in ("roy_portfolio", "ai_paper_portfolio", "transaction_ledger"):
            self.assertEqual(state_1930["decision"][key], previous["decision"][key])

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
        recovery = Path(".github/workflows/rate_production_recovery_bootstrap.yml").read_text()
        self.assertIn("workflow_dispatch:", recovery)
        self.assertNotIn("schedule:", recovery)
        self.assertIn("RATE_SCHEDULED_SOAK_CREDIT: \"false\"", recovery)
        self.assertIn("RATE_ACCEPTANCE_COUNTER_RESET: \"false\"", recovery)
        self.assertIn("bootstrap_production_recovery_state.py", recovery)
        self.assertIn("FORMAL_ACCEPTED_RECOVERY_SOURCE", recovery)


if __name__ == "__main__":
    unittest.main()
