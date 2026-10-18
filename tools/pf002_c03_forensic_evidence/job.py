"""Windows hosted-runner process containment. Imported lazily after signed runner proof."""
import os,subprocess,time,threading,queue,sys,hashlib,json,types,shutil
from pathlib import Path
class ContainmentError(RuntimeError):
 def __init__(self,code,win32_error=None,raw_wait_result=None):super().__init__(code);self.win32_error=win32_error;self.raw_wait_result=raw_wait_result
def checked_command(command,env):
 src=Path(__file__).resolve().parent
 fault=[sys.executable,'-I','-B','-S',str(src/'normal_worker.py')]
 if type(command) is list and command==fault:return 'normal'
 raise ContainmentError('FIXED_WORKER_COMMAND_ONLY_NO_SHELL')
class WindowsJob:
 def __init__(self,signed_proof,env):
  if os.name!='nt':raise ContainmentError('WINDOWS_RUNNER_ONLY')
  # Independently authenticate before ANY kernel dispatch. No caller-controlled bypass flag.
  src=Path(__file__).resolve().parent;raw=(src/'runner_proof.py').read_bytes();m=json.loads((src/'SOURCE_MANIFEST_V1.json').read_bytes())
  if m['files']['runner_proof.py']!={'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}:raise ContainmentError('JOB_PROOF_SOURCE_HASH')
  verifier=types.ModuleType('job_runner_proof');exec(compile(raw,str(src/'runner_proof.py'),'exec',dont_inherit=True),verifier.__dict__)
  verifier.verify_token(signed_proof,(src/'GITHUB_OIDC_JWKS_PINNED.json').read_bytes(),int(time.time()),env.get('PF002_HEAD'),env.get('PF002_RUN_ID'),env.get('PF002_RUN_ATTEMPT'))
  if env.get('PF002_ROLE') not in ('qualification','reproduction'):raise ContainmentError('JOB_FIXED_ROLE')
  self.proof,self.expected_env=signed_proof,dict(env)
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
  self.job_name='Local\\RATE-PF002-C03-'+env['PF002_RUN_ID']+'-'+env['PF002_ROLE']+'-'+os.urandom(16).hex()
  ctypes.set_last_error(0)
  self.job=k.CreateJobObjectW(None,self.job_name)
  if not self.job:raise ContainmentError('JOB_CREATE_FAILED',self.c.get_last_error())
  if ctypes.get_last_error()==183:self.k.CloseHandle(self.job);self.job=None;raise ContainmentError('JOB_ALREADY_EXISTS_NO_REUSE')
  limits=EXT();limits.BasicLimitInformation.LimitFlags=0x2000|0x8;limits.BasicLimitInformation.ActiveProcessLimit=4
  if not k.SetInformationJobObject(self.job,9,ctypes.byref(limits),ctypes.sizeof(limits)):
   error=ctypes.get_last_error();self.close();raise ContainmentError('JOB_LIMIT_FAILED',error)
 def launch(self,command,cwd,env,private,proof):
  """Caller chooses only fixed reviewed worker paths; token goes through anonymous stdin pipe."""
  if self.handles:raise ContainmentError('ONE_CHILD_PER_JOB_NO_REUSE')
  if proof!=self.proof or env!=self.expected_env:raise ContainmentError('JOB_PROOF_OR_ENV_CHANGED')
  leaf=checked_command(command,env)
  expected=Path(env['PF002_RUNNER_ROOT'])/('PF002-C03-'+env['PF002_RUN_ID']+'-1-'+env['PF002_ROLE'])/leaf
  if private!=expected or private!=private.resolve() or str(private)!=env['PF002_PRIVATE_ROOT'] or Path(cwd)!=Path(__file__).resolve().parent.parent.parent:raise ContainmentError('JOB_FIXED_OUTPUT_CWD')
  for p in (private,*private.parents):
   if not p.is_dir() or p.is_symlink() or getattr(p.stat(),'st_file_attributes',0)&0x400:raise ContainmentError('JOB_PHYSICAL_ROOT')
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
     error=self.c.get_last_error();self.api.TerminateProcess(hp,121);self.k.WaitForSingleObject(hp,10000)
     raise ContainmentError('ASSIGN_JOB_BEFORE_RESUME_FAILED',error)
    active_before_resume=self.active();pids_before_resume=self.pids()
    if active_before_resume!=1 or pids_before_resume!=[pid]:raise ContainmentError('SUSPENDED_ROOT_MEMBERSHIP_UNCONFIRMED')
    resumed=self.k.ResumeThread(ht)
    if resumed!=1:raise ContainmentError('RESUME_FAILED_OR_SUSPEND_COUNT_CONFLICT',self.c.get_last_error() if resumed==0xffffffff else None)
   finally:
    if not self.k.CloseHandle(ht):raise ContainmentError('THREAD_HANDLE_CLOSE_FAILED',self.c.get_last_error())
   os.close(read_fd);read_fd=None
   # Bounded proof <=16KiB; child starts reading immediately. No tokens in ENV/argv/files/logs.
   completed=queue.Queue();fd=write_fd;write_fd=None
   def send_proof():
    try:
     with os.fdopen(fd,'wb',buffering=0) as pipe:
      data=json.dumps({'token':proof,'launch_nonce':env['C03_NONCE']},sort_keys=True,separators=(',',':')).encode('ascii')+b'\n'
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
   return {'pid':pid,'tid':tid,'root_handle':int(hp),'assigned_before_resume':True,'suspended_creation':True,'thread_handle_closed':True,'active_before_resume':active_before_resume,'job_pids_before_resume':pids_before_resume}
  finally:
   if read_fd is not None:os.close(read_fd)
   if write_fd is not None:
    try:os.close(write_fd)
    except OSError:pass
 def active(self):
  row=self.ACCT()
  if not self.k.QueryInformationJobObject(self.job,1,self.c.byref(row),self.c.sizeof(row),None):raise ContainmentError('JOB_ACTIVE_UNKNOWN',self.c.get_last_error())
  return row.ActiveProcesses
 def pids(self):
  class IDS(self.c.Structure):
   _fields_=[('assigned',self.w.DWORD),('listed',self.w.DWORD),('ids',self.c.c_size_t*4)]
  row=IDS()
  if not self.k.QueryInformationJobObject(self.job,3,self.c.byref(row),self.c.sizeof(row),None):raise ContainmentError('OWN_JOB_PID_QUERY_FAILED',self.c.get_last_error())
  if row.assigned>4 or row.listed>4 or row.assigned!=row.listed:raise ContainmentError('OWN_JOB_PID_BOUND_OR_INCOMPLETE')
  return list(row.ids)[:row.listed]
 def terminate_owned(self,code):
  if not self.k.TerminateJobObject(self.job,code):raise ContainmentError('OWN_JOB_TERMINATION_FAILED',self.c.get_last_error())
 def wait_owned(self,seconds):
  result=self.k.WaitForSingleObject(self.hp,max(0,int(seconds*1000)))
  if result not in (0,258):raise ContainmentError('WAIT_UNKNOWN',self.c.get_last_error() if result==0xffffffff else None,result)
  return result
 def confirm_handles(self,end):
  for h in self.handles:
   wait=self.k.WaitForSingleObject(h,max(0,int((end-time.monotonic())*1000)))
   if wait!=0:raise ContainmentError('OWN_HANDLE_NOT_SIGNALED_WITHIN_BOUND',self.c.get_last_error() if wait==0xffffffff else None,wait)
 def close(self):
  rows=[]
  if self.job:
   h=self.job;ok=bool(self.k.CloseHandle(h));error=None if ok else self.c.get_last_error()
   rows.append({'kind':'job','handle':int(h),'closed':ok,'win32_error':error})
   if ok:self.job=None
  for h in list(self.handles):
   ok=bool(self.k.CloseHandle(h));error=None if ok else self.c.get_last_error()
   rows.append({'kind':'process','handle':int(h),'closed':ok,'win32_error':error})
   if ok:self.handles.remove(h)
  for index,f in enumerate(getattr(self,'logs',[])):
   try:f.close();rows.append({'kind':'stream','index':index,'closed':True,'win32_error':None})
   except Exception:rows.append({'kind':'stream','index':index,'closed':False,'win32_error':None})
  return {'status':'CLOSED' if all(r['closed'] for r in rows) else 'UNKNOWN','resources':rows,'not_a_termination_proof':True}
