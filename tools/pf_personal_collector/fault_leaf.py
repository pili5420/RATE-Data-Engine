"""Own test descendant: write private start acknowledgement, then await Job cancellation."""
import json,os,sys,time
from pathlib import Path
if len(sys.argv)!=3 or os.name!='nt':raise SystemExit('FIXED_OWN_CHILD_ONLY')
root=Path(sys.argv[1]);parent=int(sys.argv[2])
if root.name!='fault_descendant_hang' or not root.parent.name.startswith('PF-PERSONAL-002-') or root!=root.resolve():raise SystemExit('OWN_CHILD_OUTPUT_ONLY')
for p in (root,*root.parents):
 if p.is_symlink() or getattr(p.stat(),'st_file_attributes',0)&0x400:raise SystemExit('NO_REPARSE')
with (root/'DESCENDANT_STARTED.json').open('xb') as f:
 f.write(json.dumps({'pid':os.getpid(),'parent_pid':parent},sort_keys=True,separators=(',',':')).encode()+b'\n');f.flush();os.fsync(f.fileno())
while True:time.sleep(.1)
