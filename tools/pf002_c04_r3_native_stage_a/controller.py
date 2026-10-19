"""Fresh authenticated Hosted Runner -> one fixed Native Stage A -> STOP."""
import hashlib,json,os,re,sys,threading,time,subprocess
from pathlib import Path
SRC=Path(__file__).resolve().parent;ROOT=SRC.parent.parent
sys.path.insert(0,str(SRC))
import runner_proof as proof,source_integrity as source,transport,contract
from invocation_boundary import Boundary
WORK_ORDER_SHA256='ccd6fd3dfa277f5880df4e21a810d4bbce6b1dd14efe016f971d67a73b9a3c5d'
def canonical(v):return json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()+b'\n'

def save(path,value):
 raw=canonical(value)
 with path.open('xb') as f:f.write(raw);f.flush();os.fsync(f.fileno())

def validate_context(env,name,version,argv):
 fixed={'GITHUB_ACTIONS':'true','RUNNER_ENVIRONMENT':'github-hosted','RUNNER_OS':'Windows','GITHUB_REPOSITORY':proof.REPO,'GITHUB_REF':proof.REF,'PF002_C04_R3_PROFILE':'SIGNED_HOSTED_NATIVE_STAGE_A'}
 proof.need(len(argv)==1 and all(env.get(k)==v for k,v in fixed.items()),'HOSTED_STAGE_A_CONTEXT')
 proof.need(name=='nt' and version==('cpython',(3,12,10)),'REVIEWED_WINDOWS_CPYTHON_31210_ONLY')
 role=env.get('PF002_ROLE');head=env.get('GITHUB_SHA');rid=env.get('GITHUB_RUN_ID')
 proof.need(role in ('qualification','reproduction') and type(head) is str and re.fullmatch('[0-9a-f]{40}',head) and type(rid) is str and re.fullmatch('[1-9][0-9]{0,19}',rid) and env.get('GITHUB_RUN_ATTEMPT')=='1','FRESH_EXACT_RUN_ROLE')
 proof.need(env.get('RUNNER_TEMP')==r'D:\a\_temp','FIXED_EVIDENCE_ROOT')
 return role,head,rid

def authenticate(t,head,rid,role,manifest,root=ROOT,now=None):
 try:return _authenticate(t,head,rid,role,manifest,root,now)
 except BaseException:
  t.halt()
  raise

def _authenticate(t,head,rid,role,manifest,root=ROOT,now=None):
 response=t.fetch('OIDC_TOKEN');proof.need(type(response) is dict and set(response)=={'value'},'OIDC_RESPONSE_SCHEMA')
 token=response['value']
 claims=proof.verify_token(token,(root/'tools/pf002_c04_r3_native_stage_a/GITHUB_OIDC_JWKS_PINNED.json').read_bytes(),int(time.time()) if now is None else now,head,rid,'1')
 # The signed token is not the GitHub API credential and is never exported.
 response=None
 run=t.fetch('RUN_RECORD');source.run_record(run,head,rid,role)
 ref=t.fetch('PR87_BASE_REF')
 proof.need(type(ref) is dict and ref.get('ref')=='refs/heads/'+transport.BASE_BRANCH and type(ref.get('object')) is dict and ref['object'].get('type')=='commit' and ref['object'].get('sha')==transport.BASE,'STACKED_BASE_BINDING')
 current=t.fetch('CURRENT_TREE');prior=t.fetch('PR87_TREE')
 integrity=source.verify_trees(current,prior,root,manifest)
 proof.need(t.state=='COMPLETE' and len(t.records)==5 and time.monotonic()<t.deadline,'PREAUTH_COMPLETE_DEADLINE')
 return token,{'claims':claims,'source_integrity':integrity,'signed_oidc_verified':True,'api_read_credential_used':True,'api_credential_is_oidc':False}

def receipt(head,rid,role,records,authenticated,details):
 proof.need(type(authenticated) is bool and type(records) is list and len(records)<=5,'RECEIPT_SCHEMA')
 proof.need(type(head) is str and re.fullmatch('[0-9a-f]{40}',head) and type(rid) is str and re.fullmatch('[1-9][0-9]{0,19}',rid) and role in ('qualification','reproduction'),'RECEIPT_CONTEXT')
 keys={'fixed_request_stage','endpoint_host','fixed_path_id','http_status','safe_error_category','outcome',*transport.HEADER_FIELDS.values()}
 for i,row in enumerate(records):
  proof.need(type(row) is dict and set(row)==keys and row['fixed_request_stage']==transport.STAGES[i] and row['fixed_path_id']==transport.STAGES[i]+'_FIXED_ENDPOINT','RECEIPT_REQUEST_SCHEMA')
  proof.need(type(row['endpoint_host']) is str and (re.fullmatch('[a-z0-9.-]{1,253}',row['endpoint_host']) and row['endpoint_host'].endswith('.actions.githubusercontent.com') if i==0 else row['endpoint_host']=='api.github.com'),'RECEIPT_HOST')
  proof.need(row['http_status'] is None or type(row['http_status']) is int and 100<=row['http_status']<=599,'RECEIPT_HTTP_STATUS')
  allowed={'RESPONSE_PARSED_NOT_AUTHORIZATION','INVALID_DIAGNOSTIC_HEADERS','PRIMARY_RATE_LIMIT_HEADER_EVIDENCE','AUTHENTICATION_REJECTED','ACCESS_OR_POLICY_REJECTED_UNDETERMINED','RATE_LIMIT_STATUS_CAUSE_UNDETERMINED','HTTP_STATUS_ERROR','HTTP_STATUS_OR_REDIRECT','RESPONSE_BYTE_BOUND','PREAUTH_DEADLINE','REDIRECT_FORBIDDEN','REQUEST_REJECTED','RESPONSE_JSON_REJECTED','BOUNDED_TRANSPORT_ERROR','UNEXPECTED_TRANSPORT_ERROR','SECRET_REFLECTION_BLOCKED'}
  proof.need(row['safe_error_category'] in allowed and row['outcome'] in ('HALT','RESPONSE_PARSED_NOT_AUTHORIZATION'),'RECEIPT_ENUM')
  for key in transport.HEADER_FIELDS.values():
   value=row[key];pattern='[A-Za-z0-9:-]{1,128}' if key=='github_request_id' else '(0|[1-9][0-9]{0,11})'
   proof.need(value is None or type(value) is str and re.fullmatch(pattern,value),'RECEIPT_HEADER')
  proof.need(row['outcome']!='HALT' or i==len(records)-1,'RECEIPT_AFTER_HALT')
 if authenticated:
  proof.need(len(records)==5 and all(r['http_status']==200 and r['outcome']=='RESPONSE_PARSED_NOT_AUTHORIZATION' and r['safe_error_category']=='RESPONSE_PARSED_NOT_AUTHORIZATION' for r in records),'RECEIPT_INCOMPLETE_AUTHENTICATION')
  proof.need(type(details) is dict and set(details)=={'claims','source_integrity','signed_oidc_verified','api_read_credential_used','api_credential_is_oidc'} and details['signed_oidc_verified'] is True and details['api_read_credential_used'] is True and details['api_credential_is_oidc'] is False,'RECEIPT_VERIFICATION')
  fixed={'iss':proof.ISS,'aud':proof.AUD,'repository':proof.REPO,'repository_id':'1370145728','repository_owner_id':'325481386','ref':proof.REF,'event_name':'workflow_dispatch','runner_environment':'github-hosted','workflow_ref':proof.WORKFLOW,'sha':head,'workflow_sha':head,'run_id':rid,'run_attempt':'1'}
  proof.need(details['claims']==fixed,'RECEIPT_CLAIMS')
  integrity=details['source_integrity'];proof.need(type(integrity) is dict and set(integrity)=={'base_files','new_files','current_files','base_unchanged','exact_blob_integrity'} and type(integrity['base_files']) is int and integrity['base_files']==748 and type(integrity['new_files']) is int and 0<integrity['new_files']<=32 and type(integrity['current_files']) is int and integrity['current_files']==748+integrity['new_files'] and integrity['base_unchanged'] is True and integrity['exact_blob_integrity'] is True,'RECEIPT_INTEGRITY')
 else:proof.need(details is None,'RECEIPT_NO_UNVERIFIED_DETAILS')
 return {'version':'PF002_C04_R3_PREAUTH_ONLY_V1','source_head':head,'run_id':rid,'attempt':1,'role':role,'workflow':source.WORKFLOW,'requests':records,'authentication_completed':authenticated,'outcome':'PREAUTH_ONLY_PASS' if authenticated else 'HALT','verification':details if authenticated else None,'native_dispatches':0,'owned_jobs':0,'native_child_processes':0,'original_host_queries':0,'owner_consent_issued':False,'receipt_is_execution_authorization':False,'native_comparator':'NOT_QUALIFIED','UnknownMemberOrigin':'UNPROVEN','RS02':'BLOCKED','retry':False,'resume':False,'fallback':False,'NoAutoNext':True}
