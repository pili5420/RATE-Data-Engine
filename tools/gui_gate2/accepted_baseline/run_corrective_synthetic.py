"""One complete inherited+new synthetic run, with original raw results retained."""
import importlib.util,json,sys,unittest
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch
E=Path(__file__).resolve().parent
sys.path.insert(0,str(E))
import test_title_reliability_synthetic as new
base=new.base;d=new.d
inherited=unittest.defaultTestLoader.loadTestsFromTestCase(base.SyntheticTests)
added=unittest.defaultTestLoader.loadTestsFromTestCase(new.TitleReliabilityTests)
old_ids=[t.id() for t in inherited];new_ids=[t.id() for t in added]
assert len(old_ids)==91
suite=unittest.TestSuite([inherited,added])
with patch('ctypes.WinDLL',side_effect=AssertionError('NATIVE_DLL_BINDING_FORBIDDEN_IN_SYNTHETIC_TESTS')):
    result=unittest.TextTestRunner(verbosity=2).run(suite)
record={'status':'PASS_SYNTHETIC_CORRECTIVE_ONLY' if result.wasSuccessful() and not result.skipped else 'FAIL_SYNTHETIC_CORRECTIVE',
    'tests':result.testsRun,'inherited_count':len(old_ids),'new_count':len(new_ids),'inherited_ids':old_ids,'new_ids':new_ids,
    'failures':[{'id':t.id(),'traceback':s} for t,s in result.failures],'errors':[{'id':t.id(),'traceback':s} for t,s in result.errors],
    'skips':len(result.skipped),'relaxed_assertions':0,'failure_whitelists':0,'native_factory_calls':base.SyntheticTests.native_calls,
    'native_gui_diagnostic':0,'native_dll_bindings':0,'rate_tests':0,
    'tool_sha256':d.digest((E/'rate_readonly_gui_diag_v2.py').read_bytes()),'schema_sha256':d.digest(d.SCHEMA.read_bytes()),
    'schema_validation':'Independent strict declared-keyword subset; not a general Draft2020 validator',
    'fake_native_window_path':'In-memory ctypes buffers and fake functions; NativeBackend.__init__ never called'}
with (E/('CORRECTIVE_SYNTHETIC_RESULT_'+uuid4().hex+'.json')).open('xb') as f:f.write(json.dumps(record,sort_keys=True,indent=2).encode())
print(json.dumps({k:v for k,v in record.items() if k not in {'failures','errors','inherited_ids','new_ids'}}))
raise SystemExit(0 if record['status']=='PASS_SYNTHETIC_CORRECTIVE_ONLY' else 1)
