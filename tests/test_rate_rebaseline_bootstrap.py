import copy
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.bootstrap_production_rebaseline_state import (AUTHORIZATION_NAME, CONSUMPTION_NAME,
    _canonical_hash, bootstrap_rebaseline_state)
from src.cer074_acceptance import atomic_write_json, sha256, strip_runtime
from src.production_live_state import (CADENCE_DIR, MANIFEST_NAME, PERSIST_NAME, STATE_NAME,
    file_hash, load_live_state, validate_material, validate_rebaseline_material, validate_recovery_source_material)


class RateRebaselineBootstrapTests(unittest.TestCase):
    def setUp(self):
        tmp_root = Path.cwd() / ".tmp" / "rate-rebaseline-tests"
        tmp_root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="rate-rebaseline-test-", dir=tmp_root)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.artifacts = self.root / "artifacts"
        self.material_root = self.root / "material"
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

    def decision(self):
        roy = {"source_type": "CONTROL_CENTER_APPROVED_ROY_PORTFOLIO_OPENING_STATE",
               "positions": [{"id": "roy-1", "symbol": "台積電", "quantity": 40, "average_cost": 867.72}],
               "totals": {"cash": 179523, "opening_nav": 1509636}}
        ai = {"source_type": "AI_PAPER_PORTFOLIO_REBASELINE_OPENING_STATE",
              "opening_state_type": "CONTROL_CENTER_REBASELINE_OPENING_STATE",
              "opening_capital": 1000000, "positions": [], "cash": 1000000, "nav": 1000000,
              "historical_pnl_carried_forward": False, "historical_transactions_carried_forward": False,
              "historical_recovery": False}
        ledger = {"event_type": "REBASELINE_OPENING_BALANCE",
                  "pre_rebaseline_transaction_history": "UNAVAILABLE",
                  "historical_transaction_reconstruction": "PROHIBITED",
                  "ledger_continuity_mode": "POST_REBASELINE_ONLY",
                  "historical_recovery_status": "HISTORICAL_RECOVERY_SOURCE_IRRECOVERABLE"}
        return {"baseline_type": "CONTROL_CENTER_REBASELINE", "baseline_version": "V1",
                "trading_date": self.day, "cadence": self.cadence, "execution_scope": "PRODUCTION",
                "previous_state_resolution": "CONTROL_CENTER_REBASELINE",
                "historical_chain_break_acknowledged": True,
                "historical_account_state_recoverable": False,
                "production_evidence_state": {"validation_status": "PASS", "freshness": "PASS", "completeness": "PASS",
                                              "coverage": "30/30", "fixture_fallback": "FORBIDDEN",
                                              "stale_snapshot_fallback": "FORBIDDEN", "recovery_fallback": "FORBIDDEN"},
                "roy_portfolio": roy, "ai_paper_portfolio": ai, "transaction_ledger": ledger,
                "historical_predecessor_reference": {"state_id": "rate-state-656e460995324fb4a3eb7b30"}}

    def write_material(self, mutate=None):
        self.material_root.mkdir(parents=True, exist_ok=True)
        decision = self.decision()
        if mutate:
            mutate(decision)
        digest = sha256(strip_runtime(decision))
        state_id = "rate-state-" + digest[:24]
        rebaseline_state = {"artifact": "RATE_PRODUCTION_REBASELINE_DECISION_STATE", "validation_status": "PASS",
                            "state_id": state_id, "state_hash": digest, "decision": decision}
        source_bundle = {"artifact": "RATE_PRODUCTION_SOURCE_BUNDLE", "validation_status": "PASS",
                         "trading_date": self.day, "cadence": self.cadence, "coverage": "30/30",
                         "decision_record_coverage": {"coverage": "30/30"},
                         "source_provenance": {"fixture_fallback": "FORBIDDEN", "stale_snapshot_fallback": "FORBIDDEN"}}
        roy = {"artifact": "CONTROL_CENTER_REBASELINE_ROY_OPENING_STATE", **decision["roy_portfolio"]}
        ai = {"artifact": "CONTROL_CENTER_REBASELINE_AI_OPENING_STATE", **decision["ai_paper_portfolio"]}
        ledger = {"artifact": "RATE_LEDGER_REBASELINE_BOUNDARY", **decision["transaction_ledger"]}
        paths = {
            "source_bundle": self.material_root / "RATE_PRODUCTION_SOURCE_BUNDLE.json",
            "roy": self.material_root / "CONTROL_CENTER_REBASELINE_ROY_OPENING_STATE.json",
            "ai": self.material_root / "CONTROL_CENTER_REBASELINE_AI_OPENING_STATE.json",
            "ledger": self.material_root / "RATE_LEDGER_REBASELINE_BOUNDARY.json",
            "state": self.material_root / "RATE_PRODUCTION_REBASELINE_DECISION_STATE.json",
            "manifest": self.material_root / "RATE_PRODUCTION_REBASELINE_MANIFEST.json",
        }
        for key, obj in (("source_bundle", source_bundle), ("roy", roy), ("ai", ai), ("ledger", ledger), ("state", rebaseline_state)):
            atomic_write_json(paths[key], obj)
        manifest = {"artifact": "RATE_PRODUCTION_REBASELINE_MANIFEST", "validation_status": "PASS",
                    "baseline_type": "CONTROL_CENTER_REBASELINE", "selected_trading_date": self.day,
                    "selected_cadence": self.cadence, "baseline_id": "rate-rebaseline-20261002-0730-cc-approved-v1",
                    "state_id": state_id, "state_hash": digest,
                    "files": {"RATE_PRODUCTION_SOURCE_BUNDLE.json": file_hash(paths["source_bundle"]),
                              "CONTROL_CENTER_REBASELINE_ROY_OPENING_STATE.json": file_hash(paths["roy"]),
                              "CONTROL_CENTER_REBASELINE_AI_OPENING_STATE.json": file_hash(paths["ai"]),
                              "RATE_LEDGER_REBASELINE_BOUNDARY.json": file_hash(paths["ledger"]),
                              "RATE_PRODUCTION_REBASELINE_DECISION_STATE.json": file_hash(paths["state"])}}
        atomic_write_json(paths["manifest"], manifest)
        paths["state_id"] = state_id
        paths["state_hash"] = digest
        return paths

    def authorization_manifest(self, **overrides):
        payload = {"artifact": "RATE_PRODUCTION_REBASELINE_AUTHORIZATION_MANIFEST",
                   "authorization_id": self.authorization_id,
                   "authorization_status": "APPROVED", "approved_by": "CONTROL_CENTER",
                   "baseline_type": "CONTROL_CENTER_REBASELINE",
                   "previous_state_resolution": "CONTROL_CENTER_REBASELINE",
                   "baseline_id": "rate-rebaseline-20261002-0730-cc-approved-v1",
                   "trading_date": self.day, "cadence": self.cadence,
                   "production_source_bundle_sha256": file_hash(self.paths["source_bundle"]),
                   "roy_opening_state_sha256": file_hash(self.paths["roy"]),
                   "ai_opening_state_sha256": file_hash(self.paths["ai"]),
                   "ledger_boundary_sha256": file_hash(self.paths["ledger"]),
                   "canonical_rebaseline_state_sha256": file_hash(self.paths["state"]),
                   "expected_state_id": self.paths["state_id"], "expected_state_hash": self.paths["state_hash"],
                   "single_use": True, "acceptance_counter_reset": False,
                   "post_rebaseline_continuity_window": "NEW", "approval_commit_sha": "0" * 40}
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
        args = dict(rebaseline_manifest_path=self.paths["manifest"], rebaseline_state_path=self.paths["state"],
                    source_bundle_path=self.paths["source_bundle"], roy_opening_state_path=self.paths["roy"],
                    ai_opening_state_path=self.paths["ai"], ledger_boundary_path=self.paths["ledger"],
                    trading_date=self.day, cadence=self.cadence, rebaseline_authorization_id=self.authorization_id,
                    repository_root=self.repo, artifacts_root=self.artifacts, workflow_run_id="701", workflow_job_id="801",
                    event_name="workflow_dispatch", ref="refs/heads/main",
                    commit_sha=self.git("-C", self.repo, "rev-parse", "HEAD"),
                    evidence_output=self.artifacts / "production_state/RATE_PRODUCTION_REBASELINE_BOOTSTRAP_EVIDENCE.json")
        args.update(overrides)
        return bootstrap_rebaseline_state(**args)

    def assert_blocked(self, reason, **overrides):
        out = self.bootstrap(**overrides)
        self.assertEqual(out["validation_status"], "BLOCKED", out)
        self.assertEqual(out["blocking_reason"], reason, out)

    def test_valid_control_center_rebaseline_bootstrap_writes_canonical_trio_and_consumes_once(self):
        out = self.bootstrap()
        self.assertEqual(out["validation_status"], "PASS", out)
        directory = self.artifacts / "production_state/live" / self.day / CADENCE_DIR[self.cadence]
        self.assertTrue((directory / PERSIST_NAME).is_file())
        self.assertTrue((directory / STATE_NAME).is_file())
        self.assertTrue((directory / MANIFEST_NAME).is_file())
        manifest = json.loads((directory / MANIFEST_NAME).read_text(encoding="utf-8"))
        self.assertIs(manifest["rebaseline_bootstrap"], True)
        self.assertFalse(manifest["scheduled_soak_credit"])
        self.assertFalse(manifest["acceptance_counter_reset"])
        self.assertEqual(manifest["post_rebaseline_continuity_window"], "NEW")
        consumed = self.artifacts / "production_state/rebaseline_authorizations" / self.authorization_id / CONSUMPTION_NAME
        self.assertTrue(consumed.is_file())
        self.assertEqual(json.loads(consumed.read_text(encoding="utf-8"))["authorization_id"], self.authorization_id)
        loaded = load_live_state(self.artifacts / "production_state", self.day, self.cadence)
        self.assertEqual(loaded["state"]["current_state_id"], self.paths["state_id"])
        second = self.bootstrap()
        self.assertEqual(second["blocking_reason"], "REBASELINE_AUTHORIZATION_ALREADY_CONSUMED")

    def test_unauthorized_schedule_non_main_and_missing_authorization_blocked(self):
        self.assert_blocked("REBASELINE_BOOTSTRAP_AUTHORIZATION_REQUIRED", event_name="schedule")
        self.assert_blocked("REBASELINE_BOOTSTRAP_AUTHORIZATION_REQUIRED", ref="refs/heads/feature")
        self.assert_blocked("REBASELINE_AUTHORIZATION_MANIFEST_REQUIRED", rebaseline_authorization_id="CC-MISSING")

    def test_wrong_hashes_and_reused_authorization_blocked(self):
        self.authorization_manifest(production_source_bundle_sha256="0" * 64)
        self.assert_blocked("REBASELINE_PRODUCTION_BUNDLE_HASH_MISMATCH")
        self.authorization_manifest(roy_opening_state_sha256="0" * 64)
        self.assert_blocked("REBASELINE_ROY_OPENING_HASH_MISMATCH")
        self.authorization_manifest(ai_opening_state_sha256="0" * 64)
        self.assert_blocked("REBASELINE_AI_OPENING_HASH_MISMATCH")
        self.authorization_manifest(ledger_boundary_sha256="0" * 64)
        self.assert_blocked("REBASELINE_LEDGER_BOUNDARY_HASH_MISMATCH")
        self.authorization_manifest(expected_state_hash="0" * 64)
        self.assert_blocked("REBASELINE_MATERIAL_STATE_HASH_MISMATCH")

    def test_stale_incomplete_synthetic_fabricated_and_historical_binding_blocked(self):
        cases = [
            lambda d: d["production_evidence_state"].update(freshness="FAIL"),
            lambda d: d["production_evidence_state"].update(coverage="29/30"),
            lambda d: d["roy_portfolio"]["positions"][0].update(synthetic=True),
            lambda d: d["transaction_ledger"].update(transactions=[{"id": "fabricated"}]),
            lambda d: d.update(previous_state_id="rate-state-656e460995324fb4a3eb7b30"),
        ]
        for mutate in cases:
            with self.subTest(mutate=mutate):
                self.paths = self.write_material(mutate=mutate)
                self.authorization_manifest()
                self.assert_blocked("REBASELINE_BOOTSTRAP_BLOCKED")

    def test_normal_validate_material_and_recovery_validator_unchanged(self):
        self.paths = self.write_material()
        self.authorization_manifest()
        out = self.bootstrap()
        self.assertEqual(out["validation_status"], "PASS", out)
        directory = self.artifacts / "production_state/live" / self.day / CADENCE_DIR[self.cadence]
        persist = json.loads((directory / PERSIST_NAME).read_text(encoding="utf-8"))
        material = json.loads((directory / STATE_NAME).read_text(encoding="utf-8"))
        self.assertEqual(validate_rebaseline_material(persist, material, self.day, self.cadence)["current_state_id"], self.paths["state_id"])
        with self.assertRaisesRegex(RuntimeError, "LIVE_STATE_PERSIST_CONTRACT_INVALID|LIVE_STATE_FALLBACK_FORBIDDEN"):
            validate_material(persist, material, self.day, self.cadence)
        with self.assertRaisesRegex(RuntimeError, "REBASELINE_BOOTSTRAP_BLOCKED|LIVE_STATE_PERSIST_CONTRACT_INVALID"):
            validate_recovery_source_material(persist, material, self.day, self.cadence)


if __name__ == "__main__":
    unittest.main()



