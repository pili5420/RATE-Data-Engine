"""Offline successors only. Synthetic canonical fields never qualify a real image."""
import builtins,copy,hashlib,json,os,time,types
from pathlib import Path
CORE_MANIFEST_SHA='da015457d19b7002ffa3f9c544d386d38291b4ba6717c15c7a6fb3a83969e3d1'
REALM='OFFLINE_OWNED_FIXTURE_AND_SYNTHETIC_CANONICAL_V2'
def engine(model):
 root=Path(__file__).resolve().parent.parent/'pf002_c04_image_identity';raw=(root/'SOURCE_MANIFEST_V1.json').read_bytes()
 model.need(hashlib.sha256(raw).hexdigest()==CORE_MANIFEST_SHA,'PINNED_CANONICAL_MANIFEST')
 manifest=json.loads(raw);model.need({p.name for p in root.iterdir()}==set(manifest['files'])|{'SOURCE_MANIFEST_V1.json'},'CLOSED_CANONICAL_SOURCE')
 data={}
 for n,row in manifest['files'].items():
  p=root/n;model.need(p.is_file() and not p.is_symlink() and not(getattr(p.stat(),'st_file_attributes',0)&0x400),'CANONICAL_SOURCE_REPARSE');b=p.read_bytes()
  model.need(row=={'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()},'PINNED_CANONICAL_BYTES');data[n]=b
 modules={'model':model}
 def imported(name,*a,**kw):return modules[name] if name in modules else builtins.__import__(name,*a,**kw)
 for name in ('canonical_file','file_evidence'):
  module=types.ModuleType('offline_'+name);module.__file__=str(root/(name+'.py'));module.__dict__['__builtins__']={**vars(builtins),'__import__':imported}
  exec(compile(data[name+'.py'],module.__file__,'exec',dont_inherit=True),module.__dict__);modules[name]=module
 return modules['canonical_file'],modules['file_evidence']
def synthetic_identity(size):
 return {'volume_serial_u64':11,'file_id_128_le':'1600000000000000aabbccddeeff0011','file_size_bytes':size,'creation_time_100ns':100,'change_time_100ns':300,'last_write_time_100ns':200,'file_attributes_u32':32,'number_of_links':1}
class FixtureReader:
 """Same-source actual fstat is supplemental; canonical metadata is explicit synthetic."""
 def __init__(self,path,size,change=None,fail_phase=None):
  self.path=Path(path);self.size=size;self.change=change;self.fail_phase=fail_phase;self.observations=[];self.actual=[];self.emit=None
 def snapshot(self,fd,phase):
  if phase==self.fail_phase:
   self.emit('OFFLINE_QUERY_RESULT',{'phase':phase,'status':'UNKNOWN','errno':5,'exception_text_exported':False,'realm':REALM});raise OSError(5,'SYNTHETIC_SECRET_NOT_EXPORTED')
  s=os.fstat(fd);raw={k:getattr(s,k,None) for k in ('st_dev','st_ino','st_size','st_mtime_ns','st_ctime_ns','st_birthtime_ns','st_file_attributes','st_mode')};self.actual.append({'phase':phase,'source':'os.fstat_same_access_path','metadata':raw})
  identity=synthetic_identity(self.size)
  if self.change is not None and phase=='OPENED_AFTER_HASH':identity[self.change]+=1 if type(identity[self.change]) is int else ''
  if self.change=='file_id_128_le' and phase=='OPENED_AFTER_HASH':identity[self.change]='17'+identity[self.change][2:]
  row={'phase':phase,'schema':'C04_WINDOWS_FILE_IDENTITY_V1','api':'GetFileInformationByHandleEx','time_units':'FILETIME_100NS_1601_UTC','file_descriptor':fd,'native_handle':fd+100000,'identity':identity}
  self.observations.append(copy.deepcopy(row));self.emit('OFFLINE_SYNTHETIC_CANONICAL_OBSERVATION',{'observation':row,'realm':REALM,'native_call_executed':False});return row
def validate_fixture(model,path,end,fixed_drive,emit,reader):
 model.need(type(reader) is FixtureReader and reader.path==Path(path) and callable(emit),'EXPLICIT_OFFLINE_FIXTURE_REQUIRED')
 reader.emit=emit;canonical,file=engine(model)
 value=file.disk_image(path,end,fixed_drive,emit,reader)
 model.need(len(reader.actual)==5,'INCOMPLETE_FIXTURE_SOURCE')
 first=reader.actual[0]['metadata'];fields=('st_dev','st_ino','st_size','st_mtime_ns','st_ctime_ns')
 model.need(all(all(r['metadata'][k]==first[k] for k in fields) for r in reader.actual),'FIXTURE_SAME_SOURCE_CHANGED')
 value.update(evidence_realm=REALM,runtime_qualified=False,native_calls=0,canonical_metadata_is_synthetic=True,fixture_filesystem_observations=reader.actual)
 return value
