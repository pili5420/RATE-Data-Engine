import copy,struct,unittest
from ..adapter import OfflineIdentityCandidate,NativeCallGuard
from ..protocol import digest,Denied
from ..provider import ScriptedWindowsProvider
from ..journal import SyntheticWorkspace
from . import fixtures as f
from .test_candidate import CandidateTests

class FaultTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.root=CandidateTests.workspace;cls.trace=CandidateTests.good_trace
 def run_fault(self,api,kind,value=None,path=None,occurrence=0,window_only=False):
  rows=[(i+1,row) for i,row in enumerate(self.trace) if row['request']['api']==api and (not window_only or row['request']['subject']['role']=='window')];index=rows[occurrence][0]
  w=SyntheticWorkspace(self.root);m,p,v=f.bundle(w);world=copy.deepcopy(p.scenario);fault={'call':index,'kind':kind}
  if kind in {'delay','receipt_override','world_change'}:fault['value']=value
  if kind=='world_change':fault['path']=path
  world['faults']=[fault];p=f.replace_provider(m,world);r=OfflineIdentityCandidate().run(m,p,v,w);return r,w,m,p,index
 def denied(self,r):self.assertIn(r['status'],{'BLOCKED','INDETERMINATE'});self.assertFalse(r['native_execution_authorized']);self.assertFalse(r['diagnostic_authorized']);self.assertNotIn('identity',r)
 def test_true_process_restart_during_read(self):self.denied(self.run_fault('GetProcessTimes','world_change',f.CREATION+999,['processes','101','creation'],-1,True)[0])
 def test_hwnd_same_handle_pid_reuse(self):self.denied(self.run_fault('GetWindowThreadProcessId','world_change',999,['windows',0,'pid'],-1,True)[0])
 def test_tid_replacement(self):self.denied(self.run_fault('GetWindowThreadProcessId','world_change',999,['windows',0,'tid'],-1,True)[0])
 def test_window_destroyed_between_reads(self):self.denied(self.run_fault('IsWindow','world_change',False,['windows',0,'alive'],-1,True)[0])
 def test_class_replaced(self):self.denied(self.run_fault('GetClassNameW','world_change','Other',['windows',0,'class_name'],-1,True)[0])
 def test_file_contents_tampered_before_read(self):self.denied(self.run_fault('ReadFile','world_change',(b'X'*len(f.DATA)).hex(),['file','hex'])[0])
 def test_file_id_changed_after_read(self):self.denied(self.run_fault('GetFileInformationByHandleEx','world_change','22'*16,['file','file_id'],3,True)[0])
 def test_file_write_metadata_changed(self):self.denied(self.run_fault('GetFileInformationByHandleEx','world_change',999,['file','write'],3,True)[0])
 def test_image_path_replaced_after_read(self):self.denied(self.run_fault('QueryFullProcessImageNameW','world_change',r'C:\Windows\System32\control.exe',['processes','101','path'],-1,True)[0])
 def test_target_token_elevation_lost_after_read(self):self.denied(self.run_fault('GetTokenInformation','world_change',0,['processes','101','token','elevated'],4,True)[0])
 def test_host_changed_before_final_context(self):self.denied(self.run_fault('GetComputerNameExW','world_change','OTHER',['host'],-1)[0])
 def test_short_file_read_no_retry(self):
  r,w,m,p,index=self.run_fault('ReadFile','receipt_override',{'result':'00'});self.denied(r);self.assertEqual(len(p.calls),index)
 def test_call_timeout_no_retry(self):
  r,w,m,p,index=self.run_fault('GetComputerNameExW','delay',2000000000);self.denied(r);self.assertEqual(len(p.calls),1);self.assertIn('TIMEOUT',r['reason'])
 def test_unknown_api_outcome_no_retry(self):
  r,w,m,p,index=self.run_fault('GetCurrentProcessId','unknown');self.denied(r);self.assertEqual(len(p.calls),index)
 def test_provider_exception_no_resume(self):
  r,w,m,p,index=self.run_fault('OpenProcess','exception');self.denied(r);self.assertEqual(len(p.calls),index);self.assertFalse(w.audit_attempt(m['attempt_id'])['resume_authorized'])

RECEIPTS=[('wrong_api',{'api':'ReadFile'}),('bool_clock',{'start_ns':True}),('negative_end',{'end_ns':-1}),('bool_error',{'last_error':False}),('unknown_status',{'status':'UNKNOWN'}),('extra_field',{'unexpected':True}),('wrong_result_type',{'result':True}),('invalid_utf16',{'result':'00d80000'}),('truncated_utf16',{'result':'4100'}),('unterminated_host',{'result':'41004100'})]
def receipt_test(value):
 def test(self):
  r,w,m,p,index=self.run_fault('GetComputerNameExW','receipt_override',value);self.denied(r);self.assertEqual(len(p.calls),1)
 return test
for name,value in RECEIPTS:setattr(FaultTests,'test_receipt_'+name,receipt_test(value))

INITIAL_WORLD=[('host',['host'],'OTHER'),('observer_session',['processes','10','session_id'],2),('parent_session',['processes','11','session_id'],2),('target_session',['processes','101','session_id'],2),('observer_station',['observer','station'],'OTHER'),('observer_desktop',['observer','desktop'],'OTHER'),('target_desktop',['windows',0,'desktop'],'OTHER'),('observer_restart',['processes','10','creation'],f.CREATION+999),('parent_restart',['processes','11','creation'],f.CREATION+999),('target_initial_restart',['processes','101','creation'],f.CREATION+999),('file_id',['file','file_id'],'22'*16),('file_reparse',['file','attributes'],1024),('volume',['file','volume_serial'],999)]
for role in ['10','11','101']:
 for name,key,value in [('not_elevated','elevated',0),('limited_token','elevation_type',3),('medium_integrity','integrity_rid',8192),('deny_only_admin','admin_attributes',31),('bool_attributes','admin_attributes',True),('wide_attributes','admin_attributes',2**32+15)]:INITIAL_WORLD.append((role+'_'+name,['processes',role,'token',key],value))
def initial_world_test(path,value):
 def test(self):
  w=SyntheticWorkspace(self.root);m,p,v=f.bundle(w);world=copy.deepcopy(p.scenario);target=world
  for k in path[:-1]:target=target[k]
  target[path[-1]]=value;p=f.replace_provider(m,world);r=OfflineIdentityCandidate().run(m,p,v,w);self.denied(r)
 return test
for name,path,value in INITIAL_WORLD:setattr(FaultTests,'test_initial_world_'+name,initial_world_test(path,value))
