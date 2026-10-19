"""Windows hosted-runner process containment. Imported lazily after signed runner proof."""
import os,subprocess,time,threading,queue,sys,hashlib,json,types,shutil
from pathlib import Path
import cleanup_state as states
from invocation_boundary import AuditRefused,known_no_dispatch_rejection
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
  self.controls={};self.pending_fds=set();self.logs=[];self.io_tasks=[];self.release_sent=False;self.ready_received=False;self.launch_attempted=False;self.unassigned_root_cleanup=None
  if env.get('PF002_SCOPE')!='STAGE_A_ROOT_ONLY':raise ContainmentError('STAGE_A_SCOPE_ONLY')
  import ctypes
  from ctypes import wintypes as w
  import _winapi
  self.c,self.w,self.api=ctypes,w,_winapi;self.handles=[];self.job=None
  self.root_phase=states.NO_ROOT;self.root_creation_outcome='NOT_ATTEMPTED';self.root_pre_dispatch_receipt=None;self.root_thread_handle=None
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
   ('IsProcessInJob',[w.HANDLE,w.HANDLE,ctypes.POINTER(w.BOOL)],w.BOOL)]:
   fn=getattr(k,name);fn.argtypes=args;fn.restype=result
  self.job_name='Local\\RATE-PF002-C04-R3-'+env['PF002_RUN_ID']+'-'+env['PF002_ROLE']+'-'+os.urandom(16).hex()
  ctypes.set_last_error(0)
  self.job=k.CreateJobObjectW(None,self.job_name)
  error=ctypes.get_last_error();self.emit('JOB_API',{'api':'CreateJobObjectW','raw_return':int(self.job or 0),'ok':bool(self.job),'win32_error':error if not self.job or error==183 else None,'already_exists':error==183,'job_name':self.job_name})
  if not self.job:raise ContainmentError('JOB_CREATE_FAILED',error)
  if error==183:
   h=self.job;self.job=None;raw=self.k.CloseHandle(h);close_error=None if raw else self.c.get_last_error()
   self.emit('JOB_API',{'api':'CloseHandle','raw_return':int(raw),'ok':bool(raw),'win32_error':close_error,'existing_job_never_owned':True,'handle':int(h)})
   raise ContainmentError('JOB_ALREADY_EXISTS_NO_REUSE')
  limits=EXT();limits.BasicLimitInformation.LimitFlags=0x2000|0x8;limits.BasicLimitInformation.ActiveProcessLimit=4
  raw=k.SetInformationJobObject(self.job,9,ctypes.byref(limits),ctypes.sizeof(limits));error=None if raw else ctypes.get_last_error()
  self.emit('JOB_API',{'api':'SetInformationJobObject','information_class':9,'raw_return':int(raw),'ok':bool(raw),'win32_error':error,'limit_flags':0x2000|0x8,'active_process_limit':4})
  if not raw:raise ContainmentError('JOB_LIMIT_FAILED',error)
 def launch(self,command,cwd,env,private,proof):
  """Caller chooses only fixed reviewed worker paths; token goes through anonymous stdin pipe."""
  if self.handles or self.launch_attempted:raise ContainmentError('ONE_CHILD_PER_JOB_NO_REUSE')
  self.launch_attempted=True
  if proof!=self.proof or env!=self.expected_env:raise ContainmentError('JOB_PROOF_OR_ENV_CHANGED')
  leaf=checked_command(command,env)
  expected=Path(env['PF002_RUNNER_ROOT'])/('PF002-C04-R3-'+env['PF002_RUN_ID']+'-1-'+env['PF002_ROLE'])/leaf
  if private!=expected or private!=private.resolve() or str(private)!=env['PF002_PRIVATE_ROOT'] or Path(cwd)!=Path(__file__).resolve().parent.parent.parent:raise ContainmentError('JOB_FIXED_OUTPUT_CWD')
  for p in (private,*private.parents):
   if not p.is_dir() or p.is_symlink() or getattr(p.stat(),'st_file_attributes',0)&0x400:raise ContainmentError('JOB_PHYSICAL_ROOT')
  import msvcrt
  release_read,release_write=self.owned_pipe();ready_read,ready_write=self.owned_pipe()
  self.controls={'release_write':release_write,'ready_read':ready_read}
  self.pending_fds.difference_update((release_write,ready_read))
  os.set_inheritable(release_read,True);os.set_inheritable(ready_write,True)
  os.set_inheritable(release_write,False);os.set_inheritable(ready_read,False)
  read_fd,write_fd=self.owned_pipe()
  os.set_inheritable(read_fd,True);os.set_inheritable(write_fd,False)
  for path,mode in ((private/'stdout.private','xb'),(private/'stderr.private','xb'),(os.devnull,'rb')):self.logs.append(open(path,mode))
  for f in self.logs:os.set_inheritable(f.fileno(),True)
  si=subprocess.STARTUPINFO();si.dwFlags|=subprocess.STARTF_USESTDHANDLES
  auth_handle=msvcrt.get_osfhandle(read_fd)
  si.hStdInput=msvcrt.get_osfhandle(self.logs[2].fileno());si.hStdOutput=msvcrt.get_osfhandle(self.logs[0].fileno());si.hStdError=msvcrt.get_osfhandle(self.logs[1].fileno())
  si.lpAttributeList={'handle_list':[auth_handle,msvcrt.get_osfhandle(release_read),msvcrt.get_osfhandle(ready_write),si.hStdInput,si.hStdOutput,si.hStdError]}
  env={**env,'PF002_AUTH_PIPE':str(auth_handle),'PF002_RELEASE_PIPE':str(msvcrt.get_osfhandle(release_read)),'PF002_READY_PIPE':str(msvcrt.get_osfhandle(ready_write))}
  try:
   hp,ht,pid,tid=self.create_root(command,cwd,env,si)
   active_before_resume,pids_before_resume=self.assign_and_resume(hp,ht,pid,tid,len(si.lpAttributeList['handle_list']))
   os.close(read_fd);self.pending_fds.discard(read_fd);read_fd=None
   # Bounded proof <=16KiB; child starts reading immediately. No tokens in ENV/argv/files/logs.
   fd=write_fd;write_fd=None
   data=json.dumps({'token':proof,'launch_nonce':env['C04_R3_NONCE']},sort_keys=True,separators=(',',':')).encode('ascii')+b'\n'
   if len(data)>20000:raise ContainmentError('PROOF_BYTES_BOUND')
   def send_proof(pipe):
    remaining=data
    while remaining:
     count=pipe.write(remaining)
     if not count:raise BrokenPipeError()
     remaining=remaining[count:]
    return True
   completed=self.start_io(fd,'wb',send_proof,'proof_sender')
   try:sent=completed.get(timeout=10)
   except queue.Empty:sent=False
   if not sent:
    raise ContainmentError('PROOF_DELIVERY_FAILED_UNKNOWN_NO_RETRY')
   return {'pid':pid,'tid':tid,'root_handle':int(hp),'assigned_before_resume':True,'suspended_creation':True,'thread_handle_closed':True,'active_before_resume':active_before_resume,'job_pids_before_resume':pids_before_resume}
  finally:
   for fd in (release_read,ready_write):os.close(fd);self.pending_fds.discard(fd)
   if read_fd is not None:os.close(read_fd);self.pending_fds.discard(read_fd)
   if write_fd is not None:
    try:os.close(write_fd);self.pending_fds.discard(write_fd)
    except OSError:pass
 def create_root(self,command,cwd,env,si):
  # Called only after launch validated fixed command/context and built explicit pipes.
  if type(command) is not list or not all(type(x) is str for x in command):raise ContainmentError('CB01_FIXED_COMMAND_TYPES')
  checked_command(command,self.expected_env)
  if type(cwd) not in (str,type(Path())) or str(cwd)!=str(Path(__file__).resolve().parent.parent.parent):raise ContainmentError('CB01_EXACT_CWD_REQUIRED')
  if self.root_phase!=states.NO_ROOT or self.root_creation_outcome!='NOT_ATTEMPTED' or self.launch_attempted is not True:raise ContainmentError('CB01_CREATE_ONCE_FROM_NO_ROOT')
  self.root_phase='CREATE_OUTCOME_UNKNOWN';self.root_creation_outcome='UNKNOWN'
  try:hp,ht,pid,tid=self.api.CreateProcess(str(command[0]),subprocess.list2cmdline([str(x) for x in command]),None,None,True,0x4|0x08000000|0x80000,env,str(cwd),si)
  except AuditRefused as exc:
   if exc.audit_event=='_winapi.CreateProcess' and exc.pre_dispatch is True and exc.recorded is True and exc.receipt['decision']=='REJECT':
    known_no_dispatch_rejection(exc.receipt)
    self.root_phase=states.NO_ROOT;self.root_creation_outcome='AUDIT_REJECTED_BEFORE_DISPATCH';self.root_pre_dispatch_receipt=exc.receipt
   raise
  self.hp=hp;self.pid=pid;self.handles=[hp];self.root_thread_handle=ht
  self.root_phase=states.SUSPENDED;self.root_creation_outcome='RETURNED_OWNED_HANDLE'
  return hp,ht,pid,tid
 def owned_pipe(self):
  pair=os.pipe();self.pending_fds.update(pair);return pair
 def assign_and_resume(self,hp,ht,pid,tid,inherited_count):
  """Own both returned handles before any fallible evidence publishing."""
  assigned=None;owned_thread=getattr(self,'root_thread_handle',None)
  try:
   if type(owned_thread) is not int or owned_thread<=0 or owned_thread in (self.job,getattr(self,'hp',None)):raise ContainmentError('CB01_OWNED_ROOT_THREAD_REGISTRY_UNKNOWN')
   if type(ht) is not int or ht!=owned_thread or type(hp) is not int or hp!=getattr(self,'hp',None) or self.handles!=[hp] or type(pid) is not int or pid!=getattr(self,'pid',None) or getattr(self,'root_creation_outcome',None)!='RETURNED_OWNED_HANDLE':raise ContainmentError('CB01_RETURNED_HANDLE_ARGUMENT_MISMATCH')
   if self.root_phase!=states.SUSPENDED:raise ContainmentError('CB01_SUSPENDED_STATE_REQUIRED')
   assigned=False
   self.emit('JOB_API',{'api':'CreateProcess','ok':True,'win32_error':None,'pid':pid,'tid':tid,'process_handle':int(hp),'thread_handle':int(ht),'creation_flags':0x4|0x08000000|0x80000,'explicit_inherited_handle_count':inherited_count,'job_handle_not_inherited':True})
   assigned=None;self.root_phase='ASSIGN_OUTCOME_UNKNOWN'
   raw=self.k.AssignProcessToJobObject(self.job,hp);error=None if raw else self.c.get_last_error();assigned=bool(raw);self.root_phase=states.ASSIGNED if assigned else states.SUSPENDED
   self.emit('JOB_API',{'api':'AssignProcessToJobObject','raw_return':int(raw),'ok':assigned,'win32_error':error,'job_handle':int(self.job),'root_handle':int(hp),'before_resume':True})
   if not assigned:raise ContainmentError('ASSIGN_JOB_BEFORE_RESUME_FAILED',error)
   active=self.active();pids=self.pids()
   if active!=1 or pids!=[pid]:raise ContainmentError('SUSPENDED_ROOT_MEMBERSHIP_UNCONFIRMED')
   self.root_phase='RESUME_OUTCOME_UNKNOWN'
   resumed=self.k.ResumeThread(ht);error=self.c.get_last_error() if resumed==0xffffffff else None
   if resumed==1:self.root_phase=states.RESUMED
   self.emit('JOB_API',{'api':'ResumeThread','raw_return':int(resumed),'win32_error':error,'required_previous_suspend_count':1,'thread_handle':int(ht)})
   if resumed!=1:raise ContainmentError('RESUME_FAILED_OR_SUSPEND_COUNT_CONFLICT',error)
   return active,pids
  finally:
   try:
    if assigned is False:
     row={'known_root_handle':int(hp),'pid':pid,'assigned':False,'resumed':False,'termination_wrapper_success':False,'wait_result':None,'win32_error':None,'not_containment_qualification':True};self.unassigned_root_cleanup=row
     try:
      self.api.TerminateProcess(hp,121);row['termination_wrapper_success']=True
      wait=self.k.WaitForSingleObject(hp,10000);row['wait_result']=int(wait);row['win32_error']=self.c.get_last_error() if wait==0xffffffff else None
      if wait!=0:raise ContainmentError('UNASSIGNED_ROOT_TERMINATION_UNKNOWN',row['win32_error'],wait)
     except BaseException as exc:
      row['status']='UNKNOWN';row['win32_error']=getattr(exc,'win32_error',getattr(exc,'winerror',row['win32_error']));raise
     else:row['status']='KNOWN_ROOT_TERMINAL'
    elif assigned is None:self.unassigned_root_cleanup={'status':'UNKNOWN','assigned':None,'not_containment_qualification':True}
   finally:
    if type(owned_thread) is int and owned_thread>0 and owned_thread not in (self.job,getattr(self,'hp',None)):
     raw=self.k.CloseHandle(owned_thread);error=None if raw else self.c.get_last_error();self.thread_close={'handle':owned_thread,'raw_return':int(raw),'closed':bool(raw),'win32_error':error}
     if raw and getattr(self,'root_thread_handle',None)==owned_thread:self.root_thread_handle=None
     if not raw:raise ContainmentError('THREAD_HANDLE_CLOSE_FAILED',error)
 def start_io(self,fd,mode,operation,name):
  """Transfer FD ownership explicitly; unfinished threads make close UNKNOWN."""
  completed=queue.Queue();row={'name':name,'fd':fd,'thread':None,'started':False,'closed':False};self.io_tasks.append(row);self.pending_fds.discard(fd)
  def target():
   pipe=None;value=None
   try:
    pipe=os.fdopen(fd,mode,buffering=0);value=operation(pipe)
   except BaseException:pass
   finally:
    try:
     if pipe is None:os.close(fd)
     else:pipe.close()
     row['closed']=True
    except BaseException:pass
    completed.put(value)
  try:
   thread=threading.Thread(target=target,daemon=True);row['thread']=thread;thread.start();row['started']=True
  except BaseException:
   # A failed start never loses the FD. An unexpectedly live thread keeps ownership.
   thread=row['thread']
   if thread is None or getattr(thread,'ident',None) is None:
    try:os.close(fd);row['closed']=True
    except OSError:pass
   raise
  return completed
 def await_ready(self,end):
  if self.ready_received or 'ready_read' not in self.controls:raise ContainmentError('READY_ONE_SHOT')
  fd=self.controls['ready_read'];self.pending_fds.add(fd);del self.controls['ready_read']
  completed=self.start_io(fd,'rb',lambda pipe:pipe.read(2),'ready_reader')
  try:value=completed.get(timeout=max(0.001,end-time.monotonic()))
  except queue.Empty:raise ContainmentError('READY_TIMEOUT_UNKNOWN') from None
  if value!=b'R':raise ContainmentError('READY_PROTOCOL_UNKNOWN')
  self.ready_received=True
 def release_worker(self):
  if not self.ready_received or self.release_sent or 'release_write' not in self.controls:raise ContainmentError('RELEASE_ONE_SHOT')
  self.release_sent=True;fd=self.controls.pop('release_write')
  try:
   if os.write(fd,b'1')!=1:raise ContainmentError('RELEASE_WRITE_UNKNOWN')
  finally:
   row={'kind':'release_pipe','closed':False,'win32_error':None};self.release_close=row
   try:os.close(fd);row['closed']=True
   except OSError as exc:row['win32_error']=getattr(exc,'winerror',None);raise
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
  if getattr(self,'resource_close_attempted',False):return {'status':'UNKNOWN','resources':[],'duplicate_close_refused':True,'not_a_termination_proof':True}
  self.resource_close_attempted=True
  rows=[]
  if hasattr(self,'thread_close'):rows.append({'kind':'root_thread',**self.thread_close})
  elif getattr(self,'root_thread_handle',None) is not None:
   h=self.root_thread_handle;raw=None;error=None
   try:raw=self.k.CloseHandle(h);ok=bool(raw);error=None if ok else self.c.get_last_error()
   except BaseException:ok=False
   self.thread_close={'handle':int(h),'raw_return':int(raw) if raw is not None else None,'closed':ok,'win32_error':error};rows.append({'kind':'root_thread',**self.thread_close})
   if ok:self.root_thread_handle=None
  if getattr(self,'root_thread_handle',None) is not None:rows.append({'kind':'unresolved_root_thread','closed':False,'win32_error':None})
  if hasattr(self,'release_close'):rows.append(self.release_close.copy())
  for task in getattr(self,'io_tasks',[]):
   thread=task['thread']
   try:
    if task['started'] and thread is not None:thread.join(1)
    done=task['closed'] and (thread is None or not thread.is_alive())
   except BaseException:done=False
   rows.append({'kind':'io_thread','name':task['name'],'fd_closed':task['closed'],'closed':done,'win32_error':None})
  for fd in list(getattr(self,'pending_fds',set())):
   try:os.close(fd);self.pending_fds.remove(fd);rows.append({'kind':'untransferred_pipe','closed':True,'win32_error':None})
   except OSError:rows.append({'kind':'untransferred_pipe','closed':False,'win32_error':None})
  for name,fd in list(getattr(self,'controls',{}).items()):
   try:os.close(fd);rows.append({'kind':'control_pipe','name':name,'closed':True,'win32_error':None});del self.controls[name]
   except OSError:rows.append({'kind':'control_pipe','name':name,'closed':False,'win32_error':None})
  if self.job:
   h=self.job;self.job=None;raw=None;error=None
   try:raw=self.k.CloseHandle(h);ok=bool(raw);error=None if ok else self.c.get_last_error()
   except BaseException:ok=False
   rows.append({'kind':'job','handle':int(h),'raw_return':int(raw) if raw is not None else None,'closed':ok,'win32_error':error})
  for h in list(self.handles):
   raw=None;error=None
   try:raw=self.k.CloseHandle(h);ok=bool(raw);error=None if ok else self.c.get_last_error()
   except BaseException:ok=False
   rows.append({'kind':'process','handle':int(h),'raw_return':int(raw) if raw is not None else None,'closed':ok,'win32_error':error});self.handles.remove(h)
  for index,f in enumerate(getattr(self,'logs',[])):
   try:f.close();rows.append({'kind':'stream','index':index,'closed':True,'win32_error':None})
   except Exception:rows.append({'kind':'stream','index':index,'closed':False,'win32_error':None})
  return {'status':'CLOSED' if all(r['closed'] for r in rows) else 'UNKNOWN','resources':rows,'not_a_termination_proof':True}
