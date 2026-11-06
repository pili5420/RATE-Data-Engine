"""Phase A synthetic integration only; never publish to repository artifacts."""
import ast
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
from src.full_market_rotation import EXTERNAL_FEED
from src.production_live_state import load_live_state, file_hash, PERSIST_NAME
from tests import test_phase2_production as fixtures
from tests import test_public_official_partial_valid as public_fixtures


ROOT = Path(__file__).resolve().parents[1]


def intraday_workflow_matches_main(head: bytes, base: bytes) -> bool:
    timing_steps = (
        b"      - name: Capture CER-081 scheduler actual-timing evidence",
        b"      - name: Upload CER-081 scheduler actual-timing evidence",
    )
    if any(step in base.splitlines() for step in timing_steps):
        return head == base

    # Historical bases allow only the introduction of these two complete steps.
    unchanged_lines = []
    introduced_steps = []
    skip = False
    for line in head.splitlines(keepends=True):
        if line.startswith(b"      - "):
            skip = line.rstrip(b"\r\n") in timing_steps
            if skip:
                introduced_steps.append(line.rstrip(b"\r\n"))
        if not skip:
            unchanged_lines.append(line)
    return tuple(introduced_steps) == timing_steps and b"".join(unchanged_lines) == base


class IntradayWorkflowComparisonTests(unittest.TestCase):
    before = b"name: synthetic\n    steps:\n      - name: Before\n        run: before\n"
    runtime = b"      - name: Runtime\n        run: fail-closed\n"
    after = b"      - uses: actions/upload-artifact@v4\n"
    capture = (b"      - name: Capture CER-081 scheduler actual-timing evidence\n"
               b"        run: capture\n")
    upload = (b"      - name: Upload CER-081 scheduler actual-timing evidence\n"
              b"        uses: actions/upload-artifact@v4\n")

    def test_latest_main_requires_identical_timing_and_runtime_bytes(self):
        base = self.before + self.capture + self.runtime + self.upload + self.after
        self.assertTrue(intraday_workflow_matches_main(base, base))
        for changed in (
            base.replace(b"run: capture", b"run: changed"),
            base.replace(b"run: fail-closed", b"run: skip"),
            base.replace(self.capture, b""),
            base.replace(self.upload, b""),
            base.replace(b"\n", b"\r\n"),
        ):
            with self.subTest(changed=changed):
                self.assertFalse(intraday_workflow_matches_main(changed, base))

    def test_legacy_main_allows_only_two_introduced_timing_steps(self):
        base = self.before + self.runtime + self.after
        head = self.before + self.capture + self.runtime + self.upload + self.after
        self.assertTrue(intraday_workflow_matches_main(head, base))
        for changed in (
            head.replace(b"run: fail-closed", b"run: skip"),
            head.replace(self.capture, b""),
            head.replace(self.upload, b""),
            head.replace(self.capture, self.capture + self.capture),
            head.replace(self.after, b""),
        ):
            with self.subTest(changed=changed):
                self.assertFalse(intraday_workflow_matches_main(changed, base))


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
    def test_phase2_source_publisher_requires_explicit_opt_in(self):
        from scripts import publish_production_source_bundle_latest as publisher
        with patch.object(sys, "argv", ["publisher", "--source-bundle", "unused", "--trading-date", "2026-10-06", "--cadence", "19:30"]), \
                patch.object(publisher, "load_json", return_value={"schema_version": phase2.SOURCE_SCHEMA}), \
                patch.object(publisher, "publish_latest", side_effect=AssertionError("IMPLICIT_PUBLICATION")):
            self.assertEqual(publisher.main(), 1)

    def test_phase2_state_publisher_requires_explicit_opt_in(self):
        from scripts import publish_production_state_latest as publisher
        with patch.object(publisher, "read_object", return_value={"current_state_id": "rate-state-" + "a" * 24}), \
                patch.object(publisher, "validate_material", return_value={"decision": {"phase2": True, "report_runtime_status": "EOD_VALIDATED"}}), \
                patch.object(publisher, "load_live_state", side_effect=AssertionError("IMPLICIT_PUBLICATION")):
            result = publisher.publish_state(persist_evidence_path="unused", trading_date="2026-10-06", cadence="19:30",
                state_root="unused", workflow_run_id="100", workflow_job_id="200", event_name="schedule", commit_sha="b" * 40, ref="refs/heads/main")
            self.assertEqual(result["blocking_reason"], "PHASE2_EXPLICIT_OPT_IN_REQUIRED")
            self.assertFalse(result["live_state_updated"])

    def test_default_schedulers_do_not_gain_phase2_source_authority(self):
        import yaml
        for slot in ("0730", "1930"):
            workflow = yaml.safe_load((ROOT / f".github/workflows/rate_production_{slot}_scheduler.yml").read_text())
            self.assertFalse(workflow[True]["workflow_dispatch"]["inputs"]["phase2"]["default"])
            self.assertEqual(
                workflow["jobs"]["production-" + slot]["env"]["EXECUTION_AUTHORITY"],
                "${{ (github.event_name == 'schedule' || inputs.phase2) && 'MAIN_ONLY' || '' }}",
            )
            text=(ROOT / f".github/workflows/rate_production_{slot}_scheduler.yml").read_text(encoding="utf-8")
            self.assertIn("(github.event_name == 'schedule' || inputs.phase2) && '--phase2'", text)

    def test_full_cold_four_cadence_chain(self):
        self.assertEqual(chain_proof(None)["four_cadence_continuity"], "PASS")

    def test_intraday_workflows_are_byte_identical_to_main(self):
        current_main = subprocess.check_output(
            ["git", "-C", str(ROOT), "rev-parse", "origin/main"]
        ).decode().strip()

        for slot in ("0930", "1200"):
            path = f".github/workflows/rate_production_{slot}_scheduler.yml"
            base = subprocess.check_output(
                ["git", "-C", str(ROOT), "show", f"{current_main}:{path}"]
            )
            head = subprocess.check_output(
                ["git", "-C", str(ROOT), "show", f"HEAD:{path}"]
            )
            self.assertEqual((ROOT / path).read_text(encoding="utf-8"),
                             head.decode().replace("\r\n", "\n"), path)
            self.assertTrue(intraday_workflow_matches_main(head, base), path)
            self.assertIn(b"Capture CER-081 scheduler actual-timing evidence", head)
            self.assertIn(b"Upload CER-081 scheduler actual-timing evidence", head)

    def test_registry_eps_contract_soak_and_model_owners_unchanged(self):
        paths = ["config/RATE_FOUR_CADENCE_REPORT_SOAK_V1.json",
            "src/report_production_soak.py", "src/public_official_partial_valid.py",
            "src/sources/fundamental_history.py", "src/feature_math.py", "src/rate_logic.py", "src/full_market_catalogue.py"]
        for path in paths:
            self.assertEqual((ROOT / path).read_bytes(), subprocess.check_output(["git", "show", fixtures.BASE + ":" + path], cwd=ROOT))

        current_main = subprocess.check_output(
            ["git", "-C", str(ROOT), "rev-parse", "origin/main"]
        ).decode().strip()
        cer081_path = "src/cer081_unattended_soak.py"
        base_cer081 = subprocess.check_output(
            ["git", "-C", str(ROOT), "show", f"{current_main}:{cer081_path}"]
        ).decode()
        head_cer081 = (ROOT / cer081_path).read_text(encoding="utf-8")

        def function_ast(source, name):
            tree = ast.parse(source)
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
                    return ast.dump(node, include_attributes=False)
            self.fail(f"missing protected CER081 function: {name}")

        protected = [
            "common", "validate_cer080_predecessor", "production_source_ssot",
            "source_failure_gates", "_shared_writer_concurrency",
            "scheduler_definition_evidence", "scheduled_time_for",
            "build_expected_state", "full_production_disqualifiers",
            "normalize_scheduled_runs", "scheduled_run_metrics",
            "build_daily_matrix", "deterministic_replay",
            "build_daily_artifacts", "write_fail_closed",
        ]
        for name in protected:
            self.assertEqual(function_ast(head_cer081, name), function_ast(base_cer081, name), name)
        self.assertIn("summarize_actual_timing_evidence", head_cer081)
        self.assertIn("timing_required", head_cer081)

        dependency_doc = json.loads((ROOT / "config/RATE_EXTERNAL_PRODUCTION_DEPENDENCIES.json").read_text(encoding="utf-8"))
        dependency = next(item for item in dependency_doc["dependencies"] if item["dependency_id"] == EXTERNAL_FEED)
        self.assertEqual(dependency["status"], "BLOCKED_EXTERNAL")
        self.assertFalse(dependency["fallback_allowed"])
        self.assertFalse(dependency["engineering_resolution_available"])
        self.assertEqual(set(dependency["required_market_coverage"]), {"TWSE", "TPEX"})
        self.assertEqual(dependency["required_resolution"],
            "AUTHORIZED_TAIWAN_INTRADAY_PRODUCTION_FEED_WITH_TWSE_TPEX_COVERAGE")

        registry_doc = json.loads((ROOT / "config/RATE_PRODUCTION_OFFICIAL_SOURCE_REGISTRY_V1.json").read_text(encoding="utf-8"))
        intraday = next(item for item in registry_doc["datasets"] if item["dataset_id"] == "authorized_market_intraday")
        self.assertEqual(intraday["authority"], "AUTHORIZED_TAIWAN_INTRADAY_FEED")
        self.assertEqual(set(intraday["required_market_coverage"]), {"TWSE", "TPEX"})
        self.assertEqual(intraday["authorization_status"], "BLOCKED_EXTERNAL")
        self.assertIsNone(intraday["endpoint"])
        self.assertFalse(intraday["fallback_allowed"])

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
