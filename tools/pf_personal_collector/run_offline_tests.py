"""Pure regression entry: source-bound inherited tests plus necessary collector negatives."""
import argparse,hashlib,io,json,os,re,sys,traceback,unittest
from pathlib import Path
SRC=Path(__file__).resolve().parent;ROOT=SRC.parent.parent;BASE=ROOT/'tools/pf_personal_trust'
def output(raw):
 p=Path(raw)
 if not p.is_absolute() or p!=p.resolve() or any(x in ('.','..') for x in re.split(r'[/\\]',raw)):raise ValueError('CANONICAL_ABSOLUTE')
 runner=Path(os.environ['RUNNER_TEMP']).resolve() if os.environ.get('GITHUB_ACTIONS')=='true' else None
 approved=runner is not None and p.is_relative_to(runner) and p!=runner
 if not approved:
  approved=p.parent.parent==Path('D:/Codex') and re.fullmatch(r'RATE-PF-PERSONAL-002-(Evidence|Independent)-[0-9]{8}-[0-9]{6}',p.parent.name) is not None
 if not approved or p.exists():raise ValueError('FRESH_APPROVED_OUTPUT_REQUIRED')
 for q in (p,*p.parents):
  if q.exists() and (q.is_symlink() or getattr(q.lstat(),'st_file_attributes',0)&0x400):raise ValueError('NO_REPARSE')
 return p
def main():
 parser=argparse.ArgumentParser();parser.add_argument('--output',required=True);a=parser.parse_args()
 sys.path.extend([str(SRC),str(BASE)])
 from runner_controller import sources
 sources()
 # Accepted inherited source manifest verifies ALL original files, not only tests.
 bm=json.loads((BASE/'SOURCE_MANIFEST_V1.json').read_bytes())
 if {p.name for p in BASE.iterdir()}!=set(bm['files'])|{'SOURCE_MANIFEST_V1.json'}:raise ValueError('BASE_EXACT_FILES')
 for name,row in bm['files'].items():
  p=BASE/name;b=p.read_bytes()
  if p.is_symlink() or row!={'sha256':hashlib.sha256(b).hexdigest(),'bytes':len(b)}:raise ValueError('BASE_UNCHANGED')
 out=output(a.output);out.mkdir(parents=True,exist_ok=False);violations=[]
 def audit(event,args):
  if event.startswith(('ctypes.','socket.','subprocess.','os.spawn','winreg.')) or event=='os.system':violations.append(event);raise PermissionError('OFFLINE_BOUNDARY')
  if event=='open':
   p,mode,flags=args
   write=(isinstance(mode,str) and any(c in mode for c in 'wax+')) or (isinstance(flags,int) and flags&(os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND))
   if write and not isinstance(p,int) and not Path(os.fsdecode(p)).resolve().is_relative_to(out):violations.append('OUTSIDE_OUTPUT_WRITE');raise PermissionError('OUTSIDE_OUTPUT_WRITE')
 sys.addaudithook(audit)
 class Recorded(unittest.TextTestResult):
  def __init__(self,*a,**kw):super().__init__(*a,**kw);self.ids=[]
  def startTest(self,t):super().startTest(t);self.ids.append(t.id())
 stream=io.StringIO()
 import test_personal_model,test_collector
 for name,folder in [('test_personal_model',BASE),('test_collector',SRC)]:
  if Path(sys.modules[name].__file__).resolve()!=folder/(name+'.py'):raise ValueError('TEST_MODULE_ORIGIN')
 test_personal_model.ENGINEERING_OUTPUT_ROOT=out
 test_collector.ENGINEERING_OUTPUT_ROOT=out
 old=unittest.defaultTestLoader.loadTestsFromModule(test_personal_model)
 if old.countTestCases()!=58:raise ValueError('INHERITED_58_COUNT')
 suite=unittest.TestSuite([old,unittest.defaultTestLoader.loadTestsFromModule(test_collector)])
 result=unittest.TextTestRunner(stream=stream,verbosity=2,resultclass=Recorded).run(suite)
 ok=result.wasSuccessful() and not(result.skipped or result.expectedFailures or result.unexpectedSuccesses or violations)
 report={'status':'PASS' if ok else 'FAIL','tests':result.testsRun,'inherited':58,'new':result.testsRun-58,'test_ids':result.ids,
 'failures':[{'id':t.id(),'traceback':v} for t,v in result.failures],'errors':[{'id':t.id(),'traceback':v} for t,v in result.errors],
 'skips':len(result.skipped),'expected_failures':len(result.expectedFailures),'unexpected_successes':len(result.unexpectedSuccesses),'relaxed_assertions':0,'failure_whitelists':0,
 'boundary_violations':violations,'native_dispatches':0,'original_host_queries':0,'owner_consent_issued':False,'NoAutoNext':True,'realm':'OFFLINE_SYNTHETIC_TESTS_ONLY_NOT_NATIVE_EVIDENCE','python':sys.version,'head':os.environ.get('GITHUB_SHA')}
 (out/'RAW_TEST_LOG.txt').write_text(stream.getvalue(),encoding='utf-8')
 (out/'TEST_RESULT.json').write_text(json.dumps(report,sort_keys=True,indent=2)+'\n',encoding='utf-8')
 print(json.dumps({k:report[k] for k in ('status','tests','inherited','new','native_dispatches')}))
 return 0 if ok else 1
if __name__=='__main__':raise SystemExit(main())
