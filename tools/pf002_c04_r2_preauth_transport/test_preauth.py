import ast,base64,copy,email.message,hashlib,io,json,os,time,unittest,urllib.error
from pathlib import Path
from unittest.mock import patch
import transport as t,runner_proof as proof,source_integrity as src,controller as c
S=Path(__file__).resolve().parent;OUT=None
API='ghs_SYNTHETIC_API_CANARY_123456789';OIDC='SYNTHETIC_OIDC_CANARY_987654321'
URL='https://vstoken.actions.githubusercontent.com/fixed?api-version=2.0'
HEAD='b'*40;RID='12345'
def headers(values=()):
 h=email.message.Message()
 for k,v in values:h[k]=v
 return h
class Response:
 def __init__(self,raw=b'{}',status=200,h=None,url=None):self.raw=raw;self.status=status;self.headers=h or headers();self.url=url;self.reads=0
 def __enter__(self):return self
 def __exit__(self,*a):return False
 def getcode(self):return self.status
 def read(self,n):self.reads+=1;return self.raw[:n]
class Opener:
 def __init__(self,values=()):self.values=list(values);self.requests=[]
 def open(self,req,timeout):
  self.requests.append(req)
  value=self.values.pop(0) if self.values else Response()
  if isinstance(value,Exception):raise value
  if value.url is None:value.url=req.full_url
  return value
def claims():
 now=int(time.time());return dict(iss=proof.ISS,aud=proof.AUD,repository=proof.REPO,repository_id='1370145728',repository_owner_id='325481386',ref=proof.REF,event_name='workflow_dispatch',runner_environment='github-hosted',workflow_ref=proof.WORKFLOW,sha=HEAD,workflow_sha=HEAD,run_id=RID,run_attempt='1',sub=f'repo:{proof.REPO}:ref:{proof.REF}',iat=now-2,nbf=now-2,exp=now+300)
class Tests(unittest.TestCase):
 def tree_fixture(self):
  base=json.loads((S/'BASE_TREE_V1.json').read_bytes())['files'];current=copy.deepcopy(base)
  for p in [*S.iterdir(),S.parent.parent/'.github/workflows/rate_pf002_c04_r2_preauth.yml']:
   raw=p.read_bytes();name=p.relative_to(S.parent.parent).as_posix();current[name]={'type':'blob','mode':'100644','size':len(raw),'sha':hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()}
  def response(rows):return {'truncated':False,'tree':[dict(path=n,**row) for n,row in sorted(rows.items())]}
  return response(current),response(base)
 def make(self,values=(),clock=time.monotonic):
  op=Opener(values);events=[];v=t.Transport(HEAD,RID,t.Credentials(API,OIDC,URL),lambda k,r:events.append((k,r)),op,clock);return v,op,events
 def rest(self,values=()):
  v,op,events=self.make([Response(),*values]);v.fetch('OIDC_TOKEN');return v,op,events
 def fail_http(self,status,h=None):
  body=io.BytesIO((API+OIDC+'PRIVATE_RESPONSE_BODY').encode());err=urllib.error.HTTPError('https://api.github.com/fixed',status,API,h or headers(),body)
  v,op,events=self.rest([err])
  with self.assertRaisesRegex(t.Rejected,'PREAUTH_HTTP_HALTED'):v.fetch('RUN_RECORD')
  self.assertEqual(v.state,'HALTED');self.assertTrue(body.closed)
  for stage in ('RUN_RECORD','PR86_BASE_REF'):
   with self.assertRaises(t.Rejected):v.fetch(stage)
  self.assertEqual(len(op.requests),2)
  for secret in (API,OIDC,'PRIVATE_RESPONSE_BODY','Authorization'):self.assertNotIn(secret,json.dumps(events))
  return v.records[-1]
 def test_credential_missing_rejects_before_io(self):
  for value in (None,'',123,True):
   with self.assertRaises(t.Rejected):t.Credentials(value,OIDC,URL)
 def test_invalid_header_credential_rejected(self):
  for value in (API+'\r\nX: x',API+' ',API+'\x00',API*300):
   with self.assertRaises(t.Rejected):t.Credentials(value,OIDC,URL)
 def test_credentials_cannot_share_channel(self):
  with self.assertRaises(t.Rejected):t.Credentials(API,API,URL)
 def test_credentials_redacted_repr(self):self.assertEqual(repr(t.Credentials(API,OIDC,URL)),'<Credentials REDACTED>')
 def test_environment_secrets_removed_even_on_invalid_input(self):
  values={'PF002_R2_API_TOKEN':'bad','ACTIONS_ID_TOKEN_REQUEST_TOKEN':OIDC,'ACTIONS_ID_TOKEN_REQUEST_URL':URL,'GITHUB_TOKEN':API,'GH_TOKEN':API}
  with patch.dict(os.environ,values,clear=True):
   with self.assertRaises(t.Rejected):t.Credentials.consume_environment()
   self.assertFalse(os.environ)
 def test_environment_secrets_not_inheritable_after_consume(self):
  with patch.dict(os.environ,{'PF002_R2_API_TOKEN':API,'ACTIONS_ID_TOKEN_REQUEST_TOKEN':OIDC,'ACTIONS_ID_TOKEN_REQUEST_URL':URL},clear=True):
   secret=t.Credentials.consume_environment();self.assertEqual(dict(os.environ),{});secret.destroy();self.assertIsNone(secret._api)
 def test_rest_uses_api_token_not_oidc(self):
  v,op,events=self.rest();v.fetch('RUN_RECORD');self.assertEqual(op.requests[-1].get_header('Authorization'),'Bearer '+API);self.assertNotIn(OIDC,str(op.requests[-1].header_items()))
 def test_oidc_request_uses_only_oidc_request_token(self):
  v,op,events=self.make();v.fetch('OIDC_TOKEN');self.assertEqual(op.requests[0].get_header('Authorization'),'bearer '+OIDC);self.assertNotIn(API,str(op.requests[0].header_items()))
 def test_five_ordered_gets_only(self):
  v,op,events=self.make()
  for stage in t.STAGES:v.fetch(stage)
  self.assertEqual(v.state,'COMPLETE');self.assertEqual(len(op.requests),5);self.assertTrue(all(r.method=='GET' for r in op.requests));self.assertEqual([r['fixed_request_stage'] for r in v.records],list(t.STAGES))
 def test_stage_jump_rejected_without_network(self):
  v,op,events=self.make()
  with self.assertRaises(t.Rejected):v.fetch('CURRENT_TREE')
  self.assertEqual(op.requests,[])
 def test_duplicate_stage_no_retry(self):
  v,op,events=self.make();v.fetch('OIDC_TOKEN')
  with self.assertRaises(t.Rejected):v.fetch('OIDC_TOKEN')
  self.assertEqual(len(op.requests),1)
 def test_finished_attempt_cannot_restart(self):
  v,op,events=self.make()
  for stage in t.STAGES:v.fetch(stage)
  with self.assertRaises(t.Rejected):v.fetch('OIDC_TOKEN')
  self.assertEqual(len(op.requests),5)
 def test_http401_is_terminal(self):self.assertEqual(self.fail_http(401)['safe_error_category'],'AUTHENTICATION_REJECTED')
 def test_insufficient_actions_permission403_is_terminal(self):self.assertEqual(self.fail_http(403)['safe_error_category'],'ACCESS_OR_POLICY_REJECTED_UNDETERMINED')
 def test_http429_is_terminal_without_retry(self):self.assertEqual(self.fail_http(429)['safe_error_category'],'RATE_LIMIT_STATUS_CAUSE_UNDETERMINED')
 def test_403_rate_limit_headers_are_evidence_not_historical_cause(self):
  r=self.fail_http(403,headers([('X-RateLimit-Limit','60'),('X-RateLimit-Remaining','0'),('X-RateLimit-Reset','1890000000'),('Retry-After','90'),('X-GitHub-Request-Id','ABCD:1234')]))
  self.assertEqual(r['safe_error_category'],'PRIMARY_RATE_LIMIT_HEADER_EVIDENCE');self.assertEqual(r['rate_limit_reset'],'1890000000');self.assertEqual(r['retry_after_seconds'],'90')
 def test_403_remaining_positive_not_guessed_as_primary_limit(self):self.assertEqual(self.fail_http(403,headers([('X-RateLimit-Remaining','7')]))['safe_error_category'],'ACCESS_OR_POLICY_REJECTED_UNDETERMINED')
 def test_http500_terminal_no_fallback(self):self.assertEqual(self.fail_http(500)['http_status'],500)
 def test_invalid_numeric_header_not_exported(self):
  r=self.fail_http(403,headers([('X-RateLimit-Remaining',API)]));self.assertIsNone(r['rate_limit_remaining']);self.assertEqual(r['safe_error_category'],'INVALID_DIAGNOSTIC_HEADERS')
 def test_duplicate_diagnostic_header_rejected(self):self.assertEqual(self.fail_http(403,headers([('X-RateLimit-Remaining','0'),('X-RateLimit-Remaining','1')]))['safe_error_category'],'INVALID_DIAGNOSTIC_HEADERS')
 def test_requestid_injection_redacted(self):
  r=self.fail_http(403,headers([('X-GitHub-Request-Id',API+'!')]));self.assertIsNone(r['github_request_id'])
 def test_unapproved_response_headers_never_exported(self):
  r=self.fail_http(403,headers([('Authorization',API),('X-Secret',OIDC)]));self.assertNotIn(API,json.dumps(r));self.assertNotIn(OIDC,json.dumps(r))
 def test_success_invalid_diagnostic_header_halts(self):
  v,op,e=self.rest([Response(h=headers([('Retry-After','-1')]))])
  with self.assertRaises(t.Rejected):v.fetch('RUN_RECORD')
  self.assertEqual(v.state,'HALTED')
 def test_redirect_handler_denies_before_follow(self):
  with self.assertRaises(t.Rejected):t.NoRedirect().redirect_request(None,None,302,'',{},'https://evil.example')
 def test_redirect_response_url_change_halts(self):
  v,op,e=self.make([Response(url='https://evil.example')])
  with self.assertRaises(t.Rejected):v.fetch('OIDC_TOKEN')
  self.assertEqual(len(op.requests),1)
 def test_oidc_endpoint_injection_rejected(self):
  for value in ('http://v.actions.githubusercontent.com/x','https://evil.example/x','https://actions.githubusercontent.com/x','https://u:p@v.actions.githubusercontent.com/x','https://v.actions.githubusercontent.com:8443/x','https://v.actions.githubusercontent.com/x#fragment',URL+'&audience=evil',URL+'\r\n'):
   with self.subTest(url=value):
    with self.assertRaises(t.Rejected):t.Credentials(API,OIDC,value)
 def test_endpoints_exact_repository_head_and_base(self):
  v,op,e=self.make();self.assertEqual(v.endpoint('RUN_RECORD'),'https://api.github.com/repos/'+proof.REPO+'/actions/runs/'+RID);self.assertEqual(v.endpoint('PR86_TREE'),'https://api.github.com/repos/'+proof.REPO+'/git/trees/'+t.BASE+'?recursive=1')
 def test_run_context_injection_rejected(self):
  for head,rid in ((True,RID),('a'*39,RID),(HEAD,'1/../../evil'),(HEAD,True),(HEAD,'0')):
   with self.assertRaises(t.Rejected):t.Transport(head,rid,t.Credentials(API,OIDC,URL),lambda *x:None,Opener())
 def test_deadline_rejects_without_request(self):
  clock=[0.0];v,op,e=self.make(clock=lambda:clock[0]);clock[0]=61
  with self.assertRaises(t.Rejected):v.fetch('OIDC_TOKEN')
  self.assertEqual(op.requests,[])
 def test_timeout_terminal_sanitized(self):
  v,op,e=self.make([TimeoutError(API+OIDC)])
  with self.assertRaises(t.Rejected) as found:v.fetch('OIDC_TOKEN')
  self.assertEqual(str(found.exception),'PREAUTH_HTTP_HALTED');self.assertNotIn(API,json.dumps(e));self.assertEqual(v.state,'HALTED')
 def test_response_bytes_over_bound_halts(self):
  v,op,e=self.make([Response(b'x'*32769)])
  with self.assertRaises(t.Rejected):v.fetch('OIDC_TOKEN')
 def test_duplicate_json_key_halts(self):
  v,op,e=self.make([Response(b'{"value":1,"value":2}')])
  with self.assertRaises(t.Rejected):v.fetch('OIDC_TOKEN')
 def test_truncated_json_halts(self):
  v,op,e=self.make([Response(b'{"value":')])
  with self.assertRaises(t.Rejected):v.fetch('OIDC_TOKEN')
 def test_nonfinite_and_utf8_rejected(self):
  for raw in (b'{"x":NaN}',b'\xff'):
   v,op,e=self.make([Response(raw)])
   with self.assertRaises(t.Rejected):v.fetch('OIDC_TOKEN')
 def test_no_implicit_proxy_discovery(self):
  with patch.object(t.urllib.request,'getproxies',side_effect=AssertionError('NO_PROXY_DISCOVERY')):v=t.Transport(HEAD,RID,t.Credentials(API,OIDC,URL),lambda *x:None)
  self.assertTrue(any(isinstance(h,t.NoRedirect) for h in v.opener.handlers))
 def test_signed_claims_exact_positive(self):self.assertEqual(proof.check_claims(claims(),int(time.time()),HEAD,RID,'1')['sha'],HEAD)
 def test_all_signed_claim_mismatches_fail_closed(self):
  for key in ('iss','aud','repository','repository_id','repository_owner_id','ref','event_name','runner_environment','workflow_ref','sha','workflow_sha','run_id','run_attempt','sub'):
   value=claims();value[key]='wrong'
   with self.subTest(claim=key):
    with self.assertRaises(proof.Refused):proof.check_claims(value,int(time.time()),HEAD,RID,'1')
 def test_expired_future_numeric_alias_claims_rejected(self):
  for key,value in (('iat',True),('exp',0),('nbf',int(time.time())+99)):
   q=claims();q[key]=value
   with self.assertRaises(proof.Refused):proof.check_claims(q,int(time.time()),HEAD,RID,'1')
 def test_signature_invalid_does_not_become_api_authority(self):
  token='eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCIsImtpZCI6Indyb25nIn0.e30.AAAA'
  with self.assertRaises(proof.Refused):proof.verify_token(token,(S/'GITHUB_OIDC_JWKS_PINNED.json').read_bytes(),int(time.time()),HEAD,RID,'1')
 def test_jwks_mutation_no_refresh_fallback(self):
  with self.assertRaisesRegex(proof.Refused,'PINNED_GITHUB_KEYS_REQUIRED'):proof.verify_token('a.b.c',b'{}',int(time.time()),HEAD,RID,'1')
 def test_r1_signature_validation_unchanged_except_fixed_namespace(self):
  old=(S.parent/'pf002_c04_r1_legacy_contract/runner_proof.py').read_text();new=(S/'runner_proof.py').read_text()
  expected=old.replace('rate-pf002-c04-r1-job-member-forensics','rate-pf002-c04-r2-preauth-only').replace('codex/pf002-c04-r1-legacy-contract-corrective-v1','codex/pf002-c04-r2-preauth-transport-v1').replace('rate_pf002_c04_r1_contract.yml','rate_pf002_c04_r2_preauth.yml')
  self.assertEqual(new,expected)
 def test_wrong_repository_run_head_workflow_rejected(self):
  q={'id':int(RID),'head_sha':HEAD,'head_branch':proof.BRANCH,'event':'workflow_dispatch','display_title':'PF002-C04-R2 qualification','run_attempt':1,'path':src.WORKFLOW,'repository':{'id':1370145728,'full_name':proof.REPO}}
  src.run_record(q,HEAD,RID,'qualification')
  for k,v in (('id',12346),('id',True),('head_sha','c'*40),('head_branch','main'),('run_attempt',True),('path','.github/workflows/evil.yml'),('repository',{'id':1370145728,'full_name':'evil/repo'})):
   z=copy.deepcopy(q);z[k]=v
   with self.assertRaises(proof.Refused):src.run_record(z,HEAD,RID,'qualification')
 def test_source_tree_duplicate_path_rejects(self):
  row={'path':'file','type':'blob','mode':'100644','size':1,'sha':'a'*40}
  with self.assertRaises(proof.Refused):src.tree({'truncated':False,'tree':[row,row]})
 def test_source_tree_symlink_submodule_and_traversal_reject(self):
  row={'path':'file','type':'blob','mode':'100644','size':1,'sha':'a'*40}
  for key,value in (('mode','120000'),('mode','100755'),('type','commit'),('path','../file'),('path','a\\b'),('path','a//b'),('size',True),('sha','bad')):
   q=dict(row);q[key]=value
   with self.subTest(field=key,value=value):
    with self.assertRaises(proof.Refused):src.tree({'truncated':False,'tree':[q]})
 def test_source_tree_truncated_unknown_rejected(self):
  for value in (True,0,None):
   with self.assertRaises(proof.Refused):src.tree({'truncated':value,'tree':[]})
 def test_source_manifest_mutated_file_rejected(self):
  d=OUT/self._testMethodName;d.mkdir();(d/'x.py').write_bytes(b'old');m={'version':'PF002_C04_R2_SOURCE_V1','files':{'x.py':{'bytes':3,'sha256':hashlib.sha256(b'old').hexdigest()}}};(d/'SOURCE_MANIFEST_V1.json').write_bytes(c.canonical(m));src.closed(d);(d/'x.py').write_bytes(b'new')
  with self.assertRaisesRegex(proof.Refused,'SOURCE_HASH'):src.closed(d)
 def test_closed_source_extra_injection_rejected(self):
  d=OUT/self._testMethodName;d.mkdir();(d/'SOURCE_MANIFEST_V1.json').write_bytes(c.canonical({'version':'PF002_C04_R2_SOURCE_V1','files':{}}));(d/'evil.py').write_bytes(b'bad')
  with self.assertRaises(proof.Refused):src.closed(d)
 def test_exact_new_source_manifest_validates(self):self.assertTrue(src.closed(S)['files'])
 def test_full_735_base_and_new_blob_integrity_offline(self):
  current,prior=self.tree_fixture();result=src.verify_trees(current,prior,S.parent.parent,src.closed(S));self.assertEqual(result['base_files'],735);self.assertEqual(result['current_files'],735+result['new_files']);self.assertTrue(result['base_unchanged'])
 def test_base_remote_tree_tamper_rejected(self):
  current,prior=self.tree_fixture();prior['tree'][0]['sha']='f'*40
  with self.assertRaisesRegex(proof.Refused,'EXACT_BASE_TREE'):src.verify_trees(current,prior,S.parent.parent,src.closed(S))
 def test_current_legacy_modification_rejected(self):
  current,prior=self.tree_fixture();name=prior['tree'][0]['path'];next(r for r in current['tree'] if r['path']==name)['sha']='f'*40
  with self.assertRaisesRegex(proof.Refused,'ISOLATED_ADDITIVE_SOURCE_ONLY'):src.verify_trees(current,prior,S.parent.parent,src.closed(S))
 def test_current_unapproved_file_rejected(self):
  current,prior=self.tree_fixture();current['tree'].append({'path':'tools/evil.py','sha':'e'*40,'mode':'100644','type':'blob','size':10})
  with self.assertRaisesRegex(proof.Refused,'ISOLATED_ADDITIVE_SOURCE_ONLY'):src.verify_trees(current,prior,S.parent.parent,src.closed(S))
 def test_exact_new_blob_hash_mismatch_rejected(self):
  current,prior=self.tree_fixture();next(r for r in current['tree'] if r['path']==src.SCOPE+'controller.py')['sha']='f'*40
  with self.assertRaisesRegex(proof.Refused,'REMOTE_EXACT_BLOB'):src.verify_trees(current,prior,S.parent.parent,src.closed(S))
 def test_authenticate_full_flow_offline_not_runtime_proof(self):
  current,prior=self.tree_fixture();q=claims();selected=proof.check_claims(q,int(time.time()),HEAD,RID,'1')
  run={'id':int(RID),'head_sha':HEAD,'head_branch':proof.BRANCH,'event':'workflow_dispatch','display_title':'PF002-C04-R2 qualification','run_attempt':1,'path':src.WORKFLOW,'repository':{'id':1370145728,'full_name':proof.REPO}}
  ref={'ref':'refs/heads/'+t.BASE_BRANCH,'object':{'type':'commit','sha':t.BASE}}
  responses=[Response(c.canonical(r)) for r in ({'value':OIDC},run,ref,current,prior)]
  v,op,events=self.make(responses)
  with patch.object(proof,'verify_token',return_value=selected) as verify:
   details=c.authenticate(v,HEAD,RID,'qualification',src.closed(S));verify.assert_called_once()
  result=c.receipt(HEAD,RID,'qualification',v.records,True,details);self.assertTrue(result['authentication_completed']);self.assertEqual(len(op.requests),5);self.assertFalse(result['receipt_is_execution_authorization']);self.assertEqual(result['native_dispatches'],0)
  for secret in (API,OIDC):self.assertNotIn(secret,json.dumps(result))
 def test_oidc_claim_failure_prevents_rest_reads(self):
  v,op,events=self.make([Response(c.canonical({'value':OIDC}))])
  with patch.object(proof,'verify_token',side_effect=proof.Refused('CLAIM_sha')):
   with self.assertRaises(proof.Refused):c.authenticate(v,HEAD,RID,'qualification',src.closed(S))
  self.assertEqual(len(op.requests),1);self.assertEqual(v.records[0]['fixed_request_stage'],'OIDC_TOKEN');self.assertEqual(v.state,'HALTED')
 def test_authenticate_binding_rejection_permanently_halts_transport(self):
  selected=proof.check_claims(claims(),int(time.time()),HEAD,RID,'1')
  v,op,e=self.make([Response(c.canonical({'value':OIDC})),Response(c.canonical({'id':12346}))])
  with patch.object(proof,'verify_token',return_value=selected):
   with self.assertRaises(proof.Refused):c.authenticate(v,HEAD,RID,'qualification',src.closed(S))
  self.assertEqual(v.state,'HALTED')
  with self.assertRaises(t.Rejected):v.fetch('PR86_BASE_REF')
  self.assertEqual(len(op.requests),2)
 def test_authenticate_bad_signature_permanently_halts_transport(self):
  key=json.loads((S/'GITHUB_OIDC_JWKS_PINNED.json').read_bytes())['keys'][0]
  def enc(raw):return base64.urlsafe_b64encode(raw).decode().rstrip('=')
  header={'alg':'RS256','typ':'JWT','kid':key['kid']};size=len(proof.b64(key['n']))
  token=enc(c.canonical(header))+'.'+enc(c.canonical(claims()))+'.'+enc(b'\0'*size)
  v,op,e=self.make([Response(c.canonical({'value':token}))])
  with self.assertRaisesRegex(proof.Refused,'RUNNER_SIGNATURE'):c.authenticate(v,HEAD,RID,'qualification',src.closed(S))
  self.assertEqual(v.state,'HALTED')
  with self.assertRaises(t.Rejected):v.fetch('RUN_RECORD')
  self.assertEqual(len(op.requests),1)
 def test_authenticate_ref_and_tree_rejection_are_terminal(self):
  selected=proof.check_claims(claims(),int(time.time()),HEAD,RID,'1')
  run={'id':int(RID),'head_sha':HEAD,'head_branch':proof.BRANCH,'event':'workflow_dispatch','display_title':'PF002-C04-R2 qualification','run_attempt':1,'path':src.WORKFLOW,'repository':{'id':1370145728,'full_name':proof.REPO}}
  ref={'ref':'refs/heads/'+t.BASE_BRANCH,'object':{'type':'commit','sha':t.BASE}}
  for stage in ('REF','TREE'):
   current,prior=self.tree_fixture();r=copy.deepcopy(ref)
   if stage=='REF':r['object']['sha']='a'*40
   else:prior['tree'][0]['sha']='a'*40
   v,op,e=self.make([Response(c.canonical(x)) for x in ({'value':OIDC},run,r,current,prior)])
   with patch.object(proof,'verify_token',return_value=selected):
    with self.assertRaises(proof.Refused):c.authenticate(v,HEAD,RID,'qualification',src.closed(S))
   self.assertEqual(v.state,'HALTED')
   with self.assertRaises(t.Rejected):v.fetch('OIDC_TOKEN')
   self.assertEqual(len(op.requests),3 if stage=='REF' else 5)
 def test_bad_oidc_response_schema_never_reads_rest(self):
  v,op,events=self.make([Response(c.canonical({'value':OIDC,'extra':API}))])
  with self.assertRaisesRegex(proof.Refused,'OIDC_RESPONSE_SCHEMA'):c.authenticate(v,HEAD,RID,'qualification',src.closed(S))
  self.assertEqual(len(op.requests),1)
 def test_invalid_receipt_cannot_claim_authentication(self):
  for records in ([],[{'fixed_request_stage':'RUN_RECORD'}]):
   with self.assertRaises(proof.Refused):c.receipt(HEAD,RID,'qualification',records,True,{})
 def test_receipt_schema_and_record_fields_synchronized(self):
  v,op,e=self.make();v.fetch('OIDC_TOKEN');schema=json.loads((S/'EVIDENCE_SCHEMA_V1.json').read_bytes());self.assertEqual(set(schema['http_record_fields']),set(v.records[0]));self.assertEqual(schema['stages'],list(t.STAGES))
 def test_halt_receipt_cannot_export_unknown_fields_or_canary(self):
  v,op,e=self.make();v.fetch('OIDC_TOKEN');records=copy.deepcopy(v.records);records[0]['secret']=API
  with self.assertRaises(proof.Refused):c.receipt(HEAD,RID,'qualification',records,False,None)
 def test_workflow_step_token_not_cli_or_job_environment(self):
  text=(S.parent.parent/src.WORKFLOW).read_text();self.assertIn('          PF002_R2_API_TOKEN: ${{ github.token }}',text);self.assertIn('      actions: read',text);self.assertIn('      id-token: write',text);self.assertNotIn('secrets.',text);self.assertNotIn('GITHUB_TOKEN=',text);self.assertNotIn('  native:',text);self.assertNotIn('normal_worker.py',text)
 def test_stage_jump_poisoned_attempt_cannot_continue(self):
  v,op,e=self.make()
  with self.assertRaises(t.Rejected):v.fetch('RUN_RECORD')
  with self.assertRaises(t.Rejected):v.fetch('OIDC_TOKEN')
  self.assertEqual(v.state,'HALTED');self.assertEqual(op.requests,[])
 def test_duplicate_poisoned_attempt_cannot_continue(self):
  v,op,e=self.make();v.fetch('OIDC_TOKEN')
  with self.assertRaises(t.Rejected):v.fetch('OIDC_TOKEN')
  with self.assertRaises(t.Rejected):v.fetch('RUN_RECORD')
  self.assertEqual(len(op.requests),1);self.assertEqual(v.state,'HALTED')
 def test_start_evidence_write_failure_poisoned_no_http(self):
  v,op,e=self.make();v.emit=lambda *x:(_ for _ in ()).throw(OSError('SYNTHETIC_WRITE_FAILURE'))
  with self.assertRaises(OSError):v.fetch('OIDC_TOKEN')
  with self.assertRaises(t.Rejected):v.fetch('RUN_RECORD')
  self.assertEqual(op.requests,[]);self.assertEqual(v.state,'HALTED')
 def test_result_evidence_failure_poisoned_no_followup(self):
  v,op,e=self.make()
  def emit(event,data):
   if event=='PREAUTH_HTTP_RESULT':raise OSError('SYNTHETIC_RESULT_WRITE_FAILURE')
  v.emit=emit
  with self.assertRaises(OSError):v.fetch('OIDC_TOKEN')
  with self.assertRaises(t.Rejected):v.fetch('RUN_RECORD')
  self.assertEqual(len(op.requests),1);self.assertEqual(v.state,'HALTED')
 def test_deadline_poisoned_even_if_clock_moves_back(self):
  clock=[0.0];v,op,e=self.make(clock=lambda:clock[0]);clock[0]=61
  with self.assertRaises(t.Rejected):v.fetch('OIDC_TOKEN')
  clock[0]=0
  with self.assertRaises(t.Rejected):v.fetch('OIDC_TOKEN')
  self.assertEqual(v.state,'HALTED');self.assertEqual(op.requests,[])
 def test_secret_reflection_raw_fragment_base64_hex_fail_closed(self):
  secret='SYNTHETICSECRETALNUM'*2
  for echo in (secret,secret[4:20],base64.b64encode(secret.encode()).decode().rstrip('='),secret.encode().hex()):
   op=Opener([Response(),urllib.error.HTTPError('https://api.github.com/fixed',403,'',headers([('X-GitHub-Request-Id',echo)]),io.BytesIO(b'PRIVATE'))]);events=[]
   v=t.Transport(HEAD,RID,t.Credentials(secret,OIDC,URL),lambda k,r:events.append((k,r)),op);v.fetch('OIDC_TOKEN')
   with self.assertRaises(t.Rejected):v.fetch('RUN_RECORD')
   self.assertIsNone(v.records[-1]['github_request_id']);self.assertEqual(v.records[-1]['safe_error_category'],'SECRET_REFLECTION_BLOCKED');self.assertNotIn(echo,json.dumps(events))
 def test_jwt_reflection_registered_before_rest(self):
  jwt='SYNTHETICJWTCONFIDENTIALVALUE98765'
  v,op,e=self.make([Response(c.canonical({'value':jwt})),Response(h=headers([('X-GitHub-Request-Id',jwt)]))]);v.fetch('OIDC_TOKEN')
  with self.assertRaises(t.Rejected):v.fetch('RUN_RECORD')
  self.assertNotIn(jwt,json.dumps(e));self.assertEqual(v.state,'HALTED')
 def test_deadline_callback_only_self_exits_no_io(self):
  with patch.object(c.os,'_exit',side_effect=RuntimeError('SIMULATED_SELF_EXIT')) as exit:
   with self.assertRaisesRegex(RuntimeError,'SIMULATED_SELF_EXIT'):c.DeadlineGuard().expire()
   exit.assert_called_once_with(124)
  body=next(n for n in ast.walk(ast.parse((S/'controller.py').read_text())) if isinstance(n,ast.ClassDef) and n.name=='DeadlineGuard')
  expire=next(n for n in body.body if isinstance(n,ast.FunctionDef) and n.name=='expire');self.assertEqual(len(expire.body),1);self.assertEqual(ast.unparse(expire.body[0]),'os._exit(124)')
 def test_receipt_never_authorizes_native(self):
  r=c.receipt(HEAD,RID,'qualification',[],False,None)
  self.assertFalse(r['receipt_is_execution_authorization']);self.assertFalse(r['authentication_completed']);self.assertEqual(r['native_comparator'],'NOT_QUALIFIED');self.assertEqual(r['owned_jobs'],0);self.assertTrue(r['NoAutoNext'])
 def test_journal_chain_and_exclusive_no_overwrite(self):
  d=OUT/self._testMethodName;d.mkdir();j=c.Journal(d,HEAD,RID,'qualification');j.emit('PREAUTH_HTTP_START',{});first=(d/'0001_PREAUTH_HTTP_START.json').read_bytes();j.emit('PREAUTH_HALT',{})
  second=json.loads((d/'0002_PREAUTH_HALT.json').read_bytes());self.assertEqual(second['previous_sha256'],hashlib.sha256(first).hexdigest())
  with self.assertRaises(FileExistsError):c.save(d/'0001_PREAUTH_HTTP_START.json',{})
 def test_native_process_registry_dispatch_guard_rejects(self):
  for event in ('ctypes.dlopen','ctypes.dlsym','subprocess.Popen','os.spawn','os.system','winreg.OpenKey'):
   with self.assertRaises(PermissionError):c.runtime_audit(event,())
 def test_no_native_or_legacy_import_successor(self):
  for n in ('controller.py','transport.py','source_integrity.py','runner_proof.py'):
   tree=ast.parse((S/n).read_text());imports={x.name.split('.')[0] for node in ast.walk(tree) if isinstance(node,(ast.Import,ast.ImportFrom)) for x in (node.names if isinstance(node,ast.Import) else [])}
   self.assertFalse(imports&{'ctypes','cffi','subprocess','job','probe','winreg','normal_worker','source_loader'})
  text=(S/'controller.py').read_text();self.assertNotIn('job.launch',text);self.assertNotIn('CreateProcess',text);self.assertNotIn('loader.load',text)
 def test_no_error_body_traceback_environment_print(self):
  text=(S/'controller.py').read_text();self.assertNotIn('traceback.print',text);self.assertNotIn('print(os.environ',text);self.assertNotIn('print(exc',text)
 def test_no_test_skips_xfail_or_whitelist(self):
  tree=ast.parse((S/'test_preauth.py').read_text())
  for n in ast.walk(tree):
   if isinstance(n,(ast.FunctionDef,ast.ClassDef)):
    for d in n.decorator_list:self.assertNotIn(ast.unparse(d).split('(')[0],('unittest.skip','unittest.skipIf','unittest.skipUnless','unittest.expectedFailure'))
 def test_no_runtime_promotion_in_source_schema(self):
  schema=json.loads((S/'EVIDENCE_SCHEMA_V1.json').read_bytes());self.assertEqual(schema['native_dispatches'],0)
  with self.assertRaisesRegex(proof.Refused,'RECEIPT_INCOMPLETE_AUTHENTICATION'):c.receipt(HEAD,RID,'qualification',[],True,{})
