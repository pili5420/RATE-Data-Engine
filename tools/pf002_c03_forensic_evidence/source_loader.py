"""Verified source-byte loading only. No cached bytecode, dispatch or external I/O."""
import hashlib,json,re,sys,types
BASE_MANIFEST_SHA='7e42d669357bc39a91127d7b38f56e8d379cbfef4e6520cd08a963ffb34dbfa0'
def closed_bytes(folder,pinned_manifest=None):
 raw=(folder/'SOURCE_MANIFEST_V1.json').read_bytes()
 if pinned_manifest is not None and hashlib.sha256(raw).hexdigest()!=pinned_manifest:raise ValueError('ACCEPTED_MANIFEST_PIN')
 def pairs(items):
  v={}
  for k,x in items:
   if k in v:raise ValueError('SOURCE_DUPLICATE_KEY')
   v[k]=x
  return v
 m=json.loads(raw.decode('utf-8','strict'),object_pairs_hook=pairs)
 if {p.name for p in folder.iterdir()}!=set(m['files'])|{'SOURCE_MANIFEST_V1.json'}:raise ValueError('EXACT_SOURCE_NO_CACHE_OR_INJECTION')
 result={}
 for n,row in m['files'].items():
  if not re.fullmatch('[A-Za-z0-9_.-]+',n) or n in ('.','..'):raise ValueError('FIXED_SOURCE_NAME')
  p=folder/n
  if not p.is_file() or p.is_symlink() or getattr(p.stat(),'st_file_attributes',0)&0x400:raise ValueError('SOURCE_REPARSE')
  b=p.read_bytes()
  if row!={'sha256':hashlib.sha256(b).hexdigest(),'bytes':len(b)}:raise ValueError('SOURCE_BYTE_HASH')
  result[n]=b
 return result
class Loader:
 def __init__(self,source):
  self.source=source;self.base=source.parent/'pf_personal_trust'
  self.current=closed_bytes(source);self.accepted=closed_bytes(self.base,BASE_MANIFEST_SHA);self.loaded={}
 def load(self,name):
  if name in self.loaded:return self.loaded[name]
  if name not in ('runner_proof','job','probe','model','http_evidence','file_evidence'):raise ValueError('FIXED_MODULE_ONLY')
  if name in sys.modules:raise ValueError('PRELOADED_SOURCE_MODULE')
  folder,data=(self.base,self.accepted) if name=='personal_model' else (self.source,self.current)
  module=types.ModuleType(name);module.__file__=str(folder/(name+'.py'));module.__package__=''
  sys.modules[name]=module
  exec(compile(data[name+'.py'],module.__file__,'exec',dont_inherit=True),module.__dict__)
  self.loaded[name]=module;return module
