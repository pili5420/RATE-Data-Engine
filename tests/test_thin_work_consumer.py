from __future__ import annotations

import copy
import hashlib
import json
import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from src.cer074_acceptance import sha256, strip_runtime
from src.production_live_state import CADENCE_DIR, MANIFEST_NAME, PERSIST_NAME, STATE_NAME
from src.thin_work_manifest import INTRADAY_BLOCKED_DEPENDENCY, build_shadow_manifest
from src.thin_work_consumer import build_phase_a_consumer_evidence


class RateThinWorkConsumerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.now = datetime(2026, 9, 15, 4, 0, tzinfo=timezone.utc)
        self.source_path = self.tmp / "artifacts" / "RATE_PRODUCTION_SOURCE_BUNDLE_LATEST.json"
        self.source_path.parent.mkdir(parents=True)
        self.source = {
            "artifact": "RATE_PRODUCTION_SOURCE_BUNDLE",
            "input_snapshot_id": "rate-input-1200",
            "production_snapshot_id": "SNAP-1200",
            "validation_status": "PASS",
            "freshness_status": "PASS",
            "authorized_intraday_feed": "PASS",
            "domains": [
                {"domain": "market_daily"},
                {"domain": "market_intraday"},
                {"domain": "institutional"},
                {"domain": "large_holder"},
                {"domain": "fundamental"},
                {"domain": "benchmark"},
                {"domain": "trading_metadata"},
            ],
        }
        self.write_json(self.source_path, self.source)
        self.state_root = self.tmp / "state_root"
        self.slot = self.write_live_slot(snapshot_id="SNAP-0930", trading_date="2026-09-15", cadence="09:30")
        self.manifest_path = self.tmp / "manifest.json"
        self.write_json(self.manifest_path, self.manifest(cadence="12:00"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write_json(self, path, value):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(value, ensure_ascii=False, sort_keys=True), encoding="utf-8")

    def file_hash(self, path):
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()

    def manifest(self, **overrides):
        values = {
            "production_artifact_path": self.source_path,
            "cadence": "12:00",
            "run_id": "run-1200",
            "event": "schedule",
            "commit_sha": "a" * 40,
            "market_date": "2026-09-15",
            "generated_at": "2026-09-15T03:30:00Z",
        }
        values.update(overrides)
        return build_shadow_manifest(**values)

    def resign(self, manifest):
        manifest["manifest_sha256"] = hashlib.sha256(json.dumps({k: v for k, v in manifest.items() if k != "manifest_sha256"}, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        return manifest

    def evidence(self, **overrides):
        args = {
            "manifest_path": self.manifest_path,
            "previous_state_path": self.slot["persist_path"],
            "previous_state_root": self.state_root,
            "previous_trading_date": "2026-09-15",
            "previous_cadence": "09:30",
            "root": self.tmp,
            "expected_run_id": "run-1200",
            "expected_commit_sha": "a" * 40,
            "expected_production_snapshot_id": "SNAP-1200",
            "expected_previous_state_id": self.slot["state_id"],
            "expected_previous_state_hash": self.slot["state_hash"],
            "now": self.now,
        }
        args.update(overrides)
        return build_phase_a_consumer_evidence(**args)

    def write_live_slot(self, *, snapshot_id, trading_date, cadence):
        directory = self.state_root / "live" / trading_date / CADENCE_DIR[cadence]
        previous_state_id = f"rate-state-before-{CADENCE_DIR[cadence]}"
        decision = {
            "production_snapshot_id": snapshot_id,
            "previous_state_id": previous_state_id,
            "trading_date": trading_date,
            "cadence": cadence,
            "execution_scope": "PRODUCTION",
            "previous_state_resolution": "PERSISTED_PRODUCTION_STATE",
            "roy_portfolio": {"positions": [{"id": "roy-1", "symbol": "2330", "quantity": 1}], "cash": 1000, "nav": 1100},
            "ai_paper_portfolio": {"positions": [], "cash": 1000000, "nav": 1000000},
            "transaction_ledger": {"transactions": [{"id": "tx-1", "symbol": "2330"}]},
        }
        state_hash = sha256(strip_runtime(decision))
        state_id = "rate-state-" + state_hash[:24]
        entry = {
            "current_state_id": state_id,
            "previous_state_id": previous_state_id,
            "decision_payload_hash": state_hash,
            "trading_date": trading_date,
            "cadence": cadence,
            "execution_scope": "PRODUCTION",
            "previous_state_resolution": "PERSISTED_PRODUCTION_STATE",
        }
        persist = {
            "artifact": "RATE_CER076_PERSIST_RESULT_EVIDENCE",
            "validation_status": "PASS",
            "persist_result": {"status": "PERSISTED", "state_entry": entry},
            "current_state_id": state_id,
            "current_state_hash": state_hash,
            "previous_state_id": previous_state_id,
        }
        material = {
            "state_entry": entry,
            "decision_state": {
                "current_state_id": state_id,
                "previous_state_id": previous_state_id,
                "decision_payload_hash": state_hash,
                "decision": decision,
            },
        }
        persist_path = directory / PERSIST_NAME
        material_path = directory / STATE_NAME
        manifest_path = directory / MANIFEST_NAME
        self.write_json(persist_path, persist)
        self.write_json(material_path, material)
        manifest = {
            "artifact": "RATE_PRODUCTION_STATE_MANIFEST",
            "validation_status": "PASS",
            "ref": "refs/heads/main",
            "workflow_run_id": "123456",
            "workflow_job_id": "789012",
            "commit_sha": "b" * 40,
            "event_name": "schedule",
            "recovery_mode": False,
            "trading_date": trading_date,
            "cadence": cadence,
            "production_snapshot_id": snapshot_id,
            "current_state_id": state_id,
            "current_state_hash": state_hash,
            "files": {
                PERSIST_NAME: self.file_hash(persist_path),
                STATE_NAME: self.file_hash(material_path),
            },
        }
        self.write_json(manifest_path, manifest)
        return {
            "dir": directory,
            "persist_path": persist_path,
            "material_path": material_path,
            "manifest_path": manifest_path,
            "state_id": state_id,
            "state_hash": state_hash,
        }

    def refresh_slot_manifest(self):
        manifest = json.loads(self.slot["manifest_path"].read_text(encoding="utf-8"))
        manifest["files"][PERSIST_NAME] = self.file_hash(self.slot["persist_path"])
        manifest["files"][STATE_NAME] = self.file_hash(self.slot["material_path"])
        self.write_json(self.slot["manifest_path"], manifest)

    def assert_fail(self, evidence, reason):
        self.assertEqual(evidence["status"], "FAIL_CLOSED")
        self.assertIn(reason, evidence["fail_closed_reason"])
        self.assertFalse(evidence["state_mutation_allowed"])
        self.assertFalse(evidence["portfolio_mutation_allowed"])
        self.assertFalse(evidence["ledger_mutation_allowed"])
        self.assertFalse(evidence["production_mutation_allowed"])

    def test_positive_canonical_previous_state_continuity_different_snapshot(self):
        evidence = self.evidence()
        self.assertEqual(evidence["status"], "PASS")
        self.assertEqual(evidence["previous_state_gate"]["status"], "PASS")
        self.assertEqual(evidence["binding_gate"]["status"], "PASS")
        self.assertEqual(evidence["previous_production_snapshot_id"], "SNAP-0930")
        self.assertEqual(evidence["production_snapshot_id"], "SNAP-1200")
        self.assertTrue(evidence["decision_preview_allowed"])
        self.assertFalse(evidence["state_mutation_allowed"])
        self.assertFalse(evidence["fallback_used"])
        self.assertIn("M7", evidence["no_recalculation_evidence"]["not_calculated"])
        self.assertIn("Top30", evidence["no_recalculation_evidence"]["not_calculated"])

    def test_negative_manifest_paths(self):
        self.assert_fail(self.evidence(manifest_path=self.tmp / "missing.json"), "MISSING_MANIFEST")
        self.manifest_path.write_text("{", encoding="utf-8")
        self.assert_fail(self.evidence(), "CORRUPTED_MANIFEST")

    def test_negative_manifest_gates(self):
        cases = {
            "missing production_snapshot_id": ("MISSING_PRODUCTION_SNAPSHOT_ID", lambda m: m.pop("production_snapshot_id")),
            "snapshot mismatch": ("PRODUCTION_SNAPSHOT_BINDING_MISMATCH", lambda m: m.update({"production_snapshot_id": "other"})),
            "run mismatch": ("RUN_ID_MISMATCH", lambda m: m.update({"run_id": "other"})),
            "commit mismatch": ("COMMIT_MISMATCH", lambda m: m.update({"commit_sha": "b" * 40})),
            "validation non-pass": ("VALIDATION_STATUS_NOT_PASS", lambda m: m.update({"validation_status": "FAIL"})),
            "freshness non-pass": ("FRESHNESS_STATUS_NOT_PASS", lambda m: m.update({"freshness_status": "STALE"})),
            "source_status non-pass": ("SOURCE_STATUS_NOT_PASS", lambda m: m.update({"source_status": "BLOCKED"})),
            "missing required dataset": ("MISSING_REQUIRED_DATASET", lambda m: m.update({"datasets_missing": ["benchmark"]})),
            "blocked dependency": ("BLOCKED_DEPENDENCIES_PRESENT", lambda m: m.update({"blocked_dependencies": ["UPSTREAM_BLOCK"]})),
            "invalid previous-state requirement": ("INVALID_PREVIOUS_STATE_REQUIREMENT", lambda m: m.update({"previous_state_requirement": "OPTIONAL"})),
        }
        for name, (reason, mutate) in cases.items():
            with self.subTest(name=name):
                manifest = self.manifest()
                mutate(manifest)
                self.write_json(self.manifest_path, self.resign(manifest))
                self.assert_fail(self.evidence(), reason)

    def test_canonical_previous_state_negative_matrix(self):
        cases = {
            "persist evidence mismatch": ("LIVE_STATE_HASH_MISMATCH", self.break_persist_evidence),
            "decision-state material mismatch": ("LIVE_STATE_FULL_DECISION_MISSING", self.break_material_binding),
            "state manifest hash mismatch": ("LIVE_STATE_FILE_HASH_MISMATCH", self.break_manifest_hash),
            "previous state ID mismatch": ("PREVIOUS_STATE_ID_MISMATCH", lambda: None),
            "previous state hash mismatch": ("PREVIOUS_STATE_HASH_MISMATCH", lambda: None),
            "account continuity failure": ("LIVE_STATE_AI_ACCOUNT_MISSING", self.break_account_continuity),
            "ledger continuity failure": ("LIVE_STATE_TRANSACTION_HISTORY_MISSING", self.break_ledger_continuity),
            "non-production scope": ("LIVE_STATE_SCOPE_INVALID", self.break_scope),
            "fallback resolution": ("LIVE_STATE_FALLBACK_FORBIDDEN", self.break_fallback_resolution),
            "missing canonical persisted slot": ("LIVE_PREVIOUS_PRODUCTION_STATE_MISSING", self.break_missing_slot),
        }
        for name, (reason, mutate) in cases.items():
            with self.subTest(name=name):
                self.tearDown()
                self.setUp()
                mutate()
                overrides = {}
                if name == "previous state ID mismatch":
                    overrides["expected_previous_state_id"] = "rate-state-wrong"
                if name == "previous state hash mismatch":
                    overrides["expected_previous_state_hash"] = "0" * 64
                self.assert_fail(self.evidence(**overrides), reason)

    def break_persist_evidence(self):
        persist = json.loads(self.slot["persist_path"].read_text(encoding="utf-8"))
        persist["current_state_hash"] = "0" * 64
        self.write_json(self.slot["persist_path"], persist)
        self.refresh_slot_manifest()

    def break_material_binding(self):
        material = json.loads(self.slot["material_path"].read_text(encoding="utf-8"))
        material["state_entry"]["current_state_id"] = "rate-state-material-mismatch"
        self.write_json(self.slot["material_path"], material)
        self.refresh_slot_manifest()

    def break_manifest_hash(self):
        manifest = json.loads(self.slot["manifest_path"].read_text(encoding="utf-8"))
        manifest["files"][PERSIST_NAME] = "0" * 64
        self.write_json(self.slot["manifest_path"], manifest)

    def break_account_continuity(self):
        material = json.loads(self.slot["material_path"].read_text(encoding="utf-8"))
        material["decision_state"]["decision"]["ai_paper_portfolio"].pop("cash")
        decision = material["decision_state"]["decision"]
        state_hash = sha256(strip_runtime(decision))
        state_id = "rate-state-" + state_hash[:24]
        self.rebind_slot(material, state_id, state_hash)

    def break_ledger_continuity(self):
        material = json.loads(self.slot["material_path"].read_text(encoding="utf-8"))
        material["decision_state"]["decision"]["transaction_ledger"]["transactions"] = "corrupt"
        decision = material["decision_state"]["decision"]
        state_hash = sha256(strip_runtime(decision))
        state_id = "rate-state-" + state_hash[:24]
        self.rebind_slot(material, state_id, state_hash)

    def break_scope(self):
        persist = json.loads(self.slot["persist_path"].read_text(encoding="utf-8"))
        material = json.loads(self.slot["material_path"].read_text(encoding="utf-8"))
        persist["persist_result"]["state_entry"]["execution_scope"] = "SHADOW"
        material["state_entry"]["execution_scope"] = "SHADOW"
        self.write_json(self.slot["persist_path"], persist)
        self.write_json(self.slot["material_path"], material)
        self.refresh_slot_manifest()

    def break_fallback_resolution(self):
        persist = json.loads(self.slot["persist_path"].read_text(encoding="utf-8"))
        material = json.loads(self.slot["material_path"].read_text(encoding="utf-8"))
        persist["persist_result"]["state_entry"]["previous_state_resolution"] = "GENESIS"
        material["state_entry"]["previous_state_resolution"] = "GENESIS"
        self.write_json(self.slot["persist_path"], persist)
        self.write_json(self.slot["material_path"], material)
        self.refresh_slot_manifest()

    def break_missing_slot(self):
        self.slot["persist_path"].unlink()

    def rebind_slot(self, material, state_id, state_hash):
        material["decision_state"]["current_state_id"] = state_id
        material["decision_state"]["decision_payload_hash"] = state_hash
        material["state_entry"]["current_state_id"] = state_id
        material["state_entry"]["decision_payload_hash"] = state_hash
        persist = json.loads(self.slot["persist_path"].read_text(encoding="utf-8"))
        persist["current_state_id"] = state_id
        persist["current_state_hash"] = state_hash
        persist["persist_result"]["state_entry"] = material["state_entry"]
        manifest = json.loads(self.slot["manifest_path"].read_text(encoding="utf-8"))
        manifest["current_state_id"] = state_id
        manifest["current_state_hash"] = state_hash
        self.write_json(self.slot["persist_path"], persist)
        self.write_json(self.slot["material_path"], material)
        self.refresh_slot_manifest()
        manifest = json.loads(self.slot["manifest_path"].read_text(encoding="utf-8"))
        manifest["current_state_id"] = state_id
        manifest["current_state_hash"] = state_hash
        self.write_json(self.slot["manifest_path"], manifest)

    def test_missing_expected_bindings_fail_closed(self):
        cases = {
            "expected_run_id": "MISSING_EXPECTED_RUN_ID",
            "expected_commit_sha": "MISSING_EXPECTED_COMMIT_SHA",
            "expected_production_snapshot_id": "MISSING_EXPECTED_PRODUCTION_SNAPSHOT_ID",
            "expected_previous_state_id": "MISSING_EXPECTED_PREVIOUS_STATE_ID",
            "expected_previous_state_hash": "MISSING_EXPECTED_PREVIOUS_STATE_HASH",
        }
        for arg, reason in cases.items():
            with self.subTest(arg=arg):
                self.assert_fail(self.evidence(**{arg: None}), reason)

    def test_intraday_missing_feed_is_governed_blocked_outcome(self):
        source = dict(self.source)
        source["authorized_intraday_feed"] = "BLOCKED"
        self.write_json(self.source_path, source)
        self.write_json(self.manifest_path, self.manifest(cadence="09:30"))
        evidence = self.evidence()
        self.assert_fail(evidence, "BLOCKED_DEPENDENCIES_PRESENT")
        manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        self.assertIn(INTRADAY_BLOCKED_DEPENDENCY, manifest["blocked_dependencies"])


if __name__ == "__main__":
    unittest.main()
