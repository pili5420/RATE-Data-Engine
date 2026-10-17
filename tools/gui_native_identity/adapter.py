"""Native identity-only adapter CANDIDATE over a strictly synthetic Provider.

No live provider substitution, native binder, real Permit loader or diagnostic
operation is admitted. Post-call time checks are not native cancellation proof.
"""
import copy,hashlib,struct,traceback,threading
from . import abi
from .contracts import KIND,PROVIDER_KIND,API_FIELDS,ARG_KEYS,RIGHTS,FINAL_GATE
from .protocol import need,exact,integer,canonical,digest,validate_model,windows_path,Denied,code_identity,schema_identity,bound_schema,schema_check,MODEL_KEYS
from .provider import ScriptedWindowsProvider
from .witness import LifecycleWitness
from .journal import SyntheticWorkspace
from .baseline import accepted

class NativeCallGuard:
 def __init__(self,model,provider,workspace):
  need(type(provider) is ScriptedWindowsProvider,'ONLY_SEALED_SYNTHETIC_PROVIDER');need(hasattr(workspace,'intent') and workspace.intent['model_sha256']==digest(model),'DURABLE_INTENT_REQUIRED')
  self.model,self.provider,self.workspace=model,provider,workspace;self.model_hash=digest(model);self.code_hash=code_identity();self.failed=False;self.terminal=False;self.calls=[];self.last_end=model['issued_tick_ns'];self.first=None;self.owned={};self.borrowed={};self.windows=set();self.owners={};self.enum_calls=0
 def _subject_pid(self,subject):
  role=subject.get('role');o=self.model['scope']['observer']
  if role in {'observer','parent'}:
   need(set(subject)<={'role','pid'},'CONTEXT_SUBJECT_FIELDS');pid=o['pid'] if role=='observer' else o['parent_pid'];need('pid' not in subject or type(subject['pid']) is int and subject['pid']==pid,'CONTEXT_PID_SCOPE');return pid
  need(role=='window' and set(subject)<={'role','pid','hwnd'} and integer(subject.get('hwnd'),1) and subject['hwnd'] in self.windows,'UNREGISTERED_ENUMERATION_SUBJECT')
  if 'pid' in subject:need(type(subject['pid']) is int and self.owners.get(subject['hwnd'],(None,None))[1]==subject['pid'],'WINDOW_OWNER_PID_SCOPE')
  return self.owners.get(subject['hwnd'],(None,None))[1]
 def _arguments(self,api,args,subject):
  exact(args,ARG_KEYS[api])
  for k,v in args.items():
   if k not in {'path','inherit'}:need(integer(v),'NATIVE_ARGUMENT_INTEGER:'+k)
  if api=='GetComputerNameExW':need(args=={'format':1,'capacity':256},'HOST_ARGUMENT_SCOPE')
  if api=='GetUserObjectInformationW':need(args['index']==2 and args['capacity']==512,'OBJECT_INFO_ARGUMENT_SCOPE')
  if api in {'QueryFullProcessImageNameW','GetFinalPathNameByHandleW'}:need(args['capacity']==32768 and args['flags']==0,'IMAGE_NAME_ARGUMENT_SCOPE')
  pid=self._subject_pid(subject);role=subject['role'];s=self.model['scope']
  global_apis={'GetComputerNameExW','GetCurrentProcessId','GetCurrentThreadId','GetProcessWindowStation','EnumWindows'}
  if api in global_apis:need(role=='observer','CONTEXT_ONLY_API')
  if api in {'IsWindow','GetWindowThreadProcessId','GetClassNameW'}:need(role=='window' and args=={'hwnd':subject['hwnd']} and type(args['hwnd']) is int,'EXACT_WINDOW_SUBJECT')
  if api in {'OpenProcess','ProcessIdToSessionId'}:need(integer(args.get('pid'),1,2**32) and args['pid']==pid,'EXACT_PROCESS_SUBJECT')
  if api=='GetThreadDesktop':
   tid=s['observer']['tid'] if role=='observer' else self.owners.get(subject.get('hwnd'),(None,None))[0];need(role in {'observer','window'} and type(args.get('tid')) is int and args['tid']==tid,'EXACT_THREAD_SUBJECT')
  if api=='EnumWindows':self.enum_calls+=1;need(self.enum_calls<=2 and args=={'max_windows':s['max_windows']} and type(args['max_windows']) is int,'ENUMERATION_RETRY_OR_BOUND')
  if api in {'GetProcessTimes','QueryFullProcessImageNameW','OpenProcessToken','GetTokenInformation','ReadFile','GetFileInformationByHandleEx','GetFinalPathNameByHandleW','CloseHandle'}:
   handle=args.get('handle');need(integer(handle,1) and handle in self.owned,'UNKNOWN_OR_BORROWED_HANDLE')
   expected='process' if api in {'GetProcessTimes','QueryFullProcessImageNameW','OpenProcessToken'} else 'token' if api=='GetTokenInformation' else 'file' if api!='CloseHandle' else self.owned[handle]['kind']
   record=self.owned[handle];need(record['kind']==expected and record['pid']==pid and record['role']==role and record.get('hwnd')==subject.get('hwnd'),'HANDLE_SUBJECT_OR_KIND_MISMATCH')
  if api=='GetUserObjectInformationW':need(integer(args.get('handle'),1) and args['handle'] in self.borrowed and self.borrowed[args['handle']]==subject,'BORROWED_OBJECT_SUBJECT_MISMATCH')
  if api in {'GetTokenInformation','GetFileInformationByHandleEx'}:need(type(args.get('class')) is int and args['class'] in ({2,18,20,25} if api=='GetTokenInformation' else {0,1,18}),'NATIVE_INFO_CLASS')
  if api in {'QueryFullProcessImageNameW','GetFinalPathNameByHandleW','CreateFileW','ReadFile','GetFileInformationByHandleEx'}:need(role=='window','TARGET_EXECUTABLE_ONLY')
 def _register(self,api,result,args,subject):
  if api in {'OpenProcess','OpenProcessToken','CreateFileW'}:
   need(integer(result,1) and result not in self.owned and result not in self.borrowed,'INVALID_OR_REUSED_OWNED_HANDLE','INDETERMINATE')
   self.owned[result]={'kind':{'OpenProcess':'process','OpenProcessToken':'token','CreateFileW':'file'}[api],'pid':self._subject_pid(subject),'role':subject['role'],'hwnd':subject.get('hwnd')}
  if api in {'GetThreadDesktop','GetProcessWindowStation'}:need(integer(result,1) and result not in self.owned,'INVALID_BORROWED_HANDLE');self.borrowed[result]=dict(subject)
  if api=='CloseHandle':need(type(result) is int and result==1,'CLOSE_HANDLE_FAILED');del self.owned[args['handle']]
  if api=='EnumWindows':
   exact(result,{'handles','complete','reported_count'});need(type(result['handles']) is list and result['complete'] is True and type(result['reported_count']) is int and len(result['handles'])==result['reported_count']<=self.model['scope']['max_windows'],'ENUMERATION_INCOMPLETE_OR_BOUND','INDETERMINATE')
   need(all(integer(h,1) for h in result['handles']) and len(set(result['handles']))==len(result['handles']),'ENUMERATION_HANDLE_ALIAS_OR_DUPLICATE','INDETERMINATE');self.windows=set(result['handles'])
  if api=='GetWindowThreadProcessId':
   owner=abi.owner_pair(result);hwnd=subject['hwnd'];need(hwnd not in self.owners or self.owners[hwnd]==owner,'HWND_REUSE_OR_OWNER_CHANGED','INDETERMINATE');self.owners[hwnd]=owner
 def call(self,api,args,subject,fields=None,access=None):
  try:
   need(not self.failed,'FAILED_NATIVE_GUARD_NO_RETRY');need(not self.terminal,'TERMINAL_ATTEMPT_NO_FURTHER_REQUESTS');self.workspace.verify();need(digest(self.model)==self.model_hash and code_identity()==self.code_hash and schema_identity()==self.model['schema_sha256'],'MODEL_OR_CODE_MUTATED_OR_SCHEMA_CHANGED')
   need(api in API_FIELDS,'UNAUTHORIZED_API_OR_DIAGNOSTIC_READ');need(type(args) is dict and type(subject) is dict,'CALL_ARGUMENT_SCHEMA')
   fields=list(API_FIELDS[api]) if fields is None else fields;access=dict(RIGHTS) if access is None else access
   need(canonical(fields)==canonical(list(API_FIELDS[api])) and canonical(access)==canonical(RIGHTS),'EXACT_API_FIELD_ACCESS_BOUNDARY');self._arguments(api,args,subject)
   s=self.model['scope'];need(len(self.calls)<s['max_calls'],'MAX_NATIVE_CALLS','INDETERMINATE')
   if api=='OpenProcess':need(args.get('desired_access')==4096 and type(args.get('desired_access')) is int and args.get('inherit') is False,'PROCESS_ACCESS_RIGHTS')
   if api=='OpenProcessToken':need(type(args.get('desired_access')) is int and args.get('desired_access')==8,'TOKEN_QUERY_RIGHTS')
   if api=='CreateFileW':need(canonical(args)==canonical({'path':s['policy']['executable_path'],'desired_access':129,'share':7,'disposition':3,'flags':0x00200000}),'FILE_READ_SCOPE')
   if api=='ReadFile':need(integer(args.get('offset')) and integer(args.get('count'),1,s['chunk_bytes']+1),'BOUNDED_FILE_READ')
   start=self.provider.peek_start_ns();need(integer(start,1) and self.last_end<=start<self.model['expires_tick_ns'] and start-self.model['issued_tick_ns']<=s['total_ms']*1000000,'PRECALL_DEADLINE','INDETERMINATE')
   req={'api':api,'args':args,'subject':subject,'fields':fields,'access':access};ticket=digest({'model':self.model_hash,'ordinal':len(self.calls)+1,'request':req})
   r=self.provider.invoke(ticket,req);exact(r,{'api','start_ns','end_ns','last_error','status','result'})
   need(r['api']==api and integer(r['start_ns'],1) and integer(r['end_ns'],1) and r['start_ns']==start and self.last_end<=r['start_ns']<=r['end_ns'],'NATIVE_RECEIPT_ORDER_OR_IDENTITY','INDETERMINATE')
   need(r['end_ns']<self.model['expires_tick_ns'] and r['end_ns']-r['start_ns']<=s['per_call_ms']*1000000 and r['end_ns']-self.model['issued_tick_ns']<=s['total_ms']*1000000,'NATIVE_TIMEOUT_OR_EXPIRED','INDETERMINATE')
   need(type(r['last_error']) is int and 0<=r['last_error']<2**32,'NATIVE_ERROR_TYPE')
   self.calls.append({'ticket':ticket,'request':req,'receipt':r});self.first=r['start_ns'] if self.first is None else self.first;self.last_end=r['end_ns']
   need(r['status']=='OK' and r['last_error']==0,'NATIVE_API_ERROR_OR_UNKNOWN','INDETERMINATE');need(digest(self.model)==self.model_hash and code_identity()==self.code_hash and schema_identity()==self.model['schema_sha256'],'MODEL_OR_CODE_MUTATED_OR_SCHEMA_CHANGED');self.workspace.verify();self._register(api,r['result'],args,subject);return r['result']
  except BaseException:self.failed=True;raise

class OfflineIdentityCandidate:
 def __init__(self):self._lock=threading.Lock();self._used=False
 def run(self,model,provider,witness,workspace):
  claimed=False;guard=None
  try:
   with self._lock:need(not self._used,'CANDIDATE_SESSION_ALREADY_CONSUMED');self._used=True
   need(type(workspace) is SyntheticWorkspace and type(provider) is ScriptedWindowsProvider,'OFFLINE_PROVIDER_WORKSPACE_REQUIRED')
   validate_model(model,workspace,provider.identity,digest(witness));workspace.claim(model);claimed=True
   need(not provider.used,'PROVIDER_ATTEMPT_ALREADY_USED');provider.used=True;guard=NativeCallGuard(model,provider,workspace);self.guard=guard;self.model=model
   lifecycle=LifecycleWitness(witness,model);before=self._context();enum=self._call('EnumWindows',{'max_windows':model['scope']['max_windows']},{'role':'observer'})
   exact(enum,{'handles','complete','reported_count'});need(type(enum['handles']) is list and enum['complete'] is True and type(enum['reported_count']) is int and len(enum['handles'])==enum['reported_count']<=model['scope']['max_windows'],'ENUMERATION_INCOMPLETE_OR_BOUND','INDETERMINATE')
   need(all(integer(h,1) for h in enum['handles']) and len(set(enum['handles']))==len(enum['handles']),'ENUMERATION_HANDLE_ALIAS_OR_DUPLICATE','INDETERMINATE')
   candidates=[];excluded=[];self.observed_windows={}
   for hwnd in enum['handles']:
    identity=self._inspect(hwnd,lifecycle)
    if identity is None:excluded.append(hwnd)
    else:candidates.append(identity)
   need(len(candidates)==1,'EXACTLY_ONE_UNIQUE_CANDIDATE','INDETERMINATE')
   after=self._context();need(before==after,'OBSERVER_CONTEXT_CHANGED','INDETERMINATE')
   final_enum=self._call('EnumWindows',{'max_windows':model['scope']['max_windows']},{'role':'observer'});need(set(final_enum['handles'])==set(enum['handles']),'ENUMERATED_WINDOW_SET_CHANGED','INDETERMINATE')
   for hwnd,original in self.observed_windows.items():
    final=self._window(hwnd);need(final==original,'ALL_CANDIDATE_WINDOW_CHANGED','INDETERMINATE');lifecycle.observe_window(final)
   identity=candidates[0];proof=lifecycle.verify(identity,guard.first,guard.last_end,enum['handles'])
   need(not provider.handles and not guard.owned,'OWNED_HANDLE_LEAK','INDETERMINATE')
   result={'artifact_kind':KIND,'status':'RESOLVED_OFFLINE_IDENTITY_ONLY','identity':identity,'identity_sha256':digest(identity),'scope_sha256':model['scope_sha256'],'provider_sha256':provider.identity,'witness':proof,'native_execution_authorized':False,'diagnostic_authorized':False,'independent_review_required':True,'gate2_final_status':FINAL_GATE,'atomic_snapshot':False,'trace':copy.deepcopy(provider.calls),'model_sha256':digest(model),'no_auto_next':True}
  except Exception as exc:
   result={'artifact_kind':KIND,'status':getattr(exc,'state','INDETERMINATE'),'reason':str(exc),'error_type':type(exc).__name__,'traceback':traceback.format_exc(),'native_execution_authorized':False,'diagnostic_authorized':False,'independent_review_required':True,'gate2_final_status':FINAL_GATE,'no_retry':True,'no_resume':True,'no_auto_next':True,'trace':provider.calls if type(provider) is ScriptedWindowsProvider else []}
   if result['status'] not in {'BLOCKED','INDETERMINATE'}:result['status']='INDETERMINATE'
  if claimed:
   if guard is not None:guard.terminal=True
   try:workspace.finish(result)
   except Exception as exc:result={'artifact_kind':KIND,'status':'INDETERMINATE','reason':'JOURNAL_OR_OUTPUT_UNKNOWN:'+str(exc),'native_execution_authorized':False,'diagnostic_authorized':False,'gate2_final_status':FINAL_GATE,'no_retry':True,'no_resume':True,'no_auto_next':True}
  return result
 def _call(self,api,args,subject):return self.guard.call(api,args,subject)
 def _token(self,process,subject):
  token=self._call('OpenProcessToken',{'handle':process,'desired_access':8},subject);values={}
  for kind in [20,18,25,2]:values[kind]=self._call('GetTokenInformation',{'handle':token,'class':kind},subject)
  self._call('CloseHandle',{'handle':token},subject)
  elevation=abi.raw_hex(values[20],4);typ=abi.raw_hex(values[18],4);need(len(elevation)==len(typ)==4,'TOKEN_SCALAR_LAYOUT')
  groups=values[2];exact(groups,{'sid_copy','attributes'});need(integer(groups['attributes'],0,2**32),'TOKEN_GROUP_NATIVE_TYPE')
  t={'status':'OBSERVED','is_elevated':struct.unpack('<I',elevation)[0]==1,'elevation_type':struct.unpack('<I',typ)[0],'integrity_sid':abi.sid(values[25]),'administrators':[{'sid':abi.sid(groups['sid_copy']),'attributes':groups['attributes'],'enabled':bool(groups['attributes']&4),'deny_only':bool(groups['attributes']&16)}]}
  need(accepted().accepted_title_module().admin(t),'ADMIN_FULL_HIGH_INTEGRITY_REQUIRED');return t
 def _context(self):
  s=self.model['scope'];p=s['policy'];o=s['observer'];subject={'role':'observer'}
  host=abi.utf16(self._call('GetComputerNameExW',{'format':1,'capacity':256},subject));pid=self._call('GetCurrentProcessId',{},subject);tid=self._call('GetCurrentThreadId',{},subject)
  need(type(pid) is int and pid==o['pid'] and type(tid) is int and tid==o['tid'] and host==p['host'],'OBSERVER_HOST_PID_TID_MISMATCH')
  station=self._call('GetProcessWindowStation',{},subject);desktop=self._call('GetThreadDesktop',{'tid':tid},subject)
  station_name=abi.utf16(self._call('GetUserObjectInformationW',{'handle':station,'index':2,'capacity':512},subject));desktop_name=abi.utf16(self._call('GetUserObjectInformationW',{'handle':desktop,'index':2,'capacity':512},subject))
  need(station_name==p['observer_station'] and desktop_name==p['desktop'],'OBSERVER_DESKTOP_STATION_MISMATCH')
  observed=[]
  for role,pid,creation in [('observer',o['pid'],o['creation']),('parent',o['parent_pid'],o['parent_creation'])]:
   sub={'role':role,'pid':pid};session=self._call('ProcessIdToSessionId',{'pid':pid},sub);need(type(session) is int and session==p['session_id'],'OBSERVER_PARENT_SESSION_MISMATCH')
   handle=self._call('OpenProcess',{'pid':pid,'desired_access':4096,'inherit':False},sub);ctime=abi.process_creation(self._call('GetProcessTimes',{'handle':handle},sub));need(ctime==creation,'OBSERVER_PARENT_PROCESS_RESTART')
   token=self._token(handle,sub);self._call('CloseHandle',{'handle':handle},sub);observed.append({'role':role,'pid':pid,'creation':ctime,'session':session,'token':token})
  return {'host':host,'observer_station':station_name,'desktop':desktop_name,'processes':observed}
 def _window(self,hwnd):
  p=self.model['scope']['policy'];sub={'role':'window','hwnd':hwnd};alive=self._call('IsWindow',{'hwnd':hwnd},sub);need(type(alive) is int and alive==1,'WINDOW_DISAPPEARED','INDETERMINATE')
  tid,pid=abi.owner_pair(self._call('GetWindowThreadProcessId',{'hwnd':hwnd},sub));klass=abi.utf16(self._call('GetClassNameW',{'hwnd':hwnd},sub));session=self._call('ProcessIdToSessionId',{'pid':pid},sub)
  desktop=self._call('GetThreadDesktop',{'tid':tid},sub);name=abi.utf16(self._call('GetUserObjectInformationW',{'handle':desktop,'index':2,'capacity':512},sub))
  need(type(session) is int and session==p['session_id'] and name==p['desktop'],'WINDOW_SESSION_DESKTOP_MISMATCH');return {'hwnd':hwnd,'pid':pid,'tid':tid,'class_name':klass,'session_id':session,'desktop':name}
 def _file_info(self,handle,sub):
  get=lambda kind:self._call('GetFileInformationByHandleEx',{'handle':handle,'class':kind},sub)
  ident=abi.file_id(get(18));standard=abi.file_standard(get(1));basic=abi.file_basic(get(0));basic.pop('access');return ident|standard|basic
 def _inspect(self,hwnd,witness):
  s=self.model['scope'];p=s['policy'];before=self._window(hwnd);witness.observe_window(before);self.observed_windows[hwnd]=before
  if before['class_name']!=p['class_name']:return None
  sub={'role':'window','hwnd':hwnd,'pid':before['pid']};process=self._call('OpenProcess',{'pid':before['pid'],'desired_access':4096,'inherit':False},sub)
  ctime=abi.process_creation(self._call('GetProcessTimes',{'handle':process},sub));image=windows_path(abi.utf16(self._call('QueryFullProcessImageNameW',{'handle':process,'capacity':32768,'flags':0},sub),32768))
  witness.observe_window(before|{'creation_filetime_100ns':ctime,'executable_path':image})
  if image!=p['executable_path']:self._call('CloseHandle',{'handle':process},sub);return None
  token_before=self._token(process,sub);file=self._call('CreateFileW',{'path':image,'desired_access':129,'share':7,'disposition':3,'flags':0x00200000},sub)
  final=windows_path(abi.utf16(self._call('GetFinalPathNameByHandleW',{'handle':file,'capacity':32768,'flags':0},sub),32768),extended=True);need(final==image,'EXECUTABLE_FINAL_PATH_MISMATCH')
  metadata=self._file_info(file,sub);need(metadata['size']<=s['max_file_bytes'],'EXECUTABLE_SIZE_BOUND');need(metadata['volume_serial']==p['volume_serial'] and metadata['file_id']==p['file_id'],'EXECUTABLE_FILE_ID_MISMATCH')
  h=hashlib.sha256();offset=0
  while offset<metadata['size']:
   count=min(s['chunk_bytes'],metadata['size']-offset);data=abi.raw_hex(self._call('ReadFile',{'handle':file,'offset':offset,'count':count},sub),s['chunk_bytes']);need(len(data)==count,'SHORT_OR_TRUNCATED_FILE_READ','INDETERMINATE');h.update(data);offset+=count
  need(h.hexdigest()==p['executable_sha256'],'EXECUTABLE_SHA256_MISMATCH')
  need(self._file_info(file,sub)==metadata,'EXECUTABLE_METADATA_CHANGED','INDETERMINATE')
  final_after=windows_path(abi.utf16(self._call('GetFinalPathNameByHandleW',{'handle':file,'capacity':32768,'flags':0},sub),32768),extended=True);need(final_after==image,'FINAL_PATH_CHANGED','INDETERMINATE')
  ctime_after=abi.process_creation(self._call('GetProcessTimes',{'handle':process},sub));image_after=windows_path(abi.utf16(self._call('QueryFullProcessImageNameW',{'handle':process,'capacity':32768,'flags':0},sub),32768));need(ctime_after==ctime and image_after==image,'PROCESS_RESTART_OR_IMAGE_CHANGED','INDETERMINATE')
  need(self._token(process,sub)==token_before,'TARGET_TOKEN_CHANGED','INDETERMINATE')
  self._call('CloseHandle',{'handle':file},sub);self._call('CloseHandle',{'handle':process},sub);need(self._window(hwnd)==before,'HWND_PID_TID_OR_CLASS_CHANGED','INDETERMINATE')
  generation=witness.generation(hwnd,before['pid'],before['tid'],ctime)
  return before|{'host':p['host'],'observer_station':p['observer_station'],'creation_filetime_100ns':ctime,'executable_path':image,'executable_sha256':h.hexdigest(),'volume_serial':metadata['volume_serial'],'file_id':metadata['file_id'],'window_epoch':generation}

def validate_review_ack(ack,result,model):
 exact(ack,{'artifact_kind','decision','identity_sha256','evidence_sha256','scope_sha256','tool_sha256','schema_sha256','diagnostic_authorized'})
 need(ack['artifact_kind']=='SYNTHETIC_REVIEW_ACK_NOT_EXECUTION_AUTHORITY' and ack['decision']=='INDEPENDENT_REVIEW_ONLY' and ack['diagnostic_authorized'] is False,'ACK_IS_NOT_EXECUTION_AUTHORITY')
 schema,pin=bound_schema();schema_check(model,schema);exact(model,MODEL_KEYS)
 need(model['artifact_kind']==KIND and model['stage']=='IDENTITY_ONLY' and model['tool_sha256']==code_identity() and model['schema_sha256']==pin and digest(model['scope'])==model['scope_sha256'],'REVIEW_ACK_MODEL_BINDING')
 need(result['artifact_kind']==KIND and result['status']=='RESOLVED_OFFLINE_IDENTITY_ONLY' and result['model_sha256']==digest(model) and result['scope_sha256']==model['scope_sha256'] and result['provider_sha256']==model['provider_sha256'] and digest(result['identity'])==result['identity_sha256'] and result['native_execution_authorized'] is False and result['diagnostic_authorized'] is False and result['gate2_final_status']==FINAL_GATE and ack['identity_sha256']==result['identity_sha256'] and ack['evidence_sha256']==digest(result) and ack['scope_sha256']==model['scope_sha256'] and ack['tool_sha256']==model['tool_sha256'] and ack['schema_sha256']==model['schema_sha256'],'REVIEW_ACK_IDENTITY_EVIDENCE_SCOPE_BINDING')
 return {'status':'REVIEW_ACK_BOUND_SYNTHETIC_ONLY','native_execution_authorized':False,'diagnostic_authorized':False,'gate2_final_status':FINAL_GATE}
