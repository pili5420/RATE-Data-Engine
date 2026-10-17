"""Owned-buffer synthetic decoding for all 21 identity API declarations.

Decoded receipts are offline transport evidence, not independent target identity
or native execution qualification. Native addresses are never dereferenced.
"""
import copy,struct,hashlib
from gui_native_preflight import abi
from gui_native_preflight.protocol import require,exact,uint,rawhex,digest,canonical,Blocked
from .bindings import validate_request,PROTOTYPES,FIELDS,RIGHTS
from .contracts import blocked_runtime

def decode_frame(request,frame,owner,handles):
    validate_request(request);exact(frame,{'source','api','abi','last_error','return_hex','outputs','allocations'})
    require(frame['source']=='SYNTHETIC_OWNED_WIRE_RECEIPT' and frame['api']==request['api'] and frame['abi']==request['abi'],'WIRE_SOURCE_API_ABI')
    require(type(handles) is abi.HandleTable and handles.abi==request['abi'] and handles.owner==owner,'HANDLE_TABLE_OWNER_ABI')
    require(uint(frame['last_error'],32) and frame['last_error']==0,'API_ERROR_UNKNOWN','INDETERMINATE')
    api=request['api'];args=request['args'];out=frame['outputs'];ptr=abi.layout(request['abi'])['pointer'];ret_size=ptr if 'HANDLE' in PROTOTYPES[api][1] or PROTOTYPES[api][1] in {'BORROWED_HWINSTA','BORROWED_HDESK'} else 4
    raw=rawhex(frame['return_hex'],ret_size);ret=abi.word(raw,ret_size)
    arena=abi.ByteArena(request['abi'],owner,frame['allocations'])
    def read(name,size=None):
        require(type(name) is str and name in arena.rows,'OUTPUT_NOT_OWNED')
        row=arena.rows[name];return arena.read(name,row['base'],row['initialized'] if size is None else size,owner,row['generation'])
    def success():require(ret==1,'API_BOOL_FALSE_OR_NONCANONICAL','INDETERMINATE')
    def text(capacity,count,buffer):
        require(arena.rows[buffer]['capacity']==capacity*2,'UTF16_BUFFER_CAPACITY');return abi.utf16(read(buffer).hex(),count,capacity)
    try:
        if api in {'GetCurrentProcessId','GetCurrentThreadId'}:
            exact(out,set());require(ret>0,'ZERO_PROCESS_ID');return {FIELDS[api][0]:ret}
        if api in {'GetProcessWindowStation','GetThreadDesktop','OpenProcess','CreateFileW'}:
            exact(out,{'generation'});kind={'GetProcessWindowStation':'station','GetThreadDesktop':'desktop','OpenProcess':'process','CreateFileW':'file'}[api];handles.register(ret,kind,out['generation'],api in {'GetProcessWindowStation','GetThreadDesktop'});return {FIELDS[api][0]:ret}
        if api=='OpenProcessToken':
            success();exact(out,{'buffer','generation'});value=abi.word(read(out['buffer']),ptr);handles.register(value,'token',out['generation']);return {'token_handle':value}
        if api=='CloseHandle':
            success();exact(out,set());handles.close(args['handle'],args['kind'],args['generation']);return {'closed':True}
        if api=='IsWindow':
            exact(out,set());require(ret in {0,1},'ISWINDOW_UNKNOWN','INDETERMINATE');return {'exists':ret==1}
        if api=='GetWindowThreadProcessId':
            exact(out,{'buffer'});pid=abi.word(read(out['buffer']),4);require(pid>0 and ret>0,'WINDOW_OWNER_UNKNOWN','INDETERMINATE');return {'pid':pid,'tid':ret}
        if api=='ProcessIdToSessionId':
            success();exact(out,{'buffer'});return {'session':abi.word(read(out['buffer']),4)}
        if api in {'GetComputerNameExW','QueryFullProcessImageNameW','GetUserObjectInformationW','GetFinalPathNameByHandleW','GetClassNameW'}:
            if api in {'GetFinalPathNameByHandleW','GetClassNameW'}:exact(out,{'buffer'});count=ret;capacity=args['capacity']
            elif api=='GetUserObjectInformationW':
                success();exact(out,{'buffer','needed_bytes'});require(uint(out['needed_bytes'],32,2) and out['needed_bytes']%2==0,'USER_OBJECT_LENGTH');capacity=args['capacity_bytes']//2;count=out['needed_bytes']//2-1
            else:success();exact(out,{'buffer','count'});capacity=args['capacity'];count=out['count']
            return {FIELDS[api][0]:text(capacity,count,out['buffer'])}
        if api=='EnumWindows':
            success();exact(out,{'buffer','count','complete','source'});count=out['count'];require(uint(count,32) and count<args['max_windows'] and out['complete'] is True and out['source']=='SYNTHETIC_BOUNDED_CALLBACK_TRANSCRIPT','ENUMERATION_INCOMPLETE','INDETERMINATE');data=read(out['buffer']);require(len(data)==count*ptr,'ENUMERATION_BYTES');values=[abi.handle(abi.word(data[i:i+ptr],ptr),request['abi']) for i in range(0,len(data),ptr)];require(len(set(values))==len(values),'DUPLICATE_HWND');return {'hwnds':values,'complete':True}
        if api=='GetProcessTimes':
            success();exact(out,{'buffer'});data=read(out['buffer']);require(len(data)==32,'FOUR_FILETIME_OUTPUTS');return {name:abi.filetime(data[i*8:i*8+8].hex()) for i,name in enumerate(FIELDS[api])}
        if api=='GetTokenInformation':
            success();exact(out,{'buffer','returned_bytes'});row=arena.rows[out['buffer']];require(uint(out['returned_bytes'],32,1) and row['initialized']==out['returned_bytes'] and row['capacity']==args['buffer_bytes'],'TOKEN_BUFFER_RETURN_LENGTH');kind=args['info_class']
            if kind in {1,2,25}:value=abi.token_groups(arena,out['buffer'],row['generation'],kind!=2)
            else:require(out['returned_bytes']==4,'TOKEN_SCALAR_SIZE');value=abi.word(read(out['buffer']),4)
            return {'token':{'class':kind,'value':value}}
        if api=='GetFileInformationByHandleEx':
            success();exact(out,{'buffer'});data=read(out['buffer']);kind=args['info_class'];need={0:40,1:24,18:24}[kind];require(len(data)==args['buffer_bytes']==need,'FILE_INFORMATION_SIZE')
            if kind==18:value={'volume':abi.word(data[:8],8),'file_id':data[8:].hex()}
            elif kind==0:value={'creation':abi.filetime(data[:8].hex()),'access':abi.filetime(data[8:16].hex()),'write':abi.filetime(data[16:24].hex()),'change':abi.filetime(data[24:32].hex()),'attributes':abi.word(data[32:36],4)}
            else:
                require(data[20] in {0,1} and data[21] in {0,1},'FILE_BOOLEAN_FIELDS');value={'allocation':abi.word(data[:8],8),'size':abi.word(data[8:16],8),'links':abi.word(data[16:20],4),'delete_pending':bool(data[20]),'directory':bool(data[21])}
            return {'file_info':value}
        if api=='ReadFile':
            success();exact(out,{'buffer','returned_bytes'});data=read(out['buffer']);require(type(out['returned_bytes']) is int and out['returned_bytes']==len(data)==args['count'],'SHORT_READ','INDETERMINATE');return {'data_hex':data.hex()}
        raise ValueError('UNSUPPORTED_WIRE_API')
    finally:arena.close()

class SyntheticFrames:
    def __init__(self,data):
        exact(data,{'source','attempt_id','scope_sha256','abi','frames'})
        require(data['source']=='SYNTHETIC_READINESS_TRANSPORT_ONLY' and type(data['frames']) is list and 1<=len(data['frames'])<=128 and data['abi'] in {'win32','win64'},'SYNTHETIC_TRANSPORT_BOUND')
        self.data=copy.deepcopy(data);self.pin=digest(data);self.next=0;self.sealed=False
    def take(self,index):
        require(not self.sealed and digest(self.data)==self.pin and type(index) is int and index==self.next and index<len(self.data['frames']),'TRANSPORT_MUTATION_REPLAY_OR_SEALED');self.next+=1;return copy.deepcopy(self.data['frames'][index])

class OfflineReadSession:
    """Durable mock-only read plan. Output is not resolved native identity."""
    def __init__(self,admission,provider,root):
        from .authority import Admission
        from .contracts import BASE_TOOL_SHA256
        from gui_native_preflight.protocol import code_identity
        from gui_native_preflight.journal import accepted_workspace
        from gui_native_identity.protocol import Denied
        require(type(admission) is Admission and type(provider) is SyntheticFrames,'NO_NATIVE_OR_CALLBACK_PROVIDER')
        require(code_identity()==BASE_TOOL_SHA256,'ACCEPTED_JOURNAL_DEPENDENCY_PIN')
        admission.check(admission.clock['sample_tick']);p=admission.permit
        require(provider.pin==p['transport_sha256'] and provider.data['attempt_id']==p['attempt_id'] and provider.data['scope_sha256']==p['scope_sha256'],'SIGNED_TRANSPORT_SCOPE_ATTEMPT')
        try:
            self.workspace=accepted_workspace(root);require(p['scope']['workspace']==str(self.workspace.root) and p['scope']['journal_root']==str(self.workspace.journal) and p['scope']['evidence_root']==str(self.workspace.evidence/p['attempt_id']),'SIGNED_WORKSPACE_BINDING');self.workspace.claim(p)
        except Denied as exc:raise Blocked(str(exc),getattr(exc,'state','INDETERMINATE')) from exc
        self.admission=admission;self.provider=provider;self.handles=abi.HandleTable(provider.data['abi'],p['attempt_id']);self.first=None;self.last=admission.last_tick;self.used=False;self.file_checks=set();self.file_offset=0;self.file_bytes=[]
    def guard_request(self,request):
        validate_request(request);s=self.admission.permit['scope'];api=request['api'];a=request['args']
        require(request['abi']==self.provider.data['abi'],'REQUEST_ABI_CHANGED')
        if 'hwnd' in a:require(a['hwnd']==s['target_hwnd'],'HWND_SCOPE')
        if api=='OpenProcess':require(a['pid']==s['target_pid'],'TARGET_PROCESS_SCOPE')
        if api=='ProcessIdToSessionId':require(a['pid'] in {s['target_pid'],s['observer_pid'],s['parent_pid']},'SESSION_PROCESS_SCOPE')
        if api=='GetThreadDesktop':require(a['tid']==s['target_tid'],'DESKTOP_THREAD_SCOPE')
        if api=='CreateFileW':require(not any(r['kind']=='file' for r in self.handles.entries.values()),'SINGLE_FILE_ACQUISITION_NO_REOPEN')
        if api=='ReadFile':require(self.file_checks=={0,1,18} and a['offset']==self.file_offset,'FILE_ID_METADATA_BEFORE_CONTIGUOUS_READ')
        if 'handle' in a:
            require(a['handle'] in self.handles.entries,'HANDLE_NOT_ACQUIRED');row=self.handles.entries[a['handle']];kind=row['kind']
            required='token' if api=='GetTokenInformation' else 'file' if api in {'GetFinalPathNameByHandleW','GetFileInformationByHandleEx','ReadFile'} else 'process' if api in {'GetProcessTimes','QueryFullProcessImageNameW','OpenProcessToken'} else kind
            require(kind==required and (api!='GetUserObjectInformationW' or kind in {'station','desktop'}),'HANDLE_READ_SCOPE')
            self.handles.require(a['handle'],kind,row['generation'])
            if api=='CloseHandle':require(not row['borrowed'] and a['kind']==kind and type(a['generation']) is int and a['generation']==row['generation'],'OWNED_CLOSE_ONLY')
    def guard_observation(self,request,row):
        s=self.admission.permit['scope'];api=request['api'];a=request['args']
        expected={'GetComputerNameExW':('host',s['host']),'GetCurrentProcessId':('observer_pid',s['observer_pid']),'GetCurrentThreadId':('observer_tid',s['observer_tid']),'ProcessIdToSessionId':('session',s['session']),'GetClassNameW':('class_name',s['target_class']),'GetProcessTimes':('creation',s['target_creation'])}
        if api in expected:
            key,value=expected[api];require(type(row[key]) is type(value) and row[key]==value,'OBSERVED_IDENTITY_MISMATCH')
        if api=='GetWindowThreadProcessId':require(row['pid']==s['target_pid'] and row['tid']==s['target_tid'],'WINDOW_PID_TID_MISMATCH')
        if api=='IsWindow':require(row['exists'] is True,'TARGET_DISAPPEARED','INDETERMINATE')
        if api=='GetTokenInformation':
            kind=row['token']['class'];value=row['token']['value']
            if kind==1:require(value==[{'sid':s['operator_sid'],'attributes':0}],'TOKEN_USER_MISMATCH')
            elif kind==2:
                admins=[v for v in value if v['sid']=='S-1-5-32-544'];require(len(admins)==1 and admins[0]['attributes']&4 and not admins[0]['attributes']&16,'TOKEN_ADMIN_DISABLED_DENY_ONLY')
            elif kind==18:require(type(value) is int and value==2,'TOKEN_ELEVATION_TYPE')
            elif kind==20:require(type(value) is int and value==1,'TOKEN_NOT_ELEVATED')
            elif kind==25:require(len(value)==1 and value[0]['sid']=='S-1-16-12288' and value[0]['attributes']&32,'TOKEN_NOT_HIGH_INTEGRITY')
        if api=='GetUserObjectInformationW':require(row['object_name']==s['station' if self.handles.entries[a['handle']]['kind']=='station' else 'desktop'],'STATION_DESKTOP_MISMATCH')
        if api=='QueryFullProcessImageNameW':
            from .bindings import SYNTHETIC_FILE
            require(row['executable_path']==SYNTHETIC_FILE,'EXECUTABLE_PATH_MISMATCH')
        if api=='GetFinalPathNameByHandleW':
            from .bindings import SYNTHETIC_FILE
            require(row['final_path']==('\\'*2+'?'+'\\'+SYNTHETIC_FILE),'FINAL_EXECUTABLE_PATH_MISMATCH')
        if api=='GetFileInformationByHandleEx':
            value=row['file_info']
            if a['info_class']==18:require(value=={'volume':s['target_volume'],'file_id':s['target_file_id']},'VOLUME_FILE_ID_MISMATCH')
            if a['info_class']==0:require(value['attributes']&0x400==0,'FILE_REPARSE_POINT')
            if a['info_class']==1:require(value['links']==1 and value['delete_pending'] is False and value['directory'] is False and value['size']<=16777216,'FILE_LINK_DIRECTORY_DELETE_OR_SIZE')
            self.file_checks.add(a['info_class'])
        if api=='ReadFile':
            value=bytes.fromhex(row['data_hex']);self.file_bytes.append(value);self.file_offset+=len(value)
    def run(self):
        require(not self.used,'ONE_SHOT_NO_RETRY');self.used=True;rows=[]
        try:
            p=self.admission.permit;s=p['scope']
            for i in range(len(self.provider.data['frames'])):
                require(i<s['max_calls'],'CALL_BUDGET');plan=self.provider.data['frames'][i];exact(plan,{'request','receipt','start_tick','end_tick','subject_sha256'})
                require(uint(plan['start_tick'],64,1) and uint(plan['end_tick'],64,1) and self.last<=plan['start_tick']<=plan['end_tick'] and plan['end_tick']-plan['start_tick']<=s['per_call_ns'] and plan['end_tick']-self.admission.clock['sample_tick']<=s['total_ns'],'CALL_ORDER_TIMEOUT','INDETERMINATE')
                require(plan['subject_sha256']==digest({k:s[k] for k in ['host','boot','session','target_pid','target_tid','target_hwnd','target_creation','target_class','target_executable_sha256','target_file_id','target_volume','generation']}),'TARGET_SUBJECT_CHANGED')
                self.admission.check(plan['start_tick']);self.workspace.verify();self.guard_request(plan['request']);frame=self.provider.take(i);require(frame==plan,'RECEIPT_SUBSTITUTED')
                decoded=decode_frame(frame['request'],frame['receipt'],p['attempt_id'],self.handles);self.guard_observation(frame['request'],decoded);self.admission.check(plan['end_tick']);self.workspace.verify();rows.append(decoded);self.last=plan['end_tick']
            if self.file_bytes:require(hashlib.sha256(b''.join(self.file_bytes)).hexdigest()==s['target_executable_sha256'],'EXECUTABLE_SHA_MISMATCH')
            result={'status':'OFFLINE_WIRE_TRANSCRIPT_ONLY','decoded':rows,'permit_sha256':digest(p),**blocked_runtime()}
        except Exception as exc:
            result={'status':'INDETERMINATE','reason':str(exc),**blocked_runtime()}
        self.provider.sealed=True
        try:self.workspace.finish({'status':'BLOCKED' if result['status']=='OFFLINE_WIRE_TRANSCRIPT_ONLY' else 'INDETERMINATE','readiness_result':result,**blocked_runtime()})
        except Exception as exc:result={'status':'INDETERMINATE','reason':'JOURNAL_OUTCOME_UNKNOWN:'+str(exc),**blocked_runtime()}
        return result
