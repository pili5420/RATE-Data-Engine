"""Synthetic only: execute the real CER078 CLI, engine, persistence and publisher."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest

from src import public_official_partial_valid as p
from src import cer078_evening_1930 as evening
from src.cer074_acceptance import atomic_write_json, sha256
from src.production_live_state import PERSIST_NAME, STATE_NAME, MANIFEST_NAME, file_hash, load_live_state, read_object
from scripts.publish_production_state_latest import publish_state
from scripts.build_production_source_bundle_from_official import assemble_production_bundle, _normalize_dataset_entry
from tests import test_public_official_partial_valid as partial_tests
from tests import test_production_scheduler_change_control as source_tests


class PartialToEveningAcceptanceTests(unittest.TestCase):
    setUp = partial_tests.PublicOfficialPartialValidTests.setUp
    fetch = partial_tests.PublicOfficialPartialValidTests.fetch
    bundle = partial_tests.PublicOfficialPartialValidTests.bundle
    execute = partial_tests.PublicOfficialPartialValidTests.execute
    publish = partial_tests.PublicOfficialPartialValidTests.publish
    chain = partial_tests.PublicOfficialPartialValidTests.chain
    midnight_state = partial_tests.PublicOfficialPartialValidTests.midnight_state

    def prepare(self):
        decision = copy.deepcopy(self.previous["decision"])
        self.symbols = ["TEST"] + [str(1000 + i) for i in range(29)]
        decision["records"] = [{"symbol": s, "Fundamental": i, "Stage_inputs": {"price": 9999},
            "M7": 80, "MHE": 70} for i, s in enumerate(self.symbols)]
        for key in ("top50", "short_top30", "long_top30"):
            decision[key] = [{"symbol": s, "rank": i + 1} for i, s in enumerate(self.symbols)]
        persist, material = self.support.wrap_decision(decision, {"current_state_id": decision["previous_state_id"]}, "07:30")
        self.previous = material["decision_state"]
        atomic_write_json(self.previous_dir / STATE_NAME, material)
        atomic_write_json(self.previous_dir / PERSIST_NAME, persist)
        manifest = read_object(self.previous_dir / MANIFEST_NAME)
        manifest.update(current_state_id=persist["current_state_id"], current_state_hash=persist["current_state_hash"],
            files={n: file_hash(self.previous_dir / n) for n in (STATE_NAME, PERSIST_NAME)})
        atomic_write_json(self.previous_dir / MANIFEST_NAME, manifest)

    def eod_bundle(self):
        helper = source_tests.ProductionSchedulerChangeControlTests()
        rows = [{"symbol": s, "Code": s, "trade_date": self.day, "trading_date": self.day,
            "open": 120 + i, "high": 123 + i, "low": 119 + i, "close": 122 + i, "volume": 1000 + i,
            **helper._technical_source(i + 1)} for i, s in enumerate(self.symbols)]
        sources = []
        for domain in ("market_daily", "benchmark", "fundamental", "institutional", "large_holder", "trading_metadata"):
            entry = {"dataset_id": "synthetic-" + domain, "domain": domain, "authority": "TWSE",
                "parser": "SYNTHETIC-ENGINEERING-V1", "endpoint": "https://example.invalid/" + domain}
            payload = [{**rows[0], "symbol": "TAIEX"}] if domain == "benchmark" else rows
            normalized = _normalize_dataset_entry(entry, {"status": "PASS", "raw_payload": payload,
                "body_sha256": sha256(payload), "retrieval_timestamp": p.now()}, self.day)
            self.assertEqual(normalized["normalization_status"], "PASS")
            sources.append(normalized)
        bundle, _, _ = assemble_production_bundle(normalized_sources=sources, trading_date=self.day, cadence="19:30",
            retrieval_timestamp=p.now(), universe_binding={"validation_status": "PASS", "expected_universe": self.symbols,
                "universe_binding_hash": sha256(self.symbols)}, freshness_matrix={"validation_status": "PASS"})
        bundle["synthetic_only"] = True
        return bundle

    def evening_cli(self, source, *, reset=False):
        previous = self.artifacts / "production_state/live" / self.day / "1200" / PERSIST_NAME
        command = [sys.executable, "-B", str(p.ROOT / "scripts/run_cer078_evening_1930_acceptance.py"),
            "--continue-partial-state", "--source-bundle", str(source), "--output-dir", str(self.root / "out1930"),
            "--state-root", str(self.runtime)]
        for number in ("074", "075", "076", "077"):
            command.extend(["--cer" + number + "-persisted-evidence", str(previous)])
        if reset:
            command.append("--reset-state-root")
        return subprocess.run(command, cwd=p.ROOT, capture_output=True, text=True)

    def start(self):
        self.prepare()
        partial_tests.PublicOfficialPartialValidTests.test_actual_cli_opt_in_0930_to_1200_cold_process(self)
        self.source = self.root / "eod.json"
        atomic_write_json(self.source, self.eod_bundle())

    def publish_evening(self):
        return publish_state(persist_evidence_path=self.root / "out1930/RATE_CER078_PERSIST_RESULT_EVIDENCE.json",
            trading_date=self.day, cadence="19:30", artifacts_root=self.artifacts, state_root=self.runtime,
            workflow_run_id="302", workflow_job_id="402", event_name="schedule", ref="refs/heads/main", commit_sha="d" * 40)

    def test_full_four_cadence_cli_eod_acceptance(self):
        self.start()
        before = {str(f): file_hash(f) for f in self.artifacts.rglob("*") if f.is_file()}
        result = self.evening_cli(self.source)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.publish_evening()["validation_status"], "PASS")
        states = [load_live_state(self.artifacts / "production_state", self.day, c)["state"]
            for c in ("07:30", "09:30", "12:00", "19:30")]
        for previous, current in zip(states, states[1:]):
            self.assertEqual(current["previous_state_id"], previous["current_state_id"])
            for key in ("roy_portfolio", "ai_paper_portfolio", "transaction_ledger", "top50", "short_top30", "long_top30"):
                self.assertEqual(current["decision"][key], previous["decision"][key])
        for state in states[1:3]:
            self.assertEqual(state["decision"]["report_runtime_status"], "PARTIAL_VALID")
            self.assertTrue(all(r["current_price"] is None for r in state["decision"]["records"]))
        final = states[-1]["decision"]
        self.assertFalse(final["evening_closure"]["state_reinitialized"])
        self.assertEqual(final["full_production_acceptance"], "NOT_ALLOWED")
        self.assertFalse(final["full_production_pass"])
        self.assertEqual(final["market_intraday_price_gate"], "BLOCKED_EXTERNAL")
        self.assertFalse(final["fallback_allowed"])
        self.assertEqual([r["Evening_evidence"]["close"] for r in final["records"]], list(range(122, 152)))
        self.assertTrue(all(r["current_price"] is None for r in final["records"]))
        for path, digest in before.items():
            if Path(path).name != "RATE_PRODUCTION_STATE_LATEST.json":
                self.assertEqual(file_hash(path), digest)
        # Cold child loads the published state, not the parent's in-memory objects.
        code = "from src.production_live_state import load_live_state; import sys; print(load_live_state(sys.argv[1],sys.argv[2],'19:30')['state']['current_state_id'])"
        cold = subprocess.run([sys.executable, "-B", "-c", code, str(self.artifacts / "production_state"), self.day],
            cwd=p.ROOT, capture_output=True, text=True)
        self.assertEqual(cold.returncode, 0, cold.stderr)
        self.assertEqual(cold.stdout.strip(), states[-1]["current_state_id"])
        self.assertEqual(self.evening_cli(self.source).returncode, 0)
        self.assertEqual(self.publish_evening()["idempotency_result"], "IDEMPOTENT_NOOP")
        self.proof = read_object(self.root / "out1930/RATE_PARTIAL_TO_EOD_FULL_ACCEPTANCE.json")

    def rejected(self, mutate, reason):
        self.start()
        bundle = read_object(self.source)
        mutate(bundle)
        atomic_write_json(self.source, bundle)
        result = self.evening_cli(self.source)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(reason, read_object(self.root / "out1930/RATE_PARTIAL_TO_EOD_FULL_ACCEPTANCE.json")["reason"])
        self.assertFalse((self.runtime / "decision_state/1930").exists())

    def test_no_eod_price_fallback(self):
        self.rejected(lambda b: b.pop("eod_close_records"), "EOD_HASH_INVALID")

    def test_wrong_date(self):
        self.rejected(lambda b: b.update(trading_date="2026-10-08"), "EOD_IDENTITY_INVALID")

    def test_partial_bundle_cannot_be_formal_eod(self):
        self.rejected(lambda b: b.update(artifact=p.KIND), "EOD_IDENTITY_INVALID")

    def test_duplicate_or_missing_eod_close(self):
        def mutate(b):
            b["eod_close_records"][-1] = copy.deepcopy(b["eod_close_records"][0])
            b["eod_close_content_sha256"] = sha256(b["eod_close_records"])
        self.rejected(mutate, "EOD_COVERAGE_INVALID")

    def test_nonfinite_or_nonpositive_price(self):
        def mutate(b):
            b["eod_close_records"][0]["close"] = 0
            b["eod_close_content_sha256"] = sha256(b["eod_close_records"])
        self.rejected(mutate, "EOD_CLOSE_INVALID")

    def test_eod_source_binding_tamper(self):
        def mutate(b):
            b["eod_close_records"][0]["body_sha256"] = "e" * 64
            b["eod_close_content_sha256"] = sha256(b["eod_close_records"])
        self.rejected(mutate, "EOD_SOURCE_BINDING_INVALID")

    def test_invalid_eod_required_domain(self):
        self.rejected(lambda b: b["datasets_present"].remove("institutional"), "EOD_DATA_GATE_FAIL")

    def test_reset_forbidden(self):
        self.start()
        self.assertNotEqual(self.evening_cli(self.source, reset=True).returncode, 0)
        self.assertIn("RESET_FORBIDDEN", read_object(self.root / "out1930/RATE_PARTIAL_TO_EOD_FULL_ACCEPTANCE.json")["reason"])

    def test_fake_intraday_price_still_rejected(self):
        self.start()
        previous = load_live_state(self.artifacts / "production_state", self.day, "12:00")["state"]
        previous["decision"]["records"][0]["current_price"] = 9999
        with self.assertRaisesRegex(RuntimeError, "CURRENT_PRICE_FORBIDDEN"):
            evening._partial_eod_snapshot(previous, read_object(self.source))

    def test_snapshot_mutation_rejected_by_existing_evening_engine(self):
        self.start()
        previous = load_live_state(self.artifacts / "production_state", self.day, "12:00")["state"]
        bundle = read_object(self.source)
        snapshot = evening._partial_eod_snapshot(previous, bundle)
        snapshot["records"][0]["Fundamental"] = 99999
        with self.assertRaisesRegex(RuntimeError, "SNAPSHOT_MISMATCH"):
            evening.run_evening_decision(snapshot, previous, bundle)

    def test_wrong_previous_cadence_rejected(self):
        self.start()
        previous = load_live_state(self.artifacts / "production_state", self.day, "09:30")["state"]
        with self.assertRaisesRegex(RuntimeError, "PREDECESSOR_INVALID"):
            evening._partial_eod_snapshot(previous, read_object(self.source))

    def test_eod_cannot_promote_full_acceptance(self):
        self.start()
        self.assertEqual(self.evening_cli(self.source).returncode, 0)
        persist = read_object(self.root / "out1930/RATE_CER078_PERSIST_RESULT_EVIDENCE.json")
        path = self.runtime / "decision_state/1930" / (persist["current_state_id"] + ".json")
        decision = read_object(path)["decision_state"]["decision"]
        decision["full_production_acceptance"] = "FULL_PRODUCTION_PASS"
        with self.assertRaisesRegex(RuntimeError, "PROMOTION_FORBIDDEN"):
            evening.validate_partial_evening_state(decision)

    def test_stale_eod_source_fails_closed(self):
        def mutate(b):
            b["source_provenance"]["retrieval_timestamp"] = "2026-01-01T00:00:00Z"
        self.rejected(mutate, "EOD_DATA_GATE_FAIL")


if __name__ == "__main__":
    unittest.main()
