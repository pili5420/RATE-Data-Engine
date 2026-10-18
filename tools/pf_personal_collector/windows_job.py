"""Windows hosted-runner process containment. Imported lazily after signed runner proof."""
import os,subprocess,time,threading,queue
class ContainmentError(RuntimeError):pass
class WindowsJob:
 def __init__(self):
  if os.name!='nt':raise ContainmentError('WINDOWS_RUNNER_ONLY')
  import ctypes
  from ctypes import wintypes as w
  import _winapi
  self.c,self.w,self.api=ctypes,w,_winapi;self.handles=[];self.job=None
  class BASIC(ctypes.Structure):
   _fields_=[('PerProcessUserTimeLimit',ctypes.c_longlong),('PerJobUserTimeLimit',ctypes.c_longlong),('LimitFlags',w.DWORD),('MinimumWorkingSetSize',ctypes.c_size_t),('MaximumWorkingSetSize',ctypes.c_size_t),('ActiveProcessLimit',w.DWORD),('Affinity',ctypes.c_size_t),('PriorityClass',w.DWORD),('SchedulingClass',w.DWORD)]
  class IO(ctypes.Structure):
   _fields_=[(n,ctypes.c_ulonglong) for n in ('ReadOperationCount','WriteOperationCount','OtherOperationCount','ReadTransferCount','WriteTransferCount','OtherTransferCount')]
  class EXT(ctypes.Structure):
   _fields_=[('BasicLimitInformation',BASIC),('IoInfo',IO),('ProcessMemoryLimit',ctypes.c_size_t),('JobMemoryLimit',ctypes.c_size_t),('PeakProcessMemoryUsed',ctypes.c_size_t),('PeakJobMemoryUsed',ctypes.c_size_t)]
  class ACCT(ctypes.Structure):
   _fields_=[(n,ctypes.c_longlong) for n in ('TotalUserTime','TotalKernelTime','ThisPeriodTotalUserTime','ThisPeriodTotalKernelTime')]+[(n,w.DWORD) for n in ('TotalPageFaultCount','TotalProcesses','ActiveProcesses','TotalTerminatedProcesses')]
  k=ctypes.WinDLL('kernel32',use_last_error=True);self.k=k;self.ACCT=ACCT
  for name,args,result in [
   ('CreateJobObjectW',[ctypes.c_void_p,w.LPCWSTR],w.HANDLE),
   ('SetInformationJobObject',[w.HANDLE,ctypes.c_int,ctypes.c_void_p,w.DWORD],w.BOOL),
   ('QueryInformationJobObject',[w.HANDLE,ctypes.c_int,ctypes.c_void_p,w.DWORD,ctypes.c_void_p],w.BOOL),
   ('AssignProcessToJobObject',[w.HANDLE,w.HANDLE],w.BOOL),
   ('TerminateJobObject',[w.HANDLE,w.UINT],w.BOOL),
   ('ResumeThread',[w.HANDLE],w.DWORD),
   ('CloseHandle',[w.HANDLE],w.BOOL),
   ('WaitForSingleObject',[w.HANDLE,w.DWORD],w.DWORD),
   ('GetExitCodeProcess',[w.HANDLE,ctypes.POINTER(w.DWORD)],w.BOOL),
   ('OpenProcess',[w.DWORD,w.BOOL,w.DWORD],w.HANDLE),
   ('IsProcessInJob',[w.HANDLE,w.HANDLE,ctypes.POINTER(w.BOOL)],w.BOOL)]:
   fn=getattr(k,name);fn.argtypes=args;fn.restype=result
  self.job=k.CreateJobObjectW(None,None)
  if not self.job:raise ContainmentError('JOB_CREATE_FAILED')
  limits=EXT();limits.BasicLimitInformation.LimitFlags=0x2000|0x8;limits.BasicLimitInformation.ActiveProcessLimit=4
  if not k.SetInformationJobObject(self.job,9,ctypes.byref(limits),ctypes.sizeof(limits)):
   self.close();raise ContainmentError('JOB_LIMIT_FAILED')
 def launch(self,command,cwd,env,private,proof):
  """Caller chooses only fixed reviewed worker paths; token goes through anonymous stdin pipe."""
  if self.handles:raise ContainmentError('ONE_CHILD_PER_JOB_NO_REUSE')
  import msvcrt
  read_fd,write_fd=os.pipe()
  os.set_inheritable(read_fd,True);os.set_inheritable(write_fd,False)
  self.logs=[open(private/'stdout.private','xb'),open(private/'stderr.private','xb'),open(os.devnull,'rb')]
  for f in self.logs:os.set_inheritable(f.fileno(),True)
  si=subprocess.STARTUPINFO();si.dwFlags|=subprocess.STARTF_USESTDHANDLES
  auth_handle=msvcrt.get_osfhandle(read_fd)
  si.hStdInput=msvcrt.get_osfhandle(self.logs[2].fileno());si.hStdOutput=msvcrt.get_osfhandle(self.logs[0].fileno());si.hStdError=msvcrt.get_osfhandle(self.logs[1].fileno())
  si.lpAttributeList={'handle_list':[auth_handle,si.hStdInput,si.hStdOutput,si.hStdError]}
  env={**env,'PF002_AUTH_PIPE':str(auth_handle)}
  try:
   hp,ht,pid,tid=self.api.CreateProcess(str(command[0]),subprocess.list2cmdline([str(x) for x in command]),None,None,True,0x4|0x08000000|0x80000,env,str(cwd),si)
   self.hp=hp;self.pid=pid;self.handles=[hp]
   try:
    if not self.k.AssignProcessToJobObject(self.job,hp):
     self.api.TerminateProcess(hp,121);self.k.WaitForSingleObject(hp,10000)
     raise ContainmentError('ASSIGN_JOB_BEFORE_RESUME_FAILED')
    if self.k.ResumeThread(ht)==0xffffffff:raise ContainmentError('RESUME_FAILED')
   finally:self.k.CloseHandle(ht)
   os.close(read_fd);read_fd=None
   # Bounded proof <=16KiB; child starts reading immediately. No tokens in ENV/argv/files/logs.
   completed=queue.Queue();fd=write_fd;write_fd=None
   def send_proof():
    try:
     with os.fdopen(fd,'wb',buffering=0) as pipe:
      data=proof.encode('ascii')+b'\n'
      while data:
       count=pipe.write(data)
       if not count:raise BrokenPipeError()
       data=data[count:]
     completed.put(True)
    except Exception:completed.put(False)
   threading.Thread(target=send_proof,daemon=True).start()
   try:sent=completed.get(timeout=10)
   except queue.Empty:sent=False
   if not sent:
    self.k.TerminateJobObject(self.job,125);self.k.WaitForSingleObject(hp,10000)
    raise ContainmentError('PROOF_DELIVERY_FAILED_UNKNOWN_NO_RETRY')
   return {'pid':pid,'tid':tid,'assigned_before_resume':True,'suspended_creation':True}
  finally:
   if read_fd is not None:os.close(read_fd)
   if write_fd is not None:
    try:os.close(write_fd)
    except OSError:pass
 def active(self):
  row=self.ACCT()
  if not self.k.QueryInformationJobObject(self.job,1,self.c.byref(row),self.c.sizeof(row),None):raise ContainmentError('JOB_ACTIVE_UNKNOWN')
  return row.ActiveProcesses
 def hold_owned_pid(self,pid):
  h=self.k.OpenProcess(0x100000|0x1000,False,pid)
  if not h:raise ContainmentError('OWNED_DESCENDANT_HANDLE_UNAVAILABLE')
  inside=self.w.BOOL()
  if not self.k.IsProcessInJob(h,self.job,self.c.byref(inside)) or not inside.value:
   self.k.CloseHandle(h);raise ContainmentError('NOT_THIS_JOB_DESCENDANT')
  self.handles.append(h)
 def wait(self,seconds):
  started=time.monotonic();code=self.k.WaitForSingleObject(self.hp,int(seconds*1000))
  if code not in (0,258):raise ContainmentError('WAIT_UNKNOWN')
  if code==258:
   if not self.k.TerminateJobObject(self.job,124):raise ContainmentError('CANCELLATION_FAILED')
   for h in self.handles:
    if self.k.WaitForSingleObject(h,10000)!=0:raise ContainmentError('CANCELLATION_NOT_CONFIRMED')
   deadline=time.monotonic()+10
   while self.active()!=0 and time.monotonic()<deadline:time.sleep(.02)
   if self.active()!=0:raise ContainmentError('DESCENDANT_CANCELLATION_UNKNOWN')
  value=self.w.DWORD()
  if not self.k.GetExitCodeProcess(self.hp,self.c.byref(value)):raise ContainmentError('EXIT_CODE_UNKNOWN')
  return {'exit_code':value.value,'deadline_triggered':code==258,'elapsed_ms':int((time.monotonic()-started)*1000),'active_after':self.active(),'provider_work_outside_job_cancelled':'NOT_PROVEN_BLOCKED'}
 def close(self):
  if self.job:self.k.CloseHandle(self.job);self.job=None
  for h in self.handles:self.k.CloseHandle(h)
  self.handles=[]
  for f in getattr(self,'logs',[]):f.close()

