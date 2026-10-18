"""Engineering test CLI only. NEVER a target acquisition or Permit CLI."""
import argparse,hashlib,io,json,os,re,sys,unittest,zipfile
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--output',required=True);p.add_argument('--reference-tree',action='store_true',help='Engineering source-reference profile, never closed bundle or target authorization');a=p.parse_args()
source=Path(__file__).resolve().parent;repo=source.parent.parent;out=Path(a.output).absolute()
valid_local=out.is_relative_to(Path(r'D:\Codex')) and any(re.fullmatch(r'RATE-PF-LRO-001-(Evidence|Independent)-[0-9]{8}-[0-9]{4}',x) for x in out.parts[2:])
runner_root=Path(os.environ['RUNNER_TEMP']).resolve() if os.environ.get('GITHUB_ACTIONS')=='true' and os.environ.get('RUNNER_TEMP') else None
valid_runner=runner_root is not None and out.is_relative_to(runner_root) and out!=runner_root
if out.exists() or not(valid_local or valid_runner):raise SystemExit('FRESH_SCOPED_ENGINEERING_TEST_OUTPUT_REQUIRED')
for parent in out.parents:
 if parent.exists() and (parent.is_symlink() or getattr(parent.stat(),'st_file_attributes',0)&0x400):raise SystemExit('REPARSE_OUTPUT_FORBIDDEN')
out.mkdir(parents=True,exist_ok=False)
prior=repo/'tools'/'pagefile_non_gui_evidence'
# Pre-import safety: no repository namespace or dependency is imported first.
for directory in [repo/'tools',prior,source]:
 if any(p.name.startswith('__init__.') for p in directory.iterdir()):raise SystemExit('PREIMPORT_NAMESPACE_INITIALIZER_FORBIDDEN')
if any(p.name.startswith('tools.') for p in repo.iterdir()):raise SystemExit('PREIMPORT_ROOT_NAMESPACE_SHADOW')
if any(p.suffix.lower() in ('.pyd','.so','.dll','.pyc') for p in source.iterdir()):raise SystemExit('PREIMPORT_NATIVE_OR_COMPILED_INJECTION')
sys.path.insert(0,str(source))
from verify_bundle import verify,verify_reference_tree
bundle_result=(verify_reference_tree if a.reference_tree else verify)(repo)
sys.path[:0]=[str(repo),str(prior)]
files=[p for p in source.iterdir() if p.is_file()]+[prior/n for n in ['evidence.py','fixtures.py','test_evidence.py','evaluate_runner.py']]
manifest={p.relative_to(repo).as_posix():dict(sha256=hashlib.sha256(p.read_bytes()).hexdigest(),bytes=p.stat().st_size) for p in sorted(files)}
(out/'SOURCE_MANIFEST.json').write_text(json.dumps(manifest,sort_keys=True,indent=2)+'\n',encoding='utf-8')
with zipfile.ZipFile(out/'SOURCE_SNAPSHOT.zip','x',zipfile.ZIP_DEFLATED) as z:
 for name in manifest:z.writestr(name,(repo/name).read_bytes())
violations=[]
def audit(event,args):
 if event.startswith(('ctypes.','socket.','subprocess.','os.spawn','winreg.')) or event=='os.system':violations.append(event);raise PermissionError('OFFLINE_ONLY:'+event)
 if event=='open':
  path,mode,flags=args;writing=(isinstance(mode,str) and any(c in mode for c in 'wax+')) or (isinstance(flags,int) and flags&(os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND))
  if writing and not isinstance(path,int) and not Path(os.fsdecode(path)).resolve().is_relative_to(out):violations.append('OUTSIDE_WRITE');raise PermissionError('OUTSIDE_OUTPUT_WRITE')
sys.addaudithook(audit)
class Recorded(unittest.TextTestResult):
 def __init__(self,*a,**k):super().__init__(*a,**k);self.ids=[]
 def startTest(self,t):super().startTest(t);self.ids.append(t.id())
stream=io.StringIO()
try:
 import test_evidence
 from tools.pagefile_limited_readonly_authorization import test_candidate
 test_candidate.ENGINEERING_OUTPUT_ROOT=out
 suites=[unittest.defaultTestLoader.loadTestsFromModule(x) for x in [test_evidence,test_candidate]]
 counts=[x.countTestCases() for x in suites]
 result=unittest.TextTestRunner(stream=stream,resultclass=Recorded,verbosity=2).run(unittest.TestSuite(suites))
 ok=result.wasSuccessful() and not(result.skipped or result.expectedFailures or result.unexpectedSuccesses or violations)
 record=dict(status='PASS' if ok else 'FAIL',tests=result.testsRun,inherited=counts[0],new=counts[1],test_ids=result.ids,
  failures=[dict(id=t.id(),traceback=v) for t,v in result.failures],errors=[dict(id=t.id(),traceback=v) for t,v in result.errors],
  skips=len(result.skipped),expected_failures=len(result.expectedFailures),relaxed_assertions=0,failure_whitelists=0,boundary_violations=violations)
except Exception:
 import traceback
 stream.write(traceback.format_exc());ok=False;record=dict(status='HARNESS_ERROR',tests=0,test_ids=[])
record.update(scope='OFFLINE_SYNTHETIC_AND_STATIC_ONLY',native_collector_invocations=0,target_queries=0,formal_permit_issued=False,formal_permit_consumed=False,
 final_recommendation='BLOCKED_EXTERNAL_EVIDENCE_REQUIRED',NoAutoNext=True,bundle_profile=bundle_result,python=sys.version,executable=sys.executable)
(out/'RAW_TEST_LOG.txt').write_text(stream.getvalue(),encoding='utf-8')
(out/'TEST_RESULT.json').write_text(json.dumps(record,sort_keys=True,indent=2)+'\n',encoding='utf-8')
print(json.dumps({k:record[k] for k in ['status','tests','target_queries','formal_permit_issued']}));raise SystemExit(0 if ok else 1)
