import ast,copy,hashlib,json,os,struct,sys,time,types,unittest
from pathlib import Path
import canonical_file as cf,file_evidence as fe,model,probe,job,runner_proof as proof
S=Path(__file__).resolve().parent;ENGINEERING_OUTPUT_ROOT=None
class FakeReader:
 def __init__(self,edit=None,fail=None):self.calls=[];self.edit=edit;self.fail=fail
 def snapshot(self,fd,phase):
  self.calls.append((fd,phase))
  if self.fail==phase:raise model.Unknown('FILE_API_FAILED')
  row={'schema':cf.SCHEMA,'api':'GetFileInformationByHandleEx','time_units':'FILETIME_100NS_1601_UTC','phase':phase,'file_descriptor':fd,'native_handle':fd+1000,'identity':base_identity()}
  if self.edit:self.edit(row)
  return row
def base_identity():return {'volume_serial_u64':77,'file_id_128_le':'01'+'00'*15,'file_size_bytes':3,'creation_time_100ns':100,'change_time_100ns':300,'last_write_time_100ns':200,'file_attributes_u32':32,'number_of_links':1}
class Tests(unittest.TestCase):
 def observations(self):
  return [{'schema':cf.SCHEMA,'api':'GetFileInformationByHandleEx','time_units':'FILETIME_100NS_1601_UTC','phase':phase,'file_descriptor':2 if phase.startswith('PATH_') else 1,'native_handle':102 if phase.startswith('PATH_') else 101,'identity':base_identity()} for phase in cf.PHASES]
 def hash(self):return {'bytes':3,'sha256':hashlib.sha256(b'abc').hexdigest()}
 def basic(self,creation=100,access=90,write=200,change=300,attrs=32):return struct.pack('<4qI4x',creation,access,write,change,attrs)
 def standard(self,size=3,links=1,pending=0,directory=0):return struct.pack('<qqIBB2x',4096,size,links,pending,directory)
 def image(self):
  p=ENGINEERING_OUTPUT_ROOT/(self._testMethodName+'.bin');p.write_bytes(b'abc');return p
 def test_semantically_distinct_creation_and_change_preserved(self):
  result=cf.compare(self.observations(),self.hash());self.assertTrue(result['equal']);self.assertEqual(result['identity']['creation_time_100ns'],100);self.assertEqual(result['identity']['change_time_100ns'],300)
 def test_swapped_creation_change_rejects(self):
  rows=self.observations();rows[2]['identity'].update(creation_time_100ns=300,change_time_100ns=100);r=cf.compare(rows,self.hash());self.assertFalse(r['equal']);self.assertEqual(r['mismatch_fields']['PATH_REOPENED_BEFORE'],['creation_time_100ns','change_time_100ns'])
 def changed(self,key,value):
  rows=self.observations();rows[2]['identity'][key]=value;r=cf.compare(rows,self.hash());self.assertFalse(r['equal']);self.assertIn(key,r['mismatch_fields']['PATH_REOPENED_BEFORE'])
 def test_volume_changed(self):self.changed('volume_serial_u64',78)
 def test_file_id_changed(self):self.changed('file_id_128_le','02'+'00'*15)
 def test_file_id_upper_64_bits_retained(self):self.changed('file_id_128_le','01'+'00'*14+'01')
 def test_file_size_changed(self):self.changed('file_size_bytes',4)
 def test_last_write_changed_one_tick(self):self.changed('last_write_time_100ns',201)
 def test_change_time_changed_one_tick(self):self.changed('change_time_100ns',301)
 def test_creation_changed_one_tick(self):self.changed('creation_time_100ns',101)
 def test_attributes_changed(self):self.changed('file_attributes_u32',128)
 def test_link_count_changed(self):self.changed('number_of_links',2)
 def test_file_replacement_same_hash_not_accepted(self):self.changed('file_id_128_le','ff'*16)
 def test_zero_creation_reject(self):
  rows=self.observations();rows[0]['identity']['creation_time_100ns']=0
  with self.assertRaises(model.Unknown):cf.compare(rows,self.hash())
 def test_negative_change_reject(self):
  rows=self.observations();rows[0]['identity']['change_time_100ns']=-1
  with self.assertRaises(model.Unknown):cf.compare(rows,self.hash())
 def test_boolean_time_reject(self):
  rows=self.observations();rows[0]['identity']['last_write_time_100ns']=True
  with self.assertRaises(model.Unknown):cf.compare(rows,self.hash())
 def test_float_time_reject(self):
  rows=self.observations();rows[0]['identity']['last_write_time_100ns']=200.0
  with self.assertRaises(model.Unknown):cf.compare(rows,self.hash())
 def test_missing_change_not_dropped(self):
  rows=self.observations();del rows[0]['identity']['change_time_100ns']
  with self.assertRaises(model.Unknown):cf.compare(rows,self.hash())
 def test_unknown_identity_field_reject(self):
  rows=self.observations();rows[0]['identity']['st_ctime_ns']=300
  with self.assertRaises(model.Unknown):cf.compare(rows,self.hash())
 def test_python_ctime_source_not_native_equivalence(self):
  rows=self.observations();rows[2]['schema']='PYTHON_CTIME'
  with self.assertRaises(model.Unknown):cf.compare(rows,self.hash())
 def test_ns_units_not_silently_converted(self):
  rows=self.observations();rows[2]['time_units']='UNIX_NS'
  with self.assertRaises(model.Unknown):cf.compare(rows,self.hash())
 def test_empty_file_id_unknown(self):
  row=base_identity();row['file_id_128_le']='00'*16
  with self.assertRaises(model.Unknown):cf.validate(row)
 def test_short_file_id_unknown(self):
  row=base_identity();row['file_id_128_le']='ab'*8
  with self.assertRaises(model.Unknown):cf.validate(row)
 def test_volume_overflow_unknown(self):
  row=base_identity();row['volume_serial_u64']=2**64
  with self.assertRaises(model.Unknown):cf.validate(row)
 def test_boolean_volume_unknown(self):
  row=base_identity();row['volume_serial_u64']=True
  with self.assertRaises(model.Unknown):cf.validate(row)
 def test_phases_not_retry_loop(self):
  rows=self.observations();rows[-1]['phase']='OPENED_BEFORE'
  with self.assertRaises(model.Unknown):cf.compare(rows,self.hash())
 def test_missing_observation_unknown(self):
  with self.assertRaises(model.Unknown):cf.compare(self.observations()[:-1],self.hash())
 def test_retained_handle_identity_change(self):
  rows=self.observations();rows[1]['native_handle']=999
  with self.assertRaisesRegex(model.Unknown,'HANDLE_CHANGED'):cf.compare(rows,self.hash())
 def test_path_handle_changes_during_read(self):
  rows=self.observations();rows[3]['native_handle']=999
  with self.assertRaisesRegex(model.Unknown,'HANDLE_CHANGED'):cf.compare(rows,self.hash())
 def test_path_not_reopened_unknown(self):
  rows=self.observations()
  for row in rows:row['file_descriptor']=1;row['native_handle']=101
  with self.assertRaisesRegex(model.Unknown,'NOT_REOPENED'):cf.compare(rows,self.hash())
 def test_same_path_string_is_not_file_identity(self):self.changed('file_id_128_le','ab'*16)
 def test_hash_byte_count_conflict(self):
  h=self.hash();h['bytes']=2
  with self.assertRaisesRegex(model.Unknown,'HASH_BINDING'):cf.compare(self.observations(),h)
 def test_malformed_hash_reject(self):
  h=self.hash();h['sha256']='SECRET'
  with self.assertRaises(model.Unknown):cf.compare(self.observations(),h)
 def test_hash_does_not_attest_loaded_image(self):self.assertFalse(cf.compare(self.observations(),self.hash())['loaded_image_attestation'])
 def test_read_sequence_not_atomic(self):self.assertFalse(cf.compare(self.observations(),self.hash())['atomic_snapshot'])
 def test_basic_decoder_source_semantics(self):
  r=cf.decode(0,self.basic());self.assertEqual((r['creation_time_100ns'],r['change_time_100ns'],r['last_write_time_100ns']),(100,300,200))
 def test_basic_padding_not_identity(self):
  raw=bytearray(self.basic());raw[-4:]=b'\xff'*4;self.assertEqual(cf.decode(0,bytes(raw)),cf.decode(0,self.basic()))
 def test_standard_padding_not_identity(self):
  raw=bytearray(self.standard());raw[-2:]=b'\xff'*2;self.assertEqual(cf.decode(1,bytes(raw)),cf.decode(1,self.standard()))
 def test_raw_id_full_128_bits(self):
  raw=struct.pack('<Q16s',77,b'\x01'+b'\x00'*14+b'\x80');self.assertEqual(cf.decode(18,raw)['file_id_128_le'],raw[8:].hex())
 def test_raw_standard_size(self):self.assertEqual(cf.decode(1,self.standard())['file_size_bytes'],3)
 def test_basic_truncated(self):
  with self.assertRaises(model.Unknown):cf.decode(0,self.basic()[:-1])
 def test_id_truncated(self):
  with self.assertRaises(model.Unknown):cf.decode(18,b'\0'*16)
 def test_standard_truncated(self):
  with self.assertRaises(model.Unknown):cf.decode(1,self.standard()[:-1])
 def test_extra_buffer_bytes_reject(self):
  with self.assertRaises(model.Unknown):cf.decode(0,self.basic()+b'\0')
 def test_wrong_information_class_reject(self):
  with self.assertRaises(model.Unknown):cf.decode(9,self.basic())
 def test_boolean_information_class_reject(self):
  with self.assertRaises(model.Unknown):cf.decode(False,self.basic())
 def test_reparse_attributes_reject(self):
  with self.assertRaises(model.Unknown):cf.decode(0,self.basic(attrs=0x400))
 def test_directory_attributes_reject(self):
  with self.assertRaises(model.Unknown):cf.decode(0,self.basic(attrs=0x10))
 def test_delete_pending_reject(self):
  with self.assertRaises(model.Unknown):cf.decode(1,self.standard(pending=1))
 def test_standard_directory_reject(self):
  with self.assertRaises(model.Unknown):cf.decode(1,self.standard(directory=1))
 def test_invalid_boolean_structure_reject(self):
  with self.assertRaises(model.Unknown):cf.decode(1,self.standard(directory=2))
 def test_oversize_image_reject(self):
  with self.assertRaises(model.Unknown):cf.decode(1,self.standard(size=32*1024*1024+1))
 def test_maximum_file_size_contract(self):self.assertEqual(cf.decode(1,self.standard(size=32*1024*1024))['file_size_bytes'],32*1024*1024)
 def test_zero_size_unknown(self):
  with self.assertRaises(model.Unknown):cf.decode(1,self.standard(size=0))
 def test_last_access_change_is_not_change_time(self):
  a=cf.decode(0,self.basic(access=10));b=cf.decode(0,self.basic(access=20));self.assertNotEqual(a['last_access_time_100ns'],b['last_access_time_100ns']);self.assertEqual(a['change_time_100ns'],b['change_time_100ns'])
 def test_actual_owned_fixture_hash_and_close(self):
  p=self.image();rows=[];reader=FakeReader();r=fe.disk_image(str(p),time.monotonic()+2,lambda a:True,lambda *r:rows.append(r),reader)
  self.assertEqual(r['sha256'],hashlib.sha256(p.read_bytes()).hexdigest());self.assertEqual(len(reader.calls),5);self.assertEqual(len([r for r in rows if r[0]=='FILE_OPEN_RESULT']),2);self.assertEqual(len([r for r in rows if r[0]=='FILE_CLOSE_RESULT']),2);self.assertTrue(all(r[1]['python_file_closed'] for r in rows if r[0]=='FILE_CLOSE_RESULT'))
 def test_same_hash_replacement_emitted_then_halt(self):
  p=self.image();rows=[]
  def edit(row):
   if row['phase'].startswith('PATH_'):row['identity']['file_id_128_le']='ff'*16
  with self.assertRaisesRegex(model.Unknown,'CANONICAL_FILE_IDENTITY_CHANGED'):fe.disk_image(str(p),time.monotonic()+2,lambda a:True,lambda *r:rows.append(r),FakeReader(edit))
  comparison=next(v for k,v in rows if k=='CANONICAL_FILE_COMPARISON');self.assertFalse(comparison['equal']);self.assertIn('file_id_128_le',comparison['mismatch_fields']['PATH_REOPENED_BEFORE']);self.assertEqual(len([r for r in rows if r[0]=='FILE_CLOSE_RESULT']),2)
 def test_api_failure_no_retry_and_one_close(self):
  p=self.image();rows=[];reader=FakeReader(fail='OPENED_BEFORE')
  with self.assertRaisesRegex(model.Unknown,'FILE_API_FAILED'):fe.disk_image(str(p),time.monotonic()+2,lambda a:True,lambda *r:rows.append(r),reader)
  self.assertEqual(len(reader.calls),1);self.assertEqual(len([r for r in rows if r[0]=='FILE_CLOSE_RESULT']),1)
 def test_path_second_observation_failure_no_retry(self):
  p=self.image();rows=[];reader=FakeReader(fail='PATH_REOPENED_AFTER')
  with self.assertRaises(model.Unknown):fe.disk_image(str(p),time.monotonic()+2,lambda a:True,lambda *r:rows.append(r),reader)
  self.assertEqual(len(reader.calls),4);self.assertEqual(len([r for r in rows if r[0]=='FILE_CLOSE_RESULT']),2)
 def test_deadline_exceeded_no_file_open(self):
  p=self.image();rows=[];reader=FakeReader()
  with self.assertRaisesRegex(model.Unknown,'DEADLINE'):fe.disk_image(str(p),time.monotonic()-1,lambda a:True,lambda *r:rows.append(r),reader)
  self.assertEqual(reader.calls,[]);self.assertFalse(any(k=='FILE_OPEN_RESULT' for k,v in rows))
 def test_unc_path_reject(self):
  with self.assertRaisesRegex(model.Unknown,'LOCAL_PHYSICAL'):fe.disk_image('\\\\host\\share\\x.exe',time.monotonic()+1,lambda a:True,lambda *r:None,FakeReader())
 def test_mapped_remote_drive_reject_before_resolve(self):
  p=ENGINEERING_OUTPUT_ROOT/'does_not_exist'
  with self.assertRaisesRegex(model.Unknown,'NOT_FIXED'):fe.disk_image(str(p),time.monotonic()+1,lambda a:False,lambda *r:None,FakeReader())
 def test_missing_fixed_drive_proof_reject(self):
  with self.assertRaisesRegex(model.Unknown,'NOT_FIXED'):fe.disk_image(str(self.image()),time.monotonic()+1,None,lambda *r:None,FakeReader())
 def test_symlink_guard_without_privilege(self):
  p=self.image();actual=Path.is_symlink
  Path.is_symlink=lambda q:q==p or actual(q)
  try:
   with self.assertRaises(model.Unknown):fe.disk_image(str(p),time.monotonic()+1,lambda a:True,lambda *r:None,FakeReader())
  finally:Path.is_symlink=actual
 def test_junction_guard_without_creation(self):
  p=self.image();actual=Path.lstat
  Path.lstat=lambda q:types.SimpleNamespace(st_file_attributes=0x400,st_mode=0o100600) if q==p else actual(q)
  try:
   with self.assertRaisesRegex(model.Unknown,'REPARSE'):fe.disk_image(str(p),time.monotonic()+1,lambda a:True,lambda *r:None,FakeReader())
  finally:Path.lstat=actual
 def test_observable_toctou_identity_change_failclosed(self):
  p=self.image();reader=FakeReader(lambda r:r['identity'].update(change_time_100ns=301) if r['phase']=='OPENED_FINAL' else None)
  with self.assertRaises(model.Unknown):fe.disk_image(str(p),time.monotonic()+1,lambda a:True,lambda *r:None,reader)
 def test_missing_evidence_sink_reject(self):
  with self.assertRaises(model.Unknown):fe.disk_image(str(self.image()),time.monotonic()+1,lambda a:True,None,FakeReader())
 def test_missing_native_reader_reject(self):
  with self.assertRaises(model.Unknown):fe.disk_image(str(self.image()),time.monotonic()+1,lambda a:True,lambda *r:None,None)
 def native_query_fake(self,success=1,error=5,capacity=40):
  p=cf.NativeReader.__new__(cf.NativeReader);p.rows=[];p.emit=lambda *r:p.rows.append(r);p.bounded=lambda:None;p.types={0:lambda:types.SimpleNamespace(raw=self.basic())};p.calls=[]
  p.c=types.SimpleNamespace(sizeof=lambda r:capacity,byref=lambda r:r,string_at=lambda r,n:r.raw[:n],set_last_error=lambda e:None,get_last_error=lambda:error)
  p.k=types.SimpleNamespace(GetFileInformationByHandleEx=lambda *a:p.calls.append(a) or success);return p
 def test_native_access_denied_preserved(self):
  p=self.native_query_fake(0,5)
  with self.assertRaisesRegex(model.Unknown,'FILE_API_FAILED'):p.query(101,0,'OPENED_BEFORE')
  self.assertEqual(p.rows[0][1]['win32_error'],5);self.assertFalse(p.rows[0][1]['ok']);self.assertEqual(len(p.calls),1)
 def test_native_success_ignores_stale_lasterror(self):
  p=self.native_query_fake(1,999);r=p.query(101,0,'OPENED_BEFORE');self.assertEqual(r['change_time_100ns'],300);self.assertIsNone(p.rows[0][1]['win32_error']);self.assertFalse(p.rows[0][1]['returned_length_available'])
 def test_native_wrong_structure_before_dispatch(self):
  p=self.native_query_fake(capacity=24)
  with self.assertRaisesRegex(model.Unknown,'FILE_API_ABI'):p.query(101,0,'OPENED_BEFORE')
  self.assertEqual(p.calls,[])
 def test_native_wrong_class_before_dispatch(self):
  p=self.native_query_fake()
  with self.assertRaisesRegex(model.Unknown,'FILE_INFO_CLASS'):p.query(101,9,'OPENED_BEFORE')
  self.assertEqual(p.calls,[])
 def test_native_failed_call_not_retried(self):
  p=self.native_query_fake(0,87)
  with self.assertRaises(model.Unknown):p.query(101,0,'OPENED_BEFORE')
  self.assertEqual(len(p.calls),1);self.assertEqual(p.rows[0][1]['win32_error'],87)
 def test_unsigned_probe_rejects_before_native(self):
  with self.assertRaises(Exception):probe.Probe('NOT_SIGNED',{},lambda *r:None,time.monotonic()+1)
 def test_native_provider_requires_signed_boundary(self):
  with self.assertRaisesRegex(model.Unknown,'NATIVE_PROVIDER_REQUIRED'):cf.NativeReader(None)
 def test_stage_b_cannot_run_before_stage_a(self):
  p=probe.Probe.__new__(probe.Probe);p.stage_a_passed=False
  with self.assertRaisesRegex(model.Unknown,'STAGE_A_REQUIRED'):p.observe('AFTER_RESUME_BEFORE_WAIT')
 def test_unknown_identity_cannot_run_before_stage_a(self):
  p=probe.Probe.__new__(probe.Probe);p.pid=11;p.stage_a_passed=False
  with self.assertRaisesRegex(model.Unknown,'STAGE_A_REQUIRED'):p.identity(123,12)
 def test_stage_a_cannot_be_repeated(self):
  p=probe.Probe.__new__(probe.Probe);p.stage_a_passed=True;p.stage_a_root={}
  with self.assertRaisesRegex(model.Unknown,'STAGE_A_REQUIRED'):p.qualify_root_image()
 def process(self):return {'pid':11,'creation_time_100ns':100,'image_path':'C:\\approved\\python.exe','disk_image':{'canonical_source_schema':cf.SCHEMA,'canonical_identity':base_identity(),'sha256':self.hash()['sha256']}}
 def test_root_cross_phase_hash_conflict(self):
  a=self.process();b=copy.deepcopy(a);b['disk_image']['sha256']='f'*64;self.assertFalse(cf.same_across_process_observations(a,b))
 def test_root_cross_phase_file_replacement(self):
  a=self.process();b=copy.deepcopy(a);b['disk_image']['canonical_identity']['file_id_128_le']='f'*32;self.assertFalse(cf.same_across_process_observations(a,b))
 def test_root_cross_phase_process_restart(self):
  a=self.process();b=copy.deepcopy(a);b['creation_time_100ns']=101;self.assertFalse(cf.same_across_process_observations(a,b))
 def test_source_no_write_api_scan_or_pid_termination(self):
  for name in ('canonical_file.py','file_evidence.py','probe.py','controller.py'):
   text=(S/name).read_text()
   for forbidden in ('SetFileInformationByHandle','CreateToolhelp32Snapshot','EnumProcesses','TerminateProcess','os.kill','Get-CimInstance','OpenBaseKey','AdjustTokenPrivileges','ReadProcessMemory'):self.assertNotIn(forbidden,text)
 def test_borrowed_handles_never_native_close(self):self.assertNotIn('CloseHandle(', (S/'canonical_file.py').read_text())
 def test_native_entry_exact_dispatch_not_push(self):
  text=(S/'runner_proof.py').read_text();self.assertIn("'event_name':'workflow_dispatch'",text);self.assertNotIn("'event_name':'push'",text)
 def test_accepted_source_binding_701(self):
  text=(S/'controller.py').read_text();self.assertIn('len(pt)==701',text);self.assertIn('run[\'display_title\']==\'PF002-C04 \'+role',text)
 def test_controller_stage_a_precedes_job_member_observe(self):
  text=(S/'controller.py').read_text();self.assertLess(text.index('stage_a=job.qualify_root_image()'),text.index("pre=job.observe('AFTER_RESUME_BEFORE_WAIT')"))
 def test_fixed_api_only_three_info_classes(self):self.assertEqual(cf.SIZES,{0:40,1:24,18:24})

 def origin_fixture(self,receipt_pid=11):
  root=self.process();root['exit_time_100ns']=500
  member=self.process();member.update(pid=12,creation_time_100ns=200,pbi={'pid':12,'parent_pid':11},membership_before=True,membership_after=True)
  receipt={'pid':receipt_pid,'parent_pid':11,'executable':member['image_path']}
  obs=[{'phase':phase,'members':[copy.deepcopy(member)],'accounting':{'ActiveProcesses':1},'ids':{'pids':[12]}} for phase in ('AFTER_RESUME_BEFORE_WAIT','AFTER_ROOT_WAIT')]
  return root,receipt,obs
 def test_root_receipt_cannot_prove_unknown_origin(self):
  r=model.classify(*self.origin_fixture());self.assertEqual(r['unknown_member_origin'],'UNPROVEN');self.assertFalse(r['origin_evidence_complete_candidate'])
 def test_parent_link_only_cannot_prove_origin(self):
  root,receipt,obs=self.origin_fixture(99);r=model.classify(root,receipt,obs);self.assertEqual(r['root_cause'],'UNPROVEN');self.assertFalse(r['origin_evidence_complete_candidate'])
 def test_complete_candidate_requires_independent_review(self):
  r=model.classify(*self.origin_fixture(12));self.assertTrue(r['origin_evidence_complete_candidate']);self.assertEqual(r['unknown_member_origin'],'UNPROVEN');self.assertTrue(r['origin_requires_independent_acceptance']);self.assertFalse(r['trusted_member_allowlist_modified']);self.assertEqual(r['RS02'],'BLOCKED')
 def test_single_phase_member_is_incomplete(self):
  root,receipt,obs=self.origin_fixture(12);obs[0]['members']=[];r=model.classify(root,receipt,obs);self.assertFalse(r['origin_evidence_complete_candidate'])
 def test_member_restart_is_halt(self):
  root,receipt,obs=self.origin_fixture(12);obs[1]['members'][0]['creation_time_100ns']=201
  with self.assertRaisesRegex(model.Unknown,'MEMBER_IDENTITY_CHANGED'):model.classify(root,receipt,obs)
 def test_member_canonical_identity_change_is_halt(self):
  root,receipt,obs=self.origin_fixture(12);obs[1]['members'][0]['disk_image']['canonical_identity']['change_time_100ns']+=1
  with self.assertRaisesRegex(model.Unknown,'MEMBER_IDENTITY_CHANGED'):model.classify(root,receipt,obs)
 def test_member_source_unknown_is_halt(self):
  root,receipt,obs=self.origin_fixture(12);obs[0]['members'][0]['disk_image']['canonical_source_schema']='UNKNOWN'
  with self.assertRaisesRegex(model.Unknown,'CANONICAL_SOURCE'):model.classify(root,receipt,obs)
 def test_member_time_outside_root_cannot_prove_origin(self):
  root,receipt,obs=self.origin_fixture(12)
  for o in obs:o['members'][0]['creation_time_100ns']=501
  self.assertFalse(model.classify(root,receipt,obs)['origin_evidence_complete_candidate'])
