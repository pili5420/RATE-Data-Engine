"""Synthetic-only engineering tests. NativeBackend is never constructed."""
import ast
import copy
import datetime
import importlib.util
import json
from pathlib import Path
import re
import platform
import sys
import unittest
from uuid import uuid4

ROOT=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('gui_diag',ROOT/'rate_readonly_gui_diag_v1.py');d=importlib.util.module_from_spec(spec);spec.loader.exec_module(d)
STAMP='2026-10-17T00:00:00+00:00'
def call(api,status='OK',error=0,result=1):return {'api':api,'observed_utc':STAMP,'result':result,'last_error':error,'status':status}
def token():return {'status':'OBSERVED','is_elevated':True,'elevation_type':2,'integrity_sid':'S-1-16-12288','administrators':[{'sid':'S-1-5-32-544','attributes':15,'enabled':True,'deny_only':False}]}
def window(hwnd=1,title='虛擬記憶體'):
    return {'hwnd':hwnd,'pid':100+hwnd,'tid':200+hwnd,'visible':True,'class_name':'#32770','title':title,'title_length':len(title.encode('utf-16-le'))//2,'title_copied':len(title.encode('utf-16-le'))//2,'title_complete':True,'session_id':1,'desktop':'Default','process':{'status':'OBSERVED','image':r'C:\Windows\System32\SystemPropertiesPerformance.exe','creation_filetime_100ns':134366334000000000,'token':token()},'stable':True,'api_calls':[call(n) for n in ['IsWindow','IsWindowVisible','GetWindowTextLengthW','GetWindowTextW','GetWindowThreadProcessId','GetClassNameW','ProcessIdToSessionId','GetThreadDesktop','GetUserObjectInformationW','GetTokenInformation']],'errors':[]}
def fixture(windows=None):
    wins=[window()] if windows is None else windows
    return {'context':{'host':'SYNTHETIC_HOST','observer_pid':10,'parent_pid':11,'session_id':1,'parent_session_id':1,'desktop':'Default','window_station':'WinSta0','observer_token':token(),'parent_token':token(),'api_calls':[call(n) for n in ['GetThreadDesktop','GetProcessWindowStation','GetUserObjectInformationW','GetTokenInformation']]},'enumeration':{'return_value':True,'last_error':0,'visited':len(wins),'completed':len(wins),'callback_errors':[],'truncated':False,'api_calls':[call('EnumWindows')]},'windows':wins}
def future_permit():
    now=datetime.datetime.now(datetime.timezone.utc)
    return {'decision':d.FUTURE_DECISION,'attempt_id':'ROGUI-SYNTHETIC-PERMIT-TEST','tool_sha256':d.digest((ROOT/'rate_readonly_gui_diag_v1.py').read_bytes()),'schema_sha256':d.digest((ROOT/'GUI_DIAGNOSTIC_EVIDENCE_SCHEMA_V1.json').read_bytes()),'original_collector_sha256':d.ORIGINAL_SHA,'host':platform.node(),'operator_session_id':1,'output_root':str(d.LIVE_PARENT/'ROGUI-SYNTHETIC-PERMIT-TEST'),'issued_utc':(now-datetime.timedelta(minutes=1)).strftime('%Y-%m-%dT%H:%M:%SZ'),'expires_utc':(now+datetime.timedelta(minutes=10)).strftime('%Y-%m-%dT%H:%M:%SZ'),'max_windows':100,'read_only':True,'no_ui_inputs':True,'no_elevation':True,'one_shot':True}

def schema_check(value,schema,root=None):
    """Independent strict validator for ONLY the schema's declared keyword subset."""
    root=root or schema
    allowed={'$schema','$id','title','$defs','$ref','type','properties','required','additionalProperties','items','enum','const','minimum','maximum','pattern','oneOf'}
    assert set(schema)<=allowed,'UNSUPPORTED_SCHEMA_KEYWORD'
    if '$ref' in schema:return schema_check(value,root['$defs'][schema['$ref'].split('/')[-1]],root)
    if 'oneOf' in schema:
        count=0
        for candidate in schema['oneOf']:
            try:schema_check(value,candidate,root);count+=1
            except (AssertionError,KeyError,TypeError,ValueError):pass
        assert count==1,'ONEOF';return
    if 'const' in schema:assert type(value) is type(schema['const']) and value==schema['const'],'CONST_NATIVE_TYPE'
    if 'enum' in schema:assert value in schema['enum'],'ENUM'
    if 'type' in schema:
        types=schema['type'] if type(schema['type']) is list else [schema['type']]
        mapping={'object':dict,'array':list,'string':str,'integer':int,'boolean':bool,'null':type(None)}
        assert type(value) in {mapping[t] for t in types},'TYPE'
    if type(value) is dict:
        assert set(schema.get('required',[]))<=set(value),'REQUIRED'
        props=schema.get('properties',{})
        if schema.get('additionalProperties') is False:assert set(value)<=set(props),'ADDITIONAL'
        for k,v in value.items():
            if k in props:schema_check(v,props[k],root)
    if type(value) is list and 'items' in schema:
        for v in value:schema_check(v,schema['items'],root)
    if 'pattern' in schema:assert re.fullmatch(schema['pattern'],value),'PATTERN'
    if 'minimum' in schema:assert value>=schema['minimum'],'MINIMUM'
    if 'maximum' in schema:assert value<=schema['maximum'],'MAXIMUM'

class SyntheticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (ROOT/'fixtures').mkdir(exist_ok=True);(ROOT/'synthetic_runs').mkdir(exist_ok=True)
        cls.schema=json.loads((ROOT/'GUI_DIAGNOSTIC_EVIDENCE_SCHEMA_V1.json').read_bytes())
        cls.native_calls=0
    def report(self,f=None):
        result=d.evaluate(fixture() if f is None else f,'SYNTHETIC');schema_check(result,self.schema);return result
    def blocked(self,f,reason):
        r=self.report(f);self.assertEqual(r['gate']['status'],'BLOCKED_FOR_CONTROL_CENTER_REVIEW');self.assertIn(reason,r['gate']['reasons']);return r
    def fixture_file(self,f):
        p=ROOT/'fixtures'/('fixture-'+uuid4().hex+'.json');p.write_bytes(d.canonical(f));return p
    def output(self):return ROOT/'synthetic_runs'/('SYNTHETIC-'+uuid4().hex)
    def never_native(self,*args):SyntheticTests.native_calls+=1;raise AssertionError('NATIVE_BACKEND_MUST_NOT_RUN_IN_ENGINEERING')
    def test_positive_original_zh_tw(self):self.assertEqual(self.report()['gate']['status'],'PASS_DIAGNOSTIC_EVIDENCE_ONLY')
    def test_positive_original_zh_cn(self):self.assertEqual(self.report(fixture([window(title='虚拟内存')]))['original_logic_audit']['filtered_windows'],1)
    def test_positive_original_english_strip_lower(self):self.assertEqual(self.report(fixture([window(title='  VIRTUAL MEMORY  ')]))['original_logic_audit']['filtered_windows'],1)
    def test_zero_matches_blocked(self):self.blocked(fixture([]),'EXACTLY_ONE_HUMAN_VIRTUAL_MEMORY_DIALOG_REQUIRED')
    def test_multiple_matches_blocked(self):self.blocked(fixture([window(),window(2)]),'EXACTLY_ONE_HUMAN_VIRTUAL_MEMORY_DIALOG_REQUIRED')
    def test_hidden_window_exclusion(self):
        w=window();w['visible']=False;r=self.blocked(fixture([w]),'EXACTLY_ONE_HUMAN_VIRTUAL_MEMORY_DIALOG_REQUIRED');self.assertEqual(r['windows'][0]['exclusion_reason'],'visible')
    def test_empty_title_exclusion(self):
        w=window(title='');r=self.blocked(fixture([w]),'EXACTLY_ONE_HUMAN_VIRTUAL_MEMORY_DIALOG_REQUIRED');self.assertEqual(r['windows'][0]['exclusion_reason'],'original_length_nonzero')
    def test_parent_page_wrong_stage(self):
        r=self.blocked(fixture([window(title='效能選項')]),'EXACTLY_ONE_HUMAN_VIRTUAL_MEMORY_DIALOG_REQUIRED');self.assertEqual(r['windows'][0]['title']['raw'],'效能選項')
    def test_title_suffix_is_not_accepted(self):self.blocked(fixture([window(title='虛擬記憶體 - 系統')]),'EXACTLY_ONE_HUMAN_VIRTUAL_MEMORY_DIALOG_REQUIRED')
    def test_other_language_not_whitelisted(self):self.blocked(fixture([window(title='Virtueller Arbeitsspeicher')]),'EXACTLY_ONE_HUMAN_VIRTUAL_MEMORY_DIALOG_REQUIRED')
    def test_zero_width_unicode_not_stripped(self):self.blocked(fixture([window(title='虛擬\u200b記憶體')]),'EXACTLY_ONE_HUMAN_VIRTUAL_MEMORY_DIALOG_REQUIRED')
    def test_class_is_recorded_not_used_to_widen_title(self):
        r=self.blocked(fixture([window(title='系統內容')]),'EXACTLY_ONE_HUMAN_VIRTUAL_MEMORY_DIALOG_REQUIRED');self.assertEqual(r['windows'][0]['class_name'],'#32770')
    def test_gui_admin_token_missing(self):
        f=fixture();f['windows'][0]['process']['token']={'status':'UNOBSERVABLE'};self.blocked(f,'ACTUAL_NATIVE_MODIFIER_ADMIN_HIGH_INTEGRITY_UNPROVEN')
    def test_gui_medium_integrity_blocked(self):
        f=fixture();f['windows'][0]['process']['token']['integrity_sid']='S-1-16-8192';self.blocked(f,'ACTUAL_NATIVE_MODIFIER_ADMIN_HIGH_INTEGRITY_UNPROVEN')
    def test_gui_deny_only_blocked(self):
        f=fixture();f['windows'][0]['process']['token']['administrators'][0].update(attributes=16,enabled=False,deny_only=True);self.blocked(f,'ACTUAL_NATIVE_MODIFIER_ADMIN_HIGH_INTEGRITY_UNPROVEN')
    def test_inconsistent_group_flags_blocked(self):
        f=fixture();f['windows'][0]['process']['token']['administrators'][0]['attributes']=16;self.blocked(f,'ACTUAL_NATIVE_MODIFIER_ADMIN_HIGH_INTEGRITY_UNPROVEN')
    def test_admin_boolean_elevation_alias_blocked(self):
        f=fixture();f['windows'][0]['process']['token']['elevation_type']=True;r=d.evaluate(f,'SYNTHETIC');self.assertIn('ACTUAL_NATIVE_MODIFIER_ADMIN_HIGH_INTEGRITY_UNPROVEN',r['gate']['reasons'])
    def test_parent_admin_does_not_substitute_for_gui(self):
        f=fixture();f['windows'][0]['process']['token']['is_elevated']=False;self.blocked(f,'ACTUAL_NATIVE_MODIFIER_ADMIN_HIGH_INTEGRITY_UNPROVEN')
    def test_observer_admin_missing(self):
        f=fixture();f['context']['observer_token']['is_elevated']=False;self.blocked(f,'OBSERVER_OR_HUMAN_PARENT_ADMIN_HIGH_INTEGRITY_UNPROVEN')
    def test_parent_admin_missing(self):
        f=fixture();f['context']['parent_token']['is_elevated']=False;self.blocked(f,'OBSERVER_OR_HUMAN_PARENT_ADMIN_HIGH_INTEGRITY_UNPROVEN')
    def test_gui_session_mismatch(self):
        f=fixture();f['windows'][0]['session_id']=2;self.blocked(f,'NATIVE_GUI_HUMAN_SESSION_MISMATCH')
    def test_parent_session_mismatch(self):
        f=fixture();f['context']['parent_session_id']=2;self.blocked(f,'OBSERVER_HUMAN_PARENT_SESSION_MISMATCH')
    def test_desktop_mismatch(self):
        f=fixture();f['windows'][0]['desktop']='Other';self.blocked(f,'NATIVE_GUI_THREAD_DESKTOP_MISMATCH_OR_UNKNOWN')
    def test_untrusted_native_basename_does_not_pass(self):
        f=fixture();f['windows'][0]['process']['image']=r'C:\Temp\rundll32.exe';self.blocked(f,'ACTUAL_GUI_NATIVE_OWNER_PATH_UNPROVEN')
    def test_creation_identity_missing(self):
        f=fixture();f['windows'][0]['process']['creation_filetime_100ns']=0;self.blocked(f,'ACTUAL_GUI_PROCESS_IDENTITY_UNPROVEN')
    def test_enum_false_blocked(self):
        f=fixture();f['enumeration']['return_value']=False;self.blocked(f,'ENUMERATION_INCOMPLETE_OR_CALLBACK_ERROR')
    def test_callback_error_preserved_blocked(self):
        f=fixture();f['enumeration']['callback_errors']=[{'type':'RuntimeError','reason':'SYNTHETIC_CALLBACK_FAILURE','visited':1}];r=self.blocked(f,'ENUMERATION_INCOMPLETE_OR_CALLBACK_ERROR');self.assertEqual(r['enumeration']['callback_errors'][0]['reason'],'SYNTHETIC_CALLBACK_FAILURE')
    def test_visited_completed_mismatch(self):
        f=fixture();f['enumeration']['visited']=2;self.blocked(f,'ENUMERATION_INCOMPLETE_OR_CALLBACK_ERROR')
    def test_rows_count_mismatch(self):
        f=fixture();f['enumeration']['completed']=2;self.blocked(f,'ENUMERATION_INCOMPLETE_OR_CALLBACK_ERROR')
    def test_window_bound_partial_enumeration(self):
        f=fixture();f['enumeration']['truncated']=True;self.blocked(f,'ENUMERATION_INCOMPLETE_OR_CALLBACK_ERROR')
    def test_enum_call_count_must_be_one(self):
        f=fixture();f['enumeration']['api_calls'].append(call('EnumWindows'));self.blocked(f,'ENUMERATION_CALL_COUNT_OR_PROVENANCE')
    def test_native_api_error_retained(self):
        f=fixture();f['windows'][0]['api_calls'].append(call('GetWindowTextW','ERROR',5,0));r=self.blocked(f,'UNRELIABLE_WINDOW_OBSERVATION:1');self.assertEqual(r['windows'][0]['api_calls'][-1]['last_error'],5)
    def test_zero_result_with_error_zero_is_failure_when_status_error(self):
        f=fixture();f['windows'][0]['api_calls'].append(call('GetClassNameW','ERROR',0,0));self.blocked(f,'UNRELIABLE_WINDOW_OBSERVATION:1')
    def test_empty_text_zero_error_is_distinct(self):
        w=window(title='');w['api_calls'].append(call('GetWindowTextLengthW','EMPTY',0,0));r=self.blocked(fixture([w]),'EXACTLY_ONE_HUMAN_VIRTUAL_MEMORY_DIALOG_REQUIRED');self.assertTrue(r['windows'][0]['observation_reliable'])
    def test_unstable_handle_blocked(self):
        f=fixture();f['windows'][0]['stable']=False;self.blocked(f,'UNRELIABLE_WINDOW_OBSERVATION:1')
    def test_truncated_title_blocked(self):
        f=fixture();f['windows'][0]['title_complete']=False;self.blocked(f,'UNRELIABLE_WINDOW_OBSERVATION:1')
    def test_unknown_window_id_with_api_error_preserved(self):
        w=window();w.update(pid=0,tid=0,stable=False,errors=[{'type':'OSError','reason':'NATIVE_API_ERROR:GetWindowThreadProcessId:5'}]);r=self.blocked(fixture([w]),'UNRELIABLE_WINDOW_OBSERVATION:1');self.assertEqual(r['windows'][0]['pid'],0)
    def test_missing_context_trace_blocks(self):
        f=fixture();f['context']['api_calls']=[];self.blocked(f,'MISSING_CONTEXT_API_PROVENANCE')
    def test_missing_window_trace_blocks(self):
        f=fixture();f['windows'][0]['api_calls']=[];self.blocked(f,'UNRELIABLE_WINDOW_OBSERVATION:1')
    def test_duplicate_hwnd_reject(self):
        with self.assertRaisesRegex(ValueError,'DUPLICATE_HWND'):d.evaluate(fixture([window(),window()]),'SYNTHETIC')
    def test_unknown_input_schema_reject(self):
        f=fixture();f['unknown']=True
        with self.assertRaisesRegex(ValueError,'EXACT_SCHEMA_KEYS'):d.evaluate(f,'SYNTHETIC')
    def test_boolean_hwnd_reject(self):
        f=fixture();f['windows'][0]['hwnd']=True
        with self.assertRaisesRegex(ValueError,'WINDOW_NATIVE_INTEGER'):d.evaluate(f,'SYNTHETIC')
    def test_float_count_reject(self):
        f=fixture();f['enumeration']['visited']=1.0
        with self.assertRaisesRegex(ValueError,'ENUM_NATIVE_INTEGER'):d.evaluate(f,'SYNTHETIC')
    def test_title_utf16_count_mismatch_reject(self):
        f=fixture();f['windows'][0]['title_copied']=1
        with self.assertRaisesRegex(ValueError,'TITLE_COUNT_MISMATCH'):d.evaluate(f,'SYNTHETIC')
    def test_unapproved_api_reject(self):
        f=fixture();f['context']['api_calls'].append(call('SendInput'))
        with self.assertRaisesRegex(ValueError,'UNAPPROVED_API_RECORD'):d.evaluate(f,'SYNTHETIC')
    def test_api_timestamp_without_zone_reject(self):
        f=fixture();f['context']['api_calls'][0]['observed_utc']='2026-10-17T00:00:00'
        with self.assertRaisesRegex(ValueError,'API_UTC_TIMESTAMP'):d.evaluate(f,'SYNTHETIC')
    def test_api_error_boolean_alias_reject(self):
        f=fixture();f['context']['api_calls'][0]['last_error']=False
        with self.assertRaisesRegex(ValueError,'API_ERROR_NATIVE_INTEGER'):d.evaluate(f,'SYNTHETIC')
    def test_input_remains_unchanged(self):
        f=fixture();before=copy.deepcopy(f);self.report(f);self.assertEqual(f,before)
    def test_private_unrelated_title_is_redacted(self):
        w=window(title='PRIVATE_DOCUMENT_SECRET');w['process']['image']=r'C:\Apps\browser.exe';r=self.blocked(fixture([w]),'EXACTLY_ONE_HUMAN_VIRTUAL_MEMORY_DIALOG_REQUIRED');self.assertNotIn('PRIVATE_DOCUMENT_SECRET',d.canonical(r).decode());self.assertNotIn('codepoints',r['windows'][0]['title'])
    def test_fake_native_path_does_not_unredact_private_title(self):
        w=window(title='PRIVATE_FAKE_NATIVE');w['process']['image']=r'C:\Temp\rundll32.exe';r=self.blocked(fixture([w]),'EXACTLY_ONE_HUMAN_VIRTUAL_MEMORY_DIALOG_REQUIRED');self.assertNotIn('PRIVATE_FAKE_NATIVE',d.canonical(r).decode())
    def test_original_title_and_codepoints_preserved_for_native(self):
        r=self.report();self.assertEqual(r['windows'][0]['title']['raw'],'虛擬記憶體');self.assertEqual(len(r['windows'][0]['title']['codepoints']),5)
    def test_station_not_falsely_claimed_for_other_process(self):self.assertEqual(self.report()['windows'][0]['owner_window_station']['status'],'NOT_DIRECTLY_QUERYABLE_OTHER_PROCESS')
    def test_large_fixture_refused_before_iteration(self):
        f=fixture();f['windows']=[window()]*4097
        with self.assertRaisesRegex(ValueError,'WINDOW_LIMIT'):d.evaluate(f,'SYNTHETIC')
    def test_duplicate_json_key_reject(self):
        with self.assertRaisesRegex(ValueError,'DUPLICATE_JSON_KEY'):d.decode(b'{"x":1,"x":2}')
    def test_nonfinite_json_reject(self):
        with self.assertRaisesRegex(ValueError,'NONFINITE_JSON'):d.decode(b'{"x":NaN}')
    def test_schema_boolean_numeric_alias_reject(self):
        r=self.report();r['original_logic_audit']['filtered_windows']=True
        with self.assertRaises(AssertionError):schema_check(r,self.schema)
    def test_schema_extra_field_reject(self):
        r=self.report();r['unexpected']='x'
        with self.assertRaises(AssertionError):schema_check(r,self.schema)
    def test_synthetic_cli_positive_and_no_native_calls(self):
        output=self.output();rc=d.main(['--mode','synthetic','--fixture',str(self.fixture_file(fixture())),'--output',str(output)],native_factory=self.never_native);self.assertEqual(rc,0);self.assertEqual(json.loads((output/'complete.json').read_bytes())['status'],'PASS_SYNTHETIC_ONLY');self.assertEqual(SyntheticTests.native_calls,0)
    def test_synthetic_cli_negative_retains_halt(self):
        output=self.output();rc=d.main(['--mode','synthetic','--fixture',str(self.fixture_file(fixture([]))),'--output',str(output)],native_factory=self.never_native);self.assertEqual(rc,2);self.assertTrue((output/'HALTED.json').is_file());self.assertTrue((output/'evidence.json').is_file())
    def test_synthetic_output_no_overwrite(self):
        output=self.output();file=self.fixture_file(fixture());argv=['--mode','synthetic','--fixture',str(file),'--output',str(output)];self.assertEqual(d.main(argv,self.never_native),0);before=(output/'evidence.json').read_bytes();self.assertEqual(d.main(argv,self.never_native),2);self.assertEqual((output/'evidence.json').read_bytes(),before)
    def test_original_root_output_denied_without_touch(self):
        output=Path(r'D:\Codex\RATE-D-Pagefile-Reentry2-20261017-0009');self.assertEqual(d.main(['--mode','synthetic','--fixture',str(self.fixture_file(fixture())),'--output',str(output)],self.never_native),2)
    def test_live_without_new_permit_denied_before_backend(self):self.assertEqual(d.main(['--mode','live','--output',str(self.output())],self.never_native),2);self.assertEqual(SyntheticTests.native_calls,0)
    def test_design_approval_not_execution_authority(self):
        permit=future_permit();permit['decision']='APPROVED_FOR_SCOPED_DIAGNOSTIC_DESIGN_ONLY';p=self.fixture_file(permit)
        with self.assertRaisesRegex(ValueError,'NEW_INDEPENDENT_EXECUTION_AUTHORITY_REQUIRED'):d.validate_live_permit(p,d.digest(p.read_bytes()),Path(permit['output_root']))
        self.assertEqual(SyntheticTests.native_calls,0)
    def test_consumed_os_reentry_not_gui_execution_authority(self):
        permit=future_permit();permit['decision']='D_PAGEFILE_REENTRY2_ONE_SHOT_SYSTEM_MANAGED_AUTHORIZED';p=self.fixture_file(permit)
        with self.assertRaisesRegex(ValueError,'NEW_INDEPENDENT_EXECUTION_AUTHORITY_REQUIRED'):d.validate_live_permit(p,d.digest(p.read_bytes()),Path(permit['output_root']))
    def test_wrong_tool_pin_reject(self):
        permit=future_permit();permit['tool_sha256']='0'*64;p=self.fixture_file(permit)
        with self.assertRaisesRegex(ValueError,'EXACT_TOOL_SCHEMA_PIN'):d.validate_live_permit(p,d.digest(p.read_bytes()),Path(permit['output_root']))
    def test_wrong_schema_pin_reject(self):
        permit=future_permit();permit['schema_sha256']='0'*64;p=self.fixture_file(permit)
        with self.assertRaisesRegex(ValueError,'EXACT_TOOL_SCHEMA_PIN'):d.validate_live_permit(p,d.digest(p.read_bytes()),Path(permit['output_root']))
    def test_wrong_origin_reference_reject(self):
        permit=future_permit();permit['original_collector_sha256']='0'*64;p=self.fixture_file(permit)
        with self.assertRaisesRegex(ValueError,'ORIGINAL_REFERENCE_PIN'):d.validate_live_permit(p,d.digest(p.read_bytes()),Path(permit['output_root']))
    def test_expired_permit_reject(self):
        permit=future_permit();permit['issued_utc']='2020-01-01T00:00:00Z';permit['expires_utc']='2020-01-02T00:00:00Z';p=self.fixture_file(permit)
        with self.assertRaisesRegex(ValueError,'PERMIT_TIME_WINDOW'):d.validate_live_permit(p,d.digest(p.read_bytes()),Path(permit['output_root']))
    def test_boolean_session_permit_reject(self):
        permit=future_permit();permit['operator_session_id']=True;p=self.fixture_file(permit)
        with self.assertRaisesRegex(ValueError,'OPERATOR_SESSION_NATIVE_INTEGER'):d.validate_live_permit(p,d.digest(p.read_bytes()),Path(permit['output_root']))
    def test_false_readonly_permit_reject(self):
        permit=future_permit();permit['read_only']=False;p=self.fixture_file(permit)
        with self.assertRaisesRegex(ValueError,'PERMIT_SCOPE_FLAGS'):d.validate_live_permit(p,d.digest(p.read_bytes()),Path(permit['output_root']))
    def test_wrong_host_permit_reject(self):
        permit=future_permit();permit['host']='WRONG_SYNTHETIC_HOST';p=self.fixture_file(permit)
        with self.assertRaisesRegex(ValueError,'PERMIT_HOST'):d.validate_live_permit(p,d.digest(p.read_bytes()),Path(permit['output_root']))
    def test_synthetic_permit_never_live_authority(self):
        permit=future_permit();p=self.fixture_file(permit)
        with self.assertRaisesRegex(ValueError,'SYNTHETIC_PERMIT_NOT_LIVE_AUTHORITY'):d.validate_live_permit(p,d.digest(p.read_bytes()),self.output())
    def test_bad_permit_pin_denied_before_backend(self):
        p=self.fixture_file({'decision':d.FUTURE_DECISION});self.assertEqual(d.main(['--mode','live','--human-execution','--permit',str(p),'--expected-permit-sha256','0'*64,'--output',str(self.output())],self.never_native),2);self.assertEqual(SyntheticTests.native_calls,0)
    def test_noncanonical_permit_reject(self):
        p=ROOT/'fixtures'/('noncanonical-'+uuid4().hex+'.json');p.write_bytes(b'{ "x": 1 }');self.assertEqual(d.main(['--mode','live','--human-execution','--permit',str(p),'--expected-permit-sha256',d.digest(p.read_bytes()),'--output',str(self.output())],self.never_native),2)
    def test_hardlink_input_reject(self):
        import os
        original=self.fixture_file(fixture());linked=ROOT/'fixtures'/('link-'+uuid4().hex+'.json');os.link(original,linked)
        with self.assertRaisesRegex(ValueError,'HARDLINK_DENIED'):d.secure_path(linked)
    def test_relative_and_traversal_paths_reject(self):
        for path in [Path('relative.json'),ROOT/'fixtures'/'..'/'escape.json']:
            with self.subTest(path=str(path)):
                with self.assertRaisesRegex(ValueError,'ABSOLUTE_NONTRAVERSAL'):d.secure_path(path)
    def test_no_ui_control_process_network_or_original_imports(self):
        source=(ROOT/'rate_readonly_gui_diag_v1.py').read_text(encoding='utf-8');tree=ast.parse(source)
        imports={n.names[0].name for n in ast.walk(tree) if isinstance(n,ast.Import)}
        self.assertFalse(imports&{'subprocess','socket','requests','urllib','sky','capture_operator_prechange','src'})
        forbidden={'SendInput','SetForegroundWindow','SetWindowTextW','SetThreadDesktop','SwitchDesktop','SetProcessWindowStation','AdjustTokenPrivileges','ShellExecuteW','CreateProcessW','ExitWindowsEx','InitiateSystemShutdownW'}
        called={getattr(n.func,'attr',None) for n in ast.walk(tree) if isinstance(n,ast.Call)}
        self.assertFalse(called&forbidden)
        bindings={n.args[1].value for n in ast.walk(tree) if isinstance(n,ast.Call) and getattr(n.func,'id',None)=='bind' and len(n.args)>1 and isinstance(n.args[1],ast.Constant)}
        self.assertTrue(bindings<=d.ALLOWED_APIS)
    def test_native_backend_was_never_constructed(self):self.assertEqual(SyntheticTests.native_calls,0)
    def fake_call(self,policy,result,error=0,prior=999):
        class ErrorState:
            def set_last_error(self,n):self.n=n
            def get_last_error(self):return self.n
        state=ErrorState();state.n=prior
        backend=object.__new__(d.NativeBackend);backend.c=state;backend.calls=[]
        def fake():state.n=error;return result
        value,status=backend.call('GetWindowTextW',fake,policy=policy)
        return status,backend.calls[-1]
    def test_native_wrapper_clears_stale_last_error(self):
        status,c=self.fake_call('nonzero',1,0,5);self.assertEqual((status,c['last_error']),('OK',0))
    def test_native_wrapper_bool_failure_zero_error_recorded(self):self.assertEqual(self.fake_call('nonzero',0,0)[0],'ERROR')
    def test_native_wrapper_empty_vs_error(self):
        self.assertEqual(self.fake_call('zero_error',0,0)[0],'EMPTY');self.assertEqual(self.fake_call('zero_error',0,5)[0],'ERROR')
    def test_native_wrapper_expected_buffer_probe(self):
        self.assertEqual(self.fake_call('buffer_probe',0,122)[0],'EXPECTED_BUFFER_PROBE');self.assertEqual(self.fake_call('buffer_probe',0,5)[0],'ERROR')
    def test_native_wrapper_localfree_null_success(self):self.assertEqual(self.fake_call('local_free',None,0)[0],'OK')
    def test_unraisable_callback_error_recorded_and_hook_restored(self):
        from types import SimpleNamespace
        original=sys.unraisablehook;errors=[]
        def fake():sys.unraisablehook(SimpleNamespace(exc_type=RuntimeError,exc_value=RuntimeError('SYNTHETIC_UNRAISABLE')));return 1
        self.assertEqual(d.callback_error_guard(fake,errors),1);self.assertIs(sys.unraisablehook,original);self.assertEqual(errors[0]['reason'],'SYNTHETIC_UNRAISABLE')
    def test_callback_action_exception_restores_hook(self):
        original=sys.unraisablehook
        def fake():raise RuntimeError('SYNTHETIC_ACTION')
        with self.assertRaisesRegex(RuntimeError,'SYNTHETIC_ACTION'):d.callback_error_guard(fake,[])
        self.assertIs(sys.unraisablehook,original)
    def test_unknown_observation_is_not_claimed_zero(self):
        f=fixture();f['windows'][0]['title_complete']=False;r=self.blocked(f,'UNRELIABLE_WINDOW_OBSERVATION:1');self.assertFalse(r['original_logic_audit']['count_determinate']);self.assertEqual(r['original_logic_audit']['count_outcome'],'INDETERMINATE')
    def test_determinate_zero_vs_multiple_outcomes(self):
        self.assertEqual(self.report(fixture([]))['original_logic_audit']['count_outcome'],'ZERO_MATCHES');self.assertEqual(self.report(fixture([window(),window(2)]))['original_logic_audit']['count_outcome'],'MULTIPLE_MATCHES')
    def test_native_wrapper_python_call_exception_recorded(self):
        class ErrorState:
            def set_last_error(self,n):self.n=n
            def get_last_error(self):return self.n
        backend=object.__new__(d.NativeBackend);backend.c=ErrorState();backend.calls=[]
        def fake():raise RuntimeError('SYNTHETIC_ARGUMENT_ERROR')
        with self.assertRaisesRegex(RuntimeError,'SYNTHETIC_ARGUMENT_ERROR'):backend.call('GetWindowTextW',fake)
        self.assertEqual(backend.calls[-1]['status'],'ERROR');self.assertIsNone(backend.calls[-1]['result'])
    def test_enumeration_trace_contradiction_is_indeterminate(self):
        f=fixture();f['enumeration']['api_calls'][0].update(result=0,status='ERROR');r=self.blocked(f,'ENUMERATION_TRACE_INCONSISTENT');self.assertFalse(r['original_logic_audit']['count_determinate'])
    def test_enumeration_error_code_range_reject(self):
        f=fixture();f['enumeration']['last_error']=2**32
        with self.assertRaisesRegex(ValueError,'ENUM_WIN32_ERROR_RANGE'):d.evaluate(f,'SYNTHETIC')
    def test_output_identity_rechecked_before_write(self):
        from unittest.mock import patch
        output=self.output();output.mkdir()
        with patch.object(d,'secure_path',side_effect=ValueError('SYNTHETIC_REPARSE_DETECTED')):
            with self.assertRaisesRegex(ValueError,'SYNTHETIC_REPARSE_DETECTED'):d.write_new(output,'evidence.json',{})
        self.assertFalse((output/'evidence.json').exists())

if __name__=='__main__':
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(SyntheticTests)
    ids=[t.id() for t in suite];result=unittest.TextTestRunner(verbosity=2).run(suite)
    record={'status':'PASS_SYNTHETIC_ENGINEERING_ONLY' if result.wasSuccessful() and not result.skipped else 'FAIL_SYNTHETIC_ENGINEERING','tests':result.testsRun,'test_ids':ids,'failures':[{'id':t.id(),'traceback':s} for t,s in result.failures],'errors':[{'id':t.id(),'traceback':s} for t,s in result.errors],'skips':len(result.skipped),'native_gui_execution':0,'native_factory_calls':SyntheticTests.native_calls,'rate_tests':0,'source_tool_sha256':d.digest((ROOT/'rate_readonly_gui_diag_v1.py').read_bytes()),'schema_sha256':d.digest((ROOT/'GUI_DIAGNOSTIC_EVIDENCE_SCHEMA_V1.json').read_bytes()),'schema_validation':'Independent strict declared-keyword subset, not a full general Draft2020 implementation','all_negative_synthetic_artifacts_preserved':True}
    with (ROOT/('SYNTHETIC_TEST_RESULT_'+uuid4().hex+'.json')).open('xb') as f:f.write(json.dumps(record,sort_keys=True,indent=2).encode())
    raise SystemExit(0 if record['status']=='PASS_SYNTHETIC_ENGINEERING_ONLY' else 1)
