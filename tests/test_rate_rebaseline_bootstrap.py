import copy
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.bootstrap_production_rebaseline_state import (
    APPROVED_MATERIAL_ROOT,
    AUTHORIZATION_NAME,
    CONSUMPTION_NAME,
    _canonical_hash,
    bootstrap_rebaseline_state,
)
from src.cer074_acceptance import atomic_write_json, sha256, strip_runtime
from src.production_live_state import (
    ARTIFACTS,
    CADENCE_DIR,
    MANIFEST_NAME,
    PERSIST_NAME,
    STATE_NAME,
    file_hash,
    load_live_state,
    validate_material,
    validate_rebaseline_material,
    validate_recovery_source_material,
)


class RateRebaselineBootstrapTests(unittest.TestCase):
    baseline_id = "rate-rebaseline-20261002-0730-cc-approved-v1"

    def setUp(self):
        tmp_root = Path.cwd() / ".tmp" / "rate-rebaseline-tests"
        tmp_root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="rate-rebaseline-test-", dir=tmp_root)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.artifacts = self.root / "artifacts"
        self.material_root = self.repo / APPROVED_MATERIAL_ROOT / self.baseline_id
        self.git("init", self.repo)
        self.git("-C", self.repo, "checkout", "-b", "main")
        self.git("-C", self.repo, "config", "user.email", "rate-test@example.invalid")
        self.git("-C", self.repo, "config", "user.name", "RATE Test")
        atomic_write_json(self.repo / "README.json", {"test_repository": True})
        self.git("-C", self.repo, "add", "README.json")
        self.git("-C", self.repo, "commit", "-m", "Initial main")
        self.day = "2026-10-02"
        self.cadence = "07:30"
        self.authorization_id = "CC-RATE-REBASELINE-001"
        self.paths = self.write_material()
        self.authorization_manifest()

    def git(self, *args):
        result = subprocess.run(["git", *map(str, args)], cwd=self.root, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def rel(self, path):
        return Path(path).relative_to(self.repo).as_posix()

    def source_bundle(self):
        provenance = {
            "future_dated": False,
            "stale": False,
            "fixture": False,
            "staging": False,
            "local_cache": False,
            "synthetic": False,
            "recovery": False,
            "historical_acceptance_fallback": "FORBIDDEN",
        }
        return {
            "artifact": "RATE_PRODUCTION_SOURCE_BUNDLE",
            "validation_status": "PASS",
            "trading_date": self.day,
            "cadence": self.cadence,
            "freshness": "PASS",
            "completeness": "PASS",
            "coverage": "30/30",
            "decision_record_coverage": {"actual": 30, "required": 30, "coverage": "30/30", "status": "PASS"},
            "decision_records": [{"rank": idx + 1, "symbol": f"233{idx % 10}"} for idx in range(30)],
            "source_snapshot_id": "twse-prod-snapshot-20261002-0730",
            "input_snapshot_ids": ["twse-ohlcv-20261002", "twse-fundamental-20261002", "twse-institutional-20261002"],
            "source_provenance": provenance,
            "production_data_validation": {"freshness": "PASS", "completeness": "PASS"},
        }

    def portfolio_material(self):
        roy = {
            "source_type": "CONTROL_CENTER_APPROVED_ROY_PORTFOLIO_OPENING_STATE",
            "opening_state_type": "CONTROL_CENTER_REBASELINE_OPENING_STATE",
            "currency": "TWD",
            "positions_count": 10,
            "positions": [
                {"symbol": "00632R", "security_name": "元大台灣50反1", "quantity": 5000, "average_cost": 10.04, "currency": "TWD"},
                {"symbol": "00673R", "security_name": "期元大 S&P 原油反1", "quantity": 39750, "average_cost": 28.25, "currency": "TWD"},
                {"symbol": "2330", "security_name": "台積電", "quantity": 40, "average_cost": 867.72, "currency": "TWD"},
                {"symbol": "2337", "security_name": "旺宏", "quantity": 1500, "average_cost": 172.81, "currency": "TWD"},
                {"symbol": "2383", "security_name": "台光電", "quantity": 20, "average_cost": 1581.35, "currency": "TWD"},
                {"symbol": "2412", "security_name": "中華電", "quantity": 1000, "average_cost": 118.60, "currency": "TWD"},
                {"symbol": "3231", "security_name": "緯創", "quantity": 1000, "average_cost": 199.17, "currency": "TWD"},
                {"symbol": "6139", "security_name": "亞翔", "quantity": 20, "average_cost": 773.65, "currency": "TWD"},
                {"symbol": "6278", "security_name": "台表科", "quantity": 50, "average_cost": 219.18, "currency": "TWD"},
                {"symbol": "6442", "security_name": "光聖", "quantity": 70, "average_cost": 1851.56, "currency": "TWD"},
            ],
            "totals": {
                "cash": 179523,
                "opening_nav": 1509636,
                "stock_market_value": 1330113,
                "stock_total_cost": 1972438,
            },
        }
        ai = {
            "source_type": "AI_PAPER_PORTFOLIO_REBASELINE_OPENING_STATE",
            "opening_state_type": "CONTROL_CENTER_REBASELINE_OPENING_STATE",
            "opening_capital": 1000000,
            "positions": [],
            "cash": 1000000,
            "nav": 1000000,
            "currency": "TWD",
            "historical_pnl_carried_forward": False,
            "historical_transactions_carried_forward": False,
            "historical_recovery": False,
        }
        ledger = {
            "event_type": "REBASELINE_OPENING_BALANCE",
            "pre_rebaseline_transaction_history": "UNAVAILABLE",
            "historical_transaction_reconstruction": "PROHIBITED",
            "ledger_continuity_mode": "POST_REBASELINE_ONLY",
            "historical_recovery_status": "HISTORICAL_RECOVERY_SOURCE_IRRECOVERABLE",
            "historical_terminal_reference": {
                "trading_date": "2026-09-18",
                "cadence": "19:30",
                "state_id": "rate-state-656e460995324fb4a3eb7b30",
                "state_hash": "656e460995324fb4a3eb7b3033b754752997c8cb761d414083a2148eb150b5c7",
            },
            "roy_portfolio_reference": "CONTROL_CENTER_REBASELINE_ROY_OPENING_STATE.json",
            "ai_paper_portfolio_reference": "CONTROL_CENTER_REBASELINE_AI_OPENING_STATE.json",
        }
        return roy, ai, ledger

    def decision(self, source_bundle_hash, source_bundle, roy, ai, ledger):
        return {
            "baseline_id": self.baseline_id,
            "baseline_type": "CONTROL_CENTER_REBASELINE",
            "baseline_version": "V1",
            "trading_date": self.day,
            "cadence": self.cadence,
            "execution_scope": "PRODUCTION",
            "previous_state_resolution": "CONTROL_CENTER_REBASELINE",
            "historical_chain_break_acknowledged": True,
            "historical_account_state_recoverable": False,
            "production_source_bundle_sha256": source_bundle_hash,
            "production_evidence_state": {
                "validation_status": "PASS",
                "trading_date": self.day,
                "cadence": self.cadence,
                "freshness": "PASS",
                "completeness": "PASS",
                "coverage": "30/30",
                "source_snapshot_id": source_bundle["source_snapshot_id"],
                "input_snapshot_ids": source_bundle["input_snapshot_ids"],
                "source_provenance": source_bundle["source_provenance"],
                "fixture_fallback": "FORBIDDEN",
                "stale_snapshot_fallback": "FORBIDDEN",
                "synthetic_fallback": "FORBIDDEN",
                "recovery_fallback": "FORBIDDEN",
                "historical_acceptance_bundle_fallback": "FORBIDDEN",
            },
            "roy_portfolio": copy.deepcopy(roy),
            "ai_paper_portfolio": copy.deepcopy(ai),
            "transaction_ledger": copy.deepcopy(ledger),
            "historical_predecessor_reference": ledger["historical_terminal_reference"],
        }

    def write_material(self, mutate=None, mutate_phase="source"):
        self.material_root.mkdir(parents=True, exist_ok=True)
        source_bundle = self.source_bundle()
        roy, ai, ledger = self.portfolio_material()
        context = {"source_bundle": source_bundle, "roy": roy, "ai": ai, "ledger": ledger}
        if mutate and mutate_phase == "source":
            mutate(context)
        paths = {
            "source_bundle": self.material_root / "RATE_PRODUCTION_SOURCE_BUNDLE.json",
            "roy": self.material_root / "CONTROL_CENTER_REBASELINE_ROY_OPENING_STATE.json",
            "ai": self.material_root / "CONTROL_CENTER_REBASELINE_AI_OPENING_STATE.json",
            "ledger": self.material_root / "RATE_LEDGER_REBASELINE_BOUNDARY.json",
            "state": self.material_root / "RATE_PRODUCTION_REBASELINE_DECISION_STATE.json",
            "manifest": self.material_root / "RATE_PRODUCTION_REBASELINE_MANIFEST.json",
        }
        atomic_write_json(paths["source_bundle"], source_bundle)
        source_hash = file_hash(paths["source_bundle"])
        decision = self.decision(source_hash, source_bundle, roy, ai, ledger)
        context["decision"] = decision
        if mutate and mutate_phase == "decision":
            mutate(context)
        digest = sha256(strip_runtime(decision))
        state_id = "rate-state-" + digest[:24]
        rebaseline_state = {
            "artifact": "RATE_PRODUCTION_REBASELINE_DECISION_STATE",
            "validation_status": "PASS",
            "baseline_id": self.baseline_id,
            "state_id": state_id,
            "state_hash": digest,
            "decision": decision,
        }
        context["rebaseline_state"] = rebaseline_state
        if mutate and mutate_phase == "rebaseline_state":
            mutate(context)
        if mutate and mutate_phase == "material":
            mutate(context)
        for key, obj in (("roy", {"artifact": "CONTROL_CENTER_REBASELINE_ROY_OPENING_STATE", **roy}),
                         ("ai", {"artifact": "CONTROL_CENTER_REBASELINE_AI_OPENING_STATE", **ai}),
                         ("ledger", {"artifact": "RATE_LEDGER_REBASELINE_BOUNDARY", **ledger}),
                         ("state", rebaseline_state)):
            atomic_write_json(paths[key], obj)
        manifest = {
            "artifact": "RATE_PRODUCTION_REBASELINE_MANIFEST",
            "validation_status": "PASS",
            "baseline_type": "CONTROL_CENTER_REBASELINE",
            "baseline_id": self.baseline_id,
            "selected_trading_date": self.day,
            "selected_cadence": self.cadence,
            "state_id": state_id,
            "state_hash": digest,
            "files": {
                "RATE_PRODUCTION_SOURCE_BUNDLE.json": file_hash(paths["source_bundle"]),
                "CONTROL_CENTER_REBASELINE_ROY_OPENING_STATE.json": file_hash(paths["roy"]),
                "CONTROL_CENTER_REBASELINE_AI_OPENING_STATE.json": file_hash(paths["ai"]),
                "RATE_LEDGER_REBASELINE_BOUNDARY.json": file_hash(paths["ledger"]),
                "RATE_PRODUCTION_REBASELINE_DECISION_STATE.json": file_hash(paths["state"]),
            },
        }
        context["manifest"] = manifest
        if mutate and mutate_phase == "manifest":
            mutate(context)
        atomic_write_json(paths["manifest"], manifest)
        paths["state_id"] = state_id
        paths["state_hash"] = digest
        return paths

    def authorization_manifest(self, **overrides):
        payload = {
            "artifact": "RATE_PRODUCTION_REBASELINE_AUTHORIZATION_MANIFEST",
            "authorization_id": self.authorization_id,
            "authorization_status": "APPROVED",
            "approved_by": "CONTROL_CENTER",
            "baseline_type": "CONTROL_CENTER_REBASELINE",
            "previous_state_resolution": "CONTROL_CENTER_REBASELINE",
            "baseline_id": self.baseline_id,
            "trading_date": self.day,
            "cadence": self.cadence,
            "production_source_bundle_sha256": file_hash(self.paths["source_bundle"]),
            "roy_opening_state_sha256": file_hash(self.paths["roy"]),
            "ai_opening_state_sha256": file_hash(self.paths["ai"]),
            "ledger_boundary_sha256": file_hash(self.paths["ledger"]),
            "canonical_rebaseline_state_sha256": file_hash(self.paths["state"]),
            "expected_state_id": self.paths["state_id"],
            "expected_state_hash": self.paths["state_hash"],
            "single_use": True,
            "acceptance_counter_reset": False,
            "post_rebaseline_continuity_window": "NEW",
            "approval_commit_sha": "0" * 40,
        }
        payload.update(overrides)
        payload["authorization_blob_sha256"] = _canonical_hash(payload)
        payload["manifest_integrity_hash"] = _canonical_hash(payload)
        path = self.repo / "control" / "rebaseline_authorizations" / self.authorization_id / AUTHORIZATION_NAME
        atomic_write_json(path, payload)
        rel = path.relative_to(self.repo).as_posix()
        self.git("-C", self.repo, "add", rel)
        self.git("-C", self.repo, "commit", "-m", "Approve rebaseline")
        approval = self.git("-C", self.repo, "rev-parse", "HEAD")
        payload["approval_commit_sha"] = approval
        payload["authorization_blob_sha256"] = _canonical_hash(payload)
        payload["manifest_integrity_hash"] = _canonical_hash(payload)
        atomic_write_json(path, payload)
        self.git("-C", self.repo, "add", rel)
        self.git("-C", self.repo, "commit", "-m", "Bind approval commit")
        return path, payload

    def bootstrap(self, **overrides):
        args = dict(
            rebaseline_manifest_path=self.rel(self.paths["manifest"]),
            rebaseline_state_path=self.rel(self.paths["state"]),
            source_bundle_path=self.rel(self.paths["source_bundle"]),
            roy_opening_state_path=self.rel(self.paths["roy"]),
            ai_opening_state_path=self.rel(self.paths["ai"]),
            ledger_boundary_path=self.rel(self.paths["ledger"]),
            trading_date=self.day,
            cadence=self.cadence,
            rebaseline_authorization_id=self.authorization_id,
            repository_root=self.repo,
            artifacts_root=self.artifacts,
            workflow_run_id="701",
            workflow_job_id="801",
            event_name="workflow_dispatch",
            ref="refs/heads/main",
            commit_sha=self.git("-C", self.repo, "rev-parse", "HEAD"),
            evidence_output=self.artifacts / "production_state/RATE_PRODUCTION_REBASELINE_BOOTSTRAP_EVIDENCE.json",
        )
        args.update(overrides)
        return bootstrap_rebaseline_state(**args)

    def assert_blocked(self, reason, **overrides):
        out = self.bootstrap(**overrides)
        self.assertEqual(out["validation_status"], "BLOCKED", out)
        self.assertEqual(out["blocking_reason"], reason, out)

    def publish_live_without_latest(self):
        out = self.bootstrap(simulate_crash_at="after_live_promotion_before_latest")
        self.assertEqual(out["validation_status"], "BLOCKED", out)
        self.assertEqual(out["blocking_reason"], "LIVE_SLOT_PUBLISHED_LATEST_UPDATE_FAILED")
        return self.artifacts / "production_state/live" / self.day / CADENCE_DIR[self.cadence]

    def write_latest(self, **overrides):
        latest = {
            "artifact": "RATE_PRODUCTION_STATE_LATEST",
            "validation_status": "PASS",
            "trading_date": self.day,
            "cadence": self.cadence,
            "current_state_id": self.paths["state_id"],
            "current_state_hash": self.paths["state_hash"],
            "baseline_id": self.baseline_id,
            "baseline_type": "CONTROL_CENTER_REBASELINE",
            "rebaseline_bootstrap": True,
            "rebaseline_authorization_id": self.authorization_id,
        }
        latest.update(overrides)
        path = self.artifacts / "RATE_PRODUCTION_STATE_LATEST.json"
        atomic_write_json(path, latest)
        return path

    def write_scheduled_live_slot(self, trading_date, cadence, previous_state_id=None, previous_state_hash=None):
        decision = {
            "trading_date": trading_date,
            "cadence": cadence,
            "execution_scope": "PRODUCTION",
            "previous_state_resolution": "PERSISTED_PRODUCTION_STATE",
            "previous_state_id": previous_state_id or self.paths["state_id"],
            "previous_state_hash": previous_state_hash or self.paths["state_hash"],
            "roy_portfolio": {"positions": [], "cash": 1},
            "ai_paper_portfolio": {"positions": [], "cash": 1, "reset": False},
            "transaction_ledger": {"transactions": [{"id": f"{trading_date}-{cadence}"}], "reset": False},
        }
        digest = sha256(strip_runtime(decision))
        state_id = "rate-state-" + digest[:24]
        entry = {
            "current_state_id": state_id,
            "decision_payload_hash": digest,
            "trading_date": trading_date,
            "cadence": cadence,
            "execution_scope": "PRODUCTION",
            "previous_state_resolution": "PERSISTED_PRODUCTION_STATE",
            "previous_state_id": decision["previous_state_id"],
        }
        directory = self.artifacts / "production_state/live" / trading_date / CADENCE_DIR[cadence]
        persist = {"artifact": ARTIFACTS[cadence], "validation_status": "PASS",
                   "current_state_id": state_id, "current_state_hash": digest,
                   "previous_state_id": decision["previous_state_id"],
                   "persist_result": {"status": "PERSISTED", "state_entry": entry}}
        material = {"artifact": "RATE_PRODUCTION_DECISION_STATE", "validation_status": "PASS",
                    "state_entry": entry,
                    "decision_state": {"current_state_id": state_id, "decision_payload_hash": digest,
                                       "previous_state_id": decision["previous_state_id"],
                                       "state_entry": entry, "decision": decision}}
        atomic_write_json(directory / PERSIST_NAME, persist)
        atomic_write_json(directory / STATE_NAME, material)
        manifest = {"artifact": "RATE_PRODUCTION_STATE_MANIFEST", "validation_status": "PASS",
                    "trading_date": trading_date, "cadence": cadence, "event_name": "schedule",
                    "ref": "refs/heads/main", "commit_sha": "a" * 40, "workflow_run_id": "1",
                    "workflow_job_id": "2", "current_state_id": state_id, "current_state_hash": digest,
                    "files": {PERSIST_NAME: file_hash(directory / PERSIST_NAME),
                              STATE_NAME: file_hash(directory / STATE_NAME)}}
        atomic_write_json(directory / MANIFEST_NAME, manifest)
        self.write_latest(trading_date=trading_date, cadence=cadence, current_state_id=state_id,
                          current_state_hash=digest, baseline_type=None, rebaseline_bootstrap=False,
                          previous_state_resolution="PERSISTED_PRODUCTION_STATE",
                          rebaseline_authorization_id=None)
        return state_id, digest, file_hash(self.artifacts / "RATE_PRODUCTION_STATE_LATEST.json")

    def test_valid_control_center_rebaseline_bootstrap_writes_atomic_canonical_package_and_consumes_once(self):
        out = self.bootstrap()
        self.assertEqual(out["validation_status"], "PASS", out)
        directory = self.artifacts / "production_state/live" / self.day / CADENCE_DIR[self.cadence]
        for name in (PERSIST_NAME, STATE_NAME, MANIFEST_NAME, CONSUMPTION_NAME):
            self.assertTrue((directory / name).is_file(), name)
        manifest = json.loads((directory / MANIFEST_NAME).read_text(encoding="utf-8"))
        self.assertEqual(manifest["baseline_id"], self.baseline_id)
        self.assertEqual(manifest["baseline_state_id"], self.paths["state_id"])
        self.assertEqual(manifest["baseline_state_hash"], self.paths["state_hash"])
        self.assertEqual(manifest["files"][CONSUMPTION_NAME], file_hash(directory / CONSUMPTION_NAME))
        consumed = json.loads((directory / CONSUMPTION_NAME).read_text(encoding="utf-8"))
        self.assertEqual(consumed["authorization_id"], self.authorization_id)
        self.assertEqual(consumed["baseline_id"], self.baseline_id)
        latest = json.loads((self.artifacts / "RATE_PRODUCTION_STATE_LATEST.json").read_text(encoding="utf-8"))
        self.assertEqual(latest["baseline_id"], self.baseline_id)
        self.assertEqual(latest["current_state_id"], self.paths["state_id"])
        loaded = load_live_state(self.artifacts / "production_state", self.day, self.cadence)
        self.assertEqual(loaded["state"]["current_state_id"], self.paths["state_id"])
        second = self.bootstrap()
        self.assertEqual(second["blocking_reason"], "REBASELINE_AUTHORIZATION_ALREADY_CONSUMED")

    def test_unauthorized_schedule_non_main_and_missing_authorization_blocked(self):
        self.assert_blocked("REBASELINE_BOOTSTRAP_AUTHORIZATION_REQUIRED", event_name="schedule")
        self.assert_blocked("REBASELINE_BOOTSTRAP_AUTHORIZATION_REQUIRED", ref="refs/heads/feature")
        self.assert_blocked("REBASELINE_AUTHORIZATION_MANIFEST_REQUIRED", rebaseline_authorization_id="CC-MISSING")

    def test_authorization_integrity_blocks_changed_bytes_wrong_commit_wrong_baseline_and_material_hash(self):
        self.authorization_manifest(baseline_id="wrong-baseline")
        self.assert_blocked("REBASELINE_BASELINE_ID_MISMATCH")
        self.authorization_manifest(production_source_bundle_sha256="0" * 64)
        self.assert_blocked("REBASELINE_PRODUCTION_BUNDLE_HASH_MISMATCH")
        self.authorization_manifest(expected_state_hash="0" * 64)
        self.assert_blocked("REBASELINE_MATERIAL_STATE_HASH_MISMATCH")
        path = self.repo / "control" / "rebaseline_authorizations" / self.authorization_id / AUTHORIZATION_NAME
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["approved_by"] = "LOCAL"
        atomic_write_json(path, payload)
        self.assert_blocked("REBASELINE_AUTHORIZATION_MANIFEST_TAMPERED")
        self.authorization_manifest()
        path = self.repo / "control" / "rebaseline_authorizations" / self.authorization_id / AUTHORIZATION_NAME
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["approval_commit_sha"] = "f" * 40
        payload["authorization_blob_sha256"] = _canonical_hash(payload)
        payload["manifest_integrity_hash"] = _canonical_hash(payload)
        atomic_write_json(path, payload)
        self.assert_blocked("REBASELINE_APPROVAL_COMMIT_INVALID")

    def test_production_source_bundle_strict_binding_blocks_wrong_date_cadence_stale_incomplete_and_29_of_30(self):
        cases = [
            ("REBASELINE_PRODUCTION_SOURCE_BINDING_MISMATCH", "source", lambda m: m["source_bundle"].update(trading_date="2026-10-03")),
            ("REBASELINE_PRODUCTION_SOURCE_BINDING_MISMATCH", "source", lambda m: m["source_bundle"].update(cadence="09:30")),
            ("REBASELINE_PRODUCTION_SOURCE_BINDING_MISMATCH", "source", lambda m: m["source_bundle"].update(freshness="FAIL")),
            ("REBASELINE_PRODUCTION_SOURCE_BINDING_MISMATCH", "source", lambda m: m["source_bundle"].update(completeness="FAIL")),
            ("REBASELINE_PRODUCTION_SOURCE_BINDING_MISMATCH", "source", lambda m: m["source_bundle"].update(coverage="29/30")),
            ("REBASELINE_PRODUCTION_SOURCE_BINDING_MISMATCH", "source", lambda m: m["source_bundle"]["decision_records"].pop()),
            ("REBASELINE_PRODUCTION_SOURCE_BINDING_MISMATCH", "source", lambda m: m["source_bundle"]["source_provenance"].update(stale=True)),
            ("REBASELINE_PRODUCTION_SOURCE_BINDING_MISMATCH", "source", lambda m: m["source_bundle"].update(input_snapshot_ids=[])),
        ]
        for reason, phase, mutate in cases:
            with self.subTest(reason=reason, phase=phase, mutate=mutate):
                self.paths = self.write_material(mutate=mutate, mutate_phase=phase)
                self.authorization_manifest()
                self.assert_blocked(reason)

    def test_embedded_source_roy_ai_ledger_and_baseline_cross_binding_mismatches_blocked(self):
        cases = [
            ("REBASELINE_PRODUCTION_EVIDENCE_BINDING_MISMATCH",
             "decision", lambda m: m["decision"].update(production_source_bundle_sha256="0" * 64)),
            ("REBASELINE_PRODUCTION_EVIDENCE_BINDING_MISMATCH",
             "decision", lambda m: m["decision"]["production_evidence_state"].update(source_snapshot_id="wrong")),
            ("REBASELINE_ROY_STATE_BINDING_MISMATCH",
             "decision", lambda m: m["decision"]["roy_portfolio"]["positions"][0].update(quantity=999)),
            ("REBASELINE_ROY_STATE_BINDING_MISMATCH",
             "material", lambda m: m["roy"]["totals"].pop("stock_total_cost")),
            ("REBASELINE_AI_STATE_BINDING_MISMATCH",
             "decision", lambda m: m["decision"]["ai_paper_portfolio"].update(cash=999999)),
            ("REBASELINE_AI_STATE_BINDING_MISMATCH",
             "material", lambda m: m["ai"].update(positions=[{"symbol": "2330"}])),
            ("REBASELINE_LEDGER_BINDING_MISMATCH",
             "decision", lambda m: m["decision"]["transaction_ledger"].update(ledger_continuity_mode="HISTORICAL")),
            ("REBASELINE_LEDGER_BINDING_MISMATCH",
             "material", lambda m: m["ledger"].update(transactions=[{"id": "synthetic"}])),
            ("REBASELINE_BASELINE_ID_MISMATCH",
             "decision", lambda m: m["decision"].update(baseline_id="wrong-baseline")),
            ("REBASELINE_BASELINE_ID_MISMATCH",
             "manifest", lambda m: m["manifest"].update(baseline_id="wrong-baseline")),
            ("REBASELINE_MATERIAL_STATE_HASH_MISMATCH",
             "rebaseline_state", lambda m: m["rebaseline_state"].update(state_hash="0" * 64)),
        ]
        for reason, phase, mutate in cases:
            with self.subTest(reason=reason, phase=phase, mutate=mutate):
                self.paths = self.write_material(mutate=mutate, mutate_phase=phase)
                self.authorization_manifest()
                self.assert_blocked(reason)

    def test_material_paths_must_stay_inside_approved_namespace_without_absolute_traversal_or_symlink_escape(self):
        self.assert_blocked("REBASELINE_MATERIAL_PATH_INVALID", source_bundle_path="../outside.json")
        self.assert_blocked("REBASELINE_MATERIAL_PATH_INVALID", source_bundle_path=str(self.paths["source_bundle"]))
        bad = self.repo / "artifacts" / "production_state" / "RATE_PRODUCTION_SOURCE_BUNDLE.json"
        atomic_write_json(bad, json.loads(self.paths["source_bundle"].read_text(encoding="utf-8")))
        self.assert_blocked("REBASELINE_MATERIAL_PATH_INVALID", source_bundle_path=bad.relative_to(self.repo).as_posix())
        external = self.root / "external.json"
        atomic_write_json(external, json.loads(self.paths["source_bundle"].read_text(encoding="utf-8")))
        link = self.material_root / "RATE_PRODUCTION_SOURCE_BUNDLE_LINK.json"
        try:
            os.symlink(external, link)
        except (OSError, NotImplementedError):
            self.skipTest("symlink creation unavailable on this platform")
        self.assert_blocked("REBASELINE_MATERIAL_PATH_INVALID", source_bundle_path=link.relative_to(self.repo).as_posix())

    def test_crash_safe_staging_promotion_latest_and_idempotent_repair(self):
        for crash in ("after_one_staged_file", "staging_hash_mismatch", "before_atomic_promotion"):
            with self.subTest(crash=crash):
                out = self.bootstrap(simulate_crash_at=crash)
                self.assertEqual(out["validation_status"], "BLOCKED", out)
                live_dir = self.artifacts / "production_state/live" / self.day / CADENCE_DIR[self.cadence]
                self.assertFalse(live_dir.exists(), crash)
                self.assertFalse((self.artifacts / "RATE_PRODUCTION_STATE_LATEST.json").exists(), crash)
                if self.artifacts.exists():
                    for child in self.artifacts.iterdir():
                        if child.is_dir():
                            import shutil
                            shutil.rmtree(child)
                        else:
                            child.unlink()
        out = self.bootstrap(simulate_crash_at="after_live_promotion_before_latest")
        self.assertEqual(out["validation_status"], "BLOCKED", out)
        self.assertEqual(out["blocking_reason"], "LIVE_SLOT_PUBLISHED_LATEST_UPDATE_FAILED")
        live_dir = self.artifacts / "production_state/live" / self.day / CADENCE_DIR[self.cadence]
        self.assertTrue((live_dir / CONSUMPTION_NAME).is_file())
        self.assertFalse((self.artifacts / "RATE_PRODUCTION_STATE_LATEST.json").exists())
        repaired = self.bootstrap()
        self.assertEqual(repaired["validation_status"], "PASS", repaired)
        self.assertIs(repaired["idempotent_latest_repair"], True)
        self.assertTrue((self.artifacts / "RATE_PRODUCTION_STATE_LATEST.json").is_file())

    def test_latest_repair_allowed_only_for_missing_older_or_pending_without_newer_canonical_state(self):
        self.publish_live_without_latest()
        repaired = self.bootstrap()
        self.assertEqual(repaired["validation_status"], "PASS", repaired)
        self.assertEqual(repaired["latest_repair_eligibility"], "REBASELINE_LATEST_REPAIR_ELIGIBLE")
        exact = self.bootstrap()
        self.assertEqual(exact["validation_status"], "BLOCKED", exact)
        self.assertEqual(exact["blocking_reason"], "REBASELINE_AUTHORIZATION_ALREADY_CONSUMED")

        self.artifacts.mkdir(exist_ok=True)
        import shutil
        shutil.rmtree(self.artifacts / "production_state")
        self.publish_live_without_latest()
        self.write_latest(trading_date="2026-10-01", cadence="19:30",
                          current_state_id="rate-state-older", current_state_hash="1" * 64,
                          baseline_id="older-baseline", rebaseline_authorization_id="CC-OLDER",
                          rebaseline_bootstrap=False,
                          previous_state_resolution="PERSISTED_PRODUCTION_STATE")
        repaired = self.bootstrap()
        self.assertEqual(repaired["validation_status"], "PASS", repaired)

        shutil.rmtree(self.artifacts / "production_state")
        self.publish_live_without_latest()
        self.write_latest(validation_status="BLOCKED", latest_update_status="PENDING",
                          current_state_id=None, current_state_hash=None)
        repaired = self.bootstrap()
        self.assertEqual(repaired["validation_status"], "PASS", repaired)

    def test_latest_monotonic_guard_blocks_newer_scheduled_states_without_rewriting_latest(self):
        cases = [("09:30", self.day), ("12:00", self.day), ("07:30", "2026-10-03")]
        for cadence, trading_date in cases:
            with self.subTest(cadence=cadence, trading_date=trading_date):
                self.publish_live_without_latest()
                _state_id, _state_hash, before_hash = self.write_scheduled_live_slot(trading_date, cadence)
                out = self.bootstrap()
                self.assertEqual(out["validation_status"], "BLOCKED", out)
                self.assertEqual(out["blocking_reason"], "REBASELINE_LATEST_ALREADY_ADVANCED", out)
                self.assertEqual(file_hash(self.artifacts / "RATE_PRODUCTION_STATE_LATEST.json"), before_hash)
                import shutil
                shutil.rmtree(self.artifacts / "production_state")
                latest = self.artifacts / "RATE_PRODUCTION_STATE_LATEST.json"
                if latest.exists():
                    latest.unlink()

    def test_latest_conflicting_same_slot_blocks_and_newer_live_prevents_older_latest_repair(self):
        self.publish_live_without_latest()
        self.write_latest(current_state_id="rate-state-conflict", current_state_hash="2" * 64)
        out = self.bootstrap()
        self.assertEqual(out["validation_status"], "BLOCKED", out)
        self.assertEqual(out["blocking_reason"], "REBASELINE_LATEST_CONFLICT")

        import shutil
        shutil.rmtree(self.artifacts / "production_state")
        self.publish_live_without_latest()
        self.write_scheduled_live_slot(self.day, "09:30")
        self.write_latest(trading_date="2026-10-01", cadence="19:30",
                          current_state_id="rate-state-older", current_state_hash="1" * 64,
                          baseline_id="older-baseline", rebaseline_authorization_id="CC-OLDER")
        out = self.bootstrap()
        self.assertEqual(out["validation_status"], "BLOCKED", out)
        self.assertEqual(out["blocking_reason"], "REBASELINE_LATEST_ALREADY_ADVANCED")

    def test_next_scheduled_state_can_resolve_rebaseline_then_continue_as_persisted_without_rebaseline_propagation(self):
        out = self.bootstrap()
        self.assertEqual(out["validation_status"], "PASS", out)
        previous = load_live_state(self.artifacts / "production_state", self.day, self.cadence)
        next_decision = copy.deepcopy(previous["state"]["decision"])
        next_decision.update({
            "baseline_type": "POST_REBASELINE_CONTINUITY",
            "previous_state_resolution": "PERSISTED_PRODUCTION_STATE",
            "previous_state_id": previous["state"]["current_state_id"],
            "previous_state_hash": previous["state"]["decision_payload_hash"],
            "historical_chain_break_acknowledged": False,
            "historical_account_state_recoverable": True,
            "cadence": "09:30",
        })
        next_decision.pop("production_source_bundle_sha256", None)
        next_decision["transaction_ledger"] = {"transactions": [
            {"id": "post-rebaseline-open", "event_type": "CONTINUITY_OPEN", "previous_state_id": previous["state"]["current_state_id"]}
        ], "reset": False}
        digest = sha256(strip_runtime(next_decision))
        state_id = "rate-state-" + digest[:24]
        entry = {"current_state_id": state_id, "decision_payload_hash": digest, "trading_date": self.day,
                 "cadence": "09:30", "execution_scope": "PRODUCTION",
                 "previous_state_resolution": "PERSISTED_PRODUCTION_STATE",
                 "previous_state_id": previous["state"]["current_state_id"],
                 "previous_state_hash": previous["state"]["decision_payload_hash"]}
        persist = {"artifact": ARTIFACTS["09:30"], "validation_status": "PASS",
                   "current_state_id": state_id, "current_state_hash": digest,
                   "previous_state_id": previous["state"]["current_state_id"],
                   "persist_result": {"status": "PERSISTED", "state_entry": entry}}
        material = {"artifact": "RATE_PRODUCTION_DECISION_STATE", "validation_status": "PASS",
                    "state_entry": entry,
                    "decision_state": {"current_state_id": state_id, "decision_payload_hash": digest,
                                       "previous_state_id": previous["state"]["current_state_id"],
                                       "state_entry": entry, "decision": next_decision}}
        self.assertEqual(validate_material(persist, material, self.day, "09:30")["current_state_id"], state_id)

    def test_normal_validate_material_and_recovery_validator_remain_strictly_isolated(self):
        out = self.bootstrap()
        self.assertEqual(out["validation_status"], "PASS", out)
        directory = self.artifacts / "production_state/live" / self.day / CADENCE_DIR[self.cadence]
        persist = json.loads((directory / PERSIST_NAME).read_text(encoding="utf-8"))
        material = json.loads((directory / STATE_NAME).read_text(encoding="utf-8"))
        self.assertEqual(validate_rebaseline_material(persist, material, self.day, self.cadence)["current_state_id"],
                         self.paths["state_id"])
        with self.assertRaisesRegex(RuntimeError, "LIVE_STATE_PERSIST_CONTRACT_INVALID|LIVE_STATE_FALLBACK_FORBIDDEN"):
            validate_material(persist, material, self.day, self.cadence)
        with self.assertRaisesRegex(RuntimeError, "REBASELINE_BOOTSTRAP_BLOCKED|LIVE_STATE_PERSIST_CONTRACT_INVALID"):
            validate_recovery_source_material(persist, material, self.day, self.cadence)

    def test_workflow_uses_optimistic_main_concurrency_without_rebase_force_or_merge(self):
        workflow = Path(".github/workflows/rate_production_rebaseline_bootstrap.yml").read_text(encoding="utf-8")
        self.assertIn("VALIDATED_MAIN_SHA: ${{ github.sha }}", workflow)
        self.assertIn("git fetch origin \"${{ github.ref_name }}\"", workflow)
        self.assertIn('origin_main_sha="$(git rev-parse "origin/${{ github.ref_name }}")"', workflow)
        self.assertIn('if [ "$origin_main_sha" != "$VALIDATED_MAIN_SHA" ]; then', workflow)
        self.assertIn("MAIN_ADVANCED_AFTER_REBASELINE_VALIDATION", workflow)
        self.assertIn("REBASELINE_BOOTSTRAP_PARENT_MISMATCH", workflow)
        self.assertIn("BOOTSTRAP_MAIN_CONCURRENCY_CONFLICT", workflow)
        self.assertIn('"push_result": "PASS"', workflow)
        self.assertIn('"pushed_main_sha": os.environ["BOOTSTRAP_COMMIT_SHA"]', workflow)
        self.assertIn('"pushed_main_sha": None', workflow)
        self.assertIn('"execution_evidence_authority": "ACTIONS_ARTIFACT"', workflow)
        self.assertIn('"validated_main_sha"', workflow)
        self.assertIn('"origin_main_sha_before_push"', workflow)
        self.assertIn('"bootstrap_parent_sha"', workflow)
        self.assertIn('"bootstrap_commit_sha"', workflow)
        self.assertIn('git push origin "HEAD:${{ github.ref_name }}"', workflow)
        self.assertLess(workflow.index('"push_result": "PASS"'),
                        workflow.index("      - name: Upload rebaseline bootstrap evidence"))
        self.assertNotIn("git pull --rebase", workflow)
        self.assertNotIn("git pull", workflow)
        self.assertNotIn("git rebase", workflow)
        self.assertNotIn("--force", workflow)
        self.assertNotIn("--force-with-lease", workflow)
        self.assertNotIn("git merge", workflow)
        self.assertNotIn("git commit --amend", workflow)
        self.assertNotIn("git add artifacts/production_state/RATE_PRODUCTION_REBASELINE_BOOTSTRAP_EVIDENCE.json", workflow)


if __name__ == "__main__":
    unittest.main()
