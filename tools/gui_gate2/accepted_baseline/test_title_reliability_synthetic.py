"""Only deterministic synthetic data and fake Win32 functions; no native GUI calls."""
import ast
import copy
import ctypes
from ctypes import wintypes
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

E=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('inherited',E/'test_gui_diag_synthetic.py')
base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base)
d=base.d

def change_read(w,index,text):
    sample=w['title_observation']['reads'][index]
    sample['utf16_hex']=text.encode('utf-16-le').hex()
    c=w['api_calls'][sample['api_call_index']];c.update(result=len(text.encode('utf-16-le'))//2,status='OK' if text else 'EMPTY')

def estimates(w,before,after):
    for sample,n in zip(w['title_observation']['length_samples'],[before,after]):
        w['api_calls'][sample['api_call_index']].update(result=n,status='OK' if n else 'EMPTY')
    w['title_length']=before

def fake_backend(module,*,titles=None,lengths=None,fail_read=None,read_results=None,identities=None,alive=None):
    """Exercise the real window() Python path using in-memory API stand-ins only.
    Neither NativeBackend.__init__ nor any WinDLL/OS window query is invoked.
    """
    b=object.__new__(module.NativeBackend);b.calls=[]
    state={'error':0,'reads':0,'lengths':0,'identities':0,'alive':0}
    titles=titles or ['虛擬記憶體','虛擬記憶體'];lengths=[5,5] if lengths is None else lengths
    identities=identities or [(101,201)]*3;alive=[1]*3 if alive is None else alive
    def reset(n):state['error']=n
    b.c=SimpleNamespace(**{n:getattr(ctypes,n) for n in ['create_unicode_buffer','byref','sizeof','c_wchar','string_at','addressof']},set_last_error=reset,get_last_error=lambda:state['error'])
    b.w=wintypes
    def iswindow(hwnd):
        i=state['alive'];state['alive']+=1;return alive[min(i,len(alive)-1)]
    def owner(hwnd,pid):
        i=state['identities'];state['identities']+=1;p,t=identities[min(i,len(identities)-1)];pid._obj.value=p;return t
    def length(hwnd):
        i=state['lengths'];state['lengths']+=1;return lengths[min(i,len(lengths)-1)]
    def read(hwnd,buffer,capacity):
        i=state['reads'];state['reads']+=1
        if fail_read==i:state['error']=5;return 0
        text=titles[min(i,len(titles)-1)];raw=text.encode('utf-16-le',errors='surrogatepass')+b'\0\0'
        ctypes.memmove(ctypes.addressof(buffer),raw,min(len(raw),ctypes.sizeof(buffer)))
        return read_results[i] if read_results is not None else len(raw)//2-1
    def classname(hwnd,buffer,capacity):buffer.value='#32770';return 6
    b.u=SimpleNamespace(IsWindow=iswindow,GetWindowThreadProcessId=owner,IsWindowVisible=lambda hwnd:1,
        GetClassNameW=classname,GetWindowTextLengthW=length,GetWindowTextW=read,GetThreadDesktop=lambda tid:1)
    def session(pid):
        module.NativeBackend.required(b,'ProcessIdToSessionId',lambda:1)
        return 1
    def object_name(handle):
        module.NativeBackend.required(b,'GetUserObjectInformationW',lambda:1)
        return 'Default'
    b.session=session;b.object_name=object_name;b.process=lambda pid,query_token:copy.deepcopy(base.window()['process'])
    return b,state

class TitleReliabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema=json.loads(d.SCHEMA.read_bytes())
        (E/'fixtures').mkdir(exist_ok=True);(E/'synthetic_runs').mkdir(exist_ok=True)
    report=base.SyntheticTests.report
    blocked=base.SyntheticTests.blocked
    fixture_file=base.SyntheticTests.fixture_file
    output=base.SyntheticTests.output
    never_native=base.SyntheticTests.never_native
    def unknown(self,w,reason=None):
        r=self.blocked(base.fixture([w]),'UNRELIABLE_WINDOW_OBSERVATION:1')
        self.assertEqual(r['original_logic_audit']['count_outcome'],'INDETERMINATE')
        self.assertFalse(r['original_logic_audit']['count_determinate'])
        self.assertEqual(r['original_logic_audit']['filtered_windows'],0)
        self.assertIsNone(r['windows'][0]['original_match'])
        self.assertEqual(r['windows'][0]['exclusion_reason'],'UNKNOWN_OBSERVATION')
        if reason:self.assertIn(reason,r['windows'][0]['title_reliability']['reasons'])
        return r
    def test_changed_title_and_length(self):
        w=base.window();change_read(w,1,'virtual memory');estimates(w,5,14);self.unknown(w,'TITLE_CHANGED_BETWEEN_READS')
    def test_changed_title_same_length(self):
        w=base.window();change_read(w,1,'虛擬記憶題');self.unknown(w,'TITLE_CHANGED_BETWEEN_READS')
    def test_same_normalized_title_still_requires_exact_read_consistency(self):
        w=base.window(title='Virtual Memory');change_read(w,1,'virtual memory');self.unknown(w,'TITLE_CHANGED_BETWEEN_READS')
    def test_confirmation_api_failure(self):
        w=base.window();w['api_calls'][7].update(result=0,last_error=5,status='ERROR');self.unknown(w,'API_RESULT_OR_ERROR_UNRELIABLE')
    def test_consistent_zero_length_and_two_empty_reads(self):
        r=self.report(base.fixture([base.window(title='')]))
        self.assertTrue(r['windows'][0]['title']['complete']);self.assertTrue(r['original_logic_audit']['count_determinate'])
        self.assertEqual(r['original_logic_audit']['count_outcome'],'ZERO_MATCHES')
    def test_zero_estimate_nonempty_primary(self):
        w=base.window();estimates(w,0,0);self.unknown(w,'LENGTH_UNDERESTIMATES_COPIED_TEXT')
    def test_zero_primary_nonempty_confirmation(self):
        w=base.window(title='');change_read(w,1,'虛擬記憶體');self.unknown(w,'TITLE_CHANGED_BETWEEN_READS')
    def test_nonzero_estimates_both_empty_uncertain(self):
        w=base.window(title='');estimates(w,4,4);self.unknown(w,'ZERO_LENGTH_INCONSISTENCY')
    def test_legal_equal_length_overestimates_accepted(self):
        w=base.window();estimates(w,12,12);r=self.report(base.fixture([w]));self.assertEqual(r['gate']['status'],'PASS_DIAGNOSTIC_EVIDENCE_ONLY');self.assertEqual(r['windows'][0]['title']['reported_length'],12);self.assertEqual(r['windows'][0]['title']['copied_utf16_units'],5)
    def test_changing_estimates_remain_unknown_even_above_actual(self):
        w=base.window();estimates(w,12,13);self.unknown(w,'LENGTH_ESTIMATE_CHANGED')
    def test_utf16_surrogate_pair_uses_units_not_codepoints(self):
        w=base.window(title='虛擬😀記憶體');r=self.report(base.fixture([w]));self.assertTrue(r['windows'][0]['title']['complete']);self.assertEqual(r['windows'][0]['title']['copied_utf16_units'],7);self.assertEqual(r['windows'][0]['title']['codepoint_count'],6);self.assertEqual(r['original_logic_audit']['count_outcome'],'ZERO_MATCHES')
    def test_unpaired_surrogate_rejects(self):
        w=base.window();w['title_observation']['reads'][1]['utf16_hex']='00d8';w['api_calls'][7]['result']=1;self.unknown(w,'INVALID_UTF16')
    def test_capacity_minus_one_suspected_truncation(self):
        w=base.window(title='a'*4096);self.unknown(w,'POTENTIAL_TRUNCATION_OR_COPY_BOUND')
    def test_missing_terminator_rejects(self):
        w=base.window();w['title_observation']['reads'][0]['terminator_at_return']=False;self.unknown(w,'TERMINATOR_OR_EMBEDDED_NUL_UNPROVEN')
    def test_terminator_boolean_cannot_override_raw_unit(self):
        w=base.window();w['title_observation']['reads'][0]['terminator_utf16_hex']='4100';self.unknown(w,'TERMINATOR_OR_EMBEDDED_NUL_UNPROVEN')
    def test_embedded_null_even_with_claimed_absence_rejects(self):
        w=base.window();w['title_observation']['reads'][1]['utf16_hex']='0000'*5;self.unknown(w,'TERMINATOR_OR_EMBEDDED_NUL_UNPROVEN')
    def test_copy_count_trace_disagrees_with_raw_buffer(self):
        w=base.window();w['api_calls'][5]['result']=4;self.unknown(w,'COPIED_COUNT_EVIDENCE_MISMATCH')
    def test_claimed_title_disagrees_with_api_bytes(self):
        w=base.window();w['title']='虛擬記憶題';self.unknown(w,'WINDOW_TITLE_API_EVIDENCE_CONTRADICTION')
    def test_positive_return_nonzero_error_rejects(self):
        w=base.window();w['api_calls'][5]['last_error']=5;self.unknown(w,'API_RESULT_OR_ERROR_UNRELIABLE')
    def test_status_return_contradiction(self):
        w=base.window();w['api_calls'][5]['status']='EMPTY';self.unknown(w,'API_STATUS_RESULT_CONTRADICTION')
    def test_bool_api_result_is_not_integer(self):
        w=base.window();w['api_calls'][5]['result']=True;self.unknown(w,'API_RESULT_OR_ERROR_UNRELIABLE')
    def test_title_complete_true_with_missing_confirmation_rejects(self):
        w=base.window();w['title_observation']['reads'].pop();self.unknown(w,'FIXED_OBSERVATION_PLAN_INCOMPLETE')
    def test_missing_observation_field_is_strict_schema_rejection(self):
        w=base.window();del w['title_observation']
        with self.assertRaisesRegex(ValueError,'EXACT_SCHEMA_KEYS'):d.evaluate(base.fixture([w]),'SYNTHETIC')
    def test_unknown_title_cannot_make_second_known_match_unique(self):
        w=base.window(2);change_read(w,1,'虛擬記憶題');r=self.blocked(base.fixture([base.window(),w]),'UNRELIABLE_WINDOW_OBSERVATION:2');self.assertEqual(r['original_logic_audit']['filtered_windows'],1);self.assertEqual(r['original_logic_audit']['count_outcome'],'INDETERMINATE')
    def test_hwnd_changed_between_reads(self):
        w=base.window();w['title_observation']['reads'][1]['hwnd']=2;self.unknown(w,'HWND_CHANGED_DURING_OBSERVATION')
    def test_pid_changed_after_title(self):
        w=base.window();w['title_observation']['identities'][1]['pid']=999;self.unknown(w,'WINDOW_IDENTITY_CHANGED_DURING_OBSERVATION')
    def test_tid_changed_after_process(self):
        w=base.window();w['title_observation']['identities'][2]['tid']=999;self.unknown(w,'WINDOW_IDENTITY_CHANGED_DURING_OBSERVATION')
    def test_identity_api_return_disagrees(self):
        w=base.window();w['api_calls'][9]['result']=999;self.unknown(w,'IDENTITY_API_EVIDENCE_MISMATCH')
    def test_destroyed_hwnd_between_reads(self):
        w=base.window();w['api_calls'][8].update(result=0,status='ERROR');self.unknown(w,'IDENTITY_API_EVIDENCE_MISMATCH')
    def test_reused_api_reference_rejects(self):
        w=base.window();w['title_observation']['reads'][1]['api_call_index']=5;self.unknown(w,'API_LINK_REUSED')
    def test_extra_title_api_read_is_not_accepted(self):
        w=base.window();w['api_calls'].append(base.call('GetWindowTextW',result=5));self.unknown(w,'FIXED_TITLE_API_ORDER_OR_COUNT')
    def test_title_read_order_reversal_rejects(self):
        w=base.window();w['title_observation']['reads'].reverse();self.unknown(w,'FIXED_OBSERVATION_PLAN_INCOMPLETE')
    def test_boolean_api_reference_rejects(self):
        w=base.window();w['title_observation']['reads'][0]['api_call_index']=True
        with self.assertRaisesRegex(ValueError,'TITLE_API_INDEX'):d.evaluate(base.fixture([w]),'SYNTHETIC')
    def test_inconsistent_title_does_not_leak_unrelated_raw_hex(self):
        w=base.window(title='PRIVATE_TITLE');w['process']['image']=r'C:\Apps\browser.exe';change_read(w,1,'PRIVATE_OTHER');r=self.unknown(w);raw=d.canonical(r);self.assertNotIn(b'PRIVATE_TITLE',raw);self.assertNotIn(w['title_observation']['reads'][0]['utf16_hex'].encode(),raw)
    def test_no_atomic_snapshot_claim(self):
        r=self.report();self.assertIs(r['windows'][0]['title_reliability']['atomic_snapshot'],False)
    def test_new_schema_rejects_old_version(self):
        r=self.report();r['schema_version']='RATE_READ_ONLY_GUI_DIAGNOSTIC_V1'
        with self.assertRaises(AssertionError):base.schema_check(r,self.schema)
    def test_new_schema_requires_reliability_evidence(self):
        r=self.report();del r['windows'][0]['title_reliability']
        with self.assertRaises(AssertionError):base.schema_check(r,self.schema)
    def test_native_fixed_two_reads_even_when_empty(self):
        b,state=fake_backend(d,titles=['',''],lengths=[0,0]);w=b.window(1);self.assertTrue(w['title_complete']);self.assertEqual(state['reads'],2);self.assertEqual(state['lengths'],2);self.report(base.fixture([w]))
    def test_native_legal_overestimate_no_retry(self):
        b,state=fake_backend(d,lengths=[12,12]);w=b.window(1);self.assertTrue(w['title_complete']);self.assertEqual(state['reads'],2);self.assertEqual(self.report(base.fixture([w]))['gate']['status'],'PASS_DIAGNOSTIC_EVIDENCE_ONLY')
    def test_native_changed_same_length_false_complete(self):
        b,state=fake_backend(d,titles=['虛擬記憶體','虛擬記憶題']);w=b.window(1);self.assertFalse(w['title_complete']);self.assertEqual(state['reads'],2);self.unknown(w,'TITLE_CHANGED_BETWEEN_READS')
    def test_native_confirmation_failure_no_third_read(self):
        b,state=fake_backend(d,fail_read=1);w=b.window(1);self.assertFalse(w['title_complete']);self.assertEqual(state['reads'],2);self.assertEqual(w['api_calls'][-1]['last_error'],5);self.unknown(w)
    def test_native_primary_failure_no_confirmation(self):
        b,state=fake_backend(d,fail_read=0);w=b.window(1);self.assertFalse(w['title_complete']);self.assertEqual(state['reads'],1);self.assertEqual(state['lengths'],1);self.unknown(w)
    def test_native_changed_length_stops_before_confirmation(self):
        b,state=fake_backend(d,lengths=[5,6]);w=b.window(1);self.assertFalse(w['title_complete']);self.assertEqual(state['reads'],1);self.unknown(w)
    def test_native_primary_zero_inconsistent_stops(self):
        b,state=fake_backend(d,titles=['','']);w=b.window(1);self.assertFalse(w['title_complete']);self.assertEqual(state['reads'],1);self.unknown(w)
    def test_native_suspected_truncation_stops(self):
        b,state=fake_backend(d,titles=['x'*4096],read_results=[4096]);w=b.window(1);self.assertFalse(w['title_complete']);self.assertEqual(state['reads'],1);self.unknown(w)
    def test_native_surrogate_pair_observation(self):
        b,state=fake_backend(d,titles=['虛擬😀記憶體']*2,lengths=[7,7]);w=b.window(1);self.assertTrue(w['title_complete']);self.assertEqual(w['title_copied'],7);self.assertEqual(len(w['title']),6);self.report(base.fixture([w]))
    def test_native_owner_change_after_title_blocks(self):
        b,state=fake_backend(d,identities=[(101,201),(999,201)]);w=b.window(1);self.assertFalse(w['title_complete']);self.unknown(w)
    def test_native_owner_change_after_process_blocks(self):
        b,state=fake_backend(d,identities=[(101,201),(101,201),(101,999)]);w=b.window(1);self.assertFalse(w['title_complete']);self.unknown(w)
    def test_failed_attempt_cannot_be_reused_or_overwritten(self):
        w=base.window();change_read(w,1,'虛擬記憶題');output=self.output();p=self.fixture_file(base.fixture([w]));args=['--mode','synthetic','--fixture',str(p),'--output',str(output)]
        self.assertEqual(d.main(args,self.never_native),2)
        before={q.name:q.read_bytes() for q in output.iterdir()};self.assertIn('HALTED.json',before)
        self.assertEqual(d.main(args,self.never_native),2);self.assertEqual({q.name:q.read_bytes() for q in output.iterdir()},before)
    def test_original_91_assertions_retained(self):
        old=ast.parse((E/'baseline_source'/'test_gui_diag_synthetic.py').read_text(encoding='utf-8'))
        new=ast.parse((E/'test_gui_diag_synthetic.py').read_text(encoding='utf-8'))
        def assertions(tree):
            cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='SyntheticTests');out={}
            for method in cls.body:
                if isinstance(method,ast.FunctionDef) and method.name.startswith('test_'):
                    out[method.name]=[ast.dump(n,include_attributes=False) for n in ast.walk(method) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr.startswith('assert')]
            return out
        a,b=assertions(old),assertions(new);self.assertEqual(len(a),91);self.assertEqual(a,b)
    def test_red_to_green_original_native_path(self):
        spec=importlib.util.spec_from_file_location('old_gui',E/'baseline_source'/'rate_readonly_gui_diag_v1.py');old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
        before,bs=fake_backend(old,titles=['虛擬記憶體','虛擬記憶題']);oldrow=before.window(1)
        self.assertTrue(oldrow['title_complete']);self.assertEqual(bs['reads'],1)
        oldresult=old.evaluate(base.fixture([oldrow]),'SYNTHETIC');self.assertEqual(oldresult['gate']['status'],'PASS_DIAGNOSTIC_EVIDENCE_ONLY')
        after,gs=fake_backend(d,titles=['虛擬記憶體','虛擬記憶題']);newrow=after.window(1);result=self.unknown(newrow,'TITLE_CHANGED_BETWEEN_READS');self.assertEqual(gs['reads'],2)
        artifact={'scope':'SYNTHETIC_FAKE_API_NO_NATIVE_OS_CALLS','original_tool_sha256':d.digest((E/'baseline_source'/'rate_readonly_gui_diag_v1.py').read_bytes()),'original_result':oldresult,'corrected_result':result,'original_fake_api_reads':bs['reads'],'corrected_fake_api_reads':gs['reads']}
        with (self.output().with_suffix('.red-to-green.json')).open('xb') as f:f.write(d.canonical(artifact)+b'\n')
