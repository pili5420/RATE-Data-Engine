"""Pure synthetic factories, no native provider or legacy import."""
import hashlib,importlib.util
from pathlib import Path
P=Path(__file__).resolve().parent
STAMP="2026-10-17T00:00:00+00:00"
spec=importlib.util.spec_from_file_location("round2_model_fixture",P/"identity_binding.py");m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def call(api,status='OK',error=0,result=1):return {'api':api,'observed_utc':STAMP,'result':result,'last_error':error,'status':status}

def token():return {'status':'OBSERVED','is_elevated':True,'elevation_type':2,'integrity_sid':'S-1-16-12288','administrators':[{'sid':'S-1-5-32-544','attributes':15,'enabled':True,'deny_only':False}]}

def window(hwnd=1,title='虛擬記憶體'):
    units=len(title.encode('utf-16-le'))//2;pid=100+hwnd;tid=200+hwnd
    empty='EMPTY' if units==0 else 'OK'
    calls=[call('IsWindow'),call('GetWindowThreadProcessId',result=tid),call('IsWindowVisible'),call('GetClassNameW'),
        call('GetWindowTextLengthW',empty,result=units),call('GetWindowTextW',empty,result=units),
        call('GetWindowTextLengthW',empty,result=units),call('GetWindowTextW',empty,result=units),
        call('IsWindow'),call('GetWindowThreadProcessId',result=tid),call('ProcessIdToSessionId'),call('GetThreadDesktop'),
        call('GetUserObjectInformationW'),call('GetTokenInformation'),call('IsWindow'),call('GetWindowThreadProcessId',result=tid)]
    observation={'protocol':'BOUNDED_TWO_READ_TITLE_V2','phase':'OBSERVED',
        'length_samples':[{'stage':'BEFORE','hwnd':hwnd,'api_call_index':4},{'stage':'AFTER','hwnd':hwnd,'api_call_index':6}],
        'reads':[{'stage':stage,'hwnd':hwnd,'api_call_index':index,'capacity_utf16_units':4097,'utf16_hex':title.encode('utf-16-le').hex(),'terminator_utf16_hex':'0000','terminator_at_return':True,'no_embedded_nul':True} for stage,index in [('PRIMARY',5),('CONFIRMATION',7)]],
        'identities':[{'stage':stage,'hwnd':hwnd,'pid':pid,'tid':tid,'is_window_call_index':alive,'owner_call_index':owner} for stage,alive,owner in [('BEFORE',0,1),('AFTER_TITLE',8,9),('AFTER_PROCESS',14,15)]]}
    return {'hwnd':hwnd,'pid':pid,'tid':tid,'visible':True,'class_name':'#32770','title':title,'title_length':units,'title_copied':units,'title_complete':True,'title_observation':observation,'session_id':1,'desktop':'Default','process':{'status':'OBSERVED','image':r'C:\Windows\System32\SystemPropertiesPerformance.exe','creation_filetime_100ns':134366334000000000,'token':token()},'stable':True,'api_calls':calls,'errors':[]}

def fixture(windows=None):
    wins=[window()] if windows is None else windows
    return {'context':{'host':'SYNTHETIC_HOST','observer_pid':10,'parent_pid':11,'session_id':1,'parent_session_id':1,'desktop':'Default','window_station':'WinSta0','observer_token':token(),'parent_token':token(),'api_calls':[call(n) for n in ['GetThreadDesktop','GetProcessWindowStation','GetUserObjectInformationW','GetTokenInformation']]},'enumeration':{'return_value':True,'last_error':0,'visited':len(wins),'completed':len(wins),'callback_errors':[],'truncated':False,'api_calls':[call('EnumWindows')]},'windows':wins}

def schema_check(value,schema,root=None):
    """Independent strict validator for ONLY the schema's declared keyword subset."""
    root=root or schema
    allowed={'$schema','$id','title','$defs','$ref','type','properties','required','additionalProperties','items','enum','const','minimum','maximum','pattern','oneOf'}
    assert set(schema)<=allowed,'UNSUPPORTED_SCHEMA_KEYWORD'
    if '$ref' in schema:return schema_check(value,root['$defs'][schema['$ref'].split('/')[-1]],root)
    if 'oneOf' in schema:
        count=0
        for candidate in schema['oneOf']:
            try:schema_check(value,candidate,root);count+=1
            except (AssertionError,KeyError,TypeError,ValueError):pass
        assert count==1,'ONEOF';return
    if 'const' in schema:assert type(value) is type(schema['const']) and value==schema['const'],'CONST_NATIVE_TYPE'
    if 'enum' in schema:assert value in schema['enum'],'ENUM'
    if 'type' in schema:
        types=schema['type'] if type(schema['type']) is list else [schema['type']]
        mapping={'object':dict,'array':list,'string':str,'integer':int,'boolean':bool,'null':type(None)}
        assert type(value) in {mapping[t] for t in types},'TYPE'
    if type(value) is dict:
        assert set(schema.get('required',[]))<=set(value),'REQUIRED'
        props=schema.get('properties',{})
        if schema.get('additionalProperties') is False:assert set(value)<=set(props),'ADDITIONAL'
        for k,v in value.items():
            if k in props:schema_check(v,props[k],root)
    if type(value) is list and 'items' in schema:
        for v in value:schema_check(v,schema['items'],root)
    if 'pattern' in schema:assert re.fullmatch(schema['pattern'],value),'PATTERN'
    if 'minimum' in schema:assert value>=schema['minimum'],'MINIMUM'
    if 'maximum' in schema:assert value<=schema['maximum'],'MAXIMUM'

def ident():
    w=window()
    return {'host':'SYNTHETIC-HOST-ONLY','session_id':1,'desktop':'Default','observer_station':'WinSta0','pid':101,'tid':201,'hwnd':1,'class_name':'#32770',
        'creation_filetime_100ns':w['process']['creation_filetime_100ns'],'executable_path':w['process']['image'],'executable_sha256':'a'*64,'volume_serial':'SYNTH-VOL','file_id':'SYNTH-FILE','window_epoch':7}

def grant(stage='IDENTITY_ONLY'):
    x=ident();p={k:x[k] for k in ['host','session_id','desktop','observer_station','executable_path','executable_sha256','volume_serial','file_id','class_name']}
    attempt='SYNTHETIC-'+stage.replace('_','-')+'-00000001'
    scope={'allowed_apis':sorted(m.IDENTITY_APIS if stage=='IDENTITY_ONLY' else m.DIAGNOSTIC_APIS),'read_fields':sorted(m.IDENTITY_FIELDS if stage=='IDENTITY_ONLY' else m.DIAGNOSTIC_FIELDS),
        'access_rights':{'process':4096,'token':8,'file':129},'enumeration_bounds':{'max_windows':128 if stage=='IDENTITY_ONLY' else 0,'max_candidates':1,'max_title_reads':0 if stage=='IDENTITY_ONLY' else 2},
        'timeouts':{'per_call_ms':1000,'total_ms':10000},'evidence_destination':str(m.OUTPUT_PARENT/attempt),'target_policy':p}
    return {'artifact_kind':m.PURPOSE,'stage':stage,'attempt_id':attempt,'issued_ns':100,'expires_ns':100000000000,'scope':scope,'scope_sha256':m.hash_value(scope),
        'tool_sha256':hashlib.sha256((P/'identity_binding.py').read_bytes()).hexdigest(),'schema_sha256':hashlib.sha256((P/'TARGET_IDENTITY_BINDING_SCHEMA_V1.json').read_bytes()).hexdigest(),
        'identity_binding':{'mode':'UNRESOLVED_IDENTITY_ONLY' if stage=='IDENTITY_ONLY' else 'EXACT_REVIEWED_TARGET','target_identity_sha256':None if stage=='IDENTITY_ONLY' else m.hash_value(x),'resolution_evidence_sha256':None if stage=='IDENTITY_ONLY' else 'a'*64,'review_ack_sha256':None if stage=='IDENTITY_ONLY' else 'b'*64}}

def life():return {'source':m.LIFECYCLE_SOURCE,'coverage':'COMPLETE_SYNTHETIC_TRACE','lost_events':0,'epoch_before':7,'epoch_after':7,'events':[{'sequence':1,'kind':'CREATE','hwnd':1,'epoch':7},{'sequence':2,'kind':'UNCHANGED','hwnd':1,'epoch':7}]}

def resolution(g=None):
    g=g or grant()
    return {'artifact_kind':m.PURPOSE,'scope_sha256':g['scope_sha256'],'enumeration_count':1,'enumeration_complete':True,'candidates':[{'before':ident(),'after':ident(),'lifecycle':life()}]}

def ready():
    g=grant();r=m.resolve_identity(g,resolution(g),m.AttemptJournal(),1000);d=grant('BOUND_DIAGNOSTIC')
    ack={'artifact_kind':m.PURPOSE,'decision':'SYNTHETIC_REVIEW_ACK_ONLY_NOT_CONTROL_CENTER_AUTHORITY','resolution_evidence_sha256':r['resolution_evidence_sha256'],'target_identity_sha256':r['target_identity_sha256'],
        'diagnostic_scope_sha256':d['scope_sha256'],'issued_ns':100,'expires_ns':100000000000}
    d['identity_binding'].update(target_identity_sha256=r['target_identity_sha256'],resolution_evidence_sha256=r['resolution_evidence_sha256'],review_ack_sha256=m.hash_value(ack))
    ctx=fixture()['context'];ctx['host']=ident()['host']
    e={'artifact_kind':m.PURPOSE,'scope_sha256':d['scope_sha256'],'before':ident(),'after':ident(),'lifecycle':life(),'context':ctx,'window':window()}
    return d,r,ack,e

def desktop():return {k:ident()[k] for k in m.DESKTOP_KEYS}

def seed():return {k:ident()[k] for k in m.SEED_KEYS}
