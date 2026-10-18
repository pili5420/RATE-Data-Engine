"""Existing fstat/path-stat identity predicate, with durable operation evidence."""
import hashlib,os,time
from pathlib import Path
import model
IDENTITY_FIELDS=('st_dev','st_ino','st_size','st_mtime_ns','st_ctime_ns')
EXTRA_FIELDS=('st_birthtime_ns','st_atime_ns','st_mode','st_file_attributes','st_reparse_tag')
def error_number(value):return value if type(value) is int and -(2**31)<=value<2**32 else None
def metadata(row):
 result={}
 for field in IDENTITY_FIELDS:
  v=getattr(row,field);model.need(type(v) is int,'IMAGE_METADATA_TYPE');result[field]=v
 for field in EXTRA_FIELDS:
  v=getattr(row,field,None);model.need(v is None or type(v) is int,'IMAGE_METADATA_TYPE');result[field]=v
 return result
def differences(a,b,c):
 return {name:[field for field in IDENTITY_FIELDS if left[field]!=right[field]] for name,left,right in (('before_vs_after',a,b),('before_vs_path',a,c),('after_vs_path',b,c))}
def disk_image(path,end,fixed_drive=None,emit=None):
 """Retired entry: reject every runtime call, never downgrade to Python stat/hash."""
 model.need(callable(emit),'DURABLE_IMAGE_EVIDENCE_REQUIRED')
 p=Path(path);model.need(p.is_absolute() and not str(p).startswith(('\\\\','//')),'LOCAL_PHYSICAL_IMAGE_ONLY')
 model.need(callable(fixed_drive),'IMAGE_DRIVE_NOT_FIXED')
 model.need(time.monotonic()<=end,'IMAGE_DEADLINE')
 raise model.Unknown('LEGACY_COMPARATOR_NOT_RUNTIME_QUALIFIED')

LEGACY_RUNTIME_STATUS='LEGACY_COMPARATOR_NOT_RUNTIME_QUALIFIED'
_OFFLINE_VERIFIED_MODULE=None
def offline_contract():
 global _OFFLINE_VERIFIED_MODULE
 import types
 p=Path(__file__).resolve().parent.parent/'pf002_c04_r1_legacy_contract'/'offline_contract.py';raw=p.read_bytes()
 model.need(hashlib.sha256(raw).hexdigest()=='975fcc11a143cce4f93cf0baa8866a44adcb5e8e0f8e28850284a5ed8eb26149','PINNED_OFFLINE_SUCCESSOR_SOURCE')
 if _OFFLINE_VERIFIED_MODULE is None:
  module=types.ModuleType('explicit_offline_contract');module.__file__=str(p);exec(compile(raw,str(p),'exec',dont_inherit=True),module.__dict__);_OFFLINE_VERIFIED_MODULE=module
 return _OFFLINE_VERIFIED_MODULE
def offline_reader(path,size,change=None,fail_phase=None):
 return offline_contract().FixtureReader(path,size,change,fail_phase)
def validate_offline_fixture(path,end,fixed_drive,emit,reader):
 return offline_contract().validate_fixture(model,path,end,fixed_drive,emit,reader)
