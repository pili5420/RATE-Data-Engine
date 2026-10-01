"""Transport regression only. Generated test data is never production/soak evidence."""
import copy
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.bootstrap_production_recovery_state import (AUTHORIZATION_NAME, CONSUMPTION_NAME, _canonical_hash,
                                                        bootstrap_recovery_state)
from scripts.publish_production_state_latest import publish_state
from scripts.resolve_production_runtime_context import resolve_context
from src.cer074_acceptance import atomic_write_json, sha256, strip_runtime
from src.production_live_state import (ARTIFACTS, CADENCE_DIR, MANIFEST_NAME, PERSIST_NAME, STATE_NAME,
                                      file_hash, load_live_state, validate_material, validate_recovery_source_material)


class RateSoak005Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="rate-soak-005-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.artifacts = self.root / "artifacts"
        self.runtime = self.root / "runtime"
        self.repo = self.root / "repo"
        self.git("init", self.repo)
        self.git("-C", self.repo, "checkout", "-b", "main")
        self.git("-C", self.repo, "config", "user.email", "rate-test@example.invalid")
        self.git("-C", self.repo, "config", "user.name", "RATE Test")
        atomic_write_json(self.repo / "README.json", {"test_repository": True})
        self.git("-C", self.repo, "add", "README.json")
        self.git("-C", self.repo, "commit", "-m", "Initial main")
        self.initial_sha = self.git("-C", self.repo, "rev-parse", "HEAD")

    def git(self, *args):
        result = subprocess.run(["git", *map(str, args)], cwd=self.root, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

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

    def legacy_material(self, day, cadence, previous=None):
        previous = previous or {"current_state_id": "rate-state-" + "a" * 24, "decision_payload_hash": "a" * 64}
        decision = {"trading_date": day, "cadence": cadence, "execution_scope": "PRODUCTION",
                    "previous_state_resolution": "PERSISTED_PRODUCTION_STATE",
                    "previous_state_id": previous["current_state_id"],
                    "previous_state_hash": previous["decision_payload_hash"],
                    "records": [{"symbol": "TEST"}],
                    "roy_portfolio": {"positions_extended": True, "cash": "PASS", "nav": "PASS", "reset": False},
                    "ai_paper_portfolio": {"positions_extended": True, "cash_preserved": True,
                                           "closing_nav": "PASS", "reset": False},
                    "transaction_ledger": {"ledger_id": "legacy-accepted-ledger",
                                           "historical_transactions_preserved": True,
                                           "append_only": True, "new_transactions": [], "reset": False}}
        return self.wrap_decision(decision, previous, cadence)

    def value_level_legacy_material(self, day, cadence, previous=None):
        previous = previous or {"current_state_id": "rate-state-" + "a" * 24, "decision_payload_hash": "a" * 64}
        decision = {"trading_date": day, "cadence": cadence, "execution_scope": "PRODUCTION",
                    "previous_state_resolution": "PERSISTED_PRODUCTION_STATE",
                    "previous_state_id": previous["current_state_id"],
                    "previous_state_hash": previous["decision_payload_hash"],
                    "records": [{"symbol": "TEST"}],
                    "roy_portfolio": {"holdings": [{"id": "roy-pos-1", "symbol": "ROY", "quantity": 27,
                                                    "cost_basis": 2700}],
                                      "cash_balance": 123456, "equity": 126156, "reset": False},
                    "ai_paper_portfolio_ledger": {"position_lots": [{"id": "ai-pos-1", "symbol": "AI",
                                                                     "quantity": 19, "cost_basis": 1900}],
                                                  "cash_balance": 654321, "equity": 656221,
                                                  "reset": False, "positions_preserved": True,
                                                  "cash_preserved": True},
                    "transaction_ledger": {"ledger_id": "legacy-accepted-ledger",
                                           "historical_transactions": [{"id": "txn-1", "symbol": "AI",
                                                                        "quantity": 10},
                                                                       {"id": "txn-2", "symbol": "AI",
                                                                        "quantity": 9}],
                                           "new_transactions": [{"id": "txn-3", "symbol": "AI",
                                                                 "quantity": 0}],
                                           "historical_transactions_preserved": True,
                                           "append_only": True, "reset": False}}
        return self.wrap_decision(decision, previous, cadence)

    def wrap_decision(self, decision, previous, cadence):
        digest = sha256(strip_runtime(decision))
        state = {"current_state_id": "rate-state-" + digest[:24], "decision_payload_hash": digest,
                 "previous_state_id": previous["current_state_id"], "decision": decision}
        entry = {k: decision[k] for k in ("trading_date", "cadence", "execution_scope", "previous_state_resolution", "previous_state_id")}
        entry.update(current_state_id=state["current_state_id"], decision_payload_hash=digest)
        persist = {"artifact": ARTIFACTS[cadence], "validation_status": "PASS", "current_state_id": state["current_state_id"],
                   "current_state_hash": digest, "previous_state_id": previous["current_state_id"],
                   "persist_result": {"status": "PERSISTED", "state_entry": entry}}
        return persist, {"state_entry": entry, "decision_state": state}

    def legacy_recovery_source_files(self, day, cadence):
        persist, material = self.value_level_legacy_material(day, cadence)
        source = self.runtime / "legacy-accepted-recovery-source" / CADENCE_DIR[cadence]
        persist_path = source / PERSIST_NAME
        state_path = source / STATE_NAME
        atomic_write_json(persist_path, persist)
        atomic_write_json(state_path, material)
        return persist_path, state_path, material["decision_state"]

    def assert_recovery_normalization_blocked(self, mutate, reason="RECOVERY_SCHEMA_NORMALIZATION_DATA_UNAVAILABLE"):
        persist, material = self.value_level_legacy_material("2026-09-30", "19:30")
        mutate(material["decision_state"]["decision"])
        digest = sha256(strip_runtime(material["decision_state"]["decision"]))
        material["decision_state"].update(current_state_id="rate-state-" + digest[:24],
                                          decision_payload_hash=digest)
        material["state_entry"].update(current_state_id=material["decision_state"]["current_state_id"],
                                       decision_payload_hash=digest)
        persist.update(current_state_id=material["decision_state"]["current_state_id"],
                       current_state_hash=digest)
        persist["persist_result"]["state_entry"] = material["state_entry"]
        with self.assertRaisesRegex(RuntimeError, reason):
            validate_recovery_source_material(persist, material, "2026-09-30", "19:30")

    def authorization_manifest(self, persist_path, state_path, state, day, cadence, **overrides):
        authorization_id = overrides.pop("authorization_id", "CC-RATE-SOAK-005")
        path_authorization_id = overrides.pop("path_authorization_id", authorization_id)
        commit = overrides.pop("commit", True)
        payload = {"artifact": "RATE_PRODUCTION_RECOVERY_AUTHORIZATION_MANIFEST",
                   "authorization_id": authorization_id,
                   "defect_id": "RATE-SOAK-005",
                   "approved_source_type": "FORMAL_ACCEPTED_RECOVERY_SOURCE",
                   "approved_trading_date": day,
                   "approved_cadence": cadence,
                   "approved_source_state_id": state["current_state_id"],
                   "approved_source_state_hash": state["decision_payload_hash"],
                   "approved_source_persist_sha256": file_hash(persist_path),
                   "approved_source_state_sha256": file_hash(state_path),
                   "approved_target_trading_date": day,
                   "approved_target_cadence": cadence,
                   "scheduled_soak_credit": False,
                   "acceptance_counter_reset": False,
                   "single_use": True,
                   "authorization_status": "APPROVED",
                   "approved_by": "CONTROL_CENTER",
                   "created_at": "2026-09-30T00:00:00Z",
                   "approval_commit_sha": "0" * 40}
        payload.update(overrides)
        payload["authorization_blob_sha256"] = _canonical_hash(payload)
        payload["manifest_integrity_hash"] = _canonical_hash(payload)
        path = self.repo / "control" / "recovery_authorizations" / path_authorization_id / AUTHORIZATION_NAME
        atomic_write_json(path, payload)
        if commit:
            rel = path.relative_to(self.repo).as_posix()
            self.git("-C", self.repo, "add", rel)
            self.git("-C", self.repo, "commit", "-m", f"Approve recovery {path_authorization_id}")
            approval = self.git("-C", self.repo, "rev-parse", "HEAD")
            payload["approval_commit_sha"] = approval
            payload["authorization_blob_sha256"] = _canonical_hash(payload)
            payload["manifest_integrity_hash"] = _canonical_hash(payload)
            atomic_write_json(path, payload)
            self.git("-C", self.repo, "add", rel)
            self.git("-C", self.repo, "commit", "-m", f"Bind approval commit {path_authorization_id}")
        return path, payload

    def bootstrap_recovery(self, day, cadence, **overrides):
        persist_path, state_path, state = self.recovery_source_files(day, cadence)
        self.authorization_manifest(persist_path, state_path, state, day, cadence)
        args = dict(source_persist_path=persist_path, source_state_path=state_path,
                    trading_date=day, cadence=cadence, recovery_authorization_id="CC-RATE-SOAK-005",
                    recovery_source_type="FORMAL_ACCEPTED_RECOVERY_SOURCE",
                    repository_root=self.repo,
                    artifacts_root=self.artifacts, workflow_run_id="301", workflow_job_id="401",
                    event_name="workflow_dispatch", ref="refs/heads/main", commit_sha=self.git("-C", self.repo, "rev-parse", "HEAD"),
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
        consumption = self.artifacts / "production_state/recovery_authorizations/CC-RATE-SOAK-005" / CONSUMPTION_NAME
        self.assertTrue(consumption.is_file())
        consumed = json.loads(consumption.read_text())
        self.assertIs(consumed["consumed"], True)
        self.assertEqual(consumed["authorization_id"], "CC-RATE-SOAK-005")

    def test_legacy_accepted_state_never_passes_normal_runtime_validation(self):
        persist, material = self.legacy_material("2026-09-30", "19:30")
        with self.assertRaisesRegex(RuntimeError, "LIVE_STATE_AI_ACCOUNT_MISSING"):
            validate_material(persist, material, "2026-09-30", "19:30")

    def test_authorized_recovery_adapts_legacy_accepted_state_to_runtime_schema(self):
        persist_path, state_path, state = self.legacy_recovery_source_files("2026-09-30", "19:30")
        source = json.loads(state_path.read_text())["decision_state"]["decision"]
        self.authorization_manifest(persist_path, state_path, state, "2026-09-30", "19:30")
        out = bootstrap_recovery_state(source_persist_path=persist_path, source_state_path=state_path,
            trading_date="2026-09-30", cadence="19:30", recovery_authorization_id="CC-RATE-SOAK-005",
            recovery_source_type="FORMAL_ACCEPTED_RECOVERY_SOURCE",
            repository_root=self.repo, artifacts_root=self.artifacts, workflow_run_id="301", workflow_job_id="401",
            event_name="workflow_dispatch", ref="refs/heads/main", commit_sha=self.git("-C", self.repo, "rev-parse", "HEAD"))
        self.assertEqual(out["validation_status"], "PASS", out)
        self.assertIs(out["legacy_recovery_schema_compatibility"], True)
        loaded = load_live_state(self.artifacts / "production_state", "2026-09-30", "19:30")
        self.assertEqual(loaded["state"]["current_state_id"], state["current_state_id"])
        self.assertEqual(loaded["state"]["decision_payload_hash"], state["decision_payload_hash"])
        self.assertEqual(loaded["state"]["runtime_schema_compatibility"]["mode"], "RECOVERY_ONLY")
        self.assertIs(loaded["state"]["runtime_schema_compatibility"]["synthetic_position_created"], False)
        self.assertIs(loaded["state"]["runtime_schema_compatibility"]["synthetic_transaction_created"], False)
        self.assertIs(loaded["state"]["runtime_schema_compatibility"]["default_zero_balance_used"], False)
        self.assertIn("positions", loaded["state"]["decision"]["ai_paper_portfolio"])
        self.assertIn("cash", loaded["state"]["decision"]["ai_paper_portfolio"])
        self.assertNotEqual(loaded["state"]["decision"]["ai_paper_portfolio"]["cash"], 0)
        self.assertIn("transactions", loaded["state"]["decision"]["transaction_ledger"])
        normalized = loaded["state"]["decision"]
        self.assertEqual(normalized["ai_paper_portfolio"]["positions"],
                         source["ai_paper_portfolio_ledger"]["position_lots"])
        self.assertEqual(normalized["ai_paper_portfolio"]["positions"][0]["quantity"], 19)
        self.assertEqual(normalized["ai_paper_portfolio"]["cash"],
                         source["ai_paper_portfolio_ledger"]["cash_balance"])
        self.assertEqual(normalized["ai_paper_portfolio"]["nav"],
                         source["ai_paper_portfolio_ledger"]["equity"])
        self.assertEqual(normalized["roy_portfolio"]["positions"],
                         source["roy_portfolio"]["holdings"])
        self.assertEqual(normalized["roy_portfolio"]["positions"][0]["quantity"], 27)
        self.assertEqual(normalized["roy_portfolio"]["cash"], source["roy_portfolio"]["cash_balance"])
        self.assertEqual(normalized["roy_portfolio"]["nav"], source["roy_portfolio"]["equity"])
        self.assertEqual(normalized["transaction_ledger"]["transactions"],
                         [*source["transaction_ledger"]["historical_transactions"],
                          *source["transaction_ledger"]["new_transactions"]])
        self.assertEqual([t["id"] for t in normalized["transaction_ledger"]["transactions"]],
                         ["txn-1", "txn-2", "txn-3"])
        result_0730, state_0730 = self.publish("2026-10-01", "07:30", loaded["state"])
        self.assertEqual(result_0730["validation_status"], "PASS", result_0730)
        self.assertEqual(state_0730["previous_state_id"], state["current_state_id"])

    def test_recovery_value_level_normalization_missing_data_and_placeholders_blocked(self):
        cases = (
            ("missing AI positions", lambda d: d["ai_paper_portfolio_ledger"].pop("position_lots")),
            ("missing AI cash", lambda d: d["ai_paper_portfolio_ledger"].pop("cash_balance")),
            ("missing AI NAV", lambda d: d["ai_paper_portfolio_ledger"].pop("equity")),
            ("missing full ledger", lambda d: d["transaction_ledger"].pop("historical_transactions")),
            ("placeholder positions", lambda d: d["ai_paper_portfolio_ledger"].update(position_lots=[])),
            ("marker cash object", lambda d: d["ai_paper_portfolio_ledger"].update(cash_balance={"preserved": True})),
            ("default zero cash", lambda d: d["ai_paper_portfolio_ledger"].update(cash_balance=0)),
            ("fabricated transaction missing id", lambda d: d["transaction_ledger"]["historical_transactions"].append({"symbol": "AI", "quantity": 1})),
            ("fabricated position missing id", lambda d: d["ai_paper_portfolio_ledger"]["position_lots"].append({"symbol": "AI", "quantity": 1})),
            ("missing Roy positions", lambda d: d["roy_portfolio"].pop("holdings")),
            ("missing Roy cash", lambda d: d["roy_portfolio"].pop("cash_balance")),
            ("missing Roy NAV", lambda d: d["roy_portfolio"].pop("equity")),
            ("missing Roy quantity", lambda d: d["roy_portfolio"]["holdings"][0].pop("quantity")),
        )
        for label, mutate in cases:
            with self.subTest(label=label):
                self.assert_recovery_normalization_blocked(mutate)

    def test_recovery_source_with_only_new_transactions_is_blocked(self):
        self.assert_recovery_normalization_blocked(
            lambda d: d["transaction_ledger"].pop("historical_transactions"))

    def test_unauthorized_and_scheduled_recovery_bootstrap_blocked(self):
        scheduled, _ = self.bootstrap_recovery("2026-09-30", "19:30", event_name="schedule")
        self.assertEqual(scheduled["blocking_reason"], "RECOVERY_BOOTSTRAP_AUTHORIZATION_REQUIRED")
        persist_path, state_path, _ = self.recovery_source_files("2026-09-30", "19:30")
        unauthorized = bootstrap_recovery_state(source_persist_path=persist_path, source_state_path=state_path,
            trading_date="2026-09-30", cadence="19:30",
            recovery_authorization_id="CC-FAKE", recovery_source_type="FORMAL_ACCEPTED_RECOVERY_SOURCE",
            repository_root=self.repo, artifacts_root=self.artifacts, workflow_run_id="301", workflow_job_id="401",
            event_name="workflow_dispatch", ref="refs/heads/main", commit_sha=self.git("-C", self.repo, "rev-parse", "HEAD"))
        self.assertEqual(unauthorized["blocking_reason"], "RECOVERY_AUTHORIZATION_MANIFEST_REQUIRED")
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
        auth_path, _ = self.authorization_manifest(persist_path, state_path, json.loads(state_path.read_text())["decision_state"], "2026-09-29", "19:30",
                                                   approved_target_trading_date="2026-09-30")
        stale = bootstrap_recovery_state(source_persist_path=persist_path, source_state_path=state_path,
            trading_date="2026-09-30", cadence="19:30", recovery_authorization_id="CC-RATE-SOAK-005",
            recovery_source_type="FORMAL_ACCEPTED_RECOVERY_SOURCE",
            repository_root=self.repo, artifacts_root=self.artifacts, workflow_run_id="301", workflow_job_id="401",
            event_name="workflow_dispatch", ref="refs/heads/main", commit_sha=self.git("-C", self.repo, "rev-parse", "HEAD"))
        self.assertEqual(stale["blocking_reason"], "RECOVERY_AUTHORIZATION_SOURCE_SLOT_MISMATCH")
        persist_path, state_path, state = self.recovery_source_files("2026-09-30", "19:30")
        auth_path, _ = self.authorization_manifest(persist_path, state_path, state, "2026-09-30", "19:30")
        material = json.loads(state_path.read_text())
        material["decision_state"]["decision"]["transaction_ledger"]["transactions"] = []
        atomic_write_json(state_path, material)
        tampered = bootstrap_recovery_state(source_persist_path=persist_path, source_state_path=state_path,
            trading_date="2026-09-30", cadence="19:30", recovery_authorization_id="CC-RATE-SOAK-005",
            recovery_source_type="FORMAL_ACCEPTED_RECOVERY_SOURCE",
            repository_root=self.repo, artifacts_root=self.artifacts, workflow_run_id="301", workflow_job_id="401",
            event_name="workflow_dispatch", ref="refs/heads/main", commit_sha=self.git("-C", self.repo, "rev-parse", "HEAD"))
        self.assertEqual(tampered["blocking_reason"], "RECOVERY_SOURCE_STATE_FILE_HASH_MISMATCH")

    def test_recovery_source_fixture_staging_cache_synthetic_forbidden(self):
        for segment in ("fixtures", "staging", "cache", "synthetic"):
            with self.subTest(segment=segment):
                persist, material = self.material("2026-09-30", "19:30")
                source = self.runtime / segment / "formal-looking"
                persist_path = source / PERSIST_NAME
                state_path = source / STATE_NAME
                atomic_write_json(persist_path, persist)
                atomic_write_json(state_path, material)
                auth_path, _ = self.authorization_manifest(persist_path, state_path, material["decision_state"], "2026-09-30", "19:30")
                out = bootstrap_recovery_state(source_persist_path=persist_path, source_state_path=state_path,
                    trading_date="2026-09-30", cadence="19:30", recovery_authorization_id="CC-RATE-SOAK-005",
                    recovery_source_type="FORMAL_ACCEPTED_RECOVERY_SOURCE",
                    repository_root=self.repo, artifacts_root=self.artifacts, workflow_run_id="301", workflow_job_id="401",
                    event_name="workflow_dispatch", ref="refs/heads/main", commit_sha=self.git("-C", self.repo, "rev-parse", "HEAD"))
                self.assertEqual(out["blocking_reason"], "RECOVERY_SOURCE_FALLBACK_FORBIDDEN")

    def test_authorization_manifest_fixture_staging_cache_synthetic_forbidden(self):
        for segment in ("fixtures", "staging", "cache", "synthetic"):
            with self.subTest(segment=segment):
                persist_path, state_path, state = self.recovery_source_files("2026-09-30", "19:30")
                _, payload = self.authorization_manifest(persist_path, state_path, state, "2026-09-30", "19:30",
                                                         path_authorization_id="CC-UNUSED", commit=False)
                forbidden_path = self.runtime / segment / "authorization" / AUTHORIZATION_NAME
                atomic_write_json(forbidden_path, payload)
                out = bootstrap_recovery_state(source_persist_path=persist_path, source_state_path=state_path,
                    trading_date="2026-09-30", cadence="19:30", recovery_authorization_id="CC-RATE-SOAK-005",
                    recovery_source_type="FORMAL_ACCEPTED_RECOVERY_SOURCE",
                    repository_root=self.repo, artifacts_root=self.artifacts, workflow_run_id="301", workflow_job_id="401",
                    event_name="workflow_dispatch", ref="refs/heads/main", commit_sha=self.git("-C", self.repo, "rev-parse", "HEAD"))
                self.assertEqual(out["blocking_reason"], "RECOVERY_AUTHORIZATION_MANIFEST_REQUIRED")

    def test_authorization_id_path_traversal_blocked(self):
        persist_path, state_path, _ = self.recovery_source_files("2026-09-30", "19:30")
        for authorization_id in ("CC-../escape", "CC-RATE/SOAK", "CC-RATE\\SOAK"):
            with self.subTest(authorization_id=authorization_id):
                out = bootstrap_recovery_state(source_persist_path=persist_path, source_state_path=state_path,
                    trading_date="2026-09-30", cadence="19:30", recovery_authorization_id=authorization_id,
                    recovery_source_type="FORMAL_ACCEPTED_RECOVERY_SOURCE",
                    repository_root=self.repo, artifacts_root=self.artifacts, workflow_run_id="301", workflow_job_id="401",
                    event_name="workflow_dispatch", ref="refs/heads/main", commit_sha=self.git("-C", self.repo, "rev-parse", "HEAD"))
                self.assertEqual(out["blocking_reason"], "RECOVERY_BOOTSTRAP_AUTHORIZATION_REQUIRED")

    def test_authorization_manifest_mismatches_fail_closed(self):
        cases = (
            ("wrong authorization ID", {"authorization_id": "CC-OTHER", "path_authorization_id": "CC-RATE-SOAK-005"}, "RECOVERY_AUTHORIZATION_ID_MISMATCH", "CC-RATE-SOAK-005"),
            ("wrong source state ID", {"approved_source_state_id": "rate-state-" + "0" * 24}, "RECOVERY_SOURCE_STATE_ID_MISMATCH", "CC-RATE-SOAK-005"),
            ("wrong source state hash", {"approved_source_state_hash": "0" * 64}, "RECOVERY_SOURCE_STATE_HASH_MISMATCH", "CC-RATE-SOAK-005"),
            ("wrong persist SHA-256", {"approved_source_persist_sha256": "0" * 64}, "RECOVERY_SOURCE_PERSIST_HASH_MISMATCH", "CC-RATE-SOAK-005"),
            ("wrong state file SHA-256", {"approved_source_state_sha256": "0" * 64}, "RECOVERY_SOURCE_STATE_FILE_HASH_MISMATCH", "CC-RATE-SOAK-005"),
            ("wrong trading date", {"approved_trading_date": "2026-09-29"}, "RECOVERY_AUTHORIZATION_SOURCE_SLOT_MISMATCH", "CC-RATE-SOAK-005"),
            ("wrong cadence", {"approved_cadence": "12:00"}, "RECOVERY_AUTHORIZATION_SOURCE_SLOT_MISMATCH", "CC-RATE-SOAK-005"),
            ("wrong target date", {"approved_target_trading_date": "2026-10-01"}, "RECOVERY_AUTHORIZATION_TARGET_MISMATCH", "CC-RATE-SOAK-005"),
            ("wrong target cadence", {"approved_target_cadence": "12:00"}, "RECOVERY_AUTHORIZATION_TARGET_MISMATCH", "CC-RATE-SOAK-005"),
            ("not approved", {"authorization_status": "DRAFT"}, "RECOVERY_AUTHORIZATION_NOT_APPROVED", "CC-RATE-SOAK-005"),
            ("wrong approver", {"approved_by": "LOCAL"}, "RECOVERY_AUTHORIZATION_APPROVER_INVALID", "CC-RATE-SOAK-005"),
        )
        for label, override, reason, caller_id in cases:
            with self.subTest(label=label):
                persist_path, state_path, state = self.recovery_source_files("2026-09-30", "19:30")
                auth_path, _ = self.authorization_manifest(persist_path, state_path, state, "2026-09-30", "19:30", **override)
                out = bootstrap_recovery_state(source_persist_path=persist_path, source_state_path=state_path,
                    trading_date="2026-09-30", cadence="19:30", recovery_authorization_id=caller_id,
                    recovery_source_type="FORMAL_ACCEPTED_RECOVERY_SOURCE",
                    repository_root=self.repo, artifacts_root=self.artifacts, workflow_run_id="301", workflow_job_id="401",
                    event_name="workflow_dispatch", ref="refs/heads/main", commit_sha=self.git("-C", self.repo, "rev-parse", "HEAD"))
                self.assertEqual(out["blocking_reason"], reason)

    def test_authorization_feature_branch_non_ancestor_and_missing_commit_blocked(self):
        persist_path, state_path, state = self.recovery_source_files("2026-09-30", "19:30")
        main_sha = self.git("-C", self.repo, "rev-parse", "HEAD")
        self.git("-C", self.repo, "checkout", "-b", "feature-auth")
        self.authorization_manifest(persist_path, state_path, state, "2026-09-30", "19:30", authorization_id="CC-FEATURE")
        self.git("-C", self.repo, "checkout", "main")
        feature_only = bootstrap_recovery_state(source_persist_path=persist_path, source_state_path=state_path,
            trading_date="2026-09-30", cadence="19:30", recovery_authorization_id="CC-FEATURE",
            recovery_source_type="FORMAL_ACCEPTED_RECOVERY_SOURCE",
            repository_root=self.repo, artifacts_root=self.artifacts, workflow_run_id="301", workflow_job_id="401",
            event_name="workflow_dispatch", ref="refs/heads/main", commit_sha=main_sha)
        self.assertEqual(feature_only["blocking_reason"], "RECOVERY_AUTHORIZATION_MANIFEST_REQUIRED")

        self.authorization_manifest(persist_path, state_path, state, "2026-09-30", "19:30", authorization_id="CC-MISSING-COMMIT")
        path = self.repo / "control/recovery_authorizations/CC-MISSING-COMMIT" / AUTHORIZATION_NAME
        payload = json.loads(path.read_text())
        payload["approval_commit_sha"] = "f" * 40
        payload["authorization_blob_sha256"] = _canonical_hash(payload)
        payload["manifest_integrity_hash"] = _canonical_hash(payload)
        atomic_write_json(path, payload)
        missing = bootstrap_recovery_state(source_persist_path=persist_path, source_state_path=state_path,
            trading_date="2026-09-30", cadence="19:30", recovery_authorization_id="CC-MISSING-COMMIT",
            recovery_source_type="FORMAL_ACCEPTED_RECOVERY_SOURCE",
            repository_root=self.repo, artifacts_root=self.artifacts, workflow_run_id="301", workflow_job_id="401",
            event_name="workflow_dispatch", ref="refs/heads/main", commit_sha=self.git("-C", self.repo, "rev-parse", "HEAD"))
        self.assertEqual(missing["blocking_reason"], "RECOVERY_APPROVAL_COMMIT_INVALID")

    def test_authorization_non_ancestor_modified_bytes_and_blob_mismatch_blocked(self):
        persist_path, state_path, state = self.recovery_source_files("2026-09-30", "19:30")
        _, non_ancestor_payload = self.authorization_manifest(persist_path, state_path, state, "2026-09-30", "19:30", authorization_id="CC-NON-ANCESTOR")
        path = self.repo / "control/recovery_authorizations/CC-NON-ANCESTOR" / AUTHORIZATION_NAME
        self.git("-C", self.repo, "checkout", "-b", "side-approval", self.initial_sha)
        atomic_write_json(path, non_ancestor_payload)
        self.git("-C", self.repo, "add", path.relative_to(self.repo).as_posix())
        self.git("-C", self.repo, "commit", "-m", "Side approval")
        side_sha = self.git("-C", self.repo, "rev-parse", "HEAD")
        self.git("-C", self.repo, "checkout", "main")
        payload = json.loads(path.read_text())
        payload["approval_commit_sha"] = side_sha
        payload["authorization_blob_sha256"] = _canonical_hash(payload)
        payload["manifest_integrity_hash"] = _canonical_hash(payload)
        atomic_write_json(path, payload)
        non_ancestor = bootstrap_recovery_state(source_persist_path=persist_path, source_state_path=state_path,
            trading_date="2026-09-30", cadence="19:30", recovery_authorization_id="CC-NON-ANCESTOR",
            recovery_source_type="FORMAL_ACCEPTED_RECOVERY_SOURCE",
            repository_root=self.repo, artifacts_root=self.artifacts, workflow_run_id="301", workflow_job_id="401",
            event_name="workflow_dispatch", ref="refs/heads/main", commit_sha=self.git("-C", self.repo, "rev-parse", "HEAD"))
        self.assertEqual(non_ancestor["blocking_reason"], "RECOVERY_APPROVAL_COMMIT_NOT_MAIN_ANCESTOR")

        self.authorization_manifest(persist_path, state_path, state, "2026-09-30", "19:30", authorization_id="CC-MODIFIED")
        path = self.repo / "control/recovery_authorizations/CC-MODIFIED" / AUTHORIZATION_NAME
        payload = json.loads(path.read_text())
        payload["approved_by"] = "CONTROL_CENTER_REVISED"
        payload["authorization_blob_sha256"] = _canonical_hash(payload)
        payload["manifest_integrity_hash"] = _canonical_hash(payload)
        atomic_write_json(path, payload)
        modified = bootstrap_recovery_state(source_persist_path=persist_path, source_state_path=state_path,
            trading_date="2026-09-30", cadence="19:30", recovery_authorization_id="CC-MODIFIED",
            recovery_source_type="FORMAL_ACCEPTED_RECOVERY_SOURCE",
            repository_root=self.repo, artifacts_root=self.artifacts, workflow_run_id="301", workflow_job_id="401",
            event_name="workflow_dispatch", ref="refs/heads/main", commit_sha=self.git("-C", self.repo, "rev-parse", "HEAD"))
        self.assertEqual(modified["blocking_reason"], "RECOVERY_AUTHORIZATION_BYTES_CHANGED_AFTER_APPROVAL")

        self.authorization_manifest(persist_path, state_path, state, "2026-09-30", "19:30", authorization_id="CC-BLOB")
        path = self.repo / "control/recovery_authorizations/CC-BLOB" / AUTHORIZATION_NAME
        payload = json.loads(path.read_text())
        payload["authorization_blob_sha256"] = "0" * 64
        payload["manifest_integrity_hash"] = _canonical_hash(payload)
        atomic_write_json(path, payload)
        blob = bootstrap_recovery_state(source_persist_path=persist_path, source_state_path=state_path,
            trading_date="2026-09-30", cadence="19:30", recovery_authorization_id="CC-BLOB",
            recovery_source_type="FORMAL_ACCEPTED_RECOVERY_SOURCE",
            repository_root=self.repo, artifacts_root=self.artifacts, workflow_run_id="301", workflow_job_id="401",
            event_name="workflow_dispatch", ref="refs/heads/main", commit_sha=self.git("-C", self.repo, "rev-parse", "HEAD"))
        self.assertEqual(blob["blocking_reason"], "RECOVERY_AUTHORIZATION_BLOB_HASH_MISMATCH")

    def test_tampered_authorization_manifest_fails_closed(self):
        persist_path, state_path, state = self.recovery_source_files("2026-09-30", "19:30")
        auth_path, _ = self.authorization_manifest(persist_path, state_path, state, "2026-09-30", "19:30")
        payload = json.loads(auth_path.read_text())
        payload["approved_by"] = "LOCAL"
        atomic_write_json(auth_path, payload)
        out = bootstrap_recovery_state(source_persist_path=persist_path, source_state_path=state_path,
            trading_date="2026-09-30", cadence="19:30", recovery_authorization_id="CC-RATE-SOAK-005",
            recovery_source_type="FORMAL_ACCEPTED_RECOVERY_SOURCE",
            repository_root=self.repo, artifacts_root=self.artifacts, workflow_run_id="301", workflow_job_id="401",
            event_name="workflow_dispatch", ref="refs/heads/main", commit_sha=self.git("-C", self.repo, "rev-parse", "HEAD"))
        self.assertEqual(out["blocking_reason"], "RECOVERY_AUTHORIZATION_MANIFEST_TAMPERED")

    def test_single_use_authorization_reuse_blocked(self):
        first, _ = self.bootstrap_recovery("2026-09-30", "19:30")
        self.assertEqual(first["validation_status"], "PASS", first)
        second, _ = self.bootstrap_recovery("2026-09-30", "19:30")
        self.assertEqual(second["blocking_reason"], "RECOVERY_AUTHORIZATION_ALREADY_CONSUMED")

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
        self.assertNotIn("authorization_manifest_path", recovery)
        self.assertNotIn("--authorization-manifest", recovery)
        self.assertNotIn("control/recovery_authorizations", recovery)


if __name__ == "__main__":
    unittest.main()
