import ast,copy,hashlib,json,struct,unittest
from pathlib import Path
from uuid import uuid4
from gui_native_preflight.abi import HandleTable
from gui_native_preflight.protocol import Blocked,canonical,digest
from ..authority import SyntheticRoot,admit,review_ack,time_interval
from ..bindings import PROTOTYPES,SUPPORT_PROTOTYPES,FIELDS,RIGHTS,NativeBindingUnavailable,validate_request
from ..contracts import RUNTIME_FILES,HERE,blocked_runtime,PURPOSES
from ..wire import decode_frame,OfflineReadSession,SyntheticFrames
from ..witness import WitnessContract,verify_signed_witness
from . import fixtures as f
ROOT=None;KEYS=None

class ReadinessTests(unittest.TestCase):
    def fresh(self,abi='win64'):
        root=ROOT.parent/(ROOT.name+'-'+uuid4().hex[:8]);root.mkdir();return root,f.make(KEYS,abi,root)
    def admission(self,b,tick=100):return admit(KEYS.root(),b['envelopes'],b['expected'],tick)
    def execute(self,b,root):
        (root/'INPUT.json').write_bytes(canonical({'bundle':b,'public_test_root':KEYS.bundle}));session=OfflineReadSession(self.admission(b),SyntheticFrames(b['transport']),root);out=session.run();(root/'RESULT.json').write_bytes(canonical(out));return out,session
    def assert_blocked(self,b,root):
        try:out,s=self.execute(b,root)
        except (Blocked,ValueError,KeyError,TypeError):return
        self.assertEqual(out['status'],'INDETERMINATE',out);self.assertFalse(out['native_execution_authorized']);self.assertFalse(out['diagnostic_authorized']);self.assertEqual(out['gate2_final'],'BLOCKED');self.assertTrue(s.provider.sealed)
    def test_full21_api_wire_session_win64(self):
        root,b=self.fresh();out,s=self.execute(b,root);self.assertEqual(out['status'],'OFFLINE_WIRE_TRANSCRIPT_ONLY',out);self.assertEqual({v['request']['api'] for v in b['transport']['frames']},set(PROTOTYPES));self.assertEqual(len(out['decoded']),len(b['transport']['frames']));self.assertTrue(s.provider.sealed);self.assertEqual(s.workspace.audit_attempt(s.admission.permit['attempt_id'])['state'],'BLOCKED');self.assertFalse(out['native_execution_authorized']);self.assertFalse(out['atomic_snapshot'])
    def test_full21_api_wire_session_win32(self):
        root,b=self.fresh('win32');out,s=self.execute(b,root);self.assertEqual(out['status'],'OFFLINE_WIRE_TRANSCRIPT_ONLY',out)
    def test_nonce_replay_new_attempt_denied(self):
        root,b=self.fresh();out,s=self.execute(b,root);self.assertEqual(out['status'],'OFFLINE_WIRE_TRANSCRIPT_ONLY');other=f.make(KEYS,root=root);other['envelopes']['ISSUER']['payload']['nonce']=s.admission.permit['nonce'];f.refresh(other,KEYS)
        with self.assertRaises(Exception):OfflineReadSession(self.admission(other),SyntheticFrames(other['transport']),root)
    def test_session_no_resume_or_retry(self):
        root,b=self.fresh();out,s=self.execute(b,root)
        with self.assertRaisesRegex(Blocked,'NO_RETRY'):s.run()
        with self.assertRaisesRegex(Blocked,'SEALED'):s.provider.take(0)
    def test_scope_root_cannot_be_relocated(self):
        root,b=self.fresh();other=ROOT.parent/(ROOT.name+'-'+uuid4().hex[:8]);other.mkdir()
        with self.assertRaisesRegex(Blocked,'WORKSPACE_BINDING'):OfflineReadSession(self.admission(b),SyntheticFrames(b['transport']),other)
    def test_mock_subclass_and_native_entry_rejected(self):
        class Injected(SyntheticFrames):pass
        root,b=self.fresh()
        with self.assertRaisesRegex(Blocked,'NO_NATIVE'):OfflineReadSession(self.admission(b),Injected(b['transport']),root)
        with self.assertRaisesRegex(RuntimeError,'NOT_AUTHORIZED'):NativeBindingUnavailable().bind(b)
    def test_unsigned_expected_root_rejected(self):
        root,b=self.fresh();bundle=copy.deepcopy(KEYS.bundle);bundle['source']='PRODUCTION'
        with self.assertRaises(Blocked):SyntheticRoot(bundle,digest(bundle))
    def test_independent_roles_cannot_share_key(self):
        bundle=copy.deepcopy(KEYS.bundle);bundle['keys'][1]['public_hex']=bundle['keys'][0]['public_hex']
        with self.assertRaisesRegex(Blocked,'INDEPENDENT_KEY'):SyntheticRoot(bundle,digest(bundle))
    def test_clock_uncertainty_entire_interval_required(self):
        root,b=self.fresh();b['envelopes']['CLOCK']['payload']['latest_utc_ns']=b['envelopes']['ISSUER']['payload']['expires_utc_ns'];f.refresh(b,KEYS)
        with self.assertRaisesRegex(Blocked,'UNCERTAINTY'):self.admission(b)
    def test_clock_no_rollback_after_admission(self):
        root,b=self.fresh();a=self.admission(b);a.check(110)
        with self.assertRaisesRegex(Blocked,'ROLLBACK'):a.check(109)
    def test_review_ack_exact_and_nonpromoting(self):
        root,b=self.fresh();out,s=self.execute(b,root);a=s.admission;p={'artifact_kind':PURPOSES['REVIEW'],'permit_sha256':digest(a.permit),'scope_sha256':a.permit['scope_sha256'],'evidence_sha256':digest(out),'native_execution_authorized':False,'diagnostic_authorized':False};ack=review_ack(a,KEYS.sign('REVIEW',p),out,a.last_tick);self.assertFalse(ack['native_execution_authorized']);self.assertFalse(ack['diagnostic_authorized'])
    def test_review_ack_unknown_evidence_rejected(self):
        root,b=self.fresh();out,s=self.execute(b,root);out['status']='INDETERMINATE';a=s.admission;p={'artifact_kind':PURPOSES['REVIEW'],'permit_sha256':digest(a.permit),'scope_sha256':a.permit['scope_sha256'],'evidence_sha256':digest(out),'native_execution_authorized':False,'diagnostic_authorized':False}
        with self.assertRaisesRegex(Blocked,'UNKNOWN_PROMOTION'):review_ack(a,KEYS.sign('REVIEW',p),out,a.last_tick)
    def test_review_ack_revoked_reviewer_reject(self):
        root,b=self.fresh();b['envelopes']['REVOCATION']['payload']['revoked_keys']=[KEYS.private['REVIEW'][0]];f.refresh(b,KEYS);out,s=self.execute(b,root);a=s.admission;p={'artifact_kind':PURPOSES['REVIEW'],'permit_sha256':digest(a.permit),'scope_sha256':a.permit['scope_sha256'],'evidence_sha256':digest(out),'native_execution_authorized':False,'diagnostic_authorized':False}
        with self.assertRaisesRegex(Blocked,'REVOKED_REVIEWER'):review_ack(a,KEYS.sign('REVIEW',p),out,a.last_tick)
    def test_identity_review_and_diagnostic_role_separation(self):
        root,b=self.fresh();b['envelopes']['ISSUER']=KEYS.sign('DIAGNOSTIC',b['envelopes']['ISSUER']['payload'])
        with self.assertRaisesRegex(Blocked,'AUTHORITY_SEPARATION'):self.admission(b)
    def test_witness_signed_independent_ack_positive(self):
        root,b=self.fresh();a=self.admission(b);prefix,obs=f.lifecycle();ack={'source':'SYNTHETIC_INDEPENDENT_EXTERNAL_HEAD_ACK','permit_sha256':digest(a.permit),'scope_sha256':a.permit['scope_sha256'],'prefix_sha256':digest(prefix),'observation_sha256':digest(obs)};out=verify_signed_witness(a,KEYS.sign('WITNESS',obs),KEYS.sign('EXTERNAL',ack),prefix,100);self.assertEqual(out['state'],'OFFLINE_SYNTHETIC_WITNESS_ONLY');self.assertEqual(out['RT-04'],'BLOCKED');self.assertNotEqual(a.permit['issuer_sequence'],prefix['sequence'])
    def test_runtime_has_no_live_entry_or_native_loader(self):
        forbidden={'ctypes','win32api','win32gui','winreg','socket','subprocess'}
        for name in RUNTIME_FILES:
            tree=ast.parse((HERE/name).read_bytes())
            for node in ast.walk(tree):
                if isinstance(node,(ast.Import,ast.ImportFrom)):
                    modules=[v.name.split('.')[0] for v in node.names] if isinstance(node,ast.Import) else [(node.module or '').split('.')[0]];self.assertFalse(set(modules)&forbidden)
                if isinstance(node,ast.Call):self.assertNotIn(ast.unparse(node.func),{'eval','exec','compile','__import__','ctypes.WinDLL','ctypes.CDLL'})
                if isinstance(node,ast.If):self.assertNotIn('__name__',ast.unparse(node.test))
    def test_compile_only_source_has_no_execution_body(self):
        text=(HERE/'windows_abi_compile_only.cpp').read_text();self.assertIn('#include <windows.h>',text);self.assertEqual(text.count('ABI_CHECK('),29);self.assertNotIn('int main(',text);self.assertNotIn('LoadLibrary',text);self.assertNotIn('GetProcAddress',text)
    def test_support_compile_only_has_no_entry_and_is_separate(self):
        text=(HERE/'windows_support_compile_only.cpp').read_text();self.assertEqual(text.count('SUPPORT_CHECK('),13);self.assertNotIn('int main(',text);self.assertNotIn('LoadLibrary',text);self.assertFalse(set(PROTOTYPES)&set(SUPPORT_PROTOTYPES))
    def test_admission_cannot_be_mutated_between_reads(self):
        root,b=self.fresh();a=self.admission(b);a.permit['scope']['target_pid']=999
        with self.assertRaisesRegex(Blocked,'MUTATED'):a.check(101)
    def test_clock_ages_out_after_admission(self):
        root,b=self.fresh();b['envelopes']['CLOCK']['payload']['max_age_ns']=1;f.refresh(b,KEYS);a=self.admission(b)
        with self.assertRaisesRegex(Blocked,'CLOCK_ROLLBACK_AGE'):a.check(102)
    def test_opened_evidence_root_and_transport_nonce_replay_guard(self):
        root,b=self.fresh();a=self.admission(b);p=SyntheticFrames(b['transport']);s=OfflineReadSession(a,p,root);out=s.run();self.assertEqual(out['status'],'OFFLINE_WIRE_TRANSCRIPT_ONLY')
        with self.assertRaises(Blocked):OfflineReadSession(self.admission(b),SyntheticFrames(b['transport']),root)
    def test_readfile_cannot_precede_all_file_metadata(self):
        root,b=self.fresh();b['transport']['frames']=[r for r in b['transport']['frames'] if r['request']['api']!='GetFileInformationByHandleEx'];f.refresh(b,KEYS);out,s=self.execute(b,root);self.assertEqual(out['status'],'INDETERMINATE');self.assertIn('METADATA_BEFORE',out['reason'])
    def test_multiple_file_acquisitions_rejected(self):
        root,b=self.fresh();index=next(i for i,v in enumerate(b['transport']['frames']) if v['request']['api']=='CreateFileW');row=copy.deepcopy(b['transport']['frames'][index]);row['start_tick']+=3;row['end_tick']+=3;b['transport']['frames'].insert(index+1,row);f.refresh(b,KEYS);out,s=self.execute(b,root);self.assertEqual(out['status'],'INDETERMINATE');self.assertIn('NO_REOPEN',out['reason'])
    def test_journal_denial_boundary_preserves_reason_and_zero_reads(self):
        root,b=self.fresh();out,s=self.execute(b,root);provider=SyntheticFrames(b['transport'])
        with self.assertRaisesRegex(Blocked,'ATTEMPT_OR_NONCE_REPLAY_NO_RESUME'):OfflineReadSession(self.admission(b),provider,root)
        self.assertEqual(provider.next,0);self.assertEqual(out['gate2_final'],'BLOCKED')

def api_positive(api,arch):
    def test(self):
        root,b=self.fresh(arch);plan=next(r for r in b['transport']['frames'] if r['request']['api']==api);table=HandleTable(arch,b['envelopes']['ISSUER']['payload']['attempt_id'])
        if api=='CloseHandle':table.register(0x5300,'file',1)
        result=decode_frame(plan['request'],plan['receipt'],table.owner,table);self.assertEqual(set(result),set(FIELDS[api]))
    return test
for api in PROTOTYPES:
    for arch in ['win32','win64']:setattr(ReadinessTests,'test_wire_'+api+'_'+arch,api_positive(api,arch))

for api in SUPPORT_PROTOTYPES:
    def reject_support(self,api=api):
        with self.assertRaisesRegex(Blocked,'API_NOT_ALLOWED'):validate_request({'api':api,'abi':'win64','args':{},'fields':[],'rights':dict(RIGHTS)})
    setattr(ReadinessTests,'test_support_api_cannot_enter_identity_scope_'+api,reject_support)

def authority_negative(edit):
    def test(self):
        root,b=self.fresh();edit(b);f.refresh(b,KEYS)
        with self.assertRaises((Blocked,ValueError,TypeError,KeyError)):self.admission(b)
    return test
for name,edit in [
 ('permit_true',lambda b:b['envelopes']['ISSUER']['payload'].update(native_execution_authorized=True)),
 ('diagnostic_true',lambda b:b['envelopes']['ISSUER']['payload'].update(diagnostic_authorized=True)),
 ('sequence_alias',lambda b:b['envelopes']['ISSUER']['payload'].update(issuer_sequence=True)),
 ('sequence_gap',lambda b:b['envelopes']['ISSUER']['payload'].update(issuer_sequence=502)),
 ('previous_head',lambda b:b['expected'].update(previous_head='f'*64)),
 ('root_pin',lambda b:b['expected'].update(root_sha256='f'*64)),
 ('tool_pin',lambda b:b['envelopes']['ISSUER']['payload'].update(tool_sha256='f'*64)),
 ('schema_pin',lambda b:b['envelopes']['ISSUER']['payload'].update(schema_sha256='f'*64)),
 ('unknown_field',lambda b:b['envelopes']['ISSUER']['payload'].update(extra=1)),
 ('real_marker',lambda b:b['envelopes']['ISSUER']['payload'].update(artifact_kind='LIVE_PERMIT')),
 ('host',lambda b:b['envelopes']['HOST']['payload'].update(host='SYNTHETIC-OTHER')),
 ('boot',lambda b:b['envelopes']['BOOT']['payload'].update(boot='SYNTHETIC-OTHER')),
 ('session_alias',lambda b:b['envelopes']['HOST']['payload'].update(session=True)),
 ('parent_restart',lambda b:b['envelopes']['PARENT']['payload'].update(parent_creation=10)),
 ('observer_restart',lambda b:b['envelopes']['PARENT']['payload'].update(observer_creation=10)),
 ('operator',lambda b:b['envelopes']['OPERATOR']['payload'].update(operator_sid='S-1-5-18')),
 ('operator_low',lambda b:b['envelopes']['OPERATOR']['payload'].update(high_integrity=False)),
 ('native_source',lambda b:b['envelopes']['PARENT']['payload'].update(source='NATIVE_ASSERTED')),
 ('clock_expiry',lambda b:b['envelopes']['CLOCK']['payload'].update(max_age_ns=0)),
 ('clock_native',lambda b:b['envelopes']['CLOCK']['payload'].update(source='SYSTEM_WALL_CLOCK')),
 ('clock_bounds',lambda b:b['envelopes']['CLOCK']['payload'].update(earliest_utc_ns=10000000002)),
 ('revocation_stale',lambda b:b['envelopes']['REVOCATION']['payload'].update(expires_utc_ns=10000000000)),
 ('revocation_alias',lambda b:b['envelopes']['REVOCATION']['payload'].update(epoch=True)),
 ('revocation_duplicate',lambda b:b['envelopes']['REVOCATION']['payload'].update(revoked_keys=['x','x'])),
 ('nonce_revoked',lambda b:b['envelopes']['REVOCATION']['payload'].update(revoked_nonces=[b['envelopes']['ISSUER']['payload']['nonce']])),
 ('attempt_revoked',lambda b:b['envelopes']['REVOCATION']['payload'].update(revoked_attempts=[b['envelopes']['ISSUER']['payload']['attempt_id']]))
]:setattr(ReadinessTests,'test_authority_'+name,authority_negative(edit))

for role in ['ISSUER','HOST','BOOT','OPERATOR','PARENT','CLOCK','REVOCATION']:
    def revoked(self,role=role):
        root,b=self.fresh();b['envelopes']['REVOCATION']['payload']['revoked_keys']=[KEYS.private[role][0]];f.refresh(b,KEYS)
        with self.assertRaisesRegex(Blocked,'REVOKED'):self.admission(b)
    def tampered(self,role=role):
        root,b=self.fresh();b['envelopes'][role]['signature_hex']='00'*64
        with self.assertRaises(Exception):self.admission(b)
    setattr(ReadinessTests,'test_revoked_role_'+role,revoked);setattr(ReadinessTests,'test_signature_tamper_'+role,tampered)

def frame_negative(api,edit,reason=None):
    def test(self):
        root,b=self.fresh();row=next(r for r in b['transport']['frames'] if r['request']['api']==api);edit(row);f.refresh(b,KEYS);out,s=self.execute(b,root);self.assertEqual(out['status'],'INDETERMINATE',out);self.assertTrue(s.provider.sealed)
        if reason:self.assertIn(reason,out['reason'])
    return test
for name,api,edit,reason in [
 ('api','GetClassNameW',lambda r:r['request'].update(api='GetWindowTextW'),'API_NOT_ALLOWED'),
 ('field','GetClassNameW',lambda r:r['request'].update(fields=['title']),'READ_SCOPE'),
 ('rights','OpenProcess',lambda r:r['request']['args'].update(access=2035711),'PROCESS_QUERY'),
 ('hwnd_reuse','IsWindow',lambda r:r['request']['args'].update(hwnd=0x2200),'HWND_SCOPE'),
 ('pid_reuse','OpenProcess',lambda r:r['request']['args'].update(pid=1003),'PROCESS_SCOPE'),
 ('read_before_open','GetClassNameW',lambda r:r['request'].update(api='GetProcessTimes',args={'handle':123},fields=list(FIELDS['GetProcessTimes'])),'HANDLE_NOT_ACQUIRED'),
 ('title_injection','GetUserObjectInformationW',lambda r:r['request']['args'].update(index=4),'UOI_NAME_ONLY'),
 ('partial_enum','EnumWindows',lambda r:r['receipt']['outputs'].update(complete=False),'INCOMPLETE'),
 ('last_error','GetClassNameW',lambda r:r['receipt'].update(last_error=5),'API_ERROR'),
 ('bool_last_error','GetClassNameW',lambda r:r['receipt'].update(last_error=False),'API_ERROR'),
 ('timeout','GetClassNameW',lambda r:r.update(end_tick=r['start_tick']+101),'TIMEOUT'),
 ('bool_tick','GetClassNameW',lambda r:r.update(end_tick=True),'TIMEOUT'),
 ('subject','GetClassNameW',lambda r:r.update(subject_sha256='f'*64),'SUBJECT_CHANGED'),
 ('owner','GetClassNameW',lambda r:r['receipt']['allocations'][0].update(owner='SYNTHETIC-OTHER'),'BUFFER_ID_OWNER'),
 ('uninitialized','GetClassNameW',lambda r:r['receipt']['allocations'][0].update(initialized=1),'UTF16_LENGTH'),
 ('pointer_overflow','GetClassNameW',lambda r:r['receipt']['allocations'][0].update(base=2**64-1),'POINTER_OVERFLOW'),
 ('file_id','GetFileInformationByHandleEx',lambda r:r['receipt']['allocations'][0].update(data_hex=(struct.pack('<Q',17)+bytes.fromhex('22'*16)).hex()),'FILE_ID_MISMATCH'),
 ('bad_file_offset','ReadFile',lambda r:r['request']['args'].update(offset=1),'CONTIGUOUS_READ'),
 ('file_sha','ReadFile',lambda r:r['receipt']['allocations'][0].update(data_hex=(b'!'+f.DATA[1:]).hex()),'SHA_MISMATCH'),
 ('borrowed_close','CloseHandle',lambda r:r['request']['args'].update(handle=0x6100,kind='station'),'OWNED_CLOSE_ONLY')
]:setattr(ReadinessTests,'test_negative_frame_'+name,frame_negative(api,edit,reason))

for expiry,calls in [(1,0),(2,1),(11,1),(292,30)]:
    def test(self,expiry=expiry,calls=calls):
        root,b=self.fresh();b['envelopes']['REVOCATION']['payload']['expires_utc_ns']=10000000000+expiry;f.refresh(b,KEYS)
        if expiry==1:
            with self.assertRaises(Blocked):self.admission(b)
        else:
            out,s=self.execute(b,root);self.assertEqual(out['status'],'INDETERMINATE');self.assertIn('EXPIRY',out['reason']);self.assertTrue(s.provider.sealed)
    setattr(ReadinessTests,'test_revocation_expiry_'+str(expiry),test)
