import ast,copy,hashlib,json,sys,unittest
from pathlib import Path
from unittest.mock import patch
import state
S=Path(__file__).resolve().parent
class Fake:
 def __init__(self,active=1,mode='normal'):
  self.mode=mode;self.n=0;self.released=False;self.events=[];self.first_active=active;self.post=0
 def wait_owned(self,seconds):self.events.append('wait');return 258 if self.mode in ('hang','descendant_hang') else 0
 def terminate_owned(self,code):self.events.append('terminate')
 def confirm_handles(self,end):self.events.append('confirm')
 def snapshot(self):
  self.n+=1;exit={'normal':0,'crash':7,'hang':124,'descendant_hang':124}[self.mode]
  return {'root_exit_code':exit,'active':self.first_active if self.n==1 else 0,'job_pids':[11],
   'handles':[{'kind':'root','handle':100,'wait':0,'exit_code':exit}],'utc_ns':1,'monotonic_ns':1}
 def release_confirmed(self,expected):
  self.events.append('release');self.released=True
  return [{'handle':r['handle'],'wait':r['wait'],'exit_code':r['exit_code'],'closed':True} for r in expected]
 def active(self):return self.post
 def pids(self):return []
class Tests(unittest.TestCase):
 def run_case(self,p=None,mode='normal'):
  p=p or Fake(mode=mode);events=[];r=state.qualify(p,mode,10 if mode in ('normal','crash') else 2,{11},lambda e,v:events.append((e,copy.deepcopy(v))));return r,events
 def reject(self,p):
  events=[]
  with self.assertRaises(Exception):state.qualify(p,'normal',10,{11},lambda e,v:events.append((e,copy.deepcopy(v))))
  self.assertEqual(events[-1][1]['status'],'UNKNOWN');return events
 def test_retained_nonzero_red_and_final_zero_green(self):
  r,e=self.run_case();self.assertEqual(r['legacy_zero_gate'],'REJECT_OBSERVED');self.assertEqual(r['final_active'],0);self.assertTrue(r['temporal_change_while_handles_retained']);self.assertEqual(r['release_causality'],'NOT_ISOLATED_FROM_ELAPSED_TIME')
 def test_no_fabricated_red_if_already_zero(self):
  r,e=self.run_case(Fake(0));self.assertEqual(r['legacy_zero_gate'],'PASS_OBSERVED');self.assertIn('NOT_REPRODUCED',r['root_cause_claim'])
 def test_crash_expected_nonzero_exit(self):self.assertEqual(self.run_case(mode='crash')[0]['root_exit_code'],7)
 def test_timeout_calls_terminate_and_confirm_before_release(self):
  p=Fake(mode='hang');r,e=self.run_case(p,'hang');self.assertEqual(p.events,['wait','terminate','confirm','release']);self.assertTrue(r['timeout']);self.assertEqual(r['legacy_zero_gate'],'NOT_EQUIVALENT_TIMEOUT_PATH')
 def test_unconfirmed_wait_rejected(self):
  p=Fake();p.wait_owned=lambda s:0xffffffff;self.reject(p)
 def test_cancellation_failure_not_pass(self):
  p=Fake(mode='hang');p.terminate_owned=lambda c:(_ for _ in ()).throw(RuntimeError('CANCELLATION_FAILED'))
  with self.assertRaisesRegex(RuntimeError,'CANCELLATION_FAILED'):self.run_case(p,'hang')
 def test_live_handle_rejected_not_released(self):
  p=Fake();old=p.snapshot
  def snap():v=old();v['handles'][0]['wait']=258;return v
  p.snapshot=snap;self.reject(p);self.assertFalse(p.released)
 def test_unknown_job_member_rejected(self):
  p=Fake();old=p.snapshot
  def snap():v=old();v['job_pids']=[999];return v
  p.snapshot=snap;self.reject(p);self.assertFalse(p.released)
 def test_wrong_root_exit_rejected(self):
  p=Fake();old=p.snapshot
  def snap():v=old();v['root_exit_code']=7;return v
  p.snapshot=snap;self.reject(p)
 def test_second_root_exit_contradiction(self):self.second_mutate('root')
 def test_second_handle_exit_contradiction(self):self.second_mutate('exit')
 def test_second_handle_identity_contradiction(self):self.second_mutate('identity')
 def second_mutate(self,kind):
  p=Fake();old=p.snapshot
  def snap():
   v=old()
   if p.n==2:
    if kind=='root':v['root_exit_code']=7
    elif kind=='exit':v['handles'][0]['exit_code']=7
    else:v['handles'][0]['handle']=999
   return v
  p.snapshot=snap;self.reject(p)
 def test_nonzero_final_gate_rejects(self):
  p=Fake();calls=[0]
  def active():calls[0]+=1;return 0 if calls[0]==1 else 1
  p.active=active;self.reject(p)
 def test_zero_observed_after_original_bound_rejects(self):
  ticks=iter([0,0,0,11,11,11,11])
  with patch.object(state.time,'monotonic',side_effect=lambda:next(ticks,11)):self.reject(Fake())
 def test_no_evidence_io_between_wait_and_first_snapshot(self):
  p=Fake();sequence=[];old=p.snapshot
  p.wait_owned=lambda s:sequence.append('WAIT') or 0
  p.snapshot=lambda:sequence.append('SNAPSHOT') or old()
  state.qualify(p,'normal',10,{11},lambda e,v:sequence.append('WRITE'))
  self.assertEqual(sequence[:2],['WAIT','SNAPSHOT'])
 def test_new_job_command_refuses_native_sources_shell(self):
  import job
  for cmd in (['pwsh','-File','native_worker.ps1'],['cmd','/c','anything']):
   with self.assertRaises(job.ContainmentError):job.checked_command(cmd,{})
 def test_unsigned_helper_constructor_does_not_dispatch(self):
  import job
  with self.assertRaises(Exception):job.WindowsJob('SYNTHETIC_NOT_AUTHORIZATION',{})
 def test_kernel_abi_structs_unchanged(self):
  def parts(path):
   tree=ast.parse(path.read_bytes());out={}
   for n in ast.walk(tree):
    if isinstance(n,ast.ClassDef) and n.name in ('BASIC','EXT','IO','ACCT'):out[n.name]=ast.dump(n,include_attributes=False)
   return out
  self.assertEqual(parts(S/'job.py'),parts(S.parent/'pf_personal_collector/windows_job.py'))
 def test_no_source_api_execution_entry_in_closed_candidate(self):
  for name in ('controller.py','job.py','state.py','fault_worker.py','fault_leaf.py'):
   text=(S/name).read_text();self.assertNotIn('Get-CimInstance',text);self.assertNotIn('OpenBaseKey',text);self.assertNotIn('native_worker.ps1',text);self.assertNotIn('shell=True',text)
 def test_original_gate_and_deadline_not_removed(self):
  text=(S/'state.py').read_text();self.assertIn("final['active']==0",text);self.assertIn('time.monotonic()<=end',text);self.assertIn('job.confirm_handles(end)',text)

 def test_active_boolean_not_zero_accounting(self):self.first_mutate(lambda v:v.update(active=False))
 def test_negative_active_rejected(self):self.first_mutate(lambda v:v.update(active=-1))
 def test_active_limit_rejected(self):self.first_mutate(lambda v:v.update(active=5))
 def test_duplicate_pid_rejected(self):self.first_mutate(lambda v:v.update(job_pids=[11,11]))
 def test_boolean_pid_rejected(self):self.first_mutate(lambda v:v.update(job_pids=[True]))
 def test_missing_handle_rejected(self):self.first_mutate(lambda v:v.update(handles=[]))
 def test_boolean_exit_rejected(self):self.first_mutate(lambda v:v.update(root_exit_code=False))
 def test_missing_timestamp_rejected(self):self.first_mutate(lambda v:v.update(utc_ns=None))
 def first_mutate(self,mutate):
  p=Fake();old=p.snapshot
  def snap():v=old();mutate(v);return v
  p.snapshot=snap;self.reject(p);self.assertFalse(p.released)

 def claims(self):
  import runner_proof as p
  c={'iss':p.ISS,'aud':p.AUD,'repository':p.REPO,'repository_id':'1370145728','repository_owner_id':'325481386','ref':p.REF,'event_name':'push','runner_environment':'github-hosted','workflow_ref':p.WORKFLOW,'sha':'a'*40,'workflow_sha':'a'*40,'run_id':'123','run_attempt':'1','sub':f'repo:{p.REPO}:ref:{p.REF}','iat':1000,'nbf':1000,'exp':1600}
  return p,c
 def bad_claim(self,key,value):
  p,c=self.claims();c[key]=value
  with self.assertRaises(p.Refused):p.check_claims(c,1200,'a'*40,'123','1')
 def test_c01_claims_exact_positive_synthetic_only(self):
  p,c=self.claims();self.assertEqual(p.check_claims(c,1200,'a'*40,'123','1')['aud'],p.AUD)
 def test_old_audience_refused(self):self.bad_claim('aud','rate-pf-personal-002-engineering')
 def test_old_branch_refused(self):self.bad_claim('ref','refs/heads/codex/pf-personal-readonly-collector-v1')
 def test_old_workflow_refused(self):self.bad_claim('workflow_ref','pili5420/RATE-Data-Engine/.github/workflows/rate_pf_personal_collector.yml@refs/heads/codex/pf-personal-readonly-collector-v1')
 def test_claim_head_mismatch_refused(self):self.bad_claim('sha','b'*40)
 def test_claim_attempt2_refused(self):self.bad_claim('run_attempt','2')
 def test_claim_expired_refused(self):self.bad_claim('exp',1200)
 def test_claim_boolean_clock_refused(self):self.bad_claim('iat',True)
 def test_four_fixed_commands_only(self):
  import job
  for mode in ('normal','crash','hang','descendant_hang'):
   self.assertEqual(job.checked_command([sys.executable,'-I','-B','-S',str(S/'fault_worker.py'),mode],{}),'fault_'+mode)
 def test_command_arguments_extra_refused(self):
  import job
  with self.assertRaises(job.ContainmentError):job.checked_command([sys.executable,'-I','-B','-S',str(S/'fault_worker.py'),'normal','extra'],{})
 def test_alternate_executable_refused(self):
  import job
  with self.assertRaises(job.ContainmentError):job.checked_command(['OTHER_PYTHON','-I','-B','-S',str(S/'fault_worker.py'),'normal'],{})
 def test_alternate_worker_refused(self):
  import job
  with self.assertRaises(job.ContainmentError):job.checked_command([sys.executable,'-I','-B','-S',str(S/'fault_leaf.py'),'normal'],{})
 def close_provider(self,fail):
  import job,types
  p=job.WindowsJob.__new__(job.WindowsJob);p.job=50;p.handles=[100,200];p.logs=[]
  p.k=types.SimpleNamespace(CloseHandle=lambda h:h not in fail);p.c=types.SimpleNamespace(get_last_error=lambda:6)
  return p
 def test_failed_job_close_preserves_unknown_and_reference(self):
  p=self.close_provider({50});r=p.close();self.assertEqual(r['status'],'UNKNOWN');self.assertEqual(p.job,50);self.assertEqual(r['resources'][0]['win32_error'],6)
 def test_failed_process_close_preserves_unknown_and_reference(self):
  p=self.close_provider({100});r=p.close();self.assertEqual(r['status'],'UNKNOWN');self.assertEqual(p.handles,[100]);self.assertIsNone(p.job)
 def test_successful_close_receipts_are_actual(self):
  p=self.close_provider(set());r=p.close();self.assertEqual(r['status'],'CLOSED');self.assertFalse(p.handles);self.assertIsNone(p.job)
 def test_release_changed_exit_rejected_before_close(self):
  import types,job
  p=self.close_provider(set());p.handles=[100];closed=[]
  def exit_code(h,v):v.value=7;return True
  p.k=types.SimpleNamespace(WaitForSingleObject=lambda h,t:0,GetExitCodeProcess=exit_code,CloseHandle=lambda h:closed.append(h) or True)
  p.w=types.SimpleNamespace(DWORD=lambda:types.SimpleNamespace(value=0));p.c=types.SimpleNamespace(byref=lambda v:v,get_last_error=lambda:0)
  with self.assertRaisesRegex(job.ContainmentError,'RELEASE_EXIT_CHANGED'):p.release_confirmed([{'handle':100,'exit_code':0}])
  self.assertEqual(closed,[]);self.assertEqual(p.handles,[100])
