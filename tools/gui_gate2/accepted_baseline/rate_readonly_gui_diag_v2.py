"""External read-only GUI diagnostic. Design approval never authorizes live execution.
Standard-library only. Native DLLs load only after a separately pinned live permit.
No UI input, elevation, settings write, process control, network or RATE imports.
"""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path,PureWindowsPath
import platform
import re
import sys
import traceback

VERSION='RATE_READ_ONLY_GUI_DIAGNOSTIC_V2'
TITLE_PROTOCOL='BOUNDED_TWO_READ_TITLE_V2'
TITLE_CAPACITY=4097
FUTURE_DECISION='CONTROL_CENTER_READ_ONLY_GUI_ENUMERATION_EXECUTION_AUTHORIZED'
ORIGINAL_SHA='f132ca79abc1700bd0b9d71a42a6aab2975452217131fc619942911511d43f06'
TITLES={'虛擬記憶體','虚拟内存','virtual memory'}
NATIVE_IMAGES={'systempropertiesadvanced.exe','systempropertiesperformance.exe','systempropertiescomputername.exe','rundll32.exe','control.exe'}
LIVE_PARENT=Path(r'D:\Codex\RATE-GUI-DIAGNOSTIC-RUNS')
HERE=Path(__file__).resolve().parent
SCHEMA=HERE/'GUI_DIAGNOSTIC_EVIDENCE_SCHEMA_V2.json'
ALLOWED_APIS={'EnumWindows','IsWindow','IsWindowVisible','GetWindowTextLengthW','GetWindowTextW','GetClassNameW','GetWindowThreadProcessId','GetCurrentThreadId','GetThreadDesktop','GetProcessWindowStation','GetUserObjectInformationW','GetCurrentProcessId','ProcessIdToSessionId','OpenProcess','OpenProcessToken','GetTokenInformation','ConvertSidToStringSidW','QueryFullProcessImageNameW','GetProcessTimes','CloseHandle','LocalFree'}

def utc():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def digest(data):return hashlib.sha256(data).hexdigest()
def require(ok,reason):
    if not ok:raise ValueError(reason)
def integer(value):return type(value) is int and 0<=value<2**64
def exact(obj,keys):require(type(obj) is dict and set(obj)==set(keys),'EXACT_SCHEMA_KEYS')
def no_duplicates(pairs):
    out={}
    for k,v in pairs:
        require(k not in out,'DUPLICATE_JSON_KEY');out[k]=v
    return out
def decode(data):
    require(type(data) is bytes and len(data)<=4*1024**2,'JSON_BYTES_OR_SIZE')
    return json.loads(data.decode('utf-8'),object_pairs_hook=no_duplicates,parse_constant=lambda v:(_ for _ in ()).throw(ValueError('NONFINITE_JSON')))
def canonical(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8')
def read_json(path):return decode(Path(path).read_bytes())
def native_image(image):
    path=PureWindowsPath(image)
    return '..' not in path.parts and str(path.parent).casefold() in {r'c:\windows\system32',r'c:\windows\syswow64'} and path.name.lower() in NATIVE_IMAGES
def secure_path(path):
    path=Path(path)
    require(path.is_absolute() and '..' not in path.parts,'ABSOLUTE_NONTRAVERSAL_PATH_REQUIRED')
    raw=str(path);require(not raw.startswith(('\\\\','//','\\?\\','\\.\\')),'UNC_DEVICE_PATH_DENIED')
    require(os.path.normcase(str(path.resolve()))==os.path.normcase(str(path)),'PATH_REDIRECTION_DENIED')
    for part in [path,*path.parents]:
        if part.exists():
            stat=part.lstat();require(not part.is_symlink() and not getattr(stat,'st_file_attributes',0)&1024,'REPARSE_POINT_DENIED')
            if part.is_file():require(stat.st_nlink==1,'HARDLINK_DENIED')
    return path
def write_new(root,name,value):
    root=secure_path(root);require(root.is_dir(),'OUTPUT_DIRECTORY_IDENTITY')
    require(Path(name).name==name,'OUTPUT_FILE_NAME')
    with (root/name).open('xb') as f:f.write(canonical(value)+b'\n');f.flush();os.fsync(f.fileno())
def admin(token):
    if type(token) is not dict:return False
    groups=token.get('administrators')
    return (token.get('status')=='OBSERVED' and token.get('is_elevated') is True and type(token.get('elevation_type')) is int
        and token['elevation_type']==2 and token.get('integrity_sid')=='S-1-16-12288' and type(groups) is list and len(groups)==1
        and groups[0].get('enabled') is True and groups[0].get('deny_only') is False and groups[0].get('sid')=='S-1-5-32-544'
        and type(groups[0].get('attributes')) is int and bool(groups[0]['attributes']&4) and not bool(groups[0]['attributes']&16))
def validate_context(ctx):
    exact(ctx,{'host','observer_pid','parent_pid','session_id','parent_session_id','desktop','window_station','observer_token','parent_token','api_calls'})
    require(all(integer(ctx[k]) for k in ['observer_pid','parent_pid','session_id','parent_session_id']),'CONTEXT_NATIVE_INTEGER')
    require(all(ctx[k]>0 for k in ['observer_pid','parent_pid','session_id']),'HUMAN_CONTEXT_IDS_POSITIVE')
    require(all(type(ctx[k]) is str and ctx[k] for k in ['host','desktop','window_station']),'CONTEXT_IDENTITY_REQUIRED')
def validate_window(win):
    exact(win,{'hwnd','pid','tid','visible','class_name','title','title_length','title_copied','title_complete','title_observation','session_id','desktop','process','stable','api_calls','errors'})
    require(all(integer(win[k]) for k in ['hwnd','pid','tid','title_length','title_copied','session_id']),'WINDOW_NATIVE_INTEGER')
    require(win['hwnd']>0 and (all(win[k]>0 for k in ['pid','tid']) or bool(win.get('errors'))),'WINDOW_IDENTITY_POSITIVE_OR_EXPLICIT_API_FAILURE')
    require(all(type(win[k]) is bool for k in ['visible','title_complete','stable']),'WINDOW_NATIVE_BOOLEAN')
    require(type(win['title']) is str and type(win['class_name']) is str,'WINDOW_STRING_TYPES')
    require(len(win['title'].encode('utf-16-le',errors='surrogatepass'))//2==win['title_copied'],'TITLE_COUNT_MISMATCH')
    require(type(win['desktop']) is str and type(win['process']) is dict and type(win['errors']) is list,'WINDOW_METADATA_SCHEMA')
def calls_valid(calls):
    require(type(calls) is list,'API_CALL_LIST')
    good=True
    for c in calls:
        exact(c,{'api','observed_utc','result','last_error','status'})
        require(c['api'] in ALLOWED_APIS and type(c['observed_utc']) is str,'UNAPPROVED_API_RECORD')
        require(type(c['result']) in {int,bool,str,type(None)},'API_RESULT_NATIVE_TYPE')
        when=datetime.datetime.fromisoformat(c['observed_utc']);require(when.tzinfo is not None and when.utcoffset()==datetime.timedelta(0),'API_UTC_TIMESTAMP')
        require(type(c['last_error']) is int and 0<=c['last_error']<2**32,'API_ERROR_NATIVE_INTEGER')
        require(c['status'] in {'OK','EMPTY','EXPECTED_BUFFER_PROBE','ERROR'},'API_STATUS')
        if c['status']=='ERROR':good=False
    return good
def callback_error_guard(action,errors):
    """Capture ctypes marshalling/unraisable failures outside the Python callback body."""
    original=sys.unraisablehook
    def record(event):
        errors.append({'type':getattr(event.exc_type,'__name__','UnraisableError'),'reason':str(event.exc_value),'visited':0})
    sys.unraisablehook=record
    try:return action()
    finally:sys.unraisablehook=original

def title_reliability(win):
    """Derive bounded observational consistency from raw API evidence, never a flag.
    Two fixed reads are confirmation steps, not retries or an atomic GUI snapshot.
    A partial/contradictory plan never gives a known title matching decision.
    """
    obs=win['title_observation'];exact(obs,{'protocol','phase','length_samples','reads','identities'})
    require(obs['protocol']==TITLE_PROTOCOL and obs['phase'] in {'NOT_STARTED','PARTIAL','OBSERVED'},'TITLE_OBSERVATION_PROTOCOL')
    require(all(type(obs[k]) is list for k in ['length_samples','reads','identities']),'TITLE_OBSERVATION_ARRAYS')
    require(len(obs['length_samples'])<=2 and len(obs['reads'])<=2 and len(obs['identities'])<=3,'TITLE_FIXED_PLAN_BOUND')
    calls=win['api_calls'];reasons=[];lengths=[];reads=[];identities=[];indices=[]
    def bad(reason):
        if reason not in reasons:reasons.append(reason)
    def recorded(index,api):
        require(integer(index),'TITLE_API_INDEX')
        if index>=len(calls):
            bad('MISSING_API_EVIDENCE')
            return {'api':api,'result':None,'last_error':0,'status':'ERROR'}
        return calls[index]
    def link(row,api):
        index=row['api_call_index']
        c=recorded(index,api);indices.append(index)
        if c['api']!=api:bad('API_LINK_MISMATCH')
        if type(c['result']) is not int or c['result']<0 or c['last_error']!=0:bad('API_RESULT_OR_ERROR_UNRELIABLE')
        expected='EMPTY' if c['result']==0 else 'OK'
        if c['status']!=expected:bad('API_STATUS_RESULT_CONTRADICTION')
        if row['hwnd']!=win['hwnd'] or type(row['hwnd']) is not int:bad('HWND_CHANGED_DURING_OBSERVATION')
        return c,index
    for row in obs['length_samples']:
        exact(row,{'stage','hwnd','api_call_index'})
        require(row['stage'] in {'BEFORE','AFTER'},'TITLE_LENGTH_STAGE')
        c,index=link(row,'GetWindowTextLengthW')
        if type(c['result']) is not int or not 0<=c['result']<TITLE_CAPACITY-1:bad('LENGTH_BOUND_OR_TYPE')
        lengths.append({'stage':row['stage'],'api_call_index':index,'hwnd':row['hwnd'],'result':c['result'],'last_error':c['last_error'],'status':c['status']})
    decoded=[]
    for row in obs['reads']:
        exact(row,{'stage','hwnd','api_call_index','capacity_utf16_units','utf16_hex','terminator_utf16_hex','terminator_at_return','no_embedded_nul'})
        require(row['stage'] in {'PRIMARY','CONFIRMATION'},'TITLE_READ_STAGE')
        require(type(row['capacity_utf16_units']) is int and row['capacity_utf16_units']==TITLE_CAPACITY,'TITLE_FIXED_CAPACITY')
        require(type(row['utf16_hex']) is str and len(row['utf16_hex'])<=4*TITLE_CAPACITY and re.fullmatch(r'(?:[0-9a-f]{4})*',row['utf16_hex']) is not None,'TITLE_UTF16_HEX')
        require(type(row['terminator_at_return']) is bool and type(row['no_embedded_nul']) is bool,'TITLE_BUFFER_NATIVE_BOOLEAN')
        require(type(row['terminator_utf16_hex']) is str and re.fullmatch(r'(?:[0-9a-f]{4})?',row['terminator_utf16_hex']) is not None,'TITLE_TERMINATOR_HEX')
        c,index=link(row,'GetWindowTextW');raw=bytes.fromhex(row['utf16_hex']);units=len(raw)//2
        if type(c['result']) is not int or units!=c['result']:bad('COPIED_COUNT_EVIDENCE_MISMATCH')
        if type(c['result']) is not int or not 0<=c['result']<TITLE_CAPACITY-1:bad('POTENTIAL_TRUNCATION_OR_COPY_BOUND')
        embedded=any(raw[n:n+2]==b'\0\0' for n in range(0,len(raw),2))
        if not row['terminator_at_return'] or row['terminator_utf16_hex']!='0000' or not row['no_embedded_nul'] or embedded:bad('TERMINATOR_OR_EMBEDDED_NUL_UNPROVEN')
        try:text=raw.decode('utf-16-le',errors='strict')
        except UnicodeDecodeError:text=None;bad('INVALID_UTF16')
        decoded.append(text)
        reads.append({'stage':row['stage'],'api_call_index':index,'hwnd':row['hwnd'],'capacity_utf16_units':row['capacity_utf16_units'],'result':c['result'],'last_error':c['last_error'],'status':c['status'],'copied_utf16_units':units,'utf16_sha256':digest(raw),'utf16_hex':row['utf16_hex'],'terminator_utf16_hex':row['terminator_utf16_hex'],'terminator_utf16_sha256':digest(bytes.fromhex(row['terminator_utf16_hex'])),'terminator_at_return':row['terminator_at_return'],'no_embedded_nul':row['no_embedded_nul'],'valid_utf16':text is not None})
    for row in obs['identities']:
        exact(row,{'stage','hwnd','pid','tid','is_window_call_index','owner_call_index'})
        require(row['stage'] in {'BEFORE','AFTER_TITLE','AFTER_PROCESS'},'TITLE_IDENTITY_STAGE')
        require(all(integer(row[k]) for k in ['pid','tid','is_window_call_index','owner_call_index']),'TITLE_IDENTITY_NATIVE_INTEGER')
        alive=recorded(row['is_window_call_index'],'IsWindow');owner=recorded(row['owner_call_index'],'GetWindowThreadProcessId')
        indices.extend([row['is_window_call_index'],row['owner_call_index']])
        if (alive['api']!='IsWindow' or type(alive['result']) is not int or alive['result']!=1 or alive['status']!='OK' or alive['last_error']!=0
            or owner['api']!='GetWindowThreadProcessId' or type(owner['result']) is not int or owner['result']!=row['tid'] or owner['status']!='OK' or owner['last_error']!=0):bad('IDENTITY_API_EVIDENCE_MISMATCH')
        if type(row['hwnd']) is not int or row['hwnd']!=win['hwnd'] or row['pid']!=win['pid'] or row['tid']!=win['tid'] or not row['pid'] or not row['tid']:bad('WINDOW_IDENTITY_CHANGED_DURING_OBSERVATION')
        identities.append(dict(row))
    full=(obs['phase']=='OBSERVED' and [r['stage'] for r in lengths]==['BEFORE','AFTER']
        and [r['stage'] for r in reads]==['PRIMARY','CONFIRMATION']
        and [r['stage'] for r in identities]==['BEFORE','AFTER_TITLE','AFTER_PROCESS'])
    if not full:bad('FIXED_OBSERVATION_PLAN_INCOMPLETE')
    if len(set(indices))!=len(indices):bad('API_LINK_REUSED')
    relevant=[i for i,c in enumerate(calls) if c['api'] in {'GetWindowTextLengthW','GetWindowTextW'}]
    expected_order=[]
    if len(lengths)==len(reads)==2:expected_order=[lengths[0]['api_call_index'],reads[0]['api_call_index'],lengths[1]['api_call_index'],reads[1]['api_call_index']]
    if relevant!=expected_order:bad('FIXED_TITLE_API_ORDER_OR_COUNT')
    if full:
        order=[identities[0]['is_window_call_index'],identities[0]['owner_call_index'],*expected_order,
            identities[1]['is_window_call_index'],identities[1]['owner_call_index'],identities[2]['is_window_call_index'],identities[2]['owner_call_index']]
        if order!=sorted(order):bad('IDENTITY_TITLE_ORDER_CONTRADICTION')
        if lengths[0]['result']!=lengths[1]['result']:bad('LENGTH_ESTIMATE_CHANGED')
        if reads[0]['utf16_hex']!=reads[1]['utf16_hex']:bad('TITLE_CHANGED_BETWEEN_READS')
        for length,read in zip(lengths,reads):
            if type(length['result']) is not int or type(read['result']) is not int or length['result']<read['result']:bad('LENGTH_UNDERESTIMATES_COPIED_TEXT')
            if (length['result']==0)!=(read['result']==0):bad('ZERO_LENGTH_INCONSISTENCY')
        if win['title_length']!=lengths[0]['result'] or win['title_copied']!=reads[0]['result'] or win['title']!=decoded[0]:bad('WINDOW_TITLE_API_EVIDENCE_CONTRADICTION')
    return {'protocol':TITLE_PROTOCOL,'phase':obs['phase'],'status':'RELIABLE_BOUNDED_OBSERVATION' if not reasons else 'UNKNOWN_OBSERVATION',
        'reliable':not reasons,'reasons':reasons,'length_samples':lengths,'reads':reads,'identities':identities,
        'declared_complete':win['title_complete'],'atomic_snapshot':False,'confirmation_is_retry':False}

def evaluate(snapshot,mode):
    """Pure synthetic/native-evidence evaluation; original caption/count rules unchanged."""
    require(mode in {'SYNTHETIC','LIVE'},'MODE')
    exact(snapshot,{'context','enumeration','windows'})
    ctx=snapshot['context'];validate_context(ctx)
    enum=snapshot['enumeration'];exact(enum,{'return_value','last_error','visited','completed','callback_errors','truncated','api_calls'})
    require(type(enum['return_value']) is bool and type(enum['truncated']) is bool,'ENUM_BOOLEAN')
    require(all(integer(enum[k]) for k in ['last_error','visited','completed']),'ENUM_NATIVE_INTEGER')
    require(enum['last_error']<2**32,'ENUM_WIN32_ERROR_RANGE')
    require(type(enum['callback_errors']) is list and type(snapshot['windows']) is list,'ENUM_LISTS')
    require(len(snapshot['windows'])<=4096,'WINDOW_LIMIT')
    reasons=[];known=0;matches=[];audit=[];seen=set()
    if not calls_valid(ctx['api_calls']):reasons.append('CONTEXT_API_ERROR')
    if not {'GetThreadDesktop','GetProcessWindowStation','GetUserObjectInformationW','GetTokenInformation'}.issubset({c['api'] for c in ctx['api_calls']}):reasons.append('MISSING_CONTEXT_API_PROVENANCE')
    if not admin(ctx['observer_token']) or not admin(ctx['parent_token']):reasons.append('OBSERVER_OR_HUMAN_PARENT_ADMIN_HIGH_INTEGRITY_UNPROVEN')
    if ctx['parent_session_id']!=ctx['session_id']:reasons.append('OBSERVER_HUMAN_PARENT_SESSION_MISMATCH')
    if not calls_valid(enum['api_calls']) or not enum['return_value'] or enum['callback_errors'] or enum['truncated'] or enum['visited']!=enum['completed'] or enum['completed']!=len(snapshot['windows']):reasons.append('ENUMERATION_INCOMPLETE_OR_CALLBACK_ERROR')
    if sum(c['api']=='EnumWindows' for c in enum['api_calls'])!=1:reasons.append('ENUMERATION_CALL_COUNT_OR_PROVENANCE')
    trace=[c for c in enum['api_calls'] if c['api']=='EnumWindows']
    trace_consistent=len(trace)==1 and type(trace[0]['result']) in {int,bool} and bool(trace[0]['result'])==enum['return_value'] and trace[0]['last_error']==enum['last_error'] and trace[0]['status']==('OK' if enum['return_value'] else 'ERROR')
    if not trace_consistent:reasons.append('ENUMERATION_TRACE_INCONSISTENT')
    for win in snapshot['windows']:
        validate_window(win)
        require(win['hwnd'] not in seen,'DUPLICATE_HWND');seen.add(win['hwnd'])
        api_ok=calls_valid(win['api_calls'])
        title_audit=title_reliability(win)
        if win['title_complete']!=title_audit['reliable']:
            title_audit['reasons'].append('TITLE_COMPLETE_DECLARATION_CONTRADICTION')
            title_audit['status']='UNKNOWN_OBSERVATION';title_audit['reliable']=False
        normalized=win['title'].strip().lower()
        required={'IsWindowVisible','GetWindowTextLengthW','GetWindowThreadProcessId','GetClassNameW','ProcessIdToSessionId','GetThreadDesktop'}
        if win['title_length']>0:required.add('GetWindowTextW')
        reliable=api_ok and required.issubset({c['api'] for c in win['api_calls']}) and not win['errors'] and win['stable'] and title_audit['reliable'] and bool(win['class_name'])
        stages={'visible':win['visible'],'original_length_nonzero':win['title_length']>0,'exact_original_title_match':normalized in TITLES}
        original_match=all(stages.values()) if reliable else None
        if original_match is None:reasons.append('UNRELIABLE_WINDOW_OBSERVATION:'+str(win['hwnd']))
        else:known+=1
        if original_match:matches.append(win)
        image=str(win['process'].get('image',''));native=native_image(image)
        title={'status':'RAW_NATIVE_CANDIDATE' if native or original_match else 'REDACTED_UNRELATED','sha256':digest(win['title'].encode('utf-8',errors='surrogatepass')),'normalized_sha256':digest(normalized.encode('utf-8',errors='surrogatepass')),'codepoint_count':len(win['title']),'reported_length':win['title_length'],'copied_utf16_units':win['title_copied'],'complete':title_audit['reliable']}
        if native or original_match:title.update(raw=win['title'],normalized=normalized,codepoints=[f'U+{ord(c):04X}' for c in win['title']])
        proc=dict(win['process'])
        if not native and not original_match:
            for sample in title_audit['reads']:sample.pop('utf16_hex');sample.pop('terminator_utf16_hex')
            proc={'status':proc.get('status'),'image_basename':Path(image.replace('\\','/')).name,'image_path_sha256':digest(image.encode()),'token':{'status':'NOT_IN_SCOPE_UNRELATED_WINDOW'}}
        failed=[k for k,v in stages.items() if not v]
        audit.append({'hwnd':win['hwnd'],'pid':win['pid'],'tid':win['tid'],'class_name':win['class_name'],'session_id':win['session_id'],'desktop':win['desktop'],'owner_window_station':{'status':'NOT_DIRECTLY_QUERYABLE_OTHER_PROCESS','observer_station':ctx['window_station'],'provenance':'EnumWindows in observer desktop; owner thread desktop separately observed; do not infer a separately queried process station'},'title':title,'title_reliability':title_audit,'process':proc,'stages':stages,'observation_reliable':reliable,'original_match':original_match,'exclusion_reason':'UNKNOWN_OBSERVATION' if original_match is None else ('MATCH' if original_match else failed[0]),'stable':win['stable'],'api_calls':win['api_calls'],'errors':win['errors']})
    if len(matches)!=1:reasons.append('EXACTLY_ONE_HUMAN_VIRTUAL_MEMORY_DIALOG_REQUIRED')
    if len(matches)==1:
        win=matches[0];proc=win['process']
        if not admin(proc.get('token')):reasons.append('ACTUAL_NATIVE_MODIFIER_ADMIN_HIGH_INTEGRITY_UNPROVEN')
        if not native_image(str(proc.get('image',''))):reasons.append('ACTUAL_GUI_NATIVE_OWNER_PATH_UNPROVEN')
        if win['session_id']!=ctx['session_id']:reasons.append('NATIVE_GUI_HUMAN_SESSION_MISMATCH')
        if not win['desktop'] or win['desktop']!=ctx['desktop']:reasons.append('NATIVE_GUI_THREAD_DESKTOP_MISMATCH_OR_UNKNOWN')
        if proc.get('status')!='OBSERVED' or not integer(proc.get('creation_filetime_100ns')) or proc['creation_filetime_100ns']==0:reasons.append('ACTUAL_GUI_PROCESS_IDENTITY_UNPROVEN')
    determinate=known==len(audit) and enum['return_value'] and trace_consistent and calls_valid(enum['api_calls']) and not enum['callback_errors'] and not enum['truncated'] and enum['visited']==enum['completed']==len(audit)
    outcome='INDETERMINATE' if not determinate else ('ZERO_MATCHES' if not matches else 'EXACTLY_ONE_MATCH' if len(matches)==1 else 'MULTIPLE_MATCHES')
    return {'schema_version':VERSION,'mode':mode,'observed_utc':utc(),'source_binding':{'tool_sha256':digest(Path(__file__).read_bytes()),'original_collector_sha256':ORIGINAL_SHA},'context':ctx,'enumeration':enum,'windows':audit,'original_logic_audit':{'known_window_decisions':known,'unknown_window_decisions':len(audit)-known,'filtered_windows':len(matches),'count_determinate':determinate,'count_outcome':outcome,'matched_hwnds':[v['hwnd'] for v in matches],'title_rule':'strip().lower() exact original three captions','count_rule':'exactly1, unchanged'},'gate':{'status':'PASS_DIAGNOSTIC_EVIDENCE_ONLY' if not reasons else 'BLOCKED_FOR_CONTROL_CENTER_REVIEW','reasons':reasons,'os_change_authorized':False,'qualification_or_production_pass':False},'limitations':['Sequential window/token/API observations can race; instability blocks acceptance.','Other-process Window Station is not directly queried by GetProcessWindowStation; observer station and owner thread desktop are recorded separately.','Native image path family is checked, not Authenticode signature or binary integrity qualification.','Synthetic results do not qualify native API/desktop compatibility.','No independent cryptographic trust signature is implied by a caller-provided governance file hash.'],'prohibitions':{'ui_inputs':0,'settings_writes':0,'elevation':0,'reboots':0,'original_collector_executions':0,'rate_tests':0,'retry_resume':False,'no_auto_next':True}}

def validate_live_permit(path,expected_sha,output):
    """Independent pin comes from a NEW future Control Center record, not this design approval."""
    require(type(expected_sha) is str and re.fullmatch('[0-9a-f]{64}',expected_sha),'EXTERNAL_PERMIT_SHA_REQUIRED')
    path=secure_path(path);raw=path.read_bytes();require(digest(raw)==expected_sha,'PERMIT_FILE_SHA_MISMATCH')
    permit=decode(raw);require(canonical(permit)==raw,'CANONICAL_PERMIT_BYTES_REQUIRED')
    exact(permit,{'decision','attempt_id','tool_sha256','schema_sha256','original_collector_sha256','host','operator_session_id','output_root','issued_utc','expires_utc','max_windows','read_only','no_ui_inputs','no_elevation','one_shot'})
    require(permit['decision']==FUTURE_DECISION,'NEW_INDEPENDENT_EXECUTION_AUTHORITY_REQUIRED')
    require(permit['tool_sha256']==digest(Path(__file__).read_bytes()) and permit['schema_sha256']==digest(SCHEMA.read_bytes()),'EXACT_TOOL_SCHEMA_PIN')
    require(permit['original_collector_sha256']==ORIGINAL_SHA,'ORIGINAL_REFERENCE_PIN')
    require(type(permit['attempt_id']) is str and re.fullmatch('ROGUI-[A-Za-z0-9-]{8,80}',permit['attempt_id']),'NEW_ATTEMPT_ID')
    require(all(permit[k] is True for k in ['read_only','no_ui_inputs','no_elevation','one_shot']),'PERMIT_SCOPE_FLAGS')
    require(type(permit['operator_session_id']) is int and permit['operator_session_id']>0,'OPERATOR_SESSION_NATIVE_INTEGER')
    require(type(permit['max_windows']) is int and 1<=permit['max_windows']<=4096,'WINDOW_BOUND')
    require(type(permit['host']) is str and permit['host'].casefold()==platform.node().casefold(),'PERMIT_HOST')
    for field in ['issued_utc','expires_utc']:require(type(permit[field]) is str and re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z',permit[field]),'STRICT_UTC_TIME')
    issued=datetime.datetime.fromisoformat(permit['issued_utc'].replace('Z','+00:00'));expires=datetime.datetime.fromisoformat(permit['expires_utc'].replace('Z','+00:00'))
    require(issued<=datetime.datetime.now(datetime.timezone.utc)<expires,'PERMIT_TIME_WINDOW')
    require(not permit['attempt_id'].startswith('ROGUI-SYNTHETIC-'),'SYNTHETIC_PERMIT_NOT_LIVE_AUTHORITY')
    output=secure_path(output);require(str(output)==permit['output_root'],'EXACT_NEW_OUTPUT_ROOT')
    require(output.parent==LIVE_PARENT and output.name==permit['attempt_id'] and output.parent.is_dir() and not output.exists(),'ISOLATED_PREPROVISIONED_PARENT_NEW_OUTPUT_REQUIRED')
    require(os.name=='nt','LIVE_WINDOWS_ONLY')
    return permit

class NativeBackend:
    """Constructed only by future permitted live mode. All input/control APIs absent."""
    def __init__(self,max_windows):
        require(os.name=='nt','NATIVE_WINDOWS_ONLY')
        import ctypes
        from ctypes import wintypes as w
        self.c,self.w=ctypes,w;self.max_windows=max_windows;self.calls=[]
        self.k=ctypes.WinDLL('kernel32',use_last_error=True);self.u=ctypes.WinDLL('user32',use_last_error=True);self.a=ctypes.WinDLL('advapi32',use_last_error=True)
        self.callback_type=ctypes.WINFUNCTYPE(w.BOOL,w.HWND,w.LPARAM,use_last_error=True)
        def bind(dll,name,args,result):
            f=getattr(dll,name);f.argtypes=args;f.restype=result;return f
        bind(self.k,'GetCurrentThreadId',[],w.DWORD)
        bind(self.k,'OpenProcess',[w.DWORD,w.BOOL,w.DWORD],w.HANDLE)
        bind(self.k,'CloseHandle',[w.HANDLE],w.BOOL)
        bind(self.k,'ProcessIdToSessionId',[w.DWORD,ctypes.POINTER(w.DWORD)],w.BOOL)
        bind(self.k,'QueryFullProcessImageNameW',[w.HANDLE,w.DWORD,w.LPWSTR,ctypes.POINTER(w.DWORD)],w.BOOL)
        bind(self.k,'GetProcessTimes',[w.HANDLE,*([ctypes.POINTER(w.FILETIME)]*4)],w.BOOL)
        bind(self.k,'LocalFree',[ctypes.c_void_p],ctypes.c_void_p)
        bind(self.a,'OpenProcessToken',[w.HANDLE,w.DWORD,ctypes.POINTER(w.HANDLE)],w.BOOL)
        bind(self.a,'GetTokenInformation',[w.HANDLE,ctypes.c_int,ctypes.c_void_p,w.DWORD,ctypes.POINTER(w.DWORD)],w.BOOL)
        bind(self.a,'ConvertSidToStringSidW',[ctypes.c_void_p,ctypes.POINTER(ctypes.c_void_p)],w.BOOL)
        bind(self.u,'EnumWindows',[self.callback_type,w.LPARAM],w.BOOL)
        bind(self.u,'IsWindow',[w.HWND],w.BOOL);bind(self.u,'IsWindowVisible',[w.HWND],w.BOOL)
        bind(self.u,'GetWindowTextLengthW',[w.HWND],ctypes.c_int)
        bind(self.u,'GetWindowTextW',[w.HWND,w.LPWSTR,ctypes.c_int],ctypes.c_int)
        bind(self.u,'GetClassNameW',[w.HWND,w.LPWSTR,ctypes.c_int],ctypes.c_int)
        bind(self.u,'GetWindowThreadProcessId',[w.HWND,ctypes.POINTER(w.DWORD)],w.DWORD)
        bind(self.u,'GetThreadDesktop',[w.DWORD],w.HANDLE)
        bind(self.u,'GetProcessWindowStation',[],w.HANDLE)
        bind(self.u,'GetUserObjectInformationW',[w.HANDLE,ctypes.c_int,ctypes.c_void_p,w.DWORD,ctypes.POINTER(w.DWORD)],w.BOOL)
        class SIDATTR(ctypes.Structure):_fields_=[('Sid',ctypes.c_void_p),('Attributes',w.DWORD)]
        class GROUPS(ctypes.Structure):_fields_=[('GroupCount',w.DWORD),('Groups',SIDATTR*1)]
        self.SIDATTR,self.GROUPS=SIDATTR,GROUPS
    def call(self,api,fn,args=(),policy='nonzero'):
        require(api in ALLOWED_APIS,'UNAPPROVED_NATIVE_API')
        self.c.set_last_error(0)
        try:value=fn(*args)
        except BaseException:
            self.calls.append({'api':api,'observed_utc':utc(),'result':None,'last_error':self.c.get_last_error(),'status':'ERROR'})
            raise
        error=self.c.get_last_error()
        result=int(value) if value is not None else None
        status='OK'
        if policy=='nonzero' and not value:status='ERROR'
        elif policy=='zero_error' and not value and error:status='ERROR'
        elif policy=='zero_error' and not value:status='EMPTY'
        elif policy=='buffer_probe':status='EXPECTED_BUFFER_PROBE' if not value and error==122 else 'ERROR'
        elif policy=='local_free':status='OK' if value is None else 'ERROR'
        record={'api':api,'observed_utc':utc(),'result':result,'last_error':error,'status':status};self.calls.append(record)
        return value,status
    def required(self,api,fn,args=(),policy='nonzero'):
        value,status=self.call(api,fn,args,policy)
        require(status in {'OK','EMPTY','EXPECTED_BUFFER_PROBE'},'NATIVE_API_ERROR:'+api+':'+str(self.calls[-1]['last_error']))
        return value
    def object_name(self,handle):
        c,w=self.c,self.w;needed=w.DWORD()
        self.required('GetUserObjectInformationW',self.u.GetUserObjectInformationW,(handle,2,None,0,c.byref(needed)),'buffer_probe')
        require(2<=needed.value<=65536 and needed.value%2==0,'OBJECT_NAME_BUFFER_BOUND')
        buf=c.create_unicode_buffer(needed.value//2)
        self.required('GetUserObjectInformationW',self.u.GetUserObjectInformationW,(handle,2,buf,c.sizeof(buf),c.byref(needed)))
        require(bool(buf.value),'EMPTY_DESKTOP_OR_STATION_NAME');return buf.value
    def session(self,pid):
        value=self.w.DWORD();self.required('ProcessIdToSessionId',self.k.ProcessIdToSessionId,(pid,self.c.byref(value)));return value.value
    def sid(self,ptr):
        raw=self.c.c_void_p();self.required('ConvertSidToStringSidW',self.a.ConvertSidToStringSidW,(ptr,self.c.byref(raw)))
        try:return self.c.wstring_at(raw.value)
        finally:self.required('LocalFree',self.k.LocalFree,(raw,),'local_free')
    def token(self,process):
        c,w=self.c,self.w;token=w.HANDLE()
        self.required('OpenProcessToken',self.a.OpenProcessToken,(process,8,c.byref(token)))
        try:
            def scalar(kind):
                value=w.DWORD();size=w.DWORD();self.required('GetTokenInformation',self.a.GetTokenInformation,(token,kind,c.byref(value),c.sizeof(value),c.byref(size)));return value.value
            def blob(kind):
                size=w.DWORD();self.required('GetTokenInformation',self.a.GetTokenInformation,(token,kind,None,0,c.byref(size)),'buffer_probe')
                require(0<size.value<=1024*1024,'TOKEN_BUFFER_BOUND')
                data=c.create_string_buffer(size.value);self.required('GetTokenInformation',self.a.GetTokenInformation,(token,kind,data,size.value,c.byref(size)));return data
            data=blob(2);groups=c.cast(data,c.POINTER(self.GROUPS)).contents;selected=[]
            require(groups.GroupCount<=4096,'TOKEN_GROUP_BOUND')
            require(self.GROUPS.Groups.offset+groups.GroupCount*c.sizeof(self.SIDATTR)<=len(data),'TOKEN_GROUP_BUFFER_LAYOUT')
            for i in range(groups.GroupCount):
                group=self.SIDATTR.from_address(c.addressof(data)+self.GROUPS.Groups.offset+i*c.sizeof(self.SIDATTR))
                if self.sid(group.Sid)=='S-1-5-32-544':selected.append({'sid':'S-1-5-32-544','attributes':group.Attributes,'enabled':bool(group.Attributes&4),'deny_only':bool(group.Attributes&16)})
            integrity=blob(25);label=c.cast(integrity,c.POINTER(self.SIDATTR)).contents
            return {'status':'OBSERVED','is_elevated':bool(scalar(20)),'elevation_type':scalar(18),'integrity_sid':self.sid(label.Sid),'administrators':selected}
        finally:self.required('CloseHandle',self.k.CloseHandle,(token,))
    def process(self,pid,query_token):
        c,w=self.c,self.w;handle=self.required('OpenProcess',self.k.OpenProcess,(0x1000,False,pid))
        try:
            size=w.DWORD(32768);buf=c.create_unicode_buffer(size.value)
            self.required('QueryFullProcessImageNameW',self.k.QueryFullProcessImageNameW,(handle,0,buf,c.byref(size)))
            times=[w.FILETIME() for _ in range(4)]
            self.required('GetProcessTimes',self.k.GetProcessTimes,(handle,*[c.byref(v) for v in times]))
            created=(times[0].dwHighDateTime<<32)|times[0].dwLowDateTime
            native=native_image(buf.value)
            token=self.token(handle) if query_token or native else {'status':'NOT_IN_SCOPE_UNRELATED_WINDOW'}
            return {'status':'OBSERVED','image':buf.value,'creation_filetime_100ns':created,'token':token}
        finally:self.required('CloseHandle',self.k.CloseHandle,(handle,))
    def window(self,hwnd):
        c,w=self.c,self.w;start=len(self.calls)
        row={'hwnd':int(hwnd),'pid':0,'tid':0,'visible':False,'class_name':'','title':'','title_length':0,'title_copied':0,'title_complete':False,'title_observation':{'protocol':TITLE_PROTOCOL,'phase':'NOT_STARTED','length_samples':[],'reads':[],'identities':[]},'session_id':0,'desktop':'','process':{'status':'UNOBSERVABLE'},'stable':False,'api_calls':[],'errors':[]}
        obs=row['title_observation']
        def identity(stage):
            alive_index=len(self.calls)-start
            self.required('IsWindow',self.u.IsWindow,(hwnd,))
            pid=w.DWORD();owner_index=len(self.calls)-start
            tid=self.required('GetWindowThreadProcessId',self.u.GetWindowThreadProcessId,(hwnd,c.byref(pid)))
            observed={'stage':stage,'hwnd':int(hwnd),'pid':pid.value,'tid':int(tid),'is_window_call_index':alive_index,'owner_call_index':owner_index}
            obs['identities'].append(observed)
            if stage=='BEFORE':row.update(pid=pid.value,tid=int(tid))
            else:require(pid.value==row['pid'] and int(tid)==row['tid'],'WINDOW_OWNER_CHANGED_DURING_SAMPLE')
            return pid.value,int(tid)
        def length_sample(stage):
            index=len(self.calls)-start
            result,status=self.call('GetWindowTextLengthW',self.u.GetWindowTextLengthW,(hwnd,),'zero_error')
            obs['length_samples'].append({'stage':stage,'hwnd':int(hwnd),'api_call_index':index})
            require(status in {'OK','EMPTY'} and self.calls[-1]['last_error']==0,'TITLE_LENGTH_API_UNRELIABLE')
            require(type(result) is int and 0<=result<TITLE_CAPACITY-1,'TITLE_LENGTH_BOUND')
            return result
        def title_sample(stage):
            require(c.sizeof(c.c_wchar)==2,'WINDOWS_UTF16_WCHAR_REQUIRED')
            buffer=c.create_unicode_buffer(TITLE_CAPACITY);index=len(self.calls)-start
            result,status=self.call('GetWindowTextW',self.u.GetWindowTextW,(hwnd,buffer,TITLE_CAPACITY),'zero_error')
            raw=c.string_at(c.addressof(buffer),c.sizeof(buffer))
            bounded=type(result) is int and 0<=result<TITLE_CAPACITY
            prefix=raw[:result*2] if bounded else b''
            obs['reads'].append({'stage':stage,'hwnd':int(hwnd),'api_call_index':index,'capacity_utf16_units':TITLE_CAPACITY,'utf16_hex':prefix.hex(),
                'terminator_utf16_hex':raw[result*2:result*2+2].hex() if bounded else '',
                'terminator_at_return':bounded and raw[result*2:result*2+2]==b'\0\0',
                'no_embedded_nul':not any(prefix[n:n+2]==b'\0\0' for n in range(0,len(prefix),2))})
            require(status in {'OK','EMPTY'} and self.calls[-1]['last_error']==0,'TITLE_READ_API_UNRELIABLE')
            require(bounded and result<TITLE_CAPACITY-1,'TITLE_POTENTIALLY_TRUNCATED')
            require(obs['reads'][-1]['terminator_at_return'] and obs['reads'][-1]['no_embedded_nul'],'TITLE_BUFFER_UNRELIABLE')
            return prefix.decode('utf-16-le',errors='strict'),result
        try:
            obs['phase']='PARTIAL';pid,tid=identity('BEFORE')
            row['visible']=bool(self.required('IsWindowVisible',self.u.IsWindowVisible,(hwnd,),'zero_error'))
            classbuf=c.create_unicode_buffer(256);copied=self.required('GetClassNameW',self.u.GetClassNameW,(hwnd,classbuf,256));require(copied<255,'CLASS_POTENTIALLY_TRUNCATED')
            row['class_name']=classbuf.value
            row['title_length']=length_sample('BEFORE')
            text,copied=title_sample('PRIMARY');row.update(title=text,title_copied=copied)
            require(row['title_length']>=copied and (row['title_length']==0)==(copied==0),'TITLE_PRIMARY_LENGTH_INCONSISTENT')
            after_length=length_sample('AFTER')
            require(after_length==row['title_length'],'TITLE_LENGTH_ESTIMATE_CHANGED')
            title_sample('CONFIRMATION')
            identity('AFTER_TITLE')
            row['session_id']=self.session(pid)
            desk=self.required('GetThreadDesktop',self.u.GetThreadDesktop,(tid,));row['desktop']=self.object_name(desk)
            row['process']=self.process(pid,row['title'].strip().lower() in TITLES)
            identity('AFTER_PROCESS');row['stable']=True;obs['phase']='OBSERVED'
        except BaseException as exc:row['errors'].append({'type':type(exc).__name__,'reason':str(exc)})
        row['api_calls']=self.calls[start:]
        row['title_complete']=title_reliability(row)['reliable']
        return row
    def collect(self,permit):
        start=len(self.calls)
        pid=os.getpid();parent=os.getppid();tid=int(self.required('GetCurrentThreadId',self.k.GetCurrentThreadId))
        desk=self.required('GetThreadDesktop',self.u.GetThreadDesktop,(tid,));station=self.required('GetProcessWindowStation',self.u.GetProcessWindowStation)
        ctx={'host':platform.node(),'observer_pid':pid,'parent_pid':parent,'session_id':self.session(pid),'parent_session_id':self.session(parent),'desktop':self.object_name(desk),'window_station':self.object_name(station),'observer_token':self.process(pid,True)['token'],'parent_token':self.process(parent,True)['token'],'api_calls':self.calls[start:]}
        require(ctx['session_id']==permit['operator_session_id'] and admin(ctx['observer_token']) and admin(ctx['parent_token']),'HUMAN_ADMIN_OR_PERMITTED_SESSION_MISMATCH')
        windows=[];callback_errors=[];visited=0;completed=0;truncated=False
        @self.callback_type
        def visit(hwnd,unused):
            nonlocal visited,completed,truncated
            visited+=1
            try:
                if visited>self.max_windows:truncated=True;return False
                windows.append(self.window(hwnd));completed+=1;return True
            except BaseException as exc:
                callback_errors.append({'type':type(exc).__name__,'reason':str(exc),'visited':visited});return False
        start=len(self.calls);result,status=callback_error_guard(lambda:self.call('EnumWindows',self.u.EnumWindows,(visit,0)),callback_errors)
        enum_calls=[v for v in self.calls[start:] if v['api']=='EnumWindows']
        enum={'return_value':bool(result),'last_error':enum_calls[-1]['last_error'],'visited':visited,'completed':completed,'callback_errors':callback_errors,'truncated':truncated,'api_calls':enum_calls}
        return {'context':ctx,'enumeration':enum,'windows':windows}

def main(argv=None,native_factory=None):
    parser=argparse.ArgumentParser(description='Read-only GUI diagnostic; live needs a NEW independent permit, not design approval')
    parser.add_argument('--mode',choices=['synthetic','live'],required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--fixture',type=Path)
    parser.add_argument('--permit',type=Path)
    parser.add_argument('--expected-permit-sha256')
    parser.add_argument('--human-execution',action='store_true')
    args=parser.parse_args(argv)
    root=None;backend=None
    try:
        if args.mode=='synthetic':
            require(args.fixture is not None and not args.permit and not args.expected_permit_sha256 and not args.human_execution,'SYNTHETIC_ARGUMENT_BOUNDARY')
            output=secure_path(args.output)
            require(output.parent==HERE/'synthetic_runs' and output.parent.is_dir() and not output.exists(),'SYNTHETIC_ISOLATED_NEW_OUTPUT')
            fixture_path=secure_path(args.fixture);require(fixture_path.parent==HERE/'fixtures','ISOLATED_SYNTHETIC_FIXTURE_ONLY')
            fixture=read_json(fixture_path)
            output.mkdir();root=output
            write_new(root,'intent.json',{'mode':'SYNTHETIC','utc':utc(),'native_api_execution':False})
            report=evaluate(fixture,'SYNTHETIC')
            write_new(root,'evidence.json',report)
        else:
            require(args.human_execution and args.permit is not None and not args.fixture,'HUMAN_NEW_LIVE_PERMIT_REQUIRED')
            permit=validate_live_permit(args.permit,args.expected_permit_sha256,args.output)
            output=secure_path(args.output);output.mkdir();root=output
            write_new(root,'intent.json',{'mode':'LIVE_READ_ONLY','attempt_id':permit['attempt_id'],'utc':utc(),'permit_sha256':args.expected_permit_sha256,'tool_sha256':digest(Path(__file__).read_bytes()),'no_retry':True})
            backend=(native_factory or NativeBackend)(permit['max_windows'])
            snapshot=backend.collect(permit)
            report=evaluate(snapshot,'LIVE')
            report['authorization_binding']={'permit_sha256':args.expected_permit_sha256,'attempt_id':permit['attempt_id'],'decision':permit['decision'],'schema_sha256':permit['schema_sha256']}
            if digest(Path(__file__).read_bytes())!=permit['tool_sha256'] or digest(SCHEMA.read_bytes())!=permit['schema_sha256'] or digest(args.permit.read_bytes())!=args.expected_permit_sha256:
                report['gate']['status']='BLOCKED_FOR_CONTROL_CENTER_REVIEW';report['gate']['reasons'].append('TOOL_SCHEMA_OR_PERMIT_CHANGED_DURING_RUN')
            write_new(root,'evidence.json',report)
        if report['gate']['status']!='PASS_DIAGNOSTIC_EVIDENCE_ONLY':
            write_new(root,'HALTED.json',{'status':'BLOCKED_FOR_CONTROL_CENTER_REVIEW','utc':utc(),'reasons':report['gate']['reasons'],'no_retry':True})
            return 2
        write_new(root,'complete.json',{'status':'PASS_SYNTHETIC_ONLY' if args.mode=='synthetic' else 'PASS_READ_ONLY_DIAGNOSTIC_ONLY','utc':utc(),'evidence_sha256':digest((root/'evidence.json').read_bytes()),'os_change_authorized':False})
        return 0
    except BaseException as exc:
        if root is not None and backend is not None and not (root/'partial_api_calls.json').exists():
            write_new(root,'partial_api_calls.json',{'status':'PARTIAL_NATIVE_OBSERVATION_NOT_PASS','api_calls':backend.calls,'context_or_enumeration_completed':False})
        if root is not None and not (root/'HALTED.json').exists():write_new(root,'HALTED.json',{'status':'BLOCKED_FOR_CONTROL_CENTER_REVIEW','utc':utc(),'error_type':type(exc).__name__,'reason':str(exc),'traceback':traceback.format_exc(),'no_retry':True})
        print('BLOCKED_FOR_CONTROL_CENTER_REVIEW: '+str(exc),file=sys.stderr);return 2

if __name__=='__main__':raise SystemExit(main())
