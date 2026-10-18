"""Closed, pinned C04 engine reuse; R1 namespace only for reviewed orchestration."""
import hashlib,json,re,sys,types
C04_MANIFEST_SHA='da015457d19b7002ffa3f9c544d386d38291b4ba6717c15c7a6fb3a83969e3d1'
BASE_MANIFEST_SHA='7e42d669357bc39a91127d7b38f56e8d379cbfef4e6520cd08a963ffb34dbfa0'
def closed_bytes(folder,pin=None):
 raw=(folder/'SOURCE_MANIFEST_V1.json').read_bytes()
 if pin is not None and hashlib.sha256(raw).hexdigest()!=pin:raise ValueError('PINNED_SOURCE_MANIFEST')
 def pairs(items):
  d={}
  for k,v in items:
   if k in d:raise ValueError('DUPLICATE_KEY')
   d[k]=v
  return d
 m=json.loads(raw.decode('utf-8','strict'),object_pairs_hook=pairs)
 if {p.name for p in folder.iterdir()}!=set(m['files'])|{'SOURCE_MANIFEST_V1.json'}:raise ValueError('EXACT_CLOSED_SOURCE')
 data={}
 for n,row in m['files'].items():
  if not re.fullmatch('[A-Za-z0-9_.-]+',n) or n in ('.','..'):raise ValueError('FIXED_SOURCE_NAME')
  p=folder/n
  if not p.is_file() or p.is_symlink() or getattr(p.stat(),'st_file_attributes',0)&0x400:raise ValueError('SOURCE_REPARSE')
  b=p.read_bytes()
  if row!={'sha256':hashlib.sha256(b).hexdigest(),'bytes':len(b)}:raise ValueError('SOURCE_HASH')
  data[n]=b
 return data
class Loader:
 def __init__(self,source):
  self.source=source;self.engine=source.parent/'pf002_c04_image_identity';self.current=closed_bytes(source);self.accepted=closed_bytes(self.engine,C04_MANIFEST_SHA);closed_bytes(source.parent/'pf_personal_trust',BASE_MANIFEST_SHA);self.loaded={}
 def load(self,name):
  if name in self.loaded:return self.loaded[name]
  core=('model','canonical_file','file_evidence','probe')
  if name not in core+('runner_proof','job','http_evidence'):raise ValueError('FIXED_MODULE_ONLY')
  if name in sys.modules:raise ValueError('PRELOADED_SOURCE_MODULE')
  folder,data=(self.engine,self.accepted) if name in core else (self.source,self.current)
  module=types.ModuleType(name);module.__file__=str(folder/(name+'.py'));module.__package__='';sys.modules[name]=module
  exec(compile(data[name+'.py'],module.__file__,'exec',dont_inherit=True),module.__dict__);self.loaded[name]=module;return module
