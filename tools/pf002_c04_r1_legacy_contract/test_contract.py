import ast,copy,hashlib,json,time,types,unittest
from pathlib import Path
import source_loader,offline_contract as offline
S=Path(__file__).resolve().parent;ENGINEERING_OUTPUT_ROOT=None
loader=source_loader.Loader(S);model=loader.load('model');canonical=loader.load('canonical_file');file=loader.load('file_evidence');proof=loader.load('runner_proof');job=loader.load('job');probe=loader.load('probe')
class Tests(unittest.TestCase):
 def legacy(self,folder,name):
  p=S.parent/folder/(name+'.py');m=types.ModuleType('legacy_offline');m.__file__=str(p);exec(compile(p.read_bytes(),str(p),'exec',dont_inherit=True),m.__dict__);return m
 def c02(self):return self.legacy('pf002_c02_job_member_provenance','probe')
 def c03(self):return self.legacy('pf002_c03_forensic_evidence','file_evidence')
 def image(self):
  p=ENGINEERING_OUTPUT_ROOT/(self._testMethodName+'.bin');p.write_bytes(b'abc');return p
 def stable(self,m):
  p=self.image();rows=[];reader=m.offline_reader(p,3);value=m.validate_offline_fixture(str(p),time.monotonic()+5,lambda a:True,lambda *r:rows.append(r),reader);return p,rows,reader,value
 def bad(self,field):
  m=self.c03();p=self.image();rows=[];reader=m.offline_reader(p,3,field)
  with self.assertRaisesRegex(model.Unknown,'CANONICAL_FILE_IDENTITY_CHANGED'):m.validate_offline_fixture(str(p),time.monotonic()+5,lambda a:True,lambda *r:rows.append(r),reader)
  q=next(v for k,v in rows if k=='CANONICAL_FILE_COMPARISON');self.assertIn(field,q['mismatch_fields']['OPENED_AFTER_HASH']);self.assertFalse(q['equal']);self.assertTrue(all(v['python_file_closed'] for k,v in rows if k=='FILE_CLOSE_RESULT'))
 def test_c02_successor_real_owned_hash(self):
  p,rows,reader,value=self.stable(self.c02());self.assertEqual(value['sha256'],hashlib.sha256(p.read_bytes()).hexdigest());self.assertEqual(len(reader.actual),5);self.assertEqual(len(reader.observations),5)
 def test_c03_successor_real_owned_hash(self):
  p,rows,reader,value=self.stable(self.c03());self.assertEqual(value['sha256'],hashlib.sha256(p.read_bytes()).hexdigest());self.assertEqual(len(reader.actual),5);self.assertEqual(len(reader.observations),5)
 def test_explicit_synthetic_realm_not_runtime(self):
  p,rows,reader,value=self.stable(self.c02());self.assertEqual(value['evidence_realm'],offline.REALM);self.assertFalse(value['runtime_qualified']);self.assertTrue(value['canonical_metadata_is_synthetic']);self.assertEqual(value['native_calls'],0);self.assertFalse(value['loaded_image_attestation'])
 def test_creation_change_distinct(self):
  p,rows,reader,v=self.stable(self.c03());self.assertEqual(v['canonical_identity']['creation_time_100ns'],100);self.assertEqual(v['canonical_identity']['change_time_100ns'],300);self.assertNotEqual(v['canonical_identity']['change_time_100ns'],v['canonical_identity']['last_write_time_100ns'])
 def test_synthetic_full_id_upper_bits_preserved(self):
  p,rows,reader,v=self.stable(self.c02());self.assertEqual(v['file_id_128_le'],'1600000000000000aabbccddeeff0011');self.assertGreater(v['file_id'],2**64)
 def test_volume_change_reject(self):self.bad('volume_serial_u64')
 def test_full_file_id_change_reject(self):self.bad('file_id_128_le')
 def test_size_change_reject(self):self.bad('file_size_bytes')
 def test_creation_change_reject(self):self.bad('creation_time_100ns')
 def test_metadata_change_reject(self):self.bad('change_time_100ns')
 def test_lastwrite_change_reject(self):self.bad('last_write_time_100ns')
 def test_attributes_change_reject(self):self.bad('file_attributes_u32')
 def test_linkcount_change_reject(self):self.bad('number_of_links')
 def test_content_hash_change_rejects_cross_process_identity(self):
  a={'pid':11,'creation_time_100ns':100,'image_path':'C:/approved/python.exe','disk_image':{'canonical_source_schema':canonical.SCHEMA,'canonical_identity':offline.synthetic_identity(3),'sha256':hashlib.sha256(b'abc').hexdigest()}};b=copy.deepcopy(a);b['disk_image']['sha256']=hashlib.sha256(b'xyz').hexdigest();self.assertFalse(canonical.same_across_process_observations(a,b))
 def test_c02_runtime_always_refuses(self):
  p=self.image()
  with self.assertRaisesRegex(model.Unknown,'LEGACY_COMPARATOR_NOT_RUNTIME_QUALIFIED'):self.c02().disk_image(str(p),time.monotonic()+1,lambda a:True)
 def test_c03_runtime_always_refuses(self):
  p=self.image()
  with self.assertRaisesRegex(model.Unknown,'LEGACY_COMPARATOR_NOT_RUNTIME_QUALIFIED'):self.c03().disk_image(str(p),time.monotonic()+1,lambda a:True,lambda *r:None)
 def test_c02_retired_runtime_cannot_open_file(self):
  m=self.c02();actual=Path.open;Path.open=lambda *a,**k:(_ for _ in ()).throw(AssertionError('NO_LEGACY_RUNTIME_IO'))
  try:
   with self.assertRaisesRegex(model.Unknown,'LEGACY_COMPARATOR_NOT_RUNTIME_QUALIFIED'):m.disk_image(str(ENGINEERING_OUTPUT_ROOT/'never_open'),time.monotonic()+1,lambda a:True)
  finally:Path.open=actual
 def test_c03_retired_runtime_cannot_open_file(self):
  m=self.c03();actual=Path.open;Path.open=lambda *a,**k:(_ for _ in ()).throw(AssertionError('NO_LEGACY_RUNTIME_IO'))
  try:
   with self.assertRaisesRegex(model.Unknown,'LEGACY_COMPARATOR_NOT_RUNTIME_QUALIFIED'):m.disk_image(str(ENGINEERING_OUTPUT_ROOT/'never_open'),time.monotonic()+1,lambda a:True,lambda *r:None)
  finally:Path.open=actual
 def test_missing_offline_provider_no_fallback(self):
  with self.assertRaises(Exception):self.c03().validate_offline_fixture(str(self.image()),time.monotonic()+1,lambda a:True,lambda *r:None,None)
 def test_provider_failure_once_no_fallback(self):
  m=self.c03();p=self.image();rows=[];r=m.offline_reader(p,3,fail_phase='OPENED_BEFORE')
  with self.assertRaises(OSError):m.validate_offline_fixture(str(p),time.monotonic()+1,lambda a:True,lambda *x:rows.append(x),r)
  self.assertEqual(len([v for k,v in rows if k=='OFFLINE_QUERY_RESULT']),1);self.assertEqual(r.observations,[]);self.assertNotIn('SECRET',json.dumps(rows))
 def test_same_source_fstat_instability_failclosed(self):
  m=self.c03();p=self.image();r=m.offline_reader(p,3);helper=m.offline_contract();actual=helper.os.fstat;count=[0]
  def altered(fd):
   s=actual(fd);count[0]+=1;v={k:getattr(s,k,None) for k in ('st_dev','st_ino','st_size','st_mtime_ns','st_ctime_ns','st_birthtime_ns','st_file_attributes','st_mode')}
   if count[0]==2:v['st_ctime_ns']+=1
   return types.SimpleNamespace(**v)
  helper.os.fstat=altered
  try:
   with self.assertRaisesRegex(model.Unknown,'FIXTURE_SAME_SOURCE_CHANGED'):m.validate_offline_fixture(str(p),time.monotonic()+1,lambda a:True,lambda *r:None,r)
  finally:helper.os.fstat=actual
 def test_canonical_core_manifest_pin(self):self.assertEqual(source_loader.C04_MANIFEST_SHA,offline.CORE_MANIFEST_SHA)
 def test_no_native_factory_in_offline_helper(self):
  text=(S/'offline_contract.py').read_text()
  for item in ('ctypes','WinDLL','NativeReader(','CreateProcess','subprocess','socket'):self.assertNotIn(item,text)
 def test_core_four_modules_pinned_not_copied(self):
  for n in ('canonical_file','file_evidence','probe','model'):self.assertFalse((S/(n+'.py')).exists());self.assertEqual(Path(loader.load(n).__file__).parent,S.parent/'pf002_c04_image_identity')
 def test_legacy_module_does_not_enter_native_controller(self):
  text=(S/'controller.py').read_text();self.assertNotIn("loader.load('legacy",text);self.assertIn("native=loader.load('probe')",text)
 def test_stage_a_before_unknown_member_access(self):
  text=(S/'controller.py').read_text();self.assertLess(text.index('stage_a=job.qualify_root_image()'),text.index("pre=job.observe('AFTER_RESUME_BEFORE_WAIT')"))
 def test_original_deadlines_and_process_domain(self):
  text=(S/'controller.py').read_text();self.assertIn('end=time.monotonic()+10',text);self.assertIn("'normal_bound_seconds':10",text);self.assertIn("'unknown_pid_termination':False",text)
 def test_exact_six_legacy_modified_gate(self):
  text=(S/'controller.py').read_text();self.assertIn('len(pt)==719',text);self.assertIn('modified==allowed_modified',text);self.assertIn('set(pt)<=set(ct)',text)
 def test_new_namespace_proof_not_prior_branch(self):
  self.assertEqual(proof.BRANCH,'codex/pf002-c04-r1-legacy-contract-corrective-v1');self.assertEqual(proof.AUD,'rate-pf002-c04-r1-job-member-forensics')
 def test_native_entry_signed_job_guard_before_ctypes(self):
  text=(S/'job.py').read_text();self.assertLess(text.index('verifier.verify_token'),text.index('import ctypes'))
 def test_native_entry_exact_dispatch(self):
  self.assertIn("'event_name':'workflow_dispatch'",(S/'runner_proof.py').read_text());self.assertIn("run['display_title']=='PF002-C04-R1 '+role",(S/'controller.py').read_text())
 def test_unchanged_native_normal_worker_only(self):
  text=(S/'normal_worker.py').read_text();self.assertNotIn('subprocess',text);self.assertNotIn('time.sleep',text);self.assertIn('C04_R1_NONCE',text)
 def test_no_scan_elevation_cim_or_pid_kill(self):
  for n in ('controller.py','job.py','normal_worker.py','offline_contract.py'):
   text=(S/n).read_text()
   for forbidden in ('CreateToolhelp32Snapshot','EnumProcesses','os.kill','Get-CimInstance','OpenBaseKey','AdjustTokenPrivileges','ReadProcessMemory'):self.assertNotIn(forbidden,text)
   if n!='job.py':self.assertNotIn('TerminateProcess',text)
 def test_only_original_suspended_owned_root_abort_termination(self):
  text=(S/'job.py').read_text();prior=(S.parent/'pf002_c04_image_identity/job.py').read_text();normalized=text.replace('PF002-C04-R1-','PF002-C04-').replace('C04_R1_NONCE','C04_NONCE');self.assertEqual(normalized,prior)
  tree=ast.parse(text);calls=[n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='TerminateProcess'];self.assertEqual(len(calls),1);self.assertEqual(ast.unparse(calls[0]),'self.api.TerminateProcess(hp, 121)')
  self.assertIn('hp,ht,pid,tid=self.api.CreateProcess',text);self.assertIn('True,0x4|0x08000000|0x80000',text);self.assertIn('if not self.k.AssignProcessToJobObject(self.job,hp):',text);self.assertIn('self.k.WaitForSingleObject(hp,10000)',text)
 def test_original_ids_all_preserved(self):
  delta=json.loads((S/'CONTRACT_DELTA_V2.json').read_bytes())
  for group,row in delta['inherited_ids'].items():
   p=S.parent/group/row['test_file'];tree=ast.parse(p.read_bytes());actual=sorted(n.name for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name.startswith('test_'));self.assertEqual(actual,row['original_test_methods'])
 def test_no_skips_or_expectedfailure_decorators(self):
  for p in (S/'test_contract.py',S.parent/'pf002_c02_job_member_provenance/test_forensics.py',S.parent/'pf002_c03_forensic_evidence/test_evidence.py'):
   tree=ast.parse(p.read_bytes())
   for n in ast.walk(tree):
    if isinstance(n,ast.FunctionDef):self.assertEqual(n.decorator_list,[])
 def test_contract_requires_native_separately(self):
  q=json.loads((S/'CONTRACT_DELTA_V2.json').read_bytes());self.assertFalse(q['offline_successor_is_native_qualification']);self.assertEqual(q['legacy_runtime_status'],'LEGACY_COMPARATOR_NOT_RUNTIME_QUALIFIED')
 def test_two_original_successors_mapped(self):
  q=json.loads((S/'CONTRACT_DELTA_V2.json').read_bytes());self.assertEqual(len(q['original_blockers']),2);self.assertTrue(all(row['original_assertions_retained_or_strengthened'] for row in q['original_blockers']))

 def test_c02_retired_entry_never_calls_drive_provider(self):
  def forbidden(a):raise AssertionError('NO_RETIRED_CALLBACK')
  with self.assertRaisesRegex(model.Unknown,'LEGACY_COMPARATOR_NOT_RUNTIME_QUALIFIED'):self.c02().disk_image(str(self.image()),time.monotonic()+1,forbidden)
 def test_c03_retired_entry_never_calls_drive_provider(self):
  def forbidden(a):raise AssertionError('NO_RETIRED_CALLBACK')
  with self.assertRaisesRegex(model.Unknown,'LEGACY_COMPARATOR_NOT_RUNTIME_QUALIFIED'):self.c03().disk_image(str(self.image()),time.monotonic()+1,forbidden,lambda *r:None)
 def test_fake_reader_module_cannot_choose_validator(self):
  m=self.c03();p=self.image();calls=[];r=types.SimpleNamespace(__contract_module=types.SimpleNamespace(validate_fixture=lambda *a:calls.append(a) or {'status':'PASS'}))
  with self.assertRaisesRegex(model.Unknown,'EXPLICIT_OFFLINE_FIXTURE_REQUIRED'):m.validate_offline_fixture(str(p),time.monotonic()+1,lambda a:True,lambda *r:None,r)
  self.assertEqual(calls,[])
 def test_valid_reader_injected_module_is_ignored(self):
  m=self.c03();p=self.image();r=m.offline_reader(p,3);calls=[];r.__dict__['__contract_module']=types.SimpleNamespace(validate_fixture=lambda *a:calls.append(a) or {'runtime_qualified':True})
  v=m.validate_offline_fixture(str(p),time.monotonic()+1,lambda a:True,lambda *r:None,r);self.assertEqual(calls,[]);self.assertFalse(v['runtime_qualified']);self.assertEqual(v['sha256'],hashlib.sha256(b'abc').hexdigest())
