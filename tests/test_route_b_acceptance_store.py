"""Offline Store writer boundary tests; every path uses a temporary Store."""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.route_b_acceptance_store import (
    SESSION_NAME, RouteBAcceptanceStoreError, _admit_verified_run_to_store,
    admit_run_to_store, load_session, persist_activation_package,
)
from src.route_b_timing_provenance import TimingProvenanceError

MAIN="a"*40
BIND="d"*40
RECEIPT={"workflow_run_id":"1","run_attempt":1,"artifact_id":789}


def package():
    return {
        "artifact":"RATE_ROUTE_B_ACTIVATION_RUNTIME_PACKAGE_V1",
        "validation_status":"PASS","runtime_mode":"ACTIVE",
        "activation":{"artifact":"RATE_POST_MERGE_PRODUCTION_ACTIVATION_VERIFICATION_V1",
                      "final_disposition":"PRODUCTION_ACTIVATION_VERIFIED"},
        "overlay_0930":{"source_workflow_run_id":"2","trading_date":"2026-11-05",
                        "source_head_sha":"b"*40},
        "overlay_1200":{"source_workflow_run_id":"3","trading_date":"2026-11-05",
                        "source_head_sha":"b"*40},
        "session":{
            "artifact":"RATE_V11_PRODUCTION_ACCEPTANCE_SESSION_V1",
            "validation_status":"PASS","governance_scope":"CURRENT_PRODUCTION",
            "merged_main_sha":MAIN,"activation_code_sha":MAIN,
            "activation_binding_sha":BIND,
            "operational_head_policy":"AUTHORIZED_DESCENDANT_POINTER_COMMITS_ONLY",
            "session_start_date":"2026-11-06", "required_trading_days":3,
            "required_scheduled_runs":12,
            "required_cadences":["07:30","09:30","12:00","19:30"],
            "official_event_required":"schedule","manual_dispatch_credit_allowed":False,
            "historical_pre_activation_credit_allowed":False,"cross_main_credit_allowed":False,
            "duplicate_run_credit_allowed":False,"fallback_allowed":False,
            "automatic_recovery_credit_allowed":False,"accepted_runs":[],
            "trading_days_tested":0,"successful_cadence_runs":0,
            "missing_cadence_runs":12,"duplicate_cadence_runs":0,
            "completion_status":"IN_PROGRESS","production_acceptance_granted":False,
            "cer081_credit":0,
        },
    }


def run(run_id="1",state="s1",head="b"*40):
    return {
        "event":"schedule","validation_status":"PASS","publish_result":"PASS",
        "trading_date":"2026-11-06","cadence":"07:30",
        "run_head_sha":head,"activation_code_sha":MAIN,
        "activation_binding_sha":BIND,"activation_is_ancestor":True,
        "operational_changes_authorized":True,"workflow_run_id":run_id,
        "workflow_job_id":"10","fallback_used":False,"automatic_retry_count":0,
        "production_data_gate":"PASS","decision_state_continuity":True,
        "portfolio_continuity":True,"transaction_ledger_continuity":True,
        "ranking_model_continuity":True,"current_state_id":state,
        "previous_state_id":"prior","scheduler_actual_timing":{"synthetic":True},
        "scheduler_timing_provenance":dict(RECEIPT),
    }


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        root=patch("src.route_b_acceptance_store.STORE_ROOT",self.root)
        root.start(); self.addCleanup(root.stop)

    def create(self):
        candidate=package()
        with patch("src.route_b_acceptance_store.build_runtime_package",return_value=candidate), \
             patch("src.route_b_acceptance_store.verify_scheduled_source_from_actions",
                   side_effect=lambda **kw: {"workflow_run_id":str(kw["run_id"]),"run_attempt":1}):
            return persist_activation_package(candidate,self.root,source_run_id="3")

    def verified(self,value=None):
        with patch("src.route_b_acceptance_store.verify_timing_provenance",return_value=dict(RECEIPT)):
            return _admit_verified_run_to_store(self.root,run() if value is None else value)

    def test_activation_create_and_idempotent(self):
        self.assertEqual(self.create()["store_result"],"SESSION_CREATED")
        self.assertEqual(self.create()["store_result"],"IDEMPOTENT_NOOP_EXISTING_SESSION")
        self.assertEqual(load_session(self.root)["successful_cadence_runs"],0)

    def test_activation_missing_source_or_forged_claim_fails(self):
        with self.assertRaisesRegex(RouteBAcceptanceStoreError,"SOURCE_ID_REQUIRED"):
            persist_activation_package(package(),self.root)
        fake=package(); fake["permit"]="FORGED"
        with self.assertRaisesRegex(RouteBAcceptanceStoreError,"AUTHORITY_CLAIM_FORBIDDEN"):
            persist_activation_package(fake,self.root,source_run_id="3")
        self.assertFalse((self.root/SESSION_NAME).exists())

    def test_activation_mismatched_package_or_missing_api_fails(self):
        candidate=package()
        with patch("src.route_b_acceptance_store.build_runtime_package",return_value={}):
            with self.assertRaisesRegex(RouteBAcceptanceStoreError,"SOURCE_MISMATCH"):
                persist_activation_package(candidate,self.root,source_run_id="3")
        with patch("src.route_b_acceptance_store.build_runtime_package",return_value=candidate), \
             patch("src.route_b_acceptance_store.verify_scheduled_source_from_actions",
                   side_effect=TimingProvenanceError("API_UNAVAILABLE")):
            with self.assertRaisesRegex(TimingProvenanceError,"API_UNAVAILABLE"):
                persist_activation_package(candidate,self.root,source_run_id="3")
        self.assertFalse((self.root/SESSION_NAME).exists())

    def test_direct_helper_fails_without_store_mutation(self):
        self.create()
        with self.assertRaisesRegex(RouteBAcceptanceStoreError,"DIRECT_ADMISSION_FORBIDDEN"):
            admit_run_to_store(self.root,run())
        self.assertEqual(load_session(self.root)["accepted_runs"],[])

    def test_verified_collector_run_duplicate_and_conflict(self):
        self.create()
        self.assertEqual(self.verified()["store_result"],"RUN_ADMITTED")
        self.assertEqual(self.verified()["store_result"],"IDEMPOTENT_NOOP_EXISTING_RUN")
        with self.assertRaisesRegex(RouteBAcceptanceStoreError,"CONFLICTING_DUPLICATE_RUN"):
            self.verified(run(state="other"))
        self.assertEqual(load_session(self.root)["successful_cadence_runs"],1)
        self.assertEqual(len(load_session(self.root)["accepted_runs"]),1)

    def test_pre_session_run_noop_after_proof(self):
        self.create(); candidate=run(); candidate["trading_date"]="2026-11-05"
        self.assertEqual(self.verified(candidate)["store_result"],"NOOP_PRE_SESSION_RUN")
        self.assertEqual(load_session(self.root)["successful_cadence_runs"],0)

    def test_arbitrary_destination_rejected(self):
        elsewhere=self.root/"elsewhere"
        with self.assertRaisesRegex(RouteBAcceptanceStoreError,"DESTINATION_UNAUTHORIZED"):
            admit_run_to_store(elsewhere,run())
        with self.assertRaisesRegex(RouteBAcceptanceStoreError,"DESTINATION_UNAUTHORIZED"):
            persist_activation_package(package(),elsewhere,source_run_id="3")
        self.assertFalse(elsewhere.exists())

    def test_forged_permit_or_actor_rejected(self):
        self.create()
        for key in ("permit","permit_id","actor","authorized_actor"):
            with self.subTest(key=key):
                candidate=run(); candidate[key]="FORGED"
                with self.assertRaisesRegex(RouteBAcceptanceStoreError,"AUTHORITY_CLAIM_FORBIDDEN"):
                    self.verified(candidate)
        self.assertEqual(load_session(self.root)["accepted_runs"],[])

    def test_invalid_run_job_or_source_binding_fails(self):
        self.create()
        for field,value in (("workflow_run_id","invalid"),
                            ("workflow_job_id","invalid"),("run_head_sha","c"*40)):
            with self.subTest(field=field):
                candidate=run(); candidate[field]=value
                with patch("src.route_b_acceptance_store.verify_timing_provenance",
                           side_effect=TimingProvenanceError("SOURCE_BINDING_INVALID")):
                    with self.assertRaisesRegex(TimingProvenanceError,"SOURCE_BINDING_INVALID"):
                        _admit_verified_run_to_store(self.root,candidate)
        self.assertEqual(load_session(self.root)["accepted_runs"],[])

    def test_missing_or_forged_receipt_rejected(self):
        self.create()
        for value in (None,{"artifact_id":0}):
            candidate=run()
            if value is None: candidate.pop("scheduler_timing_provenance")
            else: candidate["scheduler_timing_provenance"]=value
            with self.assertRaisesRegex(RouteBAcceptanceStoreError,"PROVENANCE_MISMATCH"):
                self.verified(candidate)
        self.assertEqual(load_session(self.root)["accepted_runs"],[])


if __name__=="__main__":
    unittest.main()
