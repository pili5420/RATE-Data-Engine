"""Own-process fault worker. No host source reads; requires signed engineering proof."""
import os,sys,time,json,subprocess
from pathlib import Path
SRC=Path(__file__).resolve().parent
sys.path.append(str(SRC))
import runner_proof as p
def main():
 p.need(os.name=='nt' and len(sys.argv)==2 and sys.argv[1] in ('normal','crash','hang','descendant_hang'),'FIXED_FAULT_MODE')
 import msvcrt
 fd=msvcrt.open_osfhandle(int(os.environ['PF002_AUTH_PIPE']),os.O_RDONLY)
 with os.fdopen(fd,'rb') as f:b=f.read(16386)
 p.need(len(b)<=16385 and b.endswith(b'\n') and b.count(b'\n')==1,'PROOF_PIPE_BOUND')
 p.verify_token(b[:-1].decode('ascii'),(SRC/'GITHUB_OIDC_JWKS_PINNED.json').read_bytes(),int(time.time()),os.environ['PF002_HEAD'],os.environ['PF002_RUN_ID'],'1')
 root=Path(os.environ['PF002_PRIVATE_ROOT']);runner=Path(os.environ['PF002_RUNNER_ROOT'])
 mode=sys.argv[1];expected=runner/('PF-PERSONAL-002-'+os.environ['PF002_RUN_ID']+'-1-'+os.environ['PF002_ROLE'])/('fault_'+mode)
 p.need(root==expected and root==root.resolve() and root.is_dir(),'FAULT_PRIVATE_ROOT')
 for q in (root,*root.parents):p.need(not q.is_symlink() and not(getattr(q.stat(),'st_file_attributes',0)&0x400),'FAULT_REPARSE')
 if mode=='normal':return 0
 if mode=='crash':return 7
 if mode=='descendant_hang':
  # Fixed test child only, inheriting this Job, no breakaway and no proof/credentials.
  env={k:v for k,v in os.environ.items() if k in ('PATH','SystemRoot','SYSTEMROOT','WINDIR','TEMP','TMP','PF002_HEAD','PF002_RUN_ID','PF002_ROLE','PF002_RUNNER_ROOT')}
  child=subprocess.Popen([sys.executable,'-I','-B','-S',str(SRC/'fault_leaf.py'),str(root),str(os.getpid())],env=env,stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,close_fds=True)
  child.stdin.write(b);child.stdin.close() # proof remains private on anonymous pipe; never ENV/argv/file
 while True:time.sleep(.1)
if __name__=='__main__':raise SystemExit(main())
