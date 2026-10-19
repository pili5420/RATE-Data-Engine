"""Synthetic control-flow providers only; neither real audit events nor Windows APIs."""
import ast,copy,hashlib,json,sys,time,traceback,types,unittest
from pathlib import Path
from unittest.mock import patch
import invocation_boundary as boundary,stage_a,job,execution,cleanup_state as states,model,contract,runner_proof
S=Path(__file__).resolve().parent;A=S.parent/'pf002_c04_r3_native_stage_a';ROOT=S.parent.parent;OUT=None
EXE=r'C:\fixed\python.exe';CMD='C:\\fixed\\python.exe -I -B -S C:\\fixed\\normal_worker.py';CWD=r'C:\fixed'
def account():return dict(zip(('TotalUserTime','TotalKernelTime','ThisPeriodTotalUserTime','ThisPeriodTotalKernelTime','TotalPageFaultCount','TotalProcesses','ActiveProcesses','TotalTerminatedProcesses'),[0]*8))
def fake_job(phase=states.NO_ROOT):
 o=object.__new__(stage_a.StageAJob);o.job=99;o.job_name='SYNTHETIC_NEW_OWNED_JOB';o.root_phase=phase;o.root_creation_outcome='NOT_ATTEMPTED' if phase==states.NO_ROOT else 'RETURNED_OWNED_HANDLE';o.root_pre_dispatch_receipt=None;o.handles=[];o.controls={};o.logs=[];o.pending_fds=set();o.io_tasks=[];o.proof='SYNTHETIC_NOT_A_TOKEN';o.unassigned_root_cleanup=None;o.events=[];o.calls=[]
 if phase!=states.NO_ROOT:o.hp=7;o.pid=77;o.handles=[7]
 o.emit=lambda e,d:o.events.append({'event':e,'data':copy.deepcopy(d)})
 o.c=types.SimpleNamespace(set_last_error=lambda n:None,get_last_error=lambda:5,byref=lambda x:x);o.w=types.SimpleNamespace(DWORD=lambda:types.SimpleNamespace(value=0))
 def api(name,result):
  def f(*args):o.calls.append([name,*args]);return result
  return f
 def exit_code(h,code):o.calls.append(['GetExitCodeProcess',h]);code.value=0;return 1
 o.k=types.SimpleNamespace(TerminateJobObject=api('TerminateJobObject',1),CloseHandle=api('CloseHandle',1),WaitForSingleObject=api('WaitForSingleObject',0),GetExitCodeProcess=exit_code,AssignProcessToJobObject=api('AssignProcessToJobObject',1),ResumeThread=api('ResumeThread',1))
 o.api=types.SimpleNamespace(TerminateProcess=api('TerminateProcess',None))
 def query(kind):
  o.calls.append(['QueryOwnedJob',kind,99]);v=account()
  if phase not in (states.NO_ROOT,states.SUSPENDED):v['TotalProcesses']=1
  return v if kind==1 else {'pids':[],'assigned':0,'listed':0}
 o.query=query;o.confirm_handles=lambda end:o.calls.append(['ConfirmKnownHandles',*o.handles])
 return o
def correct_boundary():
 b=boundary.Boundary(EXE,CMD,CWD);rows=[];b.bind_evidence(lambda e,d:rows.append(copy.deepcopy(d)));b.arm();return b,rows
def rejection():
 b,rows=correct_boundary()
 try:b.audit('_winapi.CreateProcess',(EXE,CMD+' bad',CWD))
 except boundary.AuditRefused as e:return e
 raise AssertionError('EXPECTED_SYNTHETIC_REJECTION')
def closed(o):return execution.cleanup_resources(o,o.emit)
def old_cleanup():
 text=(S/'BASELINE_STAGE_A_V1.txt').read_text(encoding='utf-8');tree=ast.parse(text);c=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='StageAJob');f=copy.deepcopy(next(n for n in c.body if isinstance(n,ast.FunctionDef) and n.name=='cleanup'))
 t=ast.Module(body=[f],type_ignores=[]);ast.fix_missing_locations(t);namespace={'time':time,'model':model,'contract':contract};exec(compile(t,'PR88_frozen_stage_a_cleanup','exec'),namespace);return namespace['cleanup']
class Tests(unittest.TestCase):
 def test_correct_arguments_preserve_exact_types_and_all_predicates(self):
  b,rows=correct_boundary();b.audit('_winapi.CreateProcess',(EXE,CMD,CWD));self.assertEqual(b.creations,1);self.assertTrue(boundary.check_receipt(rows[0]));self.assertEqual(rows[0]['decision'],'ALLOW');self.assertTrue(all(rows[0]['exact_predicates'].values()));self.assertTrue(all(f['observed_type']=='str' and f['exact_match'] is True for f in rows[0]['fields'].values()))
 def test_duplicate_invocation_terminal_and_no_second_allow(self):
  b,rows=correct_boundary();b.audit('_winapi.CreateProcess',(EXE,CMD,CWD))
  with self.assertRaises(boundary.AuditRefused):b.audit('_winapi.CreateProcess',(EXE,CMD,CWD))
  self.assertEqual(b.state,'TERMINAL');self.assertEqual(b.creations,1);self.assertFalse(rows[-1]['exact_predicates']['invocation_count_is_zero'])
 def test_before_arm_rejection_is_permanently_terminal(self):
  b=boundary.Boundary(EXE,CMD,CWD);rows=[];b.bind_evidence(lambda e,d:rows.append(d))
  with self.assertRaises(boundary.AuditRefused):b.audit('_winapi.CreateProcess',(EXE,CMD,CWD))
  self.assertFalse(rows[0]['exact_predicates']['state_is_STAGE_A']);self.assertEqual(b.state,'TERMINAL')
  with self.assertRaises(runner_proof.Refused):b.arm()
 def test_evidence_sink_failure_rejects_before_dispatch_no_trusted_empty_claim(self):
  b=boundary.Boundary(EXE,CMD,CWD);b.bind_evidence(lambda *a:(_ for _ in ()).throw(OSError('SYNTHETIC_SINK_ERROR')));b.arm()
  with self.assertRaises(boundary.AuditRefused) as c:b.audit('_winapi.CreateProcess',(EXE,CMD,CWD))
  self.assertFalse(c.exception.recorded);self.assertEqual(b.creations,0);self.assertEqual(b.state,'TERMINAL')
 def test_rebind_or_arm_twice_rejected(self):
  b,rows=correct_boundary()
  with self.assertRaises(runner_proof.Refused):b.bind_evidence(lambda *a:None)
  with self.assertRaises(runner_proof.Refused):b.arm()
 def test_unknown_object_no_repr_str_equality_or_length_calls(self):
  class Bomb:
   def __repr__(self):raise AssertionError('NO_REPR')
   def __str__(self):raise AssertionError('NO_STR')
   def __eq__(self,x):raise AssertionError('NO_EQUALITY')
   def __len__(self):raise AssertionError('NO_LENGTH')
  b,rows=correct_boundary()
  with self.assertRaises(boundary.AuditRefused):b.audit('_winapi.CreateProcess',(EXE,Bomb(),CWD))
  self.assertEqual(rows[0]['fields']['command_line']['observed_type'],'OTHER')
 def test_string_subclass_does_not_call_overridden_equality(self):
  class Sub(str):
   def __eq__(self,x):raise AssertionError('NO_SUBCLASS_EQUALITY')
  b,rows=correct_boundary()
  with self.assertRaises(boundary.AuditRefused):b.audit('_winapi.CreateProcess',(EXE,Sub(CMD),CWD))
  self.assertIs(rows[0]['fields']['command_line']['exact_match'],False)
 def test_secret_or_unauthorized_command_never_exported_or_hashed(self):
  secret='SYNTHETIC_JWT_PRIVATE_9XQ2S7'*8;b,rows=correct_boundary()
  with self.assertRaises(boundary.AuditRefused):b.audit('_winapi.CreateProcess',(EXE,secret,CWD))
  encoded=json.dumps(rows);self.assertNotIn(secret,encoded);self.assertNotIn(hashlib.sha256(secret.encode('utf-16-le')).hexdigest(),encoded);self.assertIsNone(rows[0]['fields']['command_line']['approved_value_utf16le_sha256'])
 def test_overlong_unknown_value_length_is_bounded_without_hash(self):
  b,rows=correct_boundary()
  with self.assertRaises(boundary.AuditRefused):b.audit('_winapi.CreateProcess',(EXE,'x'*100000,CWD))
  self.assertEqual(rows[0]['fields']['command_line']['codepoints_capped_32769'],32769);self.assertLess(len(json.dumps(rows)),4096)
 def test_expected_invalid_unicode_nul_or_overlong_rejected(self):
  for command in ('bad\0value','bad\ud800','x'*32769):
   with self.subTest(case=len(command)),self.assertRaises(runner_proof.Refused):boundary.Boundary(EXE,command,CWD)
 def test_unicode_astral_exact_preserved_without_raw_observed_export(self):
  command=CMD+' \U0001f680';b=boundary.Boundary(EXE,command,CWD);rows=[];b.bind_evidence(lambda e,d:rows.append(d));b.arm();b.audit('_winapi.CreateProcess',(EXE,command,CWD));self.assertTrue(boundary.check_receipt(rows[0]));self.assertNotIn('\U0001f680',json.dumps(rows))
 def test_receipt_schema_matches_versioned_contract(self):
  b,rows=correct_boundary();b.audit('_winapi.CreateProcess',(EXE,CMD,CWD));schema=json.loads((A/'EVIDENCE_SCHEMA_CB01_V2.json').read_bytes());self.assertEqual(set(schema['audit_closed_keys']),set(rows[0]));self.assertEqual(schema['audit_validator'],'invocation_boundary.check_receipt');self.assertFalse(schema['cleanup_is_containment_qualification'])
 def test_empty_job_no_hp_access_no_process_api_and_close_before_confirmation(self):
  o=fake_job();cleanup,close,errors=closed(o);self.assertEqual(errors,[]);self.assertEqual(cleanup['status'],'EMPTY_JOB_CLEANUP_CONFIRMED');self.assertEqual(o.calls,[['QueryOwnedJob',1,99],['QueryOwnedJob',3,99],['CloseHandle',99]]);self.assertFalse(cleanup['containment_qualified']);self.assertEqual(o.events[-1]['event'],'OWN_JOB_CLEANUP_FINAL')
 def test_empty_job_observation_not_confirmation_before_close(self):
  o=fake_job();v=o.cleanup();self.assertEqual(v['status'],'EMPTY_JOB_OBSERVED_PENDING_CLOSE');self.assertNotIn('resource_close_confirmed',v)
 def test_empty_audit_rejected_with_valid_recorded_receipt(self):
  o=fake_job();o.root_creation_outcome='AUDIT_REJECTED_BEFORE_DISPATCH';o.root_pre_dispatch_receipt=rejection().receipt;v,c,e=closed(o);self.assertEqual(e,[]);self.assertEqual(v['status'],'EMPTY_JOB_CLEANUP_CONFIRMED')
 def test_empty_unknown_creation_outcome_cannot_be_promoted(self):
  o=fake_job();o.root_phase='CREATE_OUTCOME_UNKNOWN';o.root_creation_outcome='UNKNOWN';v,c,e=closed(o);self.assertIsNone(v);self.assertIn('CLEANUP_UNKNOWN',e);self.assertEqual(o.calls,[['CloseHandle',99]])
 def test_missing_audit_receipt_remains_unknown(self):
  o=fake_job();o.root_creation_outcome='AUDIT_REJECTED_BEFORE_DISPATCH';v,c,e=closed(o);self.assertIsNone(v);self.assertIn('CLEANUP_UNKNOWN',e)
 def test_missing_phase_or_creation_evidence_unknown(self):
  for key in ('root_phase','root_creation_outcome'):
   o=fake_job();delattr(o,key);v,c,e=closed(o);self.assertIsNone(v);self.assertIn('CLEANUP_UNKNOWN',e)
 def test_no_root_with_hp_or_pid_or_process_handle_is_contradiction(self):
  for key,val in [('hp',7),('pid',77),('handles',[7])]:
   o=fake_job();setattr(o,key,val);v,c,e=closed(o);self.assertIsNone(v);self.assertIn('CLEANUP_UNKNOWN',e);self.assertFalse(any(x[0] in ('GetExitCodeProcess','TerminateProcess','TerminateJobObject') for x in o.calls))
 def test_nonempty_unknown_member_never_opened_or_individually_terminated(self):
  o=fake_job();base=o.query;o.query=lambda k:base(k) if k==1 else {'pids':[1234],'assigned':1,'listed':1};v,c,e=closed(o);self.assertIsNone(v);self.assertIn('CLEANUP_UNKNOWN',e);self.assertEqual(o.calls[-1],['CloseHandle',99]);self.assertFalse(any(x[0] in ('OpenProcess','TerminateProcess','GetExitCodeProcess') for x in o.calls))
 def test_job_identity_change_during_reading_unknown(self):
  o=fake_job();base=o.query
  def q(k):
   v=base(k)
   if k==3:o.job_name='SYNTHETIC_CHANGED_JOB'
   return v
  o.query=q;v,c,e=closed(o);self.assertIsNone(v);self.assertIn('CLEANUP_UNKNOWN',e)
 def test_no_root_close_failure_does_not_emit_confirmation(self):
  o=fake_job();o.k.CloseHandle=lambda h:0;v,c,e=closed(o);self.assertIsNone(v);self.assertEqual(c['status'],'UNKNOWN');self.assertIn('CLOSE_UNKNOWN',e);self.assertNotIn('OWN_JOB_CLEANUP_FINAL',[x['event'] for x in o.events])
 def test_cleanup_and_close_are_one_shot(self):
  o=fake_job();v,c,e=closed(o);calls=o.calls.copy();v2,c2,e2=closed(o);self.assertEqual(o.calls,calls);self.assertIsNone(v2);self.assertIn('CLEANUP_UNKNOWN',e2);self.assertIn('CLOSE_UNKNOWN',e2)
 def test_assigned_root_uses_owned_job_and_retained_handle_only(self):
  for phase in (states.ASSIGNED,states.RESUMED):
   o=fake_job(phase);v,c,e=closed(o);self.assertEqual(e,[]);self.assertEqual(v['final_phase'],states.TERMINAL);self.assertTrue(any(x[0]=='TerminateJobObject' for x in o.calls));self.assertFalse(any(x[0]=='TerminateProcess' for x in o.calls));self.assertFalse(v['containment_qualified'])
 def test_unassigned_suspended_root_uses_only_known_handle_once(self):
  o=fake_job(states.SUSPENDED);v,c,e=closed(o);self.assertEqual(e,[]);self.assertEqual(sum(x[0]=='TerminateProcess' for x in o.calls),1);self.assertFalse(any(x[0]=='TerminateJobObject' for x in o.calls));self.assertEqual(v['final_phase'],states.TERMINAL)
 def test_already_terminated_unassigned_root_not_terminated_again(self):
  o=fake_job(states.SUSPENDED);o.unassigned_root_cleanup={'status':'KNOWN_ROOT_TERMINAL','known_root_handle':7,'pid':77,'assigned':False,'wait_result':0};v,c,e=closed(o);self.assertEqual(e,[]);self.assertFalse(any(x[0]=='TerminateProcess' for x in o.calls))
 def test_unassigned_unknown_previous_cleanup_not_retried(self):
  o=fake_job(states.SUSPENDED);o.unassigned_root_cleanup={'status':'UNKNOWN'};v,c,e=closed(o);self.assertIsNone(v);self.assertFalse(any(x[0]=='TerminateProcess' for x in o.calls))
 def test_terminate_success_is_not_terminal_proof(self):
  o=fake_job(states.RESUMED);o.confirm_handles=lambda end:(_ for _ in ()).throw(model.Unknown('SYNTHETIC_WAIT_UNKNOWN'));v,c,e=closed(o);self.assertIsNone(v);self.assertIn('CLEANUP_UNKNOWN',e)
 def test_active_exit_code_remains_unknown(self):
  o=fake_job(states.RESUMED)
  def code(h,p):p.value=259;return 1
  o.k.GetExitCodeProcess=code;v,c,e=closed(o);self.assertIsNone(v);self.assertIn('CLEANUP_UNKNOWN',e)
 def test_root_close_failure_remains_unknown(self):
  o=fake_job(states.RESUMED);o.k.CloseHandle=lambda h:0 if h==7 else 1;v,c,e=closed(o);self.assertIsNone(v);self.assertIn('CLOSE_UNKNOWN',e)
 def test_unknown_assignment_or_resume_state_never_terminal_pass(self):
  for phase in ('ASSIGN_OUTCOME_UNKNOWN','RESUME_OUTCOME_UNKNOWN','UNRECOGNIZED'):
   o=fake_job(states.RESUMED);o.root_phase=phase;v,c,e=closed(o);self.assertIsNone(v);self.assertIn('CLEANUP_UNKNOWN',e)
 def test_finalization_rejects_wrong_or_missing_close_identity(self):
  o=fake_job();row=o.cleanup();c=o.close()
  for mutate in (lambda v:v['resources'].clear(),lambda v:v['resources'][0].update(handle=100),lambda v:v['resources'][0].update(raw_return=True)):
   v=copy.deepcopy(c);mutate(v)
   with self.assertRaises(runner_proof.Refused):states.finalize(row,v)
 def test_evidence_failure_never_promotes_empty_cleanup(self):
  o=fake_job();base=o.emit
  def emit(e,d):
   if e=='OWN_JOB_CLEANUP_FINAL':raise OSError('SYNTHETIC_FINAL_EVIDENCE_FAILURE')
   base(e,d)
  v,c,e=execution.cleanup_resources(o,emit);self.assertIsNone(v);self.assertIn('CLEANUP_FINALIZATION_UNKNOWN',e)
 def test_red_green_original_no_hp_defect_preserved(self):
  o=fake_job();raw=''
  try:old_cleanup()(o)
  except AttributeError as e:self.assertEqual(e.name,'hp');raw=traceback.format_exc()
  else:self.fail('FROZEN_BASELINE_MUST_REPRODUCE_MISSING_HP')
  new=fake_job();v,c,e=closed(new);self.assertEqual(e,[]);self.assertEqual(v['status'],'EMPTY_JOB_CLEANUP_CONFIRMED')
  (OUT/'RED_BASELINE_MISSING_HP.txt').write_text(raw,encoding='utf-8');(OUT/'RED_GREEN_CONTROL_FLOW.json').write_text(json.dumps({'realm':'OFFLINE_FAKE_KERNEL_NOT_NATIVE_REPRODUCTION','baseline':'PR88_ce9aed92','RED':'AttributeError:hp','GREEN':v,'native_dispatches':0},sort_keys=True,indent=2)+'\n',encoding='utf-8')
 def test_legacy_baseline_data_hashes_are_frozen(self):
  pins=json.loads((S/'BASELINE_REFERENCE.json').read_bytes());self.assertEqual(pins['head'],'ce9aed927262fea6205a4693031979a36ff13d38')
  for name,row in pins['files'].items():self.assertEqual(hashlib.sha256((S/name).read_bytes()).hexdigest(),row['sha256'])
 def test_no_native_entry_or_dispatch_workflow(self):
  namespace={'__name__':'OFFLINE_ENTRY_INSPECTION'};exec(compile((A/'entry.py').read_bytes(),'CB01_OFFLINE_ENTRY','exec'),namespace)
  with self.assertRaisesRegex(RuntimeError,'CB01_OFFLINE_ONLY'):namespace['main']()
  w=(ROOT/'.github/workflows/rate_pf002_c04_r3_cb01_offline.yml').read_text();self.assertNotIn('workflow_dispatch',w);self.assertNotIn('id-token:',w);self.assertNotIn('entry.py',w);self.assertNotIn('actions: write',w)
 def test_fixed_source_still_denies_unknown_process_and_registry_apis(self):
  self.assertTrue({'OpenProcess','CreateToolhelp32Snapshot','NtQueryInformationProcess','RegOpenKeyExW'}.isdisjoint(contract.KERNEL_APIS));self.assertNotIn('time.sleep',(A/'stage_a.py').read_text());self.assertEqual(contract.stage_pass(True,True,True,True,True,0,True,True)['RS02'],'BLOCKED')
 def test_original_assignment_resume_transition_and_known_thread_close(self):
  o=fake_job(states.SUSPENDED);o.active=lambda:1;o.pids=lambda:[77]
  self.assertEqual(o.assign_and_resume(7,8,77,88,6),(1,[77]));self.assertEqual(o.root_phase,states.RESUMED);self.assertEqual(o.calls[-1],['CloseHandle',8])
 def test_assignment_exception_cannot_individually_terminate_unknown_membership(self):
  o=fake_job(states.SUSPENDED);o.active=lambda:1;o.pids=lambda:[77]
  o.k.AssignProcessToJobObject=lambda *a:(_ for _ in ()).throw(OSError('SYNTHETIC_ASSIGN_OUTCOME_UNKNOWN'))
  with self.assertRaises(OSError):o.assign_and_resume(7,8,77,88,6)
  self.assertEqual(o.root_phase,'ASSIGN_OUTCOME_UNKNOWN');self.assertFalse(any(x[0]=='TerminateProcess' for x in o.calls));self.assertEqual(o.thread_close['closed'],True)
 def test_resume_conflict_remains_unknown_and_no_individual_termination(self):
  o=fake_job(states.SUSPENDED);o.active=lambda:1;o.pids=lambda:[77];o.k.ResumeThread=lambda h:0
  with self.assertRaises(job.ContainmentError):o.assign_and_resume(7,8,77,88,6)
  self.assertEqual(o.root_phase,'RESUME_OUTCOME_UNKNOWN');self.assertFalse(any(x[0]=='TerminateProcess' for x in o.calls))
 def test_native_wait_implementation_timeout_not_terminal(self):
  o=fake_job(states.RESUMED);o.confirm_handles=types.MethodType(job.WindowsJob.confirm_handles,o);o.k.WaitForSingleObject=lambda h,ms:258
  v,c,e=closed(o);self.assertIsNone(v);self.assertIn('CLEANUP_UNKNOWN',e)
 def test_termination_api_failure_does_not_query_or_pass_terminal(self):
  o=fake_job(states.RESUMED);o.k.TerminateJobObject=lambda *a:0;v,c,e=closed(o);self.assertIsNone(v);self.assertIn('CLEANUP_UNKNOWN',e);self.assertFalse(any(x[0]=='GetExitCodeProcess' for x in o.calls))
 def test_missing_full_accounting_evidence_remains_unknown(self):
  o=fake_job();base=o.query;o.query=lambda k:{'ActiveProcesses':0,'TotalProcesses':0,'TotalTerminatedProcesses':0} if k==1 else base(k);v,c,e=closed(o);self.assertIsNone(v);self.assertIn('CLEANUP_UNKNOWN',e)
 def test_create_wrapper_validated_audit_rejection_has_known_no_dispatch_basis(self):
  o=fake_job();o.expected_env={};o.launch_attempted=True;exc=rejection();o.api.CreateProcess=lambda *a:(_ for _ in ()).throw(exc)
  command=[sys.executable,'-I','-B','-S',str(A/'normal_worker.py')]
  with self.assertRaises(boundary.AuditRefused):o.create_root(command,ROOT,{},None)
  self.assertEqual(o.root_phase,states.NO_ROOT);self.assertEqual(o.root_creation_outcome,'AUDIT_REJECTED_BEFORE_DISPATCH');v,c,e=closed(o);self.assertEqual(e,[]);self.assertEqual(v['status'],'EMPTY_JOB_CLEANUP_CONFIRMED')
 def test_create_wrapper_unknown_exception_does_not_claim_empty(self):
  o=fake_job();o.expected_env={};o.launch_attempted=True;o.api.CreateProcess=lambda *a:(_ for _ in ()).throw(OSError('SYNTHETIC_CREATE_UNKNOWN'))
  command=[sys.executable,'-I','-B','-S',str(A/'normal_worker.py')]
  with self.assertRaises(OSError):o.create_root(command,ROOT,{},None)
  self.assertEqual(o.root_phase,'CREATE_OUTCOME_UNKNOWN');v,c,e=closed(o);self.assertIsNone(v);self.assertIn('CLEANUP_UNKNOWN',e)
 def test_create_wrapper_unrecorded_rejection_not_known_no_root(self):
  o=fake_job();o.expected_env={};o.launch_attempted=True;exc=rejection();exc.recorded=False;o.api.CreateProcess=lambda *a:(_ for _ in ()).throw(exc)
  with self.assertRaises(boundary.AuditRefused):o.create_root([sys.executable,'-I','-B','-S',str(A/'normal_worker.py')],ROOT,{},None)
  self.assertEqual(o.root_phase,'CREATE_OUTCOME_UNKNOWN')
 def test_create_wrapper_preserves_handles_after_success_without_real_dispatch(self):
  o=fake_job();o.expected_env={};o.launch_attempted=True;o.api.CreateProcess=lambda *a:(7,8,77,88)
  self.assertEqual(o.create_root([sys.executable,'-I','-B','-S',str(A/'normal_worker.py')],ROOT,{},None),(7,8,77,88));self.assertEqual(o.root_phase,states.SUSPENDED);self.assertEqual(o.handles,[7]);self.assertEqual(o.root_creation_outcome,'RETURNED_OWNED_HANDLE')
 def test_duplicate_audit_rejection_cannot_prove_no_prior_root(self):
  b,rows=correct_boundary();b.audit('_winapi.CreateProcess',(EXE,CMD,CWD))
  with self.assertRaises(boundary.AuditRefused) as context:b.audit('_winapi.CreateProcess',(EXE,CMD,CWD))
  self.assertTrue(boundary.check_receipt(context.exception.receipt,True))
  with self.assertRaises(runner_proof.Refused):boundary.known_no_dispatch_rejection(context.exception.receipt)
  o=fake_job();o.root_creation_outcome='AUDIT_REJECTED_BEFORE_DISPATCH';o.root_pre_dispatch_receipt=context.exception.receipt;v,c,e=closed(o);self.assertIsNone(v);self.assertIn('CLEANUP_UNKNOWN',e)
 def test_preauth_audit_rejection_cannot_authorize_created_job_state(self):
  b=boundary.Boundary(EXE,CMD,CWD);b.bind_evidence(lambda *a:None)
  with self.assertRaises(boundary.AuditRefused) as context:b.audit('_winapi.CreateProcess',(EXE,CMD,CWD))
  with self.assertRaises(runner_proof.Refused):boundary.known_no_dispatch_rejection(context.exception.receipt)
 def test_direct_create_wrapper_unauthorized_command_or_cwd_denied(self):
  for command,cwd in [(['cmd.exe','/c','anything'],ROOT),([sys.executable,'-I','-B','-S',str(A/'normal_worker.py')],ROOT/'wrong')]:
   o=fake_job();o.expected_env={};o.launch_attempted=True
   with self.assertRaises(job.ContainmentError):o.create_root(command,cwd,{},None)
   self.assertEqual(o.root_phase,states.NO_ROOT)
 def test_completed_unknown_historical_job_member_not_whitelisted(self):
  o=fake_job(states.RESUMED);base=o.query
  def q(k):
   v=base(k)
   if k==1:v['TotalProcesses']=2
   return v
  o.query=q;v,c,e=closed(o);self.assertIsNone(v);self.assertIn('CLEANUP_FINALIZATION_UNKNOWN',e)
 def test_unassigned_root_does_not_explain_job_process_history(self):
  o=fake_job(states.SUSPENDED);base=o.query
  def q(k):
   v=base(k)
   if k==1:v['TotalProcesses']=1
   return v
  o.query=q;v,c,e=closed(o);self.assertIsNone(v);self.assertIn('CLEANUP_FINALIZATION_UNKNOWN',e)

def bad_field(index,value):
 def test(self):
  b,rows=correct_boundary();args=[EXE,CMD,CWD];args[index]=value
  with self.assertRaises(boundary.AuditRefused):b.audit('_winapi.CreateProcess',tuple(args))
  self.assertIs(rows[0]['fields'][('application_name','command_line','current_directory')[index]]['exact_match'],False);self.assertEqual(b.creations,0);self.assertEqual(b.state,'TERMINAL');self.assertTrue(boundary.check_receipt(rows[0],True))
 return test
for i,name in enumerate(('application','command','cwd')):
 for label,value in [('different','UNAPPROVED_SYNTHETIC_VALUE'),('none',None),('boolean',True),('bytes',b'UNAPPROVED')]:setattr(Tests,'test_audit_'+name+'_'+label+'_rejected',bad_field(i,value))
def bad_arity(n):
 def test(self):
  b,rows=correct_boundary()
  with self.assertRaises(boundary.AuditRefused):b.audit('_winapi.CreateProcess',tuple('x' for _ in range(n)))
  self.assertEqual(rows[0]['argument_count'],n);self.assertEqual(rows[0]['fields'],{});self.assertEqual(b.creations,0)
 return test
for n in (0,1,2,4):setattr(Tests,'test_audit_wrong_arity_'+str(n),bad_arity(n))
def query_failure(kind):
 def test(self):
  o=fake_job();base=o.query
  def q(k):
   if k==kind:raise model.Unknown('SYNTHETIC_QUERY_FAILED')
   return base(k)
  o.query=q;v,c,e=closed(o);self.assertIsNone(v);self.assertIn('CLEANUP_UNKNOWN',e)
 return test
for kind in (1,3):setattr(Tests,'test_owned_query_class_'+str(kind)+'_failure',query_failure(kind))
def bad_account(field,value):
 def test(self):
  o=fake_job();base=o.query
  def q(k):
   v=base(k)
   if k==1:v[field]=value
   return v
  o.query=q;v,c,e=closed(o);self.assertIsNone(v);self.assertIn('CLEANUP_UNKNOWN',e)
 return test
for field,value in [('ActiveProcesses',1),('ActiveProcesses',True),('TotalProcesses',1),('TotalTerminatedProcesses',1)]:setattr(Tests,'test_empty_'+field+'_'+str(value)+'_unknown',bad_account(field,value))
def bad_receipt(field,value):
 def test(self):
  r=copy.deepcopy(rejection().receipt);r[field]=value
  with self.assertRaises((runner_proof.Refused,ValueError)):boundary.check_receipt(r,True)
 return test
for key,value in [('version','wrong'),('decision','ALLOW'),('argument_count',True),('fields',{}),('raw_arguments_exported',True),('tool_hashes',{})]:setattr(Tests,'test_receipt_'+key+'_tamper_rejected',bad_receipt(key,value))
