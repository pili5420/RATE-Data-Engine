"""Retained known Root handle only. No member opening, parent lookup or Stage B."""
import os,time
from pathlib import Path
from job import WindowsJob
import model,canonical_file,contract
import cleanup_state as states
from invocation_boundary import known_no_dispatch_rejection
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
  model.need(not getattr(self,'cleanup_attempted',False),'CB01_CLEANUP_ONCE_NO_RETRY');self.cleanup_attempted=True
  phase=getattr(self,'root_phase',None);handle=self.job;name=self.job_name
  model.need(type(handle) is int and handle>0 and type(name) is str and name,'CB01_OWNED_JOB_IDENTITY')
  self.end=time.monotonic()+10
  if phase==states.NO_ROOT:
   model.need('hp' not in vars(self) and 'pid' not in vars(self) and self.handles==[],'CB01_NO_ROOT_STATE_CONTRADICTION')
   model.need(getattr(self,'root_thread_handle',None) is None and 'thread_close' not in vars(self),'CB01_NO_ROOT_THREAD_CONTRADICTION')
   outcome=getattr(self,'root_creation_outcome',None)
   model.need(outcome in ('NOT_ATTEMPTED','AUDIT_REJECTED_BEFORE_DISPATCH'),'CB01_NO_ROOT_DISPATCH_UNPROVEN')
   if outcome=='AUDIT_REJECTED_BEFORE_DISPATCH':
    receipt=getattr(self,'root_pre_dispatch_receipt',None)
    model.need(type(receipt) is dict and receipt.get('audit_event_id')=='_winapi.CreateProcess' and receipt.get('decision')=='REJECT','CB01_NO_ROOT_AUDIT_EVIDENCE_REQUIRED')
    known_no_dispatch_rejection(receipt)
   acct=self.query(1);ids=self.query(3);states.empty_job(acct,ids)
   model.need(self.job==handle and self.job_name==name and self.root_phase==phase,'CB01_JOB_IDENTITY_CHANGED')
   row={'status':'EMPTY_JOB_OBSERVED_PENDING_CLOSE','phase':phase,'job_handle':handle,'job_name':name,'root_handle':None,'accounting':acct,'ids':ids,'no_root_basis':outcome,'audit_rejection':self.root_pre_dispatch_receipt,'containment_qualified':False,'atomic_snapshot':False}
   self.emit('OWN_JOB_CLEANUP_OBSERVATION',row);return row
  model.need(phase in states.ROOT_PHASES and type(getattr(self,'hp',None)) is int and self.hp>0 and self.handles==[self.hp] and type(getattr(self,'pid',None)) is int and 0<self.pid<=0xffffffff,'CB01_ROOT_STATE_OR_HANDLE_UNKNOWN')
  model.need(self.root_creation_outcome=='RETURNED_OWNED_HANDLE','CB01_ROOT_CREATION_EVIDENCE_REQUIRED')
  if phase==states.SUSPENDED:
   row=getattr(self,'unassigned_root_cleanup',None)
   if row is None:
    row={'known_root_handle':self.hp,'pid':self.pid,'assigned':False,'resumed':False,'status':'UNKNOWN','not_containment_qualification':True};self.unassigned_root_cleanup=row
    self.api.TerminateProcess(self.hp,121);wait=self.k.WaitForSingleObject(self.hp,max(0,int((self.end-time.monotonic())*1000)));row['wait_result']=int(wait)
    model.need(wait==0,'CB01_UNASSIGNED_ROOT_WAIT_UNKNOWN');row['status']='KNOWN_ROOT_TERMINAL'
   model.need(row.get('status')=='KNOWN_ROOT_TERMINAL' and row.get('known_root_handle')==self.hp and row.get('pid')==self.pid and row.get('assigned') is False and type(row.get('wait_result')) is int and row['wait_result']==0,'CB01_UNASSIGNED_ROOT_EVIDENCE_UNKNOWN')
  else:
   self.c.set_last_error(0);raw=self.k.TerminateJobObject(self.job,126);ok=bool(raw);error=None if ok else self.c.get_last_error()
   self.emit('OWN_JOB_CLEANUP_REQUEST',{'job_name':self.job_name,'job_handle':int(self.job),'raw_return':int(raw),'ok':ok,'win32_error':error,'requested_exit':126,'cleanup_not_containment_PASS':True});model.need(ok,'OWN_JOB_TERMINATION_FAILED')
  self.confirm_handles(self.end);code=self.w.DWORD();self.c.set_last_error(0);ok=self.k.GetExitCodeProcess(self.hp,self.c.byref(code));self.record_api('GetExitCodeProcess',ok,{'handle':int(self.hp),'exit_code':code.value})
  model.need(type(code.value) is int and code.value!=259,'CB01_ROOT_EXIT_UNKNOWN')
  acct=self.query(1);ids=self.query(3);self.emit('OWN_JOB_CLEANUP_OBSERVATION',{'accounting':acct,'ids':ids,'root_handle':int(self.hp),'root_wait_result':0,'root_exit_code':code.value,'cleanup_not_containment_PASS':True})
  contract.known_domain(acct,ids,self.pid,False)
  model.need(self.job==handle and self.job_name==name and self.root_phase==phase,'CB01_JOB_IDENTITY_CHANGED')
  thread=getattr(self,'thread_close',{}).get('handle',getattr(self,'root_thread_handle',None))
  return {'status':'KNOWN_ROOT_AND_JOB_TERMINAL_OBSERVED','phase':phase,'job_name':name,'job_handle':handle,'root_handle':self.hp,'root_thread_handle':thread,'root_pid':self.pid,'accounting':acct,'ids':ids,'root_wait_result':0,'root_exit_code':code.value,'containment_qualified':False,'atomic_snapshot':False}
 def complete_cleanup(self,observed,closed):
  model.need(observed['phase']==self.root_phase,'CB01_CLEANUP_PHASE_CHANGED')
  row=states.finalize(observed,closed);self.root_phase=row['final_phase'];return row
