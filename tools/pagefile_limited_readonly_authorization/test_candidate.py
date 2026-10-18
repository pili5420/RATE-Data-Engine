import ast
import copy
import hashlib
import json
import unittest
from pathlib import Path
from tools.pagefile_non_gui_evidence import fixtures as prior
from tools.pagefile_limited_readonly_authorization import candidate as c
from tools.pagefile_limited_readonly_authorization.synthetic_fixtures import envelope,wire,submission

class CandidateTests(unittest.TestCase):
 def test_valid_synthetic_only(self):
  out=c.assess_synthetic(wire(envelope()));self.assertEqual(out['status'],'OFFLINE_SYNTHETIC_VALID_NOT_QUALIFICATION')
  self.assertFalse(out['execution_authorized']);self.assertFalse(out['can_issue_permit']);self.assertFalse(out['target_qualified'])
  self.assertFalse(out['native_filter_executed']);self.assertEqual(out['source_gaps'],list(c.GAPS))
 def test_no_external_submissions(self):
  r=c.review_external_submissions(wire([]));self.assertEqual(r['status'],'BLOCKED_EXTERNAL_EVIDENCE_REQUIRED')
  self.assertEqual(set(r['requirements'].values()),{'MISSING'});self.assertFalse(r['can_issue_permit'])
 def test_all_artifacts_present_still_unqualified(self):
  r=c.review_external_submissions(wire([submission(k) for k in c.REQUIREMENTS]))
  self.assertEqual(set(r['requirements'].values()),{'PRESENT_UNQUALIFIED'});self.assertFalse(r['independent_external_verification_complete'])
  self.assertFalse(r['can_issue_permit']);self.assertEqual(r['status'],'BLOCKED_EXTERNAL_EVIDENCE_REQUIRED')
 def test_safety_only_design(self):
  s=c.offline_safety_contract();self.assertEqual(c.check_safety(s),'DESIGN_ONLY_EXTERNAL_SAFETY_UNQUALIFIED')
  for k in ['physical_root','owner_SID','DACL','volume_identity','nonce','deadline_utc']:self.assertIsNone(s[k])
 def test_plan_not_dispatch(self):
  self.assertEqual(c.check_plan(copy.deepcopy(c.PLAN)),'OFFLINE_PLAN_VALID_NOT_NATIVE_ENFORCEMENT')
  self.assertEqual(c.PLAN['filters']['settings'],"Name = 'D:\\\\pagefile.sys'")
  self.assertEqual(c.PLAN['filters']['volumes'],"DriveLetter = 'D:'")
 def test_no_qualification_from_zero_sizes(self):
  p=prior.packet();prior.set_data(p,'settings',[{'Name':'D:\\pagefile.sys','InitialSize':0,'MaximumSize':0}]);prior.set_data(p,'registry',{'kind':'MultiString','PagingFiles':['D:\\pagefile.sys 0 0']})
  r=c.assess_synthetic(wire(envelope(p)));self.assertFalse(r['can_issue_permit']);self.assertFalse(r['target_qualified'])
  self.assertEqual(r['raw_observations']['D_system_managed']['status'],'BLOCKED')
 def test_no_qualification_from_global_true(self):
  p=prior.packet()
  for q in ['computer_before','computer_after']:prior.set_data(p,q,[{'Name':'FICTIONAL_HOST','AutomaticManagedPagefile':True}])
  r=c.assess_synthetic(wire(envelope(p)));self.assertFalse(r['can_issue_permit']);self.assertEqual(r['raw_observations']['D_system_managed']['status'],'BLOCKED')
 def test_missing_settings_no_policy_inference(self):
  p=prior.packet();prior.set_data(p,'settings',[]);r=c.assess_synthetic(wire(envelope(p)))
  self.assertFalse(r['can_issue_permit']);self.assertFalse(r['target_qualified'])
 def test_raw_registry_collateral_not_policy(self):
  p=prior.packet();prior.set_data(p,'registry',{'kind':'MultiString','PagingFiles':['D:\\pagefile.sys 512 2048','C:\\pagefile.sys 0 0']})
  r=c.assess_synthetic(wire(envelope(p)));self.assertFalse(r['can_issue_permit']);self.assertEqual(r['source_gaps'],list(c.GAPS))
 def test_no_atomic_snapshot_claim(self):
  self.assertFalse(c.PLAN['sequential_reads_atomic']);self.assertFalse(c.PLAN['matching_endpoints_exclude_ABA'])
 def test_lifecycle_correct_sequence(self):self.assertEqual(c.simulate_attempt(['reserve','intent','begin','seal']),'SEALED_MODELLED')
 def test_terminal_no_reserve_after_sealed(self):self.assertEqual(c.simulate_attempt(['reserve','intent','begin','seal','reserve']),'HALT_UNKNOWN_NO_RESUME')
 def test_attempt_events_type_bound(self):
  for bad in [None,True,{},'reserve',1,['reserve']*9]:self.assertEqual(c.simulate_attempt(bad),'HALT_UNKNOWN_NO_RESUME')
 def test_unknown_event_types(self):
  for bad in [None,True,{},[],1]:self.assertEqual(c.simulate_attempt([bad]),'HALT_UNKNOWN_NO_RESUME')
 def test_no_hidden_native_boundary(self):
  tree=ast.parse(Path(c.__file__).read_text(encoding='utf-8'));imports=[]
  for n in ast.walk(tree):
   if isinstance(n,ast.Import):imports.extend(x.name for x in n.names)
   if isinstance(n,ast.ImportFrom):imports.append(n.module)
   if isinstance(n,ast.Call) and isinstance(n.func,ast.Name):self.assertNotIn(n.func.id,['open','exec','eval','compile','__import__','input'])
  self.assertEqual(set(imports),{'base64','binascii','hashlib','json','tools.pagefile_non_gui_evidence'})
  self.assertFalse(any(isinstance(n,ast.If) and '__name__' in ast.unparse(n.test) for n in tree.body))
 def test_non_D_volume_rejected(self):
  p=prior.packet();prior.set_data(p,'volumes_before',[{'DeviceID':'\\\\?\\Volume{12345678-1234-1234-1234-123456789abc}\\','DriveLetter':'C:','SerialNumber':123}])
  self.assertEqual(c.assess_synthetic(wire(envelope(p)))['status'],'INDETERMINATE')
 def test_extra_volume_rows_rejected(self):
  p=prior.packet()
  for q in ['volumes_before','volumes_after']:prior.set_data(p,q,prior.get_data(p,q)+[{'DeviceID':'\\\\?\\Volume{87654321-1234-1234-1234-123456789abc}\\','DriveLetter':'C:','SerialNumber':456}])
  self.assertEqual(c.assess_synthetic(wire(envelope(p)))['status'],'INDETERMINATE')
 def test_other_pagefile_setting_rejected(self):
  p=prior.packet();prior.set_data(p,'settings',[{'Name':'C:\\pagefile.sys','InitialSize':1,'MaximumSize':2}])
  self.assertEqual(c.assess_synthetic(wire(envelope(p)))['status'],'INDETERMINATE')
 def test_other_pagefile_usage_rejected(self):
  p=prior.packet();row=prior.get_data(p,'usage');row[0]['Name']='C:\\pagefile.sys';prior.set_data(p,'usage',row)
  self.assertEqual(c.assess_synthetic(wire(envelope(p)))['status'],'INDETERMINATE')
 def test_runner_source_inside_synthetic_wrapper_rejected(self):
  p=prior.packet();p['realm']='RUNNER_ONLY_NOT_TARGET_HOST_EVIDENCE'
  self.assertEqual(c.assess_synthetic(wire(envelope(p)))['status'],'INDETERMINATE')
 def test_source_scalar_rejected(self):
  self.assertEqual(c.assess_synthetic(wire(envelope([])))['status'],'INDETERMINATE')
 def test_external_extra_qualification_field_rejected(self):
  s=submission();s['verified']=True;self.assertEqual(c.review_external_submissions(wire([s]))['status'],'INDETERMINATE')
 def test_external_duplicate_requirement_rejected(self):
  self.assertEqual(c.review_external_submissions(wire([submission(),submission()]))['status'],'INDETERMINATE')
 def test_all_external_missing_ids_are_exact(self):
  self.assertEqual(set(c.review_external_submissions(wire([]))['requirements']),set(c.REQUIREMENTS))
 def test_read_scope_document_matches_code(self):
  self.assertEqual(json.loads((Path(c.__file__).parent/'READ_SCOPE_V1.json').read_bytes()),c.PLAN)
 def test_closed_bundle_exact_source_integrity(self):
  # Fixture must be physically closed, not the complete inherited Git tree.
  from tools.pagefile_limited_readonly_authorization.verify_bundle import verify
  self.assertEqual(verify(self.closed_bundle_fixture())['status'],'PASS_CLOSED_OFFLINE_BUNDLE_INTEGRITY')
 def closed_bundle_fixture(self):
  root=ENGINEERING_OUTPUT_ROOT/'CLOSED_BUNDLE_UNIT_FIXTURE'
  if not root.exists():
   repo=Path(c.__file__).resolve().parents[2];source=Path(c.__file__).parent
   manifest=json.loads((source/'BUNDLE_MANIFEST_V1.json').read_bytes())
   for name in [*manifest['files'],'tools/pagefile_limited_readonly_authorization/BUNDLE_MANIFEST_V1.json']:
    dest=root/name;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes((repo/name).read_bytes())
  return root
 def test_closed_bundle_root_extra_rejected(self):
  from tools.pagefile_limited_readonly_authorization.verify_bundle import verify
  root=self.closed_bundle_fixture();p=root/'extra.txt';p.write_text('unlisted',encoding='utf-8')
  try:
   with self.assertRaises(ValueError):verify(root)
  finally:p.unlink()
 def test_closed_bundle_dependency_extra_rejected(self):
  from tools.pagefile_limited_readonly_authorization.verify_bundle import verify
  root=self.closed_bundle_fixture();p=root/'tools/pagefile_non_gui_evidence/extra.py';p.write_text('# unlisted',encoding='utf-8')
  try:
   with self.assertRaises(ValueError):verify(root)
  finally:p.unlink()
 def test_closed_bundle_namespace_init_rejected(self):
  from tools.pagefile_limited_readonly_authorization.verify_bundle import verify
  root=self.closed_bundle_fixture();p=root/'tools/__init__.py';p.write_text('# marker-only; never imported',encoding='utf-8')
  try:
   with self.assertRaises(ValueError):verify(root)
  finally:p.unlink()
 def test_reference_dependency_package_sibling_rejected(self):
  from tools.pagefile_limited_readonly_authorization.verify_bundle import check_package_siblings
  for suffix in ['py','pyc','pyd','cp312-win_amd64.pyd','so']:
   with self.assertRaises(ValueError):check_package_siblings(['pagefile_non_gui_evidence.'+suffix])
 def test_reference_candidate_package_sibling_rejected(self):
  from tools.pagefile_limited_readonly_authorization.verify_bundle import check_package_siblings
  for suffix in ['py','pyc','pyd','cp312-win_amd64.pyd','so']:
   with self.assertRaises(ValueError):check_package_siblings(['pagefile_limited_readonly_authorization.'+suffix])
 def test_safety_document_matches_code(self):
  self.assertEqual(json.loads((Path(c.__file__).parent/'EXECUTION_SAFETY_CONTRACT_V1.json').read_bytes()),c.offline_safety_contract())
 def test_candidate_schema_scope_identity(self):
  s=json.loads((Path(c.__file__).parent/'CANDIDATE_SCHEMA_V1.json').read_bytes());r=envelope()
  self.assertFalse(s['additionalProperties']);self.assertEqual(set(s['required']),set(r));self.assertEqual(set(s['properties']),set(r))
  for key,v in s['properties'].items():
   if key!='synthetic_source_packet_b64':self.assertEqual(v,{'const':r[key]})
 def test_external_request_is_missing_not_fabricated(self):
  doc=json.loads((Path(c.__file__).parent/'EXTERNAL_EVIDENCE_REQUEST_V1.json').read_bytes())
  self.assertEqual(doc['actual_submissions'],[]);self.assertFalse(doc['can_issue_permit'])
  self.assertEqual([r['id'] for r in doc['rows']],list(c.REQUIREMENTS))
  for r in doc['rows']:
   self.assertIsNone(r['artifact']);self.assertEqual(r['status'],'EXTERNAL_DEPENDENCY_BLOCKED');self.assertEqual(r['availability'],'MISSING')

OUTER={
 'real_target_realm':('realm','ORIGINAL_TARGET'), 'runner_realm':('realm','RUNNER_ONLY_NOT_TARGET_HOST_EVIDENCE'),
 'historical_realm':('realm','HISTORICAL_TARGET'), 'wrong_version':('version','PAGEFILE_NON_GUI_V1'),
 'wrong_base':('base_head','a'*40),'engine_tamper':('accepted_engine_sha256','a'*64),
 'schema_tamper':('accepted_schema_sha256','b'*64),'scope_tamper':('scope_sha256','c'*64),
 'scope_bool':('scope_sha256',True),'body_wrong_type':('synthetic_source_packet_b64',{}),
 'body_bad_base64':('synthetic_source_packet_b64','%%!'),'body_oversize':('synthetic_source_packet_b64','A'*524289),
}
def outer_test(key,value):
 def test(self):
  r=envelope();r[key]=value;out=c.assess_synthetic(wire(r));self.assertEqual(out['status'],'INDETERMINATE');self.assertEqual(out['raw_observations'],{});self.assertFalse(out['can_issue_permit'])
 return test
for name,(key,value) in OUTER.items():setattr(CandidateTests,'test_reject_'+name,outer_test(key,value))

PLAN_MUTATIONS=[('remote_API',['api_allowlist'],['OpenRemoteBaseKey']),('write_API',['api_allowlist'],['Set-CimInstance']),
 ('namespace',['namespace'],'ROOT/DEFAULT'),('extra_field',['classes','computer','fields'],['Name','AutomaticManagedPagefile','UserName']),
 ('unfiltered',['filters','settings'],None),('arbitrary_filter',['filters','settings'],"Name LIKE '%'"),('filter_injection',['filters','settings'],"Name = 'D:\\\\pagefile.sys' OR 1=1"),
 ('other_drive',['filters','volumes'],"DriveLetter = 'C:'"),('other_provider',['classes','volumes','provider'],'MS_VOLUME'),
 ('Registry_write',['registry','writable'],True),('Registry_key',['registry','key'],'SYSTEM\\Other'),('Registry_value',['registry','value'],'Other'),
 ('too_many_records',['counts','records'],12),('row_bound',['counts','rows_per_CIM_record'],2),('timeout_bound',['time_bounds','total_seconds'],121),
 ('claim_promotion',['claim_scope'],'D_SYSTEM_MANAGED_PASS'),('atomic_claim',['sequential_reads_atomic'],True)]
def plan_test(path,value):
 def test(self):
  plan=copy.deepcopy(c.PLAN);node=plan
  for k in path[:-1]:node=node[k]
  node[path[-1]]=value
  with self.assertRaises(c.Invalid):c.check_plan(plan)
 return test
for name,path,value in PLAN_MUTATIONS:setattr(CandidateTests,'test_plan_reject_'+name,plan_test(path,value))

SAFETY_MUTATIONS=[('retry',1),('retry',False),('resume',True),('fallback',True),('auto_next',True),('cleanup_on_failure',True),('native_enforcement','QUALIFIED'),('physical_root','D:\\target'),('nonce','a'*64),('deadline_utc','2030-01-01T00:00:00Z')]
for index,(key,value) in enumerate(SAFETY_MUTATIONS):
 def make(key,value):
  def test(self):
   s=c.offline_safety_contract();s[key]=value
   with self.assertRaises(c.Invalid):c.check_safety(s)
  return test
 setattr(CandidateTests,f'test_safety_reject_{index}_{key}',make(key,value))

BAD_WIRE={'duplicate':b'{"a":1,"a":2}\n','malformed':b'{\n','truncated':b'{"x":','bom':b'\xef\xbb\xbf{}\n','no_LF':b'{}','double_LF':b'{}\n\n','space':b'{"a": 1}\n','NaN':b'{"a":NaN}\n','invalid_UTF8':b'{"a":"\xff"}\n','surrogate':b'{"a":"\\ud800"}\n','wrong_root':b'[]\n'}
for name,raw in BAD_WIRE.items():
 def make(raw):
  def test(self):self.assertEqual(c.assess_synthetic(raw)['status'],'INDETERMINATE')
  return test
 setattr(CandidateTests,'test_wire_reject_'+name,make(raw))

BAD_EXTERNAL=[('claimed_PASS','status','PASS'),('claimed_verified','status','VERIFIED'),('claimed_available','status','AVAILABLE'),('unknown_requirement','requirement','OTHER'),('hash_tamper','artifact_sha256','0'*64),('bad_b64','artifact_utf8_b64','!!!'),('bool_authority','source_authority',True)]
for name,key,value in BAD_EXTERNAL:
 def make(key,value):
  def test(self):
   s=submission();s[key]=value;r=c.review_external_submissions(wire([s]));self.assertEqual(r['status'],'INDETERMINATE');self.assertFalse(r['can_issue_permit'])
  return test
 setattr(CandidateTests,'test_external_reject_'+name,make(key,value))

for event in ['crash','timeout','unknown','retry','resume','repair','fallback','reserve']:
 def make(event):
  def test(self):self.assertEqual(c.simulate_attempt(['reserve',event,'begin','seal']),'HALT_UNKNOWN_NO_RESUME')
  return test
 setattr(CandidateTests,'test_attempt_terminal_'+event,make(event))
