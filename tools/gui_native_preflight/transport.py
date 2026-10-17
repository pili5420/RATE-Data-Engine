"""Synthetic transport candidate; no real Windows DLL binder/dispatch route."""
import copy,hashlib
from . import abi
from .contracts import APIS,RIGHTS,BOUNDARY
from .protocol import require,exact,uint,digest,canonical,code_identity,schema_identity
from .trust import Admission
# Declarative C prototypes only. No callable pointers or FFI library are loaded.
C_ABI_SIGNATURES={
 'GetTokenInformation':('HANDLE','INT32','OUT_LPVOID','DWORD','OUT_PDWORD','RET_BOOL32'),
 'GetWindowThreadProcessId':('HWND','OUT_PDWORD','RET_DWORD'),
 'GetClassNameW':('HWND','OUT_LPWSTR','INT32','RET_INT32'),
 'GetProcessTimes':('HANDLE','OUT_PFILETIME','OUT_PFILETIME','OUT_PFILETIME','OUT_PFILETIME','RET_BOOL32'),
 'QueryFullProcessImageNameW':('HANDLE','DWORD','OUT_LPWSTR','INOUT_PDWORD','RET_BOOL32'),
 'ReadFile':('HANDLE','OUT_LPVOID','DWORD','OUT_PDWORD','NULL_OVERLAPPED_ONLY','RET_BOOL32')}
ARGUMENTS={'GetTokenInformation':{'handle','info_class','buffer_bytes'},'GetWindowThreadProcessId':{'hwnd'},'GetClassNameW':{'hwnd','capacity'},'GetProcessTimes':{'handle'},'QueryFullProcessImageNameW':{'handle','flags','capacity'},'ReadFile':{'handle','offset','count'}}
class NativeTransportUnavailable:
 def dispatch(self,*args,**kwargs):raise RuntimeError('REAL_WINDOWS_DLL_BINDING_DISPATCH_NOT_IMPLEMENTED_NOT_AUTHORIZED')
class MockNativeTransport:
 def __init__(self,scenario):
  exact(scenario,{'source','abi','attempt_id','target_sha256','start_tick','handles','frames'})
  require(scenario['source']=='SYNTHETIC_NATIVE_FRAME_TRANSPORT_ONLY' and scenario['abi'] in {'win32','win64'} and type(scenario['attempt_id']) is str and scenario['attempt_id'].startswith('SYNTHETIC-'),'SYNTHETIC_TRANSPORT_ONLY')
  require(uint(scenario['start_tick'],64,1) and type(scenario['frames']) is list and 1<=len(scenario['frames'])<=64,'FRAME_COUNT_OR_CLOCK');self.data=copy.deepcopy(scenario);self.pin=digest(scenario);self.used=False;self.sealed=False;self.calls=[]
 def unchanged(self):require(digest(self.data)==self.pin,'TRANSPORT_DATA_MUTATED','INDETERMINATE')
 def exchange(self,index,ticket):
  self.unchanged();require(not self.sealed and type(index) is int and index==len(self.calls) and index<len(self.data['frames']),'NO_RETRY_SKIP_OR_SEALED_TRANSPORT');require(type(ticket) is str and len(ticket)==64,'CALL_TICKET')
  frame=copy.deepcopy(self.data['frames'][index]);self.calls.append({'index':index,'ticket':ticket,'frame':copy.deepcopy(frame)});return frame

class CallSession:
 def __init__(self,admission,transport,workspace):
  require(type(admission) is Admission and type(transport) is MockNativeTransport,'NO_NATIVE_OR_CALLBACK_PROVIDER');admission.unchanged();transport.unchanged();require(not transport.used and hasattr(workspace,'intent') and workspace.intent['model_sha256']==digest(admission.payload),'DURABLE_INTENT_BEFORE_TRANSPORT')
  model=admission.payload;scope=model['scope'];require(transport.pin==model['transport_sha256'] and transport.data['attempt_id']==model['attempt_id'] and transport.data['abi']==scope['abi'] and transport.data['target_sha256']==digest(scope['target']),'TRANSPORT_MODEL_IDENTITY_BINDING')
  transport.used=True;self.transport=transport;self.admission=admission;self.workspace=workspace;self.model_pin=digest(model);self.code_pin=code_identity();self.failed=False;self.finished=False;self.first=None;self.last=transport.data['start_tick'];self.begin=transport.data['start_tick'];self.handles=abi.HandleTable(scope['abi'],model['attempt_id'])
  exact(transport.data['handles'],{'process','token','file','generation'});generation=transport.data['handles']['generation'];require(uint(generation,32,1),'HANDLE_GENERATION')
  for kind in ['process','token','file']:self.handles.register(transport.data['handles'][kind],kind,generation)
 def _request(self,frame):
  model=self.admission.payload;scope=model['scope'];target=scope['target'];api=frame['api'];require(api in APIS,'UNAUTHORIZED_NATIVE_API');require(canonical(frame['fields'])==canonical(list(APIS[api])) and canonical(frame['rights'])==canonical(RIGHTS),'UNAUTHORIZED_FIELD_OR_RIGHT')
  require(canonical(frame['subject'])==canonical({k:target[k] for k in ['pid','hwnd','tid','creation','generation']}),'TARGET_SUBJECT_CHANGED')
  a=frame['args'];exact(a,ARGUMENTS[api]);require(all(type(v) is int for v in a.values()),'NATIVE_ARGUMENT_TYPE')
  if 'hwnd' in a:require(abi.handle(a['hwnd'],scope['abi'])==target['hwnd'],'HWND_SCOPE')
  if 'handle' in a:
   kind='token' if api=='GetTokenInformation' else 'file' if api=='ReadFile' else 'process';require(a['handle']==self.transport.data['handles'][kind],'EXACT_REGISTERED_HANDLE');self.handles.require(a['handle'],kind,self.transport.data['handles']['generation'])
  if api=='GetTokenInformation':require(a['info_class'] in {1,2,18,20,25} and 1<=a['buffer_bytes']<=1048576,'TOKEN_CLASS_AND_BUFFER')
  if 'capacity' in a:require(2<=a['capacity']<=32768,'UTF16_CAPACITY')
  if api=='QueryFullProcessImageNameW':require(a['flags']==0,'IMAGE_QUERY_FLAGS')
  if api=='ReadFile':require(0<=a['offset']<=16777216 and 1<=a['count']<=65536 and a['offset']+a['count']<=16777216,'FILE_RANGE_BOUND')
 def call(self,index):
  try:
   require(not self.failed and not self.finished,'SESSION_FAILED_OR_TERMINAL_NO_RETRY');self.workspace.verify();self.admission.unchanged();self.transport.unchanged();model=self.admission.payload;scope=model['scope']
   require(code_identity()==self.code_pin==model['tool_sha256'] and schema_identity()==model['schema_sha256'] and digest(model)==self.model_pin,'CODE_SCHEMA_MODEL_MUTATED');require(index<len(self.transport.data['frames']) and index<scope['max_calls'],'CALL_BOUND')
   plan=self.transport.data['frames'][index];exact(plan,{'api','args','subject','fields','rights','start_tick','end_tick','status','last_error','return_hex','outputs','allocations'})
   self._request(plan);require(uint(plan['start_tick'],64,1) and plan['start_tick']>=self.last and plan['start_tick']-self.begin<=scope['total_ns'],'PRECALL_DEADLINE','INDETERMINATE')
   require(model['issued_utc_ns']<=self.admission.host['utc_ns']+plan['start_tick']-self.begin<model['expires_utc_ns'],'PRECALL_PERMIT_EXPIRY','INDETERMINATE')
   ticket=digest({'model':self.model_pin,'index':index,'request':{k:plan[k] for k in ['api','args','subject','fields','rights']}});frame=self.transport.exchange(index,ticket)
   require(frame==plan,'TRANSPORT_RECEIPT_SUBSTITUTED');require(uint(frame['last_error'],32) and frame['status']=='OK' and frame['last_error']==0,'NATIVE_ERROR_OR_UNKNOWN','INDETERMINATE')
   require(uint(frame['end_tick'],64,1) and frame['start_tick']<=frame['end_tick'] and frame['end_tick']-frame['start_tick']<=scope['per_call_ns'] and frame['end_tick']-self.begin<=scope['total_ns'] and self.admission.host['utc_ns']+frame['end_tick']-self.begin<model['expires_utc_ns'],'TIMEOUT_OR_EXPIRED','INDETERMINATE')
   arena=abi.ByteArena(scope['abi'],model['attempt_id'],frame['allocations'])
   try:decoded=self._decode(frame,arena)
   finally:arena.close()
   self.admission.unchanged();self.workspace.verify();require(code_identity()==self.code_pin and schema_identity()==model['schema_sha256'],'POSTCALL_CODE_SCHEMA_CHANGED');self.first=frame['start_tick'] if self.first is None else self.first;self.last=frame['end_tick'];return decoded
  except BaseException:self.failed=True;self.transport.sealed=True;raise
 def _decode(self,f,arena):
  from .protocol import rawhex
  api=f['api'];a=f['args'];out=f['outputs'];ret=abi.word(rawhex(f['return_hex'],4),4)
  def read(name,n=None):
   require(name in arena.rows,'OUTPUT_BUFFER_NOT_OWNED');row=arena.rows[name];return arena.read(name,row['base'],row['initialized'] if n is None else n,arena.owner,row['generation'])
  if api=='GetTokenInformation':
   exact(out,{'buffer','returned_bytes'});require(ret==1 and uint(out['returned_bytes'],32,1),'TOKEN_BOOL_AND_RETURN_LENGTH');row=arena.rows[out['buffer']];require(row['capacity']==a['buffer_bytes'] and row['initialized']==out['returned_bytes'],'TOKEN_RETURNED_CAPACITY')
   value=abi.token_groups(arena,out['buffer'],row['generation'],mandatory=a['info_class'] in {1,25}) if a['info_class'] in {1,2,25} else abi.word(read(out['buffer'],4),4)
   if a['info_class'] in {18,20}:require(out['returned_bytes']==4,'TOKEN_SCALAR_RETURN_LENGTH')
   return {'token_class':a['info_class'],'value':value}
  if api=='GetWindowThreadProcessId':exact(out,{'pid_buffer'});pid=abi.word(read(out['pid_buffer']),4);require(ret>0 and pid>0,'WINDOW_OWNER_ZERO');return {'tid':ret,'pid':pid}
  if api in {'GetClassNameW','QueryFullProcessImageNameW'}:
   exact(out,{'text_buffer'} if api=='GetClassNameW' else {'text_buffer','count'});count=ret if api=='GetClassNameW' else out['count'];require(api=='GetClassNameW' or ret==1,'IMAGE_QUERY_FAILED');require(arena.rows[out['text_buffer']]['capacity']==a['capacity']*2,'TEXT_ALLOCATION_CAPACITY');value=abi.utf16(read(out['text_buffer']).hex(),count,a['capacity']);return {'class_name' if api=='GetClassNameW' else 'executable_path':value}
  if api=='GetProcessTimes':exact(out,{'times_buffer'});require(ret==1,'GET_PROCESS_TIMES_FAILED');data=read(out['times_buffer']);require(len(data)==32,'FOUR_FILETIME_OUTPUTS');return {'creation':abi.filetime(data[:8].hex())}
  if api=='ReadFile':exact(out,{'data_buffer','returned_bytes'});require(ret==1 and type(out['returned_bytes']) is int and out['returned_bytes']==a['count'],'SHORT_FILE_READ','INDETERMINATE');data=read(out['data_buffer']);require(len(data)==a['count'],'FILE_DATA_LENGTH');return {'file_offset':a['offset'],'data_hex':data.hex()}
  raise ValueError('UNSUPPORTED_NATIVE_ABI')
 def finish(self):require(not self.failed and not self.finished,'SESSION_NO_RETRY');self.finished=True;self.transport.sealed=True
