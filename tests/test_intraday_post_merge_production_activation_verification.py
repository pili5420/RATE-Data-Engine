import unittest
from src.intraday_activation_candidate_review import canonical_digest
from src.intraday_post_merge_production_activation_verification import PostMergeActivationVerificationError, validate_post_merge_production_activation
PRE="1"*40; MERGED="2"*40; ACT="3"*40
def run(c,state,prev=None):
 return {"event":"schedule","cadence":c,"validation_status":"PASS","authorized_intraday_feed":"PASS",
 "coverage":"30/30","market_counts":{"TWSE":25,"TPEX":5},"market_intraday_price_gate":"PASS",
 "full_intraday_decision_status":"PASS","fallback_used":False,"automatic_retry_count":0,
 "production_data_gate":"PASS","decision_state_continuity":True,"portfolio_continuity":True,
 "transaction_ledger_continuity":True,"production_snapshot_id":"ps-"+c,"input_snapshot_id":"is-"+c,
 "current_state_id":state,"previous_state_id":prev}
def ev():
 return {"artifact":"RATE_POST_MERGE_PRODUCTION_ACTIVATION_EVIDENCE_V1","merge_status":"PASS",
 "pre_merge_main_sha":PRE,"merged_main_sha":MERGED,"activation_pr_number":999,"activation_commit_sha":ACT,
 "activation_pr_merged":True,"merge_commit_on_main":True,
 "configuration":{
   "external_dependency":{"dependency_id":"EXTERNAL_AUTHORIZED_INTRADAY_FEED_DEPENDENCY","status":"PASS",
     "engineering_resolution_available":True,"required_market_coverage":["TWSE","TPEX"],"fallback_allowed":False},
   "source_registry":{"provider":"Fugle","authorization_status":"PASS","operational_use_allowed":True,
     "intraday_status":{"0930":"AUTHORIZED_PROVIDER_READY","1200":"AUTHORIZED_PROVIDER_READY"}},
   "official_registry":{"dataset_id":"authorized_market_intraday","authority":"Fugle","authorization_status":"PASS",
     "blocked_dependency_present":False,"fallback_allowed":False,
     "cadence_applicability":{"09:30":"REQUIRED","12:00":"REQUIRED"}},
   "phase2":{"intraday_authority":"PASS","0930_price_gate":"PASS","1200_price_gate":"PASS"},
   "schedulers":{"09:30":{"authorized_feed_path_bound":True,"execution_authority":"MAIN_ONLY","provider_build_step_present":True},
                 "12:00":{"authorized_feed_path_bound":True,"execution_authority":"MAIN_ONLY","provider_build_step_present":True}}},
 "scheduled_runs":[run("09:30","S0930","S0730"),run("12:00","S1200","S0930")],
 "blocking_defects":[],"merge_rollback_performed":False}
class T(unittest.TestCase):
 def q(self,e=None,**kw):
  e=e or ev()
  return validate_post_merge_production_activation(e,expected_evidence_sha256=kw.get("h",canonical_digest(e)),
    expected_pre_merge_main_sha=PRE,expected_merged_main_sha=MERGED,expected_activation_pr_number=999,
    expected_activation_commit_sha=ACT)
 def test_pass(self): self.assertEqual(self.q()["final_disposition"],"PRODUCTION_ACTIVATION_VERIFIED")
 def test_merge_binding(self):
  e=ev(); e["merged_main_sha"]="f"*40
  with self.assertRaisesRegex(PostMergeActivationVerificationError,"MERGE_BINDING_MISMATCH"): self.q(e)
 def test_config_gate(self):
  e=ev(); e["configuration"]["source_registry"]["operational_use_allowed"]=False
  with self.assertRaisesRegex(PostMergeActivationVerificationError,"SOURCE_REGISTRY_INVALID"): self.q(e)
 def test_manual_run_rejected(self):
  e=ev(); e["scheduled_runs"][0]["event"]="workflow_dispatch"
  with self.assertRaisesRegex(PostMergeActivationVerificationError,"EVENT_NOT_SCHEDULE"): self.q(e)
 def test_continuity_required(self):
  e=ev(); e["scheduled_runs"][1]["previous_state_id"]="WRONG"
  with self.assertRaisesRegex(PostMergeActivationVerificationError,"STATE_CHAIN_BROKEN"): self.q(e)
 def test_fallback_rejected(self):
  e=ev(); e["scheduled_runs"][0]["fallback_used"]=True
  with self.assertRaisesRegex(PostMergeActivationVerificationError,"FALLBACK_OR_RETRY_INVALID"): self.q(e)
if __name__=="__main__": unittest.main()
