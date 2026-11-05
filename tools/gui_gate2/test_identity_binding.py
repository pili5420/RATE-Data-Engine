"""Offline synthetic identity/read-scope tests; no native provider or enumeration."""
import ast,copy,hashlib,importlib.util,json,unittest
from pathlib import Path
P=Path(__file__).resolve().parent
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
m=load('gate2_model_test',P/'identity_binding.py')
v2=load('gate2_title_fixtures',P/'accepted_baseline'/'test_gui_diag_synthetic.py')
def ident():
    w=v2.window()
    return {'host':'SYNTHETIC-HOST-ONLY','session_id':1,'desktop':'Default','observer_station':'WinSta0','pid':101,'tid':201,'hwnd':1,'class_name':'#32770',
        'creation_filetime_100ns':w['process']['creation_filetime_100ns'],'executable_path':w['process']['image'],'executable_sha256':'a'*64,'volume_serial':'SYNTH-VOL','file_id':'SYNTH-FILE','window_epoch':7}
def grant(stage='IDENTITY_ONLY'):
    x=ident();p={k:x[k] for k in ['host','session_id','desktop','observer_station','executable_path','executable_sha256','volume_serial','file_id','class_name']}
    attempt='SYNTHETIC-'+stage.replace('_','-')+'-00000001'
    scope={'allowed_apis':sorted(m.IDENTITY_APIS if stage=='IDENTITY_ONLY' else m.DIAGNOSTIC_APIS),'read_fields':sorted(m.IDENTITY_FIELDS if stage=='IDENTITY_ONLY' else m.DIAGNOSTIC_FIELDS),
        'access_rights':{'process':4096,'token':8,'file':129},'enumeration_bounds':{'max_windows':128 if stage=='IDENTITY_ONLY' else 0,'max_candidates':1,'max_title_reads':0 if stage=='IDENTITY_ONLY' else 2},
        'timeouts':{'per_call_ms':1000,'total_ms':10000},'evidence_destination':str(m.OUTPUT_PARENT/attempt),'target_policy':p}
    return {'artifact_kind':m.PURPOSE,'stage':stage,'attempt_id':attempt,'issued_ns':100,'expires_ns':100000000000,'scope':scope,'scope_sha256':m.hash_value(scope),
        'tool_sha256':hashlib.sha256((P/'identity_binding.py').read_bytes()).hexdigest(),'schema_sha256':hashlib.sha256((P/'TARGET_IDENTITY_BINDING_SCHEMA_V1.json').read_bytes()).hexdigest(),
        'identity_binding':{'mode':'UNRESOLVED_IDENTITY_ONLY' if stage=='IDENTITY_ONLY' else 'EXACT_REVIEWED_TARGET','target_identity_sha256':None if stage=='IDENTITY_ONLY' else m.hash_value(x),'resolution_evidence_sha256':None if stage=='IDENTITY_ONLY' else 'a'*64,'review_ack_sha256':None if stage=='IDENTITY_ONLY' else 'b'*64}}
def life():return {'source':m.LIFECYCLE_SOURCE,'coverage':'COMPLETE_SYNTHETIC_TRACE','lost_events':0,'epoch_before':7,'epoch_after':7,'events':[{'sequence':1,'kind':'CREATE','hwnd':1,'epoch':7},{'sequence':2,'kind':'UNCHANGED','hwnd':1,'epoch':7}]}
def resolution(g=None):
    g=g or grant()
    return {'artifact_kind':m.PURPOSE,'scope_sha256':g['scope_sha256'],'enumeration_count':1,'enumeration_complete':True,'candidates':[{'before':ident(),'after':ident(),'lifecycle':life()}]}
def ready():
    g=grant();r=m.resolve_identity(g,resolution(g),m.AttemptJournal(),1000);d=grant('BOUND_DIAGNOSTIC')
    ack={'artifact_kind':m.PURPOSE,'decision':'SYNTHETIC_REVIEW_ACK_ONLY_NOT_CONTROL_CENTER_AUTHORITY','resolution_evidence_sha256':r['resolution_evidence_sha256'],'target_identity_sha256':r['target_identity_sha256'],
        'diagnostic_scope_sha256':d['scope_sha256'],'issued_ns':100,'expires_ns':100000000000}
    d['identity_binding'].update(target_identity_sha256=r['target_identity_sha256'],resolution_evidence_sha256=r['resolution_evidence_sha256'],review_ack_sha256=m.hash_value(ack))
    ctx=v2.fixture()['context'];ctx['host']=ident()['host']
    e={'artifact_kind':m.PURPOSE,'scope_sha256':d['scope_sha256'],'before':ident(),'after':ident(),'lifecycle':life(),'context':ctx,'window':v2.window()}
    return d,r,ack,e
def desktop():return {k:ident()[k] for k in m.DESKTOP_KEYS}
def seed():return {k:ident()[k] for k in m.SEED_KEYS}

class Gate2Tests(unittest.TestCase):
    def resolve(self,e=None,g=None,j=None):
        g=g or grant();return m.safe_result(m.resolve_identity,g,e if e is not None else resolution(g),j or m.AttemptJournal(),1000)
    def diagnose(self,change=None):
        args=list(ready())
        if change:change(*args)
        return m.safe_result(m.verify_bound_diagnostic,*args,m.AttemptJournal(),1000)
    def denied(self,r,reason=None,state=None):
        self.assertEqual(r['status'],'BLOCKED');self.assertFalse(r['native_execution_authorized']);self.assertTrue(r['no_retry'])
        if reason:self.assertIn(reason,r['reason'])
        if state:self.assertEqual(r['identity_state'],state)
    def test_unique_target_binding(self):
        r=self.resolve();self.assertEqual(r['status'],'RESOLVED_SYNTHETIC_REQUIRES_INDEPENDENT_REVIEW');self.assertFalse(r['diagnostic_authorized'])
    def test_multiple_candidate_rejection(self):
        e=resolution();e['candidates']*=2;self.denied(self.resolve(e),'EXACTLY_ONE','AMBIGUOUS')
    def test_zero_candidate_unknown(self):
        e=resolution();e['candidates']=[];self.denied(self.resolve(e),'EXACTLY_ONE','UNKNOWN')
    def test_pid_reuse_same_pid_new_creation_time(self):
        e=resolution();e['candidates'][0]['after']['creation_filetime_100ns']+=1;self.denied(self.resolve(e),'IDENTITY_CHANGED','MISMATCH')
    def test_process_restart_new_pid(self):
        e=resolution();e['candidates'][0]['after']['pid']+=1;self.denied(self.resolve(e),'IDENTITY_CHANGED','MISMATCH')
    def test_hwnd_reuse_generation_changed(self):
        e=resolution();e['candidates'][0]['after']['window_epoch']+=1;self.denied(self.resolve(e),'IDENTITY_CHANGED','MISMATCH')
    def test_window_replacement_new_handle(self):
        e=resolution();e['candidates'][0]['after']['hwnd']+=1;self.denied(self.resolve(e),'IDENTITY_CHANGED','MISMATCH')
    def test_same_identity_destroy_event_still_blocks(self):
        e=resolution();e['candidates'][0]['lifecycle']['events'][1]['kind']='DESTROY';self.denied(self.resolve(e),'WINDOW_DESTROYED','MISMATCH')
    def test_generation_unknown_not_boolean_assurance(self):
        e=resolution();e['candidates'][0]['lifecycle']['coverage']='UNKNOWN';self.denied(self.resolve(e),'ASSURANCE_UNKNOWN')
    def test_lifecycle_lost_events(self):
        e=resolution();e['candidates'][0]['lifecycle']['lost_events']=1;self.denied(self.resolve(e),'LOSS_UNKNOWN')
    def test_lifecycle_sequence_gap(self):
        e=resolution();e['candidates'][0]['lifecycle']['events'][1]['sequence']=3;self.denied(self.resolve(e),'TRACE_GAP')
    def test_lifecycle_must_anchor_creation(self):
        e=resolution();e['candidates'][0]['lifecycle']['events'][0]['kind']='UNCHANGED';self.denied(self.resolve(e),'UNANCHORED')
    def test_host_mismatch(self):
        e=resolution();e['candidates'][0]['before']['host']='OTHER';self.denied(self.resolve(e),'MISMATCH:host','MISMATCH')
    def test_session_mismatch(self):
        e=resolution();e['candidates'][0]['before']['session_id']=2;self.denied(self.resolve(e),'MISMATCH:session_id','MISMATCH')
    def test_desktop_mismatch(self):
        e=resolution();e['candidates'][0]['before']['desktop']='Other';self.denied(self.resolve(e),'MISMATCH:desktop','MISMATCH')
    def test_station_mismatch(self):
        e=resolution();e['candidates'][0]['before']['observer_station']='Other';self.denied(self.resolve(e),'MISMATCH:observer_station','MISMATCH')
    def test_executable_path_mismatch(self):
        e=resolution();e['candidates'][0]['before']['executable_path']=r'C:\Windows\System32\control.exe';self.denied(self.resolve(e),'MISMATCH:executable_path','MISMATCH')
    def test_executable_hash_mismatch(self):
        e=resolution();e['candidates'][0]['before']['executable_sha256']='b'*64;self.denied(self.resolve(e),'MISMATCH:executable_sha256','MISMATCH')
    def test_same_path_hash_replaced_file_id(self):
        e=resolution();e['candidates'][0]['before']['file_id']='OTHER';self.denied(self.resolve(e),'MISMATCH:file_id','MISMATCH')
    def test_identity_bool_pid_rejects(self):
        e=resolution();e['candidates'][0]['before']['pid']=True;self.denied(self.resolve(e),'NATIVE_INTEGER')
    def test_identity_float_creation_rejects(self):
        e=resolution();e['candidates'][0]['before']['creation_filetime_100ns']=1.0;self.denied(self.resolve(e),'NATIVE_INTEGER')
    def test_identity_title_is_not_a_selector(self):
        e=resolution();e['candidates'][0]['before']['title']='virtual memory';self.denied(self.resolve(e),'EXACT_KEYS')
    def test_enumeration_incomplete(self):
        e=resolution();e['enumeration_complete']=False;self.denied(self.resolve(e),'ENUMERATION_INCOMPLETE','INDETERMINATE')
    def test_enumeration_bound_exceeded(self):
        e=resolution();e['enumeration_count']=129;self.denied(self.resolve(e),'BOUNDS','INDETERMINATE')
    def test_enumeration_bool_count(self):
        e=resolution();e['enumeration_count']=True;self.denied(self.resolve(e),'BOUNDS')
    def test_scope_digest_mismatch(self):
        e=resolution();e['scope_sha256']='0'*64;self.denied(self.resolve(e),'SCOPE_BINDING')
    def test_scope_unauthorized_api(self):
        g=grant();g['scope']['allowed_apis'].append('ReadProcessMemory');g['scope_sha256']=m.hash_value(g['scope']);self.denied(self.resolve(g=g),'EXACT_ALLOWED_APIS')
    def test_scope_unauthorized_field(self):
        g=grant();g['scope']['read_fields'].append('environment');g['scope_sha256']=m.hash_value(g['scope']);self.denied(self.resolve(g=g),'EXACT_READ_FIELDS')
    def test_scope_write_access_rights(self):
        g=grant();g['scope']['access_rights']['process']=0x1f0fff;g['scope_sha256']=m.hash_value(g['scope']);self.denied(self.resolve(g=g),'READ_ACCESS_RIGHTS')
    def test_scope_unbounded_timeout(self):
        g=grant();g['scope']['timeouts']['total_ms']=0;g['scope_sha256']=m.hash_value(g['scope']);self.denied(self.resolve(g=g),'BOUNDED_TIMEOUTS')
    def test_scope_dest_cannot_be_production_or_halt(self):
        g=grant();g['scope']['evidence_destination']=r'D:\Codex\RATE-D-Pagefile-Reentry2-20261017-0009';g['scope_sha256']=m.hash_value(g['scope']);self.denied(self.resolve(g=g),'EVIDENCE_DESTINATION')
    def test_scope_path_traversal(self):
        g=grant();g['scope']['target_policy']['executable_path']=r'C:\Windows\System32\..\control.exe';g['scope_sha256']=m.hash_value(g['scope']);self.denied(self.resolve(g=g),'WINDOWS_PATH')
    def test_real_host_authority_cannot_enter_offline_model(self):
        g=grant();g['scope']['target_policy']['host']='Pili';g['scope_sha256']=m.hash_value(g['scope']);self.denied(self.resolve(g=g),'NOT_LIVE_AUTHORITY')
    def test_real_permit_not_loaded(self):
        g=grant();g['artifact_kind']='EXECUTION_PERMIT';self.denied(self.resolve(g=g),'LIVE_PERMIT_LOADING_NOT_IMPLEMENTED')
    def test_stale_model(self):
        g=grant();g['expires_ns']=999;self.denied(self.resolve(g=g),'TIME_WINDOW')
    def test_tool_pin_mismatch(self):
        g=grant();g['tool_sha256']='0'*64;self.denied(self.resolve(g=g),'EXACT_TOOL_SCHEMA_BINDING')
    def test_schema_pin_mismatch(self):
        g=grant();g['schema_sha256']='0'*64;self.denied(self.resolve(g=g),'EXACT_TOOL_SCHEMA_BINDING')
    def test_failed_resolution_attempt_not_reused(self):
        j=m.AttemptJournal();e=resolution();e['candidates']=[];self.denied(self.resolve(e,j=j));self.denied(self.resolve(j=j),'ATTEMPT_ALREADY_USED')
    def test_bound_diagnostic_unique_ack_target(self):
        r=self.diagnose();self.assertEqual(r['status'],'PASS_OFFLINE_MODEL_ONLY');self.assertFalse(r['native_execution_authorized']);self.assertFalse(r['atomic_snapshot']);self.assertIn('BLOCKED',r['gate2_final_status'])
    def test_identity_only_cannot_authorize_diagnostic(self):
        d,r,a,e=ready();self.denied(m.safe_result(m.verify_bound_diagnostic,grant(),r,a,e,m.AttemptJournal(),1000),'IDENTITY_ONLY_CANNOT_DIAGNOSE')
    def test_wrong_ack_identity(self):self.denied(self.diagnose(lambda d,r,a,e:a.update(target_identity_sha256='0'*64)),'ACK_BINDING')
    def test_wrong_ack_resolution_evidence(self):self.denied(self.diagnose(lambda d,r,a,e:a.update(resolution_evidence_sha256='0'*64)),'ACK_BINDING')
    def test_wrong_ack_read_scope(self):self.denied(self.diagnose(lambda d,r,a,e:a.update(diagnostic_scope_sha256='0'*64)),'ACK_BINDING')
    def test_missing_independent_review_ack(self):self.denied(self.diagnose(lambda d,r,a,e:a.update(decision='AUTO_PROMOTED')),'REVIEW_ACK_REQUIRED')
    def test_stale_ack(self):
        def change(d,r,a,e):
            a['expires_ns']=999;d['identity_binding']['review_ack_sha256']=m.hash_value(a)
        self.denied(self.diagnose(change),'ACK_TIME_WINDOW')
    def test_diagnostic_pid_identity_changes(self):self.denied(self.diagnose(lambda d,r,a,e:e['after'].update(pid=999)),'IDENTITY_CHANGED_AFTER','MISMATCH')
    def test_diagnostic_executable_hash_changes(self):self.denied(self.diagnose(lambda d,r,a,e:e['after'].update(executable_sha256='b'*64)),'IDENTITY_CHANGED_AFTER','MISMATCH')
    def test_diagnostic_target_title_not_enough(self):self.denied(self.diagnose(lambda d,r,a,e:e['window'].update(pid=999)),'WINDOW_BINDING_MISMATCH','MISMATCH')
    def test_diagnostic_gui_token_still_required(self):self.denied(self.diagnose(lambda d,r,a,e:e['window']['process']['token'].update(is_elevated=False)),'ADMIN_FULL_HIGH')
    def test_diagnostic_parent_high_integrity_still_required(self):self.denied(self.diagnose(lambda d,r,a,e:e['context']['parent_token'].update(integrity_sid='S-1-16-8192')),'ADMIN_FULL_HIGH')
    def test_diagnostic_context_session_mismatch(self):self.denied(self.diagnose(lambda d,r,a,e:e['context'].update(session_id=2)),'CONTEXT_IDENTITY_MISMATCH')
    def test_title_changes_do_not_bypass_binding(self):
        def change(d,r,a,e):e['window']['title_observation']['reads'][1]['utf16_hex']='4100'*5
        self.denied(self.diagnose(change),'UNKNOWN_TITLE','INDETERMINATE')
    def test_unknown_title_declaration(self):self.denied(self.diagnose(lambda d,r,a,e:e['window'].update(title_complete=False)),'UNKNOWN_TITLE','INDETERMINATE')
    def test_original_caption_rule_not_widened(self):
        def change(d,r,a,e):e['window']=v2.window(title='virtual memory - system')
        self.denied(self.diagnose(change),'ORIGINAL_EXACT_TITLE')
    def test_no_diagnostic_desktop_enumeration(self):
        d,r,a,e=ready();g=m.ReadGuard(d,m.AttemptJournal(),1000,r['target_identity'],review_evidence=(r,a))
        with self.assertRaisesRegex(m.Denied,'UNAUTHORIZED_API'):g.begin('EnumWindows',['hwnd'],ident(),1100)
    def test_identity_phase_cannot_read_title(self):
        g=m.ReadGuard(grant(),m.AttemptJournal(),1000)
        with self.assertRaisesRegex(m.Denied,'UNAUTHORIZED_API'):g.begin('GetWindowTextW',['title'],ident(),1100)
    def test_guard_unauthorized_read_field(self):
        d,r,a,e=ready();g=m.ReadGuard(d,m.AttemptJournal(),1000,r['target_identity'],review_evidence=(r,a))
        with self.assertRaisesRegex(m.Denied,'UNAUTHORIZED_READ_FIELD'):g.begin('GetWindowTextW',['process_memory'],ident(),1100)
    def test_guard_unauthorized_api_field_pair(self):
        d,r,a,e=ready();g=m.ReadGuard(d,m.AttemptJournal(),1000,r['target_identity'],review_evidence=(r,a))
        with self.assertRaisesRegex(m.Denied,'UNAUTHORIZED_API_FIELD_PAIR'):g.begin('ReadFile',['title'],ident(),1100)
    def test_guard_identity_change_before_read(self):
        d,r,a,e=ready();g=m.ReadGuard(d,m.AttemptJournal(),1000,r['target_identity'],review_evidence=(r,a));x=ident();x['creation_filetime_100ns']+=1
        with self.assertRaisesRegex(m.Denied,'BOUND_IDENTITY_CHANGED'):g.begin('GetWindowTextW',['title'],x,1100)
    def test_guard_identity_change_during_read(self):
        d,r,a,e=ready();g=m.ReadGuard(d,m.AttemptJournal(),1000,r['target_identity'],review_evidence=(r,a));ticket=g.begin('GetWindowTextW',['title'],ident(),1100);x=ident();x['tid']+=1
        with self.assertRaisesRegex(m.Denied,'DURING_READ'):g.finish(ticket,x,1200)
        with self.assertRaisesRegex(m.Denied,'NO_RETRY'):g.begin('GetWindowTextW',['title'],ident(),1300)
    def test_guard_call_timeout_poisoned(self):
        d,r,a,e=ready();g=m.ReadGuard(d,m.AttemptJournal(),1000,r['target_identity'],review_evidence=(r,a));ticket=g.begin('GetWindowTextW',['title'],ident(),1100)
        with self.assertRaisesRegex(m.Denied,'CALL_TIMEOUT'):g.finish(ticket,ident(),1000001101)
    def test_guard_total_timeout(self):
        d,r,a,e=ready();g=m.ReadGuard(d,m.AttemptJournal(),1000,r['target_identity'],review_evidence=(r,a))
        with self.assertRaisesRegex(m.Denied,'TOTAL_TIMEOUT'):g.begin('GetWindowTextW',['title'],ident(),10000001001)
    def test_guard_api_error_poisoned(self):
        d,r,a,e=ready();g=m.ReadGuard(d,m.AttemptJournal(),1000,r['target_identity'],review_evidence=(r,a));ticket=g.begin('GetWindowTextW',['title'],ident(),1100)
        with self.assertRaisesRegex(m.Denied,'READ_API_ERROR'):g.finish(ticket,ident(),1200,'ERROR')
    def test_guard_title_third_read_forbidden(self):
        d,r,a,e=ready();g=m.ReadGuard(d,m.AttemptJournal(),1000,r['target_identity'],review_evidence=(r,a))
        for n in [1100,1300]:t=g.begin('GetWindowTextW',['title'],ident(),n);g.finish(t,ident(),n+1)
        with self.assertRaisesRegex(m.Denied,'RETRY_FORBIDDEN'):g.begin('GetWindowTextW',['title'],ident(),1500)
    def test_identity_enumeration_one_shot_and_seed_binding(self):
        g=m.ReadGuard(grant(),m.AttemptJournal(),1000);t=g.begin('EnumWindows',['hwnd'],desktop(),1100);g.finish(t,desktop(),1200);g.register_enumerated_seeds([seed()],1,True)
        t=g.begin('GetProcessTimes',['pid','creation_filetime_100ns'],seed(),1300);g.finish(t,seed(),1400)
        with self.assertRaisesRegex(m.Denied,'ENUMERATION_RETRY'):g.begin('EnumWindows',['hwnd'],desktop(),1500)
    def test_identity_arbitrary_pid_probe_forbidden(self):
        g=m.ReadGuard(grant(),m.AttemptJournal(),1000)
        with self.assertRaisesRegex(m.Denied,'UNREGISTERED'):g.begin('OpenProcess',['pid'],seed(),1100)
    def test_identity_wrong_desktop_discovery_forbidden(self):
        g=m.ReadGuard(grant(),m.AttemptJournal(),1000);x=desktop();x['desktop']='Other'
        with self.assertRaisesRegex(m.Denied,'SCOPE_MISMATCH'):g.begin('EnumWindows',['hwnd'],x,1100)
    def test_file_read_ticket_has_only_approved_path(self):
        d,r,a,e=ready();g=m.ReadGuard(d,m.AttemptJournal(),1000,r['target_identity'],review_evidence=(r,a));g.begin('ReadFile',['executable_sha256'],ident(),1100)
        self.assertEqual(g.pending['resource'],ident()['executable_path'])
    def test_duplicate_json_rejects(self):
        with self.assertRaisesRegex(m.Denied,'DUPLICATE'):m.decode(b'{"x":1,"x":2}')
    def test_nan_json_rejects(self):
        with self.assertRaisesRegex(m.Denied,'NONFINITE'):m.decode(b'{"x":NaN}')
    def test_schema_model_positive_and_bool_negative(self):
        schema=json.loads((P/'TARGET_IDENTITY_BINDING_SCHEMA_V1.json').read_bytes());g=grant();v2.schema_check(g,schema['$defs']['model'],schema);g['scope']['access_rights']['token']=True
        with self.assertRaises(AssertionError):v2.schema_check(g,schema['$defs']['model'],schema)
    def test_original_142_sources_byte_identical(self):
        pins=json.loads((P/'ACCEPTED_BASELINE_PINS.json').read_bytes())
        for n,row in pins.items():self.assertEqual(hashlib.sha256((P/'accepted_baseline'/n).read_bytes()).hexdigest(),row['sha256'])
    def test_no_original_halt_or_any_os_write_in_new_component(self):
        tree=ast.parse((P/'identity_binding.py').read_text(encoding='utf-8'));attrs={getattr(n.func,'attr',None) for n in ast.walk(tree) if isinstance(n,ast.Call)}
        self.assertFalse(attrs&{'write_bytes','write_text','open','mkdir','unlink','rename','replace','WinDLL','EnumWindows','OpenProcess'})
        imports={n.names[0].name for n in ast.walk(tree) if isinstance(n,ast.Import)};self.assertFalse(imports&{'ctypes','subprocess','socket','requests'})
    def test_live_entry_always_blocked(self):
        self.denied(m.safe_result(m.live_entry),'NOT_IMPLEMENTED_OR_AUTHORIZED')
    def test_no_final_gate2_pass_claim(self):
        self.assertIn('BLOCKED',self.resolve()['gate2_final_status']);self.assertIn('BLOCKED',self.diagnose()['gate2_final_status'])
    def test_zero_enumerated_windows_cannot_yield_candidate(self):
        e=resolution();e['enumeration_count']=0;self.denied(self.resolve(e),'COUNT_CONTRADICTION','INDETERMINATE')
    def test_forged_resolved_identity_cannot_replace_grant_target(self):
        d,r,a,e=ready();r['target_identity']['pid']=777;r['target_identity_sha256']=m.hash_value(r['target_identity']);a['target_identity_sha256']=r['target_identity_sha256']
        self.denied(m.safe_result(m.verify_bound_diagnostic,d,r,a,e,m.AttemptJournal(),1000),'GRANT_BOUND_TARGET_IDENTITY_MISMATCH','MISMATCH')
    def test_guard_requires_review_evidence(self):
        d,r,a,e=ready()
        with self.assertRaisesRegex(m.Denied,'INDEPENDENT_REVIEW_ACK_REQUIRED'):m.ReadGuard(d,m.AttemptJournal(),1000,r['target_identity'])
    def test_grant_scope_mutation_after_binding_blocks(self):
        d,r,a,e=ready();g=m.ReadGuard(d,m.AttemptJournal(),1000,r['target_identity'],review_evidence=(r,a));d['scope']['allowed_apis'].append('ReadProcessMemory')
        with self.assertRaisesRegex(m.Denied,'AUTHORITY_OR_BOUND_IDENTITY_MUTATED'):g.begin('ReadProcessMemory',['pid'],ident(),1100)
    def test_ack_mutation_during_read_blocks(self):
        d,r,a,e=ready();g=m.ReadGuard(d,m.AttemptJournal(),1000,r['target_identity'],review_evidence=(r,a));t=g.begin('GetWindowTextW',['title'],ident(),1100);a['decision']='AUTO_ACCEPT'
        with self.assertRaisesRegex(m.Denied,'AUTHORITY_OR_BOUND_IDENTITY_MUTATED'):g.finish(t,ident(),1200)
    def test_desktop_descriptor_boolean_session_rejects(self):
        g=m.ReadGuard(grant(),m.AttemptJournal(),1000);x=desktop();x['session_id']=True
        with self.assertRaisesRegex(m.Denied,'NATIVE_CONTEXT_TYPES'):g.begin('EnumWindows',['hwnd'],x,1100)
