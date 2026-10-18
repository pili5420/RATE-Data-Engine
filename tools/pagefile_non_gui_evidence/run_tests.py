"""Fixed offline test suite. Never invokes the collector or Windows providers."""
import argparse,hashlib,io,json,os,sys,unittest,zipfile
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--output',required=True);a=p.parse_args()
source=Path(__file__).resolve().parent;out=Path(a.output).absolute()
allowed=[Path(r'D:\Codex')]
if os.environ.get('GITHUB_ACTIONS')=='true' and os.environ.get('RUNNER_TEMP'):allowed.append(Path(os.environ['RUNNER_TEMP']).resolve())
if out.exists() or not any(out.is_relative_to(root) and out!=root for root in allowed):raise SystemExit('FRESH_ISOLATED_OUTPUT_REQUIRED')
for parent in out.parents:
 if parent.exists() and (parent.is_symlink() or getattr(parent.stat(),'st_file_attributes',0)&0x400):raise SystemExit('REPARSE_OUTPUT_FORBIDDEN')
out.mkdir(parents=True,exist_ok=False);out=out.resolve();sys.path.insert(0,str(source))
manifest={x.name:{'sha256':hashlib.sha256(x.read_bytes()).hexdigest(),'bytes':x.stat().st_size} for x in sorted(source.iterdir()) if x.is_file()}
(out/'SOURCE_MANIFEST.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
with zipfile.ZipFile(out/'SOURCE_SNAPSHOT.zip','x',zipfile.ZIP_DEFLATED) as z:
 for name in manifest:z.write(source/name,name)
violations=[]
def audit(event,args):
 if event.startswith(('ctypes.','socket.','subprocess.','os.spawn','winreg.')) or event=='os.system':violations.append(event);raise PermissionError('OFFLINE_ONLY:'+event)
 if event=='open':
  path,mode,flags=args
  writing=(isinstance(mode,str) and any(c in mode for c in 'wax+')) or (isinstance(flags,int) and flags&(os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND))
  if writing and not isinstance(path,int) and not Path(os.fsdecode(path)).resolve().is_relative_to(out):violations.append('OUTSIDE_WRITE');raise PermissionError('OUTSIDE_EVIDENCE_WRITE')
sys.addaudithook(audit)
try:
 import test_evidence
except Exception:
 import traceback
 trace=traceback.format_exc()
 (out/'RAW_TEST_LOG.txt').write_text(trace,encoding='utf-8')
 (out/'TEST_RESULT.json').write_text(json.dumps({'status':'HARNESS_IMPORT_ERROR','tests':0,'test_ids':[],'traceback':trace,'target_qualification':'BLOCKED'},indent=2)+'\n',encoding='utf-8')
 print(trace);raise SystemExit(1)
class Recorded(unittest.TextTestResult):
 def __init__(self,*a,**k):super().__init__(*a,**k);self.records=[]
 def startTest(self,t):super().startTest(t);self.records.append({'id':t.id(),'outcome':'STARTED','subtests':[]})
 def addSuccess(self,t):super().addSuccess(t);self.records[-1]['outcome']='PASS'
 def addFailure(self,t,e):super().addFailure(t,e);self.records[-1]['outcome']='FAIL'
 def addError(self,t,e):super().addError(t,e);self.records[-1]['outcome']='ERROR'
 def addSubTest(self,t,s,e):
  super().addSubTest(t,s,e);self.records[-1]['subtests'].append({'id':str(s),'outcome':'PASS' if e is None else 'FAIL'})
  if e is not None:self.records[-1]['outcome']='FAIL'
stream=io.StringIO();result=unittest.TextTestRunner(stream=stream,resultclass=Recorded,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(test_evidence))
good=result.wasSuccessful() and not(result.skipped or result.expectedFailures or result.unexpectedSuccesses or violations)
record={'status':'PASS' if good else 'FAIL','scope':'OFFLINE_SYNTHETIC_AND_STATIC_ONLY','tests':result.testsRun,'test_ids':result.records,'failures':[{'id':t.id(),'traceback':v} for t,v in result.failures],'errors':[{'id':t.id(),'traceback':v} for t,v in result.errors],'skips':len(result.skipped),'relaxed_assertions':0,'failure_whitelists':0,'expected_failures':len(result.expectedFailures),'unexpected_successes':len(result.unexpectedSuccesses),'boundary_violations':violations,'original_host_pagefile_queries':0,'native_GUI_dispatch':0,'target_qualification':'BLOCKED','GUI_Gate2':'BLOCKED','original_halt_root_cause':'UNKNOWN','python':sys.executable,'python_version':sys.version}
(out/'RAW_TEST_LOG.txt').write_text(stream.getvalue(),encoding='utf-8');(out/'TEST_RESULT.json').write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'status':record['status'],'tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'output':str(out)}));raise SystemExit(0 if good else 1)
