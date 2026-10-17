"""Fixed offline test CLI, never a live adapter, Permit loader or activation."""
import argparse,ctypes,json,os,sys,time,unittest
from pathlib import Path
from uuid import uuid4

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);a=p.parse_args();out=Path(a.output);out.mkdir(parents=True,exist_ok=False)
    root=Path(r'D:\Codex')/('RATE-Gate2-Native-Offline-Tests-rqr-'+uuid4().hex[:12]);root.mkdir()
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]));sys.path.append(r'D:\Codex\RATE-MH-Batch-Engineering-Evidence-20261016-000558-271982\venv-native\Lib\site-packages')
    native=[];violations=[]
    def deny(*args,**kwargs):native.append(repr(args));raise RuntimeError('NO_REAL_NATIVE_GUI_DISPATCH')
    ctypes.WinDLL=deny;ctypes.CDLL=deny
    def audit(event,args):
        if event.startswith('socket.') or event in {'ctypes.dlopen','subprocess.Popen','os.system','os.startfile','os.exec','os.posix_spawn'}:violations.append(event);raise RuntimeError('READINESS_OFFLINE_BOUNDARY:'+event)
        if event=='open' and isinstance(args[0],(str,bytes,os.PathLike)) and args[2]&(os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND):
            path=Path(os.fsdecode(args[0])).resolve();private=path.is_relative_to(root.parent) and path.relative_to(root.parent).parts[0].startswith(root.name)
            if not (path.is_relative_to(out) or private):violations.append('WRITE:'+str(path));raise RuntimeError('PRIVATE_OUTPUT_BOUNDARY')
    sys.addaudithook(audit)
    from gui_runtime_readiness.tests import test_readiness as core,test_faults as faults
    from gui_runtime_readiness.tests.fixtures import Keys
    core.ROOT=root;core.KEYS=Keys();(out/'PUBLIC_TEST_ROOTS.json').write_text(json.dumps(core.KEYS.bundle,indent=2))
    class Result(unittest.TextTestResult):
        def __init__(self,*args,**kwargs):super().__init__(*args,**kwargs);self.ids=[]
        def startTest(self,test):self.ids.append({'id':test.id(),'outcome':'RUNNING'});super().startTest(test)
        def addSuccess(self,test):self.ids[-1]['outcome']='PASS';super().addSuccess(test)
        def addFailure(self,test,err):self.ids[-1]['outcome']='FAIL';super().addFailure(test,err)
        def addError(self,test,err):self.ids[-1]['outcome']='ERROR';super().addError(test,err)
        def addSkip(self,test,reason):self.ids[-1]['outcome']='SKIP';super().addSkip(test,reason)
    suite=unittest.TestSuite([unittest.defaultTestLoader.loadTestsFromTestCase(core.ReadinessTests),unittest.defaultTestLoader.loadTestsFromTestCase(faults.FaultTests)])
    start=time.time()
    with (out/'RAW_TEST_LOG.txt').open('w',encoding='utf-8') as stream:r=unittest.TextTestRunner(stream=stream,verbosity=2,resultclass=Result).run(suite)
    report={'status':'PASS' if r.wasSuccessful() and not r.skipped and not native and not violations else 'FAIL','tests':r.testsRun,'failures':len(r.failures),'errors':len(r.errors),'skips':len(r.skipped),'relaxed_assertions':0,'failure_whitelists':0,'explicit_native_GUI_identity_DLL_dispatch_calls':len(native),'native_attempts':native,'violations':violations,'test_ids':r.ids,'workspace':str(root),'additional_workspaces':[str(p) for p in root.parent.glob(root.name+'-*') if p.is_dir()],'python':sys.version,'executable':sys.executable,'pid':os.getpid(),'start_unix':start,'end_unix':time.time(),'real_runtime_qualification':'BLOCKED','ordinary_runtime':'Normal Python/OS/filesystem and preinstalled PyCA50.0.2 compiled crypto are not claimed absent','isolation':'Fresh isolated source/test roots and Python -I -B -S,not a VM or generalOSsandbox'}
    (out/'TEST_RESULT.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({k:report[k] for k in ['status','tests','failures','errors','skips','explicit_native_GUI_identity_DLL_dispatch_calls','workspace']}));return 0 if report['status']=='PASS' else 1
if __name__=='__main__':raise SystemExit(main())
