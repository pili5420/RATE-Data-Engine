"""Offline regression for source-date diagnostics and pre-acquisition timing."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
import uuid
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from scripts.build_phase2_production_source import build_phase2_bundle
from scripts.validate_production_scheduler_actual_timing import evaluate
from src.cer081_scheduler_actual_timing import (CADENCE_CRONS, CADENCE_WORKFLOWS,
    build_actual_timing_evidence, expected_slot_utc)
from src.full_market_catalogue import CLASSIFICATION_ENDPOINTS, build_catalogue
from src.production_acceptance_session import (ProductionAcceptanceSessionError,
    admit_scheduled_run, audit_session_lineage, open_production_acceptance_session,
    summarize_production_acceptance_session)
from src.route_b_timing_provenance import TimingProvenanceError, verify_timing_provenance

DAY = "2026-11-10"
HEAD = "a" * 40
RUN_ID = "1001"


def iso(value):
    return value.isoformat().replace("+00:00", "Z")


def metadata(cadence, delay):
    slot = expected_slot_utc(DAY, cadence)
    return {"id": int(RUN_ID), "event": "schedule", "path": CADENCE_WORKFLOWS[cadence],
        "head_sha": HEAD, "run_attempt": 1, "created_at": iso(slot + timedelta(seconds=delay)),
        "run_started_at": iso(slot + timedelta(seconds=delay))}


class MainlineCorrectiveTests(unittest.TestCase):
    def check_timing(self, cadence, delay, **changes):
        raw = metadata(cadence, delay)
        raw.update(changes)
        evidence = build_actual_timing_evidence(raw, cadence=cadence, trading_date=DAY,
            event_schedule=CADENCE_CRONS[cadence], workflow_path=CADENCE_WORKFLOWS[cadence],
            expected_run_id=RUN_ID, expected_head_sha=HEAD)
        return evaluate(raw, evidence, cadence=cadence, trading_date=DAY,
            run_id=RUN_ID, head_sha=HEAD, event_schedule=CADENCE_CRONS[cadence],
            workflow_path=CADENCE_WORKFLOWS[cadence])

    def test_all_four_cadences_accept_exact_900_only(self):
        for cadence in CADENCE_CRONS:
            with self.subTest(cadence=cadence):
                self.assertEqual(self.check_timing(cadence, 900)["validation_status"], "PASS")
                blocked = self.check_timing(cadence, 901)
                self.assertEqual(blocked["validation_status"], "FAIL_CLOSED")
                self.assertEqual(blocked["blocking_reason"], "SCHEDULER_BLOCKING_DELAY")
                self.assertEqual(blocked["production_credit"], 0)

    def test_observed_november_delays_block(self):
        for delay in (26110, 36228):
            self.assertEqual(self.check_timing("19:30", delay)["blocking_reason"], "SCHEDULER_BLOCKING_DELAY")

    def test_missing_and_tampered_timing_block(self):
        raw = metadata("19:30", 30)
        timing = build_actual_timing_evidence(raw, cadence="19:30", trading_date=DAY,
            event_schedule=CADENCE_CRONS["19:30"], workflow_path=CADENCE_WORKFLOWS["19:30"],
            expected_run_id=RUN_ID, expected_head_sha=HEAD)
        common = dict(cadence="19:30", trading_date=DAY, run_id=RUN_ID, head_sha=HEAD,
            event_schedule=CADENCE_CRONS["19:30"], workflow_path=CADENCE_WORKFLOWS["19:30"])
        for changes in ({"scheduler_start_delay_seconds": 0}, {"actions_run_started_at": iso(expected_slot_utc(DAY,"19:30"))},
                        {"run_head_sha": "b"*40}, {"event_name": "workflow_dispatch"}):
            with self.subTest(changes=changes):
                self.assertEqual(evaluate(raw, {**timing, **changes}, **common)["validation_status"], "FAIL_CLOSED")
        self.assertEqual(evaluate({}, {}, **common)["validation_status"], "FAIL_CLOSED")
        self.assertEqual(evaluate([], {}, **common)["validation_status"], "FAIL_CLOSED")

    def test_github_event_and_head_binding_block(self):
        cadence="19:30"; raw=metadata(cadence, 30)
        evidence=build_actual_timing_evidence(raw,cadence=cadence,trading_date=DAY,
            event_schedule=CADENCE_CRONS[cadence],workflow_path=CADENCE_WORKFLOWS[cadence],
            expected_run_id=RUN_ID,expected_head_sha=HEAD)
        for field,value in (("event","workflow_dispatch"),("head_sha","b"*40),
                            ("run_attempt",2),("path","other.yml"),("id",999)):
            with self.subTest(field=field):
                altered={**raw,field:value}
                blocked=evaluate(altered,evidence,cadence=cadence,trading_date=DAY,
                    run_id=RUN_ID,head_sha=HEAD,event_schedule=CADENCE_CRONS[cadence],
                    workflow_path=CADENCE_WORKFLOWS[cadence])
                self.assertEqual(blocked["validation_status"],"FAIL_CLOSED")

    def test_early_and_late_official_date_retains_exact_gate(self):
        endpoint=CLASSIFICATION_ENDPOINTS["TWSE"]
        for source_date, expected in (("2026-11-09","OFFICIAL_DATE_BEFORE_NOMINAL_SLOT"),
                                      ("2026-11-11","OFFICIAL_DATE_AFTER_NOMINAL_SLOT")):
            calls=[]
            def fetch(url, *, html=False):
                calls.append(url)
                return b"synthetic", {"endpoint":url,"retrieved_at":"2026-11-10T18:45:20Z",
                    "http_status":200,"body_sha256":"c"*64,"fallback_used":False}
            with self.subTest(source_date=source_date), patch("src.full_market_catalogue.parse_classification",return_value=(source_date,[])):
                with self.assertRaisesRegex(RuntimeError,"STALE_OR_FUTURE_CATALOGUE") as caught:
                    build_catalogue(DAY,fetcher=fetch)
            self.assertFalse(hasattr(caught.exception,"catalogue_freshness_evidence"))
            self.assertEqual(calls,[endpoint])

    def test_phase2_failure_preserves_source_evidence_and_no_bundle(self):
        failure=RuntimeError("STALE_OR_FUTURE_CATALOGUE")
        failure.catalogue_transport_evidence=[{"source_owner":"TWSE","endpoint":CLASSIFICATION_ENDPOINTS["TWSE"],
            "http_status":200,"retrieval_timestamp":"2026-11-10T18:45:20Z",
            "retry_decision":"ACCEPT_COMPLETE_RESPONSE","fallback_used":False}]
        base=Path(os.environ.get("RATE_MAINLINE_TEST_TMP", tempfile.gettempdir())).resolve()
        root=base/("rate-mainline-corrective-"+uuid.uuid4().hex)
        root.mkdir()
        try:
            with patch("scripts.build_phase2_production_source.main_authority",return_value={"run_id":RUN_ID}), \
                 patch("scripts.build_phase2_production_source.latest_predecessor",return_value=(None,None,{"state":{}})), \
                 patch("scripts.build_phase2_production_source.materialize_full_market",side_effect=failure):
                result=build_phase2_bundle(trading_date=DAY,cadence="19:30",output=root/"bundle.json",
                    evidence_output=root/"evidence.json",state_root=root,history_root=root)
            self.assertEqual(result["validation_status"],"FAIL_CLOSED")
            self.assertEqual(result["source_timestamp"],"UNKNOWN_NOT_PRESERVED_BY_FROZEN_CATALOGUE")
            self.assertEqual(result["publication_time"],"UNKNOWN_NOT_SUPPLIED_BY_SOURCE")
            self.assertEqual(result["new_data_publication_status"],"UNPROVEN")
            self.assertEqual(result["catalogue_transport_evidence"],failure.catalogue_transport_evidence)
            self.assertFalse((root/"bundle.json").exists())
        finally:
            if root.resolve().parent != base or not root.name.startswith("rate-mainline-corrective-"):
                raise RuntimeError("UNSAFE_TEST_CLEANUP")
            shutil.rmtree(root)

    def test_transport_failure_preserves_attempts_without_publication_inference(self):
        failure=RuntimeError("CATALOGUE_TRANSPORT_FAILED")
        failure.catalogue_transport_evidence=[{"endpoint":CLASSIFICATION_ENDPOINTS["TWSE"],
            "http_status":503,"retry_decision":"FAIL_CLOSED_RETRY_EXHAUSTED",
            "fallback_used":False}]
        base=Path(os.environ.get("RATE_MAINLINE_TEST_TMP", tempfile.gettempdir())).resolve()
        root=base/("rate-mainline-corrective-"+uuid.uuid4().hex)
        root.mkdir()
        try:
            with patch("scripts.build_phase2_production_source.main_authority",return_value={"run_id":RUN_ID}), \
                 patch("scripts.build_phase2_production_source.latest_predecessor",return_value=(None,None,{"state":{}})), \
                 patch("scripts.build_phase2_production_source.materialize_full_market",side_effect=failure):
                result=build_phase2_bundle(trading_date=DAY,cadence="19:30",output=root/"bundle.json",
                    evidence_output=root/"evidence.json",state_root=root,history_root=root)
            self.assertEqual(result["retrieval_status"],"FAIL_CLOSED")
            self.assertEqual(result["catalogue_transport_evidence"],failure.catalogue_transport_evidence)
            self.assertNotIn("catalogue_freshness_evidence",result)
            self.assertFalse((root/"bundle.json").exists())
        finally:
            if root.resolve().parent != base or not root.name.startswith("rate-mainline-corrective-"):
                raise RuntimeError("UNSAFE_TEST_CLEANUP")
            shutil.rmtree(root)

    def test_eod_workflow_preacquisition_order_and_intraday_freeze(self):
        root=Path(__file__).resolve().parents[1]
        for cadence in ("0730","1930"):
            text=(root/f".github/workflows/rate_production_{cadence}_scheduler.yml").read_text()
            self.assertLess(text.index("Capture CER-081 scheduler actual-timing evidence"),
                            text.index("Enforce actual scheduler timing before source acquisition"))
            self.assertLess(text.index("Enforce actual scheduler timing before source acquisition"),
                            text.index("Build official production source bundle"))
            self.assertIn(f"--output artifacts/production_{cadence}/RATE_PRODUCTION_SCHEDULER_PREACQUISITION_GATE.json",text)
        # Existing operational intraday workflows are frozen byte-for-byte.
        for cadence in ("0930","1200"):
            text=(root/f".github/workflows/rate_production_{cadence}_scheduler.yml").read_text()
            self.assertNotIn("Enforce actual scheduler timing before source acquisition",text)

    def test_session_without_production_evidence_cannot_be_ready(self):
        activation={"artifact":"RATE_POST_MERGE_PRODUCTION_ACTIVATION_VERIFICATION_V1",
            "validation_status":"PASS","final_disposition":"PRODUCTION_ACTIVATION_VERIFIED",
            "production_credit":1,"cer081_credit":0,"merged_main_sha":HEAD}
        session=open_production_acceptance_session(activation,session_start_date=DAY)
        summary=summarize_production_acceptance_session(session)
        self.assertEqual(summary["completion_status"],"IN_PROGRESS")
        self.assertEqual(summary["missing_cadence_runs"],12)
        self.assertEqual(summary["cer081_credit"],0)
        with self.assertRaisesRegex(ProductionAcceptanceSessionError,"PA_RUN_PRODUCTION_DATA_GATE_NOT_PASS"):
            admit_scheduled_run(session,{"event":"schedule","validation_status":"PASS",
                "fallback_used":False,"trading_date":DAY,"cadence":"07:30",
                "run_head_sha":HEAD,"production_data_gate":"BLOCKED"})
        with self.assertRaisesRegex(TimingProvenanceError,"TIMING_PROVENANCE_LEDGER_BINDING_MISSING"):
            verify_timing_provenance({"workflow_run_id":"1001"},reader=object())

    def test_cross_day_chain_and_duplicate_slot_fail_closed(self):
        activation={"artifact":"RATE_POST_MERGE_PRODUCTION_ACTIVATION_VERIFICATION_V1",
            "validation_status":"PASS","final_disposition":"PRODUCTION_ACTIVATION_VERIFIED",
            "production_credit":1,"cer081_credit":0,"merged_main_sha":HEAD}
        session=open_production_acceptance_session(activation,session_start_date=DAY)
        first={"event":"schedule","validation_status":"PASS","publish_result":"PASS",
            "fallback_used":False,"trading_date":DAY,"cadence":"19:30","run_head_sha":HEAD,
            "production_data_gate":"PASS","decision_state_continuity":True,
            "portfolio_continuity":True,"transaction_ledger_continuity":True,
            "ranking_model_continuity":True,"current_state_id":"synthetic-state-1",
            "previous_state_id":"synthetic-state-0","workflow_run_id":"1001"}
        session=admit_scheduled_run(session,first)
        with self.assertRaisesRegex(ProductionAcceptanceSessionError,"PA_RUN_DUPLICATE_FORBIDDEN"):
            admit_scheduled_run(session,{**first,"workflow_run_id":"1002"})
        second={**first,"trading_date":"2026-11-11","cadence":"07:30",
            "workflow_run_id":"1003","previous_state_id":"synthetic-state-1",
            "current_state_id":"synthetic-state-2"}
        session=admit_scheduled_run(session,second)
        self.assertEqual(audit_session_lineage(session)["cross_day_links_verified"],1)
        broken={**session,"accepted_runs":[session["accepted_runs"][0],
            {**session["accepted_runs"][1],"previous_state_id":"synthetic-reset"}]}
        with self.assertRaisesRegex(ProductionAcceptanceSessionError,"PA_LINEAGE_STATE_CHAIN_BROKEN"):
            audit_session_lineage(broken)
        self.assertEqual(summarize_production_acceptance_session(session)["completion_status"],"IN_PROGRESS")


if __name__ == "__main__": unittest.main()
