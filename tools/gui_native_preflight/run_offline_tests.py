"""Engineering test runner only. Loads no real Permit and no Windows DLL."""
import argparse,ctypes,hashlib,json,os,re,subprocess,sys,time,unittest
from pathlib import Path
from uuid import uuid4
def main():
 p=argparse.ArgumentParser();p.add_argument('--output',required=True);a=p.parse_args();out=Path(a.output);out.mkdir(parents=True,exist_ok=False)
 root=Path(r'D:\Codex')/('RATE-Gate2-Native-Offline-Tests-NQ-'+uuid4().hex);root.mkdir();sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
 dependency=Path(r'D:\Codex\RATE-MH-Batch-Engineering-Evidence-20261016-000558-271982\venv-native\Lib\site-packages');sys.path.append(str(dependency))
 native=[];violations=[];children=[]
 def deny_native(*args,**kw):native.append(repr(args));raise RuntimeError('NQ_REAL_WINDOWS_DLL_CALL_FORBIDDEN')
 ctypes.WinDLL=deny_native;ctypes.CDLL=deny_native
 def audit(event,args):
  if event in {'ctypes.dlopen','os.system','os.startfile','os.exec','os.posix_spawn'} or event.startswith('socket.'):
   violations.append(event);raise RuntimeError('NQ_OFFLINE_BOUNDARY:'+event)
  if event=='subprocess.Popen':
   exe,cmd,cwd,env=args;worker=str(Path(__file__).with_name('tests')/'owned_worker.py');prefix=subprocess.list2cmdline([sys.executable,'-I','-B','-S',worker]);pattern=re.escape(prefix)+r' --root '+re.escape(str(root))+r'-child-[0-9a-f]{32} --mode (after_lock|after_attempt|after_claim|after_result|sleep|clean) --attempt SYNTHETIC-[0-9a-f]{32} --nonce SYNTHETIC-[0-9a-f]{32}'
   cmd=subprocess.list2cmdline(cmd) if type(cmd) is list else cmd;allowed=exe in (None,sys.executable) and type(cmd) is str and re.fullmatch(pattern,cmd) is not None;children.append({'command':cmd,'allowed':allowed})
   if not allowed:violations.append('UNAUTHORIZED_CHILD');raise RuntimeError('NQ_UNAUTHORIZED_CHILD')
  if event=='open' and isinstance(args[0],(str,bytes,os.PathLike)):
   path=Path(os.fsdecode(args[0])).resolve();flags=args[2]
   if flags&(os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND):
    private=path.is_relative_to(root.parent) and path.relative_to(root.parent).parts[0].startswith(root.name)
    if not (path.is_relative_to(out) or private):violations.append('OUT_OF_SCOPE_WRITE:'+str(path));raise RuntimeError('NQ_OUTPUT_ROOT_BOUNDARY')
 sys.addaudithook(audit)
 from gui_native_preflight.tests import test_preflight as core,test_abi_and_containment as more
 from gui_native_preflight.tests.fixtures import TestKeys
 core.ROOT=root;core.KEYS=TestKeys();(out/'PUBLIC_SYNTHETIC_TEST_KEYS.json').write_text(json.dumps(core.KEYS.bundle,indent=2))
 class Result(unittest.TextTestResult):
  def __init__(self,*args,**kwargs):super().__init__(*args,**kwargs);self.ids=[]
  def startTest(self,test):self.ids.append({'id':test.id(),'outcome':'RUNNING'});super().startTest(test)
  def addSuccess(self,test):self.ids[-1]['outcome']='PASS';super().addSuccess(test)
  def addFailure(self,test,err):self.ids[-1]['outcome']='FAIL';super().addFailure(test,err)
  def addError(self,test,err):self.ids[-1]['outcome']='ERROR';super().addError(test,err)
  def addSkip(self,test,reason):self.ids[-1]['outcome']='SKIP';super().addSkip(test,reason)
 suite=unittest.TestSuite([unittest.defaultTestLoader.loadTestsFromTestCase(core.PreflightTests),unittest.defaultTestLoader.loadTestsFromTestCase(more.AbiTests),unittest.defaultTestLoader.loadTestsFromTestCase(more.ContainmentTests)])
 started=time.time()
 with (out/'RAW_TEST_LOG.txt').open('w',encoding='utf-8') as stream:r=unittest.TextTestRunner(stream=stream,verbosity=2,resultclass=Result).run(suite)
 report={'status':'PASS' if r.wasSuccessful() and not r.skipped and not native and not violations else 'FAIL','tests':r.testsRun,'failures':len(r.failures),'errors':len(r.errors),'skips':len(r.skipped),'relaxed_assertions':0,'failure_whitelists':0,'explicit_windows_DLL_dispatch_calls':len(native),'native_attempts':native,'boundary_violations':violations,'test_ids':r.ids,'owned_child_commands':children,'workspace':str(root),'additional_workspaces':[str(d) for d in root.parent.glob(root.name+'-*') if d.is_dir()],'python':sys.version,'executable':sys.executable,'pid':os.getpid(),'start_unix':started,'end_unix':time.time(),'crypto':'PyCA cryptography50.0.2 Ed25519 with compiled crypto dependency;not Windows GUI DLL dispatch','real_native_runtime_qualification':'BLOCKED'}
 (out/'TEST_RESULT.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({k:report[k] for k in ['status','tests','failures','errors','skips','explicit_windows_DLL_dispatch_calls','workspace']}));return 0 if report['status']=='PASS' else 1
if __name__=='__main__':raise SystemExit(main())
