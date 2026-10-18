"""Offline engineering tests only; no original-host acquisition or live consent loader."""
import argparse,hashlib,io,json,os,re,sys,traceback,unittest,zipfile
from pathlib import Path
parser=argparse.ArgumentParser();parser.add_argument('--output',required=True);args=parser.parse_args()
source=Path(__file__).resolve().parent
manifest=json.loads((source/'SOURCE_MANIFEST_V1.json').read_bytes())
entries=manifest['files'];actual={p.name for p in source.iterdir()}
if actual!=set(entries)|{'SOURCE_MANIFEST_V1.json'}:raise SystemExit('EXACT_SOURCE_DIRECTORY_REQUIRED')
for name,row in entries.items():
    p=source/name
    if p.is_symlink() or getattr(p.stat(),'st_file_attributes',0)&0x400 or not p.is_file():raise SystemExit('SOURCE_REPARSE_FORBIDDEN')
    b=p.read_bytes()
    if row!={'sha256':hashlib.sha256(b).hexdigest(),'bytes':len(b)}:raise SystemExit('SOURCE_HASH_MISMATCH:'+name)
sys.path.append(str(source))
from offline_paths import approved_output
if Path(sys.modules['offline_paths'].__file__).resolve()!=source/'offline_paths.py':raise SystemExit('UNAPPROVED_PATH_POLICY_ORIGIN')
runner=os.environ.get('RUNNER_TEMP') if os.environ.get('GITHUB_ACTIONS')=='true' else None
out=approved_output(args.output,runner)
out.mkdir(parents=True,exist_ok=False)
(out/'SOURCE_MANIFEST.json').write_bytes((source/'SOURCE_MANIFEST_V1.json').read_bytes())
with zipfile.ZipFile(out/'SOURCE_SNAPSHOT.zip','x',zipfile.ZIP_DEFLATED) as z:
    for name in sorted(actual):z.writestr(name,(source/name).read_bytes())
violations=[]
def audit(event,args):
    if event.startswith(('ctypes.','socket.','subprocess.','os.spawn','winreg.')) or event=='os.system':
        violations.append(event);raise PermissionError('OFFLINE_BOUNDARY:'+event)
    if event=='open':
        p,mode,flags=args
        write=(isinstance(mode,str) and any(c in mode for c in 'wax+')) or (isinstance(flags,int) and flags&(os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND))
        if write and not isinstance(p,int) and not Path(os.fsdecode(p)).resolve().is_relative_to(out):
            violations.append('OUTSIDE_OUTPUT_WRITE');raise PermissionError('OUTSIDE_OUTPUT_WRITE')
sys.addaudithook(audit)
sys.path.append(str(source))
class Recorded(unittest.TextTestResult):
    def __init__(self,*a,**kw):super().__init__(*a,**kw);self.ids=[]
    def startTest(self,t):super().startTest(t);self.ids.append(t.id())
stream=io.StringIO();record={}
try:
    import personal_model,synthetic_fixtures,test_personal_model
    for name in ('personal_model','synthetic_fixtures','test_personal_model'):
        if Path(sys.modules[name].__file__).resolve()!=source/(name+'.py'):raise RuntimeError('MODULE_ORIGIN_MISMATCH')
    test_personal_model.ENGINEERING_OUTPUT_ROOT=out
    suite=unittest.defaultTestLoader.loadTestsFromModule(test_personal_model)
    result=unittest.TextTestRunner(stream=stream,verbosity=2,resultclass=Recorded).run(suite)
    ok=result.wasSuccessful() and not(result.skipped or result.expectedFailures or result.unexpectedSuccesses or violations)
    record={'status':'PASS' if ok else 'FAIL','tests':result.testsRun,'test_ids':result.ids,
            'failures':[{'id':t.id(),'traceback':v} for t,v in result.failures],
            'errors':[{'id':t.id(),'traceback':v} for t,v in result.errors],
            'skips':len(result.skipped),'expected_failures':len(result.expectedFailures),'unexpected_successes':len(result.unexpectedSuccesses),
            'relaxed_assertions':0,'failure_whitelists':0,'boundary_violations':violations}
except Exception:
    ok=False;stream.write(traceback.format_exc());record={'status':'HARNESS_ERROR','tests':0,'test_ids':[]}
record.update(scope='OFFLINE_SYNTHETIC_ONLY_NOT_RUNTIME',original_host_queries=0,formal_permit_issued=False,
              real_owner_consent_created_or_consumed=False,native_dispatches=0,NoAutoNext=True,
              python=sys.version,executable=sys.executable,CI_reported_head=os.environ.get('GITHUB_HEAD_SHA'))
(out/'RAW_TEST_LOG.txt').write_text(stream.getvalue(),encoding='utf-8')
(out/'TEST_RESULT.json').write_text(json.dumps(record,sort_keys=True,indent=2)+'\n',encoding='utf-8')
print(json.dumps({k:record[k] for k in ('status','tests','scope','original_host_queries')}))
raise SystemExit(0 if ok else 1)
