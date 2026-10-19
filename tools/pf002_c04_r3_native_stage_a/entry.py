"""Fixed Hosted Runner Stage-A entry. No Permit loader, consent or original-host mode."""
import subprocess,sys
from pathlib import Path
S=Path(__file__).resolve().parent;sys.path.insert(0,str(S))
from invocation_boundary import Boundary
import execution
def main():
 boundary=Boundary(sys.executable,subprocess.list2cmdline([sys.executable,'-I','-B','-S',str(S/'normal_worker.py')]),str(S.parent.parent));boundary.install()
 try:return execution.run(boundary)
 finally:boundary.stop()
if __name__=='__main__':
 try:code=main()
 except BaseException:code=1
 print('PF002_C04_R3_STAGE_A_PASS' if code==0 else 'PF002_C04_R3_HALTED_NO_SECRET_DETAIL')
 raise SystemExit(code)
