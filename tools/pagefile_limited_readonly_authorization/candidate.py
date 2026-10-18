"""PF-LRO-001 ORIGINAL-TARGET SCOPE CANDIDATE, OFFLINE DATA ONLY.

No native transport, callback, collector, Permit loader, signer, target root IO,
CLI or activation path. No input can cause a Windows API call or issue a Permit.
Accepted PR78's pure evidence engine is reused without changing its source or
SYNTHETIC/RUNNER realm gates. Real target context is deliberately unresolved.
"""
import base64
import binascii
import hashlib
import json
from tools.pagefile_non_gui_evidence import evidence as accepted

BASE_HEAD='7208a58e3b0eadc3ee910d508af04191b018a219'
ACCEPTED_ENGINE_SHA256='1279dfe85cd3685e7af081908235a969ee2172a6c021d4022c793284de6f5e70'
ACCEPTED_SCHEMA_SHA256='2126fca45026a23bbe4be80f6a2b29a760ef6a38e470b3c33dab92c8f05bcbbd'
GAPS=('PF-SOURCE-001','PF-SOURCE-002','PF-TRUST-003')
REQUIREMENTS=('HOST','BOOT','VOLUME','CLOCK','OPERATOR_RIGHTS','PROVIDER_PROFILE','TARGET_TOOL_QUALIFICATION','PHYSICAL_OUTPUT','DURABLE_ATTEMPT','DEADLINE_CONTAINMENT','SEPARATE_SCOPE_AUTHORIZATION','INDEPENDENT_EXTERNAL_REVIEW')
PLAN={
 'version':'PF_LRO_READ_SCOPE_V1','target':'D:\\pagefile.sys','mode':'OFFLINE_CANDIDATE_NO_NATIVE_TRANSPORT',
 'namespace':'ROOT/CIMV2',
 'classes':{key:{'class':v[0],'fields':list(v[1]),'provider':v[2]} for key,v in accepted.CLASSES.items()},
 'filters':{'computer':None,'boot':None,'product':None,'volumes':"DriveLetter = 'D:'",'settings':"Name = 'D:\\\\pagefile.sys'",'usage':"Name = 'D:\\\\pagefile.sys'"},
 'query_order':list(accepted.ORDER),
 'api_allowlist':['CimCmdlets\\Get-CimClass','CimCmdlets\\Get-CimInstance','Registry64.LocalMachine.OpenBaseKey','RegistryKey.OpenSubKey(false)','RegistryKey.GetValueKind','RegistryKey.GetValue(DoNotExpandEnvironmentNames)'],
 'instance_parameters':['Namespace','ClassName','Property','OperationTimeoutSec=5','ErrorAction=Stop','EXACT_LITERAL_Filter_ONLY_WHEN_LISTED'],
 'metadata_parameters':['Namespace','ClassName','OperationTimeoutSec=5','ErrorAction=Stop'],
 'registry':{'hive':'LocalMachine','view':'Registry64','key':accepted.REGKEY,'value':'PagingFiles','kind':'MultiString','writable':False},
 'rights':['WMI namespace WBEM_ENABLE read only','Registry read-only exact subkey/value','future evidence-root CreateNew only; no system writes'],
 'counts':{'instance_reads':10,'metadata_reads':10,'registry_value_reads':1,'records':11,'rows_per_CIM_record':1,'registry_strings':32,'string_characters':512,'raw_record_bytes':98304},
 'time_bounds':{'CIM_option_seconds':5,'record_wall_seconds':10,'total_seconds':120},
 'filter_qualification':'FIXED_DESIGN_ONLY_NOT_DISPATCHED_OR_TARGET_QUALIFIED; no dynamic Filter, Query, wildcard, remote/session/InputObject or unfiltered fallback',
 'registry_collateral':'Exact PagingFiles MultiString necessarily includes other-drive entries if present; bounded raw value requires separate explicit disclosure/retention approval. No other values or keys.',
 'claim_scope':'RAW_CONFIGURATION_AND_RAW_RUNTIME_ONLY_NOT_D_POLICY_OR_BOOT_APPLIED',
 'sequential_reads_atomic':False,'matching_endpoints_exclude_ABA':False,
}
SAFETY={
 'mode':'OFFLINE_CONTRACT_ONLY','physical_root':None,'owner_SID':None,'DACL':None,'directory_file_identity':None,'volume_identity':None,
 'nonce':None,'attempt_id':None,'not_before_utc':None,'deadline_utc':None,'trusted_clock_reference':None,
 'root_rules':['exact pre-reviewed physical path','no UNC/device/ADS/traversal/alias/reparse/junction','owner SID and least-write DACL independently verified','handle-bound same-volume exclusive CreateNew','no overwrite; preserve every partial result','power-loss/directory-flush guarantees independently qualified'],
 'journal_rules':['independent durable nonce reservation before any read','intent hashes tool/schema/scope/target/boot/output/time','crash/unknown consumes future attempt; no local repair','external review of sealed raw evidence; no automatic promotion'],
 'read_scope_sha256':None,
 'clock_rules':['external trusted UTC and <=1000ms uncertainty design bound','conservative [not_before,deadline) <=120s','monotonic watchdog and verified cancellation/containment','clock rollback/boundary uncertainty => HALT'],
 'retry':0,'resume':False,'fallback':False,'auto_next':False,'cleanup_on_failure':False,
 'any_error':'HALT_PRESERVE_UNKNOWN_OUTCOME','native_enforcement':'NOT_IMPLEMENTED_NOT_QUALIFIED',
}

class Invalid(ValueError):pass
def need(ok,why):
 if not ok:raise Invalid(why)
def shape(value,keys,why):need(type(value) is dict and set(value)==set(keys),'CLOSED_SCHEMA:'+why)
def canonical(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8')
def digest(value):return hashlib.sha256(canonical(value)).hexdigest()
def exact(value,expected,why):need(canonical(value)==canonical(expected),'EXACT_BINDING:'+why)
def strict(raw):
 need(type(raw) is bytes and 0<len(raw)<=1048576,'BYTE_BOUND')
 def pairs(items):
  obj={}
  for k,v in items:need(k not in obj,'DUPLICATE_KEY');obj[k]=v
  return obj
 try:
  value=json.loads(raw.decode('utf-8','strict'),object_pairs_hook=pairs,parse_constant=lambda _:(_ for _ in ()).throw(Invalid('NONFINITE')))
  need(canonical(value)+b'\n'==raw,'CANONICAL_UTF8_SINGLE_LF');return value
 except (ValueError,UnicodeError,TypeError,RecursionError) as error:raise Invalid('INVALID_JSON:'+str(error)) from error

def scope_hash():return digest(PLAN)
def offline_safety_contract():
 result=json.loads(canonical(SAFETY));result['read_scope_sha256']=scope_hash();return result
def check_plan(plan):exact(plan,PLAN,'fixed read scope');return 'OFFLINE_PLAN_VALID_NOT_NATIVE_ENFORCEMENT'
def check_safety(contract):exact(contract,offline_safety_contract(),'unresolved offline safety');return 'DESIGN_ONLY_EXTERNAL_SAFETY_UNQUALIFIED'

def assess_synthetic(raw):
 """Validate fictional D-only projected records, never collect/read target data.

 Fixed Filter literals are a proposed future API plan, not proof a filter ran.
 The old engine is only given original SYNTHETIC bytes; no realm relabeling.
 """
 try:
  envelope=strict(raw)
  shape(envelope,['version','realm','base_head','accepted_engine_sha256','accepted_schema_sha256','scope_sha256','synthetic_source_packet_b64'],'candidate')
  exact(envelope['version'],'PF_LRO_OFFLINE_RAW_CANDIDATE_V1','version')
  exact(envelope['realm'],'SYNTHETIC_ONLY','offline realm')
  exact(envelope['base_head'],BASE_HEAD,'base head')
  exact(envelope['accepted_engine_sha256'],ACCEPTED_ENGINE_SHA256,'accepted engine')
  exact(envelope['accepted_schema_sha256'],ACCEPTED_SCHEMA_SHA256,'accepted schema')
  exact(envelope['scope_sha256'],scope_hash(),'scope digest')
  encoded=envelope['synthetic_source_packet_b64'];need(type(encoded) is str and len(encoded)<=524288,'SOURCE_PACKET_BOUND')
  packet_bytes=base64.b64decode(encoded,validate=True)
  need(base64.b64encode(packet_bytes).decode()==encoded,'CANONICAL_BASE64')
  packet=accepted.strict_json(packet_bytes)
  need(type(packet) is dict,'SOURCE_PACKET_OBJECT')
  exact(packet.get('realm'),'SYNTHETIC_ONLY','no runner or target packet transfer')
  result=accepted.assess(packet_bytes)
  need(result['status']!='INDETERMINATE','INHERITED_ENGINE:'+result.get('reason',''))
  for record in packet['records']:
   rows=json.loads(base64.b64decode(record['raw_utf8_b64'],validate=True))
   if record['id']!='registry':
    need(type(rows) is list and len(rows)<=1,'D_ONLY_CANDIDATE_ROW_BOUND')
    family=record['id'].removesuffix('_before').removesuffix('_after')
    if family=='volumes':need(all(r['DriveLetter']=='D:' for r in rows),'NON_D_VOLUME')
    if family in ('settings','usage'):need(all(r['Name'].lower()=='d:\\pagefile.sys' for r in rows),'NON_D_PAGEFILE')
  return {'status':'OFFLINE_SYNTHETIC_VALID_NOT_QUALIFICATION','raw_observations':result['observations'],
    'inherited_observation_status':result['status'],
    'synthetic_source_sha256':hashlib.sha256(packet_bytes).hexdigest(),'scope_sha256':scope_hash(),
    'native_filter_executed':False,'source_gaps':list(GAPS),'external_evidence_status':'EXTERNAL_DEPENDENCY_BLOCKED',
    'can_issue_permit':False,'execution_authorized':False,'target_qualified':False,'GUI_Gate2':'BLOCKED','original_HALT_root_cause':'UNKNOWN','NoAutoNext':True}
 except (Invalid,accepted.Refused,ValueError,UnicodeError,TypeError,KeyError,binascii.Error,RecursionError) as error:
  return {'status':'INDETERMINATE','raw_observations':{},'reason':str(error),'can_issue_permit':False,'execution_authorized':False,'target_qualified':False,'source_gaps':list(GAPS),'GUI_Gate2':'BLOCKED','original_HALT_root_cause':'UNKNOWN','NoAutoNext':True}

def review_external_submissions(raw):
 """Hashes prove supplied bytes only. No root/signature/identity qualification.

 The current submission list is empty. Even present bytes require separately
 appointed independent authority verification. A claimed VERIFIED/PASS field
 is forbidden, so external trust cannot be manufactured by model inputs.
 """
 try:
  rows=strict(raw);need(type(rows) is list and len(rows)<=len(REQUIREMENTS),'SUBMISSION_BOUND')
  seen={}
  for row in rows:
   shape(row,['requirement','artifact_utf8_b64','artifact_sha256','source_authority','status'],'external reference')
   key=row['requirement'];need(type(key) is str and key in REQUIREMENTS and key not in seen,'UNKNOWN_OR_DUPLICATE_REQUIREMENT')
   exact(row['status'],'UNVERIFIED_SUBMISSION','no self qualification')
   authority=row['source_authority'];need(type(authority) is str and 0<len(authority)<=128,'AUTHORITY_LABEL')
   need(type(row['artifact_utf8_b64']) is str and len(row['artifact_utf8_b64'])<=65536,'ARTIFACT_BOUND')
   b=base64.b64decode(row['artifact_utf8_b64'],validate=True);need(0<len(b)<=49152,'ARTIFACT_BYTES')
   need(base64.b64encode(b).decode()==row['artifact_utf8_b64'],'ARTIFACT_BASE64')
   need(type(row['artifact_sha256']) is str and hashlib.sha256(b).hexdigest()==row['artifact_sha256'],'ARTIFACT_SHA256')
   seen[key]='PRESENT_UNQUALIFIED'
  return {'status':'BLOCKED_EXTERNAL_EVIDENCE_REQUIRED','requirements':{k:seen.get(k,'MISSING') for k in REQUIREMENTS},
    'source_gaps':list(GAPS),'can_issue_permit':False,'execution_authorized':False,'independent_external_verification_complete':False,'NoAutoNext':True}
 except (Invalid,ValueError,UnicodeError,TypeError,binascii.Error,RecursionError) as error:
  return {'status':'INDETERMINATE','reason':str(error),'can_issue_permit':False,'execution_authorized':False,'NoAutoNext':True}

def simulate_attempt(events):
 """Pure lifecycle simulation: no actual nonce/intent/file/Permit consumption."""
 if type(events) is not list or len(events)>8:return 'HALT_UNKNOWN_NO_RESUME'
 state='INITIAL'
 mapping={('INITIAL','reserve'):'RESERVED',('RESERVED','intent'):'INTENT_MODELLED',('INTENT_MODELLED','begin'):'OBSERVATION_MODELLED',('OBSERVATION_MODELLED','seal'):'SEALED_MODELLED'}
 for event in events:
  if type(event) is not str:return 'HALT_UNKNOWN_NO_RESUME'
  state=mapping.get((state,event),'HALT_UNKNOWN_NO_RESUME')
 return state
