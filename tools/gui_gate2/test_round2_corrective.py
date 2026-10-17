"""Offline lifecycle, import, package and authority negatives; original223 are unchanged."""
import importlib.util,json,shutil,unittest,zipfile,zipimport
from pathlib import Path
from uuid import uuid4
P=Path(__file__).resolve().parent;WORK=None
def load(name,path):
    s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
f=load('round2_fixtures',P/'synthetic_fixtures.py');m=f.m;b=load('round2_boundary',P/'boundary_check.py')
class Round2Tests(unittest.TestCase):
    def blocked(self,r,reason):
        self.assertEqual(r['status'],'BLOCKED');self.assertIn(reason,r['reason']);self.assertFalse(r['native_execution_authorized']);self.assertTrue(r['no_retry']);self.assertIn('BLOCKED',r['gate2_final_status'])
    def root(self):p=WORK/('case-'+uuid4().hex);p.mkdir();return p
    def source(self):p=self.root()/'source';shutil.copytree(P,p);return p
    def test_valid_state_machine_still_resolves(self):
        g=f.grant();r=m.resolve_identity(g,f.resolution(g),m.AttemptJournal(),1000);self.assertEqual(r['status'],'RESOLVED_SYNTHETIC_REQUIRES_INDEPENDENT_REVIEW');self.assertFalse(r['diagnostic_authorized'])
    def test_valid_bound_diagnostic_never_final_pass(self):
        r=m.verify_bound_diagnostic(*f.ready(),m.AttemptJournal(),1000);self.assertEqual(r['status'],'PASS_OFFLINE_MODEL_ONLY');self.assertFalse(r['atomic_snapshot']);self.assertFalse(r['native_execution_authorized']);self.assertIn('BLOCKED',r['gate2_final_status'])
    def test_failed_lifecycle_attempt_cannot_be_reused(self):
        g=f.grant();e=f.resolution(g);e['candidates'][0]['lifecycle']['events'][1]['kind']='CREATE';j=m.AttemptJournal()
        self.blocked(m.safe_result(m.resolve_identity,g,e,j,1000),'DUPLICATE_CREATE');self.blocked(m.safe_result(m.resolve_identity,g,f.resolution(g),j,1000),'ATTEMPT_ALREADY_USED')
    def test_identity_only_cannot_diagnose(self):
        d,r,a,e=f.ready();self.blocked(m.safe_result(m.verify_bound_diagnostic,f.grant(),r,a,e,m.AttemptJournal(),1000),'IDENTITY_ONLY_CANNOT_DIAGNOSE')
    def test_review_ack_is_not_grant(self):
        d,r,a,e=f.ready();self.blocked(m.safe_result(m.verify_bound_diagnostic,a,r,a,e,m.AttemptJournal(),1000),'stage')
    def test_independent_review_still_required(self):
        d,r,a,e=f.ready();a['decision']='AUTO_PROMOTE';self.blocked(m.safe_result(m.verify_bound_diagnostic,d,r,a,e,m.AttemptJournal(),1000),'REVIEW_ACK_REQUIRED')
    def test_exact_target_still_required(self):
        d,r,a,e=f.ready();e['before']['tid']+=1;self.blocked(m.safe_result(m.verify_bound_diagnostic,d,r,a,e,m.AttemptJournal(),1000),'IDENTITY_CHANGED_BEFORE')
    def test_exact_three_titles_preserved(self):self.assertEqual(m.accepted_title_module().TITLES,{'虛擬記憶體','虚拟内存','virtual memory'})
    def test_title_suffix_still_rejected(self):
        d,r,a,e=f.ready();e['window']=f.window(title='virtual memory - system');self.blocked(m.safe_result(m.verify_bound_diagnostic,d,r,a,e,m.AttemptJournal(),1000),'ORIGINAL_EXACT_TITLE')
    def test_unknown_title_still_rejected(self):
        d,r,a,e=f.ready();e['window']['title_complete']=False;self.blocked(m.safe_result(m.verify_bound_diagnostic,d,r,a,e,m.AttemptJournal(),1000),'UNKNOWN_TITLE')
    def test_original_admin_high_gate_preserved(self):
        d,r,a,e=f.ready();e['context']['parent_token']['is_elevated']=False;self.blocked(m.safe_result(m.verify_bound_diagnostic,d,r,a,e,m.AttemptJournal(),1000),'ADMIN_FULL_HIGH')
    def test_closed_source_boundary(self):self.assertEqual(b.audit_boundary(P)['status'],'PASS_OFFLINE_DELIVERY_BOUNDARY')
    def test_pure_module_has_no_native_or_permit_entry(self):
        pure=m.accepted_title_module()
        for n in ['NativeBackend','validate_live_permit','main','collect','secure_path','write_new']:self.assertFalse(hasattr(pure,n))
    def test_legacy_paths_absent(self):
        for n in ['accepted_baseline/rate_readonly_gui_diag_v2.py','accepted_baseline/baseline_source/rate_readonly_gui_diag_v1.py']:self.assertFalse((P/n).exists())
    def test_legacy_direct_loader_fails_missing_file(self):
        s=importlib.util.spec_from_file_location('absent_legacy',P/'accepted_baseline/rate_readonly_gui_diag_v2.py')
        with self.assertRaises(FileNotFoundError):s.loader.exec_module(importlib.util.module_from_spec(s))
    def test_live_entry_always_rejects(self):self.blocked(m.safe_result(m.live_entry),'NOT_IMPLEMENTED_OR_AUTHORIZED')
    def test_bundle_closed_and_legacy_not_importable(self):
        out=self.root()/'library.zip';b.build_bundle(P,out)
        with zipfile.ZipFile(out) as z:self.assertEqual(set(z.namelist()),set(b.RUNTIME_FILES));self.assertIsNone(z.testzip())
        for n in ['rate_readonly_gui_diag_v1','rate_readonly_gui_diag_v2','accepted_baseline']:
            with self.assertRaises(zipimport.ZipImportError):zipimport.zipimporter(str(out)).get_code(n)
    def test_extracted_bundle_import_boundary(self):
        r=self.root();out=r/'library.zip';b.build_bundle(P,out);dest=r/'unpacked';dest.mkdir()
        with zipfile.ZipFile(out) as z:
            for n in b.RUNTIME_FILES:(dest/n).write_bytes(z.read(n))
        self.assertEqual(b.audit_boundary(dest,packaged=True)['status'],'PASS_OFFLINE_DELIVERY_BOUNDARY')
        model=load('unpacked_model',dest/'identity_binding.py');self.assertFalse(hasattr(model.accepted_title_module(),'NativeBackend'));self.blocked(model.safe_result(model.live_entry),'NOT_IMPLEMENTED_OR_AUTHORIZED')
    def test_no_output_overwrite(self):
        out=self.root()/'existing.zip';out.write_bytes(b'preserve')
        with self.assertRaisesRegex(ValueError,'EXCLUSIVE_NEW'):b.build_bundle(P,out)
        self.assertEqual(out.read_bytes(),b'preserve')
    def test_output_cannot_target_halt_or_campaign(self):
        for p in [Path(r'D:\R1-20261015-01\forbidden.zip'),Path(r'D:\Codex\RATE-D-Pagefile-Reentry2-20261017-0009\forbidden.zip')]:
            with self.assertRaisesRegex(ValueError,'EXTERNAL_ROUND2_EVIDENCE_ONLY'):b.build_bundle(P,p)
            self.assertFalse(p.exists())
    def test_output_must_be_absolute(self):
        with self.assertRaisesRegex(ValueError,'ABSOLUTE_PHYSICAL_PATH'):b.build_bundle(P,Path('relative.zip'))

LIFECYCLE_CASES=[
('duplicate_create',lambda p:p['events'][1].update(kind='CREATE'),'DUPLICATE_CREATE'),
('later_duplicate_create',lambda p:p['events'].append({'sequence':3,'kind':'CREATE','hwnd':1,'epoch':7}),'DUPLICATE_CREATE'),
('destroy',lambda p:p['events'][1].update(kind='DESTROY'),'WINDOW_DESTROYED'),
('destroy_first',lambda p:p['events'][0].update(kind='DESTROY'),'WINDOW_DESTROYED'),
('missing_create',lambda p:p['events'][0].update(kind='UNCHANGED'),'UNANCHORED'),
('empty_events',lambda p:p.update(events=[]),'MISSING_LIFECYCLE'),
('missing_interval',lambda p:p.update(events=p['events'][:1]),'MISSING_LIFECYCLE_INTERVAL'),
('sequence_gap',lambda p:p['events'][1].update(sequence=3),'TRACE_GAP'),
('duplicate_sequence',lambda p:p['events'][1].update(sequence=1),'TRACE_GAP'),
('reversed_events',lambda p:p['events'].reverse(),'TRACE_GAP'),
('boolean_sequence',lambda p:p['events'][0].update(sequence=True),'TRACE_GAP'),
('float_sequence',lambda p:p['events'][1].update(sequence=2.0),'TRACE_GAP'),
('unknown_event',lambda p:p['events'][1].update(kind='UNKNOWN'),'EVENT_KIND'),
('untrusted_source',lambda p:p.update(source='UNTRUSTED'),'ASSURANCE_UNKNOWN'),
('unknown_coverage',lambda p:p.update(coverage='UNKNOWN'),'ASSURANCE_UNKNOWN'),
('lost_event',lambda p:p.update(lost_events=1),'LOSS_UNKNOWN'),
('boolean_loss',lambda p:p.update(lost_events=False),'LOSS_UNKNOWN'),
('missing_field',lambda p:p.pop('coverage'),'EXACT_KEYS'),
('boolean_generation',lambda p:p.update(epoch_after=True),'WINDOW_REPLACEMENT'),
('changed_generation',lambda p:p.update(epoch_after=8),'WINDOW_REPLACEMENT'),
('wrong_event_epoch',lambda p:p['events'][1].update(epoch=8),'WINDOW_REPLACEMENT'),
('wrong_event_handle',lambda p:p['events'][1].update(hwnd=2),'WINDOW_REPLACEMENT'),
('boolean_event_handle',lambda p:p['events'][0].update(hwnd=True),'WINDOW_REPLACEMENT'),
('missing_event_key',lambda p:p['events'][1].pop('hwnd'),'EXACT_KEYS')]
def lifecycle_test(edit,reason,diagnostic):
    def test(self):
        if diagnostic:
            d,r,a,e=f.ready();edit(e['lifecycle']);result=m.safe_result(m.verify_bound_diagnostic,d,r,a,e,m.AttemptJournal(),1000)
        else:
            g=f.grant();e=f.resolution(g);edit(e['candidates'][0]['lifecycle']);result=m.safe_result(m.resolve_identity,g,e,m.AttemptJournal(),1000)
        self.blocked(result,reason);self.assertNotIn('target_identity',result)
    return test
for name,edit,reason in LIFECYCLE_CASES:
    for diagnostic in [False,True]:setattr(Round2Tests,'test_'+('diagnostic_' if diagnostic else 'resolution_')+name,lifecycle_test(edit,reason,diagnostic))

INJECTIONS=[('extra_legacy_file','rate_readonly_gui_diag_v2.py',b'raise RuntimeError("never run")','CLOSED_DELIVERY_FILE_SET'),('extra_archive','legacy.zip',b'quarantine','CLOSED_DELIVERY_FILE_SET'),('native_import','identity_binding.py',b'\nimport ctypes\n','RUNTIME_IMPORT_CLOSURE'),('native_class','identity_binding.py',b'\nclass NativeBackend: pass\n','LEGACY_EXECUTABLE_DEFINITION'),('permit_loader','identity_binding.py',b'\ndef validate_live_permit(): pass\n','LEGACY_EXECUTABLE_DEFINITION'),('runtime_cli','identity_binding.py',b'\nif __name__=="__main__": pass\n','RUNTIME_CLI_ENTRY'),('pure_tamper','title_validation_pure_v2.py',b'\n#changed\n','PURE_VALIDATOR_PIN'),('schema_tamper','TITLE_EVIDENCE_SCHEMA_V2.json',b' ','TITLE_SCHEMA_PIN')]
def injection_test(name,data,reason):
    def test(self):
        src=self.source();p=src/name;p.write_bytes((p.read_bytes() if p.exists() else b'')+data)
        with self.assertRaisesRegex(ValueError,reason):b.build_bundle(src,self.root()/'denied.zip')
    return test
for label,name,data,reason in INJECTIONS:setattr(Round2Tests,'test_boundary_'+label,injection_test(name,data,reason))
