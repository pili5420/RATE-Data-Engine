import hashlib, unittest
from src.intraday_activation_apply_authorization import EXPECTED_PATHS
from src.intraday_activation_candidate_review import canonical_digest
from src.intraday_real_git_data_http_rehearsal import candidate_manifest_sha256, SyntheticGitDataHTTP, rehearse_real_git_data_http

MAIN="1"*40; TREE="2"*40; BRANCH="activation/rate-v11-intraday-test"
def blob_sha(s):
 b=s.encode(); return hashlib.sha1(f"blob {len(b)}\0".encode()+b).hexdigest()
def files(): return {p:f"candidate-{i}-{p}\n" for i,p in enumerate(EXPECTED_PATHS)}
def plan(c):
 return {"artifact":"RATE_INTRADAY_ACTIVATION_APPLY_TRANSACTION_PLAN_V1","status":"TRANSACTION_PLAN_ONLY",
 "base_main_sha":MAIN,"candidate_manifest_sha256":candidate_manifest_sha256(c),"target_branch":BRANCH,
 "files":{p:{"mode":"100644","git_blob_sha1":blob_sha(c[p])} for p in EXPECTED_PATHS}}

class T(unittest.TestCase):
 def runit(self,fail=None):
  c=files(); p=plan(c); t=SyntheticGitDataHTTP(main_sha=MAIN,base_tree_sha=TREE,fail_at=fail)
  r=rehearse_real_git_data_http(p,c,t,expected_transaction_plan_sha256=canonical_digest(p),expected_base_main_sha=MAIN,expected_candidate_manifest_sha256=candidate_manifest_sha256(c))
  return r,t
 def test_success(self):
  r,t=self.runit(); self.assertEqual(r["blob_count"],9); self.assertTrue(r["branch_readback_verified"]); self.assertEqual(len(t.calls),16)
 def test_ambiguous_ref_readback_no_retry(self):
  r,t=self.runit("ref:ambiguous"); self.assertEqual(r["ref_create_count"],1); self.assertEqual(r["ref_create_retries"],0); self.assertTrue(r["branch_readback_verified"])
 def test_blob_failure_never_creates_branch(self):
  c=files(); p=plan(c); t=SyntheticGitDataHTTP(main_sha=MAIN,base_tree_sha=TREE,fail_at="blob:3")
  with self.assertRaisesRegex(RuntimeError,"BLOB_FAILED"):
   rehearse_real_git_data_http(p,c,t,expected_transaction_plan_sha256=canonical_digest(p),expected_base_main_sha=MAIN,expected_candidate_manifest_sha256=candidate_manifest_sha256(c))
  self.assertNotIn("heads/"+BRANCH,t.refs); self.assertEqual(t.ref_create_attempts,0)
 def test_tree_or_commit_failure_never_creates_branch(self):
  for fail in ("tree","commit"):
   c=files(); p=plan(c); t=SyntheticGitDataHTTP(main_sha=MAIN,base_tree_sha=TREE,fail_at=fail)
   with self.subTest(fail=fail), self.assertRaises(RuntimeError):
    rehearse_real_git_data_http(p,c,t,expected_transaction_plan_sha256=canonical_digest(p),expected_base_main_sha=MAIN,expected_candidate_manifest_sha256=candidate_manifest_sha256(c))
   self.assertNotIn("heads/"+BRANCH,t.refs); self.assertEqual(t.ref_create_attempts,0)
 def test_main_drift_fails_before_objects(self):
  c=files(); p=plan(c); t=SyntheticGitDataHTTP(main_sha="f"*40,base_tree_sha=TREE)
  with self.assertRaisesRegex(Exception,"MAIN_REF_DRIFT"):
   rehearse_real_git_data_http(p,c,t,expected_transaction_plan_sha256=canonical_digest(p),expected_base_main_sha=MAIN,expected_candidate_manifest_sha256=candidate_manifest_sha256(c))
  self.assertEqual(t.blob_attempts,0)
if __name__=="__main__": unittest.main()
