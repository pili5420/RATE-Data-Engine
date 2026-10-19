"""Restricted same-process audit guard; not a general sandbox or runtime attestation."""
import sys
from contract import KERNEL_APIS,need
class Boundary:
 def __init__(self,executable,command,cwd):self.state='PREAUTH';self.executable=executable;self.command=command;self.cwd=cwd;self.creations=0
 def arm(self):need(self.state=='PREAUTH','BOUNDARY_ONE_SHOT');self.state='STAGE_A'
 def stop(self):self.state='TERMINAL'
 def audit(self,event,args):
  try:return self._audit(event,args)
  except BaseException:
   self.state='TERMINAL'
   raise
 def _audit(self,event,args):
  if event.startswith('winreg.') or event=='os.system' or event.startswith(('subprocess.','os.spawn','os.exec')):raise PermissionError('NO_SHELL_REGISTRY_OR_UNCONTROLLED_PROCESS')
  if event.startswith('socket.') and self.state!='PREAUTH':raise PermissionError('NO_NETWORK_AFTER_PREAUTH')
  if event=='_winapi.CreateProcess':
   need(self.state=='STAGE_A' and self.creations==0 and len(args)==3 and args==(self.executable,self.command,self.cwd),'ONE_FIXED_NATIVE_ROOT_ONLY');self.creations+=1
  if event=='ctypes.dlopen':need(self.state=='STAGE_A' and args[0] in (None,'kernel32'),'FIXED_STAGE_A_DLL_ONLY')
  if event=='ctypes.dlsym':
   library,name=args;need(self.state=='STAGE_A','NATIVE_BEFORE_AUTH_FORBIDDEN')
   if getattr(library,'_name',None)=='kernel32':need(name in KERNEL_APIS,'FIXED_STAGE_A_API_ONLY')
   else:need(getattr(library,'_name',None) is None and name in ('PyObj_FromPtr','Py_IncRef','Py_DecRef'),'ONLY_REQUIRED_CPYTHON_CTYPES_RUNTIME_SYMBOLS')
 def install(self):sys.addaudithook(self.audit)
