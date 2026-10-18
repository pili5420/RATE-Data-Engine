"""Native calls only after Job's exact signed hosted-runner guard. No global scan."""
import hashlib,os,time
from pathlib import Path
from job import WindowsJob,ContainmentError
import model

def disk_image(path,end,fixed_drive=None):
 """Retired entry: reject every runtime call, never downgrade to Python stat/hash."""
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

class Probe(WindowsJob):
 def __init__(self,token,env,emit,end):
  self.emit=emit;self.end=end;self.opened={};self.phases=set();self.rejected_close_failures=[];super().__init__(token,env)
  try:self.configure()
  except Exception:
   self.emit('CONSTRUCTOR_RESOURCE_CLOSE',self.close());raise
 def configure(self):
  c,w=self.c,self.w
  class PBI(c.Structure):
   _fields_=[('ExitStatus',c.c_int32),('PebBaseAddress',c.c_void_p),('AffinityMask',c.c_size_t),('BasePriority',c.c_int32),('UniqueProcessId',c.c_size_t),('InheritedFromUniqueProcessId',c.c_size_t)]
  class IDS(c.Structure):_fields_=[('assigned',w.DWORD),('listed',w.DWORD),('ids',c.c_size_t*4)]
  self.IDS,self.PBI=IDS,PBI;self.ptr=c.sizeof(c.c_void_p)
  model.need(c.sizeof(w.DWORD)==4 and self.ptr in (4,8) and c.sizeof(self.ACCT)==48 and self.ACCT.ActiveProcesses.offset==40 and IDS.ids.offset==8 and c.sizeof(IDS)==8+4*self.ptr and c.sizeof(PBI)==6*self.ptr and PBI.UniqueProcessId.offset==4*self.ptr and PBI.InheritedFromUniqueProcessId.offset==5*self.ptr,'NATIVE_ABI_LAYOUT')
  self.emit('ABI_LAYOUT',{'pointer_bytes':self.ptr,'DWORD_bytes':4,'accounting_bytes':48,'active_offset':40,'ids_bytes':c.sizeof(IDS),'pid_list_offset':8,'PBI_bytes':c.sizeof(PBI),'PBI_pid_offset':PBI.UniqueProcessId.offset,'PBI_parent_offset':PBI.InheritedFromUniqueProcessId.offset})
  for name,args,result in [('GetDriveTypeW',[w.LPCWSTR],w.UINT),('GetProcessId',[w.HANDLE],w.DWORD),('GetProcessTimes',[w.HANDLE,c.POINTER(w.FILETIME),c.POINTER(w.FILETIME),c.POINTER(w.FILETIME),c.POINTER(w.FILETIME)],w.BOOL),('QueryFullProcessImageNameW',[w.HANDLE,w.DWORD,w.LPWSTR,c.POINTER(w.DWORD)],w.BOOL)]:
   f=getattr(self.k,name);f.argtypes=args;f.restype=result
  self.nt=c.WinDLL('ntdll',use_last_error=True);self.nq=self.nt.NtQueryInformationProcess
  self.nq.argtypes=[w.HANDLE,c.c_int,c.c_void_p,w.DWORD,c.POINTER(w.DWORD)];self.nq.restype=c.c_int32
 def bounded(self):model.need(time.monotonic()<=self.end,'NORMAL_FORENSICS_DEADLINE')
 def fixed_drive(self,anchor):
  self.bounded();model.need(len(anchor)==3 and anchor[1:]==':\\','FIXED_LOCAL_DRIVE_ANCHOR')
  result=self.k.GetDriveTypeW(anchor);self.emit('PROCESS_API',{'api':'GetDriveTypeW','exact_image_volume_anchor':anchor,'raw_result':result,'required_type':3,'no_other_volume_enumeration':True})
  return result==3
 def query(self,kind):
  model.need(type(kind) is int and kind in (1,3),'FIXED_JOB_QUERY_CLASS')
  self.bounded();row=self.ACCT() if kind==1 else self.IDS();length=self.w.DWORD();ok=bool(self.k.QueryInformationJobObject(self.job,kind,self.c.byref(row),self.c.sizeof(row),self.c.byref(length)));error=None if ok else self.c.get_last_error()
  raw=self.c.string_at(self.c.byref(row),self.c.sizeof(row));self.emit('RAW_JOB_QUERY',{'info_class':kind,'job_name':self.job_name,'job_handle':int(self.job),'ok':ok,'win32_error':error,'buffer_bytes':len(raw),'returned_bytes':length.value,'raw_hex':raw.hex(),'observation_monotonic_ns':time.monotonic_ns()})
  model.need(ok,'JOB_QUERY_UNKNOWN')
  decoded=model.acct(raw,length.value) if kind==1 else model.ids(raw,length.value,self.ptr)
  if kind==1:model.need(decoded['ActiveProcesses']==row.ActiveProcesses,'ACCT_DECODER_DISAGREEMENT')
  else:model.need(decoded['pids']==list(row.ids)[:row.listed] and decoded['assigned']==row.assigned,'IDS_DECODER_DISAGREEMENT')
  return decoded
 def active(self):return self.query(1)['ActiveProcesses']
 def pids(self):return self.query(3)['pids']
 def record_api(self,name,ok,data):
  self.emit('PROCESS_API',{'api':name,'ok':bool(ok),'win32_error':None if ok else self.c.get_last_error(),**data,'observation_monotonic_ns':time.monotonic_ns()});model.need(bool(ok),'PROCESS_API_UNKNOWN')
 def membership(self,h,pid):
  inside=self.w.BOOL();ok=self.k.IsProcessInJob(h,self.job,self.c.byref(inside));self.record_api('IsProcessInJob',ok,{'pid_candidate':pid,'handle':int(h),'inside':bool(inside.value),'job_handle':int(self.job)})
  return bool(inside.value)
 def identity(self,h,pid,require_member=True):
  self.bounded();inside=self.membership(h,pid)
  model.need(inside or not require_member,'PID_NOT_THIS_OWN_JOB')
  actual=self.k.GetProcessId(h);self.record_api('GetProcessId',actual!=0,{'handle':int(h),'pid':actual});model.need(actual==pid,'PID_HANDLE_MISMATCH')
  def times():
   rows=[self.w.FILETIME() for _ in range(4)];ok=self.k.GetProcessTimes(h,*[self.c.byref(r) for r in rows]);v=[r.dwLowDateTime+(r.dwHighDateTime<<32) for r in rows]
   self.record_api('GetProcessTimes',ok,{'handle':int(h),'filetimes_100ns':v});return v
  first=times();model.need(first[0]>0,'CREATION_TIME_UNKNOWN')
  def image():
   buf=self.c.create_unicode_buffer(32768);n=self.w.DWORD(32768);ok=self.k.QueryFullProcessImageNameW(h,0,buf,self.c.byref(n));error=None if ok else self.c.get_last_error()
   self.emit('PROCESS_API',{'api':'QueryFullProcessImageNameW','handle':int(h),'ok':bool(ok),'win32_error':error,'capacity_utf16_units':32768,'returned_utf16_units':n.value,'evidence_max_utf16_units':4096,'raw_utf16le_hex':self.c.string_at(buf,n.value*2).hex() if ok and n.value<=4096 else None})
   model.need(bool(ok) and 0<n.value<=4096,'IMAGE_PATH_UNKNOWN_OR_TRUNCATED');raw=self.c.string_at(buf,n.value*2);text=raw.decode('utf-16-le','strict');model.need('\0' not in text,'IMAGE_PATH_EMBEDDED_NUL');return text
  path=image();disk=disk_image(path,self.end,self.fixed_drive)
  info=self.PBI();returned=self.w.DWORD();status=self.nq(h,0,self.c.byref(info),self.c.sizeof(info),self.c.byref(returned));raw=self.c.string_at(self.c.byref(info),self.c.sizeof(info))
  selected={'pid_slice':raw[4*self.ptr:5*self.ptr].hex(),'parent_slice':raw[5*self.ptr:6*self.ptr].hex()}
  self.emit('PROCESS_API',{'api':'NtQueryInformationProcess','class':0,'handle':int(h),'NTSTATUS':status,'returned_bytes':returned.value,'buffer_bytes':len(raw),'selected_raw_fields':selected,'unrequested_PEB_priority_affinity_fields_not_exported':True})
  model.need(status==0,'PBI_QUERY_UNKNOWN_NO_RIGHTS_FALLBACK');parent=model.pbi(raw,returned.value,self.ptr);model.need(parent['pid']==pid,'PBI_PID_MISMATCH')
  second=times();confirmed_path=image();after=self.membership(h,pid)
  model.need(first[0]==second[0] and path==confirmed_path and (after or not require_member),'PROCESS_IDENTITY_CHANGED')
  wait=self.k.WaitForSingleObject(h,0);error=self.c.get_last_error() if wait==0xffffffff else None;self.emit('PROCESS_API',{'api':'WaitForSingleObject','handle':int(h),'timeout_ms':0,'raw_result':wait,'win32_error':error});model.need(wait in (0,258),'MEMBER_WAIT_UNKNOWN')
  code=self.w.DWORD();ok=self.k.GetExitCodeProcess(h,self.c.byref(code));self.record_api('GetExitCodeProcess',ok,{'handle':int(h),'exit_code':code.value})
  result={'pid':pid,'handle':int(h),'creation_time_100ns':first[0],'exit_time_100ns':second[1],'filetimes_before':first,'filetimes_after':second,'image_path':path,'disk_image':disk,'pbi':parent,'membership_before':inside,'membership_after':after,'wait_result':wait,'exit_code':code.value,'atomic_snapshot':False}
  self.emit('MEMBER_IDENTITY',result);return result
 def observe(self,phase):
  model.need(phase in ('AFTER_RESUME_BEFORE_WAIT','AFTER_ROOT_WAIT') and phase not in self.phases,'FIXED_PHASE_NO_RETRY');self.phases.add(phase)
  accounting=self.query(1);ids=self.query(3);current=set(ids['pids']);members=[]
  # Acquire handles to all listed candidates before slower image/hash reads.
  for pid in ids['pids']:
   if pid==self.pid or pid in self.opened:continue
   model.need(len(self.opened)<3,'TOTAL_MEMBER_OPEN_BOUND');h=self.k.OpenProcess(0x101000,False,pid);self.record_api('OpenProcess',bool(h),{'pid_candidate':pid,'access_rights':0x101000,'inherit':False,'handle':int(h or 0),'phase':phase})
   # retain for close even if membership check fails; never wait/terminate by PID
   try:model.need(self.membership(h,pid),'PID_REUSE_OR_NOT_OWN_JOB')
   except Exception:
    ok=bool(self.k.CloseHandle(h));row={'handle':int(h),'closed':ok,'win32_error':None if ok else self.c.get_last_error()};self.emit('REJECTED_CANDIDATE_HANDLE_CLOSE',row)
    if not ok:self.rejected_close_failures.append(row)
    raise
   self.opened[pid]=h;self.handles.append(h)
  for pid in ids['pids']:members.append(self.identity(self.hp if pid==self.pid else self.opened[pid],pid))
  result={'phase':phase,'accounting':accounting,'ids':ids,'members':members,'observation_monotonic_ns':time.monotonic_ns(),'atomic_snapshot':False};self.emit('OWN_JOB_OBSERVATION',result);return result
 def root_identity(self):return self.identity(self.hp,self.pid,False)
 def close(self):
  result=super().close()
  if self.rejected_close_failures:
   result['resources']+= [{'kind':'rejected_query_handle','not_retried':True,**r} for r in self.rejected_close_failures];result['status']='UNKNOWN'
  return result
 def cleanup(self):
  end=time.monotonic()+10;self.terminate_owned(126);self.emit('OWN_JOB_CLEANUP_REQUEST',{'requested_exit':126,'job_name':self.job_name,'cleanup_not_containment_PASS':True})
  self.confirm_handles(end);states=[]
  for h in self.handles:
   code=self.w.DWORD();ok=self.k.GetExitCodeProcess(h,self.c.byref(code));self.record_api('GetExitCodeProcess',ok,{'handle':int(h),'exit_code':code.value});states.append({'handle':int(h),'wait_result':0,'exit_code':code.value})
  # No retries/reopening; one terminal read only. This evidence never promotes PASS.
  old=self.end;self.end=end
  try:acct=self.query(1);ids=self.query(3)
  finally:self.end=old
  self.emit('OWN_JOB_CLEANUP_OBSERVATION',{'accounting':acct,'ids':ids,'retained_handle_states':states,'cleanup_not_containment_PASS':True})
