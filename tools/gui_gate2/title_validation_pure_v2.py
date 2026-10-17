"""Pure accepted-V2 title/token/evidence validation. No collector or execution authority.
Sequential observations are not atomic; original HALT root cause remains UNKNOWN.
"""
import datetime
import hashlib
from pathlib import PureWindowsPath
import re

TITLE_PROTOCOL='BOUNDED_TWO_READ_TITLE_V2'

TITLE_CAPACITY=4097

TITLES={'虛擬記憶體','虚拟内存','virtual memory'}

NATIVE_IMAGES={'systempropertiesadvanced.exe','systempropertiesperformance.exe','systempropertiescomputername.exe','rundll32.exe','control.exe'}

ALLOWED_APIS={'EnumWindows','IsWindow','IsWindowVisible','GetWindowTextLengthW','GetWindowTextW','GetClassNameW','GetWindowThreadProcessId','GetCurrentThreadId','GetThreadDesktop','GetProcessWindowStation','GetUserObjectInformationW','GetCurrentProcessId','ProcessIdToSessionId','OpenProcess','OpenProcessToken','GetTokenInformation','ConvertSidToStringSidW','QueryFullProcessImageNameW','GetProcessTimes','CloseHandle','LocalFree'}

def digest(data):return hashlib.sha256(data).hexdigest()

def require(ok,reason):
    if not ok:raise ValueError(reason)

def integer(value):return type(value) is int and 0<=value<2**64

def exact(obj,keys):require(type(obj) is dict and set(obj)==set(keys),'EXACT_SCHEMA_KEYS')

def native_image(image):
    path=PureWindowsPath(image)
    return '..' not in path.parts and str(path.parent).casefold() in {r'c:\windows\system32',r'c:\windows\syswow64'} and path.name.lower() in NATIVE_IMAGES

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
