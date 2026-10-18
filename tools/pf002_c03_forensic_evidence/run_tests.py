import argparse,hashlib,io,json,os,re,sys,unittest
from pathlib import Path
S=Path(__file__).resolve().parent
a=argparse.ArgumentParser();a.add_argument('--output',required=True);args=a.parse_args();out=Path(args.output)
if not out.is_absolute() or out!=out.resolve() or any(x in ('.','..') for x in re.split(r'[/\\]',args.output)) or any(re.search(r'[:<>"|?*]',x) for x in out.parts[1:]):raise SystemExit('OUTPUT_ALIAS')
if re.fullmatch('[A-Za-z0-9_-]{1,64}',out.name) is None:raise SystemExit('OUTPUT_LEAF_BOUND')
runner=Path(os.environ['RUNNER_TEMP']).resolve() if os.environ.get('GITHUB_ACTIONS')=='true' else None
if not((runner and out.is_relative_to(runner) and out!=runner) or out.parent.parent==Path('D:/Codex') and re.fullmatch('RATE-PF002-C03-(Evidence|Independent)-[0-9]{8}-[0-9]{4,6}',out.parent.name)):raise SystemExit('APPROVED_NEW_OUTPUT_ONLY')
for p in (out,*out.parents):
 if p.exists() and (p.is_symlink() or getattr(p.lstat(),'st_file_attributes',0)&0x400):raise SystemExit('OUTPUT_REPARSE')
sys.path.append(str(S));import source_loader
source_loader.closed_bytes(S)
out.mkdir(parents=True,exist_ok=False);violations=[]
def audit(event,args):
 if event.startswith(('ctypes.','socket.','subprocess.','os.spawn','winreg.')) or event=='os.system':violations.append(event);raise PermissionError('OFFLINE_ONLY')
 if event=='open':
  p,mode,flags=args;write=isinstance(mode,str) and any(x in mode for x in 'wax+') or isinstance(flags,int) and flags&(os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_APPEND|os.O_TRUNC)
  if write and not isinstance(p,int) and not Path(os.fsdecode(p)).resolve().is_relative_to(out):raise PermissionError('OUTPUT_ONLY')
sys.addaudithook(audit)
import test_evidence
test_evidence.ENGINEERING_OUTPUT_ROOT=out
class Recorded(unittest.TextTestResult):
 def __init__(self,*a,**k):super().__init__(*a,**k);self.ids=[]
 def startTest(self,t):super().startTest(t);self.ids.append(t.id())
stream=io.StringIO();suite=unittest.TestSuite([unittest.defaultTestLoader.loadTestsFromModule(m) for m in (test_evidence,)])
r=unittest.TextTestRunner(stream=stream,verbosity=2,resultclass=Recorded).run(suite)
ok=r.wasSuccessful() and not(r.skipped or r.expectedFailures or r.unexpectedSuccesses or violations)
result={'status':'PASS' if ok else 'FAIL','tests':r.testsRun,'test_ids':r.ids,'source_manifest_sha256':hashlib.sha256((S/'SOURCE_MANIFEST_V1.json').read_bytes()).hexdigest(),'python_version':sys.version,'errors':[{'id':t.id(),'traceback':v} for t,v in r.errors],'failures':[{'id':t.id(),'traceback':v} for t,v in r.failures],
 'skips':len(r.skipped),'relaxed_assertions':0,'failure_whitelists':0,'expected_failures':len(r.expectedFailures),'unexpected_successes':len(r.unexpectedSuccesses),'boundary_violations':violations,'native_calls':0,'original_host_queries':0,'realm':'OFFLINE_FAKE_API_NOT_NATIVE_ROOT_CAUSE_PROOF','head':os.environ.get('GITHUB_SHA')}
(out/'TEST_RESULT.json').write_text(json.dumps(result,sort_keys=True,indent=2)+'\n',encoding='utf-8');(out/'RAW_TEST_LOG.txt').write_text(stream.getvalue(),encoding='utf-8')
print(json.dumps({'status':result['status'],'tests':r.testsRun}));raise SystemExit(0 if ok else 1)
