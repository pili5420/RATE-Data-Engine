"""Regressions for independent183c7db7 findings; no native execution."""
import copy,hashlib,json,threading,unittest
from uuid import uuid4
from unittest.mock import patch
from .. import protocol
from ..adapter import OfflineIdentityCandidate,NativeCallGuard,validate_review_ack
from ..provider import ScriptedWindowsProvider
from ..journal import SyntheticWorkspace
from ..protocol import Denied,digest,canonical
from .test_candidate import CandidateTests
from . import fixtures as f

class ReviewCorrectiveTests(unittest.TestCase):
 def new(self,count=1):
  if not hasattr(self,'case_root'):
   self.case_root=CandidateTests.workspace.parent/(CandidateTests.workspace.name+'-review-'+uuid4().hex);self.case_root.mkdir()
  w=SyntheticWorkspace(self.case_root);return w,*f.bundle(w,count)
 def private(self):
  root=CandidateTests.workspace.parent/(CandidateTests.workspace.name+'-private-'+uuid4().hex);root.mkdir();w=SyntheticWorkspace(root);return w,*f.bundle(w)
 def denied(self,result):self.assertIn(result['status'],{'BLOCKED','INDETERMINATE'});self.assertFalse(result['diagnostic_authorized']);self.assertNotIn('identity',result)
 def excluded(self):
  w,m,p,v=self.new(2);world=copy.deepcopy(p.scenario);world['windows'][1]['class_name']='Other'
  for event in v['events']:
   if event['identity']['hwnd']==2:event['identity']['class_name']='Other'
  f.bind_witness(m,v);return w,m,world,v
 def test_partial_durable_intent_reserves_nonce_without_secondary_index(self):
  w,m,p,v=self.new();original=w.write_new
  def crash(path,value):
   h=original(path,value)
   if path.name.startswith('attempt-'):raise RuntimeError('SYNTHETIC_EXIT_AFTER_FIRST_DURABLE_WRITE')
   return h
  w.write_new=crash
  with self.assertRaisesRegex(RuntimeError,'SYNTHETIC_EXIT'):w.claim(m)
  other=SyntheticWorkspace(w.root);a,provider,proof=f.bundle(other,nonce=m['nonce']);r=OfflineIdentityCandidate().run(a,provider,proof,other);self.denied(r);self.assertIn('REPLAY',r['reason']);self.assertEqual(provider.calls,[]);self.assertEqual(other.audit_attempt(m['attempt_id'])['state'],'UNKNOWN_PARTIAL_OR_CRASH')
 def test_unknown_journal_entry_blocks_before_any_request(self):
  w,m,p,v=self.private();path=w.journal/'unknown-entry';path.write_bytes(b'?');r=OfflineIdentityCandidate().run(m,p,v,w);self.denied(r);self.assertEqual(p.calls,[]);self.assertEqual(path.read_bytes(),b'?')
 def test_malformed_other_intent_blocks_before_any_request(self):
  w,m,p,v=self.private();path=w.journal/('attempt-'+'f'*64+'.json');path.write_bytes(b'{');r=OfflineIdentityCandidate().run(m,p,v,w);self.denied(r);self.assertEqual(p.calls,[]);self.assertEqual(path.read_bytes(),b'{')
 def test_excluded_candidate_wrong_pid_witness_rejected(self):
  w,m,world,v=self.excluded()
  for event in v['events']:
   if event['identity']['hwnd']==2:event['identity']['pid']=999
  f.bind_witness(m,v);p=f.replace_provider(m,world);r=OfflineIdentityCandidate().run(m,p,v,w);self.denied(r);self.assertIn('WINDOW_WITNESS_MISMATCH',r['reason'])
 def excluded_image(self):
  w,m,p,v=self.new(2);world=copy.deepcopy(p.scenario);world['processes']['102']['path']=r'C:\Windows\System32\control.exe'
  for event in v['events']:
   if event['identity']['hwnd']==2:event['identity']['executable_path']=r'C:\Windows\System32\control.exe'
  f.bind_witness(m,v);return w,m,world,v
 def test_known_image_exclusion_preserves_unique_and_file_scope(self):
  w,m,world,v=self.excluded_image();p=f.replace_provider(m,world);r=OfflineIdentityCandidate().run(m,p,v,w);self.assertEqual(r['status'],'RESOLVED_OFFLINE_IDENTITY_ONLY');self.assertEqual(r['identity'],f.identity());self.assertFalse(any(row['request']['api']=='CreateFileW' and row['request']['subject'].get('hwnd')==2 for row in p.calls))
 def test_excluded_image_wrong_creation_witness_rejected(self):
  w,m,world,v=self.excluded_image()
  for event in v['events']:
   if event['identity']['hwnd']==2:event['identity']['creation_filetime_100ns']+=99
  f.bind_witness(m,v);p=f.replace_provider(m,world);r=OfflineIdentityCandidate().run(m,p,v,w);self.denied(r);self.assertIn('WINDOW_WITNESS_MISMATCH',r['reason'])
 def test_excluded_image_path_witness_contradiction_rejected(self):
  w,m,world,v=self.excluded_image()
  for event in v['events']:
   if event['identity']['hwnd']==2:event['identity']['executable_path']=f.IMAGE
  f.bind_witness(m,v);p=f.replace_provider(m,world);r=OfflineIdentityCandidate().run(m,p,v,w);self.denied(r);self.assertIn('WINDOW_WITNESS_MISMATCH',r['reason'])
 def test_excluded_class_change_during_final_context_rejected(self):
  w,m,world,v=self.excluded();p=f.replace_provider(m,world);positive=OfflineIdentityCandidate().run(m,p,v,w);self.assertEqual(positive['status'],'RESOLVED_OFFLINE_IDENTITY_ONLY')
  last_host=next(i+1 for i,row in reversed(list(enumerate(p.calls))) if row['request']['api']=='GetComputerNameExW')
  w,m,world,v=self.excluded();world['faults']=[{'call':last_host,'kind':'world_change','path':['windows',1,'class_name'],'value':'#32770'}];p=f.replace_provider(m,world);r=OfflineIdentityCandidate().run(m,p,v,w);self.denied(r);self.assertIn('ALL_CANDIDATE_WINDOW_CHANGED',r['reason'])
 def test_scheduled_final_enumeration_is_not_retry(self):
  w,m,p,v=self.new();r=OfflineIdentityCandidate().run(m,p,v,w);self.assertEqual(r['status'],'RESOLVED_OFFLINE_IDENTITY_ONLY');self.assertEqual(sum(row['request']['api']=='EnumWindows' for row in p.calls),2)
 def test_new_window_after_initial_enumeration_rejected(self):
  w,m,p,v=self.new();index=next(i+1 for i,row in enumerate(CandidateTests.good_trace) if row['request']['api']=='EnumWindows');world=copy.deepcopy(p.scenario);world['faults']=[{'call':index+1,'kind':'world_change','path':['windows'],'value':world['windows']+[dict(world['windows'][0],hwnd=2)]}];p=f.replace_provider(m,world);r=OfflineIdentityCandidate().run(m,p,v,w);self.denied(r);self.assertIn('WINDOW_SET_CHANGED',r['reason'])
 def test_cross_model_scope_review_ack_rejected(self):
  w,m,p,v=self.new();r=OfflineIdentityCandidate().run(m,p,v,w);self.assertEqual(r['status'],'RESOLVED_OFFLINE_IDENTITY_ONLY');other=copy.deepcopy(m);other['scope']['max_calls']+=1;other['scope_sha256']=digest(other['scope']);ack=f.ack(r,other)
  with self.assertRaisesRegex(Denied,'REVIEW_ACK'):validate_review_ack(ack,r,other)
 def test_cross_attempt_review_ack_rejected(self):
  w,m,p,v=self.new();r=OfflineIdentityCandidate().run(m,p,v,w);other=copy.deepcopy(m);other['attempt_id']+='-B';ack=f.ack(r,other)
  with self.assertRaisesRegex(Denied,'REVIEW_ACK'):validate_review_ack(ack,r,other)
 def test_result_scope_substitution_rejected(self):
  w,m,p,v=self.new();r=OfflineIdentityCandidate().run(m,p,v,w);r['scope_sha256']='f'*64;ack=f.ack(r,m)
  with self.assertRaisesRegex(Denied,'REVIEW_ACK'):validate_review_ack(ack,r,m)
 def test_result_identity_digest_substitution_rejected(self):
  w,m,p,v=self.new();r=OfflineIdentityCandidate().run(m,p,v,w);r['identity']['pid']=999;ack=f.ack(r,m)
  with self.assertRaisesRegex(Denied,'REVIEW_ACK'):validate_review_ack(ack,r,m)
 def test_schema_parse_and_hash_same_single_read(self):
  raw=(protocol.HERE/'NATIVE_IDENTITY_SCHEMA_V1.json').read_bytes()
  with patch('pathlib.Path.read_bytes',side_effect=[raw,b'{}']) as read:
   schema,pin=protocol.bound_schema();self.assertEqual(schema,json.loads(raw));self.assertEqual(pin,hashlib.sha256(raw).hexdigest());self.assertEqual(read.call_count,1)
 def test_schema_mutation_guard_blocks_before_request(self):
  w,m,p,v=self.new();w.claim(m);guard=NativeCallGuard(m,p,w)
  with patch('gui_native_identity.adapter.schema_identity',return_value='f'*64):
   with self.assertRaisesRegex(Denied,'SCHEMA_CHANGED'):guard.call('GetCurrentProcessId',{}, {'role':'observer'})
  self.assertEqual(p.calls,[])
 def test_schema_mutation_after_request_stops_further_requests(self):
  w,m,p,v=self.new();w.claim(m);guard=NativeCallGuard(m,p,w)
  with patch('gui_native_identity.adapter.schema_identity',side_effect=[m['schema_sha256'],'f'*64]):
   with self.assertRaisesRegex(Denied,'SCHEMA_CHANGED'):guard.call('GetCurrentProcessId',{}, {'role':'observer'})
  self.assertEqual(len(p.calls),1)
  with self.assertRaisesRegex(Denied,'NO_RETRY'):guard.call('GetCurrentProcessId',{}, {'role':'observer'})
 def test_actual_enumeration_bound_exceeded(self):
  w,m,p,v=self.new(9);r=OfflineIdentityCandidate().run(m,p,v,w);self.denied(r);self.assertIn('ENUMERATION_INCOMPLETE_OR_BOUND',r['reason'])
 def test_terminal_success_guard_cannot_read_again(self):
  w,m,p,v=self.new();candidate=OfflineIdentityCandidate();r=candidate.run(m,p,v,w);self.assertEqual(r['status'],'RESOLVED_OFFLINE_IDENTITY_ONLY');count=len(p.calls)
  with self.assertRaisesRegex(Denied,'TERMINAL_ATTEMPT'):candidate.guard.call('GetCurrentProcessId',{}, {'role':'observer'})
  self.assertEqual(len(p.calls),count);self.assertEqual(w.audit_attempt(m['attempt_id'])['state'],'RESOLVED_OFFLINE_IDENTITY_ONLY')
 def test_result_trace_detached_from_mutable_provider(self):
  w,m,p,v=self.new();r=OfflineIdentityCandidate().run(m,p,v,w);before=digest(r);p.calls[0]['receipt']['result']='mutated';self.assertEqual(digest(r),before)
 def test_concurrent_scan_and_first_write_crash_is_serialized(self):
  w,b,p,v=self.new();paused=threading.Event();release=threading.Event();result=[];partial=[];original=w.write_new
  def pause_before_attempt(path,value):
   if path.name.startswith('attempt-'):
    paused.set()
    if not release.wait(15):raise RuntimeError('TEST_SCHEDULER_TIMEOUT')
   return original(path,value)
  w.write_new=pause_before_attempt
  worker=threading.Thread(target=lambda:result.append(OfflineIdentityCandidate().run(b,p,v,w)));worker.start()
  try:
   self.assertTrue(paused.wait(15));other=SyntheticWorkspace(w.root);a,ap,av=f.bundle(other,nonce=b['nonce']);a_write=other.write_new
   def crash_after_attempt(path,value):
    out=a_write(path,value)
    if path.name.startswith('attempt-'):partial.append(True);raise RuntimeError('SYNTHETIC_FIRST_WRITE_CRASH')
    return out
   other.write_new=crash_after_attempt;ar=OfflineIdentityCandidate().run(a,ap,av,other);self.denied(ar);self.assertEqual(ap.calls,[]);self.assertFalse(partial,'Another claim must not reach first attempt write while B holds its admission lock')
  finally:release.set();worker.join(20)
  self.assertFalse(worker.is_alive());self.assertEqual(result[0]['status'],'RESOLVED_OFFLINE_IDENTITY_ONLY')
 def test_successful_claim_lock_header_preserved_by_commit_rename(self):
  w,m,p,v=self.new();w.claim(m);self.assertFalse((w.journal/'CLAIM_IN_PROGRESS.lock').exists());completed=w.journal/('claim-completed-'+digest(m['attempt_id'])+'.json');data=json.loads(completed.read_bytes());self.assertEqual(data['nonce_sha256'],digest(m['nonce']));self.assertEqual(data['attempt_id'],m['attempt_id']);self.assertTrue(data['no_resume'])
 def test_partial_claim_lock_blocks_different_nonce_without_cleanup(self):
  w,m,p,v=self.new();original=w.write_new
  def crash_after_lock(path,value):
   out=original(path,value)
   if path.name=='CLAIM_IN_PROGRESS.lock':raise RuntimeError('SYNTHETIC_CRASH_AFTER_LOCK')
   return out
  w.write_new=crash_after_lock
  with self.assertRaisesRegex(RuntimeError,'AFTER_LOCK'):w.claim(m)
  lock=w.journal/'CLAIM_IN_PROGRESS.lock';before=lock.read_bytes();other=SyntheticWorkspace(w.root);a,ap,av=f.bundle(other);r=OfflineIdentityCandidate().run(a,ap,av,other);self.denied(r);self.assertEqual(ap.calls,[]);self.assertEqual(lock.read_bytes(),before);self.assertEqual(other.audit_attempt(m['attempt_id'])['state'],'UNKNOWN_PARTIAL_OR_CRASH')

ENUM_NEGATIVES=[('duplicate',{'handles':[1,1],'complete':True,'reported_count':2}),('bool_handle',{'handles':[True],'complete':True,'reported_count':1}),('bool_count',{'handles':[1],'complete':True,'reported_count':True}),('count_mismatch',{'handles':[1],'complete':True,'reported_count':2}),('incomplete',{'handles':[1],'complete':False,'reported_count':1}),('empty_unexpected',{'handles':[],'complete':True,'reported_count':1})]
def enum_negative(value):
 def test(self):
  w,m,p,v=self.new();index=next(i+1 for i,row in enumerate(CandidateTests.good_trace) if row['request']['api']=='EnumWindows');world=copy.deepcopy(p.scenario);world['faults']=[{'call':index,'kind':'receipt_override','value':{'result':value}}];p=f.replace_provider(m,world);r=OfflineIdentityCandidate().run(m,p,v,w);self.denied(r);self.assertEqual(len(p.calls),index)
 return test
for name,value in ENUM_NEGATIVES:setattr(ReviewCorrectiveTests,'test_enum_receipt_'+name,enum_negative(value))
