"""Gate2 offline identity/read-boundary reference validator. No native adapter.

Only explicit synthetic models are accepted by these engineering entry points.
There is no live Permit loader, native enumeration, process access or diagnostic
activation. The contract describes future independent identity-only approval,
review ACK, and a separate exact-target diagnostic grant. Gate2 stays BLOCKED.
"""
import hashlib
import importlib.util
import json
from pathlib import Path,PureWindowsPath
import re

VERSION='RATE_GUI_GATE2_OFFLINE_V1'
PURPOSE='OFFLINE_SYNTHETIC_MODEL_NO_EXECUTION_AUTHORITY'
BASELINE_SHA='3488a20b13021f7c9072f475c8bcfe7c5be703ff82eea847c0216d00fb8fc228'
BASELINE_SCHEMA_SHA='4c55b48bc6eb5a9a9d4065a578be355764e5f2541d97089fdc0e35869bd29a02'
HERE=Path(__file__).resolve().parent
OUTPUT_PARENT=PureWindowsPath(r'D:\Codex\RATE-GUI-GATE2-RUNS')
IDENTITY_KEYS={'host','session_id','desktop','observer_station','pid','creation_filetime_100ns','executable_path','executable_sha256','volume_serial','file_id','hwnd','tid','class_name','window_epoch'}
IDENTITY_APIS={'EnumWindows','IsWindow','GetClassNameW','GetWindowThreadProcessId','ProcessIdToSessionId','GetThreadDesktop','GetProcessWindowStation','GetUserObjectInformationW','OpenProcess','QueryFullProcessImageNameW','GetProcessTimes','OpenProcessToken','GetTokenInformation','ConvertSidToStringSidW','CloseHandle','LocalFree','CreateFileW','GetFinalPathNameByHandleW','GetFileInformationByHandleEx','ReadFile','GetComputerNameW','GetTickCount64'}
DIAGNOSTIC_APIS=IDENTITY_APIS-{'EnumWindows'}|{'IsWindowVisible','GetWindowTextLengthW','GetWindowTextW'}
IDENTITY_FIELDS={'host','session_id','desktop','observer_station','pid','creation_filetime_100ns','executable_path','executable_sha256','volume_serial','file_id','hwnd','tid','class_name','window_epoch','admin_token','enumeration_count','lifecycle_trace'}
DIAGNOSTIC_FIELDS=IDENTITY_FIELDS-{'enumeration_count'}|{'visibility','title','title_utf16','title_length','title_api_errors','title_consistency'}
LIFECYCLE_SOURCE='SYNTHETIC_LOSSLESS_LIFECYCLE_LEDGER'
SEED_KEYS={'host','session_id','desktop','observer_station','hwnd','pid','tid','class_name'}
DESKTOP_KEYS={'host','session_id','desktop','observer_station'}
FILE_APIS={'CreateFileW','GetFinalPathNameByHandleW','GetFileInformationByHandleEx','ReadFile'}
API_FIELDS={
    'EnumWindows':{'hwnd'},'IsWindow':{'hwnd'},'IsWindowVisible':{'visibility'},'GetClassNameW':{'hwnd','class_name'},
    'GetWindowThreadProcessId':{'hwnd','pid','tid'},'ProcessIdToSessionId':{'pid','session_id'},
    'GetThreadDesktop':{'tid','desktop'},'GetProcessWindowStation':{'observer_station'},
    'GetUserObjectInformationW':{'desktop','observer_station'},'OpenProcess':{'pid'},
    'QueryFullProcessImageNameW':{'pid','executable_path'},'GetProcessTimes':{'pid','creation_filetime_100ns'},
    'OpenProcessToken':{'pid','admin_token'},'GetTokenInformation':{'admin_token'},'ConvertSidToStringSidW':{'admin_token'},
    'CloseHandle':set(),'LocalFree':set(),'CreateFileW':{'executable_path'},
    'GetFinalPathNameByHandleW':{'executable_path'},'GetFileInformationByHandleEx':{'volume_serial','file_id'},
    'ReadFile':{'executable_sha256'},'GetComputerNameW':{'host'},'GetTickCount64':set(),
    'GetWindowTextLengthW':{'title_length','title_api_errors'},'GetWindowTextW':{'title','title_utf16','title_api_errors','title_consistency'}}

class Denied(ValueError):
    def __init__(self,reason,state='UNKNOWN'):
        self.reason,self.state=reason,state
        super().__init__(reason)
def need(ok,reason,state='UNKNOWN'):
    if not ok:raise Denied(reason,state)
def exact(value,keys):need(type(value) is dict and set(value)==set(keys),'EXACT_KEYS')
def uint(value,limit=2**64):return type(value) is int and 0<value<limit
def canon(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode('utf-8')
def hash_value(value):return hashlib.sha256(canon(value)).hexdigest()
def hash64(value):return type(value) is str and re.fullmatch('[0-9a-f]{64}',value) is not None
def decode(raw):
    def pairs(items):
        d={}
        for k,v in items:need(k not in d,'DUPLICATE_JSON_KEY');d[k]=v
        return d
    need(type(raw) is bytes and len(raw)<=4*1024**2,'JSON_BYTES_BOUND')
    return json.loads(raw.decode('utf-8'),object_pairs_hook=pairs,parse_constant=lambda x:(_ for _ in ()).throw(Denied('NONFINITE_JSON')))
def path(value):
    need(type(value) is str and value and '/' not in value and not value.startswith('\\\\'),'CANONICAL_LOCAL_WINDOWS_PATH')
    p=PureWindowsPath(value)
    need(p.is_absolute() and re.fullmatch('[A-Za-z]:',p.drive) is not None and '..' not in p.parts and str(p)==value,'CANONICAL_LOCAL_WINDOWS_PATH')
    need(':' not in value[2:] and not any(part.endswith((' ','.')) for part in p.parts[1:]),'PATH_ALIAS_OR_ADS')
    return p
def identity(value):
    exact(value,IDENTITY_KEYS)
    for k in ['pid','tid','session_id']:need(uint(value[k],2**32),'IDENTITY_NATIVE_INTEGER')
    for k in ['creation_filetime_100ns','hwnd','window_epoch']:need(uint(value[k]),'IDENTITY_NATIVE_INTEGER')
    for k in ['host','desktop','observer_station','class_name','volume_serial','file_id']:
        need(type(value[k]) is str and 0<len(value[k])<=256,'IDENTITY_STRING')
    path(value['executable_path']);need(hash64(value['executable_sha256']),'EXECUTABLE_HASH')
    return value
def policy(value):
    exact(value,{'host','session_id','desktop','observer_station','executable_path','executable_sha256','volume_serial','file_id','class_name'})
    need(type(value['host']) is str and value['host']=='SYNTHETIC-HOST-ONLY','SYNTHETIC_HOST_ONLY_NOT_LIVE_AUTHORITY')
    need(uint(value['session_id'],2**32),'SESSION_NATIVE_INTEGER')
    for k in ['desktop','observer_station','volume_serial','file_id','class_name']:need(type(value[k]) is str and value[k],'POLICY_IDENTITY_STRING')
    path(value['executable_path']);need(hash64(value['executable_sha256']),'EXECUTABLE_HASH')
def scope(value,stage):
    exact(value,{'allowed_apis','read_fields','access_rights','enumeration_bounds','timeouts','evidence_destination','target_policy'})
    policy(value['target_policy'])
    need(type(value['allowed_apis']) is list and all(type(v) is str for v in value['allowed_apis']),'API_LIST')
    expected=IDENTITY_APIS if stage=='IDENTITY_ONLY' else DIAGNOSTIC_APIS
    need(set(value['allowed_apis'])==expected and len(value['allowed_apis'])==len(expected),'EXACT_ALLOWED_APIS')
    fields=IDENTITY_FIELDS if stage=='IDENTITY_ONLY' else DIAGNOSTIC_FIELDS
    need(type(value['read_fields']) is list and all(type(v) is str for v in value['read_fields']) and set(value['read_fields'])==fields and len(value['read_fields'])==len(fields),'EXACT_READ_FIELDS')
    exact(value['access_rights'],{'process','token','file'})
    need(all(type(v) is int for v in value['access_rights'].values()) and value['access_rights']=={'process':0x1000,'token':0x8,'file':0x81},'EXACT_READ_ACCESS_RIGHTS')
    b=value['enumeration_bounds'];exact(b,{'max_windows','max_candidates','max_title_reads'})
    need(all(type(v) is int for v in b.values()),'NATIVE_BOUND_TYPES')
    need((1<=b['max_windows']<=4096 if stage=='IDENTITY_ONLY' else b['max_windows']==0) and b['max_candidates']==1 and b['max_title_reads']==(0 if stage=='IDENTITY_ONLY' else 2),'STAGE_ENUMERATION_AND_TITLE_BOUNDS')
    t=value['timeouts'];exact(t,{'per_call_ms','total_ms'})
    need(type(t['per_call_ms']) is int and 1<=t['per_call_ms']<=5000 and type(t['total_ms']) is int and t['per_call_ms']<=t['total_ms']<=60000,'BOUNDED_TIMEOUTS')
    out=path(value['evidence_destination']);need(out.parent==OUTPUT_PARENT and out.name.startswith('SYNTHETIC-'),'ISOLATED_SYNTHETIC_EVIDENCE_DESTINATION')
def model(value,stage,now_ns):
    need(stage in {'IDENTITY_ONLY','BOUND_DIAGNOSTIC'},'SEPARATE_STAGE_AUTHORITY_REQUIRED')
    exact(value,{'artifact_kind','stage','attempt_id','issued_ns','expires_ns','scope','scope_sha256','tool_sha256','schema_sha256','identity_binding'})
    need(value['artifact_kind']==PURPOSE,'LIVE_PERMIT_LOADING_NOT_IMPLEMENTED')
    need(value['stage']==stage,'SEPARATE_STAGE_AUTHORITY_REQUIRED')
    need(type(value['attempt_id']) is str and re.fullmatch('SYNTHETIC-[A-Za-z0-9-]{8,80}',value['attempt_id']) is not None,'SYNTHETIC_ATTEMPT_ONLY')
    need(all(uint(v) for v in [value['issued_ns'],value['expires_ns'],now_ns]) and value['issued_ns']<=now_ns<value['expires_ns'],'MODEL_TIME_WINDOW')
    scope(value['scope'],stage)
    need(value['scope_sha256']==hash_value(value['scope']),'EXACT_SCOPE_HASH')
    need(value['tool_sha256']==hashlib.sha256(Path(__file__).read_bytes()).hexdigest() and value['schema_sha256']==hashlib.sha256((HERE/'TARGET_IDENTITY_BINDING_SCHEMA_V1.json').read_bytes()).hexdigest(),'EXACT_TOOL_SCHEMA_BINDING')
    need(PureWindowsPath(value['scope']['evidence_destination']).name==value['attempt_id'],'ATTEMPT_DESTINATION_BINDING')
    binding=value['identity_binding'];exact(binding,{'mode','target_identity_sha256','resolution_evidence_sha256','review_ack_sha256'})
    if stage=='IDENTITY_ONLY':need(binding['mode']=='UNRESOLVED_IDENTITY_ONLY' and all(binding[k] is None for k in ['target_identity_sha256','resolution_evidence_sha256','review_ack_sha256']),'IDENTITY_ONLY_CANNOT_PREAUTHORIZE_DIAGNOSIS')
    else:need(binding['mode']=='EXACT_REVIEWED_TARGET' and all(hash64(binding[k]) for k in ['target_identity_sha256','resolution_evidence_sha256','review_ack_sha256']),'EXACT_REVIEWED_TARGET_BINDING_REQUIRED')
def match_policy(value,expected):
    identity(value)
    for k,v in expected.items():need(value[k]==v,'TARGET_POLICY_MISMATCH:'+k,'MISMATCH')
def lifecycle(proof,before,after):
    exact(proof,{'source','coverage','lost_events','epoch_before','epoch_after','events'})
    need(proof['source']==LIFECYCLE_SOURCE and proof['coverage']=='COMPLETE_SYNTHETIC_TRACE','WINDOW_GENERATION_ASSURANCE_UNKNOWN')
    need(type(proof['lost_events']) is int and proof['lost_events']==0,'LIFECYCLE_LOSS_UNKNOWN')
    need(uint(proof['epoch_before']) and uint(proof['epoch_after']) and proof['epoch_before']==proof['epoch_after']==before['window_epoch']==after['window_epoch'],'WINDOW_REPLACEMENT_OR_REUSE','MISMATCH')
    need(type(proof['events']) is list and proof['events'],'MISSING_LIFECYCLE_EVIDENCE')
    previous=0
    for event in proof['events']:
        exact(event,{'sequence','kind','hwnd','epoch'});need(type(event['sequence']) is int and event['sequence']==previous+1,'LIFECYCLE_TRACE_GAP');previous=event['sequence']
        need(event['kind'] in {'CREATE','UNCHANGED','DESTROY'},'LIFECYCLE_EVENT_KIND')
        need(type(event['hwnd']) is int and event['hwnd']==before['hwnd'] and type(event['epoch']) is int and event['epoch']==before['window_epoch'],'WINDOW_REPLACEMENT_OR_REUSE','MISMATCH')
        need(event['kind']!='DESTROY','WINDOW_DESTROYED','MISMATCH')
    need(proof['events'][0]['kind']=='CREATE','UNANCHORED_WINDOW_GENERATION')

class AttemptJournal:
    """Synthetic state only. Future native adapter needs durable exclusive intent."""
    def __init__(self):self.used=set()
    def consume_model(self,attempt):
        need(attempt not in self.used,'ATTEMPT_ALREADY_USED_NO_RETRY');self.used.add(attempt)

class ReadGuard:
    """Pre-call synthetic capability guard, not a native transport or Permit loader."""
    def __init__(self,grant,journal,now_ns,bound=None,review_evidence=None):
        self.grant,self.bound,self.start,self.calls=grant,bound,now_ns,[]
        journal.consume_model(grant['attempt_id'])
        model(grant,grant['stage'],now_ns)
        need(grant['stage']=='IDENTITY_ONLY' or bound is not None,'BOUND_TARGET_REQUIRED')
        if bound is not None:
            identity(bound);match_policy(bound,grant['scope']['target_policy'])
            need(grant['identity_binding']['target_identity_sha256']==hash_value(bound),'GRANT_BOUND_TARGET_IDENTITY_MISMATCH','MISMATCH')
            need(type(review_evidence) is tuple and len(review_evidence)==2,'INDEPENDENT_REVIEW_ACK_REQUIRED')
            validate_review_ack(review_evidence[1],review_evidence[0],grant,now_ns)
        self.review_evidence=review_evidence
        self.grant_hash=hash_value(grant);self.bound_hash=hash_value(bound);self.review_hash=hash_value(review_evidence)
        self.failed=False;self.pending=None;self.title_reads=0;self.enum_calls=0
        self.seeds=set();self.enumeration_finished=False;self.seeds_registered=False
    def unchanged(self):
        need(hash_value(self.grant)==self.grant_hash and hash_value(self.bound)==self.bound_hash and hash_value(self.review_evidence)==self.review_hash,'AUTHORITY_OR_BOUND_IDENTITY_MUTATED','MISMATCH')
    def check_subject(self,api,subject):
        if self.bound is not None:
            need(identity(subject)==self.bound,'BOUND_IDENTITY_CHANGED_BEFORE_READ','MISMATCH');return
        keys=DESKTOP_KEYS if api=='EnumWindows' else SEED_KEYS
        exact(subject,keys)
        need(uint(subject['session_id'],2**32) and all(type(subject[k]) is str and subject[k] for k in ['host','desktop','observer_station']),'DISCOVERY_NATIVE_CONTEXT_TYPES')
        for k in DESKTOP_KEYS:need(subject[k]==self.grant['scope']['target_policy'][k],'DISCOVERY_DESKTOP_SCOPE_MISMATCH','MISMATCH')
        if api!='EnumWindows':
            need(self.enumeration_finished and hash_value(subject) in self.seeds,'UNREGISTERED_ENUMERATION_SEED')
            need(subject['class_name']==self.grant['scope']['target_policy']['class_name'],'DISCOVERY_CLASS_SCOPE_MISMATCH','MISMATCH')
    def register_enumerated_seeds(self,seeds,enumerated_count,complete):
        try:
            self.unchanged()
            need(not self.failed and self.pending is None and self.enumeration_finished and not self.seeds_registered,'ENUMERATION_SEED_STATE')
            need(complete is True and type(enumerated_count) is int and 0<=enumerated_count<=self.grant['scope']['enumeration_bounds']['max_windows'],'ENUMERATION_INCOMPLETE_OR_BOUNDS','INDETERMINATE')
            need(type(seeds) is list and len(seeds)<=enumerated_count,'ENUMERATION_SEED_COUNT')
            handles=set()
            for seed in seeds:
                exact(seed,SEED_KEYS)
                need(all(uint(seed[k],2**32) for k in ['pid','tid','session_id']) and uint(seed['hwnd']),'SEED_NATIVE_INTEGER')
                need(seed['hwnd'] not in handles,'DUPLICATE_ENUMERATION_SEED');handles.add(seed['hwnd'])
                need(all(seed[k]==self.grant['scope']['target_policy'][k] for k in DESKTOP_KEYS),'DISCOVERY_DESKTOP_SCOPE_MISMATCH','MISMATCH')
                self.seeds.add(hash_value(seed))
            self.seeds_registered=True
        except BaseException:self.failed=True;raise
    def begin(self,api,fields,subject,now_ns):
        try:
            self.unchanged()
            need(not self.failed and self.pending is None,'FAILED_OR_PENDING_NO_RETRY')
            need(uint(now_ns) and now_ns>=self.start and now_ns<self.grant['expires_ns'],'READ_TIME_INVALID')
            need(now_ns-self.start<=self.grant['scope']['timeouts']['total_ms']*1000000,'TOTAL_TIMEOUT','INDETERMINATE')
            need(api in self.grant['scope']['allowed_apis'],'UNAUTHORIZED_API')
            need(type(fields) is list and all(type(v) is str for v in fields) and len(fields)==len(set(fields)) and set(fields)<=set(self.grant['scope']['read_fields']),'UNAUTHORIZED_READ_FIELD')
            need(set(fields)<=API_FIELDS[api],'UNAUTHORIZED_API_FIELD_PAIR')
            self.check_subject(api,subject)
            if api=='EnumWindows':self.enum_calls+=1;need(self.enum_calls==1,'ENUMERATION_RETRY_FORBIDDEN')
            if api=='GetWindowTextW':self.title_reads+=1;need(self.title_reads<=2,'TITLE_READ_RETRY_FORBIDDEN')
            resource=self.grant['scope']['target_policy']['executable_path'] if api in FILE_APIS else None
            self.pending={'api':api,'fields':fields,'subject':dict(subject),'resource':resource,'started_ns':now_ns}
            return hash_value(self.pending)
        except BaseException:self.failed=True;raise
    def finish(self,ticket,subject,now_ns,status='OK'):
        try:
            self.unchanged()
            need(not self.failed and self.pending is not None and ticket==hash_value(self.pending),'READ_TICKET_MISMATCH')
            need(uint(now_ns) and now_ns>=self.pending['started_ns'],'READ_TIME_INVALID')
            need(now_ns-self.pending['started_ns']<=self.grant['scope']['timeouts']['per_call_ms']*1000000,'CALL_TIMEOUT','INDETERMINATE')
            need(now_ns-self.start<=self.grant['scope']['timeouts']['total_ms']*1000000 and now_ns<self.grant['expires_ns'],'TOTAL_TIMEOUT','INDETERMINATE')
            need(status=='OK','READ_API_ERROR','INDETERMINATE')
            need(type(subject) is dict and subject==self.pending['subject'],'TARGET_IDENTITY_CHANGED_DURING_READ','MISMATCH')
            self.check_subject(self.pending['api'],subject)
            if self.pending['api']=='EnumWindows':self.enumeration_finished=True
            self.calls.append(self.pending|{'ended_ns':now_ns,'status':status});self.pending=None
        except BaseException:self.failed=True;raise

def resolve_identity(grant,evidence,journal,now_ns):
    guard=ReadGuard(grant,journal,now_ns)
    need(grant['stage']=='IDENTITY_ONLY','SEPARATE_STAGE_AUTHORITY_REQUIRED')
    exact(evidence,{'artifact_kind','scope_sha256','enumeration_count','enumeration_complete','candidates'})
    need(evidence['artifact_kind']==PURPOSE and evidence['scope_sha256']==grant['scope_sha256'],'RESOLUTION_SCOPE_BINDING')
    need(type(evidence['enumeration_count']) is int and 0<=evidence['enumeration_count']<=grant['scope']['enumeration_bounds']['max_windows'] and evidence['enumeration_complete'] is True,'ENUMERATION_INCOMPLETE_OR_BOUNDS','INDETERMINATE')
    need(type(evidence['candidates']) is list,'CANDIDATE_LIST')
    need(len(evidence['candidates'])==1,'EXACTLY_ONE_IDENTITY_CANDIDATE_REQUIRED','AMBIGUOUS' if len(evidence['candidates'])>1 else 'UNKNOWN')
    need(len(evidence['candidates'])<=evidence['enumeration_count'],'CANDIDATE_ENUMERATION_COUNT_CONTRADICTION','INDETERMINATE')
    candidate=evidence['candidates'][0];exact(candidate,{'before','after','lifecycle'})
    match_policy(candidate['before'],grant['scope']['target_policy']);match_policy(candidate['after'],grant['scope']['target_policy'])
    need(candidate['before']==candidate['after'],'PROCESS_OR_WINDOW_IDENTITY_CHANGED','MISMATCH')
    lifecycle(candidate['lifecycle'],candidate['before'],candidate['after'])
    return {'artifact_kind':PURPOSE,'status':'RESOLVED_SYNTHETIC_REQUIRES_INDEPENDENT_REVIEW','scope_sha256':grant['scope_sha256'],
        'resolution_evidence_sha256':hash_value(evidence),'target_identity':candidate['before'],'target_identity_sha256':hash_value(candidate['before']),
        'diagnostic_authorized':False,'gate2_final_status':'BLOCKED_PENDING_SEPARATE_IDENTITY_RESOLUTION_AND_REVIEW'}

def validate_review_ack(ack,resolved,diagnostic_grant,now_ns):
    exact(ack,{'artifact_kind','decision','resolution_evidence_sha256','target_identity_sha256','diagnostic_scope_sha256','issued_ns','expires_ns'})
    need(ack['artifact_kind']==PURPOSE and ack['decision']=='SYNTHETIC_REVIEW_ACK_ONLY_NOT_CONTROL_CENTER_AUTHORITY','INDEPENDENT_REVIEW_ACK_REQUIRED')
    pins=diagnostic_grant['identity_binding']
    need(pins['review_ack_sha256']==hash_value(ack) and pins['target_identity_sha256']==resolved['target_identity_sha256'] and pins['resolution_evidence_sha256']==resolved['resolution_evidence_sha256'],'GRANT_REVIEW_ACK_BINDING_MISMATCH')
    need(ack['resolution_evidence_sha256']==resolved['resolution_evidence_sha256'] and ack['target_identity_sha256']==resolved['target_identity_sha256'] and ack['diagnostic_scope_sha256']==diagnostic_grant['scope_sha256'],'EXTERNAL_ACK_BINDING_MISMATCH')
    need(all(uint(v) for v in [ack['issued_ns'],ack['expires_ns'],now_ns]) and ack['issued_ns']<=now_ns<ack['expires_ns'],'REVIEW_ACK_TIME_WINDOW')

def accepted_title_module():
    source=HERE/'accepted_baseline'/'rate_readonly_gui_diag_v2.py';schema=HERE/'accepted_baseline'/'GUI_DIAGNOSTIC_EVIDENCE_SCHEMA_V2.json'
    need(hashlib.sha256(source.read_bytes()).hexdigest()==BASELINE_SHA and hashlib.sha256(schema.read_bytes()).hexdigest()==BASELINE_SCHEMA_SHA,'ACCEPTED_TITLE_BASELINE_PIN_MISMATCH')
    spec=importlib.util.spec_from_file_location('accepted_title_pure',source);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module

def verify_bound_diagnostic(grant,resolved,ack,evidence,journal,now_ns):
    need(grant['stage']=='BOUND_DIAGNOSTIC','IDENTITY_ONLY_CANNOT_DIAGNOSE')
    exact(resolved,{'artifact_kind','status','scope_sha256','resolution_evidence_sha256','target_identity','target_identity_sha256','diagnostic_authorized','gate2_final_status'})
    need(resolved['artifact_kind']==PURPOSE and resolved['status']=='RESOLVED_SYNTHETIC_REQUIRES_INDEPENDENT_REVIEW' and resolved['diagnostic_authorized'] is False,'RESOLVED_ARTIFACT_NOT_AUTHORITY')
    identity(resolved['target_identity']);need(hash_value(resolved['target_identity'])==resolved['target_identity_sha256'],'RESOLVED_IDENTITY_HASH_MISMATCH')
    guard=ReadGuard(grant,journal,now_ns,resolved['target_identity'],review_evidence=(resolved,ack))
    validate_review_ack(ack,resolved,grant,now_ns)
    exact(evidence,{'artifact_kind','scope_sha256','before','after','lifecycle','context','window'})
    need(evidence['artifact_kind']==PURPOSE and evidence['scope_sha256']==grant['scope_sha256'],'DIAGNOSTIC_SCOPE_BINDING')
    for state in ['before','after']:need(identity(evidence[state])==guard.bound,'TARGET_IDENTITY_CHANGED_'+state.upper(),'MISMATCH')
    lifecycle(evidence['lifecycle'],evidence['before'],evidence['after'])
    title=accepted_title_module();ctx=evidence['context'];win=evidence['window']
    title.validate_context(ctx);title.validate_window(win)
    need(ctx['host']==guard.bound['host'] and ctx['session_id']==ctx['parent_session_id']==guard.bound['session_id'] and ctx['desktop']==guard.bound['desktop'] and ctx['window_station']==guard.bound['observer_station'],'CONTEXT_IDENTITY_MISMATCH','MISMATCH')
    need(title.admin(ctx['observer_token']) and title.admin(ctx['parent_token']) and title.admin(win['process'].get('token')),'ADMIN_FULL_HIGH_INTEGRITY_REQUIRED')
    need(title.calls_valid(ctx['api_calls']) and title.calls_valid(win['api_calls']),'UNRELIABLE_API_EVIDENCE')
    need(all(c['api'] in grant['scope']['allowed_apis'] for c in ctx['api_calls']+win['api_calls']),'UNAUTHORIZED_API')
    for k in ['hwnd','pid','tid','class_name','session_id','desktop']:need(win[k]==guard.bound[k],'WINDOW_BINDING_MISMATCH:'+k,'MISMATCH')
    need(win['process'].get('image')==guard.bound['executable_path'] and win['process'].get('creation_filetime_100ns')==guard.bound['creation_filetime_100ns'] and win['process'].get('status')=='OBSERVED','PROCESS_BINDING_MISMATCH','MISMATCH')
    need(title.native_image(win['process']['image']),'ORIGINAL_NATIVE_PATH_GATE')
    audit=title.title_reliability(win)
    need(audit['reliable'] and win['title_complete'] is True and win['stable'] is True and not win['errors'],'UNKNOWN_TITLE_OBSERVATION','INDETERMINATE')
    need(win['visible'] and win['title_length']>0 and win['title'].strip().lower() in title.TITLES,'ORIGINAL_EXACT_TITLE_AND_ONE_BOUND_TARGET_REQUIRED')
    return {'artifact_kind':PURPOSE,'status':'PASS_OFFLINE_MODEL_ONLY','target_identity_sha256':resolved['target_identity_sha256'],'scope_sha256':grant['scope_sha256'],
        'title_reliability':audit,'native_execution_authorized':False,'gate2_final_status':'BLOCKED_PENDING_SEPARATE_IDENTITY_RESOLUTION_AND_REVIEW','atomic_snapshot':False}

def safe_result(operation,*args):
    try:return operation(*args)
    except (Denied,ValueError,TypeError,KeyError) as exc:
        return {'artifact_kind':PURPOSE,'status':'BLOCKED','identity_state':getattr(exc,'state','UNKNOWN'),'reason':getattr(exc,'reason',str(exc)),
            'native_execution_authorized':False,'no_retry':True,'gate2_final_status':'BLOCKED_PENDING_SEPARATE_IDENTITY_RESOLUTION_AND_REVIEW'}

def live_entry(*args,**kwargs):
    raise Denied('LIVE_IDENTITY_RESOLUTION_AND_DIAGNOSTIC_NOT_IMPLEMENTED_OR_AUTHORIZED')
