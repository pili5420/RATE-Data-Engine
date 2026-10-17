import ast,copy,hashlib,json,struct,threading,unittest
from pathlib import Path
from uuid import uuid4
from .. import abi
from ..engine import OfflinePreflight
from ..trust import SyntheticTrust,verify_identity_model,verify_review_ack
from ..transport import MockNativeTransport,NativeTransportUnavailable
from ..witness import LifecycleVerifier,SyntheticLifecycleOracle
from ..protocol import *
from ..contracts import *
from ..journal import accepted_workspace
from . import fixtures as f
ROOT=None
KEYS=None
class PreflightTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.keys=KEYS
 def fresh(self,abi_name='win64'):
  root=ROOT.parent/(ROOT.name+'-case-'+uuid4().hex);b=f.make(root,self.keys,abi_name);return root,b
 def execute(self,b,root):
  label=uuid4().hex;(root/('CASE_INPUT-'+label+'.json')).write_bytes(canonical({'bundle':b,'public_test_trust':self.keys.bundle}));r=OfflinePreflight().run(b,SyntheticTrust(self.keys.bundle),root);(root/('CASE_RESULT-'+label+'.json')).write_bytes(canonical(r));return r
 def denied(self,r):self.assertIn(r['status'],{'BLOCKED','INDETERMINATE'});self.assertFalse(r['native_execution_authorized']);self.assertFalse(r['diagnostic_authorized']);self.assertEqual(r['gate2_final'],'BLOCKED');self.assertNotIn('identity',r);self.assertTrue(r['no_auto_next'])
 def test_positive_win64_full_signature_witness_abi(self):
  root,b=self.fresh();r=self.execute(b,root);self.assertEqual(r['status'],'RESOLVED_OFFLINE_IDENTITY_ONLY',r);self.assertEqual(len(r['trace']),10);self.assertFalse(r['atomic_snapshot']);self.assertEqual(r['witness']['native_coverage'],'UNKNOWN');self.assertFalse(r['root_contract']['native_acl_verified']);self.assertEqual(accepted_workspace(root).audit_attempt(b['issuer']['payload']['attempt_id'])['state'],r['status'])
 def test_positive_win32_full_signature_witness_abi(self):
  root,b=self.fresh('win32');r=self.execute(b,root);self.assertEqual(r['status'],'RESOLVED_OFFLINE_IDENTITY_ONLY',r);self.assertEqual(len(r['trace']),10)
 def test_witness_sequence_not_issuer_sequence(self):
  root,b=self.fresh();self.assertNotEqual(b['issuer']['payload']['issuer_sequence'],b['expected_pre']['sequence']);self.assertEqual(self.execute(b,root)['status'],'RESOLVED_OFFLINE_IDENTITY_ONLY')
 def test_native_dispatch_unavailable_even_with_signed_model(self):
  root,b=self.fresh()
  with self.assertRaisesRegex(RuntimeError,'NOT_AUTHORIZED'):NativeTransportUnavailable().dispatch(b['issuer'])
  self.denied(OfflinePreflight().run(b,SyntheticTrust(self.keys.bundle),root,NativeTransportUnavailable()))
 def test_transport_subclass_cannot_be_live_provider(self):
  class Bad(MockNativeTransport):pass
  root,b=self.fresh();self.denied(OfflinePreflight().run(b,SyntheticTrust(self.keys.bundle),root,Bad(b['transport'])))
 def test_engine_instance_no_retry(self):
  root,b=self.fresh();e=OfflinePreflight();self.assertEqual(e.run(b,SyntheticTrust(self.keys.bundle),root)['status'],'RESOLVED_OFFLINE_IDENTITY_ONLY');self.denied(e.run(b,SyntheticTrust(self.keys.bundle),root))
 def test_same_attempt_replay_fresh_engine(self):
  root,b=self.fresh();self.assertEqual(self.execute(b,root)['status'],'RESOLVED_OFFLINE_IDENTITY_ONLY');self.denied(self.execute(b,root))
 def test_nonce_replay_new_signed_attempt(self):
  root,b=self.fresh();self.assertEqual(self.execute(b,root)['status'],'RESOLVED_OFFLINE_IDENTITY_ONLY');other=f.make(root,self.keys);other['issuer']['payload']['nonce']=b['issuer']['payload']['nonce'];f.refresh(other,self.keys);self.denied(self.execute(other,root))
 def test_terminal_guard_no_further_reads(self):
  root,b=self.fresh();e=OfflinePreflight();self.assertEqual(e.run(b,SyntheticTrust(self.keys.bundle),root)['status'],'RESOLVED_OFFLINE_IDENTITY_ONLY')
  with self.assertRaisesRegex(Blocked,'NO_RETRY'):e.session.call(0)
 def test_independent_review_ack_no_promotion(self):
  root,b=self.fresh();trust=SyntheticTrust(self.keys.bundle);e=OfflinePreflight();r=e.run(b,trust,root);a=e.admission;p={'artifact_kind':REVIEW_KIND,'model_sha256':digest(a.payload),'evidence_sha256':digest(r),'scope_sha256':a.payload['scope_sha256'],'identity_sha256':r['identity_sha256'],'native_execution_authorized':False,'diagnostic_authorized':False};out=verify_review_ack(trust,self.keys.sign(REVIEW_KIND,p),r,a);self.assertFalse(out['native_execution_authorized']);self.assertFalse(out['diagnostic_authorized'])
 def test_ack_cross_model_scope_reject(self):
  root,b=self.fresh();trust=SyntheticTrust(self.keys.bundle);e=OfflinePreflight();r=e.run(b,trust,root);p={'artifact_kind':REVIEW_KIND,'model_sha256':'f'*64,'evidence_sha256':digest(r),'scope_sha256':r['scope_sha256'],'identity_sha256':r['identity_sha256'],'native_execution_authorized':False,'diagnostic_authorized':False}
  with self.assertRaisesRegex(Blocked,'EXACT_MODEL_RESULT'):verify_review_ack(trust,self.keys.sign(REVIEW_KIND,p),r,e.admission)
 def test_shared_public_key_roles_reject(self):
  value=copy.deepcopy(self.keys.bundle);value['keys'][1]['public_hex']=value['keys'][0]['public_hex']
  with self.assertRaisesRegex(Blocked,'SHARED'):SyntheticTrust(value)
 def test_trust_key_map_mutation_reject(self):
  trust=SyntheticTrust(self.keys.bundle);trust.keys[next(iter(trust.keys))]['public_hex']='00'*32;root,b=self.fresh();self.denied(OfflinePreflight().run(b,trust,root))
 def test_diagnostic_grant_not_identity_permit(self):
  root,b=self.fresh();b['issuer']=self.keys.sign(DIAGNOSTIC_KIND,b['issuer']['payload']);self.denied(self.execute(b,root))
 def test_production_trust_root_marker_reject(self):
  value=copy.deepcopy(self.keys.bundle);value['realm']='PRODUCTION'
  with self.assertRaises(Blocked):SyntheticTrust(value)
 def test_runtime_source_has_no_dll_loader_or_live_entry(self):
  forbidden={'ctypes','win32api','win32gui','winreg','subprocess','socket'}
  for name in RUNTIME_FILES:
   tree=ast.parse((HERE/name).read_bytes())
   for n in ast.walk(tree):
    if isinstance(n,(ast.Import,ast.ImportFrom)):
     modules=[v.name.split('.')[0] for v in n.names] if isinstance(n,ast.Import) else [(n.module or '').split('.')[0]];self.assertFalse(set(modules)&forbidden)
    if isinstance(n,ast.Call):self.assertNotIn(ast.unparse(n.func),{'eval','exec','compile','__import__','ctypes.WinDLL','ctypes.CDLL'})
    if isinstance(n,ast.If):self.assertNotIn('__name__',ast.unparse(n.test))
 def test_review_ack_revoked_signer_reject(self):
  root,b=self.fresh();b['revocation']['payload']['revoked_keys'].append(self.keys.private['REVIEW'][0]);f.refresh(b,self.keys);trust=SyntheticTrust(self.keys.bundle);e=OfflinePreflight();r=e.run(b,trust,root);self.assertEqual(r['status'],'RESOLVED_OFFLINE_IDENTITY_ONLY',r)
  p={'artifact_kind':REVIEW_KIND,'model_sha256':digest(e.admission.payload),'evidence_sha256':digest(r),'scope_sha256':r['scope_sha256'],'identity_sha256':r['identity_sha256'],'native_execution_authorized':False,'diagnostic_authorized':False}
  with self.assertRaisesRegex(Blocked,'REVOKED_REVIEW'):verify_review_ack(trust,self.keys.sign(REVIEW_KIND,p),r,e.admission)
 def test_review_ack_different_trust_root_reject(self):
  root,b=self.fresh();e=OfflinePreflight();r=e.run(b,SyntheticTrust(self.keys.bundle),root);other=f.TestKeys();p={'artifact_kind':REVIEW_KIND,'model_sha256':r['model_sha256'],'evidence_sha256':digest(r),'scope_sha256':r['scope_sha256'],'identity_sha256':r['identity_sha256'],'native_execution_authorized':False,'diagnostic_authorized':False}
  with self.assertRaisesRegex(Blocked,'TRUST_BINDING'):verify_review_ack(SyntheticTrust(other.bundle),other.sign(REVIEW_KIND,p),r,e.admission)
 def test_concurrent_same_nonce_only_one_admission(self):
  root,a=self.fresh();b=f.make(root,self.keys);b['issuer']['payload']['nonce']=a['issuer']['payload']['nonce'];f.refresh(b,self.keys);barrier=threading.Barrier(2);results=[]
  def run(bundle):barrier.wait(timeout=10);results.append(self.execute(bundle,root))
  threads=[threading.Thread(target=run,args=(value,)) for value in [a,b]]
  for thread in threads:thread.start()
  for thread in threads:thread.join(timeout=30);self.assertFalse(thread.is_alive())
  self.assertEqual(len(results),2);self.assertLessEqual(sum(r['status']=='RESOLVED_OFFLINE_IDENTITY_ONLY' for r in results),1);self.assertGreaterEqual(sum(r['status'] in {'BLOCKED','INDETERMINATE'} for r in results),1)
 def test_schema_and_code_identity_bound_to_actual_bytes(self):
  root,b=self.fresh();self.assertEqual(b['issuer']['payload']['tool_sha256'],code_identity());self.assertEqual(b['issuer']['payload']['schema_sha256'],schema_identity())
 def test_transport_mutation_before_read_is_rejected(self):
  root,b=self.fresh();transport=MockNativeTransport(b['transport']);transport.data['frames'][0]['subject']['pid']+=1;self.denied(OfflinePreflight().run(b,SyntheticTrust(self.keys.bundle),root,transport))
 def test_signed_host_parent_change_external_pin_reject(self):
  root,b=self.fresh();pin=b['expected']['host_sha256'];b['host']['payload']['parent_pid']+=1;b['host']['payload']['parent_creation']+=1;f.refresh(b,self.keys);b['expected']['host_sha256']=pin;self.denied(self.execute(b,root))
 def test_valid_parent_is_attestation_only_not_native_proof(self):
  root,b=self.fresh();r=self.execute(b,root);self.assertEqual(r['status'],'RESOLVED_OFFLINE_IDENTITY_ONLY');self.assertIn('TRUSTED_HOST_BOOT_OPERATOR_PROVENANCE',r['runtime_blockers']);self.assertEqual(r['gate2_final'],'BLOCKED')

def mutate_model(edit):
 def test(self):
  root,b=self.fresh();edit(b['issuer']['payload']);f.refresh(b,self.keys);self.denied(self.execute(b,root))
 return test
MODEL_NEGATIVES=[('live_marker',lambda m:m.update(artifact_kind='LIVE_PERMIT')),('diagnostic_stage',lambda m:m.update(stage='DIAGNOSTIC')),('native_flag',lambda m:m.update(native_execution_authorized=True)),('diagnostic_flag',lambda m:m.update(diagnostic_authorized=True)),('tool_pin',lambda m:m.update(tool_sha256='f'*64)),('schema_pin',lambda m:m.update(schema_sha256='f'*64)),('expired',lambda m:m.update(expires_utc_ns=10_000_000_000)),('future_issue',lambda m:m.update(issued_utc_ns=10_000_000_001)),('overlong_validity',lambda m:m.update(expires_utc_ns=100_000_000_000)),('bool_issuer_sequence',lambda m:m.update(issuer_sequence=True)),('float_max_calls',lambda m:m['scope'].update(max_calls=32.0)),('scope_rights',lambda m:m['scope']['boundary']['rights'].update(process=2035711)),('title_scope',lambda m:m['scope']['boundary'].update(no_title_reads=False)),('real_target',lambda m:m['scope']['target'].update(executable_path=r'C:\Windows\System32\cmd.exe')),('outside_root',lambda m:m.update(workspace=r'D:\R1-20261015-01')),('unknown_field',lambda m:m.update(extra=True)),('bool_session',lambda m:m['scope']['target'].update(session=True)),('alias_handle',lambda m:m['scope']['target'].update(hwnd=True))]
for name,edit in MODEL_NEGATIVES:setattr(PreflightTests,'test_model_'+name,mutate_model(edit))

def frame_negative(edit,index=0):
 def test(self):
  root,b=self.fresh();edit(b['transport']['frames'][index]);f.refresh(b,self.keys);self.denied(self.execute(b,root))
 return test
FRAME_NEGATIVES=[('api',lambda r:r.update(api='ReadProcessMemory')),('field',lambda r:r.update(fields=['title'])),('rights',lambda r:r['rights'].update(token=983551)),('pid',lambda r:r['subject'].update(pid=999)),('bool_argument',lambda r:r['args'].update(handle=True)),('foreign_handle',lambda r:r['args'].update(handle=55555)),('bad_info_class',lambda r:r['args'].update(info_class=99)),('error',lambda r:r.update(status='ERROR',last_error=5)),('unknown',lambda r:r.update(status='UNKNOWN')),('negative_tick',lambda r:r.update(start_tick=-1)),('bool_tick',lambda r:r.update(end_tick=True)),('timeout',lambda r:r.update(end_tick=100000)),('raw_bool',lambda r:r.update(return_hex=True)),('raw_short',lambda r:r.update(return_hex='01')),('last_error_bool',lambda r:r.update(last_error=False)),('unknown_frame_field',lambda r:r.update(extra=1)),('owner',lambda r:r['allocations'][0].update(owner='SYNTHETIC-OTHER')),('initialized_tail',lambda r:r['allocations'][0].update(initialized=1)),('capacity',lambda r:r['allocations'][0].update(capacity=1)),('pointer_overflow',lambda r:r['allocations'][0].update(base=2**64-4)),('pointer_null',lambda r:r['allocations'][0].update(base=0))]
for name,edit in FRAME_NEGATIVES:setattr(PreflightTests,'test_frame_'+name,frame_negative(edit))

def signature_negative(key,edit):
 def test(self):
  root,b=self.fresh();edit(b[key]);self.denied(self.execute(b,root))
 return test
for key in ['issuer','host','revocation','witness','anchor']:
 for name,edit in [('tamper',lambda e:e['payload'].update(tamper=True)),('signature',lambda e:e.update(signature_hex='00'*64)),('bool_version',lambda e:e.update(version=True)),('foreign_realm',lambda e:e.update(realm='PRODUCTION')),('wrong_role',lambda e:e.update(role='DIAGNOSTIC'))]:setattr(PreflightTests,'test_signature_'+key+'_'+name,signature_negative(key,edit))

def host_negative(field,value):
 def test(self):
  root,b=self.fresh();b['host']['payload'][field]=value;f.refresh(b,self.keys);self.denied(self.execute(b,root))
 return test
for name,field,value in [('host','host','SYNTHETIC-OTHER'),('boot','boot','SYNTHETIC-OTHER'),('session','session',2),('desktop','desktop','Other'),('station','station','Other'),('operator','operator_sid','S-1-5-21-999'),('parent_bool','parent_pid',True),('parent_missing_time','parent_creation',0),('observer_missing_time','observer_creation',0),('operator_not_high','operator_token',{'elevated':True,'elevation_type':2,'integrity_sid':'S-1-16-8192','admin_enabled':True,'deny_only':False})]:setattr(PreflightTests,'test_host_'+name,host_negative(field,value))

def revocation_negative(role=None,nonce=False,attempt=False):
 def test(self):
  root,b=self.fresh();rev=b['revocation']['payload']
  if role:rev['revoked_keys'].append(self.keys.private[role][0])
  if nonce:rev['revoked_nonces'].append(b['issuer']['payload']['nonce'])
  if attempt:rev['revoked_attempts'].append(b['issuer']['payload']['attempt_id'])
  f.refresh(b,self.keys);self.denied(self.execute(b,root))
 return test
for role in ['ISSUER','HOST','REVOCATION','WITNESS','ANCHOR']:setattr(PreflightTests,'test_revoked_'+role.lower(),revocation_negative(role))
setattr(PreflightTests,'test_revoked_nonce',revocation_negative(nonce=True));setattr(PreflightTests,'test_revoked_attempt',revocation_negative(attempt=True))

def witness_negative(edit):
 def test(self):
  root,b=self.fresh();edit(b);f.refresh(b,self.keys);self.denied(self.execute(b,root))
 return test
WITNESS_NEGATIVES=[('native_source',lambda b:b['witness']['payload'].update(source='WinEvent')),('loss',lambda b:b['witness']['payload'].update(loss=1)),('bool_loss',lambda b:b['witness']['payload'].update(loss=False)),('duplicate_create',lambda b:b['witness']['payload']['events'][1].update(kind='CREATE')),('missing',lambda b:b['witness']['payload'].update(events=b['witness']['payload']['events'][:1])),('reorder',lambda b:b['witness']['payload']['events'].reverse()),('generation',lambda b:b['witness']['payload']['events'][1]['identity'].update(generation=8)),('sequence',lambda b:b['witness']['payload']['events'][1].update(sequence=101)),('prefix',lambda b:b['expected_pre'].update(sequence=96)),('head',lambda b:b['expected_pre'].update(head='b'*64)),('anchor_scope',lambda b:b['anchor']['payload'].update(scope_sha256='0'*64)),('anchor_final',lambda b:b['anchor']['payload'].update(final_head='0'*64)),('truncated_coverage',lambda b:b['witness']['payload'].update(end_tick=150)),('untrusted_oracle',lambda b:b['oracle'].update(source='ETW_LOSSLESS')),('oracle_diff',lambda b:b['oracle']['events'][1].update(kind='DESTROY'))]
for name,edit in WITNESS_NEGATIVES:setattr(PreflightTests,'test_witness_'+name,witness_negative(edit))

def fully_signed_witness_negative(edit,reason):
 def test(self):
  root,b=self.fresh();edit(b['oracle']);events=b['oracle']['events'];final=f.rehead(events);b['witness']['payload'].update(events=copy.deepcopy(events),oracle_sha256=digest(b['oracle']),begin_tick=b['oracle']['begin_tick'],end_tick=b['oracle']['end_tick']);b['anchor']['payload'].update(oracle_sha256=digest(b['oracle']),final_head=final,final_sequence=events[-1]['sequence']);f.refresh(b,self.keys);r=self.execute(b,root);self.denied(r);self.assertIn(reason,r['reason'],r)
 return test
SIGNED_CONTRADICTIONS=[('duplicate_create',lambda o:o['events'][1].update(kind='CREATE'),'DUPLICATE_CREATE'),('destroy',lambda o:o['events'][1].update(kind='DESTROY'),'DUPLICATE_CREATE'),('unknown',lambda o:o['events'][1].update(kind='UNKNOWN'),'DUPLICATE_CREATE'),('first_unchanged',lambda o:o['events'][0].update(kind='UNCHANGED'),'DUPLICATE_CREATE'),('sequence_gap',lambda o:o['events'][1].update(sequence=100),'SEQUENCE_REORDER'),('sequence_bool',lambda o:o['events'][1].update(sequence=True),'SEQUENCE_REORDER'),('reorder_ticks',lambda o:o['events'][1].update(tick=1),'SEQUENCE_REORDER'),('tick_outside_interval',lambda o:o['events'][1].update(tick=10001),'SEQUENCE_REORDER'),('sequence_uint64_overflow',lambda o:o['events'][1].update(sequence=2**64),'SEQUENCE_REORDER'),('generation',lambda o:o['events'][1]['identity'].update(generation=8),'IDENTITY_GENERATION'),('pid_reuse',lambda o:o['events'][1]['identity'].update(creation=134366334000001001),'IDENTITY_GENERATION'),('hwnd_replacement',lambda o:o['events'][1]['identity'].update(hwnd=0x2200),'IDENTITY_GENERATION'),('tid_replacement',lambda o:o['events'][1]['identity'].update(tid=1003),'IDENTITY_GENERATION'),('file_identity',lambda o:o['events'][1]['identity'].update(file_id='33'*16),'IDENTITY_GENERATION')]
for name,edit,reason in SIGNED_CONTRADICTIONS:setattr(PreflightTests,'test_signed_oracle_'+name,fully_signed_witness_negative(edit,reason))

def expected_negative(field,value):
 def test(self):
  root,b=self.fresh();b['expected'][field]=value;self.denied(self.execute(b,root))
 return test
for name,field,value in [('revocation_epoch_bool','revocation_epoch',True),('revocation_rollback','revocation_epoch',4),('revocation_head','revocation_sha256','f'*64),('host_pin','host_sha256','f'*64),('scope_pin','scope_sha256','f'*64),('transport_pin','transport_sha256','f'*64),('utc_bool','now_utc_ns',True),('utc_change','now_utc_ns',10000000001)]:setattr(PreflightTests,'test_external_'+name,expected_negative(field,value))

def revocation_fields_negative(edit):
 def test(self):
  root,b=self.fresh();edit(b['revocation']['payload']);f.refresh(b,self.keys);self.denied(self.execute(b,root))
 return test
for name,edit in [('expired',lambda p:p.update(expires_utc_ns=10000000000)),('future',lambda p:p.update(issued_utc_ns=10000000001)),('unknown_source',lambda p:p.update(source='LIVE')),('duplicate_key',lambda p:p.update(revoked_keys=['SYNTHETIC-X','SYNTHETIC-X'])),('numeric_key',lambda p:p.update(revoked_keys=[1])),('unknown_field',lambda p:p.update(extra=1))]:setattr(PreflightTests,'test_revocation_schema_'+name,revocation_fields_negative(edit))

def observed_bytes_negative(index,edit):
 def test(self):
  root,b=self.fresh();row=b['transport']['frames'][index]['allocations'][0];data=bytearray.fromhex(row['data_hex']);edit(data);row['data_hex']=data.hex();f.refresh(b,self.keys);r=self.execute(b,root);self.denied(r)
 return test
for name,index,edit in [('user_sid',0,lambda d:d.__setitem__(-1,1)),('admin_disabled',1,lambda d:d.__setitem__(slice(16,20),struct.pack('<I',0))),('admin_deny',1,lambda d:d.__setitem__(slice(16,20),struct.pack('<I',20))),('limited',2,lambda d:d.__setitem__(slice(0,4),struct.pack('<I',3))),('not_elevated',3,lambda d:d.__setitem__(slice(0,4),struct.pack('<I',0))),('medium',4,lambda d:d.__setitem__(slice(-4,None),struct.pack('<I',8192))),('pid',5,lambda d:d.__setitem__(slice(0,4),struct.pack('<I',999))),('class',6,lambda d:d.__setitem__(0,ord('!'))),('creation',7,lambda d:d.__setitem__(0,1)),('path',8,lambda d:d.__setitem__(0,ord('X'))),('file_sha',9,lambda d:d.__setitem__(0,ord('!')))]:setattr(PreflightTests,'test_observed_'+name,observed_bytes_negative(index,edit))

def ack_promotion_negative(field,value):
 def test(self):
  root,b=self.fresh();trust=SyntheticTrust(self.keys.bundle);e=OfflinePreflight();r=e.run(b,trust,root);r[field]=value;p={'artifact_kind':REVIEW_KIND,'model_sha256':r['model_sha256'],'evidence_sha256':digest(r),'scope_sha256':r['scope_sha256'],'identity_sha256':r['identity_sha256'],'native_execution_authorized':False,'diagnostic_authorized':False}
  with self.assertRaisesRegex(Blocked,'CANNOT_PROMOTE_RUNTIME'):verify_review_ack(trust,self.keys.sign(REVIEW_KIND,p),r,e.admission)
 return test
for name,field,value in [('native','native_execution_authorized',True),('diagnostic','diagnostic_authorized',True),('gate2','gate2_final','PASS'),('auto_next','no_auto_next',False),('atomic','atomic_snapshot',True)]:setattr(PreflightTests,'test_ack_promotion_'+name,ack_promotion_negative(field,value))

for name,data in [('duplicate_key',b'{"a":1,"a":2}'),('noncanonical',b'{ "a": 1 }'),('truncated',b'{"a":'),('numeric_alias',b'{"a":NaN}'),('utf8_error',b'\xff')]:
 def test(self,data=data):
  with self.assertRaises((Blocked,ValueError,UnicodeError)):decode(data)
 setattr(PreflightTests,'test_protocol_'+name,test)

def fs_negative(edit):
 def test(self):
  root,b=self.fresh();edit(b['filesystem']);self.denied(self.execute(b,root))
 return test
for name,edit in [('native_source',lambda p:p.update(source='NATIVE_ASSERTED_TRUSTED')),('owner',lambda p:p.update(owner_sid='S-1-5-18')),('inherited',lambda p:p.update(inherited_aces=1)),('unprotected',lambda p:p.update(dacl_protected=False)),('world_write',lambda p:p['aces'].append({'type':'ALLOW','sid':'S-1-1-0','rights':'FULL'})),('reparse',lambda p:p.update(reparse=True)),('race',lambda p:p['after_anchor'].update(file_id='33'*16)),('numeric_alias',lambda p:p['after_anchor'].update(volume=True))]:setattr(PreflightTests,'test_filesystem_'+name,fs_negative(edit))
