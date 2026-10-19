"""One fixed Root: fresh signed proof, ready/hold/release, no parent/other-process read."""
import hashlib,json,os,sys,types
from pathlib import Path
S=Path(__file__).resolve().parent
def main():
 if os.name!='nt' or len(sys.argv)!=1 or sys.implementation.name!='cpython' or sys.version_info[:3]!=(3,12,10):raise ValueError('FIXED_HOSTED_WORKER_ONLY')
 raw=(S/'SOURCE_MANIFEST_V1.json').read_bytes();m=json.loads(raw);praw=(S/'runner_proof.py').read_bytes()
 if hashlib.sha256(raw).hexdigest()!=os.environ['PF002_MANIFEST_SHA256'] or m['files']['runner_proof.py']!={'bytes':len(praw),'sha256':hashlib.sha256(praw).hexdigest()}:raise ValueError('WORKER_SOURCE_BINDING')
 p=types.ModuleType('worker_runner_proof');exec(compile(praw,str(S/'runner_proof.py'),'exec',dont_inherit=True),p.__dict__)
 import msvcrt,time
 handles=[int(os.environ[n]) for n in ('PF002_AUTH_PIPE','PF002_RELEASE_PIPE','PF002_READY_PIPE')]
 p.need(len(set(handles))==3 and all(h>0 for h in handles),'PIPE_HANDLE_IDENTITY')
 with os.fdopen(msvcrt.open_osfhandle(handles[0],os.O_RDONLY),'rb') as f:b=f.read(20001)
 p.need(0<len(b)<=20000 and b.endswith(b'\n') and b.count(b'\n')==1,'PROOF_PIPE_BOUND')
 v=p.strict(b,20000);p.need(type(v) is dict and set(v)=={'token','launch_nonce'} and v['launch_nonce']==os.environ['C04_R3_NONCE'],'PROOF_NONCE')
 p.verify_token(v['token'],(S/'GITHUB_OIDC_JWKS_PINNED.json').read_bytes(),int(time.time()),os.environ['PF002_HEAD'],os.environ['PF002_RUN_ID'],'1');v=None;b=None
 sys.path.insert(0,str(S));import contract,source_integrity
 source_integrity.closed(S)
 p.need(set(os.environ).isdisjoint({k.upper() for k in contract.SECRET_KEYS}) and os.environ.get('PF002_SCOPE')=='STAGE_A_ROOT_ONLY','CHILD_CREDENTIAL_OR_SCOPE')
 role=os.environ['PF002_ROLE'];rid=os.environ['PF002_RUN_ID'];head=os.environ['PF002_HEAD'];nonce=os.environ['C04_R3_NONCE'];contract.context(head,rid,role,nonce)
 root=Path(os.environ['PF002_PRIVATE_ROOT']);expected=Path(r'D:\a\_temp')/('PF002-C04-R3-'+rid+'-1-'+role)/'normal';p.need(root==expected and os.environ['PF002_RUNNER_ROOT']==r'D:\a\_temp','WORKER_FIXED_OUTPUT');source_integrity.physical(root)
 receipt={'state':'READY','head':head,'role':role,'run_id':rid,'attempt':1,'nonce':nonce,'pid':os.getpid(),'executable':sys.executable,'source_manifest_sha256':hashlib.sha256(raw).hexdigest(),'worker_source_sha256':hashlib.sha256((S/'normal_worker.py').read_bytes()).hexdigest(),'credential_variables_absent':True,'NoAutoNext':True}
 def save(name,value):
  with (root/name).open('xb') as f:f.write(contract.canonical(value));f.flush();os.fsync(f.fileno())
 save('WORKER_READY.json',receipt)
 with os.fdopen(msvcrt.open_osfhandle(handles[2],os.O_WRONLY),'wb',buffering=0) as f:p.need(f.write(b'R')==1,'READY_WRITE_UNKNOWN')
 with os.fdopen(msvcrt.open_osfhandle(handles[1],os.O_RDONLY),'rb') as f:released=f.read(2)
 p.need(released==b'1','RELEASE_PROTOCOL_UNKNOWN');receipt['state']='COMPLETE';save('WORKER_COMPLETE.json',receipt)
 return 0
if __name__=='__main__':
 try:code=main()
 except BaseException:print('R3_WORKER_HALTED_NO_SECRET_DETAIL');code=1
 raise SystemExit(code)
