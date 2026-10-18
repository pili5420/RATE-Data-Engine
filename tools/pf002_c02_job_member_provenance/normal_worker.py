"""One normal self-report only; no child creation, GUI or source collector."""
import hashlib,json,os,sys
from pathlib import Path
S=Path(__file__).resolve().parent
raw=(S/'source_loader.py').read_bytes();m=json.loads((S/'SOURCE_MANIFEST_V1.json').read_bytes())
if m['files']['source_loader.py']!={'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}:raise ValueError('LOADER_HASH')
ns={'__file__':str(S/'source_loader.py')};exec(compile(raw,str(S/'source_loader.py'),'exec',dont_inherit=True),ns);p=ns['Loader'](S).load('runner_proof')
def main():
 p.need(os.name=='nt' and len(sys.argv)==1 and sys.implementation.name=='cpython' and sys.version_info[:3]==(3,12,10),'FIXED_NORMAL_CPYTHON_ONLY')
 import msvcrt,time
 fd=msvcrt.open_osfhandle(int(os.environ['PF002_AUTH_PIPE']),os.O_RDONLY)
 with os.fdopen(fd,'rb') as f:b=f.read(20001)
 p.need(0<len(b)<=20000 and b.endswith(b'\n') and b.count(b'\n')==1,'PIPE_BOUND')
 v=p.strict(b,20000);p.need(type(v) is dict and set(v)=={'token','launch_nonce'} and v['launch_nonce']==os.environ['C02_NONCE'],'LAUNCH_NONCE')
 p.verify_token(v['token'],(S/'GITHUB_OIDC_JWKS_PINNED.json').read_bytes(),int(time.time()),os.environ['PF002_HEAD'],os.environ['PF002_RUN_ID'],'1')
 root=Path(os.environ['PF002_PRIVATE_ROOT']);expected=Path(os.environ['PF002_RUNNER_ROOT'])/('PF002-C02-'+os.environ['PF002_RUN_ID']+'-1-'+os.environ['PF002_ROLE'])/'normal'
 p.need(root==expected and root==root.resolve(),'FIXED_WORKER_ROOT')
 for q in (root,*root.parents):p.need(not q.is_symlink() and not(getattr(q.stat(),'st_file_attributes',0)&0x400),'NO_REPARSE')
 # CPython 3.12.10 getppid uses current-process PSS_CAPTURE_NONE, not a global scan.
 value={'head':os.environ['PF002_HEAD'],'role':os.environ['PF002_ROLE'],'run_id':os.environ['PF002_RUN_ID'],'launch_nonce':v['launch_nonce'],'pid':os.getpid(),'parent_pid':os.getppid(),'executable':sys.executable,'base_executable':sys._base_executable,'worker_source_sha256':hashlib.sha256((S/'normal_worker.py').read_bytes()).hexdigest(),'self_parent_source':'CPYTHON_3_12_10_CURRENT_PROCESS_PSS_NONE','NoAutoNext':True}
 with (root/'WORKER_RECEIPT.part').open('xb') as f:f.write(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()+b'\n');f.flush();os.fsync(f.fileno())
 (root/'WORKER_RECEIPT.part').rename(root/'WORKER_RECEIPT.json');return 0
if __name__=='__main__':raise SystemExit(main())
