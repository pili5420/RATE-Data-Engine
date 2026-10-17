"""Run new Round2 offline tests. Full frozen223 run in the external quarantine harness."""
import argparse,ctypes,hashlib,importlib.util,json,unittest
from pathlib import Path
from unittest.mock import patch
P=Path(__file__).resolve().parent
def load(name,path):
    s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
def main(argv=None):
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);args=parser.parse_args(argv)
    b=load('round2_pretest_boundary',P/'boundary_check.py');b.audit_boundary(P);out=b.evidence_path(args.output)
    b.need(out.parent.is_dir() and not out.exists(),'NEW_EXTERNAL_TEST_OUTPUT_REQUIRED');out.mkdir()
    tests=load('round2_tests',P/'test_round2_corrective.py');tests.WORK=out
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(tests.Round2Tests);ids=[t.id() for t in suite]
    with patch('ctypes.WinDLL',side_effect=AssertionError('NATIVE_DLL_FORBIDDEN')) as forbidden:result=unittest.TextTestRunner(verbosity=2).run(suite)
    ok=result.wasSuccessful() and not result.skipped and not result.expectedFailures and forbidden.call_count==0
    r={'status':'PASS_ROUND2_OFFLINE_ONLY' if ok else 'FAIL_ROUND2','tests':result.testsRun,'test_ids':ids,'failures':[{'id':t.id(),'traceback':s} for t,s in result.failures],'errors':[{'id':t.id(),'traceback':s} for t,s in result.errors],'skips':len(result.skipped),'expected_failures':len(result.expectedFailures),'relaxed_assertions':0,'failure_whitelists':0,'native_dll_calls':forbidden.call_count,'gate2_final_status':'BLOCKED_PENDING_SEPARATE_IDENTITY_RESOLUTION_AND_REVIEW','source_tool_sha256':hashlib.sha256((P/'identity_binding.py').read_bytes()).hexdigest()}
    with (out/'ROUND2_TEST_RESULT.json').open('xb') as f:f.write(json.dumps(r,sort_keys=True,indent=2).encode())
    print(json.dumps({k:v for k,v in r.items() if k not in {'test_ids','failures','errors'}}));return 0 if ok else 1
if __name__=='__main__':raise SystemExit(main())
