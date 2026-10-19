"""CB01 pure offline regression. All Native/network/process/registry dispatch denied."""
import argparse,hashlib,io,json,os,re,sys,unittest
from pathlib import Path
S=Path(__file__).resolve().parent;R=S.parent.parent;A=R/'tools/pf002_c04_r3_native_stage_a'
p=argparse.ArgumentParser();p.add_argument('--output',required=True);v=p.parse_args();out=Path(v.output)
if not out.is_absolute() or out!=out.resolve() or any(x in ('.','..') for x in re.split(r'[/\\]',v.output)):raise SystemExit('CB01_OUTPUT_ALIAS')
runner=Path(os.environ['RUNNER_TEMP']).resolve() if os.environ.get('GITHUB_ACTIONS')=='true' else None
local=out.parent.parent==Path('D:/Codex') and re.fullmatch(r'RATE-PF002-C04-R3-CB01-(Evidence|Independent)-[0-9]{8}-[0-9]{4,6}',out.parent.name)
if not(local or runner and out.is_relative_to(runner) and out!=runner):raise SystemExit('CB01_NEW_EVIDENCE_ROOT_ONLY')
for q in (out,*out.parents):
 if q.exists() and (q.is_symlink() or getattr(q.lstat(),'st_file_attributes',0)&0x400):raise SystemExit('CB01_OUTPUT_REPARSE')
out.mkdir(parents=True,exist_ok=False);violations=[]
def audit(event,args):
 if event.startswith(('ctypes.','socket.','subprocess.','os.spawn','os.exec','winreg.','_winapi.')) or event=='os.system':violations.append(event);raise PermissionError('CB01_OFFLINE_ONLY')
 if event=='open':
  path,mode,flags=args;write=isinstance(mode,str) and any(c in mode for c in 'wax+') or isinstance(flags,int) and flags&(os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_APPEND|os.O_TRUNC)
  if write and not isinstance(path,int) and not Path(os.fsdecode(path)).resolve().is_relative_to(out):raise PermissionError('CB01_OUTPUT_ONLY')
sys.addaudithook(audit);sys.path[:0]=[str(S),str(A)]
import source_integrity;source_integrity.closed(A)
import test_cb01;test_cb01.OUT=out
class Recorded(unittest.TextTestResult):
 def __init__(self,*a,**k):super().__init__(*a,**k);self.ids=[]
 def startTest(self,t):super().startTest(t);self.ids.append(t.id())
stream=io.StringIO();r=unittest.TextTestRunner(stream=stream,verbosity=2,resultclass=Recorded).run(unittest.defaultTestLoader.loadTestsFromModule(test_cb01))
ok=r.wasSuccessful() and not(r.skipped or r.expectedFailures or r.unexpectedSuccesses or violations)
data={'status':'PASS' if ok else 'FAIL','head':os.environ.get('GITHUB_SHA'),'tests':r.testsRun,'test_ids':r.ids,'errors':[{'id':t.id(),'traceback':v} for t,v in r.errors],'failures':[{'id':t.id(),'traceback':v} for t,v in r.failures],'skips':len(r.skipped),'expected_failures':len(r.expectedFailures),'unexpected_successes':len(r.unexpectedSuccesses),'failure_whitelists':0,'relaxed_assertions':0,'native_calls':0,'original_host_queries':0,'boundary_violations':violations,'python_version':sys.version,'source_manifest_sha256':hashlib.sha256((A/'SOURCE_MANIFEST_V1.json').read_bytes()).hexdigest(),'realm':'SYNTHETIC_CONTROL_FLOW_AND_STRICT_CONTRACT_ONLY_NOT_NATIVE_QUALIFICATION'}
(out/'TEST_RESULT.json').write_text(json.dumps(data,sort_keys=True,indent=2)+'\n',encoding='utf-8');(out/'RAW_TEST_LOG.txt').write_text(stream.getvalue(),encoding='utf-8')
print(json.dumps({'status':data['status'],'tests':data['tests']}));raise SystemExit(0 if ok else 1)
