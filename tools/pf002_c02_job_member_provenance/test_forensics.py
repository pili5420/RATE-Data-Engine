import ast,copy,hashlib,json,struct,sys,time,types,unittest
from pathlib import Path
import model,probe,job,runner_proof as proof
S=Path(__file__).resolve().parent;ENGINEERING_OUTPUT_ROOT=None
class Tests(unittest.TestCase):
 def packed_ids(self,ptr=8,assigned=1,listed=1,values=(12,0,0,0)):
  return struct.pack('<II'+('Q' if ptr==8 else 'I')*4,assigned,listed,*values)
 def test_ids_x64_raw_offset(self):self.assertEqual(model.ids(self.packed_ids(),16,8)['pids'],[12])
 def test_ids_x86_raw_offset(self):self.assertEqual(model.ids(self.packed_ids(4),12,4)['pids'],[12])
 def test_ids_incomplete_reject(self):
  with self.assertRaises(model.Unknown):model.ids(self.packed_ids(assigned=2),16,8)
 def test_ids_returnlength_truncated_reject(self):
  with self.assertRaises(model.Unknown):model.ids(self.packed_ids(),8,8)
 def test_ids_duplicate_reject(self):
  with self.assertRaises(model.Unknown):model.ids(self.packed_ids(assigned=2,listed=2,values=(12,12,0,0)),24,8)
 def test_ids_invalid_pid_no_dword_wrap(self):
  with self.assertRaises(model.Unknown):model.ids(self.packed_ids(values=(2**32+12,0,0,0)),16,8)
 def test_ids_boolean_pointer_alias_reject(self):
  with self.assertRaises(model.Unknown):model.ids(self.packed_ids(),16,True)
 def test_acct_active_offset40(self):self.assertEqual(model.acct(struct.pack('<4q4I',1,2,3,4,5,6,2,0),48)['ActiveProcesses'],2)
 def test_acct_invalid_active_reject(self):
  with self.assertRaises(model.Unknown):model.acct(struct.pack('<4q4I',1,2,3,4,5,6,5,0),48)
 def test_acct_wrong_returnlength_reject(self):
  with self.assertRaises(model.Unknown):model.acct(b'\0'*48,40)
 def test_pbi_x64(self):
  b=bytearray(48);b[32:40]=(12).to_bytes(8,'little');b[40:48]=(11).to_bytes(8,'little');self.assertEqual(model.pbi(bytes(b),48,8)['parent_pid'],11)
 def test_pbi_x86(self):
  b=bytearray(24);b[16:20]=(12).to_bytes(4,'little');b[20:24]=(11).to_bytes(4,'little');self.assertEqual(model.pbi(bytes(b),24,4)['pid'],12)
 def test_pbi_wrong_length_no_abi_fallback(self):
  with self.assertRaises(model.Unknown):model.pbi(b'\0'*48,24,8)
 def fixture(self,worker_is_root=True):
  root={'pid':11,'creation_time_100ns':100,'exit_time_100ns':300,'image_path':'C:\\test\\python.exe'}
  receipt={'pid':11 if worker_is_root else 12,'parent_pid':10 if worker_is_root else 11,'executable':root['image_path']}
  member={'pid':12,'creation_time_100ns':200,'image_path':root['image_path'],'disk_image':{'sha256':'a'*64},'pbi':{'pid':12,'parent_pid':11},'membership_before':True,'membership_after':True}
  observations=[{'phase':phase,'members':[copy.deepcopy(member)],'accounting':{'ActiveProcesses':1},'ids':{'pids':[12]}} for phase in ('AFTER_RESUME_BEFORE_WAIT','AFTER_ROOT_WAIT')]
  return root,receipt,observations
 def test_parent_link_synthetic_evidence_not_runtime_pass(self):
  d=model.classify(*self.fixture());self.assertEqual(d['root_cause'],'PROVEN');self.assertEqual(d['RS02'],'BLOCKED');self.assertFalse(d['trusted_member_allowlist_modified'])
 def test_worker_pid_differs_synthetic_link(self):self.assertEqual(model.classify(*self.fixture(False))['mechanisms'][0]['mechanism'],'CREATEPROCESS_ROOT_DIFFERS_FROM_CONTROLLED_WORKER_PID')
 def test_image_name_alone_never_proves_origin(self):
  a,b,c=self.fixture()
  for o in c:o['members'][0]['pbi']['parent_pid']=99;o['members'][0]['image_path']='C:\\Windows\\System32\\conhost.exe'
  self.assertEqual(model.classify(a,b,c)['root_cause'],'UNPROVEN')
 def test_creation_outside_retained_root_lifetime_unproven(self):
  a,b,c=self.fixture()
  for o in c:o['members'][0]['creation_time_100ns']=400
  self.assertEqual(model.classify(a,b,c)['root_cause'],'UNPROVEN')
 def test_creation_identity_change_reject(self):
  a,b,c=self.fixture();c[1]['members'][0]['creation_time_100ns']=201
  with self.assertRaisesRegex(model.Unknown,'IDENTITY_CHANGED'):model.classify(a,b,c)
 def test_image_hash_change_reject(self):
  a,b,c=self.fixture();c[1]['members'][0]['disk_image']['sha256']='b'*64
  with self.assertRaisesRegex(model.Unknown,'IDENTITY_CHANGED'):model.classify(a,b,c)
 def test_nonmember_cannot_promote(self):
  a,b,c=self.fixture();c[0]['members'][0]['membership_before']=False
  with self.assertRaises(model.Unknown):model.classify(a,b,c)
 def test_no_post_root_unknown_means_not_reproduced(self):
  a,b,c=self.fixture();c[1]['ids']['pids']=[];c[1]['accounting']['ActiveProcesses']=0
  self.assertEqual(model.classify(a,b,c)['root_cause'],'UNPROVEN')
 def test_normal_command_only(self):self.assertEqual(job.checked_command([sys.executable,'-I','-B','-S',str(S/'normal_worker.py')],{}),'normal')
 def test_crash_hang_descendant_commands_rejected(self):
  for mode in ('crash','hang','descendant_hang'):
   with self.assertRaises(job.ContainmentError):job.checked_command([sys.executable,'-I','-B','-S',str(S/'normal_worker.py'),mode],{})
 def test_old_worker_path_rejected(self):
  with self.assertRaises(job.ContainmentError):job.checked_command([sys.executable,'-I','-B','-S',str(S.parent/'pf002_containment_c01/fault_worker.py'),'normal'],{})
 def test_unsigned_constructor_before_dispatch(self):
  with self.assertRaises(Exception):probe.Probe('NOT_A_SIGNED_PROOF',{},lambda *a:None,time.monotonic()+1)
 def test_unapproved_job_class_before_native(self):
  p=probe.Probe.__new__(probe.Probe)
  with self.assertRaisesRegex(model.Unknown,'FIXED_JOB_QUERY_CLASS'):p.query(99)
 def test_phase_replay_before_native(self):
  p=probe.Probe.__new__(probe.Probe);p.phases={'AFTER_ROOT_WAIT'}
  with self.assertRaisesRegex(model.Unknown,'NO_RETRY'):p.observe('AFTER_ROOT_WAIT')
 def fake_probe(self,membership=True):
  p=probe.Probe.__new__(probe.Probe);p.pid=11;p.hp=111;p.job=50;p.phases=set();p.opened={};p.handles=[111];p.rejected_close_failures=[];p.rows=[];p.emit=lambda *a:p.rows.append(a);p.calls=[]
  p.query=lambda k:{'ActiveProcesses':1} if k==1 else {'pids':[12]}
  p.k=types.SimpleNamespace(OpenProcess=lambda rights,inherit,pid:p.calls.append((rights,inherit,pid)) or 222,CloseHandle=lambda h:True)
  p.record_api=lambda *a:None;p.membership=lambda h,pid:membership;p.identity=lambda h,pid:{'pid':pid,'handle':h};return p
 def test_open_only_ids_returned_by_owned_job(self):
  p=self.fake_probe();p.observe('AFTER_ROOT_WAIT');self.assertEqual(p.calls,[(0x101000,False,12)]);self.assertEqual(p.handles,[111,222])
 def test_same_member_second_phase_not_reopened(self):
  p=self.fake_probe();p.observe('AFTER_RESUME_BEFORE_WAIT');p.observe('AFTER_ROOT_WAIT');self.assertEqual(len(p.calls),1)
 def test_reused_or_outside_job_handle_closed_not_accepted(self):
  p=self.fake_probe(False)
  with self.assertRaisesRegex(model.Unknown,'NOT_OWN_JOB'):p.observe('AFTER_ROOT_WAIT')
  self.assertEqual(p.opened,{});self.assertEqual(p.handles,[111]);self.assertTrue(p.rows[-1][1]['closed'])
 def test_failed_rejected_handle_close_is_unknown_not_retried(self):
  p=self.fake_probe(False);p.k.CloseHandle=lambda h:False;p.c=types.SimpleNamespace(get_last_error=lambda:6)
  with self.assertRaises(model.Unknown):p.observe('AFTER_ROOT_WAIT')
  self.assertEqual(p.rejected_close_failures,[{'handle':222,'closed':False,'win32_error':6}])
 def test_network_image_path_rejected_before_file_access(self):
  with self.assertRaisesRegex(model.Unknown,'LOCAL_PHYSICAL'):probe.disk_image('\\\\server\\share\\image.exe',time.monotonic()+1)
 def test_disk_hash_own_fixture_stable_identity(self):
  p=ENGINEERING_OUTPUT_ROOT/'fake_image.bin';p.write_bytes(b'own synthetic image');rows=[]
  with self.assertRaisesRegex(model.Unknown,'LEGACY_COMPARATOR_NOT_RUNTIME_QUALIFIED'):probe.disk_image(str(p),time.monotonic()+1,lambda anchor:True)
  reader=probe.offline_reader(p,19);r=probe.validate_offline_fixture(str(p),time.monotonic()+5,lambda a:True,lambda *a:rows.append(a),reader)
  self.assertEqual(r['sha256'],hashlib.sha256(p.read_bytes()).hexdigest());self.assertFalse(r['loaded_image_attestation']);self.assertFalse(r['runtime_qualified']);self.assertEqual(r['native_calls'],0)
  self.assertEqual(r['canonical_identity']['creation_time_100ns'],100);self.assertEqual(r['canonical_identity']['change_time_100ns'],300);self.assertEqual(len(r['fixture_filesystem_observations']),5);self.assertEqual(len(reader.observations),5)
  self.assertEqual(len(r['file_id_128_le']),32);self.assertTrue(all(row['python_file_closed'] for event,row in rows if event=='FILE_CLOSE_RESULT'))
 def test_disk_hash_deadline_no_fallback(self):
  p=ENGINEERING_OUTPUT_ROOT/'late_image.bin';p.write_bytes(b'a')
  with self.assertRaisesRegex(model.Unknown,'DEADLINE'):probe.disk_image(str(p),time.monotonic()-1,lambda anchor:True)
 def test_source_no_global_scan_or_pid_kill(self):
  for name in ('probe.py','controller.py','normal_worker.py'):
   text=(S/name).read_text()
   for forbidden in ('CreateToolhelp32Snapshot','EnumProcesses','TerminateProcess','os.kill','Get-CimInstance','OpenBaseKey','AdjustTokenPrivileges','ReadProcessMemory','Popen('):self.assertNotIn(forbidden,text)
 def test_api_scope_unchanged_no_high_rights_retry(self):
  text=(S/'probe.py').read_text();self.assertIn('OpenProcess(0x101000,False,pid)',text);self.assertIn('status==0',text);self.assertNotIn('PROCESS_ALL_ACCESS',text)
 def test_normal_worker_source_has_no_fault_modes(self):
  text=(S/'normal_worker.py').read_text();self.assertNotIn('time.sleep',text);self.assertNotIn('subprocess',text);self.assertIn('sys.version_info[:3]==(3,12,10)',text)
 def claims(self):
  return {'iss':proof.ISS,'aud':proof.AUD,'repository':proof.REPO,'repository_id':'1370145728','repository_owner_id':'325481386','ref':proof.REF,'event_name':'push','runner_environment':'github-hosted','workflow_ref':proof.WORKFLOW,'sha':'a'*40,'workflow_sha':'a'*40,'run_id':'123','run_attempt':'1','sub':f'repo:{proof.REPO}:ref:{proof.REF}','iat':1000,'nbf':1000,'exp':1600}
 def test_new_claims_synthetic_only(self):self.assertEqual(proof.check_claims(self.claims(),1200,'a'*40,'123','1')['aud'],'rate-pf002-c02-job-member-forensics')
 def test_old_audience_rejected(self):
  c=self.claims();c['aud']='rate-pf002-c01-containment-only'
  with self.assertRaises(proof.Refused):proof.check_claims(c,1200,'a'*40,'123','1')
 def test_attempt2_replay_rejected(self):
  c=self.claims();c['run_attempt']='2'
  with self.assertRaises(proof.Refused):proof.check_claims(c,1200,'a'*40,'123','1')
 def test_old_workflow_rejected(self):
  c=self.claims();c['workflow_ref']='old'
  with self.assertRaises(proof.Refused):proof.check_claims(c,1200,'a'*40,'123','1')
 def test_real_base_api_module_does_not_shadow_evidence_helper(self):
  p=probe.Probe.__new__(probe.Probe);p.api=types.ModuleType('_winapi');p.job=50;rows=[];p.emit=lambda *a:rows.append(a)
  p.w=types.SimpleNamespace(BOOL=lambda:types.SimpleNamespace(value=False));p.c=types.SimpleNamespace(byref=lambda v:v,get_last_error=lambda:0)
  def inside(h,j,v):v.value=True;return 1
  p.k=types.SimpleNamespace(IsProcessInJob=inside)
  self.assertTrue(p.membership(111,11));self.assertEqual(rows[0][1]['api'],'IsProcessInJob')
 def test_nonfixed_drive_rejected_before_resolve_or_open(self):
  p=ENGINEERING_OUTPUT_ROOT/'does_not_exist.bin'
  with self.assertRaisesRegex(model.Unknown,'LEGACY_COMPARATOR_NOT_RUNTIME_QUALIFIED'):probe.disk_image(str(p),time.monotonic()+1,lambda anchor:False)
  reader=probe.offline_reader(p,1)
  with self.assertRaisesRegex(model.Unknown,'NOT_FIXED'):probe.validate_offline_fixture(str(p),time.monotonic()+1,lambda a:False,lambda *r:None,reader)
  self.assertEqual(reader.actual,[]);self.assertEqual(reader.observations,[])
 def test_missing_drive_proof_rejected(self):
  p=ENGINEERING_OUTPUT_ROOT/'also_missing.bin'
  with self.assertRaisesRegex(model.Unknown,'NOT_FIXED'):probe.disk_image(str(p),time.monotonic()+1)
 def test_boolean_member_creation_is_not_native_timestamp(self):
  a,b,c=self.fixture();c[0]['members'][0]['creation_time_100ns']=True
  with self.assertRaises(model.Unknown):model.classify(a,b,c)
 def test_fresh_parent_link_is_not_historical_assignment_proof(self):
  d=model.classify(*self.fixture());self.assertEqual(d['historical_C01_root_cause'],'UNPROVEN');self.assertIn('NOT_ASSIGNMENT',d['job_assignment_origin'])
