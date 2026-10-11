"""Synthetic-only acceptance tests for Fundamental-only First Refresh wiring."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.eps_duration_facts.model import Rejected
from src import fundamental_first_refresh_execution as e


def universe():
    stocks = ([{"symbol": f"T{i:04d}", "market": "TWSE"} for i in range(1, 1086)] +
              [{"symbol": f"P{i:04d}", "market": "TPEX"} for i in range(1, 894)])
    return {"verification_status": "PASS", "stocks": stocks}


def plan():
    return e.build_request_plan(universe(), "synthetic-authority", e.CONTRACT["base_sha"])


def observations(value="1"):
    p = plan()
    stocks = universe()["stocks"]
    by_market = {m: [row for row in stocks if row["market"] == m] for m in ("TWSE", "TPEX")}
    result = []
    for entry in p["entries"]:
        if entry["provider"] == "FinMind":
            symbol, market = entry["target"]["symbol"], entry["target"]["market"]
            rows = [{"symbol": symbol, "market": market, "period": period,
                     "numeric_status": "VALID_NUMERIC", "value": value} for period in e.EPS_PERIODS]
        else:
            market, period = entry["target"]["market"], entry["target"]["period"]
            rows = [{"symbol": row["symbol"], "market": market, "period": period,
                     "numeric_status": "VALID_NUMERIC", "value": value} for row in by_market[market]]
        intent_id = f"intent-{entry['ordinal']:04d}"
        intent = {"intent_id": intent_id, "dispatch": {"plan_binding": e.PlanDispatchGate(p, entry, None)._binding()}}
        result.append({
            "ordinal": entry["ordinal"], "request_key": entry["request_key"],
            "intent_id": intent_id, "intent": intent,
            "event_sha256": e.digest({"ordinal": entry["ordinal"]}),
            "record": {
                "provider": entry["provider"], "target": deepcopy(entry["target"]), "rows": rows,
                "raw_sha256": e.digest({"raw": entry["ordinal"]}),
                "receipt_sha256": e.digest({"receipt": entry["ordinal"]}),
                "immutable_snapshot_id": "snapshot-" + e.digest({"snapshot": entry["ordinal"]}),
            },
        })
    return result


def minimal_snapshot(seed="one"):
    p = plan()
    core = {
        "artifact_kind": e.SNAPSHOT_KIND,
        "request_plan_id": p["request_plan_id"],
        "request_plan_sha256": p["request_plan_sha256"],
        "authority_id": p["authority_id"],
        "execution_main_sha": p["execution_main_sha"],
        "universe_identity": p["universe_identity"],
        "issuer_count": 1978,
        "issuer_readiness": [],
        "evidence_index": [],
        "acquisition_ledger_head": e.digest({"head": seed}),
        "historical_pit": "UNPROVEN",
        "original_eight_quarter_coverage_credit": 0,
        "fallback_allowed": False,
        "ranking_authorized": False,
        "decision_state_authorized": False,
        "production_domain": "fundamental",
        "publication_destination": deepcopy(p["publication_destination"]),
        "seed": seed,
    }
    h = e.digest(core)
    return {**core, "fundamental_snapshot_id": "rate-fundamental-first-refresh-" + h,
            "content_sha256": h, "fundamental_production_eligible": True}


class PlanTests(unittest.TestCase):
    def test_exact_inventory(self):
        p = plan()
        self.assertEqual((p["planned_requests"], p["maximum_requests"]), (1984, 1984))
        self.assertEqual((p["finmind_requests"], p["mops_requests"]), (1978, 6))

    def test_finmind_canonical_order_then_mops(self):
        p = plan()
        self.assertTrue(all(row["provider"] == "FinMind" for row in p["entries"][:1978]))
        self.assertEqual([(r["target"]["market"], r["target"]["period"]) for r in p["entries"][-6:]], list(e.MOPS_ORDER))
        self.assertEqual([r["ordinal"] for r in p["entries"]], list(range(1, 1985)))

    def test_plan_hash_deterministic(self):
        self.assertEqual(plan(), plan())

    def test_plan_hash_changes_with_authority(self):
        other = e.build_request_plan(universe(), "other-authority", e.CONTRACT["base_sha"])
        self.assertNotEqual(plan()["request_plan_sha256"], other["request_plan_sha256"])

    def test_duplicate_symbol_rejected(self):
        u = universe()
        u["stocks"][-1] = deepcopy(u["stocks"][0])
        with self.assertRaises(Rejected):
            e.build_request_plan(u, "a", e.CONTRACT["base_sha"])

    def test_wrong_market_counts_rejected(self):
        u = universe()
        u["stocks"][0]["market"] = "TPEX"
        with self.assertRaises(Rejected):
            e.build_request_plan(u, "a", e.CONTRACT["base_sha"])

    def test_invalid_main_sha_rejected(self):
        with self.assertRaisesRegex(Rejected, "MAIN_SHA"):
            e.build_request_plan(universe(), "a", "not-a-sha")

    def test_plan_mutation_rejected(self):
        p = plan()
        p["entries"][0]["timeout_seconds"] = 21
        with self.assertRaisesRegex(Rejected, "PLAN_DRIFT"):
            e.validate_plan(p, universe(), "synthetic-authority", e.CONTRACT["base_sha"])

    def test_timeout_and_interval_sealed(self):
        p = plan()
        self.assertEqual({r["timeout_seconds"] for r in p["entries"][:1978]}, {20})
        self.assertEqual({r["timeout_seconds"] for r in p["entries"][-6:]}, {45})
        self.assertEqual({r["minimum_dispatch_interval_seconds"] for r in p["entries"]}, {13})

    def test_destination_is_separate_fundamental_layer(self):
        dest = plan()["publication_destination"]
        self.assertEqual(dest["path"], e.LATEST_NAME)
        self.assertEqual(dest["production_domain"], "fundamental")
        self.assertFalse(dest["mutates_global_source_bundle_latest"])

    def test_plan_does_not_authorize_refresh_or_ranking(self):
        p = plan()
        self.assertFalse(p["first_refresh_authorized"])
        self.assertFalse(p["ranking_authorized"])
        self.assertFalse(p["fallback_allowed"])

    def test_authority_drift_rejected(self):
        p = plan(); p["authority_id"] = "other"
        with self.assertRaisesRegex(Rejected, "PLAN_DRIFT"):
            e.validate_plan(p, universe(), "synthetic-authority", e.CONTRACT["base_sha"])

    def test_same_count_universe_identity_drift_rejected(self):
        u = universe(); u["stocks"][0]["symbol"] = "T9999"
        with self.assertRaisesRegex(Rejected, "PLAN_DRIFT"):
            e.validate_plan(plan(), u, "synthetic-authority", e.CONTRACT["base_sha"])

    def test_valid_main_drift_rejected_by_existing_plan(self):
        with self.assertRaisesRegex(Rejected, "PLAN_DRIFT"):
            e.validate_plan(plan(), universe(), "synthetic-authority", "0" * 40)

    def test_destination_drift_rejected(self):
        p = plan(); p["publication_destination"]["path"] = "other.json"
        with self.assertRaisesRegex(Rejected, "PLAN_DRIFT"):
            e.validate_plan(p, universe(), "synthetic-authority", e.CONTRACT["base_sha"])


class DispatchTests(unittest.TestCase):
    class Inner:
        def __init__(self): self.calls = []
        def boundary(self, intent): self.calls.append(("boundary", intent)); return {"minimum_interval_seconds": 13}
        def check_outbound(self, value): self.calls.append(("check", value))
        def completed(self): self.calls.append(("completed", None))

    def test_gate_binds_plan_entry(self):
        p = plan(); inner = self.Inner()
        gate = e.PlanDispatchGate(p, p["entries"][0], inner)
        evidence = gate.boundary("intent")
        gate.check_outbound(evidence); gate.completed()
        self.assertEqual(evidence["plan_binding"]["request_plan_sha256"], p["request_plan_sha256"])
        self.assertEqual(evidence["plan_binding"]["ordinal"], 1)
        self.assertEqual(len(inner.calls), 3)

    def test_gate_rejects_binding_mutation(self):
        p = plan(); gate = e.PlanDispatchGate(p, p["entries"][0], None)
        evidence = gate.boundary("intent")
        evidence["plan_binding"]["ordinal"] = 2
        with self.assertRaisesRegex(Rejected, "DISPATCH_PLAN_MISMATCH"):
            gate.check_outbound(evidence)


class SimulationTests(unittest.TestCase):
    def test_full_1984_dry_execution(self):
        result = e.simulate_full_plan(plan(), universe())
        self.assertEqual(result["status"], "PASS")
        self.assertEqual((result["dispatch_count"], result["completed_count"], result["unique_intent_count"]),
                         (1984, 1984, 1984))
        self.assertIsNone(result["final_checkpoint"]["next_ordinal"])

    def test_request_one_failure_stops(self):
        r = e.simulate_full_plan(plan(), universe(), terminal_failure_at=1)
        self.assertEqual((r["status"], r["dispatch_count"], r["completed_count"]), ("STOPPED_TERMINAL_FAILURE", 1, 0))

    def test_middle_failure_stops(self):
        r = e.simulate_full_plan(plan(), universe(), terminal_failure_at=992)
        self.assertEqual((r["dispatch_count"], r["completed_count"], r["stopped_ordinal"]), (992, 991, 992))

    def test_last_failure_stops(self):
        r = e.simulate_full_plan(plan(), universe(), terminal_failure_at=1984)
        self.assertEqual((r["dispatch_count"], r["completed_count"]), (1984, 1983))

    def test_unknown_outcome_stops_without_retry(self):
        r = e.simulate_full_plan(plan(), universe(), unknown_outcome_at=10)
        self.assertEqual(r["status"], "STOPPED_UNKNOWN_OUTCOME")
        self.assertFalse(r["retry_allowed"]); self.assertFalse(r["fallback_allowed"])

    def test_crash_before_dispatch_does_not_consume_entry(self):
        r = e.simulate_full_plan(plan(), universe(), crash_before_at=10)
        self.assertEqual((r["dispatch_count"], r["completed_count"], r["next_ordinal"]), (9, 9, 10))
        self.assertFalse(r["auto_resume_allowed"])

    def test_crash_after_immutable_success_is_not_resent(self):
        r = e.simulate_full_plan(plan(), universe(), crash_after_success_at=10)
        self.assertEqual((r["dispatch_count"], r["completed_count"]), (10, 10))
        self.assertTrue(r["cold_replay_proves_completed"])
        self.assertFalse(r["would_resend_completed_request"])
        self.assertFalse(r["auto_resume_allowed"])

    def test_duplicate_ordinal_fails_closed(self):
        p = plan(); p["entries"][1]["ordinal"] = 1
        with self.assertRaises(Rejected): e.simulate_full_plan(p, universe())

    def test_duplicate_request_key_fails_closed(self):
        p = plan(); p["entries"][1]["request_key"] = p["entries"][0]["request_key"]
        with self.assertRaises(Rejected): e.simulate_full_plan(p, universe())


class AssemblerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = plan()
        cls.obs = observations()

    def test_full_plan_assembler_preserves_1978(self):
        snapshot = e.assemble_fundamental(self.p, universe(), self.obs)
        self.assertEqual(snapshot["issuer_count"], 1978)
        self.assertEqual(sum(r["fundamental_input_status"] == "READY" for r in snapshot["issuer_readiness"]), 1978)
        self.assertFalse(any(r["ranking_eligible"] for r in snapshot["issuer_readiness"]))

    def test_missing_eps_period_is_not_ready_not_filled(self):
        obs = deepcopy(self.obs)
        obs[0]["record"]["rows"].pop()
        snapshot = e.assemble_fundamental(self.p, universe(), obs)
        issuer = next(r for r in snapshot["issuer_readiness"] if r["symbol"] == self.p["entries"][0]["target"]["symbol"])
        self.assertEqual(issuer["fundamental_input_status"], "NOT_READY_MISSING_REQUIRED_PERIOD")
        self.assertEqual(len(issuer["feature_inputs"]["eps"]), 7)

    def test_zero_base_null_preserved(self):
        obs = deepcopy(self.obs)
        mops = obs[1978]
        mops["record"]["rows"][0]["numeric_status"] = "UNDEFINED_ZERO_BASE"
        mops["record"]["rows"][0]["value"] = None
        snapshot = e.assemble_fundamental(self.p, universe(), obs)
        symbol = mops["record"]["rows"][0]["symbol"]
        issuer = next(r for r in snapshot["issuer_readiness"] if r["symbol"] == symbol)
        self.assertEqual(issuer["fundamental_input_status"], "NOT_READY_MISSING_REQUIRED_PERIOD")

    def test_request_loss_rejected(self):
        with self.assertRaisesRegex(Rejected, "REQUEST_COUNT"):
            e.assemble_fundamental(self.p, universe(), self.obs[:-1])

    def test_request_key_substitution_rejected(self):
        obs = deepcopy(self.obs)
        obs[0]["request_key"] = obs[1]["request_key"]
        with self.assertRaises(Rejected):
            e.assemble_fundamental(self.p, universe(), obs)

    def test_intent_plan_binding_required(self):
        obs = deepcopy(self.obs)
        obs[0]["intent"]["dispatch"]["plan_binding"]["request_plan_sha256"] = "0" * 64
        with self.assertRaisesRegex(Rejected, "INTENT_BINDING"):
            e.assemble_fundamental(self.p, universe(), obs)

    def test_nonfinite_rejected(self):
        obs = deepcopy(self.obs)
        obs[0]["record"]["rows"][0]["value"] = "NaN"
        with self.assertRaisesRegex(Rejected, "NONFINITE"):
            e.assemble_fundamental(self.p, universe(), obs)

    def test_evidence_index_keeps_raw_receipt_snapshot(self):
        snapshot = e.assemble_fundamental(self.p, universe(), self.obs)
        first = snapshot["evidence_index"][0]
        self.assertTrue(first["raw_sha256"] and first["receipt_sha256"] and first["immutable_snapshot_id"])
        self.assertEqual(first["request_key"], self.p["entries"][0]["request_key"])


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.global_latest = self.root / "RATE_PRODUCTION_SOURCE_BUNDLE_LATEST.json"
        self.global_latest.write_bytes(b'{"protected":"global"}\n')

    def test_atomic_publish_uses_dedicated_pointer(self):
        before = self.global_latest.read_bytes()
        result = e.publish_fundamental_atomic(minimal_snapshot(), artifacts_root=self.root, expected_previous_latest=None)
        self.assertEqual(result["status"], "COMMITTED")
        self.assertEqual(self.global_latest.read_bytes(), before)
        self.assertTrue((self.root / e.LATEST_NAME).is_file())
        e.read_fundamental_committed(self.root, result["latest_identity"])

    def test_stale_cas_rejected(self):
        first = e.publish_fundamental_atomic(minimal_snapshot("a"), artifacts_root=self.root, expected_previous_latest=None)
        before = (self.root / e.LATEST_NAME).read_bytes()
        with self.assertRaisesRegex(Rejected, "CAS_STALE"):
            e.publish_fundamental_atomic(minimal_snapshot("b"), artifacts_root=self.root, expected_previous_latest="0" * 64)
        self.assertEqual((self.root / e.LATEST_NAME).read_bytes(), before)
        self.assertTrue(first["latest_identity"])

    def test_writer_failure_before_replace_preserves_previous(self):
        first = e.publish_fundamental_atomic(minimal_snapshot("a"), artifacts_root=self.root, expected_previous_latest=None)
        before = (self.root / e.LATEST_NAME).read_bytes()
        def fail(path, value): raise OSError("synthetic precommit")
        with self.assertRaises(OSError):
            e.publish_fundamental_atomic(minimal_snapshot("b"), artifacts_root=self.root,
                                         expected_previous_latest=first["latest_identity"], writer=fail)
        self.assertEqual((self.root / e.LATEST_NAME).read_bytes(), before)

    def test_post_replace_error_is_still_committed(self):
        from scripts.publish_production_source_bundle_latest import atomic_write_json
        def after(path, value):
            atomic_write_json(path, value)
            raise OSError("synthetic after replace")
        result = e.publish_fundamental_atomic(minimal_snapshot("a"), artifacts_root=self.root,
                                              expected_previous_latest=None, writer=after)
        self.assertEqual(e.read_fundamental_committed(self.root)["latest_identity"], result["latest_identity"])

    def test_manifest_tamper_rejected(self):
        e.publish_fundamental_atomic(minimal_snapshot(), artifacts_root=self.root, expected_previous_latest=None)
        path = self.root / e.LATEST_NAME
        value = json.loads(path.read_text())
        value["request_plan_sha256"] = "0" * 64
        path.write_text(json.dumps(value))
        with self.assertRaises(Rejected):
            e.read_fundamental_committed(self.root)

    def test_publication_never_changes_global_latest(self):
        before = self.global_latest.read_bytes()
        e.publish_fundamental_atomic(minimal_snapshot(), artifacts_root=self.root, expected_previous_latest=None)
        self.assertEqual(before, self.global_latest.read_bytes())

    def test_staging_failure_preserves_pointer_absence(self):
        with patch.object(e, "_put_object", side_effect=OSError("synthetic staging failure")):
            with self.assertRaises(OSError):
                e.publish_fundamental_atomic(minimal_snapshot(), artifacts_root=self.root, expected_previous_latest=None)
        self.assertFalse((self.root / e.LATEST_NAME).exists())


class AuthorizationTests(unittest.TestCase):
    def valid_auth(self):
        p = plan()
        return {
            "status": "FIRST_REFRESH_EXECUTION_AUTHORIZED",
            "main_sha": p["execution_main_sha"],
            "authority_id": p["authority_id"],
            "universe_identity": p["universe_identity"],
            "request_plan_sha256": p["request_plan_sha256"],
            "maximum_requests": 1984,
            "publication_destination_identity": p["publication_destination"]["identity"],
            "expected_previous_fundamental_latest_identity": None,
            "single_use": True,
        }

    def test_authorization_required(self):
        p = plan(); a = self.valid_auth(); a["status"] = "NOT_AUTHORIZED"
        with self.assertRaisesRegex(Rejected, "NOT_AUTHORIZED"):
            e.validate_execution_authorization(a, p, None)

    def test_authorization_plan_hash_binding(self):
        p = plan(); a = self.valid_auth(); a["request_plan_sha256"] = "0" * 64
        with self.assertRaisesRegex(Rejected, "AUTHORIZATION_BINDING"):
            e.validate_execution_authorization(a, p, None)

    def test_authorization_previous_latest_binding(self):
        p = plan(); a = self.valid_auth()
        with self.assertRaisesRegex(Rejected, "AUTHORIZATION_BINDING"):
            e.validate_execution_authorization(a, p, "0" * 64)

    def test_preexecution_seal_contains_owner_hashes(self):
        seal = e.preexecution_seal(plan(), None)
        self.assertEqual(seal["maximum_requests"], 1984)
        self.assertIn("acquisition_owner", seal["owner_sha256"])
        self.assertIn("atomic_publication_owner", seal["owner_sha256"])
        self.assertFalse(seal["first_refresh_authorized"])

    def test_resume_requires_new_control_center_continuation(self):
        with self.assertRaisesRegex(Rejected, "CONTROL_CENTER_CONTINUATION"):
            e.resume_execution()


class CheckpointTests(unittest.TestCase):
    def test_checkpoint_tamper_fails_closed(self):
        p = plan()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            h = e._checkpoint(root, p, p["entries"][0], event_sha256=e.digest({"event": 1}),
                              completed_keys=[p["entries"][0]["request_key"]], previous_checkpoint_sha256=None)
            path = next((root / "execution-checkpoints").iterdir())
            value = e.verify_checkpoint(path, p, None)
            self.assertEqual(value["last_completed_ordinal"], 1)
            self.assertEqual(h, path.stem.split("-", 1)[1])
            path.write_bytes(path.read_bytes() + b" ")
            with self.assertRaisesRegex(Rejected, "CHECKPOINT_TAMPER"):
                e.verify_checkpoint(path, p, None)


class GovernanceTests(unittest.TestCase):
    def test_contract_boundaries(self):
        self.assertFalse(e.CONTRACT["fallback_allowed"])
        self.assertFalse(e.CONTRACT["first_refresh_authorized"])
        self.assertFalse(e.CONTRACT["ranking_authorized"])
        self.assertEqual(e.CONTRACT["historical_pit"], "UNPROVEN")
        self.assertEqual(e.CONTRACT["intraday_dependency"], "BLOCKED_EXTERNAL")

    def test_no_phase2_or_ranking_import(self):
        source = Path(e.__file__).read_text(encoding="utf-8")
        self.assertNotIn("phase2_production", source)
        self.assertNotIn("rank_full_market", source)
        self.assertNotIn("production_live_state", source)

    def test_destination_does_not_mutate_global_source_latest(self):
        self.assertFalse(e.CONTRACT["publication_destination"]["mutates_global_source_bundle_latest"])
        self.assertEqual(e.CONTRACT["publication_destination"]["path"], e.LATEST_NAME)

    def test_existing_owner_reuse_declared(self):
        self.assertEqual(e.CONTRACT["acquisition_owner"], "scripts/run_prospective_provider_activation.py:acquire_once")
        self.assertEqual(e.CONTRACT["atomic_primitives_owner"], "src/production_refresh_commit.py")


if __name__ == "__main__":
    unittest.main()
