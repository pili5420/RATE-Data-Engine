"""Run Gate2 tests only. Caller runs accepted142 separately in a disposable copy."""
import hashlib,importlib.util,json,sys,unittest
from pathlib import Path
from unittest.mock import patch
P=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('gate2_tests',P/'test_identity_binding.py');t=importlib.util.module_from_spec(spec);spec.loader.exec_module(t)
suite=unittest.defaultTestLoader.loadTestsFromTestCase(t.Gate2Tests);ids=[x.id() for x in suite]
with patch('ctypes.WinDLL',side_effect=AssertionError('NATIVE_DLL_FORBIDDEN_IN_OFFLINE_TESTS')) as forbidden:
    result=unittest.TextTestRunner(verbosity=2).run(suite)
passed=result.wasSuccessful() and not result.skipped and forbidden.call_count==0
record={'status':'PASS_OFFLINE_GATE2_SYNTHETIC_ONLY' if passed else 'FAIL_OFFLINE_GATE2_SYNTHETIC','tests':result.testsRun,'test_ids':ids,
    'failures':[{'id':x.id(),'traceback':trace} for x,trace in result.failures],'errors':[{'id':x.id(),'traceback':trace} for x,trace in result.errors],
    'skips':len(result.skipped),'relaxed_assertions':0,'failure_whitelists':0,'native_dll_calls':forbidden.call_count,'native_enumerations':0,'execution_permits':0,
    'tool_sha256':hashlib.sha256((P/'identity_binding.py').read_bytes()).hexdigest(),'schema_sha256':hashlib.sha256((P/'TARGET_IDENTITY_BINDING_SCHEMA_V1.json').read_bytes()).hexdigest(),
    'gate2_final_status':'BLOCKED_PENDING_SEPARATE_IDENTITY_RESOLUTION_AND_REVIEW'}
with (P/'GATE2_SYNTHETIC_RESULT.json').open('xb') as f:f.write(json.dumps(record,sort_keys=True,indent=2).encode('utf-8'))
print(json.dumps({k:v for k,v in record.items() if k not in {'test_ids','failures','errors'}}))
raise SystemExit(0 if passed else 1)
