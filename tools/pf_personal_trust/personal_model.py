"""PF-PERSONAL-001 pure offline candidate. No acquisition, file I/O or authorization loader."""
import base64
import binascii
import datetime as dt
import hashlib
import json
import re

PERSONAL = 'PERSONAL_OWNER_ATTESTED'
ENTERPRISE = 'ENTERPRISE_INDEPENDENT_ATTESTED'
REALM = 'OFFLINE_SYNTHETIC_NOT_HOST_EVIDENCE'
TARGET = 'D:\\pagefile.sys'
GAPS = ('PF-SOURCE-001', 'PF-SOURCE-002', 'PF-SOURCE-003')
LABELS = ('LOCAL_OBSERVED', 'OWNER_CONFIRMED', 'CROSS_CHECKED', 'INDETERMINATE',
          'UNAVAILABLE', 'INDEPENDENTLY_ATTESTED_NOT_ESTABLISHED')
RISKS = (
 'OWNER_DECLARATION_NOT_INDEPENDENT_PROOF', 'LOCAL_METADATA_CAN_BE_SPOOFED',
 'LOCAL_CLOCK_NOT_TRUSTED_UTC', 'SEQUENTIAL_READS_NOT_ATOMIC',
 'LOCAL_FS_NOT_POWER_LOSS_DURABLE', 'NO_ENTERPRISE_OR_GUI_PROMOTION',
 'D_POLICY_AND_BOOT_APPLIED_NOT_PROVEN', 'NATIVE_CANCELLATION_NOT_QUALIFIED')
# Declarative specs only. There is no native transport, provider callback or shell dispatcher.
QUERIES = {
 'account': {'api':'WindowsIdentity.GetCurrent.User.Value+Process.GetCurrentProcess.SessionId',
             'namespace':'CURRENT_PROCESS', 'class':'CURRENT_ACCOUNT',
             'fields':['UserSID','SessionId'], 'filter':None, 'max_rows':1},
 'os': {'api':'Get-CimInstance', 'namespace':'ROOT/CIMV2', 'class':'Win32_OperatingSystem',
        'fields':['CSName','Version','BuildNumber','LastBootUpTime'], 'filter':None, 'max_rows':1},
 'computer': {'api':'Get-CimInstance', 'namespace':'ROOT/CIMV2', 'class':'Win32_ComputerSystem',
              'fields':['Name','AutomaticManagedPagefile'], 'filter':None, 'max_rows':1},
 'volume': {'api':'Get-CimInstance', 'namespace':'ROOT/CIMV2', 'class':'Win32_Volume',
            'fields':['DeviceID','DriveLetter','SerialNumber'], 'filter':"DriveLetter = 'D:'", 'max_rows':1},
 'settings': {'api':'Get-CimInstance', 'namespace':'ROOT/CIMV2', 'class':'Win32_PageFileSetting',
              'fields':['Name','InitialSize','MaximumSize'], 'filter':"Name = 'D:\\\\pagefile.sys'", 'max_rows':1},
 'usage': {'api':'Get-CimInstance', 'namespace':'ROOT/CIMV2', 'class':'Win32_PageFileUsage',
           'fields':['Name','AllocatedBaseSize','CurrentUsage','PeakUsage','TempPageFile'],
           'filter':"Name = 'D:\\\\pagefile.sys'", 'max_rows':1},
 'registry': {'api':'RegistryKey.OpenBaseKey.Registry64.OpenSubKey(writable=False).GetValue(DoNotExpandEnvironmentNames)',
              'namespace':'HKLM', 'class':r'SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management',
              'fields':['PagingFiles'], 'filter':None, 'max_rows':1},
 'tpm': {'api':'Get-CimInstance', 'namespace':'ROOT/CIMV2/Security/MicrosoftTpm', 'class':'Win32_Tpm',
         'fields':['IsEnabled_InitialValue','IsActivated_InitialValue','IsOwned_InitialValue'],
         'filter':None, 'max_rows':1}
}
ORDER = ('account_before','os_before','computer_before','volume_before','tpm',
         'settings','usage','registry','account_after','os_after','computer_after','volume_after')
SCOPE = {'version':'PF_PERSONAL_READ_SCOPE_V1', 'local_only':True, 'remote':False,
         'target':TARGET, 'queries':QUERIES, 'order':list(ORDER),
         'access':'EXISTING_TOKEN_READ_ONLY_NO_ENABLE_PRIVILEGES',
         'max_records':12, 'max_raw_bytes':16384, 'query_deadline_seconds':5,
         'total_deadline_seconds':120, 'fallback':False, 'retry':False, 'resume':False,
         'native_transport':'NOT_IMPLEMENTED_NOT_AUTHORIZED'}
IMMUTABLE = {'enterprise_G0':'BLOCKED','enterprise_evidence':'0/12 QUALIFIED',
             'GUI_Gate2':'BLOCKED','original_HALT_root_cause':'UNKNOWN',
             'source_gaps':list(GAPS)}

class Refused(ValueError):
    pass

def need(ok, why):
    if not ok:
        raise Refused(why)

def shape(v, keys, why):
    need(type(v) is dict and set(v)==set(keys), why)

def integer(v, lo, hi, why):
    need(type(v) is int and lo<=v<=hi, why)

def text(v, why, bound=512):
    need(type(v) is str and 0<len(v)<=bound and not any(ord(c)<32 or 0xd800<=ord(c)<=0xdfff for c in v), why)

def digest(v):
    return hashlib.sha256(canonical(v)).hexdigest()

def canonical(v):
    return json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode('utf-8')

def sha(v, why):
    need(type(v) is str and re.fullmatch('[0-9a-f]{64}',v) is not None, why)

def utc(v):
    need(type(v) is str and re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ',v) is not None, 'UTC_FORMAT')
    try:
        return dt.datetime.strptime(v,'%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=dt.timezone.utc)
    except ValueError:
        raise Refused('UTC_VALUE') from None

def strict(raw):
    need(type(raw) is bytes and 0<len(raw)<=524288, 'WIRE_BYTES')
    def pairs(items):
        out={}
        for k,v in items:
            need(k not in out,'DUPLICATE_KEY');out[k]=v
        return out
    def no_constant(_):
        raise Refused('NONFINITE')
    try:
        v=json.loads(raw.decode('utf-8','strict'),object_pairs_hook=pairs,parse_constant=no_constant)
    except (UnicodeError,ValueError,RecursionError) as error:
        raise Refused('INVALID_JSON:'+type(error).__name__) from None
    def walk(x,depth=0):
        need(depth<=16,'DEPTH')
        if type(x) is dict:
            need(len(x)<=32,'OBJECT_BOUND')
            for k,y in x.items():
                text(k,'KEY',128);walk(y,depth+1)
        elif type(x) is list:
            need(len(x)<=32,'ARRAY_BOUND')
            for y in x:walk(y,depth+1)
        elif type(x) is str:
            text(x,'STRING',32768) if x else None
        elif type(x) is int:
            integer(x,-2**63,2**63-1,'INTEGER')
        else:
            need(type(x) is bool or x is None,'JSON_TYPE')
    walk(v)
    need(raw==canonical(v)+b'\n','CANONICAL_JSON_SINGLE_LF')
    return v

def scope_check(v):
    need(type(v) is dict and canonical(v)==canonical(SCOPE),'EXACT_FIXED_SCOPE_REQUIRED')
    return 'DESIGN_ONLY_NOT_NATIVE_ENFORCEMENT'

def context(v):
    shape(v,('host','sid','session','boot_utc','volume_id','volume_serial','os_version','os_build'), 'CONTEXT_SHAPE')
    text(v['host'],'HOST',128);need(v['host'].startswith('SYNTHETIC-'),'SYNTHETIC_HOST_ONLY')
    need(type(v['sid']) is str and re.fullmatch(r'S-1-5-21-\d{1,10}-\d{1,10}-\d{1,10}-\d{1,10}',v['sid']) is not None,'SID')
    integer(v['session'],0,2**31-1,'SESSION');utc(v['boot_utc'])
    need(type(v['volume_id']) is str and re.fullmatch(r'\\\\\?\\Volume\{[0-9a-f-]{36}\}\\',v['volume_id']) is not None,'VOLUME_ID')
    integer(v['volume_serial'],0,2**32-1,'VOLUME_SERIAL')
    for k in ('os_version','os_build'):text(v[k],'OS_CONTEXT',64)

def output_path(v, attempt):
    need(type(v) is str and v=='D:\\RATE-Personal-Evidence\\'+attempt, 'EXACT_DEDICATED_OUTPUT_ROOT')

def consent(v, expected_context, expected_tool_sha, now_utc):
    """Checks fictional consent grammar/binding only; never authenticates or consumes real consent."""
    shape(v,('version','realm','tier','host_context','tool_sha256','scope_sha256','target','attempt',
             'nonce','approved','owner_owns_manages','owner_confirmation','not_before','expires',
             'evidence_destination','accepted_risks','operation'), 'CONSENT_SHAPE')
    need(v['version']=='PF_PERSONAL_SYNTHETIC_CONSENT_V1' and v['realm']==REALM,'SYNTHETIC_CONSENT_ONLY')
    need(v['tier']==PERSONAL,'TRUST_TIER_SEPARATION');context(v['host_context'])
    need(v['host_context']==expected_context,'EXACT_HOST_BINDING')
    sha(expected_tool_sha,'EXPECTED_TOOL_SHA');sha(v['tool_sha256'],'TOOL_SHA')
    need(v['tool_sha256']==expected_tool_sha and v['scope_sha256']==digest(SCOPE),'TOOL_SCOPE_BINDING')
    need(v['target']==TARGET and v['operation']=='LOCAL_READ_ONLY_ONCE','OPERATION_SCOPE')
    need(v['approved'] is True and v['owner_owns_manages'] is True and v['owner_confirmation']=='EXPLICIT_THIS_ATTEMPT_ONLY','EXPLICIT_OWNER_CONFIRMATION')
    need(type(v['attempt']) is str and re.fullmatch('SYNTHETIC-[A-Za-z0-9_-]{1,48}',v['attempt']) is not None,'ATTEMPT')
    sha(v['nonce'],'NONCE');output_path(v['evidence_destination'],v['attempt'])
    need(v['accepted_risks']==list(RISKS),'EXPLICIT_RISK_ACK')
    start,end,now=utc(v['not_before']),utc(v['expires']),utc(now_utc)
    need(start<=now<=end and 0<(end-start).total_seconds()<=600,'ONE_SHOT_LOCAL_TIME_WINDOW')
    need(utc(expected_context['boot_utc'])<=start,'BOOT_AFTER_APPROVAL')
    return {'status':'SYNTHETIC_CONTRACT_VALID_NO_RUNTIME_AUTHORIZATION','consent_sha256':digest(v),
            'real_execution_authorized':False,'enterprise_permit':False}

def _qid(name):
    return name.removesuffix('_before').removesuffix('_after')

def _validate_rows(q, rows):
    need(type(rows) is list and len(rows)<=1,'FIXED_SINGLE_ROW_BOUND')
    for v in rows:
        shape(v,QUERIES[q]['fields'],'EXACT_READ_FIELDS')
        if q=='account':
            need(type(v['UserSID']) is str and re.fullmatch(r'S-1-5-21-\d{1,10}-\d{1,10}-\d{1,10}-\d{1,10}',v['UserSID']) is not None,'READ_SID')
            integer(v['SessionId'],0,2**31-1,'READ_SESSION')
        elif q=='computer':
            text(v['Name'],'READ_HOST',128);need(type(v['AutomaticManagedPagefile']) is bool,'BOOLEAN_GLOBAL')
        elif q=='os':
            for k in ('CSName','Version','BuildNumber'):text(v[k],'READ_OS',128)
            utc(v['LastBootUpTime'])
        elif q=='volume':
            need(v['DriveLetter']=='D:','D_ONLY');text(v['DeviceID'],'DEVICE_ID')
            integer(v['SerialNumber'],0,2**32-1,'READ_SERIAL')
        elif q in ('settings','usage'):
            need(type(v['Name']) is str and v['Name'].casefold()==TARGET.casefold(),'D_PAGEFILE_ONLY')
            for k,x in v.items():
                if k not in ('Name','TempPageFile'):integer(x,0,2**32-1,'STRICT_UINT32_MIB')
            if q=='usage':need(type(v['TempPageFile']) is bool,'TEMP_BOOLEAN')
        elif q=='registry':
            need(type(v['PagingFiles']) is list and len(v['PagingFiles'])<=16,'REG_MULTI_STRING_BOUND')
            for s in v['PagingFiles']:text(s,'REG_STRING_BOUND',512)
        elif q=='tpm':
            need(all(type(x) is bool for x in v.values()),'TPM_BOOLEAN')
    return rows

def assess(raw, expected_context, expected_tool_sha, now_utc):
    """Offline evidence semantics. Partial records remain visible but cannot become a complete result."""
    e=strict(raw)
    shape(e,('version','realm','consent','tool_sha256','scope','context_before','context_after',
             'started_utc','ended_utc','clock_source','records'), 'ENVELOPE_SHAPE')
    need(e['version']=='PF_PERSONAL_SYNTHETIC_EVIDENCE_V1' and e['realm']==REALM,'OFFLINE_REALM_ONLY')
    context(expected_context);context(e['context_before']);context(e['context_after'])
    c=e['consent'];consent(c,expected_context,expected_tool_sha,now_utc)
    scope_check(e['scope'])
    need(e['tool_sha256']==expected_tool_sha,'EVIDENCE_TOOL_BINDING')
    start,end=utc(e['started_utc']),utc(e['ended_utc'])
    need(utc(c['not_before'])<=start<=end<=utc(c['expires']) and end<=utc(now_utc) and (end-start).total_seconds()<=120,'READ_WINDOW')
    need(e['clock_source']=='WINDOWS_LOCAL_UNTRUSTED','NO_TRUSTED_CLOCK_CLAIM')
    need(type(e['records']) is list and len(e['records'])==len(ORDER),'RECORD_COMPLETENESS')
    parsed={};record_evidence=[];previous=start;issues=[]
    for n,(record,name) in enumerate(zip(e['records'],ORDER)):
        q=_qid(name)
        shape(record,('sequence','id','query','status','started_utc','ended_utc','raw_base64','raw_sha256'),'RECORD_SHAPE')
        need(type(record['sequence']) is int and record['sequence']==n+1 and record['id']==name,'SEQUENCE_ORDER')
        need(canonical(record['query'])==canonical(QUERIES[q]),'FIXED_QUERY_BINDING')
        rs,re_=utc(record['started_utc']),utc(record['ended_utc'])
        need(previous<=rs<=re_<=end and (re_-rs).total_seconds()<=5,'QUERY_WINDOW')
        previous=re_
        need(record['status'] in ('OBSERVED','UNAVAILABLE','INDETERMINATE'),'RECORD_STATUS')
        if record['status']!='OBSERVED':
            need(record['raw_base64'] is None and record['raw_sha256'] is None,'UNKNOWN_NO_FABRICATED_RAW')
            parsed[name]=None
            if q!='tpm':issues.append(name+':'+record['status'])
        else:
            need(type(record['raw_base64']) is str,'RAW_ENCODING')
            try:b=base64.b64decode(record['raw_base64'],validate=True)
            except (ValueError,binascii.Error):raise Refused('RAW_BASE64') from None
            need(0<len(b)<=16384 and base64.b64encode(b).decode('ascii')==record['raw_base64'],'RAW_BYTE_BOUND')
            need(hashlib.sha256(b).hexdigest()==record['raw_sha256'],'RAW_SHA256')
            parsed[name]=_validate_rows(q,strict(b))
            if not parsed[name] and q!='tpm':issues.append(name+':MISSING_INSTANCE')
        record_evidence.append({'id':name,'label':'LOCAL_OBSERVED' if record['status']=='OBSERVED' else record['status'],
                                'raw_sha256':record['raw_sha256'],'independent_attestation':'INDEPENDENTLY_ATTESTED_NOT_ESTABLISHED'})
    same=e['context_before']==e['context_after']==expected_context
    if not same:issues.append('CONTEXT_RACE_OR_MISMATCH')
    # Every source-specific context must corroborate the declared context; title/hostname alone never suffices.
    expected={
      'account':{'UserSID':expected_context['sid'],'SessionId':expected_context['session']},
      'os':{'CSName':expected_context['host'],'Version':expected_context['os_version'],
            'BuildNumber':expected_context['os_build'],'LastBootUpTime':expected_context['boot_utc']},
      'computer':None,
      'volume':{'DeviceID':expected_context['volume_id'],'DriveLetter':'D:','SerialNumber':expected_context['volume_serial']}}
    for q in expected:
        a,b=parsed[q+'_before'],parsed[q+'_after']
        if a!=b:issues.append(q+':SEQUENTIAL_MISMATCH')
        for v in (a,b):
            if v:
                if q=='computer':
                    if v[0]['Name']!=expected_context['host']:issues.append('HOST_MISMATCH')
                elif v[0]!=expected[q]:issues.append(q+':SOURCE_CONTEXT_MISMATCH')
    valid=not issues
    def child(name,status):
        return {'status':status if valid and parsed[name] else 'INDETERMINATE',
                'source_record':name,'raw_sha256':next(r['raw_sha256'] for r in e['records'] if r['id']==name)}
    result={
      'status':'OFFLINE_COMPLETE_RAW_SEMANTICS_ONLY' if valid else 'INDETERMINATE',
      'realm':REALM,'trust_tier_model':PERSONAL,'owner_declaration':'OWNER_CONFIRMED',
      'context':'CROSS_CHECKED' if valid else 'INDETERMINATE',
      'independent_attestation':'INDEPENDENTLY_ATTESTED_NOT_ESTABLISHED',
      'configuration':child('settings','CONFIGURATION_OBSERVED'),
      'runtime_usage':child('usage','RUNTIME_USAGE_OBSERVED'),
      'global_automatic':child('computer_before','SYSTEM_WIDE_AUTOMATIC_SETTING_OBSERVED'),
      'd_policy':'D_POLICY_NOT_PROVEN','boot_applied':'BOOT_APPLIED_NOT_PROVEN',
      'tpm':('LOCAL_OBSERVED' if parsed['tpm'] else ('UNAVAILABLE' if e['records'][4]['status']=='UNAVAILABLE' else 'INDETERMINATE')),
      'tpm_readiness':'INDETERMINATE','tpm_attestation':'INDEPENDENTLY_ATTESTED_NOT_ESTABLISHED',
      'issues':issues,'records':record_evidence,'input_sha256':hashlib.sha256(raw).hexdigest(),
      'consent_sha256':digest(c),'tool_sha256':expected_tool_sha,'scope_sha256':digest(SCOPE),
      'real_execution_authorized':False,'enterprise_permit':False,'NoAutoNext':True,
      'original_states':json.loads(canonical(IMMUTABLE))}
    return result

def model_transition(journal, event):
    """In-memory fault model only. No filesystem durability, real nonce store or consent consumption."""
    shape(journal,('realm','attempt','nonce','events'),'JOURNAL_SHAPE')
    need(journal['realm']==REALM,'SYNTHETIC_JOURNAL_ONLY')
    text(journal['attempt'],'JOURNAL_ATTEMPT');sha(journal['nonce'],'JOURNAL_NONCE')
    need(type(journal['events']) is list and len(journal['events'])<=5,'JOURNAL_BOUND')
    transitions={('EMPTY','OWNER_APPROVES'):'APPROVED',('APPROVED','BEGIN'):'READING',
                 ('APPROVED','CANCEL'):'HALTED',('READING','CANCEL'):'HALTED',
                 ('READING','COMPLETE_RAW'):'CLOSED',
                 ('READING','ERROR'):'HALTED',('READING','TIMEOUT'):'HALTED',
                 ('READING','CRASH'):'UNKNOWN',('READING','UNKNOWN_OUTCOME'):'UNKNOWN'}
    state='EMPTY';previous=None
    for n,row in enumerate(journal['events']):
        shape(row,('sequence','event','previous_sha256','entry_sha256'),'JOURNAL_ENTRY')
        need(type(row['sequence']) is int and row['sequence']==n+1 and row['previous_sha256']==previous,'JOURNAL_CHAIN')
        core={k:row[k] for k in ('sequence','event','previous_sha256')}
        need(digest({'attempt':journal['attempt'],'nonce':journal['nonce'],**core})==row['entry_sha256'],'JOURNAL_HASH')
        need(type(row['event']) is str,'JOURNAL_EVENT')
        need((state,row['event']) in transitions,'JOURNAL_STATE')
        state=transitions[state,row['event']];previous=row['entry_sha256']
    need(type(event) is str and (state,event) in transitions,'NO_RETRY_RESUME_OR_AUTO_NEXT')
    core={'sequence':len(journal['events'])+1,'event':event,'previous_sha256':previous}
    row={**core,'entry_sha256':digest({'attempt':journal['attempt'],'nonce':journal['nonce'],**core})}
    return {'journal':{**journal,'events':journal['events']+[row]},'state':transitions[state,event],
            'real_execution_authorized':False,'durability':'NOT_IMPLEMENTED_MODEL_ONLY'}

