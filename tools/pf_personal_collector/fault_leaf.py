"""Own test descendant: write private start acknowledgement, then await Job cancellation."""
import json,os,sys,time
from pathlib import Path
if len(sys.argv)!=3 or os.name!='nt':raise SystemExit('FIXED_OWN_CHILD_ONLY')
SRC=Path(__file__).resolve().parent;sys.path.append(str(SRC))
import runner_proof as proof
b=sys.stdin.buffer.read(16386)
proof.need(len(b)<=16385 and b.endswith(b'\n') and b.count(b'\n')==1,'SIGNED_RUNNER_PROOF_REQUIRED')
proof.verify_token(b[:-1].decode('ascii'),(SRC/'GITHUB_OIDC_JWKS_PINNED.json').read_bytes(),int(time.time()),os.environ['PF002_HEAD'],os.environ['PF002_RUN_ID'],'1')
root=Path(sys.argv[1]);parent=int(sys.argv[2])
expected=Path(os.environ['PF002_RUNNER_ROOT'])/('PF-PERSONAL-002-'+os.environ['PF002_RUN_ID']+'-1-'+os.environ['PF002_ROLE'])/'fault_descendant_hang'
if root!=expected or root!=root.resolve():raise SystemExit('OWN_CHILD_OUTPUT_ONLY')
for p in (root,*root.parents):
 if p.is_symlink() or getattr(p.stat(),'st_file_attributes',0)&0x400:raise SystemExit('NO_REPARSE')
with (root/'DESCENDANT_STARTED.json').open('xb') as f:
 f.write(json.dumps({'pid':os.getpid(),'parent_pid':parent},sort_keys=True,separators=(',',':')).encode()+b'\n');f.flush();os.fsync(f.fileno())
while True:time.sleep(.1)
