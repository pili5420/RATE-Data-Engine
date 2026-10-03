from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from src.production_live_state import calculate_state_hash, state_id_for
from src.thin_work_manifest import INTRADAY_BLOCKED_DEPENDENCY, build_shadow_manifest
from src.thin_work_consumer import build_phase_a_consumer_evidence


class RateThinWorkConsumerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.now = datetime(2026, 9, 15, 1, 0, tzinfo=timezone.utc)
        self.source_path = self.tmp / "artifacts" / "RATE_PRODUCTION_SOURCE_BUNDLE_LATEST.json"
        self.source_path.parent.mkdir(parents=True)
        self.previous_state_path = self.tmp / "state" / "previous.json"
        self.previous_state_path.parent.mkdir(parents=True)
        self.source = {
            "artifact": "RATE_PRODUCTION_SOURCE_BUNDLE",
            "input_snapshot_id": "rate-input-1",
            "production_snapshot_id": "rate-prod-1",
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
        self.previous_state = self.previous_state_fixture()
        self.write_json(self.previous_state_path, self.previous_state)
        self.manifest_path = self.tmp / "manifest.json"
        self.write_json(self.manifest_path, self.manifest())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write_json(self, path, value):
        Path(path).write_text(json.dumps(value, ensure_ascii=False, sort_keys=True), encoding="utf-8")

    def resign(self, manifest):
        manifest["manifest_sha256"] = hashlib.sha256(json.dumps({k: v for k, v in manifest.items() if k != "manifest_sha256"}, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        return manifest

    def manifest(self, **overrides):
        values = {
            "production_artifact_path": self.source_path,
            "cadence": "07:30",
            "run_id": "run-1",
            "event": "schedule",
            "commit_sha": "a" * 40,
            "market_date": "2026-09-15",
            "generated_at": "2026-09-15T00:30:00Z",
        }
        values.update(overrides)
        return build_shadow_manifest(**values)

    def evidence(self, **overrides):
        args = {
            "manifest_path": self.manifest_path,
            "previous_state_path": self.previous_state_path,
            "root": self.tmp,
            "expected_run_id": "run-1",
            "expected_commit_sha": "a" * 40,
            "expected_production_snapshot_id": "rate-prod-1",
            "expected_previous_state_id": self.previous_state["current_state_id"],
            "expected_previous_state_hash": self.previous_state["current_state_hash"],
            "now": self.now,
        }
        args.update(overrides)
        return build_phase_a_consumer_evidence(**args)

    def previous_state_fixture(self):
        state = {
            "current_state_id": "rate-state-prev-1",
            "previous_state_id": "rate-state-prev-0",
            "current_state_hash": "PENDING",
            "decision_payload_hash": "decision-hash-1",
            "production_snapshot_id": "rate-prod-1",
            "portfolio_state_reference": "portfolio-ref-1",
            "roy_portfolio_account_reference": "roy-account-ref-1",
            "ai_paper_portfolio_account_reference": "paper-account-ref-1",
            "ai_paper_portfolio_ledger_reference": "paper-ledger-ref-1",
            "transaction_ledger_reference": "transaction-ledger-ref-1",
            "state_reset_detected": False,
            "ledger_reset_detected": False,
            "fallback_used": False,
            "production_execution_scope": "PRODUCTION",
            "lineage": {
                "current_state_id": "rate-state-prev-1",
                "current_state_hash": "PENDING",
                "previous_state_id": "rate-state-prev-0",
                "production_snapshot_id": "rate-prod-1",
                "decision_payload_hash": "decision-hash-1",
                "portfolio_state_reference": "portfolio-ref-1",
                "roy_portfolio_account_reference": "roy-account-ref-1",
                "ai_paper_portfolio_account_reference": "paper-account-ref-1",
                "ai_paper_portfolio_ledger_reference": "paper-ledger-ref-1",
                "transaction_ledger_reference": "transaction-ledger-ref-1",
            },
        }
        state["current_state_hash"] = calculate_state_hash(state)
        state["current_state_id"] = state_id_for(state["current_state_hash"])
        state["lineage"]["current_state_id"] = state["current_state_id"]
        state["lineage"]["current_state_hash"] = state["current_state_hash"]
        state["current_state_hash"] = calculate_state_hash(state)
        state["current_state_id"] = state_id_for(state["current_state_hash"])
        state["lineage"]["current_state_id"] = state["current_state_id"]
        state["lineage"]["current_state_hash"] = state["current_state_hash"]
        return state

    def assert_fail(self, evidence, reason):
        self.assertEqual(evidence["status"], "FAIL_CLOSED")
        self.assertIn(reason, evidence["fail_closed_reason"])
        self.assertFalse(evidence["state_mutation_allowed"])
        self.assertFalse(evidence["portfolio_mutation_allowed"])
        self.assertFalse(evidence["ledger_mutation_allowed"])
        self.assertFalse(evidence["production_mutation_allowed"])

    def test_positive_shadow_acceptance_preview_only(self):
        evidence = self.evidence()
        self.assertEqual(evidence["status"], "PASS")
        self.assertTrue(evidence["decision_preview_allowed"])
        self.assertTrue(evidence["portfolio_preview_allowed"])
        self.assertTrue(evidence["ledger_preview_allowed"])
        self.assertFalse(evidence["state_mutation_allowed"])
        self.assertFalse(evidence["portfolio_mutation_allowed"])
        self.assertFalse(evidence["ledger_mutation_allowed"])
        self.assertFalse(evidence["production_mutation_allowed"])
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

    def test_previous_state_negative_paths_and_continuity(self):
        self.assert_fail(self.evidence(previous_state_path=self.tmp / "missing-state.json"), "MISSING_PREVIOUS_STATE")
        self.previous_state_path.write_text("{", encoding="utf-8")
        self.assert_fail(self.evidence(), "CORRUPTED_PREVIOUS_STATE")
        state = self.previous_state_fixture()
        state["current_state_id"] = "rate-production-state-wrong"
        self.write_json(self.previous_state_path, state)
        self.assert_fail(self.evidence(), "RATE_STATE_ID_MISMATCH")

    def test_previous_state_semantic_corruption_fails_closed(self):
        state = self.previous_state_fixture()
        state["decision_payload_hash"] = "tampered"
        self.write_json(self.previous_state_path, state)
        self.assert_fail(self.evidence(), "RATE_STATE_HASH_MISMATCH")

        state = self.previous_state_fixture()
        state["lineage"]["transaction_ledger_reference"] = "stale-ledger"
        state = self.refresh_state_identity(state)
        self.write_json(self.previous_state_path, state)
        self.assert_fail(self.evidence(expected_previous_state_hash=state["current_state_hash"]), "RATE_STATE_LINEAGE_LEDGER")

        state = self.previous_state_fixture()
        state.pop("portfolio_state_reference")
        self.write_json(self.previous_state_path, state)
        self.assert_fail(self.evidence(), "RATE_STATE_PORTFOLIO_REFERENCE_REQUIRED")

        state = self.previous_state_fixture()
        state["ledger_reset_detected"] = True
        state = self.refresh_state_identity(state)
        self.write_json(self.previous_state_path, state)
        self.assert_fail(self.evidence(expected_previous_state_hash=state["current_state_hash"]), "RATE_LEDGER_RESET_DETECTED")

    def refresh_state_identity(self, state):
        state["current_state_hash"] = calculate_state_hash(state)
        state["current_state_id"] = state_id_for(state["current_state_hash"])
        state["lineage"]["current_state_id"] = state["current_state_id"]
        state["lineage"]["current_state_hash"] = state["current_state_hash"]
        state["current_state_hash"] = calculate_state_hash(state)
        state["current_state_id"] = state_id_for(state["current_state_hash"])
        state["lineage"]["current_state_id"] = state["current_state_id"]
        state["lineage"]["current_state_hash"] = state["current_state_hash"]
        return state

    def test_previous_state_canonical_contract_fail_closed_matrix(self):
        cases = {
            "state hash mismatch": ("RATE_STATE_HASH_MISMATCH", lambda s: s.update({"decision_payload_hash": "tampered"}), False),
            "state ID mismatch": ("RATE_STATE_ID_MISMATCH", lambda s: s.update({"current_state_id": "rate-production-state-wrong"}), False),
            "lineage ID mismatch": ("RATE_STATE_LINEAGE_ID", lambda s: s["lineage"].update({"current_state_id": "rate-production-state-stale"}), False),
            "lineage hash mismatch": ("RATE_STATE_LINEAGE_HASH", lambda s: s["lineage"].update({"current_state_hash": "0" * 64}), False),
            "lineage previous mismatch": ("RATE_STATE_LINEAGE_PREVIOUS_ID", lambda s: s["lineage"].update({"previous_state_id": "stale"}), True),
            "lineage snapshot mismatch": ("RATE_STATE_LINEAGE_SNAPSHOT", lambda s: s["lineage"].update({"production_snapshot_id": "stale"}), True),
            "portfolio account missing": ("RATE_STATE_ROY_PORTFOLIO_ACCOUNT_REQUIRED", lambda s: s.pop("roy_portfolio_account_reference"), False),
            "AI Paper account missing": ("RATE_STATE_AI_PAPER_ACCOUNT_REQUIRED", lambda s: s.pop("ai_paper_portfolio_account_reference"), False),
            "AI Paper ledger missing": ("RATE_STATE_AI_PAPER_LEDGER_REQUIRED", lambda s: s.pop("ai_paper_portfolio_ledger_reference"), False),
            "transaction ledger missing": ("RATE_STATE_TRANSACTION_LEDGER_REQUIRED", lambda s: s.pop("transaction_ledger_reference"), False),
            "reset marker detected": ("RATE_STATE_RESET_DETECTED", lambda s: s.update({"state_reset_detected": True}), True),
            "fallback detected": ("RATE_STATE_FALLBACK_USED", lambda s: s.update({"fallback_used": True}), True),
            "non-production scope": ("RATE_STATE_PRODUCTION_SCOPE", lambda s: s.update({"production_execution_scope": "SHADOW"}), True),
        }
        for name, (reason, mutate, resign) in cases.items():
            with self.subTest(name=name):
                state = self.previous_state_fixture()
                mutate(state)
                if resign:
                    state = self.refresh_state_identity(state)
                self.write_json(self.previous_state_path, state)
                expected_hash = state.get("current_state_hash") if resign else self.previous_state["current_state_hash"]
                self.assert_fail(self.evidence(expected_previous_state_hash=expected_hash), reason)

    def test_previous_state_manifest_binding_mismatch_fails_closed(self):
        state = self.previous_state_fixture()
        state["production_snapshot_id"] = "rate-prod-other"
        state["lineage"]["production_snapshot_id"] = "rate-prod-other"
        state = self.refresh_state_identity(state)
        self.write_json(self.previous_state_path, state)
        self.assert_fail(self.evidence(expected_previous_state_hash=state["current_state_hash"]), "RATE_STATE_PRODUCTION_SNAPSHOT_MISMATCH")

    def test_tampered_payload_with_unchanged_claimed_id_fails_closed(self):
        state = self.previous_state_fixture()
        state["portfolio_state_reference"] = "tampered"
        self.write_json(self.previous_state_path, state)
        self.assert_fail(self.evidence(), "RATE_STATE_HASH_MISMATCH")

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
