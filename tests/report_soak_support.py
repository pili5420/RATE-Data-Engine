"""SYNTHETIC ENGINEERING ONLY: 07:30 transport fixtures + real intraday/EOD CLIs."""
import copy
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

from scripts.publish_production_state_latest import publish_state
from scripts.resolve_production_runtime_context import resolve_context, _previous_legal_trading_day
from src import public_official_partial_valid as p
from src.cer074_acceptance import atomic_write_json, sha256
from src.production_live_state import CADENCE_DIR, MANIFEST_NAME, PERSIST_NAME, STATE_NAME, file_hash, load_live_state, read_object
from tests.test_partial_to_evening_acceptance import PartialToEveningAcceptanceTests


def reference(path):
    return {"path": str(path), "sha256": file_hash(path)}


class ReportSoakFixture:
    def __init__(self):
        self.test = PartialToEveningAcceptanceTests()
        self.test.setUp()
        try:
            self.build()
        except BaseException:
            self.close()
            raise

    def close(self):
        self.test.doCleanups()

    def slot(self, day, cadence):
        directory = self.artifacts / "production_state/live" / day / CADENCE_DIR[cadence]
        return {"trading_date": day, "cadence": cadence, "state_manifest": reference(directory / MANIFEST_NAME)}

    def record(self, day, cadence, source, context):
        path = self.base / day / (CADENCE_DIR[cadence] + "-context.json")
        atomic_write_json(path, context)
        self.evidence["runs"].append({**self.slot(day, cadence), "event_name": "schedule",
            "runtime_context": reference(path), "source_bundle": reference(source), "source_validated_at": p.now()})

    def build(self):
        t = self.test
        t.prepare()
        self.base, self.artifacts = t.root, t.artifacts
        baseline_decision = copy.deepcopy(t.previous["decision"])
        days = ["2026-10-05", "2026-10-06", "2026-10-07"]
        prior_day = _previous_legal_trading_day(days[0])
        previous, _ = t.support.install_test_predecessor(prior_day, "19:30")
        self.evidence = {"artifact": "RATE-FOUR-CADENCE-REPORT-SOAK-V1-INPUT", "synthetic_only": True,
            "predecessor": self.slot(prior_day, "19:30"), "runs": []}
        self.cli_results = []
        for index, day in enumerate(days):
            t.day, t.root = day, self.base / day
            t.runtime = t.root / "runtime"
            t.root.mkdir(parents=True, exist_ok=True)
            with patch("scripts.resolve_production_runtime_context._today_taipei", return_value=day):
                context = resolve_context(cadence="07:30", event_name="schedule", dispatch_trading_date=None,
                    state_root=self.artifacts / "production_state")
            t.assertEqual(context["validation_status"], "PASS")
            morning_source = t.eod_bundle()
            morning_source["cadence"] = "07:30"
            source_path = t.root / "morning-source.json"
            atomic_write_json(source_path, morning_source)
            decision = copy.deepcopy(baseline_decision)
            decision.update(trading_date=day, previous_state_id=previous["current_state_id"],
                previous_state_hash=previous["decision_payload_hash"], source_bundle_hash=sha256(morning_source))
            for name in ("roy_portfolio", "ai_paper_portfolio", "transaction_ledger"):
                decision[name] = copy.deepcopy(previous["decision"][name])
            persist, material = t.support.wrap_decision(decision, previous, "07:30")
            atomic_write_json(t.runtime / "decision_state/0730" / (persist["current_state_id"] + ".json"), material)
            evidence_path = t.root / "morning-persist.json"
            atomic_write_json(evidence_path, persist)
            result = publish_state(persist_evidence_path=evidence_path, trading_date=day, cadence="07:30",
                artifacts_root=self.artifacts, state_root=t.runtime, workflow_run_id=str(1000 + index * 4),
                workflow_job_id="2000", event_name="schedule", ref="refs/heads/main", commit_sha="a" * 40)
            t.assertEqual(result["validation_status"], "PASS")
            self.record(day, "07:30", source_path, context)
            for cadence, number in (("09:30", "076"), ("12:00", "077")):
                with patch("scripts.resolve_production_runtime_context._today_taipei", return_value=day):
                    context = resolve_context(cadence=cadence, event_name="schedule", dispatch_trading_date=None,
                        state_root=self.artifacts / "production_state")
                previous_path = Path(context["previous_state_evidence_path"])
                source_path, _ = t.bundle(cadence)
                out = t.root / ("out" + CADENCE_DIR[cadence])
                command = [sys.executable, "-B", str(p.ROOT / "scripts" / ("run_cer" + number + "_incremental_" + CADENCE_DIR[cadence] + "_acceptance.py")),
                    "--public-official-partial", "--source-bundle", str(source_path),
                    "--cer074-persisted-evidence", str(previous_path), "--cer075-persisted-evidence", str(previous_path),
                    "--output-dir", str(out), "--state-root", str(t.runtime)]
                if cadence == "12:00":
                    command += ["--cer076-persisted-evidence", str(previous_path)]
                completed = subprocess.run(command, cwd=p.ROOT, capture_output=True, text=True)
                t.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
                self.cli_results.append({"day": day, "cadence": cadence, "exit_code": completed.returncode})
                with patch.dict("os.environ", {"GITHUB_EVENT_NAME": "schedule", "GITHUB_REF": "refs/heads/main"}):
                    p.publish_report(source_bundle_path=source_path, trading_date=day, cadence=cadence,
                        artifacts_root=self.artifacts, workflow_run_id=str(1001 + index * 4 + (cadence == "12:00")),
                        workflow_job_id="2000", evidence_output=t.root / (CADENCE_DIR[cadence] + "-report.json"))
                published = publish_state(persist_evidence_path=out / (p.ARTIFACTS[cadence] + ".json"), trading_date=day, cadence=cadence,
                    artifacts_root=self.artifacts, state_root=t.runtime, workflow_run_id=str(1001 + index * 4 + (cadence == "12:00")),
                    workflow_job_id="2000", event_name="schedule", ref="refs/heads/main", commit_sha="a" * 40)
                t.assertEqual(published["validation_status"], "PASS", published)
                self.record(day, cadence, source_path, context)
            with patch("scripts.resolve_production_runtime_context._today_taipei", return_value=day):
                context = resolve_context(cadence="19:30", event_name="schedule", dispatch_trading_date=None,
                    state_root=self.artifacts / "production_state")
            source_path = t.root / "evening-source.json"
            atomic_write_json(source_path, t.eod_bundle())
            completed = t.evening_cli(source_path)
            t.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr + str(read_object(t.root / "out1930/RATE_PARTIAL_TO_EOD_FULL_ACCEPTANCE.json")))
            self.cli_results.append({"day": day, "cadence": "19:30", "exit_code": completed.returncode})
            publish_state(persist_evidence_path=t.root / "out1930/RATE_CER078_PERSIST_RESULT_EVIDENCE.json", trading_date=day, cadence="19:30",
                artifacts_root=self.artifacts, state_root=t.runtime, workflow_run_id=str(1003 + index * 4),
                workflow_job_id="2000", event_name="schedule", ref="refs/heads/main", commit_sha="a" * 40)
            self.record(day, "19:30", source_path, context)
            previous = load_live_state(self.artifacts / "production_state", day, "19:30")["state"]
        self.input_path = self.base / "report-soak-input.json"
        atomic_write_json(self.input_path, self.evidence)

    def hashes(self):
        return {str(path): file_hash(path) for path in self.base.rglob("*") if path.is_file()}
