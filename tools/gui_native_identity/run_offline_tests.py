"""Synthetic tests only; no live target, adapter binder or Permit loader."""
import argparse,ctypes,hashlib,json,os,re,subprocess,sys,time,unittest
from pathlib import Path
from uuid import uuid4

def allowed_crash_child(exe,cmd,python,probe,root):
 if exe not in (None,python):return False
 prefix=[python,'-I','-B','-S',probe,'--root',str(root)]
 pattern=re.escape(subprocess.list2cmdline(prefix))+r' --mode (after_lock|after_attempt|after_claim|after_result) --attempt SYNTHETIC-[A-Za-z0-9-]{8,96} --nonce SYNTHETIC-[A-Za-z0-9-]{8,96}'
 if type(cmd) is list:cmd=subprocess.list2cmdline(cmd)
 return type(cmd) is str and re.fullmatch(pattern,cmd) is not None

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--output',required=True);args=parser.parse_args()
 output=Path(args.output).resolve();output.mkdir(parents=True,exist_ok=False)
 root=Path(r'D:\Codex')/('RATE-Gate2-Native-Offline-Tests-'+uuid4().hex);root.mkdir()
 sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
 from gui_native_identity.tests import test_candidate,test_faults,test_review_corrective
 test_candidate.ROOT=root
 native_attempts=[];children=[];violations=[]
 def no_native(*a,**kw):native_attempts.append(repr(a));raise RuntimeError('NATIVE_DLL_CALL_PROHIBITED')
 ctypes.WinDLL=no_native;ctypes.CDLL=no_native
 if hasattr(ctypes,'windll'):ctypes.windll=type('Blocked',(),{'__getattr__':lambda self,name:no_native(name)})()
 probe=str(Path(test_candidate.__file__).with_name('fault_probe.py'))
 def audit(event,items):
  if event=='subprocess.Popen':
   exe,cmd,cwd,env=items
   allowed=any(allowed_crash_child(exe,cmd,sys.executable,probe,p) for p in [root,*root.parent.glob(root.name+'-*')] if p.is_dir() and not p.is_symlink())
   children.append({'executable':exe,'args':cmd,'allowed':allowed})
   if not allowed:violations.append(event);raise RuntimeError('UNAUTHORIZED_TEST_CHILD')
  if event.startswith('socket.') or event in {'os.system','os.startfile','ctypes.dlopen'}:
   violations.append(event);raise RuntimeError('OFFLINE_BOUNDARY:'+event)
  if event=='open' and isinstance(items[0],(str,bytes,os.PathLike)):
   path=Path(os.fsdecode(items[0])).resolve();flags=items[2]
   if isinstance(flags,int) and flags&(os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND) and not (path.is_relative_to(root) or path.is_relative_to(output) or (path.is_relative_to(root.parent) and path.relative_to(root.parent).parts[0].startswith(root.name+'-'))):
    violations.append('write:'+str(path));raise RuntimeError('TEST_WRITE_OUTSIDE_ROOT')
 sys.addaudithook(audit)
 class Result(unittest.TextTestResult):
  def __init__(self,*a,**kw):super().__init__(*a,**kw);self.records=[]
  def startTest(self,test):self.records.append({'id':test.id(),'outcome':'RUNNING'});super().startTest(test)
  def addSuccess(self,test):self.records[-1]['outcome']='PASS';super().addSuccess(test)
  def addFailure(self,test,err):self.records[-1]['outcome']='FAIL';super().addFailure(test,err)
  def addError(self,test,err):self.records[-1]['outcome']='ERROR';super().addError(test,err)
  def addSkip(self,test,reason):self.records[-1].update(outcome='SKIP',reason=reason);super().addSkip(test,reason)
 suite=unittest.TestSuite([unittest.defaultTestLoader.loadTestsFromTestCase(test_candidate.CandidateTests),unittest.defaultTestLoader.loadTestsFromTestCase(test_faults.FaultTests),unittest.defaultTestLoader.loadTestsFromTestCase(test_review_corrective.ReviewCorrectiveTests)])
 started=time.time()
 with (output/'RAW_TEST_LOG.txt').open('w',encoding='utf-8') as stream:result=unittest.TextTestRunner(stream=stream,verbosity=2,resultclass=Result).run(suite)
 report={'status':'PASS' if result.wasSuccessful() and not result.skipped and not native_attempts and not violations else 'FAIL','tests_run':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'skips':len(result.skipped),'relaxed_assertions':0,'failure_whitelists':0,'native_dll_calls':len(native_attempts),'native_attempts':native_attempts,'boundary_violations':violations,'test_ids':result.records,'children':children,'workspace':str(root),'additional_workspaces':[str(p) for p in root.parent.glob(root.name+'-*') if p.is_dir()],'python':sys.version,'executable':sys.executable,'pid':os.getpid(),'started_unix':started,'finished_unix':time.time()}
 (output/'TEST_RESULT.json').write_text(json.dumps(report,ensure_ascii=True,indent=2)+'\n',encoding='utf-8')
 print(json.dumps({k:report[k] for k in ['status','tests_run','failures','errors','skips','native_dll_calls','workspace']}));return 0 if report['status']=='PASS' else 1

if __name__=='__main__':raise SystemExit(main())
