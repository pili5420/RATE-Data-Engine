"""Real owners, fake transport, temporary keys and isolated synthetic Sidecar roots."""
from copy import deepcopy
from pathlib import Path
import os
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

from src.prospective_acquisition_recovery import offline_network_guard
sys.addaudithook(offline_network_guard)
from src import history_batch_authority as a
from src import history_batch_launcher as launch
from src.history_batch_orchestration import cold_acceptance, Orchestrator
from tests.batch_synthetic_support import Fixture, AT


class EndToEndTests(unittest.TestCase):
    def fixture(self, window=1):
        fixture = Fixture(window)
        self.addCleanup(fixture.close)
        return fixture

    def prove_window(self, count):
        started = time.perf_counter()
        f = self.fixture(count)
        old = a.sidecar.snapshot(f.campaign)
        f.start()
        result = f.run()
        self.assertEqual(result["status"], "SYNTHETIC_WINDOW_PASS")
        self.assertEqual(result["completed_ordinals"], list(range(2, count + 2)))
        self.assertEqual(f.calls, f.policy["maximum_requests"])
        after = a.sidecar.snapshot(f.campaign)
        self.assertTrue(all(after[k] == v for k, v in old.items()))
        replay = a.sidecar.replay(f.ctx, genesis_path=f.genesis, trusted_genesis_sha256=f.policy["genesis_file_sha256"],
            trusted_records=f.runner.records, expected_head=result["acceptance_head"])
        self.assertEqual(replay["accepted_chunks"], count + 1)
        self.assertEqual(replay["accepted_requests"], f.policy["maximum_requests"] + 10)
        self.assertEqual(len(list((f.ledger / "events").glob("*.json"))), count + 1)
        self.assertTrue(result["effective_No_Auto_Next"])
        self.assertEqual((result["real_authorizations"], result["live_requests"]), (0, 0))
        for ordinal in f.policy["ordinals"]:
            bundle = f.bundle(ordinal)
            self.assertEqual(len(list(Path(bundle["consumption_root"]).glob("*.json"))), 1)
            cold = a.load(f.base / "cold-proofs" / f"{ordinal:06}.json")["proof"]
            self.assertTrue(cold["isolated"])
            self.assertEqual(cold["network_attempts"], 0)
        sessions = []
        for ordinal in f.policy["ordinals"]:
            bundle = f.bundle(ordinal)
            first = a.load(sorted((Path(bundle["execution_root"]) / "intents").glob("*.json"))[0])
            dispatch = first["dispatch"]
            self.assertGreaterEqual(dispatch["monotonic_timestamp"] - dispatch["previous_wait_anchor_monotonic"], 13)
            self.assertEqual(dispatch["measurement_boundary"], "CAPTURE_CALL_NOT_HTTP_WIRE_START")
            sessions.append({"ordinal": ordinal, "session_identity": dispatch["session_identity"],
                "first_anchor_gap": dispatch["monotonic_timestamp"] - dispatch["previous_wait_anchor_monotonic"]})
        self.assertEqual(len({s["session_identity"] for s in sessions}), count)
        proof_dir = os.environ.get("RATE_BATCH_SYNTHETIC_PROOF_DIR")
        paths = [p for p in f.base.rglob("*") if p.is_file()]
        metrics = {"observed_wall_seconds": time.perf_counter() - started,
            "retained_synthetic_bytes": sum(p.stat().st_size for p in paths), "retained_files": len(paths),
            "maximum_path_characters": max(len(str(p.resolve())) for p in paths),
            "live_network_latency_measured": False}
        if os.name == "nt":
            self.assertLessEqual(metrics["maximum_path_characters"], 259)
        if proof_dir and count in (3, 10):
            proof = {"material_scope": a.SCOPE, "window_chunks": count, "result": result,
                "mock_transport_calls": f.calls, "expected_mock_calls": f.policy["maximum_requests"],
                "accepted_chunks_including_synthetic_bootstrap": replay["accepted_chunks"],
                "source_producer_main": f.policy["main_sha"], "sidecar_head": f.policy["sidecar_head"],
                "issuer_pid": f.client.public["pid"], "runner_pid": os.getpid(), "private_key_serialized": False,
                "runner_events": f.runner.journal.replay(f.runner.head),
                "resource_measurements": metrics,
                "distinct_dispatch_sessions": sessions,
                "cold_proofs": [a.load(f.base / "cold-proofs" / f"{n:06}.json") for n in f.policy["ordinals"]]}
            a.put(Path(proof_dir) / f"SYNTHETIC_{count}_CHUNK_ACCEPTANCE.json", proof)
        calls = f.calls
        with self.assertRaises(ValueError):
            f.client.call("AUTHORIZE", ordinal=count + 2, predecessor_head=result["acceptance_head"], at=AT)
        self.assertEqual(f.calls, calls)
        return f

    def test_three_chunk_pilot_full_owner_e2e(self):
        self.prove_window(3)

    def test_ten_chunk_window_full_owner_e2e(self):
        self.prove_window(10)

    def test_no_second_window_or_repeat_execution(self):
        f = self.prove_window(1)
        calls = f.calls
        with self.assertRaisesRegex(ValueError, "NO_RETRY_OR_RESUME"):
            f.run()
        self.assertEqual(f.calls, calls)

    def test_global_single_release_before_any_claim(self):
        f = self.fixture(); f.start()
        f.client.call("AUTHORIZE", ordinal=2, predecessor_head=f.policy["start_head"], at=AT)
        with self.assertRaisesRegex(ValueError, "CHILD_FAILED"):
            f.client.call("AUTHORIZE", ordinal=2, predecessor_head=f.policy["start_head"], at=AT)
        self.assertFalse(Path(f.bundle(2)["consumption_root"]).exists())
        self.assertEqual(f.calls, 0)

    def test_out_of_window_release_has_no_claim(self):
        f = self.fixture(); f.start()
        with self.assertRaisesRegex(ValueError, "CHILD_FAILED"):
            f.client.call("AUTHORIZE", ordinal=3, predecessor_head=f.policy["start_head"], at=AT)
        self.assertEqual(f.calls, 0)
        self.assertFalse(Path(f.bundle(2)["execution_root"]).exists())

    def test_issuer_rebuilds_seal_not_runner_value(self):
        f = self.fixture(); f.start()
        released = f.client.call("AUTHORIZE", ordinal=2, predecessor_head=f.policy["start_head"], at=AT)
        a.h.validate_authorization(released["artifact"], f.bundle(2)["seal"])
        bad = deepcopy(f.bundle(2)["seal"]); bad["plan_sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            a.h.validate_authorization(released["artifact"], bad)

    def test_pending_candidate_is_not_authorized(self):
        f = self.fixture()
        bundle = f.bundle(2)
        with self.assertRaises(ValueError):
            a.h.validate_authorization(bundle["candidate"], bundle["seal"])

    def test_execution_pass_without_acceptance_cannot_release_next(self):
        f = self.fixture(3); f.start()
        def crash(stage, ordinal):
            if stage == "after_execution":
                raise RuntimeError("SYNTHETIC_FAILURE_BEFORE_ACCEPTANCE")
        with self.assertRaises(RuntimeError):
            f.run(fault=crash)
        self.assertFalse(Path(f.bundle(3)["consumption_root"]).exists())
        self.assertEqual(len(list((f.ledger / "events").glob("*.json"))), 1)

    def test_unknown_transport_outcome_stops_no_resend(self):
        f = self.fixture(3); f.start()
        def unknown(entry):
            f.calls += 1
            raise OSError("SYNTHETIC_UNKNOWN_OUTCOME")
        with self.assertRaises(ValueError):
            f.run(transport=unknown)
        self.assertEqual(f.calls, 1)
        self.assertFalse(Path(f.bundle(3)["execution_root"]).exists())
        self.assertTrue((Path(f.bundle(2)["execution_root"]) / "STOP.json").exists())
        with self.assertRaises(ValueError):
            f.run()

    def test_http_failure_stops_all_later_calls(self):
        f = self.fixture(3); f.start()
        def blocked(entry):
            response = f.capture(entry); response["http_status"] = 403
            return response
        with self.assertRaises(ValueError):
            f.run(transport=blocked)
        self.assertEqual(f.calls, 1)
        self.assertFalse(Path(f.bundle(3)["consumption_root"]).exists())

    def test_external_ack_unknown_preserves_append_without_advancing(self):
        f = self.fixture(3); f.start()
        def fail(stage, ordinal):
            if stage == "before_external_ack":
                raise RuntimeError("SYNTHETIC_UNKNOWN_ACK")
        with self.assertRaises(RuntimeError):
            f.run(fault=fail)
        self.assertEqual(len(list((f.ledger / "events").glob("*.json"))), 2)
        self.assertEqual(f.runner.completed, [])
        self.assertFalse(Path(f.bundle(3)["consumption_root"]).exists())
        self.assertTrue((f.runner.root / "HALTED.json").exists())

    def test_revocation_before_release(self):
        f = self.fixture(); f.start()
        f.client.call("REVOKE", at=AT)
        with self.assertRaises(ValueError):
            f.run()
        self.assertEqual(f.calls, 0)
        self.assertFalse(Path(f.bundle(2)["consumption_root"]).exists())

    def test_no_sign_rpc_and_no_private_key_export(self):
        f = self.fixture(); f.start()
        self.assertFalse(f.client.public["private_key_serialized"])
        self.assertNotEqual(f.client.public["pid"], os.getpid())
        self.assertFalse(hasattr(f.client, "sign"))
        with self.assertRaisesRegex(ValueError, "RPC_NOT_ALLOWED"):
            f.client.call("SIGN", at=AT, payload={})
        self.assertEqual(f.calls, 0)

    def test_registry_mutation_cannot_self_pin_during_initialize(self):
        f = self.fixture()
        f.registry["keys"]["issuer"]["epoch"] = 2
        with self.assertRaisesRegex(ValueError, "EXTERNAL_KEY_REGISTRY_PIN"):
            f.start()
        self.assertEqual(f.calls, 0)
        self.assertFalse(Path(f.bundle(2)["consumption_root"]).exists())

    def test_registry_mutation_after_initialize_is_rejected_before_claim(self):
        f = self.fixture(); f.start()
        f.registry["keys"]["issuer"]["epoch"] = 2
        with self.assertRaisesRegex(ValueError, "EXTERNAL_KEY_REGISTRY_PIN"):
            f.run()
        self.assertEqual(f.calls, 0)
        self.assertFalse(Path(f.bundle(2)["consumption_root"]).exists())

    def test_bootstrap_missing_record_blocks_before_release(self):
        f = self.fixture(); f.record1.unlink()
        with self.assertRaises(ValueError):
            f.start()
        self.assertEqual(f.calls, 0)

    def test_second_orchestrator_writer_rejected(self):
        f = self.fixture(); f.start()
        lock = f.base / "orchestrator-lock"; lock.mkdir()
        with a.h.exclusive_scan(lock):
            with self.assertRaisesRegex(RuntimeError, "WRITER_ALREADY_ACTIVE"):
                f.run()
        self.assertEqual(f.calls, 0)

    def test_orchestrator_and_owner_locks_do_not_deadlock(self):
        f = self.prove_window(1)
        self.assertTrue((f.base / "orchestrator-lock/.scan.lock").exists())
        self.assertTrue((f.campaign / ".scan.lock").exists())
        self.assertTrue((f.ledger / ".scan.lock").exists())

    def test_source_head_and_owner_binding_readonly(self):
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=a.h.ROOT).decode().strip()
        proof = launch.verify_checkout(a.h.ROOT, head, a.h.owners())
        self.assertEqual(proof["head"], head)
        with self.assertRaises(ValueError):
            launch.verify_checkout(a.h.ROOT, "0" * 40, a.h.owners())
        pins = a.h.owners(); pins[next(iter(pins))] = "0" * 64
        with self.assertRaises(ValueError):
            launch.verify_checkout(a.h.ROOT, head, pins)

    def test_real_launch_always_rejected(self):
        with self.assertRaisesRegex(ValueError, "NOT_AUTHORIZED"):
            launch.real_launch()

    def test_global_issuer_root_cannot_be_replaced(self):
        f = self.fixture()
        f.policy["roots"]["issuer"] = str(f.base / "different-issuer")
        with self.assertRaises(ValueError):
            f.start()
        self.assertFalse((f.base / "different-issuer").exists())
        self.assertFalse(Path(f.bundle(2)["consumption_root"]).exists())

    def test_restart_overlapping_window_nonce_cannot_reissue(self):
        f = self.prove_window(1)
        f.client.close()
        f.client = launch.IssuerClient(f.base)
        f.registry["keys"]["issuer"]["public_key"] = f.client.public["issuer_public_key"]
        f.registry["keys"]["witness"]["public_key"] = f.client.public["witness_public_key"]
        with self.assertRaises(ValueError):
            f.start()
        self.assertEqual(f.calls, 1)

    def test_signed_packet_tamper_before_claim(self):
        f = self.fixture(); f.start()
        released = f.client.call("AUTHORIZE", ordinal=2, predecessor_head=f.policy["start_head"], at=AT)
        released["witness_head"] = "0" * 64
        with self.assertRaises(ValueError):
            f.runner.packet(released, "AUTHORIZATION")
        self.assertEqual(f.calls, 0)
        self.assertFalse(Path(f.bundle(2)["consumption_root"]).exists())

    def test_issuer_cannot_accept_without_original_result(self):
        f = self.fixture(); f.start()
        f.client.call("AUTHORIZE", ordinal=2, predecessor_head=f.policy["start_head"], at=AT)
        with self.assertRaises(ValueError):
            f.client.call("ACCEPT", ordinal=2, at=AT)
        self.assertFalse(Path(f.bundle(2)["consumption_root"]).exists())

    def test_append_stale_expected_head_halts_no_duplicate_credit(self):
        f = self.fixture(3); f.start()
        def stale(stage, ordinal):
            if stage == "before_append":
                f.runner.accepted_head = "0" * 64
        with self.assertRaises(ValueError):
            f.run(fault=stale)
        self.assertEqual(len(list((f.ledger / "events").glob("*.json"))), 1)
        self.assertFalse(Path(f.bundle(3)["consumption_root"]).exists())

    def test_cold_acceptance_nonzero_exit_rejected(self):
        f = self.fixture()
        bad = subprocess.CompletedProcess([], 1, b"", b"SYNTHETIC_CHILD_FAILURE")
        with patch("src.history_batch_orchestration.subprocess.run", return_value=bad):
            with self.assertRaisesRegex(ValueError, "CHILD_FAILED"):
                cold_acceptance(f.ctx, f.policy, f.records, f.policy["start_head"], f.base / "unused.json")
        self.assertFalse(Path(f.bundle(2)["consumption_root"]).exists())

    def test_cold_acceptance_wrong_head_rejected(self):
        f = self.fixture()
        bad = subprocess.CompletedProcess([], 0, a.e.canonical({"status": "PASS", "head": "0" * 64}), b"")
        with patch("src.history_batch_orchestration.subprocess.run", return_value=bad):
            with self.assertRaisesRegex(ValueError, "BINDING_MISMATCH"):
                cold_acceptance(f.ctx, f.policy, f.records, f.policy["start_head"], f.base / "unused.json")

    def test_malformed_or_extra_root_policy_fails_before_claim(self):
        f = self.fixture()
        f.policy["roots"]["issuer"] = f.policy["roots"]["runner"]
        with self.assertRaises(ValueError):
            f.start()
        self.assertEqual(f.calls, 0)

    def test_genesis_pin_tamper_rejected_before_claim(self):
        f = self.fixture(); f.genesis.write_bytes(b"{}")
        with self.assertRaises(ValueError):
            f.start()
        self.assertFalse(Path(f.bundle(2)["consumption_root"]).exists())

    def test_prior_stop_blocks_before_claim(self):
        f = self.fixture()
        a.put(Path(f.bundle(1)["execution_root"]) / "STOP.json", {"status": "SYNTHETIC_STOP"})
        with self.assertRaises(ValueError):
            f.start()
        self.assertFalse(Path(f.bundle(2)["consumption_root"]).exists())

    def test_endpoint_override_rejected_by_original_plan_owner(self):
        f = self.fixture()
        plan = deepcopy(f.bundle(2)["plan"])
        plan["entries"][0]["endpoint"] = "https://invalid.example/SYNTHETIC"
        with self.assertRaises(ValueError):
            a.h.validate_plan(plan)
        self.assertEqual(f.calls, 0)


def prior_tamper(family, filename=None):
    def test(self):
        f = self.fixture()
        run = Path(f.bundle(1)["execution_root"])
        target = run / filename if filename else next((run / family).iterdir())
        target.write_bytes(b"{}")
        with self.assertRaises(ValueError):
            f.start()
        self.assertEqual(f.calls, 0)
        self.assertFalse(Path(f.bundle(2)["consumption_root"]).exists())
    return test


for family, filename in (("raw", None), ("receipts", None), ("intents", None), ("events", None),
                         ("checkpoints", None), ("result", "RESULT.json"), ("consumption", "consumption.json")):
    setattr(EndToEndTests, "test_prior_" + family + "_tamper_before_claim", prior_tamper(family, filename))


def fail_at(stage):
    def test(self):
        f = self.fixture(3); f.start()
        def inject(current, ordinal):
            if current == stage:
                raise RuntimeError("SYNTHETIC_CRASH_" + stage)
        with self.assertRaises(RuntimeError):
            f.run(fault=inject)
        self.assertTrue((f.runner.root / "HALTED.json").exists())
        self.assertFalse(Path(f.bundle(3)["execution_root"]).exists())
        with self.assertRaises(ValueError):
            f.run()
    return test


for stage in ("before_release", "before_claim", "after_cold", "before_append", "after_append", "after_external_ack"):
    setattr(EndToEndTests, "test_crash_" + stage + "_no_resume", fail_at(stage))


def issuer_crash(stage):
    def test(self):
        f = self.fixture(3)
        f.start(synthetic_fault_stage=stage)
        if stage.startswith("revocation_"):
            with self.assertRaises(ValueError):
                f.client.call("REVOKE", at=AT)
            with self.assertRaises(ValueError):
                f.run()
        else:
            with self.assertRaises(ValueError):
                f.run()
        preclaim = stage.startswith(("reserve_", "authorization_", "revocation_"))
        self.assertEqual(Path(f.bundle(2)["consumption_root"]).exists(), not preclaim)
        self.assertEqual(f.calls, 0 if preclaim else f.policy["per_chunk_requests"][0])
        self.assertFalse(Path(f.bundle(3)["consumption_root"]).exists())
        self.assertFalse(Path(f.bundle(3)["execution_root"]).exists())
        self.assertTrue(list((f.base / "issuer" / "intents").glob("*.json")))
        self.assertTrue((f.runner.root / "HALTED.json").exists())
        with self.assertRaises(ValueError):
            f.run()
    return test


ISSUER_CRASH_STAGES = ["reserve_" + boundary for boundary in ("intents", "events", "checkpoints")]
ISSUER_CRASH_STAGES += [purpose + journal + boundary
    for purpose in ("authorization", "acceptance", "head_ack", "revocation")
    for journal in ("_", "_witness_") for boundary in ("intents", "events", "checkpoints")]
for stage in ISSUER_CRASH_STAGES:
    setattr(EndToEndTests, "test_issuer_crash_" + stage, issuer_crash(stage))
