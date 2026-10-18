import base64,copy,hashlib,json,unittest
from pathlib import Path
import personal_model as b
import runner_proof as proof
import offline_fixtures as f
import evidence_protocol as e
import source_policy as policy
SRC=Path(__file__).resolve().parent
class CollectorTests(unittest.TestCase):
 def test_output_candidate_fresh_and_not_created_by_check(self):
  import run_offline_tests as harness
  p=ENGINEERING_OUTPUT_ROOT.parent/'new-output-policy-candidate'
  self.assertEqual(harness.output(str(p)),p);self.assertFalse(p.exists())
 def test_output_traversal_alias_unc_ads_and_replay_rejected(self):
  import run_offline_tests as harness
  for p in (str(ENGINEERING_OUTPUT_ROOT),str(ENGINEERING_OUTPUT_ROOT)+'/../escape',str(ENGINEERING_OUTPUT_ROOT)+'/./alias','relative','\\\\host\\share\\x',str(ENGINEERING_OUTPUT_ROOT)+':stream'):
   with self.assertRaises(ValueError):harness.output(p)
 def assess(self,p):return e.evaluate_private(f.wire(p),f.HEAD,f.RUN,'1')
 def bad(self,p):
  with self.assertRaises(b.Refused):self.assess(p)
 def mutate_public(self,key,value):
  r=self.assess(f.packet());r[key]=value
  with self.assertRaises(b.Refused):e.check_public(r)
 def test_complete_packet_is_only_runner_observation(self):
  r=self.assess(f.packet());self.assertEqual(len(r['records']),12);self.assertEqual(r['d_policy'],'D_POLICY_NOT_PROVEN');self.assertFalse(r['original_host_authorized']);self.assertEqual(r['context'],'CROSS_CHECKED_NOT_ATOMIC_NOT_ATTESTED')
 def test_missing_d_pagefile_never_becomes_policy(self):
  p=f.packet()
  for i in (5,6):f.rows(p,i,[]);p['records'][i].update(status='SOURCE_ABSENT',provider_availability='QUERY_SUCCEEDED_NO_INSTANCE')
  r=self.assess(p);self.assertEqual(r['configuration'],'INDETERMINATE');self.assertEqual(r['runtime_usage'],'INDETERMINATE');self.assertEqual(r['d_policy'],'D_POLICY_NOT_PROVEN')
 def test_missing_d_volume_is_indeterminate(self):
  p=f.packet()
  for i in (3,11):f.rows(p,i,[]);p['records'][i].update(status='SOURCE_ABSENT',provider_availability='QUERY_SUCCEEDED_NO_INSTANCE')
  self.assertEqual(self.assess(p)['context'],'INDETERMINATE')
 def test_optional_tpm_unavailable_is_not_fabricated(self):
  p=f.packet();p['records'][4].update(status='UNAVAILABLE',provider_availability='OPTIONAL_PROVIDER_UNAVAILABLE',raw_base64=None,raw_sha256=None,error_kind='CimException',hresult=-1)
  self.assertEqual(self.assess(p)['records'][4]['status'],'UNAVAILABLE')
 def test_required_provider_cannot_be_optional(self):
  p=f.packet();p['records'][1].update(status='UNAVAILABLE',provider_availability='OPTIONAL_PROVIDER_UNAVAILABLE',raw_base64=None,raw_sha256=None,error_kind='CimException',hresult=-1);self.bad(p)
 def test_tpm_timeout_cannot_be_optional_success(self):
  p=f.packet();p['records'][4].update(status='UNAVAILABLE',provider_availability='OPTIONAL_PROVIDER_UNAVAILABLE',raw_base64=None,raw_sha256=None,error_kind='CimException',hresult=-1,elapsed_ms=5001);self.bad(p)
 def test_false_absence_rejects_nonempty_rows(self):
  p=f.packet();p['records'][5]['status']='SOURCE_ABSENT';self.bad(p)
 def test_wrong_namespace_class_fields_filter_all_rejected(self):
  for k,v in [('namespace','ROOT/OTHER'),('class','Win32_Process'),('fields',['Name']),('filter',"Name = 'C:\\\\pagefile.sys'")]:
   p=f.packet();p['records'][5]['query'][k]=v;self.bad(p)
 def test_remote_scope_injection_rejected(self):
  for k in ('ComputerName','CimSession','InputObject','Query'):
   p=f.packet();p['records'][1]['query'][k]='injected';self.bad(p)
 def test_filter_exact_two_wql_backslashes(self):
  self.assertEqual(b.QUERIES['settings']['filter'],"Name = 'D:\\\\pagefile.sys'");self.assertEqual(b.QUERIES['usage']['filter'],b.QUERIES['settings']['filter'])
 def test_extra_cim_raw_property_rejected(self):
  p=f.packet();import synthetic_fixtures as old
  rows=old.rows(p,1);rows[0]['Extra']='secret';f.rows(p,1,rows);self.bad(p)
 def test_partial_truncated_duplicate_noncanonical_evidence(self):
  raw=f.wire(f.packet())
  for bad in (raw[:-4],b'{"a":1,"a":2}\n',json.dumps(f.packet()).encode(),raw+b'\n'):
   with self.assertRaises(b.Refused):e.evaluate_private(bad,f.HEAD,f.RUN,'1')
 def test_raw_corruption_and_base64_alias_rejected(self):
  for k,v in [('raw_sha256','f'*64),('raw_base64','AA==\n')]:
   p=f.packet();p['records'][0][k]=v;self.bad(p)
 def test_wrong_attempt_or_head_binding_rejected(self):
  for k,v in [('head','b'*40),('run_id','987'),('run_attempt','2'),('realm',b.REALM)]:
   p=f.packet();p[k]=v;self.bad(p)
 def test_wrong_host_context_cannot_promote(self):
  p=f.packet();import synthetic_fixtures as old
  rows=old.rows(p,9);rows[0]['CSName']='DIFFERENT';f.rows(p,9,rows)
  r=self.assess(p);self.assertEqual(r['context'],'INDETERMINATE');self.assertEqual(r['configuration'],'INDETERMINATE');self.assertIn('os',r['context_conflicts'])
 def test_identity_change_same_projection_is_detected_by_raw(self):
  p=f.packet();import synthetic_fixtures as old
  rows=old.rows(p,8);rows[0]['UserSID']='S-1-5-21-100-200-300-1002';f.rows(p,8,rows)
  r=self.assess(p);self.assertIn('account',r['context_conflicts']);self.assertEqual(r['context'],'INDETERMINATE')
 def test_per_query_and_total_deadlines_rejected(self):
  p=f.packet();p['records'][0]['elapsed_ms']=5001;self.bad(p)
  p=f.packet();p['elapsed_ms']=120001;self.bad(p)
 def test_halt_partial_preserves_no_promotion(self):
  p=f.packet();p['records']=p['records'][:2];p['status']='HALT';p['records'][-1].update(status='HALT',error_kind='ERROR',hresult=-1,provider_availability='SOURCE_ERROR')
  r=self.assess(p);self.assertEqual(r['native_outcome'],'HALT');self.assertEqual(r['configuration'],'INDETERMINATE')
 def test_records_after_halt_and_sequence_alias_rejected(self):
  p=f.packet();p['records'][0]['status']='HALT';self.bad(p)
  p=f.packet();p['records'][0]['sequence']=True;self.bad(p)
 def test_global_true_zero_zero_not_d_policy(self):
  p=f.packet();import synthetic_fixtures as old
  for i in (2,10):f.rows(p,i,[{'Name':'SYNTHETIC-PERSONAL-PC','AutomaticManagedPagefile':True}])
  f.rows(p,5,[{'Name':b.TARGET,'InitialSize':0,'MaximumSize':0}]);r=self.assess(p)
  self.assertEqual(r['d_policy'],'D_POLICY_NOT_PROVEN');self.assertEqual(r['boot_applied'],'BOOT_APPLIED_NOT_PROVEN')
 def test_public_raw_hash_injection_rejected(self):
  r=self.assess(f.packet());r['records'][0]['raw_sha256']='S-1-5-21-private';
  with self.assertRaises(b.Refused):e.check_public(r)
 def test_public_provider_plaintext_injection_rejected(self):
  r=self.assess(f.packet());r['records'][0]['provider_availability']='HOSTNAME_PRIVATE'
  with self.assertRaises(b.Refused):e.check_public(r)
 def test_public_raw_verification_false_rejected(self):self.mutate_public('raw_verified_before_redaction',False)
 def test_public_runtime_qualified_injection_rejected(self):self.mutate_public('context','RUNTIME_QUALIFIED')
 def test_public_identity_field_injection_rejected(self):
  r=self.assess(f.packet());r['records'][0]['projection']['UserSID']='secret'
  with self.assertRaises(b.Refused):e.check_public(r)
 def test_public_numeric_alias_rejected(self):
  r=self.assess(f.packet());r['records'][0]['projection']['SessionId']=True
  with self.assertRaises(b.Refused):e.check_public(r)
 def test_public_incomplete_unfailed_list_rejected(self):
  r=self.assess(f.packet());r['records']=r['records'][:1];r['native_outcome']='HALT'
  with self.assertRaises(b.Refused):e.check_public(r)
 def test_public_context_mismatch_cannot_be_hidden(self):
  r=self.assess(f.packet());r['records'][8]['raw_sha256']='b'*64
  with self.assertRaises(b.Refused):e.check_public(r)
 def test_synthetic_consent_has_no_native_authority(self):
  import synthetic_fixtures as old
  with self.assertRaises(proof.Refused):proof.verify_token(json.dumps(old.approval()),b'{}',1001,f.HEAD,f.RUN,'1')
 def test_signed_claims_exact_boundary(self):
  c=f.claims();self.assertEqual(proof.check_claims(c,1100,f.HEAD,f.RUN,'1')['sha'],f.HEAD)
 def test_claim_wrong_repo_host_runner_event_workflow(self):
  for k in ('repository','repository_id','repository_owner_id','runner_environment','event_name','workflow_ref','sha','workflow_sha','ref','aud','iss'):
   c=f.claims();c[k]='WRONG'
   with self.assertRaises(proof.Refused):proof.check_claims(c,1100,f.HEAD,f.RUN,'1')
 def test_attempt_replay_refused(self):
  c=f.claims();c['run_attempt']='2'
  with self.assertRaises(proof.Refused):proof.check_claims(c,1100,f.HEAD,f.RUN,'2')
 def test_expiry_future_and_numeric_time_alias(self):
  for k,v in [('exp',1001),('nbf',1200),('iat',True),('exp',2500)]:
   c=f.claims();c[k]=v
   with self.assertRaises(proof.Refused):proof.check_claims(c,1100,f.HEAD,f.RUN,'1')
 def test_unsigned_unknown_key_and_jwks_tamper(self):
  enc=lambda o:base64.urlsafe_b64encode(json.dumps(o).encode()).decode().rstrip('=')
  token=enc({'alg':'RS256','typ':'JWT','kid':'unknown'})+'.'+enc(f.claims())+'.AA'
  with self.assertRaises(proof.Refused):proof.verify_token(token,(SRC/'GITHUB_OIDC_JWKS_PINNED.json').read_bytes(),1100,f.HEAD,f.RUN,'1')
  with self.assertRaises(proof.Refused):proof.verify_token(token,b'{}',1100,f.HEAD,f.RUN,'1')
 def test_fixed_powershell_source(self):self.assertEqual(policy.check_powershell((SRC/'native_worker.ps1').read_text()),'FIXED_REVIEWED_SOURCE_INVARIANTS')
 def test_forbidden_write_remote_dynamic_commands_rejected(self):
  text=(SRC/'native_worker.ps1').read_text()
  for command in ('Set-CimInstance','Invoke-CimMethod','SetValue','ComputerName','Invoke-Expression','AdjustTokenPrivileges'):
   with self.assertRaises(policy.Refused):policy.check_powershell(text+'\n'+command)
 def test_fixed_scope_removed_rejects(self):
  text=(SRC/'native_worker.ps1').read_text().replace('OperationTimeoutSec=5','OperationTimeoutSec=10')
  with self.assertRaises(policy.Refused):policy.check_powershell(text)
 def test_cim_inputobject_not_confused_with_json_conversion(self):
  text=(SRC/'native_worker.ps1').read_text().replace('Get-CimInstance @options','Get-CimInstance @options -InputObject $injected')
  with self.assertRaises(policy.Refused):policy.check_powershell(text)
 def test_native_modules_do_not_import_fixtures_or_owner_loader(self):
  for name in ('runner_controller.py','native_worker.ps1','windows_job.py','fault_worker.py'):
   text=(SRC/name).read_text();self.assertNotIn('import offline_fixtures',text);self.assertNotIn('personal_model.consent(',text);self.assertNotIn('shell=True',text)
