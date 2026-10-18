"""Source-bound offline tests. Network, process, registry and native calls are denied."""
import argparse,hashlib,io,json,os,re,sys,unittest
from pathlib import Path
S=Path(__file__).resolve().parent
p=argparse.ArgumentParser();p.add_argument('--output',required=True);args=p.parse_args();out=Path(args.output)
if not out.is_absolute() or out!=out.resolve() or any(x in ('.','..') for x in re.split(r'[/\\]',args.output)) or re.fullmatch('[A-Za-z0-9_-]{1,64}',out.name) is None:raise SystemExit('OUTPUT_ALIAS')
runner=Path(os.environ['RUNNER_TEMP']).resolve() if os.environ.get('GITHUB_ACTIONS')=='true' else None
if not((runner and out.is_relative_to(runner) and out!=runner) or out.parent.parent==Path('D:/Codex') and re.fullmatch('RATE-PF002-C04-R2-(Evidence|Independent)-[0-9]{8}-[0-9]{4,6}',out.parent.name)):raise SystemExit('APPROVED_NEW_OUTPUT_ONLY')
for q in (out,*out.parents):
 if q.exists() and (q.is_symlink() or getattr(q.lstat(),'st_file_attributes',0)&0x400):raise SystemExit('OUTPUT_REPARSE')
sys.path.insert(0,str(S));import source_integrity
source_integrity.closed(S)
out.mkdir(parents=True,exist_ok=False);violations=[]
def audit(event,args):
 if event.startswith(('ctypes.','socket.','subprocess.','os.spawn','winreg.')) or event=='os.system':violations.append(event);raise PermissionError('OFFLINE_ONLY')
 if event=='open':
  p,mode,flags=args;write=isinstance(mode,str) and any(x in mode for x in 'wax+') or isinstance(flags,int) and flags&(os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_APPEND|os.O_TRUNC)
  if write and not isinstance(p,int) and not Path(os.fsdecode(p)).resolve().is_relative_to(out):raise PermissionError('OUTPUT_ONLY')
sys.addaudithook(audit)
import test_preauth
test_preauth.OUT=out
class Recorded(unittest.TextTestResult):
 def __init__(self,*a,**k):super().__init__(*a,**k);self.ids=[]
 def startTest(self,t):super().startTest(t);self.ids.append(t.id())
stream=io.StringIO();suite=unittest.defaultTestLoader.loadTestsFromModule(test_preauth)
r=unittest.TextTestRunner(stream=stream,verbosity=2,resultclass=Recorded).run(suite)
ok=r.wasSuccessful() and not(r.skipped or r.expectedFailures or r.unexpectedSuccesses or violations)
value={'status':'PASS' if ok else 'FAIL','tests':r.testsRun,'test_ids':r.ids,'source_manifest_sha256':hashlib.sha256((S/'SOURCE_MANIFEST_V1.json').read_bytes()).hexdigest(),'python_version':sys.version,'errors':[{'id':t.id(),'traceback':v} for t,v in r.errors],'failures':[{'id':t.id(),'traceback':v} for t,v in r.failures],'skips':len(r.skipped),'relaxed_assertions':0,'failure_whitelists':0,'expected_failures':len(r.expectedFailures),'unexpected_successes':len(r.unexpectedSuccesses),'boundary_violations':violations,'native_calls':0,'original_host_queries':0,'realm':'OFFLINE_SYNTHETIC_TRANSPORT_NOT_NATIVE_AUTHORIZATION','head':os.environ.get('GITHUB_SHA')}
(out/'TEST_RESULT.json').write_text(json.dumps(value,sort_keys=True,indent=2)+'\n',encoding='utf-8');(out/'RAW_TEST_LOG.txt').write_text(stream.getvalue(),encoding='utf-8')
print(json.dumps({'status':value['status'],'tests':r.testsRun}));raise SystemExit(0 if ok else 1)
