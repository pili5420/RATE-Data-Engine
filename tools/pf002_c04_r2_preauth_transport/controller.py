"""Hosted PREAUTH-ONLY. There is deliberately no Job/worker/native successor path."""
import hashlib,json,os,re,sys,threading,time
from pathlib import Path
SRC=Path(__file__).resolve().parent;ROOT=SRC.parent.parent
sys.path.insert(0,str(SRC))
import runner_proof as proof
import source_integrity as source
import transport

def canonical(v):return json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()+b'\n'
def save(path,value):
 raw=canonical(value)
 with path.open('xb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
class Journal:
 def __init__(self,root,head,rid,role):self.root=root;self.head=head;self.rid=rid;self.role=role;self.sequence=0;self.previous=None
 def emit(self,event,data):
  proof.need(event in ('PREAUTH_HTTP_START','PREAUTH_HTTP_RESULT','PREAUTH_PASS','PREAUTH_HALT'),'EVENT_ENUM')
  self.sequence+=1;proof.need(self.sequence<=11,'EVENT_BOUND')
  v={'sequence':self.sequence,'previous_sha256':self.previous,'source_head':self.head,'run_id':self.rid,'attempt':1,'role':self.role,'event':event,'utc_ns':time.time_ns(),'monotonic_ns':time.monotonic_ns(),'data':data}
  raw=canonical(v);proof.need(len(raw)<=16384,'EVENT_BYTES')
  save(self.root/f'{self.sequence:04d}_{event}.json',v);self.previous=hashlib.sha256(raw).hexdigest()

def validate_context(env,name,version,argv):
 fixed={'GITHUB_ACTIONS':'true','RUNNER_ENVIRONMENT':'github-hosted','RUNNER_OS':'Windows','GITHUB_REPOSITORY':proof.REPO,'GITHUB_REF':proof.REF,'PF002_C04_R2_PROFILE':'SIGNED_HOSTED_PREAUTH_ONLY'}
 proof.need(len(argv)==1 and all(env.get(k)==v for k,v in fixed.items()),'HOSTED_PREAUTH_ONLY_CONTEXT')
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
 claims=proof.verify_token(token,(root/'tools/pf002_c04_r2_preauth_transport/GITHUB_OIDC_JWKS_PINNED.json').read_bytes(),int(time.time()) if now is None else now,head,rid,'1')
 # The signed token is not the GitHub API credential and is never exported.
 token=None;response=None
 run=t.fetch('RUN_RECORD');source.run_record(run,head,rid,role)
 ref=t.fetch('PR86_BASE_REF')
 proof.need(type(ref) is dict and ref.get('ref')=='refs/heads/'+transport.BASE_BRANCH and type(ref.get('object')) is dict and ref['object'].get('type')=='commit' and ref['object'].get('sha')==transport.BASE,'STACKED_BASE_BINDING')
 current=t.fetch('CURRENT_TREE');prior=t.fetch('PR86_TREE')
 integrity=source.verify_trees(current,prior,root,manifest)
 proof.need(t.state=='COMPLETE' and len(t.records)==5 and time.monotonic()<t.deadline,'PREAUTH_COMPLETE_DEADLINE')
 return {'claims':claims,'source_integrity':integrity,'signed_oidc_verified':True,'api_read_credential_used':True,'api_credential_is_oidc':False}

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
  integrity=details['source_integrity'];proof.need(type(integrity) is dict and set(integrity)=={'base_files','new_files','current_files','base_unchanged','exact_blob_integrity'} and type(integrity['base_files']) is int and integrity['base_files']==735 and type(integrity['new_files']) is int and 0<integrity['new_files']<=32 and type(integrity['current_files']) is int and integrity['current_files']==735+integrity['new_files'] and integrity['base_unchanged'] is True and integrity['exact_blob_integrity'] is True,'RECEIPT_INTEGRITY')
 else:proof.need(details is None,'RECEIPT_NO_UNVERIFIED_DETAILS')
 return {'version':'PF002_C04_R2_PREAUTH_ONLY_V1','source_head':head,'run_id':rid,'attempt':1,'role':role,'workflow':source.WORKFLOW,'requests':records,'authentication_completed':authenticated,'outcome':'PREAUTH_ONLY_PASS' if authenticated else 'HALT','verification':details if authenticated else None,'native_dispatches':0,'owned_jobs':0,'native_child_processes':0,'original_host_queries':0,'owner_consent_issued':False,'receipt_is_execution_authorization':False,'native_comparator':'NOT_QUALIFIED','UnknownMemberOrigin':'UNPROVEN','RS02':'BLOCKED','retry':False,'resume':False,'fallback':False,'NoAutoNext':True}

class DeadlineGuard:
 """Independent self-exit timer; OS/GIL scheduling is not a hard real-time promise."""
 def __init__(self):
  self.timer=threading.Timer(60,self.expire);self.timer.daemon=True
 def start(self):self.timer.start()
 def cancel(self):self.timer.cancel()
 def expire(self):os._exit(124)

def run():
 credentials=None;t=None;watchdog=None
 try:
  credentials=transport.Credentials.consume_environment()
  role,head,rid=validate_context(os.environ,os.name,(sys.implementation.name,sys.version_info[:3]),sys.argv)
  manifest=source.closed(SRC)
  runner=Path(r'D:\a\_temp');source.physical(runner)
  root=runner/f'PF002-C04-R2-{rid}-1-{role}';source.physical(root)
  proof.need(not root.exists(),'ONE_SHOT_ROOT_EXISTS')
  root.mkdir();public=root/'public';public.mkdir();j=Journal(public,head,rid,role)
  save(public/'ONE_SHOT_INTENT.json',{'source_head':head,'run_id':rid,'attempt':1,'role':role,'nonce':os.urandom(32).hex(),'realm':'PREAUTH_ONLY_NOT_NATIVE_AUTHORITY','NoRetry':True,'NoResume':True,'NoFallback':True})
  armed=time.monotonic_ns()
  save(public/'DEADLINE_POLICY.json',{'source_head':head,'run_id':rid,'attempt':1,'role':role,'armed_monotonic_ns':armed,'target_expiry_monotonic_ns':armed+60_000_000_000,'self_exit_code':124,'scheduling_is_not_hard_realtime':True,'partial_evidence_is_unknown':True,'complete_receipt_not_guaranteed_after_abrupt_exit':True,'retry':False,'NoAutoNext':True})
  watchdog=DeadlineGuard();watchdog.start()
  authenticated=False;details=None
  try:
   t=transport.Transport(head,rid,credentials,j.emit)
   details=authenticate(t,head,rid,role,manifest)
   authenticated=True
   j.emit('PREAUTH_PASS',{'signed_oidc_verified':True,'exact_source_verified':True,'native_authorization':False})
  except Exception:
   if t is not None:t.halt()
   j.emit('PREAUTH_HALT',{'reason':'PREAUTHORIZATION_HALTED','native_owned_job_created':False,'receipt_is_execution_authorization':False})
  save(public/'PREAUTH_DIAGNOSTIC_RECEIPT.json',receipt(head,rid,role,t.records if t else [],authenticated,details))
  save(public/'SOURCE_MANIFEST.json',manifest)
  save(public/'FINAL_HEAD.json',{'source_head':head,'run_id':rid,'attempt':1,'role':role,'journal_head':j.previous,'process_exit_code':0 if authenticated else 1,'historical_http403_root_cause':'UNPROVEN','native_dispatches':0,'owned_jobs':0,'NoAutoNext':True})
  return 0 if authenticated else 1
 finally:
  if watchdog is not None:watchdog.cancel()
  if credentials is not None:credentials.destroy()

def runtime_audit(event,args):
 if event.startswith(('ctypes.','subprocess.','os.spawn','winreg.')) or event=='os.system':raise PermissionError('PREAUTH_ONLY_NO_NATIVE_OR_CHILD')

if __name__=='__main__':
 sys.addaudithook(runtime_audit)
 try:code=run()
 except BaseException:code=1
 # No traceback, exception text, response body, environment or credential is printed.
 print('PF002_C04_R2_PREAUTH_ONLY_PASS' if code==0 else 'PF002_C04_R2_HALTED')
 raise SystemExit(code)
