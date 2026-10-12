"""Synthetic-only acceptance tests for Fundamental-only First Refresh wiring."""
from copy import deepcopy
from datetime import datetime, timezone
import json
import multiprocessing
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.eps_duration_facts.model import Rejected
from src import fundamental_first_refresh_execution as e


def synthetic_authorization(artifacts_root, p=None, previous=None):
    """Synthetic authority cannot match the real activation seal; never a live grant."""
    p = p or plan()
    seal = e.preexecution_seal(p, previous)
    value = {
        "status": "FIRST_REFRESH_EXECUTION_AUTHORIZED", "evidence_scope": "SYNTHETIC_ENGINEERING_ONLY",
        "main_sha": p["execution_main_sha"], "authority_id": p["authority_id"],
        "universe_identity": p["universe_identity"], "request_plan_id": p["request_plan_id"],
        "request_plan_sha256": p["request_plan_sha256"], "planned_requests": 1984, "maximum_requests": 1984,
        "publication_destination_identity": p["publication_destination"]["identity"],
        "expected_previous_fundamental_latest_identity": previous, "single_use": True,
        "preexecution_seal_id": seal["seal_id"], "preexecution_seal_sha256": seal["seal_sha256"],
        "owner_sha256": deepcopy(seal["owner_sha256"]),
        "authorization_consumption_root_identity": e.consumption_root_identity(artifacts_root),
    }
    return rehash_authorization(value)


def rehash_authorization(value):
    value["authorization_id"] = e.authorization_identity(value)
    value["authorization_sha256"] = e.authorization_digest(value)
    return value


def synthetic_clock():
    return datetime.now(timezone.utc).isoformat()


def consumption_worker(artifacts_root, execution_root, start, output, crash_after=False):
    from src.prospective_acquisition_recovery import offline_network_guard
    import sys
    sys.addaudithook(offline_network_guard)
    p = plan()
    auth = synthetic_authorization(artifacts_root, p)
    if start is not None:
        start.wait(20)
    try:
        e.claim_authorization(auth, p, artifacts_root=artifacts_root, execution_root=execution_root,
                              expected_previous_latest=None, clock=synthetic_clock)
        if crash_after:
            os._exit(23)
        output.put("CLAIMED")
    except Exception as exc:
        output.put(str(exc))


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
        return synthetic_authorization(Path(tempfile.gettempdir()) / "synthetic-artifacts")

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


class HardeningAuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "authoritative-artifacts"
        self.p = plan()
        self.auth = synthetic_authorization(self.root, self.p)

    def reject_mutation(self, field, value, reason="AUTHORIZATION_BINDING"):
        changed = deepcopy(self.auth)
        changed[field] = value
        rehash_authorization(changed)
        with self.assertRaisesRegex(Rejected, reason):
            e.validate_execution_authorization(changed, self.p, None, artifacts_root=self.root)
        self.assertFalse(self.root.exists())

    def test_correct_seal_and_authorization_pass(self):
        seal = e.validate_execution_authorization(self.auth, self.p, None, artifacts_root=self.root)
        self.assertEqual(seal["seal_id"], "rate-first-refresh-preexecution-" + seal["seal_sha256"])
        self.assertEqual(seal["request_plan_id"], self.p["request_plan_id"])
        self.assertEqual(seal["planned_requests"], 1984)
        self.assertFalse(seal["first_refresh_authorized"])

    def test_wrong_seal_id_rejected(self):
        self.reject_mutation("preexecution_seal_id", "wrong")

    def test_wrong_seal_sha_rejected(self):
        self.reject_mutation("preexecution_seal_sha256", "0" * 64)

    def owner_drift(self, name):
        owners = deepcopy(self.auth["owner_sha256"])
        owners[name] = "0" * 64
        self.reject_mutation("owner_sha256", owners)

    def test_execution_owner_hash_drift_rejected(self):
        self.owner_drift("execution_owner")

    def test_assembler_owner_hash_drift_rejected(self):
        self.owner_drift("assembler_owner")

    def test_acquisition_owner_hash_drift_rejected(self):
        self.owner_drift("acquisition_owner")

    def test_atomic_publication_owner_hash_drift_rejected(self):
        self.owner_drift("atomic_publication_owner")

    def test_atomic_commit_owner_hash_drift_rejected(self):
        self.owner_drift("atomic_commit_owner")

    def test_current_owner_bytes_recomputed_not_trusted(self):
        fixture = Path(self.temp.name) / "controlled-owner-fixtures"
        files = ("src/fundamental_first_refresh_execution.py", "scripts/run_prospective_provider_activation.py",
                 "scripts/publish_production_source_bundle_latest.py", "src/production_refresh_commit.py")
        for relative in files:
            path = fixture / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"synthetic owner bytes\n")
        with patch.object(e, "ROOT", fixture):
            auth = synthetic_authorization(self.root, self.p)
            (fixture / files[1]).write_bytes(b"changed synthetic owner bytes\n")
            with self.assertRaisesRegex(Rejected, "AUTHORIZATION_BINDING"):
                e.validate_execution_authorization(auth, self.p, None, artifacts_root=self.root)

    def test_authorization_sha_tamper_rejected(self):
        changed = deepcopy(self.auth)
        changed["authorization_sha256"] = "0" * 64
        with self.assertRaisesRegex(Rejected, "AUTHORIZATION_HASH_BINDING"):
            e.validate_execution_authorization(changed, self.p, None, artifacts_root=self.root)

    def test_wrong_authorization_id_rejected(self):
        changed = deepcopy(self.auth)
        changed["authorization_id"] = "rate-first-refresh-authorization-" + "0" * 64
        changed["authorization_sha256"] = e.authorization_digest(changed)
        with self.assertRaisesRegex(Rejected, "AUTHORIZATION_ID_BINDING"):
            e.validate_execution_authorization(changed, self.p, None, artifacts_root=self.root)

    def test_authorization_hash_excludes_only_own_hash(self):
        core = {k: v for k, v in self.auth.items() if k != "authorization_sha256"}
        self.assertEqual(self.auth["authorization_sha256"], e.digest(core))
        changed = deepcopy(self.auth)
        changed["authorization_sha256"] = "0" * 64
        self.assertEqual(e.authorization_digest(changed), self.auth["authorization_sha256"])
        changed["authorization_id"] = "changed"
        self.assertNotEqual(e.authorization_digest(changed), self.auth["authorization_sha256"])

    def test_wrong_plan_sha_rejected(self):
        self.reject_mutation("request_plan_sha256", "0" * 64)

    def test_wrong_plan_id_rejected(self):
        self.reject_mutation("request_plan_id", "wrong")

    def test_wrong_main_rejected(self):
        self.reject_mutation("main_sha", "0" * 40)

    def test_wrong_authority_rejected(self):
        self.reject_mutation("authority_id", "other-authority")

    def test_wrong_universe_rejected(self):
        self.reject_mutation("universe_identity", "0" * 64)

    def test_wrong_destination_rejected(self):
        self.reject_mutation("publication_destination_identity", "0" * 64)

    def test_single_use_false_rejected(self):
        self.reject_mutation("single_use", False)

    def test_changed_authoritative_artifacts_root_rejected(self):
        with self.assertRaisesRegex(Rejected, "CONSUMPTION_ROOT_BINDING"):
            e.validate_execution_authorization(self.auth, self.p, None, artifacts_root=self.root.parent / "alternate")


class HardeningConsumptionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "authoritative-artifacts"
        self.p = plan()
        self.auth = synthetic_authorization(self.root, self.p)

    def claim(self, execution="execution-a"):
        return e.claim_authorization(self.auth, self.p, artifacts_root=self.root,
                                     execution_root=self.base / execution, expected_previous_latest=None,
                                     clock=synthetic_clock)

    def record_path(self):
        return self.root / e.CONSUMPTION_NAMESPACE / (self.auth["authorization_id"] + ".json")

    def test_first_claim_pass_and_schema(self):
        record = self.claim()
        self.assertEqual(record["status"], "CONSUMED")
        self.assertEqual(record["authorization_id"], self.auth["authorization_id"])
        self.assertEqual(record["authorization_sha256"], self.auth["authorization_sha256"])
        self.assertEqual(record["request_plan_id"], self.p["request_plan_id"])
        self.assertEqual(record["preexecution_seal_id"], self.auth["preexecution_seal_id"])
        self.assertTrue(record["execution_root_identity"] and record["consumed_at"])
        self.assertFalse((self.base / "execution-a").exists())

    def test_same_root_second_claim_rejected(self):
        self.claim()
        with self.assertRaisesRegex(Rejected, "AUTHORIZATION_ALREADY_CONSUMED"):
            self.claim()

    def test_different_execution_root_second_claim_rejected(self):
        self.claim()
        with self.assertRaisesRegex(Rejected, "AUTHORIZATION_ALREADY_CONSUMED"):
            self.claim("execution-b")
        self.assertFalse((self.base / "execution-b").exists())

    def test_consumption_record_never_overwritten(self):
        self.claim()
        before = self.record_path().read_bytes()
        with self.assertRaisesRegex(Rejected, "ALREADY_CONSUMED"):
            self.claim("execution-b")
        self.assertEqual(self.record_path().read_bytes(), before)

    def test_consumption_record_tamper_detected(self):
        self.claim()
        record = json.loads(self.record_path().read_bytes())
        record["status"] = "UNUSED"
        self.record_path().write_bytes(e.canonical(record))
        with self.assertRaisesRegex(Rejected, "CONSUMPTION_TAMPER"):
            self.claim("execution-b")

    def test_partial_crashed_consumption_record_blocks_reuse(self):
        self.record_path().parent.mkdir(parents=True)
        self.record_path().write_bytes(b'{"partial":')
        with self.assertRaisesRegex(Rejected, "CONSUMPTION_TAMPER"):
            self.claim()
        self.assertEqual(self.record_path().read_bytes(), b'{"partial":')

    def test_claim_failure_before_record_does_not_create_execution(self):
        with patch.object(e, "_write_immutable", side_effect=OSError("synthetic disk failure")):
            with self.assertRaises(OSError):
                self.claim()
        self.assertFalse((self.base / "execution-a").exists())

    def test_different_artifacts_root_cannot_reuse_authorization(self):
        self.claim()
        with self.assertRaisesRegex(Rejected, "CONSUMPTION_ROOT_BINDING"):
            e.claim_authorization(self.auth, self.p, artifacts_root=self.base / "alternate-artifacts",
                                  execution_root=self.base / "execution-b", expected_previous_latest=None,
                                  clock=synthetic_clock)
        self.assertFalse((self.base / "alternate-artifacts").exists())

    def run_workers(self, executions, crash=False):
        context = multiprocessing.get_context("spawn")
        start = context.Event()
        queue = context.Queue()
        processes = [context.Process(target=consumption_worker,
            args=(str(self.root), str(self.base / name), start, queue, crash)) for name in executions]
        for process in processes:
            process.start()
        start.set()
        for process in processes:
            process.join(30)
            if process.is_alive():
                process.terminate()
                process.join(10)
                self.fail("synthetic claim process timed out")
        if crash:
            self.assertEqual([p.exitcode for p in processes], [23])
            results = []
        else:
            self.assertTrue(all(p.exitcode == 0 for p in processes))
            results = [queue.get(timeout=10) for _ in processes]
        queue.close()
        queue.join_thread()
        return results

    def test_cold_process_restart_second_claim_rejected(self):
        self.assertEqual(self.run_workers(["execution-a"]), ["CLAIMED"])
        self.assertEqual(self.run_workers(["execution-b"]), ["FIRST_REFRESH_AUTHORIZATION_ALREADY_CONSUMED"])

    def test_concurrent_claims_exactly_one_winner(self):
        result = self.run_workers(["execution-a", "execution-b"])
        self.assertCountEqual(result, ["CLAIMED", "FIRST_REFRESH_AUTHORIZATION_ALREADY_CONSUMED"])
        self.assertEqual(len(list((self.root / e.CONSUMPTION_NAMESPACE).glob("*.json"))), 1)

    def test_crash_after_claim_before_request_remains_consumed(self):
        self.run_workers(["execution-a"], crash=True)
        with self.assertRaisesRegex(Rejected, "ALREADY_CONSUMED"):
            self.claim("execution-b")
        self.assertFalse((self.base / "execution-a").exists())
        self.assertFalse((self.base / "execution-b").exists())


class HardeningPreacquisitionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "authoritative-artifacts"
        self.p = plan()
        self.auth = synthetic_authorization(self.root, self.p)
        self.capture_calls = 0
        self.store_calls = 0
        self.publication_calls = 0

    def capture(self, *args, **kwargs):
        self.capture_calls += 1
        raise AssertionError("no capture allowed")

    def create_store(self, *args, **kwargs):
        self.store_calls += 1
        raise RuntimeError("synthetic crash before request one")

    def publish(self, *args, **kwargs):
        self.publication_calls += 1
        raise AssertionError("no publication allowed")

    def execute(self, previous=None, execution="execution-a", auth=None, main_guard=lambda: None):
        with patch.object(e, "publish_fundamental_atomic", self.publish):
            return e.execute_authorized_first_refresh(self.p, universe(), self.auth if auth is None else auth,
                authority_root=self.base / "nonexistent-synthetic-authority", authority_sha256="0" * 64,
                execution_root=self.base / execution, captures={"FinMind": self.capture, "MOPS Official": self.capture},
                expected_previous_latest=previous, artifacts_root=self.root, dispatch_gate=None, clock=synthetic_clock,
                create_store=self.create_store, acquire=self.capture, main_guard=main_guard)

    def latest(self, value=b'{"synthetic":"current"}\n'):
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / e.LATEST_NAME).write_bytes(value)
        return e.refresh.current_identity(self.root / e.LATEST_NAME)

    def assert_no_start(self):
        self.assertEqual((self.capture_calls, self.store_calls, self.publication_calls), (0, 0, 0))
        self.assertFalse((self.root / e.CONSUMPTION_NAMESPACE).exists())
        self.assertFalse((self.base / "execution-a").exists())

    def test_actual_none_expected_none_reaches_claim_before_store(self):
        with self.assertRaisesRegex(RuntimeError, "synthetic crash"):
            self.execute()
        self.assertEqual((self.store_calls, self.capture_calls, self.publication_calls), (1, 0, 0))
        self.assertEqual(len(list((self.root / e.CONSUMPTION_NAMESPACE).glob("*.json"))), 1)

    def test_actual_identity_exact_match_passes_precheck(self):
        identity = self.latest()
        self.auth = synthetic_authorization(self.root, self.p, identity)
        with self.assertRaisesRegex(RuntimeError, "synthetic crash"):
            self.execute(previous=identity)
        self.assertEqual((self.store_calls, self.capture_calls), (1, 0))

    def test_latest_drift_rejected_before_acquisition(self):
        self.latest()
        with self.assertRaisesRegex(Rejected, "PREACQUISITION_LATEST_DRIFT"):
            self.execute()
        self.assert_no_start()

    def test_latest_changed_since_preflight_rejected(self):
        previous = self.latest()
        self.auth = synthetic_authorization(self.root, self.p, previous)
        self.latest(b'{"synthetic":"changed after preflight"}\n')
        with self.assertRaisesRegex(Rejected, "PREACQUISITION_LATEST_DRIFT"):
            self.execute(previous=previous)
        self.assert_no_start()

    def test_latest_drift_does_not_consume_authorization(self):
        self.latest()
        with self.assertRaisesRegex(Rejected, "PREACQUISITION_LATEST_DRIFT"):
            self.execute()
        self.assertFalse((self.root / e.CONSUMPTION_NAMESPACE).exists())

    def test_latest_drift_zero_capture_calls(self):
        self.latest()
        with self.assertRaisesRegex(Rejected, "PREACQUISITION_LATEST_DRIFT"):
            self.execute()
        self.assertEqual(self.capture_calls, 0)

    def test_latest_drift_zero_financial_requests(self):
        self.latest()
        with self.assertRaisesRegex(Rejected, "PREACQUISITION_LATEST_DRIFT"):
            self.execute()
        self.assertEqual((self.store_calls, self.capture_calls, self.publication_calls), (0, 0, 0))

    def test_latest_race_rechecked_under_claim_lock(self):
        from contextlib import contextmanager
        original = e._authorization_claim_lock
        @contextmanager
        def changed_before_lock(root):
            self.latest()
            with original(root):
                yield
        with patch.object(e, "_authorization_claim_lock", changed_before_lock):
            with self.assertRaisesRegex(Rejected, "PREACQUISITION_LATEST_DRIFT"):
                self.execute()
        self.assert_no_start()

    def test_missing_authorization_rejected_without_claim_or_store(self):
        with self.assertRaisesRegex(Rejected, "EXECUTION_NOT_AUTHORIZED"):
            self.execute(auth={})
        self.assert_no_start()

    def test_pending_authorization_never_runtime_accepted(self):
        pending = {**self.auth, "status": "PENDING_CONTROL_CENTER_AUTHORIZATION"}
        with self.assertRaisesRegex(Rejected, "EXECUTION_NOT_AUTHORIZED"):
            self.execute(auth=pending)
        self.assert_no_start()

    def test_invalid_seal_does_not_consume(self):
        self.auth["preexecution_seal_id"] = "wrong"
        rehash_authorization(self.auth)
        with self.assertRaisesRegex(Rejected, "AUTHORIZATION_BINDING"):
            self.execute()
        self.assert_no_start()

    def test_main_guard_precedes_claim(self):
        def reject_main():
            raise Rejected("synthetic wrong current main")
        with self.assertRaisesRegex(Rejected, "wrong current main"):
            self.execute(main_guard=reject_main)
        self.assert_no_start()

    def test_post_claim_crash_cannot_start_second_execution(self):
        with self.assertRaisesRegex(RuntimeError, "synthetic crash"):
            self.execute()
        with self.assertRaisesRegex(Rejected, "AUTHORIZATION_ALREADY_CONSUMED"):
            self.execute(execution="execution-b")
        self.assertEqual((self.store_calls, self.capture_calls, self.publication_calls), (1, 0, 0))
        self.assertFalse((self.base / "execution-b").exists())

    def test_final_publication_cas_preserved_after_precheck(self):
        previous = self.latest()
        e._actual_latest_precheck(self.root, previous)
        changed = self.latest(b'{"synthetic":"later concurrent publisher"}\n')
        with self.assertRaisesRegex(Rejected, "CAS_STALE_CURRENT"):
            e.publish_fundamental_atomic(minimal_snapshot(), artifacts_root=self.root, expected_previous_latest=previous)
        self.assertEqual(e.refresh.current_identity(self.root / e.LATEST_NAME), changed)


if __name__ == "__main__":
    unittest.main()
