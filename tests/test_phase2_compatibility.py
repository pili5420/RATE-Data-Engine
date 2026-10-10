"""Phase A synthetic integration only; never publish to repository artifacts."""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from src.cer074_acceptance import atomic_write_json
from src import phase2_production as phase2
from src.production_live_state import load_live_state, file_hash, PERSIST_NAME
from tests import test_phase2_production as fixtures
from tests import test_public_official_partial_valid as public_fixtures


ROOT = Path(__file__).resolve().parents[1]


def chain_proof(output):
    helper = fixtures.Phase2ProductionTests()
    helper.setUp()
    try:
        helper.publish(helper.bundle())
        day = "2026-10-06"
        previous = load_live_state(helper.state_root, helper.day, "19:30")["state"]
        carried = {"carried_state_id": previous["current_state_id"],
            "carried_state_hash": previous["decision_payload_hash"], "intraday_feed": None}
        material = phase2.bind_input_material(carried, helper.catalogue, previous,
            trading_date=day, cadence="07:30", authority=fixtures.AUTHORITY)
        morning, _ = helper.publish(phase2.bundle_from_material(material, helper.catalogue, helper.state_root))
        public = public_fixtures.PublicOfficialPartialValidTests()
        public.root, public.artifacts, public.runtime = helper.root, helper.artifacts, helper.root / "public-runtime"
        public.day, public.calls = day, []
        public.previous = morning
        public.predecessor = helper.state_root / "live" / day / "0730" / PERSIST_NAME
        def fetch(endpoint):
            response = public.fetch(endpoint)
            rows = json.loads(response["raw_bytes"])
            for row in rows:
                row["\u51fa\u8868\u65e5\u671f"] = "1151006"
            return {**response, "raw_bytes": json.dumps(rows, ensure_ascii=False).encode()}
        for cadence, predecessor in (("09:30", "0730"), ("12:00", "0930")):
            source, _ = public.bundle(cadence, fetch)
            persist = public.execute(cadence, previous=helper.state_root / "live" / day / predecessor / PERSIST_NAME, source=source)
            public.assertEqual(public.publish(cadence, persist)["validation_status"], "PASS")
        midday = load_live_state(helper.state_root, day, "12:00")["state"]
        catalogue = fixtures.fake_catalogue(day)
        material = phase2.bind_input_material(fixtures.raw_fixture(day), catalogue, midday,
            trading_date=day, cadence="19:30", authority=fixtures.AUTHORITY)
        bundle = phase2.bundle_from_material(material, catalogue, helper.state_root)
        source = helper.root / "eod-phase2.json"
        atomic_write_json(source, bundle)
        before = {str(p): file_hash(p) for p in helper.artifacts.rglob("*") if p.is_file()}
        env = {**os.environ, "GITHUB_REF": "refs/heads/main", "GITHUB_EVENT_NAME": "schedule",
            "GITHUB_RUN_ID": "100", "GITHUB_SHA": fixtures.AUTHORITY["commit_sha"],
            "ACTIONS_JOB_ID": "200", "EXECUTION_AUTHORITY": "MAIN_ONLY"}
        command = [sys.executable, "-B", str(ROOT / "scripts/run_phase2_production.py"),
            "--cadence", "19:30", "--source-bundle", str(source),
            "--canonical-state-root", str(helper.state_root), "--state-root", str(helper.root / "cold-runtime"),
            "--output-dir", str(helper.root / "cold-output"), "--actions-job-id", "200",
            "--expected-previous-state-evidence", str(helper.state_root / "live" / day / "1200" / PERSIST_NAME)]
        cold = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True)
        helper.assertEqual(cold.returncode, 0, cold.stdout + cold.stderr)
        final, _ = helper.publish(bundle)
        helper.assertEqual(json.loads(cold.stdout)["current_state_id"], final["current_state_id"])
        states = [load_live_state(helper.state_root, day, cadence)["state"] for cadence in ("07:30", "09:30", "12:00", "19:30")]
        for previous, current in zip(states, states[1:]):
            helper.assertEqual(current["previous_state_id"], previous["current_state_id"])
            for key in ("roy_portfolio", "ai_paper_portfolio", "transaction_ledger"):
                helper.assertEqual(current["decision"][key], previous["decision"][key])
        for state in states[1:3]:
            helper.assertEqual(state["decision"]["report_runtime_status"], "PARTIAL_VALID")
            helper.assertEqual(state["decision"]["full_production_acceptance"], "NOT_ALLOWED")
            helper.assertTrue(all(r["current_price"] is None for r in state["decision"]["records"]))
        helper.assertEqual(final["decision"]["phase2_partial_eod_closure"]["new_intraday_fills"], 0)
        helper.assertFalse(final["decision"]["full_production_pass"])
        mutable_pointers = {"RATE_PRODUCTION_STATE_LATEST.json", "RATE_PRODUCTION_SOURCE_BUNDLE_LATEST.json",
            "RATE_THIN_WORK_PRODUCTION_BUNDLE_MANIFEST_LATEST.json"}
        for path, digest in before.items():
            if Path(path).name not in mutable_pointers:
                helper.assertEqual(file_hash(path), digest, path)
        cold_read = subprocess.run([sys.executable, "-B", "-c",
            "from src.production_live_state import load_live_state; import sys; print(load_live_state(sys.argv[1],sys.argv[2],'19:30')['state']['current_state_id'])",
            str(helper.state_root), day], cwd=ROOT, capture_output=True, text=True)
        helper.assertEqual(cold_read.returncode, 0, cold_read.stderr)
        helper.assertEqual(cold_read.stdout.strip(), final["current_state_id"])
        result = {"scope": "SYNTHETIC_ONLY_NOT_PRODUCTION_ACCEPTANCE", "real_source_requests": 0,
            "states": [{"cadence": state["decision"]["cadence"], "current_state_id": state["current_state_id"],
                "previous_state_id": state["previous_state_id"], "report_runtime_status": state["decision"]["report_runtime_status"]} for state in states],
            "four_cadence_continuity": "PASS", "cold_eod_runtime": "PASS", "cold_published_state_read": "PASS",
            "account_ledger_continuity": "PASS", "new_intraday_fills": 0,
            "full_production_acceptance": "NOT_ALLOWED", "fallback_allowed": False,
            "market_intraday_price_gate": "BLOCKED_EXTERNAL",
            "synthetic_mutable_pointers": sorted(mutable_pointers),
            "existing_synthetic_files_unchanged": sum(Path(path).name not in mutable_pointers for path in before)}
        if output is not None:
            output = Path(output)
            output.mkdir(parents=True, exist_ok=True)
            shutil.copytree(helper.artifacts, output / "synthetic-state-chain")
            atomic_write_json(output / "PHASE2_FOUR_CADENCE_PROOF.json", result)
        return result
    finally:
        helper.doCleanups()


class Phase2CompatibilityTests(unittest.TestCase):
    def test_full_cold_four_cadence_chain(self):
        self.assertEqual(chain_proof(None)["four_cadence_continuity"], "PASS")

    def test_intraday_workflows_are_byte_identical_to_main(self):
        for slot in ("0930", "1200"):
            path = f".github/workflows/rate_production_{slot}_scheduler.yml"
            self.assertEqual((ROOT / path).read_bytes(), subprocess.check_output(["git", "show", fixtures.BASE + ":" + path], cwd=ROOT))

    def test_registry_eps_contract_soak_and_model_owners_unchanged(self):
        paths = ["config/RATE_EXTERNAL_PRODUCTION_DEPENDENCIES.json", "config/RATE_FOUR_CADENCE_REPORT_SOAK_V1.json",
            "src/report_production_soak.py", "src/cer081_unattended_soak.py", "src/public_official_partial_valid.py",
            "src/sources/fundamental_history.py", "src/feature_math.py", "src/rate_logic.py", "src/full_market_catalogue.py"]
        for path in paths:
            self.assertEqual((ROOT / path).read_bytes(), subprocess.check_output(["git", "show", fixtures.BASE + ":" + path], cwd=ROOT))

    def test_phase_a_does_not_grant_activation(self):
        contract = phase2.contract()
        self.assertFalse(contract["production_activation_allowed"])
        self.assertEqual(contract["full_production_acceptance"], "NOT_ALLOWED")
        self.assertEqual(contract["cadence_modes"]["09:30"], "PUBLIC_OFFICIAL_PARTIAL_VALID_EXISTING_RUNTIME")

    def test_declarative_feed_cannot_restore_full_intraday(self):
        with patch("src.phase2_production.json.loads", return_value={"dependencies": [{
                "dependency_id": phase2.EXTERNAL_FEED, "status": "PASS", "fallback_allowed": False}]}):
            with self.assertRaisesRegex(RuntimeError, "PUBLIC_OFFICIAL_PARTIAL_RUNTIME_REQUIRED"):
                phase2.require_intraday_authority()

    def test_phase2_intraday_bundle_is_not_accepted(self):
        for cadence in ("09:30", "12:00"):
            result = phase2.validate_phase2_source_bundle({}, trading_date="2026-10-06", cadence=cadence)
            self.assertEqual(result["blocking_reason"], "PUBLIC_OFFICIAL_PARTIAL_RUNTIME_REQUIRED")

    def test_builder_phase2_intraday_routes_existing_public_mode(self):
        from scripts import build_production_source_bundle_from_official as builder
        with patch.object(sys, "argv", ["builder", "--phase2", "--trading-date", "2026-10-06", "--cadence", "09:30", "--output", "unused", "--evidence-output", "unused"]), \
                patch.object(builder, "build_bundle", return_value={"validation_status": "PASS"}) as build, \
                patch("scripts.build_phase2_production_source.build_phase2_bundle", side_effect=AssertionError("OLD_INTRADAY_PATH")):
            self.assertEqual(builder.main(), 0)
            self.assertTrue(build.call_args.kwargs["public_official_partial"])

    def test_resolver_phase2_intraday_routes_existing_context(self):
        from scripts import resolve_production_runtime_context as resolver
        with patch.object(sys, "argv", ["resolver", "--phase2", "--cadence", "12:00"]), \
                patch.object(resolver, "resolve_context", return_value={"validation_status": "PASS"}) as resolve, \
                patch.object(resolver, "atomic_write_json"), patch.object(phase2, "resolve_phase2_context", side_effect=AssertionError("OLD_INTRADAY_PATH")):
            self.assertEqual(resolver.main(), 0)
            self.assertTrue(resolve.called)

    def test_missing_eps_period_gate_preserved(self):
        from scripts.build_phase2_production_source import build_phase2_bundle
        with tempfile.TemporaryDirectory() as root, patch("scripts.build_phase2_production_source.main_authority", return_value=fixtures.AUTHORITY), \
                patch("scripts.build_phase2_production_source.latest_predecessor", return_value=("2026-10-05", "12:00", {"state": {}})), \
                patch("scripts.build_phase2_production_source.materialize_full_market", side_effect=RuntimeError("FUNDAMENTAL_EPS_PERIOD_IDENTITY_UNPROVEN")):
            result = build_phase2_bundle(trading_date="2026-10-05", cadence="19:30", output=Path(root) / "bundle.json", evidence_output=Path(root) / "evidence.json", state_root=root, history_root=root)
            self.assertEqual(result["blocking_reason"], "FUNDAMENTAL_EPS_PERIOD_IDENTITY_UNPROVEN")
            self.assertFalse((Path(root) / "bundle.json").exists())


if __name__ == "__main__":
    unittest.main()
