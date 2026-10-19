"""One bounded approved-image read and one same-path read-only reopen; canonical source."""
import hashlib,os,time
from pathlib import Path
import model,canonical_file as canonical
def physical(path,fixed_drive):
 p=Path(path)
 model.need(p.is_absolute() and not str(p).startswith(('\\\\','//')) and all(':' not in part and not any(ord(ch)<32 for ch in part) for part in p.parts[1:]),'LOCAL_PHYSICAL_IMAGE_ONLY')
 model.need(callable(fixed_drive) and fixed_drive(p.anchor) is True,'IMAGE_DRIVE_NOT_FIXED')
 model.need(p==p.resolve(),'LOCAL_PHYSICAL_IMAGE_ONLY')
 for q in (p,*p.parents):model.need(not q.is_symlink() and not(getattr(q.lstat(),'st_file_attributes',0)&0x400),'IMAGE_REPARSE')
 return p
def disk_image(path,end,fixed_drive=None,emit=None,reader=None):
 model.need(callable(emit) and reader is not None,'DURABLE_IMAGE_EVIDENCE_REQUIRED')
 p=physical(path,fixed_drive);files=[];phase='OPEN_APPROVED_IMAGE'
 def bounded():model.need(time.monotonic()<=end,'IMAGE_DEADLINE')
 def opened(label):
  bounded();start=time.monotonic_ns()
  try:f=p.open('rb')
  except OSError as exc:
   emit('FILE_OPEN_RESULT',{'phase':label,'status':'UNKNOWN','errno':canonical.error_number(exc.errno),'win32_error':canonical.error_number(getattr(exc,'winerror',None)),'start_monotonic_ns':start,'end_monotonic_ns':time.monotonic_ns()});raise
  files.append((label,f));emit('FILE_OPEN_RESULT',{'phase':label,'status':'OK','path':str(p),'access':'rb_READ_ONLY_existing_file','file_descriptor':f.fileno(),'start_monotonic_ns':start,'end_monotonic_ns':time.monotonic_ns()});return f
 try:
  f=opened('OPENED_HANDLE');before=reader.snapshot(f.fileno(),'OPENED_BEFORE');size=before['identity']['file_size_bytes'];model.need(type(size) is int and 0<size<=32*1024*1024,'IMAGE_SIZE_BOUND')
  digest=hashlib.sha256();count=0;phase='READ_APPROVED_IMAGE'
  while count<size:
   bounded();raw=f.read(min(65536,size-count));model.need(bool(raw),'IMAGE_TRUNCATED');digest.update(raw);count+=len(raw)
  after=reader.snapshot(f.fileno(),'OPENED_AFTER_HASH')
  phase='REOPEN_SAME_APPROVED_PATH';physical(str(p),fixed_drive);g=opened('PATH_REOPENED_HANDLE')
  path_before=reader.snapshot(g.fileno(),'PATH_REOPENED_BEFORE');path_after=reader.snapshot(g.fileno(),'PATH_REOPENED_AFTER');final=reader.snapshot(f.fileno(),'OPENED_FINAL');physical(str(p),fixed_drive);bounded()
  result=canonical.compare([before,after,path_before,path_after,final],{'bytes':count,'sha256':digest.hexdigest()})
  emit('CANONICAL_FILE_COMPARISON',{'path':str(p),**result,'comparison_monotonic_ns':time.monotonic_ns(),'path_reopened_exact_same_approved_path':True,'image_size_bound_bytes':32*1024*1024,'actual_bytes_read':count})
  model.need(result['equal'],'CANONICAL_FILE_IDENTITY_CHANGED')
  return {'sha256':digest.hexdigest(),'bytes':count,'canonical_identity':result['identity'],'canonical_source_schema':canonical.SCHEMA,'file_id':int.from_bytes(bytes.fromhex(result['identity']['file_id_128_le']),'little'),'file_id_128_le':result['identity']['file_id_128_le'],'volume_id':result['identity']['volume_serial_u64'],'loaded_image_attestation':False,'atomic_snapshot':False}
 except Exception as exc:
  code=str(exc) if isinstance(exc,model.Unknown) and str(exc) in canonical.ERROR_CODES|{'IMAGE_DEADLINE','IMAGE_SIZE_BOUND','IMAGE_TRUNCATED','LOCAL_PHYSICAL_IMAGE_ONLY','IMAGE_DRIVE_NOT_FIXED','IMAGE_REPARSE'} else 'IMAGE_OPERATION_UNKNOWN'
  emit('CANONICAL_FILE_HALT',{'phase':phase,'error_code':code,'errno':canonical.error_number(getattr(exc,'errno',None)),'win32_error':canonical.error_number(getattr(exc,'winerror',None))});raise
 finally:
  rows=[];errors=False
  for label,f in reversed(files):
   try:f.close();row={'phase':label,'file_descriptor_owner':'Python_file_object','python_file_closed':f.closed,'status':'OK' if f.closed else 'UNKNOWN','native_CloseHandle_result':'NOT_EXPORTED_BY_CPYTHON','borrowed_handle_not_separately_closed':True};errors|=not f.closed
   except OSError as exc:errors=True;row={'phase':label,'status':'UNKNOWN','errno':canonical.error_number(exc.errno),'win32_error':canonical.error_number(getattr(exc,'winerror',None))}
   rows.append(row)
  # Close all owned file objects first, even if publishing a close record then fails.
  for row in rows:emit('FILE_CLOSE_RESULT',row)
  model.need(not errors,'FILE_CLOSE_UNKNOWN')
