"""Fixed offline tests only; accepts an output directory, never live evidence."""
import argparse
import hashlib
import io
import json
import os
import sys
import unittest
import zipfile
from pathlib import Path

parser=argparse.ArgumentParser();parser.add_argument('--output',required=True);args=parser.parse_args()
source=Path(__file__).resolve().parent
output=Path(args.output)
allowed=Path(r'D:\Codex')
absolute=output.absolute()
try:
    relative=absolute.relative_to(allowed)
except ValueError:
    raise SystemExit('ISOLATED_D_CODEX_OUTPUT_REQUIRED')
if not relative.parts or not relative.parts[0].startswith('RATE-RT04-') or absolute.exists():
    raise SystemExit('FRESH_RT04_OUTPUT_REQUIRED')
for parent in absolute.parents:
    if parent.exists() and parent.stat().st_file_attributes & 0x400:
        raise SystemExit('REPARSE_OUTPUT_FORBIDDEN')
output.mkdir(parents=True,exist_ok=False)
output=output.resolve()
site=Path(sys.executable).parents[1]/'Lib/site-packages'
sys.path.insert(0,str(source));sys.path.append(str(site))
import cryptography
if cryptography.__version__!='50.0.2':raise SystemExit('PINNED_PREINSTALLED_TEST_CRYPTO_REQUIRED')
manifest={p.name:{'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'bytes':p.stat().st_size} for p in sorted(source.iterdir()) if p.is_file()}
(output/'SOURCE_MANIFEST.json').write_text(json.dumps(manifest,indent=2)+'\n')
with zipfile.ZipFile(output/'SOURCE_SNAPSHOT.zip','x',compression=zipfile.ZIP_DEFLATED) as z:
    for name in manifest:z.write(source/name,name)
violations=[]
def audit(event, arguments):
    if event.startswith(('ctypes.','socket.','subprocess.','os.spawn')) or event in ('os.system','winreg.SetValue','winreg.SetValueEx','winreg.DeleteKey','winreg.DeleteValue'):
        violations.append(event);raise PermissionError('OFFLINE_BOUNDARY:'+event)
    if event=='open':
        path,mode,flags=arguments
        writing=(isinstance(mode,str) and any(c in mode for c in 'wax+')) or (isinstance(flags,int) and flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND))
        if writing and not isinstance(path,int):
            candidate=Path(os.fsdecode(path)).resolve()
            if not candidate.is_relative_to(output):
                violations.append('OUTSIDE_WRITE:'+str(candidate));raise PermissionError('OUTSIDE_EVIDENCE_WRITE')
sys.addaudithook(audit)
import test_feasibility
class Recorded(unittest.TextTestResult):
    def __init__(self,*a,**k):super().__init__(*a,**k);self.records=[]
    def startTest(self,test):super().startTest(test);self.records.append({'id':test.id(),'outcome':'STARTED','subtests':[]})
    def addSuccess(self,test):super().addSuccess(test);self.records[-1]['outcome']='PASS'
    def addFailure(self,test,err):super().addFailure(test,err);self.records[-1]['outcome']='FAIL'
    def addError(self,test,err):super().addError(test,err);self.records[-1]['outcome']='ERROR'
    def addSubTest(self,test,subtest,err):
        super().addSubTest(test,subtest,err);self.records[-1]['subtests'].append({'id':str(subtest),'outcome':'PASS' if err is None else 'FAIL'})
        if err is not None:self.records[-1]['outcome']='FAIL'
stream=io.StringIO();suite=unittest.defaultTestLoader.loadTestsFromModule(test_feasibility)
result=unittest.TextTestRunner(stream=stream,resultclass=Recorded,verbosity=2).run(suite)
good=result.wasSuccessful() and not result.skipped and not result.expectedFailures and not result.unexpectedSuccesses and not violations
record={'status':'PASS' if good else 'FAIL','scope':'OFFLINE_FINITE_MODEL_AND_DOCUMENTATION_ONLY','tests':result.testsRun,'test_ids':result.records,'failures':[{'id':t.id(),'traceback':trace} for t,trace in result.failures],'errors':[{'id':t.id(),'traceback':trace} for t,trace in result.errors],'skips':len(result.skipped),'relaxed_assertions':0,'failure_whitelists':0,'expected_failures':len(result.expectedFailures),'unexpected_successes':len(result.unexpectedSuccesses),'boundary_violations':violations,'explicit_native_GUI_identity_dispatch_calls':0,'crypto_version':cryptography.__version__,'crypto_package':cryptography.__file__,'python':sys.executable,'python_version':sys.version,'original_target_decision':'NO_GO','native_runtime_qualification':'BLOCKED','original_halt_root_cause':'UNKNOWN','compiler_or_live_process_invoked':False}
(output/'RAW_TEST_LOG.txt').write_text(stream.getvalue(),encoding='utf-8')
(output/'TEST_RESULT.json').write_text(json.dumps(record,indent=2)+'\n')
print(json.dumps({'output':str(output),'status':record['status'],'tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors)}))
raise SystemExit(0 if good else 1)
