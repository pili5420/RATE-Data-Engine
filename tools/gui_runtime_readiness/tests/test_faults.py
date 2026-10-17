import copy,os,struct,unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4
from gui_native_preflight.protocol import Blocked,digest
from ..containment import ContainmentModel,extended_job_limits,JOB_FLAGS
from ..filesystem import PrivateEvidenceStore,validate_descriptor,inspect_private_file
from ..witness import WitnessContract,verify_signed_witness
from ..authority import admit
from . import fixtures as f
from . import test_readiness as core

class FaultTests(unittest.TestCase):
    def root(self):
        p=core.ROOT.parent/(core.ROOT.name+'-'+uuid4().hex[:8]);p.mkdir();return p
    def test_descriptor_owner_only_protected_dacl(self):
        out=validate_descriptor(f.descriptor_bytes().hex(),f.SID);self.assertEqual(out['state'],'OFFLINE_DESCRIPTOR_VALIDATED');self.assertFalse(out['native_acl_verified'])
    def test_actual_private_file_immutable(self):
        root=self.root();store=PrivateEvidenceStore(root);out=store.write_once('SYNTHETIC-first.json',{'only':'synthetic'});self.assertFalse(out['power_loss_durable']);self.assertFalse(out['native_acl_verified']);self.assertFalse(out['directory_handle_race_verified']);inspect_private_file(root/'SYNTHETIC-first.json')
        with self.assertRaises(FileExistsError):store.write_once('SYNTHETIC-first.json',{'changed':True})
        with self.assertRaisesRegex(Blocked,'NO_RETRY'):store.write_once('SYNTHETIC-second.json',{})
        self.assertEqual((root/'SYNTHETIC-first.json').read_bytes(),b'{"only":"synthetic"}')
    def test_actual_private_hardlink_is_rejected(self):
        root=self.root();p=root/'SYNTHETIC-file.json';p.write_bytes(b'{}');os.link(p,root/'SYNTHETIC-alias.json')
        with self.assertRaisesRegex(Blocked,'SINGLE_LINK'):inspect_private_file(p)
    def test_fsync_failure_keeps_partial_and_poisoned(self):
        root=self.root();store=PrivateEvidenceStore(root)
        with patch('gui_runtime_readiness.filesystem.os.fsync',side_effect=OSError('SYNTHETIC_FSYNC_FAULT')):
            with self.assertRaisesRegex(OSError,'FSYNC_FAULT'):store.write_once('SYNTHETIC-partial.json',{'partial':True})
        self.assertTrue((root/'SYNTHETIC-partial.json').exists())
        with self.assertRaisesRegex(Blocked,'NO_RETRY'):store.write_once('SYNTHETIC-new.json',{})
    def test_real_private_directory_replacement_is_detected(self):
        root=self.root();store=PrivateEvidenceStore(root);moved=root.with_name(root.name+'-moved');root.rename(moved);root.mkdir()
        with self.assertRaisesRegex(Blocked,'ROOT_REPLACED'):store.write_once('SYNTHETIC-forbidden.json',{})
        self.assertFalse((root/'SYNTHETIC-forbidden.json').exists())
    def test_root_restore_cannot_resume_failed_store(self):
        root=self.root();store=PrivateEvidenceStore(root);original=root.with_name(root.name+'-original');replacement=root.with_name(root.name+'-replacement');root.rename(original);root.mkdir()
        with self.assertRaisesRegex(Blocked,'ROOT_REPLACED'):store.write_once('SYNTHETIC-blocked.json',{})
        self.assertTrue(store.failed);root.rename(replacement);original.rename(root)
        with self.assertRaisesRegex(Blocked,'NO_RETRY'):store.write_once('SYNTHETIC-retry.json',{})
        self.assertFalse((root/'SYNTHETIC-retry.json').exists())
    def test_unavailable_root_poisoned_before_file_creation(self):
        root=self.root();store=PrivateEvidenceStore(root);root.rename(root.with_name(root.name+'-retained'))
        with self.assertRaises(FileNotFoundError):store.write_once('SYNTHETIC-blocked.json',{})
        self.assertTrue(store.failed)
        with self.assertRaisesRegex(Blocked,'NO_RETRY'):store.write_once('SYNTHETIC-retry.json',{})
    def test_production_root_rejected_before_io(self):
        with self.assertRaisesRegex(Blocked,'PRIVATE_EVIDENCE_ROOT'):PrivateEvidenceStore(r'D:\RATE-MH-Governance\R1-20261015-01')
    def test_path_traversal_ads_and_absolute_evidence_names_rejected(self):
        store=PrivateEvidenceStore(self.root())
        for name in ['../x.json','SYNTHETIC-x.json:stream',r'C:\x.json','sub/SYNTHETIC-x.json']:
            with self.assertRaisesRegex(Blocked,'BASENAME'):store.write_once(name,{})
    def test_job_layout_models_separate_x86_x64(self):
        self.assertEqual(extended_job_limits('win32')['extended_limit_size'],112);self.assertEqual(extended_job_limits('win64')['extended_limit_size'],144);self.assertFalse(extended_job_limits('win64')['native_qualified'])
    def drive(self,stop=None,edit=None):
        model=ContainmentModel('SYNTHETIC-'+uuid4().hex,100);events=[('JOB_CONFIGURED',{'flags':JOB_FLAGS,'active_process_limit':1,'inherit_job_handle':False,'job_nonce':'SYNTHETIC-JOB'}),('CHILD_SUSPENDED',{'pid':500,'creation':12345,'suspended':True,'inherited_handles':['SYNTHETIC-IPC-ONLY']}),('ASSIGNED',{'pid':500,'creation':12345,'job_nonce':'SYNTHETIC-JOB'}),('INTENT_DURABLE',{'attempt_id':model.attempt,'intent_sha256':'a'*64,'outside_head_sha256':'b'*64}),('RESUME',{'pid':500,'creation':12345}),('RESULT_AND_EXIT',{'pid':500,'creation':12345,'exit_code':0,'active_processes':0,'result_sha256':'c'*64,'external_ack_sha256':'d'*64})]
        for i,(kind,data) in enumerate(events):
            if stop is not None and i==stop:return model,events
            event={'source':'SYNTHETIC_SUPERVISOR_ORACLE','sequence':i+1,'previous_head':model.head,'tick':i+1,'kind':kind,'data':copy.deepcopy(data)}
            if edit:edit(i,event)
            model.event(event)
        return model,events
    def test_complete_job_transcript_remains_native_blocked(self):
        model,_=self.drive();self.assertEqual(model.state,'OFFLINE_TRANSCRIPT_COMPLETE');self.assertTrue(model.stopped)
        with self.assertRaisesRegex(Blocked,'NO_RESUME'):model.event({})
    def test_malformed_event_poison_no_retry(self):
        model=ContainmentModel('SYNTHETIC-'+uuid4().hex,100)
        with self.assertRaises(Blocked):model.event({})
        self.assertTrue(model.stopped);self.assertEqual(model.state,'UNKNOWN')
        with self.assertRaisesRegex(Blocked,'NO_RESUME'):model.event({})
    def test_witness_complete_synthetic_not_native(self):
        prefix,obs=f.lifecycle();out=WitnessContract(prefix).assess(obs);self.assertEqual(out['state'],'OFFLINE_SYNTHETIC_WITNESS_ONLY');self.assertEqual(out['RT-04'],'BLOCKED');self.assertFalse(out['atomic_snapshot'])
    def test_signed_witness_external_ack_cannot_transplant(self):
        b=f.make(core.KEYS);a=admit(core.KEYS.root(),b['envelopes'],b['expected'],100);prefix,obs=f.lifecycle();ack={'source':'SYNTHETIC_INDEPENDENT_EXTERNAL_HEAD_ACK','permit_sha256':'f'*64,'scope_sha256':a.permit['scope_sha256'],'prefix_sha256':digest(prefix),'observation_sha256':digest(obs)}
        with self.assertRaisesRegex(Blocked,'ACK_MODEL_SCOPE'):verify_signed_witness(a,core.KEYS.sign('WITNESS',obs),core.KEYS.sign('EXTERNAL',ack),prefix,100)

for source in ['WinEvent','ETW','HWND_BEFORE_AFTER','SIGNED_NATIVE_LABEL']:
    def native_unknown(self,source=source):
        prefix,obs=f.lifecycle();obs['source']=source;out=WitnessContract(prefix).assess(obs);self.assertEqual(out['state'],'INDETERMINATE');self.assertEqual(out['RT-04'],'BLOCKED');self.assertFalse(out['native_execution_authorized'])
    setattr(FaultTests,'test_native_witness_source_'+source,native_unknown)

for field in ['host','boot','clock_domain','generation','hwnd','pid','tid','creation']:
    def scope_negative(self,field=field):
        b=f.make(core.KEYS);a=admit(core.KEYS.root(),b['envelopes'],b['expected'],100);prefix,obs=f.lifecycle()
        if field in {'host','boot','clock_domain'}:prefix[field]=obs[field]='SYNTHETIC-OTHER'
        elif field=='generation':prefix[field]=8;[e.update(generation=8) for e in obs['events']]
        else:
            for event in obs['events']:event[field]+=1
        head=prefix['head']
        for event in obs['events']:event['previous_head']=head;head=digest(event)
        prefix.update(final_head=head,oracle_sha256=digest(obs['events']))
        ack={'source':'SYNTHETIC_INDEPENDENT_EXTERNAL_HEAD_ACK','permit_sha256':digest(a.permit),'scope_sha256':a.permit['scope_sha256'],'prefix_sha256':digest(prefix),'observation_sha256':digest(obs)}
        with self.assertRaisesRegex(Blocked,'WITNESS_(SCOPE|TARGET)'):verify_signed_witness(a,core.KEYS.sign('WITNESS',obs),core.KEYS.sign('EXTERNAL',ack),prefix,100)
    setattr(FaultTests,'test_signed_witness_cross_scope_'+field,scope_negative)

def descriptor_negative(edit):
    def test(self):
        data=bytearray(f.descriptor_bytes());edit(data)
        with self.assertRaises((Blocked,ValueError)):validate_descriptor(data.hex(),f.SID)
    return test
for name,edit in [('revision',lambda d:d.__setitem__(0,2)),('unprotected',lambda d:d.__setitem__(slice(2,4),struct.pack('<H',0x8004))),('null_dacl',lambda d:d.__setitem__(slice(16,20),bytes(4))),('owner_alias',lambda d:d.__setitem__(slice(4,8),struct.pack('<I',4))),('offset_overflow',lambda d:d.__setitem__(slice(16,20),struct.pack('<I',0xfffffffc))),('unknown_ace',lambda d:d.__setitem__(20+len(f.sid_bytes(f.SID))+8,5)),('inherited_ace',lambda d:d.__setitem__(20+len(f.sid_bytes(f.SID))+9,0x10)),('full_control',lambda d:d.__setitem__(slice(20+len(f.sid_bytes(f.SID))+12,20+len(f.sid_bytes(f.SID))+16),struct.pack('<I',0x1f01ff))),('wrong_trustee',lambda d:d.__setitem__(-1,1)),('truncated',lambda d:d.pop()),('trailing',lambda d:d.extend(b'\0'*4))]:setattr(FaultTests,'test_descriptor_'+name,descriptor_negative(edit))

def containment_negative(index,edit):
    def test(self):
        model,events=self.drive(stop=index);kind,data=events[index];event={'source':'SYNTHETIC_SUPERVISOR_ORACLE','sequence':index+1,'previous_head':model.head,'tick':index+1,'kind':kind,'data':copy.deepcopy(data)};edit(event)
        try:model.event(event)
        except (Blocked,ValueError,KeyError,TypeError):pass
        self.assertEqual(model.state,'UNKNOWN');self.assertTrue(model.stopped)
        with self.assertRaisesRegex(Blocked,'NO_RESUME'):model.event(event)
    return test
for name,index,edit in [('breakaway',0,lambda e:e['data'].update(flags=JOB_FLAGS|0x800)),('inherit_job',0,lambda e:e['data'].update(inherit_job_handle=True)),('unbounded_processes',0,lambda e:e['data'].update(active_process_limit=0)),('unsuspended',1,lambda e:e['data'].update(suspended=False)),('inherited_secret_handle',1,lambda e:e['data'].update(inherited_handles=['OTHER'])),('pid_reuse',2,lambda e:e['data'].update(creation=12346)),('wrong_job',2,lambda e:e['data'].update(job_nonce='SYNTHETIC-OTHER')),('resume_before_intent',3,lambda e:e.update(kind='RESUME',data={'pid':500,'creation':12345})),('intent_missing_hash',3,lambda e:e['data'].update(intent_sha256='unknown')),('resume_wrong_pid',4,lambda e:e['data'].update(pid=501)),('descendants_alive',5,lambda e:e['data'].update(active_processes=1)),('failed_exit',5,lambda e:e['data'].update(exit_code=1)),('exit_alias',5,lambda e:e['data'].update(exit_code=False)),('unknown_result',5,lambda e:e.update(kind='UNKNOWN_RESULT',data={})),('clock_rollback',5,lambda e:e.update(tick=1)),('sequence_gap',4,lambda e:e.update(sequence=7)),('sequence_alias',4,lambda e:e.update(sequence=True)),('head_tamper',4,lambda e:e.update(previous_head='f'*64)),('timeout_exact',5,lambda e:e.update(tick=100)),('cancel_then_late_success',5,lambda e:e.update(kind='CANCEL_REQUESTED',data={'pid':500,'creation':12345})),('crash',4,lambda e:e.update(kind='CRASH',data={})),('ipc_loss',4,lambda e:e.update(kind='IPC_LOSS',data={}))]:setattr(FaultTests,'test_containment_'+name,containment_negative(index,edit))

def witness_negative(edit,rebind=True):
    def test(self):
        prefix,obs=f.lifecycle();edit(prefix,obs)
        if rebind:
            head=prefix['head']
            for event in obs['events']:event['previous_head']=head;head=digest(event)
            prefix['final_head']=head;prefix['final_sequence']=obs['events'][-1]['sequence'];prefix['oracle_sha256']=digest(obs['events'])
        with self.assertRaises((Blocked,ValueError,KeyError,TypeError)):WitnessContract(prefix).assess(obs)
    return test
for name,edit,rebind in [('duplicate_create',lambda p,o:o['events'][1].update(kind='CREATE'),True),('destroy',lambda p,o:o['events'][1].update(kind='DESTROY'),True),('unknown',lambda p,o:o['events'][1].update(kind='UNKNOWN'),True),('sequence_gap',lambda p,o:o['events'][1].update(sequence=203),True),('generation',lambda p,o:o['events'][1].update(generation=8),True),('generation_alias',lambda p,o:o['events'][1].update(generation=True),True),('hwnd_reuse',lambda p,o:o['events'][1].update(hwnd=0x2200),True),('pid_restart',lambda p,o:o['events'][1].update(creation=134000000000001002),True),('lost_event',lambda p,o:o.update(events_lost=1),True),('lost_buffer',lambda p,o:o.update(buffers_lost=1),True),('loss_alias',lambda p,o:o.update(events_lost=False),True),('reordered',lambda p,o:o['events'][1].update(tick=99),True),('incomplete_interval',lambda p,o:o['events'][1].update(tick=999),True),('external_head',lambda p,o:p.update(final_head='f'*64),False),('oracle_mismatch',lambda p,o:p.update(oracle_sha256='f'*64),False),('unknown_source',lambda p,o:o.update(source='TRUST_ME'),True)]:setattr(FaultTests,'test_witness_'+name,witness_negative(edit,rebind))
