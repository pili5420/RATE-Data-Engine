"""Retained known Root handle only. No member opening, parent lookup or Stage B."""
import os,time
from pathlib import Path
from job import WindowsJob
import model,canonical_file,contract
from file_evidence import disk_image
class StageAJob(WindowsJob):
 def __init__(self,token,env,emit,end):
  self.emit=emit;self.end=end;self.root_before=None;self.root_after=None
  try:
   super().__init__(token,env);self.configure()
  except BaseException:
   if getattr(self,'job',None) is not None or getattr(self,'handles',[]):
    closed=self.close();self.emit('CONSTRUCTOR_RESOURCE_CLOSE',closed)
   raise
 def bounded(self):model.need(time.monotonic()<=self.end,'NORMAL_STAGE_A_DEADLINE')
 def configure(self):
  c,w=self.c,self.w
  class IDS(c.Structure):_fields_=[('assigned',w.DWORD),('listed',w.DWORD),('ids',c.c_size_t*4)]
  self.IDS=IDS;self.ptr=c.sizeof(c.c_void_p)
  model.need(c.sizeof(w.DWORD)==4 and self.ptr in (4,8) and c.sizeof(self.ACCT)==48 and self.ACCT.ActiveProcesses.offset==40 and IDS.ids.offset==8 and c.sizeof(IDS)==8+4*self.ptr,'NATIVE_ABI_LAYOUT')
  self.emit('ABI_LAYOUT',{'pointer_bytes':self.ptr,'DWORD_bytes':4,'accounting_bytes':48,'active_offset':40,'ids_bytes':c.sizeof(IDS),'pid_list_offset':8,'parent_API_configured':False})
  for name,args,result in [('GetDriveTypeW',[w.LPCWSTR],w.UINT),('GetProcessId',[w.HANDLE],w.DWORD),('GetProcessTimes',[w.HANDLE,c.POINTER(w.FILETIME),c.POINTER(w.FILETIME),c.POINTER(w.FILETIME),c.POINTER(w.FILETIME)],w.BOOL),('QueryFullProcessImageNameW',[w.HANDLE,w.DWORD,w.LPWSTR,c.POINTER(w.DWORD)],w.BOOL)]:
   f=getattr(self.k,name);f.argtypes=args;f.restype=result
  self._signed_file_provider_ready=True;self.file_reader=canonical_file.NativeReader(self)
 def query(self,kind):
  model.need(type(kind) is int and kind in (1,3),'FIXED_JOB_QUERY_CLASS');self.bounded()
  row=self.ACCT() if kind==1 else self.IDS();length=self.w.DWORD();self.c.set_last_error(0)
  result=self.k.QueryInformationJobObject(self.job,kind,self.c.byref(row),self.c.sizeof(row),self.c.byref(length));ok=bool(result);error=None if ok else self.c.get_last_error()
  raw=self.c.string_at(self.c.byref(row),self.c.sizeof(row));self.emit('RAW_JOB_QUERY',{'info_class':kind,'job_name':self.job_name,'job_handle':int(self.job),'raw_return':int(result),'ok':ok,'win32_error':error,'buffer_bytes':len(raw),'returned_bytes':length.value,'raw_hex':raw.hex(),'observation_monotonic_ns':time.monotonic_ns()})
  model.need(ok,'JOB_QUERY_UNKNOWN');decoded=model.acct(raw,length.value) if kind==1 else model.ids(raw,length.value,self.ptr)
  if kind==1:model.need(decoded['ActiveProcesses']==row.ActiveProcesses,'ACCT_DECODER_DISAGREEMENT')
  else:model.need(decoded['pids']==list(row.ids)[:row.listed] and decoded['assigned']==row.assigned,'IDS_DECODER_DISAGREEMENT')
  return decoded
 def active(self):return self.query(1)['ActiveProcesses']
 def pids(self):return self.query(3)['pids']
 def record_api(self,name,ok,data):
  self.emit('PROCESS_API',{'api':name,'raw_return':int(ok),'ok':bool(ok),'win32_error':None if ok else self.c.get_last_error(),**data,'observation_monotonic_ns':time.monotonic_ns()});model.need(bool(ok),'PROCESS_API_UNKNOWN')
 def membership(self,h):
  inside=self.w.BOOL();ok=self.k.IsProcessInJob(h,self.job,self.c.byref(inside));self.record_api('IsProcessInJob',ok,{'pid':self.pid,'handle':int(h),'inside':bool(inside.value),'job_handle':int(self.job)});return bool(inside.value)
 def domain(self,phase,alive):
  acct=self.query(1);ids=self.query(3);self.emit('KNOWN_ROOT_JOB_DOMAIN',{'phase':phase,'root_pid':self.pid,'accounting':acct,'ids':ids,'authorized_domain':'SINGLE_CREATED_ROOT_ONLY','no_unknown_pid_inspection':True})
  return contract.known_domain(acct,ids,self.pid,alive)
 def fixed_drive(self,anchor):
  self.bounded();model.need(len(anchor)==3 and anchor[1:]==':\\','FIXED_LOCAL_DRIVE_ANCHOR')
  result=self.k.GetDriveTypeW(anchor);self.emit('PROCESS_API',{'api':'GetDriveTypeW','exact_image_volume_anchor':anchor,'raw_result':result,'required_type':3,'no_other_volume_enumeration':True});return result==3
 def root_identity(self,phase,executable):
  model.need(phase in ('ROOT_BEFORE','ROOT_AFTER') and (self.root_before is None if phase=='ROOT_BEFORE' else self.root_before is not None and self.root_after is None),'ROOT_PHASE_ONE_SHOT')
  self.bounded();self.domain(phase,True);h=self.hp
  inside=self.membership(h);model.need(inside,'ROOT_NOT_THIS_OWN_JOB')
  actual=self.k.GetProcessId(h);self.record_api('GetProcessId',actual,{'handle':int(h),'pid':actual});model.need(type(actual) is int and actual==self.pid,'PID_HANDLE_MISMATCH')
  def times():
   rows=[self.w.FILETIME() for _ in range(4)];ok=self.k.GetProcessTimes(h,*[self.c.byref(r) for r in rows]);values=[r.dwLowDateTime+(r.dwHighDateTime<<32) for r in rows]
   self.record_api('GetProcessTimes',ok,{'handle':int(h),'filetimes_100ns':values,'exit_time_not_interpreted_while_alive':True});return values
  def image():
   buf=self.c.create_unicode_buffer(32768);n=self.w.DWORD(32768);self.c.set_last_error(0);ok=self.k.QueryFullProcessImageNameW(h,0,buf,self.c.byref(n));error=None if ok else self.c.get_last_error()
   self.emit('PROCESS_API',{'api':'QueryFullProcessImageNameW','handle':int(h),'raw_return':int(ok),'ok':bool(ok),'win32_error':error,'capacity_utf16_units':32768,'returned_utf16_units':n.value,'evidence_max_utf16_units':4096,'raw_utf16le_hex':self.c.string_at(buf,n.value*2).hex() if ok and n.value<=4096 else None})
   model.need(bool(ok) and 0<n.value<=4096,'IMAGE_PATH_UNKNOWN_OR_TRUNCATED');text=self.c.string_at(buf,n.value*2).decode('utf-16-le','strict')
   model.need('\0' not in text and Path(text)==Path(executable),'FIXED_ROOT_EXECUTABLE_CHANGED');return text
  wait0=self.k.WaitForSingleObject(h,0);self.emit('ROOT_LIVENESS',{'phase':phase,'handle':int(h),'raw_wait':wait0,'timeout_ms':0,'win32_error':self.c.get_last_error() if wait0==0xffffffff else None});model.need(wait0==258,'ROOT_EARLY_EXIT_OR_WAIT_UNKNOWN')
  before=times();model.need(before[0]>0,'CREATION_TIME_UNKNOWN');path=image();disk=disk_image(path,self.end,self.fixed_drive,self.emit,self.file_reader)
  after=times();confirmed=image();member=self.membership(h);wait=self.k.WaitForSingleObject(h,0);wait_error=self.c.get_last_error() if wait==0xffffffff else None
  self.emit('ROOT_LIVENESS',{'phase':phase+'_END','handle':int(h),'raw_wait':wait,'timeout_ms':0,'win32_error':wait_error})
  code=self.w.DWORD();ok=self.k.GetExitCodeProcess(h,self.c.byref(code));self.record_api('GetExitCodeProcess',ok,{'handle':int(h),'exit_code':code.value})
  model.need(before[0]==after[0] and path==confirmed and member and wait==258 and code.value==259,'ROOT_IDENTITY_CHANGED_OR_EARLY_EXIT');self.domain(phase+'_END',True)
  row={'phase':phase,'pid':self.pid,'handle':int(h),'creation_time_100ns':before[0],'filetimes_before':before,'filetimes_after':after,'image_path':path,'disk_image':disk,'membership_before':inside,'membership_after':member,'wait_result':wait,'exit_code':code.value,'atomic_snapshot':False,'parent_inspected':False}
  self.emit('ROOT_IDENTITY',row)
  if phase=='ROOT_BEFORE':self.root_before=row
  else:contract.root_equivalent(self.root_before,row);self.root_after=row
  return row
 def cleanup(self):
  self.end=time.monotonic()+10;self.c.set_last_error(0);raw=self.k.TerminateJobObject(self.job,126);ok=bool(raw);error=None if ok else self.c.get_last_error()
  self.emit('OWN_JOB_CLEANUP_REQUEST',{'job_name':self.job_name,'job_handle':int(self.job),'raw_return':int(raw),'ok':ok,'win32_error':error,'requested_exit':126,'cleanup_not_containment_PASS':True});model.need(ok,'OWN_JOB_TERMINATION_FAILED')
  self.confirm_handles(self.end);code=self.w.DWORD();self.c.set_last_error(0);ok=self.k.GetExitCodeProcess(self.hp,self.c.byref(code));self.record_api('GetExitCodeProcess',ok,{'handle':int(self.hp),'exit_code':code.value})
  acct=self.query(1);ids=self.query(3);self.emit('OWN_JOB_CLEANUP_OBSERVATION',{'accounting':acct,'ids':ids,'root_handle':int(self.hp),'root_wait_result':0,'root_exit_code':code.value,'cleanup_not_containment_PASS':True})
  contract.known_domain(acct,ids,self.pid,False)
  return {'status':'KNOWN_ROOT_AND_JOB_TERMINAL_OBSERVED','accounting':acct,'ids':ids,'root_wait_result':0,'root_exit_code':code.value,'containment_qualified':False}
