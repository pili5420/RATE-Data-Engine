import unittest
from src.intraday_activation_candidate_review import canonical_digest
from src.intraday_cer081_final_production_acceptance import CER081FinalAcceptanceError, validate_cer081_final_production_acceptance

MAIN="1"*40
def post():
 return {"artifact":"RATE_POST_MERGE_PRODUCTION_ACTIVATION_VERIFICATION_V1","validation_status":"PASS",
 "final_disposition":"PRODUCTION_ACTIVATION_VERIFIED","merged_main_sha":MAIN,"activation_pr_number":999,
 "provider_name":"Fugle","scheduled_runs":"2/2","intraday_market_coverage":"30/30",
 "market_counts":{"TWSE":25,"TPEX":5},"state_chain_continuity":True,"fallback_used":False,
 "production_credit":1,"cer081_credit":0}
def soak():
 return {"artifact":"RATE_CER081_SOAK_SUMMARY","validation_status":"PASS","final_result":"PASS",
 "completion_status":"ACCEPTED_CLOSED","governance_scope":"CURRENT_PRODUCTION",
 "CER081_FULL_PRODUCTION_SOAK":"PASS","production_acceptance_granted":True,
 "trading_days_tested":3,"successful_cadence_runs":12,"missing_cadence_runs":0,"duplicate_cadence_runs":0,
 "report_only_run_count":0,"full_4_cadence_scheduled_coverage":"PASS","state_continuity":"PASS",
 "cross_day_continuity":"PASS","portfolio_continuity":"PASS","transaction_ledger_continuity":"PASS",
 "ranking_model_continuity":"PASS","remaining_blockers":[],"unrecovered_failure_count":0,
 "duplicate_production_record_count":0,"automatic_recovery_count":0,
 "soak_credit_allowed_while_blocked":False,"cer081_completion_allowed_while_blocked":False,
 "production_acceptance_allowed_while_blocked":False}
def scheduler():
 return {"artifact":"RATE_CER081_SCHEDULER_RELIABILITY_SUMMARY","validation_status":"PASS",
 "scheduler_coverage":"PASS","manual_dispatch_substitution":"NO","missed_execution_count":0,
 "delayed_execution_blocking_count":0}
def deterministic():
 return {"artifact":"RATE_CER081_DETERMINISTIC_REPLAY_SUMMARY","validation_status":"PASS",
 "deterministic_audit_replay":"PASS","replay_new_record_count":0}
def freeze():
 return {"artifact":"RATE_CER081_MODEL_FREEZE_SUMMARY","validation_status":"PASS",
 "model_freeze_integrity":"PASS","production_rule_auto_upgrade":"NO",
 "change_control_required_for_model_changes":"PASS"}
class T(unittest.TestCase):
 def q(self,p=None,s=None,sch=None,d=None,f=None,**kw):
  p=p or post(); s=s or soak(); sch=sch or scheduler(); d=d or deterministic(); f=f or freeze()
  return validate_cer081_final_production_acceptance(p,s,sch,d,f,
   expected_post_merge_sha256=kw.get("ph",canonical_digest(p)),
   expected_soak_summary_sha256=kw.get("sh",canonical_digest(s)),
   expected_scheduler_summary_sha256=kw.get("schh",canonical_digest(sch)),
   expected_deterministic_summary_sha256=kw.get("dh",canonical_digest(d)),
   expected_model_freeze_summary_sha256=kw.get("fh",canonical_digest(f)),
   expected_merged_main_sha=kw.get("main",MAIN))
 def test_pass(self):
  r=self.q(); self.assertEqual(r["final_disposition"],"RATE_V11_PRODUCTION_ACCEPTED"); self.assertEqual(r["development_status"],"COMPLETE")
 def test_post_merge_required(self):
  p=post(); p["final_disposition"]="BLOCKED"
  with self.assertRaisesRegex(CER081FinalAcceptanceError,"POST_MERGE_NOT_PASS"): self.q(p=p)
 def test_three_days_twelve_runs_required(self):
  s=soak(); s["trading_days_tested"]=2
  with self.assertRaisesRegex(CER081FinalAcceptanceError,"SCHEDULED_RUN_METRICS_INVALID"): self.q(s=s)
  s=soak(); s["successful_cadence_runs"]=11
  with self.assertRaisesRegex(CER081FinalAcceptanceError,"SCHEDULED_RUN_METRICS_INVALID"): self.q(s=s)
 def test_continuity_required(self):
  s=soak(); s["transaction_ledger_continuity"]="FAIL"
  with self.assertRaisesRegex(CER081FinalAcceptanceError,"CONTINUITY_NOT_PASS"): self.q(s=s)
 def test_scheduler_required(self):
  sch=scheduler(); sch["missed_execution_count"]=1
  with self.assertRaisesRegex(CER081FinalAcceptanceError,"SCHEDULER_NOT_PASS"): self.q(sch=sch)
 def test_determinism_and_freeze_required(self):
  d=deterministic(); d["deterministic_audit_replay"]="FAIL"
  with self.assertRaisesRegex(CER081FinalAcceptanceError,"DETERMINISTIC_NOT_PASS"): self.q(d=d)
  f=freeze(); f["model_freeze_integrity"]="FAIL"
  with self.assertRaisesRegex(CER081FinalAcceptanceError,"MODEL_FREEZE_NOT_PASS"): self.q(f=f)
if __name__=="__main__": unittest.main()
