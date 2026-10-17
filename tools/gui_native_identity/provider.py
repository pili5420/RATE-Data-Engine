"""Replaceable DATA-ONLY Windows Provider Boundary. No function-pointer injection.

This is the only provider admitted by the candidate. Real DLL dispatch, WinEvent
hooks and live Permit loading do not exist. API requests/receipts are auditable;
the fake world and fault plan are deterministic synthetic input data.
"""
import copy,struct
from .contracts import PROVIDER_KIND,API_FIELDS,RIGHTS
from .protocol import need,exact,canonical,digest,integer,Denied
from .abi import raw_hex
def text(value):return (value+'\0').encode('utf-16-le').hex()
def times(value):return struct.pack('<8I',value&0xffffffff,value>>32,0,0,0,0,0,0).hex()
def sid_bytes(authority,subs):return bytes([1,len(subs)])+authority.to_bytes(6,'big')+struct.pack('<'+'I'*len(subs),*subs)
class ScriptedWindowsProvider:
 """Strict synthetic provider, no arbitrary callbacks or external code surfaces."""
 def __init__(self,scenario):
  exact(scenario,{'artifact_kind','host','observer','windows','processes','file','faults','start_ns','step_ns'})
  need(scenario['artifact_kind']==PROVIDER_KIND,'REAL_PROVIDER_NOT_IMPLEMENTED')
  canonical(scenario);need(integer(scenario['start_ns'],1) and integer(scenario['step_ns'],1),'SYNTHETIC_CLOCK')
  need(type(scenario['faults']) is list,'FAULT_PLAN_ARRAY')
  fault_calls=set()
  for f in scenario['faults']:
   need(type(f) is dict and integer(f.get('call'),1) and f.get('kind') in {'world_change','error','unknown','delay','receipt_override','exception'},'FAULT_PLAN_SCHEMA')
   need(f['call'] not in fault_calls,'DUPLICATE_FAULT_CALL');fault_calls.add(f['call'])
   exact(f,{'call','kind','path','value'} if f['kind']=='world_change' else {'call','kind','value'} if f['kind'] in {'delay','receipt_override'} else {'call','kind'})
   if f['kind']=='world_change':need(type(f['path']) is list and 1<=len(f['path'])<=8 and f['path'][0] in {'host','observer','windows','processes','file'} and all(type(k) in {str,int} for k in f['path']),'FAULT_PATH_SCHEMA')
   if f['kind']=='delay':need(integer(f['value']),'FAULT_DELAY_INTEGER')
   if f['kind']=='receipt_override':need(type(f['value']) is dict,'FAULT_RECEIPT_OBJECT')
  self.scenario=copy.deepcopy(scenario);self.identity=digest(self.scenario);self.world=copy.deepcopy(scenario);self.world_hash=digest(self.world);self.calls=[];self.handles={};self.borrowed={};self.next_handle=10000;self.used=False
 def _handle(self,kind,pid=0):
  self.next_handle+=1;self.handles[self.next_handle]=(kind,pid);return self.next_handle
 def _owned(self,handle,kind):
  need(integer(handle,1) and handle in self.handles and self.handles[handle][0]==kind,'UNKNOWN_OR_REUSED_HANDLE','INDETERMINATE');return self.handles[handle][1]
 def peek_start_ns(self):
  need(digest(self.scenario)==self.identity,'PROVIDER_INPUT_MUTATED');return self.scenario['start_ns']+len(self.calls)*self.scenario['step_ns']
 def invoke(self,ticket,request):
  need(digest(self.scenario)==self.identity and digest(self.world)==self.world_hash,'PROVIDER_INPUT_OR_WORLD_MUTATED')
  need(type(ticket) is str and len(ticket)==64,'CALL_TICKET_REQUIRED');exact(request,{'api','args','subject','fields','access'})
  api=request['api'];need(api in API_FIELDS,'UNAUTHORIZED_API');canonical(request)
  index=len(self.calls)+1;start=self.scenario['start_ns']+(index-1)*self.scenario['step_ns'];receipt={'api':api,'start_ns':start,'end_ns':start+100,'last_error':0,'status':'OK','result':None}
  fault=next((f for f in self.scenario['faults'] if f['call']==index),None)
  if fault and fault['kind']=='world_change':
   target=self.world
   for key in fault['path'][:-1]:target=target[key]
   target[fault['path'][-1]]=copy.deepcopy(fault['value'])
   self.world_hash=digest(self.world)
  try:receipt['result']=self._execute(api,request['args'])
  except (KeyError,ValueError,TypeError) as exc:receipt.update(status='ERROR',last_error=5,result={'error':str(exc)})
  if fault:
   if fault['kind']=='error':receipt.update(status='ERROR',last_error=5)
   elif fault['kind']=='unknown':receipt.update(status='UNKNOWN')
   elif fault['kind']=='delay':receipt['end_ns']+=fault['value']
   elif fault['kind']=='receipt_override':receipt.update(copy.deepcopy(fault['value']))
   elif fault['kind']=='exception':self.calls.append({'ticket':ticket,'request':copy.deepcopy(request),'receipt':receipt});raise RuntimeError('SYNTHETIC_PROVIDER_CRASH')
  self.calls.append({'ticket':ticket,'request':copy.deepcopy(request),'receipt':copy.deepcopy(receipt)});return receipt
 def _execute(self,api,a):
  w=self.world
  if api=='GetComputerNameExW':need(a=={'format':1,'capacity':256},'HOST_ARGUMENTS');return text(w['host'])
  if api=='GetCurrentProcessId':need(a=={},'NO_ARGS');return w['observer']['pid']
  if api=='GetCurrentThreadId':need(a=={},'NO_ARGS');return w['observer']['tid']
  if api=='GetProcessWindowStation':need(a=={},'NO_ARGS');self.borrowed[400001]=w['observer']['station'];return 400001
  if api=='GetThreadDesktop':
   exact(a,{'tid'});need(integer(a['tid'],1,2**32),'THREAD_INTEGER')
   if a['tid']==w['observer']['tid']:handle=400002;name=w['observer']['desktop']
   else:row=next(x for x in w['windows'] if x['tid']==a['tid']);handle=400002+row['tid'];name=row['desktop']
   self.borrowed[handle]=name;return handle
  if api=='GetUserObjectInformationW':exact(a,{'handle','index','capacity'});need(a['index']==2 and a['capacity']==512 and a['handle'] in self.borrowed,'OBJECT_NAME_ARGUMENTS');return text(self.borrowed[a['handle']])
  if api=='ProcessIdToSessionId':exact(a,{'pid'});return w['processes'][str(a['pid'])]['session_id']
  if api=='EnumWindows':
   exact(a,{'max_windows'});need(integer(a['max_windows'],1,129),'ENUM_BOUND');handles=[x['hwnd'] for x in w['windows']];return {'handles':handles[:a['max_windows']],'complete':len(handles)<=a['max_windows'],'reported_count':len(handles)}
  if api in {'IsWindow','GetWindowThreadProcessId','GetClassNameW'}:
   exact(a,{'hwnd'});row=next((x for x in w['windows'] if x['hwnd']==a['hwnd']),None)
   if api=='IsWindow':return 1 if row and row['alive'] else 0
   need(row is not None,'WINDOW_DISAPPEARED','INDETERMINATE')
   return struct.pack('<II',row['tid'],row['pid']).hex() if api=='GetWindowThreadProcessId' else text(row['class_name'])
  if api=='OpenProcess':exact(a,{'pid','desired_access','inherit'});need(a['desired_access']==RIGHTS['process'] and a['inherit'] is False,'PROCESS_ACCESS');need(str(a['pid']) in w['processes'],'PROCESS_UNKNOWN');return self._handle('process',a['pid'])
  if api=='GetProcessTimes':exact(a,{'handle'});pid=self._owned(a['handle'],'process');return times(w['processes'][str(pid)]['creation'])
  if api=='QueryFullProcessImageNameW':exact(a,{'handle','capacity','flags'});pid=self._owned(a['handle'],'process');need(a['capacity']==32768 and a['flags']==0,'PROCESS_IMAGE_ARGS');return text(w['processes'][str(pid)]['path'])
  if api=='OpenProcessToken':exact(a,{'handle','desired_access'});need(a['desired_access']==8,'TOKEN_ACCESS');return self._handle('token',self._owned(a['handle'],'process'))
  if api=='GetTokenInformation':
   exact(a,{'handle','class'});pid=self._owned(a['handle'],'token');token=w['processes'][str(pid)]['token'];kind=a['class']
   if kind==20:return struct.pack('<I',token['elevated']).hex()
   if kind==18:return struct.pack('<I',token['elevation_type']).hex()
   if kind==25:return sid_bytes(16,[token['integrity_rid']]).hex()
   need(kind==2,'TOKEN_CLASS');return {'sid_copy':sid_bytes(5,[32,544]).hex(),'attributes':token['admin_attributes']}
  if api=='CreateFileW':
   exact(a,{'path','desired_access','share','disposition','flags'});need(a=={'path':w['file']['path'],'desired_access':129,'share':7,'disposition':3,'flags':0x00200000},'FILE_READ_SCOPE');return self._handle('file')
  if api=='GetFinalPathNameByHandleW':exact(a,{'handle','capacity','flags'});self._owned(a['handle'],'file');need(a['capacity']==32768 and a['flags']==0,'FINAL_PATH_ARGS');return text('\\\\?\\'+w['file']['path'])
  if api=='GetFileInformationByHandleEx':
   exact(a,{'handle','class'});self._owned(a['handle'],'file');file=w['file'];kind=a['class']
   if kind==18:return struct.pack('<Q',file['volume_serial']).hex()+file['file_id']
   if kind==1:return struct.pack('<qqIBB2x',len(raw_hex(file['hex'],16*1024*1024)),len(raw_hex(file['hex'],16*1024*1024)),1,0,0).hex()
   need(kind==0,'FILE_INFO_CLASS');return struct.pack('<qqqqI4x',file['creation'],0,file['write'],file['change'],file['attributes']).hex()
  if api=='ReadFile':
   exact(a,{'handle','offset','count'});self._owned(a['handle'],'file');need(integer(a['offset']) and integer(a['count'],1,65537),'READ_RANGE');data=raw_hex(w['file']['hex'],16*1024*1024);return data[a['offset']:a['offset']+a['count']].hex()
  if api=='CloseHandle':exact(a,{'handle'});need(a['handle'] in self.handles,'CLOSE_BORROWED_OR_UNKNOWN_HANDLE');del self.handles[a['handle']];return 1
  raise Denied('UNIMPLEMENTED_SYNTHETIC_API')
