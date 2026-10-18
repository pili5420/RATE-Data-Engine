"""Private Runner packet validation and strict, reviewed public projection. No acquisition or authority."""
import base64,hashlib,json,re
import personal_model as base
REALM='RUNNER_ONLY_NOT_ORIGINAL_HOST_EVIDENCE'
def need(ok,why):base.need(ok,why)
def shape(v,keys,why):base.shape(v,keys,why)
def evaluate_private(raw,head,run_id,attempt):
 p=base.strict(raw)
 shape(p,('version','realm','head','run_id','run_attempt','started_utc','ended_utc','elapsed_ms','status','records','powershell_version'),'PRIVATE_PACKET')
 need(p['version']=='PF_PERSONAL_002_NATIVE_PRIVATE_V1' and p['realm']==REALM,'RUNNER_REALM')
 need(p['head']==head and p['run_id']==run_id and p['run_attempt']==attempt=='1','RUN_BINDING')
 base.integer(p['elapsed_ms'],0,2**31-1,'TOTAL_ELAPSED')
 need(type(p['powershell_version']) is str and re.fullmatch('[0-9]+(?:[.][0-9]+){2,3}',p['powershell_version']) is not None,'PWSH_VERSION')
 start,end=base.utc(p['started_utc']),base.utc(p['ended_utc']);need(start<=end,'PACKET_CLOCK')
 need(p['status'] in ('COMPLETED','HALT') and type(p['records']) is list and 0<len(p['records'])<=12,'PACKET_STATE')
 parsed={};public=[];last=start;halt=False;missing=[];conflict=[]
 for i,r in enumerate(p['records']):
  shape(r,('sequence','id','query','status','started_utc','ended_utc','elapsed_ms','raw_base64','raw_sha256','error_kind','hresult','provider_availability'),'PRIVATE_RECORD')
  need(type(r['sequence']) is int and r['sequence']==i+1 and r['id']==base.ORDER[i],'RECORD_ORDER')
  name=r['id'];q=base._qid(name)
  need(base.canonical(r['query'])==base.canonical(base.QUERIES[q]),'FIXED_SOURCE_NAMESPACE_FIELDS_FILTER')
  a,b=base.utc(r['started_utc']),base.utc(r['ended_utc']);need(last<=a<=b<=end,'RECORD_CLOCK');last=b
  base.integer(r['elapsed_ms'],0,2**31-1,'QUERY_ELAPSED')
  need(type(r['hresult']) is int or r['hresult'] is None,'HRESULT_TYPE')
  need(r['status'] in ('OBSERVED','SOURCE_ABSENT','UNAVAILABLE','HALT'),'SOURCE_STATUS')
  need(not halt,'RECORD_AFTER_HALT')
  if r['status']!='HALT':need(r['elapsed_ms']<=5000 and p['elapsed_ms']<=120000,'DEADLINE_NOT_PASS')
  if r['status']=='HALT':
   halt=True;need(i==len(p['records'])-1 and p['status']=='HALT','HALT_FINAL_ONLY')
  elif r['status']=='UNAVAILABLE':
   need(q=='tpm' and r['provider_availability']=='OPTIONAL_PROVIDER_UNAVAILABLE','ONLY_OPTIONAL_TPM_UNAVAILABLE')
   need(r['raw_base64'] is None and r['raw_sha256'] is None,'UNAVAILABLE_NO_FABRICATION')
  else:
   need(r['elapsed_ms']<=5000 and p['elapsed_ms']<=120000,'DEADLINE_NOT_PASS')
   need(r['error_kind'] is None and r['hresult'] is None,'SUCCESS_ERROR_CONFLICT')
  rows=None
  if r['raw_base64'] is not None:
   need(type(r['raw_base64']) is str,'RAW_ENCODING')
   try:data=base64.b64decode(r['raw_base64'],validate=True)
   except ValueError:raise base.Refused('RAW_BASE64') from None
   need(0<len(data)<=16384 and base64.b64encode(data).decode()==r['raw_base64'],'RAW_BOUND')
   need(hashlib.sha256(data).hexdigest()==r['raw_sha256'],'RAW_DIGEST')
   rows=base._validate_rows(q,base.strict(data))
   if r['status']!='HALT':
    need((len(rows)==0)==(r['status']=='SOURCE_ABSENT'),'ABSENCE_NOT_FAKE_INSTANCE')
    expected='QUERY_SUCCEEDED_NO_INSTANCE' if not rows else 'RESPONSE_RECEIVED_NOT_PROVIDER_BINARY_ATTESTATION'
    need(r['provider_availability']==expected,'PROVIDER_AVAILABILITY_NOT_ATTESTATION')
  else:need(r['status'] in ('UNAVAILABLE','HALT') and r['raw_sha256'] is None,'MISSING_SUCCESS_RAW')
  parsed[name]=rows
  if rows==[] and q!='tpm':missing.append(name)
  # Only reviewed non-identifying actual response fields may be public.
  projection=None
  if rows:
   row=rows[0]
   fields={'account':['SessionId'],'os':['Version','BuildNumber'],'computer':['AutomaticManagedPagefile'],
           'volume':['DriveLetter'],'settings':['Name','InitialSize','MaximumSize'],
           'usage':['Name','AllocatedBaseSize','CurrentUsage','PeakUsage','TempPageFile'],
           'registry':[],'tpm':base.QUERIES['tpm']['fields']}[q]
   projection={k:row[k] for k in fields}
   if q in ('settings','usage'):projection['Name']=base.TARGET # canonical selector, private digest retains exact source casing
   if q=='registry':projection={'entry_count':len(row['PagingFiles'])}
  public.append({'id':name,'query':r['query'],'status':r['status'],'elapsed_ms':r['elapsed_ms'],
   'provider_availability':r['provider_availability'],'raw_sha256':r['raw_sha256'],'raw_bytes':0 if r['raw_base64'] is None else len(data),
   'row_count':None if rows is None else len(rows),'projection':projection,'hresult':r['hresult'],'error_recorded':r['error_kind'] is not None})
 if p['status']=='COMPLETED':
  need(len(p['records'])==12 and not halt and p['elapsed_ms']<=120000,'COMPLETE_12_RECORDS')
  for q in ('account','os','computer','volume'):
   a,b=parsed[q+'_before'],parsed[q+'_after']
   if a!=b:conflict.append(q)
  osrow=parsed['os_before'];computer=parsed['computer_before']
  if osrow and computer and osrow[0]['CSName']!=computer[0]['Name']:conflict.append('OS_COMPUTER_HOST')
 else:need(halt,'HALT_WITHOUT_FAILED_RECORD')
 context='INDETERMINATE' if halt or conflict or any(q in missing for q in ('account_before','os_before','computer_before','volume_before','account_after','os_after','computer_after','volume_after')) else 'CROSS_CHECKED_NOT_ATOMIC_NOT_ATTESTED'
 def status(q,label):return label if not halt and not conflict and parsed.get(q) else 'INDETERMINATE'
 report={'version':'PF_PERSONAL_002_RUNNER_PUBLIC_V1','realm':REALM,'head':head,'run_id':run_id,'run_attempt':attempt,'powershell_version':p['powershell_version'],
  'native_outcome':'HALT' if halt else 'NATIVE_READ_COMPLETED','context':context,'missing_sources':missing,'context_conflicts':conflict,
  'configuration':status('settings','CONFIGURATION_OBSERVED'),'runtime_usage':status('usage','RUNTIME_USAGE_OBSERVED'),
  'global_automatic':status('computer_before','SYSTEM_WIDE_AUTOMATIC_SETTING_OBSERVED'),
  'd_policy':'D_POLICY_NOT_PROVEN','boot_applied':'BOOT_APPLIED_NOT_PROVEN','records':public,
  'private_packet_sha256':hashlib.sha256(raw).hexdigest(),'private_raw_publicly_retained':False,
  'private_raw_posthoc_independent_rehash':'UNAVAILABLE_AFTER_EPHEMERAL_RUNNER_TEARDOWN',
  'raw_verified_before_redaction':True,'original_host_authorized':False,'owner_consent_issued':False,
  'provider_binary_attestation':False,'sequential_atomic_snapshot':False,'NoAutoNext':True}
 check_public(report)
 return report
def check_public(r):
 shape(r,('version','realm','head','run_id','run_attempt','powershell_version','native_outcome','context','missing_sources','context_conflicts','configuration','runtime_usage','global_automatic','d_policy','boot_applied','records','private_packet_sha256','private_raw_publicly_retained','private_raw_posthoc_independent_rehash','raw_verified_before_redaction','original_host_authorized','owner_consent_issued','provider_binary_attestation','sequential_atomic_snapshot','NoAutoNext'),'PUBLIC_EXACT_SCHEMA')
 need(type(r['powershell_version']) is str and re.fullmatch('[0-9]+(?:[.][0-9]+){2,3}',r['powershell_version']) is not None,'PUBLIC_PWSH_VERSION')
 need(r['version']=='PF_PERSONAL_002_RUNNER_PUBLIC_V1' and r['realm']==REALM,'PUBLIC_REALM')
 need(type(r['head']) is str and re.fullmatch('[0-9a-f]{40}',r['head']) is not None,'PUBLIC_HEAD')
 need(type(r['run_id']) is str and re.fullmatch('[1-9][0-9]{0,19}',r['run_id']) is not None and r['run_attempt']=='1','PUBLIC_RUN')
 need(r['original_host_authorized'] is False and r['owner_consent_issued'] is False and r['provider_binary_attestation'] is False and r['sequential_atomic_snapshot'] is False and r['NoAutoNext'] is True,'NO_QUALIFICATION_PROMOTION')
 need(r['d_policy']=='D_POLICY_NOT_PROVEN' and r['boot_applied']=='BOOT_APPLIED_NOT_PROVEN' and r['private_raw_publicly_retained'] is False,'POLICY_PRIVACY')
 need(r['raw_verified_before_redaction'] is True and r['private_raw_posthoc_independent_rehash']=='UNAVAILABLE_AFTER_EPHEMERAL_RUNNER_TEARDOWN','EXACT_PRIVACY_LIMIT')
 base.sha(r['private_packet_sha256'],'PRIVATE_DIGEST')
 need(type(r['records']) is list and 0<len(r['records'])<=12,'PUBLIC_RECORDS')
 rows={};halt=False;missing=[]
 for i,row in enumerate(r['records']):
  shape(row,('id','query','status','elapsed_ms','provider_availability','raw_sha256','raw_bytes','row_count','projection','hresult','error_recorded'),'PUBLIC_RECORD_EXACT')
  need(row['id']==base.ORDER[i],'PUBLIC_ORDER');q=base._qid(row['id']);rows[row['id']]=row
  need(base.canonical(row['query'])==base.canonical(base.QUERIES[q]),'PUBLIC_FIXED_QUERY')
  base.integer(row['elapsed_ms'],0,2**31-1,'PUBLIC_ELAPSED')
  need(row['status'] in ('OBSERVED','SOURCE_ABSENT','UNAVAILABLE','HALT'),'PUBLIC_STATUS')
  need(type(row['error_recorded']) is bool,'PUBLIC_ERROR_BOOL')
  if row['hresult'] is not None:base.integer(row['hresult'],-2**31,2**31-1,'PUBLIC_HRESULT')
  base.integer(row['raw_bytes'],0,16384,'PUBLIC_BYTE_BOUND')
  if row['raw_sha256'] is not None:base.sha(row['raw_sha256'],'PUBLIC_RAW_DIGEST')
  if row['row_count'] is not None:base.integer(row['row_count'],0,1,'PUBLIC_ROW_BOUND')
  need(row['provider_availability'] in ('QUERY_SUCCEEDED_NO_INSTANCE','RESPONSE_RECEIVED_NOT_PROVIDER_BINARY_ATTESTATION','OPTIONAL_PROVIDER_UNAVAILABLE','SOURCE_ERROR'),'PUBLIC_PROVIDER_STATUS')
  if row['status']=='HALT':
   halt=True;need(i==len(r['records'])-1 and row['error_recorded'],'PUBLIC_HALT_TERMINAL')
  else:need(row['elapsed_ms']<=5000,'PUBLIC_TIMEOUT_CANNOT_PASS')
  if row['status']=='OBSERVED':
   need(row['raw_sha256'] is not None and row['raw_bytes']>0 and row['row_count']==1 and row['projection'] is not None and not row['error_recorded'] and row['hresult'] is None,'PUBLIC_OBSERVATION_FIELDS')
   need(row['provider_availability']=='RESPONSE_RECEIVED_NOT_PROVIDER_BINARY_ATTESTATION','PUBLIC_PROVIDER_CONFLICT')
  elif row['status']=='SOURCE_ABSENT':
   need(row['raw_sha256'] is not None and row['raw_bytes']>0 and row['row_count']==0 and row['projection'] is None and not row['error_recorded'] and row['hresult'] is None,'PUBLIC_ABSENCE_FIELDS')
   need(row['provider_availability']=='QUERY_SUCCEEDED_NO_INSTANCE','PUBLIC_PROVIDER_CONFLICT')
   if q!='tpm':missing.append(row['id'])
  elif row['status']=='UNAVAILABLE':
   need(q=='tpm' and row['raw_sha256'] is None and row['raw_bytes']==0 and row['row_count'] is None and row['projection'] is None and row['error_recorded'],'PUBLIC_OPTIONAL_UNAVAILABLE')
   need(row['provider_availability']=='OPTIONAL_PROVIDER_UNAVAILABLE','PUBLIC_PROVIDER_CONFLICT')
  if row['raw_sha256'] is None:need(row['raw_bytes']==0 and row['row_count'] is None and row['projection'] is None,'PUBLIC_NO_FAKE_RAW')
  allowed={'account':{'SessionId'},'os':{'Version','BuildNumber'},'computer':{'AutomaticManagedPagefile'},
   'volume':{'DriveLetter'},'settings':{'Name','InitialSize','MaximumSize'},'usage':{'Name','AllocatedBaseSize','CurrentUsage','PeakUsage','TempPageFile'},
   'registry':{'entry_count'},'tpm':set(base.QUERIES['tpm']['fields'])}[q]
  if row['projection'] is not None:
   need(type(row['projection']) is dict and set(row['projection'])==allowed,'PUBLIC_NO_IDENTITY_OR_REGISTRY_RAW')
   v=row['projection']
   if q in ('settings','usage'):
    need(v['Name']==base.TARGET,'PUBLIC_D_PATH_ONLY')
    for key,value in v.items():
     if key not in ('Name','TempPageFile'):base.integer(value,0,2**32-1,'PUBLIC_NUMERIC_TYPE')
    if q=='usage':need(type(v['TempPageFile']) is bool,'PUBLIC_TEMP_BOOL')
   if q=='volume':need(v['DriveLetter']=='D:','PUBLIC_VOLUME_PROJECTION')
   if q=='account':base.integer(v['SessionId'],0,2**31-1,'PUBLIC_SESSION_TYPE')
   if q=='os':
    for value in v.values():need(type(value) is str and re.fullmatch(r'[0-9]+(?:\.[0-9]+)*',value) is not None and len(value)<=64,'PUBLIC_OS_NUMERIC_VERSION_ONLY')
   if q=='registry':base.integer(v['entry_count'],0,16,'PUBLIC_REGISTRY_COUNT')
   if q=='computer':need(type(v['AutomaticManagedPagefile']) is bool,'PUBLIC_GLOBAL_BOOL')
   if q=='tpm':need(all(type(value) is bool for value in v.values()),'PUBLIC_TPM_BOOL')
 need(r['missing_sources']==missing,'PUBLIC_MISSING_CONSISTENCY')
 need(type(r['context_conflicts']) is list and all(type(x) is str and x in ('account','os','computer','volume','OS_COMPUTER_HOST') for x in r['context_conflicts']) and len(r['context_conflicts'])==len(set(r['context_conflicts'])),'PUBLIC_CONFLICT_CLOSED_SET')
 for q in ('account','os','computer','volume'):
  a,b=rows.get(q+'_before'),rows.get(q+'_after')
  if a and b and a['status'] in ('OBSERVED','SOURCE_ABSENT') and b['status'] in ('OBSERVED','SOURCE_ABSENT') and a['raw_sha256']!=b['raw_sha256']:
   need(q in r['context_conflicts'],'PUBLIC_CONTEXT_MISMATCH_HIDDEN')
 complete=not halt and len(r['records'])==12
 need(complete or halt,'PUBLIC_INCOMPLETE_WITHOUT_HALT')
 need(r['native_outcome']==('NATIVE_READ_COMPLETED' if complete else 'HALT'),'PUBLIC_OUTCOME')
 context_missing=any(n in missing for n in ('account_before','account_after','os_before','os_after','computer_before','computer_after','volume_before','volume_after'))
 expected_context='INDETERMINATE' if halt or r['context_conflicts'] or context_missing else 'CROSS_CHECKED_NOT_ATOMIC_NOT_ATTESTED'
 need(r['context']==expected_context,'PUBLIC_CONTEXT_NO_PROMOTION')
 for field,name,label in [('configuration','settings','CONFIGURATION_OBSERVED'),('runtime_usage','usage','RUNTIME_USAGE_OBSERVED'),('global_automatic','computer_before','SYSTEM_WIDE_AUTOMATIC_SETTING_OBSERVED')]:
  observed=complete and not r['context_conflicts'] and rows.get(name,{}).get('status')=='OBSERVED'
  need(r[field]==(label if observed else 'INDETERMINATE'),'PUBLIC_CHILD_NO_PROMOTION')
 return 'REVIEWED_RUNNER_ONLY_PUBLIC_FIELDS'

