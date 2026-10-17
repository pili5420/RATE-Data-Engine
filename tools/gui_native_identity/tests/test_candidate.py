import ast,copy,hashlib,json,os,struct,subprocess,sys,threading,unittest
from pathlib import Path
from uuid import uuid4
from ..adapter import OfflineIdentityCandidate,NativeCallGuard,validate_review_ack
from ..provider import ScriptedWindowsProvider
from ..journal import SyntheticWorkspace
from ..protocol import Denied,canonical,decode,digest,code_identity,schema_check
from ..contracts import API_FIELDS,SCOPE
from .. import abi
from . import fixtures as f
ROOT=None
class CandidateTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.workspace=ROOT;w=SyntheticWorkspace(ROOT);m,p,v=f.bundle(w);r=OfflineIdentityCandidate().run(m,p,v,w)
  if r['status']!='RESOLVED_OFFLINE_IDENTITY_ONLY':raise AssertionError(r)
  cls.good_trace=copy.deepcopy(p.calls);cls.api_index={api:next(i+1 for i,row in enumerate(p.calls) if row['request']['api']==api) for api in API_FIELDS}
 def new(self,count=1):
  if not hasattr(self,'case_root'):
   self.case_root=ROOT.parent/(ROOT.name+'-case-'+uuid4().hex);self.case_root.mkdir()
  w=SyntheticWorkspace(self.case_root);return w,*f.bundle(w,count)
 def run_model(self,edit=None,count=1):
  w,m,p,v=self.new(count)
  if edit:replacement=edit(w,m,p,v);p=replacement if replacement is not None else p
  r=OfflineIdentityCandidate().run(m,p,v,w);return r,w,m,p,v
 def denied(self,r,reason=None):
  self.assertIn(r['status'],{'BLOCKED','INDETERMINATE'});self.assertFalse(r['native_execution_authorized']);self.assertFalse(r['diagnostic_authorized']);self.assertIn('BLOCKED',r['gate2_final_status']);self.assertTrue(r['no_auto_next'])
  self.assertNotIn('identity',r)
  if reason:self.assertIn(reason,r['reason'])
 def test_positive_exact_identity(self):
  r,w,m,p,v=self.run_model();self.assertEqual(r['status'],'RESOLVED_OFFLINE_IDENTITY_ONLY');self.assertEqual(r['identity'],f.identity());self.assertFalse(r['atomic_snapshot']);self.assertFalse(r['diagnostic_authorized']);self.assertFalse(r['native_execution_authorized']);self.assertTrue(r['independent_review_required']);self.assertEqual(w.audit_attempt(m['attempt_id'])['state'],r['status']);self.assertFalse(p.handles)
 def test_zero_candidate(self):self.denied(self.run_model(count=0)[0],'EXACTLY_ONE')
 def test_multiple_candidates(self):self.denied(self.run_model(count=2)[0],'EXACTLY_ONE')
 def test_known_class_exclusion_and_unique(self):
  def edit(w,m,p,v):
   world=copy.deepcopy(p.scenario);world['windows'][1]['class_name']='Other'
   for event in v['events']:
    if event['identity']['hwnd']==2:event['identity']['class_name']='Other'
   f.bind_witness(m,v);return f.replace_provider(m,world)
  r,*_=self.run_model(edit,2);self.assertEqual(r['identity'],f.identity())
 def test_nonmatching_image_never_file_read(self):
  def edit(w,m,p,v):
   world=copy.deepcopy(p.scenario);world['processes']['101']['path']=r'C:\Windows\System32\control.exe'
   for event in v['events']:event['identity']['executable_path']=r'C:\Windows\System32\control.exe'
   f.bind_witness(m,v);return f.replace_provider(m,world)
  r,w,m,p,v=self.run_model(edit);self.denied(r,'EXACTLY_ONE');self.assertFalse(any(x['request']['api']=='CreateFileW' for x in p.calls))
 def test_no_title_api_ever_requested(self):
  r,w,m,p,v=self.run_model();self.assertFalse(any('WindowText' in x['request']['api'] for x in p.calls));self.assertFalse(any(x['request']['api'] in {'ReadProcessMemory','WriteFile','SetWindowTextW'} for x in p.calls))
 def test_no_borrowed_handle_closed(self):
  r,w,m,p,v=self.run_model();closed={x['request']['args']['handle'] for x in p.calls if x['request']['api']=='CloseHandle'};borrowed={x['receipt']['result'] for x in p.calls if x['request']['api'] in {'GetThreadDesktop','GetProcessWindowStation'}};self.assertFalse(closed&borrowed)
 def test_attempt_replay_new_session(self):
  r,w,m,p,v=self.run_model();other=SyntheticWorkspace(w.root);fresh=ScriptedWindowsProvider(p.scenario);self.denied(OfflineIdentityCandidate().run(m,fresh,v,other),'REPLAY');self.assertEqual(fresh.calls,[])
 def test_nonce_replay_new_attempt(self):
  r,w,m,p,v=self.run_model();other=SyntheticWorkspace(w.root);a,provider,witness=f.bundle(other,nonce=m['nonce']);self.denied(OfflineIdentityCandidate().run(a,provider,witness,other),'REPLAY');self.assertEqual(provider.calls,[])
 def test_same_session_cannot_claim_second_model(self):
  w,m,p,v=self.new();w.claim(m);a,_,_=f.bundle(w)
  with self.assertRaisesRegex(Denied,'SESSION_ALREADY_CONSUMED'):w.claim(a)
 def test_candidate_instance_cannot_be_reused(self):
  w,m,p,v=self.new();candidate=OfflineIdentityCandidate();self.assertEqual(candidate.run(m,p,v,w)['status'],'RESOLVED_OFFLINE_IDENTITY_ONLY');ws,other,provider,proof=self.new();self.denied(candidate.run(other,provider,proof,ws),'CANDIDATE_SESSION_ALREADY_CONSUMED');self.assertEqual(provider.calls,[])
 def test_error_attempt_cannot_resume(self):
  def edit(w,m,p,v):world=copy.deepcopy(p.scenario);world['faults']=[{'call':1,'kind':'unknown'}];return f.replace_provider(m,world)
  r,w,m,p,v=self.run_model(edit);self.denied(r);self.assertEqual(w.audit_attempt(m['attempt_id'])['state'],'INDETERMINATE');other=SyntheticWorkspace(w.root);fresh=ScriptedWindowsProvider(p.scenario);self.denied(OfflineIdentityCandidate().run(m,fresh,v,other),'REPLAY');self.assertEqual(fresh.calls,[])
 def test_review_ack_binds_evidence_no_promotion(self):
  r,w,m,p,v=self.run_model();ack=f.ack(r,m);out=validate_review_ack(ack,r,m);self.assertFalse(out['diagnostic_authorized']);self.assertFalse(out['native_execution_authorized']);self.assertIn('BLOCKED',out['gate2_final_status'])
 def test_ack_is_not_identity_model(self):
  r,w,m,p,v=self.run_model();ack=f.ack(r,m);other=SyntheticWorkspace(ROOT);self.denied(OfflineIdentityCandidate().run(ack,ScriptedWindowsProvider(p.scenario),v,other));self.assertEqual(other.audit_attempt('SYNTHETIC-UNUSED00000000')['state'],'NOT_ATTEMPTED')
 def test_ack_mismatch_rejects(self):
  r,w,m,p,v=self.run_model();ack=f.ack(r,m);ack['identity_sha256']='0'*64
  with self.assertRaisesRegex(Denied,'REVIEW_ACK'):validate_review_ack(ack,r,m)
 def test_ack_cannot_authorize_diagnostic(self):
  r,w,m,p,v=self.run_model();ack=f.ack(r,m);ack['diagnostic_authorized']=True
  with self.assertRaisesRegex(Denied,'ACK_IS_NOT_EXECUTION'):validate_review_ack(ack,r,m)
 def test_untrusted_provider_subclass_rejected(self):
  class Bad(ScriptedWindowsProvider):pass
  w,m,p,v=self.new();bad=Bad(p.scenario);self.denied(OfflineIdentityCandidate().run(m,bad,v,w),'OFFLINE_PROVIDER');self.assertEqual(bad.calls,[])
 def test_callback_injection_rejected(self):
  world=f.scenario();world['faults']=[lambda:None]
  with self.assertRaises((Denied,TypeError)):ScriptedWindowsProvider(world)
 def test_duplicate_fault_call_rejected(self):
  world=f.scenario();world['faults']=[{'call':1,'kind':'error'}]*2
  with self.assertRaisesRegex(Denied,'DUPLICATE_FAULT'):ScriptedWindowsProvider(world)
 def test_provider_unplanned_world_mutation_rejected(self):
  def edit(w,m,p,v):p.world['host']='OTHER'
  r,w,m,p,v=self.run_model(edit);self.denied(r,'MUTATED');self.assertEqual(p.calls,[])
 def test_physical_root_cannot_target_halt_or_campaign(self):
  for p in [Path(r'D:\R1-20261015-01'),Path(r'D:\Codex\RATE-D-Pagefile-Reentry2-20261017-0009')]:
   with self.assertRaisesRegex(Denied,'SYNTHETIC_PHYSICAL_WORKSPACE_ONLY'):SyntheticWorkspace(p)
 def test_relative_and_traversal_root_rejected(self):
  for p in [Path('relative'),ROOT/'..'/'escape']:
   with self.assertRaises(Denied):SyntheticWorkspace(p)
 def test_actual_hardlink_rejected(self):
  p=ROOT/('hardlink-source-'+uuid4().hex);q=ROOT/('hardlink-target-'+uuid4().hex);p.write_bytes(b'SYNTHETIC');q.hardlink_to(p)
  with self.assertRaisesRegex(Denied,'HARDLINK'):SyntheticWorkspace(ROOT)._physical(q)
 def test_result_tamper_detected(self):
  r,w,m,p,v=self.run_model();file=w.output/'RESULT.json';file.write_bytes(b'{}')
  with self.assertRaisesRegex(Denied,'RESULT_FILE_TAMPER'):w.audit_attempt(m['attempt_id'])
 def test_terminal_binding_tamper_detected(self):
  r,w,m,p,v=self.run_model();path=w.journal/('terminal-'+digest(m['attempt_id'])+'.json');x=decode(path.read_bytes());x['intent_sha256']='0'*64;path.write_bytes(canonical(x))
  with self.assertRaisesRegex(Denied,'TERMINAL_INTENT'):w.audit_attempt(m['attempt_id'])
 def test_nonce_reservation_tamper_detected(self):
  r,w,m,p,v=self.run_model();path=w.journal/('nonce-'+digest(m['nonce'])+'.json');path.write_bytes(canonical({'attempt_sha256':'0'*64,'model_sha256':digest(m)}))
  with self.assertRaisesRegex(Denied,'NONCE_RESERVATION'):w.audit_attempt(m['attempt_id'])
 def test_api_guard_unregistered_pid_rejected(self):
  w,m,p,v=self.new();w.claim(m);g=NativeCallGuard(m,p,w)
  with self.assertRaisesRegex(Denied,'EXACT_PROCESS_SUBJECT'):g.call('OpenProcess',{'pid':999,'desired_access':4096,'inherit':False},{'role':'observer'})
  self.assertEqual(p.calls,[])
 def test_api_guard_unregistered_window_rejected(self):
  w,m,p,v=self.new();w.claim(m);g=NativeCallGuard(m,p,w)
  with self.assertRaisesRegex(Denied,'UNREGISTERED'):g.call('IsWindow',{'hwnd':1},{'role':'window','hwnd':1})
 def test_api_guard_no_intent_rejected(self):
  w,m,p,v=self.new()
  with self.assertRaisesRegex(Denied,'DURABLE_INTENT'):NativeCallGuard(m,p,w)
 def test_api_guard_arbitrary_handle_rejected(self):
  w,m,p,v=self.new();w.claim(m);g=NativeCallGuard(m,p,w)
  with self.assertRaisesRegex(Denied,'UNKNOWN_OR_BORROWED'):g.call('CloseHandle',{'handle':9999},{'role':'observer'})
 def test_api_guard_failure_poisoned(self):
  w,m,p,v=self.new();w.claim(m);g=NativeCallGuard(m,p,w)
  with self.assertRaisesRegex(Denied,'UNAUTHORIZED_API'):g.call('GetWindowTextW',{}, {'role':'observer'})
  with self.assertRaisesRegex(Denied,'NO_RETRY'):g.call('GetCurrentProcessId',{}, {'role':'observer'})
 def test_api_guard_model_mutation(self):
  w,m,p,v=self.new();w.claim(m);g=NativeCallGuard(m,p,w);m['scope']['max_windows']=9
  with self.assertRaisesRegex(Denied,'MODEL_OR_CODE_MUTATED'):g.call('GetCurrentProcessId',{}, {'role':'observer'})
 def test_file_path_aliases_rejected(self):
  from ..protocol import windows_path
  for path in [r'\\server\file',r'\\?\GLOBALROOT\a',r'C:\Windows\..\a',r'C:\Windows\a:stream',r'C:\Windows\a.','C:/Windows/a']:
   with self.assertRaises(Denied):windows_path(path,extended=True)
 def test_abi_file_id_and_process_time(self):self.assertEqual(abi.file_id(struct.pack('<Q',1).hex()+'11'*16),{'volume_serial':'0000000000000001','file_id':'11'*16});self.assertEqual(abi.process_creation(f.times(1)) if hasattr(f,'times') else abi.process_creation(struct.pack('<8I',1,0,0,0,0,0,0,0).hex()),1)
 def test_abi_utf16_surrogate_pair(self):self.assertEqual(abi.utf16(('A😀\0').encode('utf-16-le').hex()),'A😀')
 def test_abi_invalid_surrogate_rejected(self):
  with self.assertRaises(UnicodeDecodeError):abi.utf16('00d80000')
 def test_abi_truncated_fileinfo_rejected(self):
  for decoder in [abi.file_id,abi.file_standard,abi.file_basic,abi.process_creation,abi.owner_pair,abi.sid]:
   with self.assertRaises((Denied,ValueError)):decoder('00')
 def test_scope_calls_bounded_before_native(self):
  def edit(w,m,p,v):m['scope']['max_calls']=1;m['scope_sha256']=digest(m['scope'])
  r,w,m,p,v=self.run_model(edit);self.denied(r,'MAX_NATIVE_CALLS');self.assertEqual(len(p.calls),1)
 def test_pre_call_expiry_zero_calls(self):
  def edit(w,m,p,v):m['expires_tick_ns']=9000
  r,w,m,p,v=self.run_model(edit);self.denied(r,'PRECALL_DEADLINE');self.assertEqual(p.calls,[])
 def test_native_sources_never_claimed_lossless(self):
  def edit(w,m,p,v):v['artifact_kind']='WIN_EVENT_HOOK_SELF_DECLARED_LOSSLESS';f.bind_witness(m,v)
  r,w,m,p,v=self.run_model(edit);self.denied(r,'PROVENANCE_UNKNOWN');self.assertEqual(p.calls,[])
 def test_concurrent_same_attempt_single_winner(self):
  w,m,p,v=self.new();barrier=threading.Barrier(2);outputs=[]
  def worker():
   ws=SyntheticWorkspace(w.root);provider=ScriptedWindowsProvider(p.scenario);barrier.wait();outputs.append((OfflineIdentityCandidate().run(copy.deepcopy(m),provider,copy.deepcopy(v),ws),len(provider.calls)))
  threads=[threading.Thread(target=worker) for _ in range(2)]
  for t in threads:t.start()
  for t in threads:t.join(20);self.assertFalse(t.is_alive())
  self.assertEqual(sum(r['status']=='RESOLVED_OFFLINE_IDENTITY_ONLY' for r,c in outputs),1);self.assertEqual(sum(c==0 for r,c in outputs),1)
 def test_runtime_has_no_native_binder_or_cli(self):
  from ..contracts import RUNTIME_FILES
  for name in RUNTIME_FILES:
   tree=ast.parse((Path(__file__).resolve().parents[1]/name).read_bytes())
   for node in ast.walk(tree):
    if isinstance(node,ast.Call):self.assertFalse(any(x in ast.unparse(node.func) for x in ['WinDLL','CDLL','windll','LoadLibrary','GetProcAddress']))
    if isinstance(node,ast.If):self.assertNotIn('__name__',ast.unparse(node.test))
 def test_windows_crash_child_exact_serialized_command(self):
  from ..run_offline_tests import allowed_crash_child
  probe=str(Path(__file__).with_name('fault_probe.py'));cmd=[sys.executable,'-I','-B','-S',probe,'--root',str(ROOT),'--mode','after_attempt','--attempt','SYNTHETIC-12345678','--nonce','SYNTHETIC-12345678']
  self.assertTrue(allowed_crash_child(None,subprocess.list2cmdline(cmd),sys.executable,probe,ROOT));self.assertTrue(allowed_crash_child(sys.executable,cmd,sys.executable,probe,ROOT))
  for bad in [cmd+['--live'],['cmd.exe','/c','ver'],cmd[:-1]+['SYNTHETIC-12345678 & whoami'],cmd[:5]+['--root',str(ROOT.parent)]+cmd[7:]]:self.assertFalse(allowed_crash_child(None,subprocess.list2cmdline(bad),sys.executable,probe,ROOT))
  self.assertFalse(allowed_crash_child('cmd.exe',cmd,sys.executable,probe,ROOT))
 def test_workspace_replaced_at_real_filesystem(self):
  path=ROOT.parent/(ROOT.name+'-replacement-'+uuid4().hex);path.mkdir();w=SyntheticWorkspace(path);preserved=path.with_name(path.name+'-preserved');path.rename(preserved);path.mkdir()
  with self.assertRaisesRegex(Denied,'WORKSPACE_REPLACED'):w.verify()
 def test_witness_external_final_head_mismatch(self):
  def edit(w,m,p,v):m['witness_final_head']='f'*64
  self.denied(self.run_model(edit)[0])
 def test_witness_external_pre_head_mismatch(self):
  def edit(w,m,p,v):m['witness_pre_head']='f'*64
  self.denied(self.run_model(edit)[0])
 def test_nonselected_witness_duplicate_create_blocks_whole_stream(self):
  def edit(w,m,p,v):
   world=copy.deepcopy(p.scenario);world['windows'][1]['class_name']='Other';v['events'][-1]['kind']='CREATE';f.bind_witness(m,v);return f.replace_provider(m,world)
  self.denied(self.run_model(edit,2)[0])
 def test_nonselected_witness_destroy_blocks_whole_stream(self):
  def edit(w,m,p,v):
   world=copy.deepcopy(p.scenario);world['windows'][1]['class_name']='Other';v['events'][-1]['kind']='DESTROY';f.bind_witness(m,v);return f.replace_provider(m,world)
  self.denied(self.run_model(edit,2)[0])
 def test_nonselected_witness_generation_conflict_blocks_whole_stream(self):
  def edit(w,m,p,v):
   world=copy.deepcopy(p.scenario);world['windows'][1]['class_name']='Other';v['events'][-1]['identity']['window_epoch']=999;f.bind_witness(m,v);return f.replace_provider(m,world)
  self.denied(self.run_model(edit,2)[0])
 def test_concurrent_nonce_new_attempt_single_winner(self):
  nonce='SYNTHETIC-'+uuid4().hex;barrier=threading.Barrier(2);outputs=[]
  def worker():
   w=SyntheticWorkspace(ROOT);m,p,v=f.bundle(w,nonce=nonce);barrier.wait();outputs.append((OfflineIdentityCandidate().run(m,p,v,w),len(p.calls)))
  threads=[threading.Thread(target=worker) for _ in range(2)]
  for t in threads:t.start()
  for t in threads:t.join(20);self.assertFalse(t.is_alive())
  self.assertEqual(sum(r['status']=='RESOLVED_OFFLINE_IDENTITY_ONLY' for r,c in outputs),1);self.assertEqual(sum(c==0 for r,c in outputs),1)

def api_error_test(api):
 def test(self):
  def edit(w,m,p,v):world=copy.deepcopy(p.scenario);world['faults']=[{'call':self.api_index[api],'kind':'error'}];return f.replace_provider(m,world)
  r,w,m,p,v=self.run_model(edit);self.denied(r);self.assertEqual(len(p.calls),self.api_index[api]);self.assertFalse(w.audit_attempt(m['attempt_id'])['resume_authorized'])
 return test
def api_field_test(api):
 def test(self):
  w,m,p,v=self.new();w.claim(m);g=NativeCallGuard(m,p,w)
  with self.assertRaisesRegex(Denied,'EXACT_API_FIELD_ACCESS'):g.call(api,{}, {'role':'observer'},fields=['title'])
  self.assertEqual(p.calls,[])
 return test
for api in API_FIELDS:
 setattr(CandidateTests,'test_fault_error_'+api,api_error_test(api));setattr(CandidateTests,'test_forbidden_fields_'+api,api_field_test(api))

def rights_negative(api):
 def test(self):
  w,m,p,v=self.new();w.claim(m);g=NativeCallGuard(m,p,w)
  with self.assertRaisesRegex(Denied,'EXACT_API_FIELD_ACCESS'):g.call(api,{}, {'role':'observer'},access={'process':2035711,'token':8,'file':129})
  self.assertEqual(p.calls,[])
 return test
for api in API_FIELDS:setattr(CandidateTests,'test_forbidden_rights_'+api,rights_negative(api))

MODEL_NEGATIVES=[('formal_permit',lambda m:m.update(artifact_kind='EXECUTION_PERMIT')),('diagnostic_stage',lambda m:m.update(stage='BOUND_DIAGNOSTIC')),('tool_pin',lambda m:m.update(tool_sha256='0'*64)),('schema_pin',lambda m:m.update(schema_sha256='0'*64)),('provider_pin',lambda m:m.update(provider_sha256='0'*64)),('witness_pin',lambda m:m.update(witness_sha256='0'*64)),('scope_pin',lambda m:m.update(scope_sha256='0'*64)),('numeric_alias',lambda m:m['scope']['read_boundary']['access_rights'].update(token=8.0)),('bool_alias',lambda m:m['scope'].update(max_windows=True)),('float_timeout',lambda m:m['scope'].update(per_call_ms=1.0)),('extra_field',lambda m:m.update(unknown=True)),('bad_nonce',lambda m:m.update(nonce='LIVE-00000000')),('host_live',lambda m:m['scope']['policy'].update(host='Pili')),('outside_output',lambda m:m.update(evidence_root=r'D:\R1-20261015-01')),('zero_bound',lambda m:m['scope'].update(max_windows=0)),('unbounded',lambda m:m['scope'].update(max_windows=129))]
def model_negative(edit):
 def test(self):
  def change(w,m,p,v):edit(m);m['scope_sha256']=digest(m['scope']) if m.get('scope_sha256')!='0'*64 else m['scope_sha256']
  r,w,m,p,v=self.run_model(change);self.denied(r);self.assertEqual(p.calls,[])
 return test
for name,edit in MODEL_NEGATIVES:setattr(CandidateTests,'test_model_'+name,model_negative(edit))

WITNESS_NEGATIVES=[('duplicate_create',lambda v:v['events'][1].update(kind='CREATE')),('destroy',lambda v:v['events'][1].update(kind='DESTROY')),('gap',lambda v:v['events'][1].update(sequence=3)),('reorder',lambda v:v['events'].reverse()),('loss',lambda v:v.update(lost_events=1)),('unknown_coverage',lambda v:v.update(coverage='UNKNOWN')),('boot',lambda v:v.update(boot_id='SYNTHETIC-OTHER-BOOT')),('generation',lambda v:v['events'][1]['identity'].update(window_epoch=99)),('restart',lambda v:v['events'][1]['identity'].update(creation_filetime_100ns=f.CREATION+999)),('missing_interval',lambda v:v.update(events=v['events'][:1])),('coverage_end',lambda v:v.update(end_ns=10001)),('extra_timestamp',lambda v:v.update(hwnd_creation_timestamp=1)),('bool_loss',lambda v:v.update(lost_events=False)),('bool_sequence',lambda v:v['events'][0].update(sequence=True))]
def witness_negative(edit):
 def test(self):
  def change(w,m,p,v):edit(v);f.bind_witness(m,v)
  self.denied(self.run_model(change)[0])
 return test
for name,edit in WITNESS_NEGATIVES:setattr(CandidateTests,'test_witness_'+name,witness_negative(edit))

RAW_JSON_NEGATIVES=[b'{"x":1,"x":2}',b'{"x":NaN}',b'{ "x":1}',b'{"x":',b'\xff',b'{"x":Infinity}']
def json_negative(data):
 def test(self):
  with self.assertRaises((Denied,ValueError,TypeError)):decode(data)
 return test
for i,data in enumerate(RAW_JSON_NEGATIVES):setattr(CandidateTests,'test_canonical_json_negative_'+str(i),json_negative(data))

def crash_test(mode):
 def test(self):
  attempt='SYNTHETIC-'+uuid4().hex;nonce='SYNTHETIC-'+uuid4().hex;cmd=[sys.executable,'-I','-B','-S',str(Path(__file__).with_name('fault_probe.py')),'--root',str(ROOT),'--mode',mode,'--attempt',attempt,'--nonce',nonce]
  child=subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE);out,err=child.communicate(timeout=20)
  (ROOT/('child-'+attempt+'.stdout.log')).write_bytes(out);(ROOT/('child-'+attempt+'.stderr.log')).write_bytes(err)
  (ROOT/('child-'+attempt+'.process.json')).write_bytes(canonical({'command':cmd,'pid':child.pid,'exit_code':child.returncode,'native_provider':'NOT_PRESENT','mode':mode}))
  self.assertEqual(child.returncode,73,err.decode(errors='replace'));w=SyntheticWorkspace(ROOT);self.assertEqual(w.audit_attempt(attempt)['state'],'UNKNOWN_PARTIAL_OR_CRASH');m,p,v=f.bundle(w,attempt=attempt,nonce=nonce);self.denied(OfflineIdentityCandidate().run(m,p,v,w));self.assertEqual(p.calls,[])
  fresh=SyntheticWorkspace(ROOT);m,p,v=f.bundle(fresh,nonce=nonce);self.denied(OfflineIdentityCandidate().run(m,p,v,fresh),'REPLAY');self.assertEqual(p.calls,[])
 return test
for mode in ['after_attempt','after_claim','after_result']:setattr(CandidateTests,'test_real_owned_child_crash_'+mode,crash_test(mode))
