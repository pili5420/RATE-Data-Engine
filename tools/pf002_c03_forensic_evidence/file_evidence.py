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
 model.need(callable(emit),'DURABLE_IMAGE_EVIDENCE_REQUIRED')
 p=Path(path)
 model.need(p.is_absolute() and not str(p).startswith(('\\\\','//')),'LOCAL_PHYSICAL_IMAGE_ONLY')
 model.need(callable(fixed_drive) and fixed_drive(p.anchor) is True,'IMAGE_DRIVE_NOT_FIXED')
 model.need(p==p.resolve(),'LOCAL_PHYSICAL_IMAGE_ONLY')
 for q in (p,*p.parents):model.need(not q.is_symlink() and not(getattr(q.lstat(),'st_file_attributes',0)&0x400),'IMAGE_REPARSE')
 def query(stage,fn,descriptor):
  start=time.monotonic_ns()
  try:
   row=fn();m=metadata(row)
  except Exception as exc:
   error={'operation':stage,'descriptor':descriptor,'status':'UNKNOWN','start_monotonic_ns':start,'end_monotonic_ns':time.monotonic_ns(),
          'error_type':'OSError' if isinstance(exc,OSError) else 'MetadataError','errno':error_number(getattr(exc,'errno',None)),
          'win32_error':error_number(getattr(exc,'winerror',None)),'exception_text_exported':False}
   emit('IMAGE_IDENTITY_QUERY',error);raise
  emit('IMAGE_IDENTITY_QUERY',{'operation':stage,'descriptor':descriptor,'status':'OK','metadata':m,'start_monotonic_ns':start,'end_monotonic_ns':time.monotonic_ns(),'native_error':None})
  return row,m
 opened=time.monotonic_ns()
 try:f=p.open('rb')
 except OSError as exc:
  emit('IMAGE_OPEN_RESULT',{'status':'UNKNOWN','start_monotonic_ns':opened,'end_monotonic_ns':time.monotonic_ns(),'errno':error_number(exc.errno),'win32_error':error_number(getattr(exc,'winerror',None)),'exception_text_exported':False});raise
 with f:
  fd=f.fileno();emit('IMAGE_OPEN_RESULT',{'status':'OK','file_descriptor':fd,'access':'rb','opened_file_handle_metadata_source':'os.fstat on this retained descriptor','start_monotonic_ns':opened,'end_monotonic_ns':time.monotonic_ns()})
  a,ma=query('OPEN_HANDLE_FSTAT_BEFORE',lambda:os.fstat(fd),fd)
  model.need(0<a.st_size<=32*1024*1024,'IMAGE_SIZE_BOUND');digest=hashlib.sha256();count=0
  while count<a.st_size:
   model.need(time.monotonic()<=end,'IMAGE_DEADLINE');raw=f.read(min(65536,a.st_size-count));model.need(bool(raw),'IMAGE_TRUNCATED');digest.update(raw);count+=len(raw)
  b,mb=query('OPEN_HANDLE_FSTAT_AFTER',lambda:os.fstat(fd),fd)
  c,mc=query('SAME_PATH_STAT',p.stat,None)
  mismatch=differences(ma,mb,mc)
  emit('IMAGE_IDENTITY_COMPARISON',{'identity_fields':list(IDENTITY_FIELDS),'before':ma,'after':mb,'path_stat':mc,'mismatch_fields':mismatch,
       'equal':not any(mismatch.values()),'bytes_hashed':count,'sha256':digest.hexdigest(),'comparison_monotonic_ns':time.monotonic_ns(),
       'atomic_snapshot':False,'ctime_is_not_assumed_birthtime':True,'birthtime_recorded_separately_when_available':True,
       'all_original_identity_fields_retained':True,'loaded_image_attestation':False,'underlying_file_information_API_status':'NOT_EXPORTED_BY_CPYTHON_ON_SUCCESS; Python operation status only'})
  # The C02 five-field predicate is unchanged. Extra birthtime evidence does not bypass it.
  identity=lambda s:(s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
  model.need(identity(a)==identity(b)==identity(c),'IMAGE_DISK_IDENTITY_CHANGED')
 return {'sha256':digest.hexdigest(),'bytes':count,'file_id':a.st_ino,'volume_id':a.st_dev,'mtime_ns':a.st_mtime_ns,'creation_ns':a.st_ctime_ns,'ctime_ns':a.st_ctime_ns,'birthtime_ns':ma['st_birthtime_ns'],'creation_ns_legacy_field_not_birthtime_attestation':True,'loaded_image_attestation':False}
