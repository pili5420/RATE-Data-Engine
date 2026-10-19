"""Offline integration/negative checks only. No real process, network or DLL dispatch."""
import ast,base64,copy,hashlib,json,os,struct,types,unittest
from pathlib import Path
from unittest.mock import patch
import controller as auth,contract,canonical_file as canonical,model,runner_proof as proof,source_integrity as source,transport,execution
from invocation_boundary import Boundary
import job
import stage_a
S=Path(__file__).resolve().parent;ROOT=S.parent.parent;OUT=None
H='a'*40;RID='123456789';N='b'*64;ROLE='qualification';NOW=2000000000;EXE=r'C:\hostedtoolcache\Python\3.12.10\x64\python.exe';PRIVATE=r'D:\a\_temp\PF002-C04-R3-123456789-1-qualification\normal';M='c'*64;W='d'*64
def claims():
 return {'iss':proof.ISS,'aud':proof.AUD,'repository':proof.REPO,'repository_id':'1370145728','repository_owner_id':'325481386','ref':proof.REF,'event_name':'workflow_dispatch','runner_environment':'github-hosted','workflow_ref':proof.WORKFLOW,'sha':H,'workflow_sha':H,'run_id':RID,'run_attempt':'1','sub':f'repo:{proof.REPO}:ref:{proof.REF}','iat':NOW-10,'nbf':NOW-10,'exp':NOW+300}
def ready():return {'state':'READY','head':H,'role':ROLE,'run_id':RID,'attempt':1,'nonce':N,'pid':77,'executable':EXE,'source_manifest_sha256':M,'worker_source_sha256':W,'credential_variables_absent':True,'NoAutoNext':True}
def check_ready(v):return contract.worker_receipt(contract.canonical(v),'READY',H,RID,ROLE,N,77,EXE,M,W)
def identity():return {'volume_serial_u64':1,'file_id_128_le':'01'+'00'*15,'file_size_bytes':128,'creation_time_100ns':100,'change_time_100ns':200,'last_write_time_100ns':150,'file_attributes_u32':32,'number_of_links':1}
def observations():
 return [{'phase':p,'schema':canonical.SCHEMA,'api':'GetFileInformationByHandleEx','time_units':'FILETIME_100NS_1601_UTC','file_descriptor':5 if i in (2,3) else 4,'native_handle':101 if i in (2,3) else 100,'identity':identity()} for i,p in enumerate(canonical.PHASES)]
def compare(rows):return canonical.compare(rows,{'bytes':128,'sha256':'e'*64})
def root():return {'pid':77,'handle':88,'creation_time_100ns':99,'image_path':EXE,'disk_image':{'canonical_source_schema':canonical.SCHEMA,'canonical_identity':identity(),'sha256':'e'*64},'membership_before':True,'membership_after':True,'wait_result':258,'exit_code':259}
def credential():return transport.Credentials('SYNTHETIC_API_9v82K6mF31R7tQ25xS41L9nB86Y4h0cD','SYNTHETIC_OIDC_6Yq78xG14R9tB52F0mP61L3nK24wS85Z','https://run-test.actions.githubusercontent.com/fixed/path?api-version=2')
class IntegrationTests(unittest.TestCase):
 def test_exact_original_c04_comparator_and_file_reader_bytes(self):
  for n in ('canonical_file.py','file_evidence.py'):
   self.assertEqual((S/n).read_bytes(),(ROOT/'tools/pf002_c04_image_identity'/n).read_bytes())
 def test_exact_four_pure_model_definitions_and_no_parent_parser(self):
  a=ast.parse((S/'model.py').read_text(encoding='utf-8'));b=ast.parse((ROOT/'tools/pf002_c04_image_identity/model.py').read_text(encoding='utf-8'))
  defs=lambda t:{n.name:ast.dump(n,include_attributes=False) for n in t.body if isinstance(n,(ast.FunctionDef,ast.ClassDef))}
  self.assertEqual(set(defs(a)),{'Unknown','need','acct','ids'})
  for name,v in defs(a).items():self.assertEqual(v,defs(b)[name])
 def test_exact_original_rsa_algorithm_and_claim_function_ast(self):
  a=ast.parse((S/'runner_proof.py').read_text());b=ast.parse((ROOT/'tools/pf002_c04_r2_preauth_transport/runner_proof.py').read_text())
  f=lambda t:{n.name:ast.dump(n,include_attributes=False) for n in t.body if isinstance(n,(ast.FunctionDef,ast.ClassDef))}
  self.assertEqual(f(a),f(b));self.assertEqual(proof.JWKS_SHA,hashlib.sha256((S/'GITHUB_OIDC_JWKS_PINNED.json').read_bytes()).hexdigest())
 def test_fresh_r3_claim_contract(self):
  value=proof.check_claims(claims(),NOW,H,RID,'1');self.assertEqual(value['aud'],'rate-pf002-c04-r3-native-stage-a');self.assertEqual(value['run_id'],RID)
 def test_real_rsa_invalid_signature_rejected(self):
  key=json.loads((S/'GITHUB_OIDC_JWKS_PINNED.json').read_bytes())['keys'][0]
  enc=lambda b:base64.urlsafe_b64encode(b).decode().rstrip('=')
  token=enc(json.dumps({'alg':'RS256','typ':'JWT','kid':key['kid']}).encode())+'.'+enc(json.dumps(claims()).encode())+'.'+enc(bytes(len(proof.b64(key['n']))))
  with self.assertRaisesRegex(proof.Refused,'RUNNER_SIGNATURE'):proof.verify_token(token,(S/'GITHUB_OIDC_JWKS_PINNED.json').read_bytes(),NOW,H,RID,'1')
 def test_synthetic_consent_cannot_initialize_real_job(self):
  error=ValueError if os.name=='nt' else job.ContainmentError;code='SIGNED_RUNNER_PROOF_REQUIRED' if os.name=='nt' else 'WINDOWS_RUNNER_ONLY'
  with self.assertRaisesRegex(error,'^'+code+'$'):job.WindowsJob('SYNTHETIC_CONSENT_NOT_A_JWT',{'PF002_ROLE':ROLE})
 def test_child_environment_exact_keys_no_case_alias_or_credentials(self):
  v=contract.child_environment(r'C:\Windows',EXE,PRIVATE,M,H,RID,ROLE,N,credential());self.assertEqual(set(v),contract.ENV_KEYS);self.assertEqual(len(v),len({k.upper() for k in v}));self.assertTrue(set(v).isdisjoint(contract.SECRET_KEYS));self.assertNotIn('GITHUB',repr(v));self.assertEqual(v['TEMP'],PRIVATE+'\\tmp')
 def test_child_environment_secret_value_rejected(self):
  c=credential()
  with self.assertRaisesRegex(proof.Refused,'CHILD_SECRET'):contract.child_environment('C:'+chr(92)+c._api,EXE,PRIVATE,M,H,RID,ROLE,N,c)
 def test_original_overlapping_secret_fixture_is_correctly_rejected(self):
  c=transport.Credentials('SYNTHETIC_API_'+'A'*40,'SYNTHETIC_OIDC_'+'B'*40,'https://run-test.actions.githubusercontent.com/fixed/path?api-version=2')
  with self.assertRaisesRegex(proof.Refused,'CHILD_SECRET_VALUE_REFLECTION'):contract.child_environment(r'C:\Windows',EXE,PRIVATE,M,H,RID,ROLE,N,c)
 def test_public_audience_and_real_secrets_have_distinct_child_projection(self):
  c=credential();self.assertTrue(c.reflected(proof.AUD));self.assertFalse(c.child_reflected(PRIVATE));self.assertTrue(c.child_reflected(c._api));self.assertTrue(c.child_reflected(c._oidc));c.add_secret('SYNTHETIC_FRESH_JWT_51a7b2t8x6k4r9q3');self.assertTrue(c.child_reflected('SYNTHETIC_FRESH_JWT_51a7b2t8x6k4r9q3'))
 def test_private_query_values_remain_forbidden_in_child_environment(self):
  c=transport.Credentials('SYNTHETIC_API_9v82K6mF31R7tQ25xS41L9nB86Y4h0cD','SYNTHETIC_OIDC_6Yq78xG14R9tB52F0mP61L3nK24wS85Z','https://run-test.actions.githubusercontent.com/fixed/path?private=SYNTHETIC_QUERY_8p7q6r5t4x3v2y1z')
  self.assertTrue(c.child_reflected('SYNTHETIC_QUERY_8p7q6r5t4x3v2y1z'))
 def test_credential_environment_removed_before_any_validation(self):
  names={k:'SYNTHETIC_SECRET_'+'x'*30 for k in contract.SECRET_KEYS};names['PF002_R3_API_TOKEN']='bad'
  with patch.dict(os.environ,names,clear=True):
   with self.assertRaises(transport.Rejected):transport.Credentials.consume_environment()
   self.assertTrue(set(os.environ).isdisjoint(names))
 def test_ready_and_complete_strict_canonical_messages(self):
  self.assertEqual(check_ready(ready())['pid'],77);v=ready();v['state']='COMPLETE';self.assertEqual(contract.worker_receipt(contract.canonical(v),'COMPLETE',H,RID,ROLE,N,77,EXE,M,W)['state'],'COMPLETE')
 def test_noncanonical_duplicate_malformed_truncated_receipts_reject(self):
  raws=[json.dumps(ready()).encode(),b'{"state":"READY","state":"READY"}\n',b'{',contract.canonical(ready())[:-2],contract.canonical(ready())+b'\n']
  for b in raws:
   with self.subTest(raw_type=len(b)),self.assertRaises((proof.Refused,ValueError)):contract.worker_receipt(b,'READY',H,RID,ROLE,N,77,EXE,M,W)
 def test_ready_unknown_extra_parent_field_rejected(self):
  v=ready();v['parent_pid']=1
  with self.assertRaises(proof.Refused):check_ready(v)
 def test_native_boundary_no_dispatch_before_auth(self):
  b=Boundary(EXE,'fixed','cwd')
  with self.assertRaises(proof.Refused):b.audit('ctypes.dlopen',('kernel32',))
  self.assertEqual(b.state,'TERMINAL')
 def test_native_boundary_exact_create_once_and_no_retry(self):
  b=Boundary(EXE,'fixed','cwd');b.arm();b.audit('_winapi.CreateProcess',(EXE,'fixed','cwd'));self.assertEqual(b.creations,1)
  with self.assertRaises(proof.Refused):b.audit('_winapi.CreateProcess',(EXE,'fixed','cwd'))
  self.assertEqual(b.state,'TERMINAL');self.assertEqual(b.creations,1)
 def test_native_boundary_wrong_command_terminal(self):
  b=Boundary(EXE,'fixed','cwd');b.arm()
  with self.assertRaises(proof.Refused):b.audit('_winapi.CreateProcess',(EXE,'injected','cwd'))
  with self.assertRaises(proof.Refused):b.audit('_winapi.CreateProcess',(EXE,'fixed','cwd'))
  self.assertEqual(b.creations,0)
 def test_native_boundary_no_network_after_preauth(self):
  b=Boundary(EXE,'fixed','cwd');b.arm()
  with self.assertRaises(PermissionError):b.audit('socket.connect',(None,None))
  self.assertEqual(b.state,'TERMINAL')
 def test_native_boundary_fixed_kernel_api_and_no_parent_or_unknown_access(self):
  for name in ('OpenProcess','NtQueryInformationProcess','CreateToolhelp32Snapshot','RegOpenKeyExW'):
   b=Boundary(EXE,'fixed','cwd');b.arm()
   with self.assertRaises(proof.Refused):b.audit('ctypes.dlsym',(types.SimpleNamespace(_name='kernel32'),name))
   self.assertEqual(b.state,'TERMINAL')
 def test_native_boundary_dll_injection_and_shell_rejected(self):
  for event,args in [('ctypes.dlopen',('ntdll',)),('os.system',('anything',)),('subprocess.Popen',('anything',))]:
   b=Boundary(EXE,'fixed','cwd');b.arm()
   with self.assertRaises((proof.Refused,PermissionError)):b.audit(event,args)
   self.assertEqual(b.state,'TERMINAL')
 def test_live_namespace_has_no_stage_b_parent_or_process_scanner(self):
  forbidden={'getppid','OpenProcess','NtQueryInformationProcess','CreateToolhelp32Snapshot','Process32FirstW','RegOpenKeyExW','GetCimInstance','observe','classify','pbi'}
  for n in ('job.py','stage_a.py','normal_worker.py','execution.py','entry.py','model.py'):
   tree=ast.parse((S/n).read_text(encoding='utf-8'))
   for node in ast.walk(tree):
    if isinstance(node,ast.Attribute):self.assertNotIn(node.attr,forbidden,(n,node.attr))
    if isinstance(node,(ast.FunctionDef,ast.ClassDef)):self.assertNotIn(node.name,forbidden,(n,node.name))
  self.assertNotIn('SyntheticConsent',(S/'entry.py').read_text())
 def test_job_signature_check_precedes_ctypes_and_kernel_loading(self):
  text=(S/'job.py').read_text();self.assertLess(text.index('verifier.verify_token('),text.index('  import ctypes'));self.assertLess(text.index('verifier.verify_token('),text.index("ctypes.WinDLL('kernel32'"))
 def test_only_fixed_normal_command(self):
  expected=[__import__('sys').executable,'-I','-B','-S',str(S/'normal_worker.py')];self.assertEqual(job.checked_command(expected,{}),'normal')
  for cmd in (expected+['extra'],['cmd.exe','/c','x'],tuple(expected)):
   with self.assertRaises(job.ContainmentError):job.checked_command(cmd,{})
 def test_known_root_domain_and_empty_terminal_domain(self):
  self.assertTrue(contract.known_domain({'ActiveProcesses':1},{'pids':[77],'assigned':1,'listed':1},77,True)['no_member_inspection']);self.assertEqual(contract.known_domain({'ActiveProcesses':0},{'pids':[],'assigned':0,'listed':0},77,False)['authorized_pids'],[])
 def test_unknown_job_member_rejected_without_inspection(self):
  with self.assertRaisesRegex(proof.Refused,'UNKNOWN_JOB_MEMBER'):contract.known_domain({'ActiveProcesses':2},{'pids':[77,99],'assigned':2,'listed':2},77,True)
 def test_accounting_incomplete_or_divergent_rejected(self):
  for account,ids in [({'ActiveProcesses':0},{'pids':[77],'assigned':1,'listed':1}),({'ActiveProcesses':1},{'pids':[77],'assigned':2,'listed':1}),({'ActiveProcesses':True},{'pids':[77],'assigned':1,'listed':1})]:
   with self.assertRaises(proof.Refused):contract.known_domain(account,ids,77,True)
 def test_canonical_all_five_phases_and_distinct_reopen_handles(self):
  self.assertTrue(compare(observations())['equal']);v=observations();v[2]['native_handle']=v[0]['native_handle']
  with self.assertRaises(model.Unknown):compare(v)
 def test_canonical_class_buffer_type_and_abi_boundaries(self):
  for info,raw in [(0,bytes(39)),(18,bytes(23)),(1,bytes(25)),(True,bytes(24)),(99,bytes(24))]:
   with self.assertRaises(model.Unknown):canonical.decode(info,raw)
 def test_canonical_full_128bit_file_id_high_half_matters(self):
  v=observations();v[3]['identity']['file_id_128_le']='01'+'00'*14+'80';self.assertFalse(compare(v)['equal'])
 def test_canonical_hash_size_truncation_and_type_confusion_reject(self):
  for h in ({'bytes':127,'sha256':'e'*64},{'bytes':True,'sha256':'e'*64},{'bytes':128,'sha256':'bad'}):
   with self.assertRaises(model.Unknown):canonical.compare(observations(),h)
 def test_canonical_reparse_directory_and_zero_identity_reject(self):
  for key,val in [('file_attributes_u32',0x400),('file_attributes_u32',0x10),('number_of_links',0),('volume_serial_u64',True),('file_id_128_le','00'*16)]:
   v=identity();v[key]=val
   with self.assertRaises(model.Unknown):canonical.validate(v)
 def test_root_observation_identity_and_liveness_positive(self):self.assertTrue(contract.root_equivalent(root(),root()))
 def test_complete_pass_requires_all_stages_cleanup_and_exit0(self):
  self.assertEqual(contract.stage_pass(True,True,True,True,True,0,True,True)['RS02'],'BLOCKED')
  args=[True,True,True,True,True,0,True,True]
  for i in range(8):
   values=args[:];values[i]=False if i!=5 else 1
   with self.assertRaises(proof.Refused):contract.stage_pass(*values)
 def test_native_watchdog_policy_quiesces_preauth_and_records_unknown_abrupt_cleanup(self):
  text=(S/'execution.py').read_text();self.assertLess(text.index('pre_timer.quiesce()'),text.index('boundary.arm()'));self.assertLess(text.index('job=StageAJob'),text.index('native_timer=PhaseTimer(20)'));self.assertIn("'abrupt_cleanup_outcome':'NOT_OBSERVED_MUST_REMAIN_UNKNOWN'",text);self.assertNotIn('time.sleep',text)
 def test_output_alias_source_manifest_and_physical_checks(self):
  self.assertEqual(source.closed(S)['version'],'PF002_C04_R3_SOURCE_V1')
  bad=OUT/'badsource';bad.mkdir();(bad/'SOURCE_MANIFEST_V1.json').write_bytes(b'{"version":"wrong","files":{}}')
  with self.assertRaises(proof.Refused):source.closed(bad)
 def test_journal_exclusive_no_overwrite_and_strict_hash_link(self):
  p=OUT/'journal';p.mkdir();j=execution.Journal(p,H,RID,ROLE);j.emit('NATIVE_STAGE_A_INTENT',{'NoAutoNext':True});j.emit('HALT',{'status':'UNKNOWN'})
  a=(p/'0001_NATIVE_STAGE_A_INTENT.json').read_bytes();b=json.loads((p/'0002_HALT.json').read_bytes());self.assertEqual(b['previous_sha256'],hashlib.sha256(a).hexdigest())
  with self.assertRaises(FileExistsError):auth.save(p/'0001_NATIVE_STAGE_A_INTENT.json',{})
 def test_workflow_offline_and_native_authorization_separation(self):
  t=(ROOT/source.WORKFLOW).read_text();self.assertIn("if: github.event_name == 'workflow_dispatch'",t);self.assertIn('needs: offline',t);self.assertEqual(t.count('id-token: write'),1);self.assertIn('actions: read',t);self.assertIn('tools/pf002_c04_r2_preauth_transport/run_tests.py',t);self.assertNotIn('secrets.',t);self.assertNotIn('rerun',t)
 def test_baseline_count_source_and_namespaces_are_fixed(self):
  v=json.loads((S/'BASE_TREE_V1.json').read_bytes());self.assertEqual(v['head'],'1d32415ed1c3747b2ed7cba4ac19ccdeaaf78848');self.assertEqual(len(v['files']),748);self.assertEqual(transport.STAGES,('OIDC_TOKEN','RUN_RECORD','PR87_BASE_REF','CURRENT_TREE','PR87_TREE'))
 def test_official_new_run_title_head_workflow_and_id_binding(self):
  v={'head_sha':H,'head_branch':proof.BRANCH,'event':'workflow_dispatch','display_title':'PF002-C04-R3 '+ROLE,'run_attempt':1,'id':int(RID),'path':source.WORKFLOW,'repository':{'id':1370145728,'full_name':proof.REPO}}
  source.run_record(v,H,RID,ROLE)
  for key,value in [('head_sha','f'*40),('id',1),('display_title','PF002-C04-R2 '+ROLE),('path','.github/workflows/rate_pf002_c04_r2_preauth.yml'),('run_attempt',True)]:
   wrong=copy.deepcopy(v);wrong[key]=value
   with self.assertRaises(proof.Refused):source.run_record(wrong,H,RID,ROLE)
 def test_signature_or_stale_receipt_rejection_is_terminal_before_native(self):
  class T:
   state='ACTIVE'
   calls=[]
   def fetch(self,stage):self.calls.append(stage);return {'value':'SYNTHETIC_NOT_A_JWT'}
   def halt(self):self.state='HALTED'
  t=T()
  with self.assertRaises(proof.Refused):auth.authenticate(t,H,RID,ROLE,{})
  self.assertEqual(t.state,'HALTED');self.assertEqual(t.calls,['OIDC_TOKEN'])
 def test_emit_failure_before_assign_terminates_only_owned_suspended_root(self):
  obj,calls=resource_job('CreateProcess',0)
  with self.assertRaises(OSError):obj.assign_and_resume(7,8,77,88,6)
  self.assertEqual(calls,['emit:CreateProcess',('terminate_known_handle',7,121),('wait',7,10000),('close',8)])
  self.assertEqual(obj.unassigned_root_cleanup['status'],'KNOWN_ROOT_TERMINAL')
 def test_assign_failure_emit_failure_cannot_skip_known_root_cleanup(self):
  obj,calls=resource_job('AssignProcessToJobObject',0)
  with self.assertRaises(OSError):obj.assign_and_resume(7,8,77,88,6)
  self.assertEqual(calls[-3:],[('terminate_known_handle',7,121),('wait',7,10000),('close',8)])
  self.assertNotIn('resume',calls)
 def test_assigned_root_emit_failure_never_individually_terminates(self):
  obj,calls=resource_job('AssignProcessToJobObject',2)
  with self.assertRaises(OSError):obj.assign_and_resume(7,8,77,88,6)
  self.assertEqual(calls[-1],('close',8));self.assertFalse(any(isinstance(c,tuple) and c[0]=='terminate_known_handle' for c in calls));self.assertNotIn('resume',calls)
 def test_unassigned_root_termination_failure_still_closes_thread(self):
  obj,calls=resource_job('CreateProcess',0)
  def fail(*a):calls.append('termination_raised');raise OSError('SYNTHETIC_TERMINATION_FAILURE')
  obj.api.TerminateProcess=fail
  with self.assertRaises(OSError):obj.assign_and_resume(7,8,77,88,6)
  self.assertEqual(calls[-2:],['termination_raised',('close',8)]);self.assertEqual(obj.unassigned_root_cleanup['status'],'UNKNOWN')
 def test_constructor_base_failure_closes_job_before_evidence(self):
  calls=[]
  def fail(obj,*a):obj.job=99;obj.handles=[];calls.append('base_created');raise OSError('SYNTHETIC_EVIDENCE_FAILURE')
  def close(obj):calls.append('close');return {'status':'CLOSED'}
  with patch.object(job.WindowsJob,'__init__',fail),patch.object(stage_a.StageAJob,'close',close):
   with self.assertRaises(OSError):stage_a.StageAJob('SYNTHETIC',{},lambda *a:calls.append('emit'),10)
  self.assertEqual(calls,['base_created','close','emit'])
 def test_cleanup_failure_and_evidence_failure_still_close(self):
  calls=[]
  def fail():calls.append('cleanup');raise OSError('SYNTHETIC_FAILURE')
  def emit(*a):calls.append('emit');raise OSError('SYNTHETIC_EVIDENCE_FAILURE')
  obj=types.SimpleNamespace(cleanup=fail,close=lambda:(calls.append('close') or {'status':'CLOSED'}),proof='SYNTHETIC')
  cleanup,closed,errors=execution.cleanup_resources(obj,emit)
  self.assertEqual(calls,['cleanup','emit','close','emit']);self.assertIsNone(cleanup);self.assertEqual(closed['status'],'CLOSED');self.assertEqual(errors,['CLEANUP_UNKNOWN','CLEANUP_EVIDENCE_UNKNOWN','CLOSE_EVIDENCE_UNKNOWN']);self.assertIsNone(obj.proof)
 def test_thread_start_failure_retains_and_closes_fd(self):
  obj,calls=resource_job(None,1);obj.io_tasks=[];obj.pending_fds={999};obj.controls={};obj.logs=[];obj.job=None;obj.handles=[]
  class InertThread:
   ident=None
   def __init__(self,**kw):pass
   def start(self):raise RuntimeError('SYNTHETIC_START_FAILURE')
   def is_alive(self):return False
  with patch.object(job.threading,'Thread',InertThread),patch.object(job.os,'close',lambda fd:calls.append(('fd_close',fd))):
   with self.assertRaises(RuntimeError):obj.start_io(999,'rb',lambda p:None,'synthetic')
   closed=obj.close()
  self.assertEqual(calls,[('fd_close',999)]);self.assertEqual(closed['status'],'CLOSED');self.assertTrue(obj.io_tasks[0]['closed'])
 def test_unfinished_io_thread_never_reports_closed(self):
  obj,calls=resource_job(None,1);obj.pending_fds=set();obj.controls={};obj.logs=[];obj.job=None;obj.handles=[]
  obj.io_tasks=[{'name':'synthetic','fd':999,'started':True,'closed':False,'thread':types.SimpleNamespace(join=lambda n:calls.append(('join',n)),is_alive=lambda:True)}]
  self.assertEqual(obj.close()['status'],'UNKNOWN');self.assertEqual(calls,[('join',1)])
 def test_raw_nonzero_bool_preserved_not_normalized(self):
  obj=object.__new__(stage_a.StageAJob);events=[];obj.job=99;obj.hp=7;obj.pid=77;obj.job_name='SYNTHETIC';obj.emit=lambda e,d:events.append((e,d))
  obj.k=types.SimpleNamespace(TerminateJobObject=lambda *a:2,GetExitCodeProcess=lambda *a:2);obj.c=types.SimpleNamespace(set_last_error=lambda n:None,get_last_error=lambda:0,byref=lambda x:x);obj.w=types.SimpleNamespace(DWORD=lambda:types.SimpleNamespace(value=0));obj.confirm_handles=lambda end:None;obj.query=lambda kind:({'ActiveProcesses':0} if kind==1 else {'pids':[],'assigned':0,'listed':0})
  obj.cleanup();self.assertEqual(events[0][1]['raw_return'],2);self.assertIs(events[0][1]['ok'],True);self.assertEqual(events[1][1]['raw_return'],2)
 def test_release_write_failure_still_closes_known_fd(self):
  obj,calls=resource_job(None,1);obj.ready_received=True;obj.release_sent=False;obj.controls={'release_write':999}
  def fail(fd,value):calls.append(('write',fd,value));raise OSError('SYNTHETIC_PIPE_FAILURE')
  with patch.object(job.os,'write',fail),patch.object(job.os,'close',lambda fd:calls.append(('fd_close',fd))):
   with self.assertRaises(OSError):obj.release_worker()
  self.assertEqual(calls,[('write',999,b'1'),('fd_close',999)]);self.assertTrue(obj.release_close['closed']);self.assertTrue(obj.release_sent)
  with self.assertRaises(job.ContainmentError):obj.release_worker()
 def test_release_close_failure_is_preserved_not_retried_or_passed(self):
  obj,calls=resource_job(None,1);obj.ready_received=True;obj.release_sent=False;obj.controls={'release_write':999};obj.pending_fds=set();obj.logs=[];obj.io_tasks=[];obj.handles=[];obj.job=None
  def fail(fd):calls.append(('fd_close',fd));raise OSError('SYNTHETIC_CLOSE_FAILURE')
  with patch.object(job.os,'write',lambda fd,value:1),patch.object(job.os,'close',fail):
   with self.assertRaises(OSError):obj.release_worker()
   closed=obj.close()
  self.assertEqual(calls,[('fd_close',999)]);self.assertEqual(closed['status'],'UNKNOWN')
 def test_io_join_failure_does_not_skip_job_and_known_handle_close(self):
  obj,calls=resource_job(None,1);obj.pending_fds=set();obj.controls={};obj.logs=[];obj.handles=[7]
  def fail(n):calls.append('join_failed');raise RuntimeError('SYNTHETIC_JOIN_FAILURE')
  obj.io_tasks=[{'name':'synthetic','fd':999,'started':True,'closed':False,'thread':types.SimpleNamespace(join=fail,is_alive=lambda:True)}]
  closed=obj.close();self.assertEqual(calls,['join_failed',('close',99),('close',7)]);self.assertEqual(closed['status'],'UNKNOWN')
 def test_failed_thread_close_is_included_and_not_retried(self):
  obj,calls=resource_job(None,1);obj.pending_fds=set();obj.controls={};obj.logs=[];obj.handles=[7];obj.io_tasks=[];obj.thread_close={'handle':8,'raw_return':0,'closed':False,'win32_error':5}
  self.assertEqual(obj.close()['status'],'UNKNOWN');self.assertEqual(calls,[('close',99),('close',7)]);self.assertEqual(obj.close()['status'],'UNKNOWN');self.assertEqual(calls,[('close',99),('close',7)])

def resource_job(fail_event,assigned):
 obj=object.__new__(job.WindowsJob);calls=[];obj.job=99;obj.unassigned_root_cleanup=None;obj.c=types.SimpleNamespace(get_last_error=lambda:5)
 def emit(e,d):
  calls.append('emit:'+d['api'])
  if d['api']==fail_event:raise OSError('SYNTHETIC_EVIDENCE_FAILURE')
 obj.emit=emit;obj.active=lambda:1;obj.pids=lambda:[77]
 obj.api=types.SimpleNamespace(TerminateProcess=lambda hp,code:calls.append(('terminate_known_handle',hp,code)))
 obj.k=types.SimpleNamespace(AssignProcessToJobObject=lambda *a:assigned,WaitForSingleObject=lambda hp,n:(calls.append(('wait',hp,n)) or 0),CloseHandle=lambda h:(calls.append(('close',h)) or 1),ResumeThread=lambda h:(calls.append('resume') or 1))
 return obj,calls

def negative_claim(field,value):
 def test(self):
  c=claims();c[field]=value
  with self.assertRaises(proof.Refused):proof.check_claims(c,NOW,H,RID,'1')
 return test
for field,value in [('aud','rate-pf002-c04-r2-preauth-only'),('sha','f'*40),('workflow_sha','f'*40),('run_id','123'),('run_attempt','2'),('ref','refs/heads/main'),('workflow_ref','wrong'),('repository','wrong/repo'),('runner_environment','self-hosted'),('exp',NOW),('iat',True)]:setattr(IntegrationTests,'test_reject_claim_'+field,negative_claim(field,value))
def negative_ready(field,value):
 def test(self):
  v=ready();v[field]=value
  with self.assertRaises(proof.Refused):check_ready(v)
 return test
for field,value in [('nonce','f'*64),('head','f'*40),('pid',88),('attempt',True),('credential_variables_absent',1),('source_manifest_sha256','f'*64),('worker_source_sha256','f'*64),('state','COMPLETE'),('NoAutoNext',False)]:setattr(IntegrationTests,'test_reject_worker_'+field,negative_ready(field,value))
def changed_file(field):
 def test(self):
  v=observations();x=v[4]['identity'][field];v[4]['identity'][field]=('02'+'00'*15) if type(x) is str else x+1;self.assertFalse(compare(v)['equal'])
 return test
for field in canonical.FIELDS:setattr(IntegrationTests,'test_file_change_'+field,changed_file(field))
def changed_root(field,value):
 def test(self):
  a=root();b=copy.deepcopy(a);b[field]=value
  with self.assertRaises((proof.Refused,model.Unknown)):contract.root_equivalent(a,b)
 return test
for field,value in [('pid',99),('handle',99),('creation_time_100ns',100),('image_path',r'C:\wrong.exe'),('membership_after',False),('wait_result',0),('exit_code',0)]:setattr(IntegrationTests,'test_root_change_'+field,changed_root(field,value))
