"""One fresh authenticated Stage-A Normal case. No Stage B or automatic next run."""
import hashlib,os,re,sys,threading,time
from pathlib import Path
import controller as auth,contract,runner_proof as proof,source_integrity as source,transport
SRC=auth.SRC;ROOT=auth.ROOT
EVENTS=frozenset(('PREAUTH_HTTP_START','PREAUTH_HTTP_RESULT','PREAUTH_PASS','PREAUTH_HALT','NATIVE_STAGE_A_INTENT','ABI_LAYOUT','FILE_API_ABI','CONSTRUCTOR_RESOURCE_CLOSE','OWN_JOB_CREATED','JOB_API','RAW_JOB_QUERY','ROOT_BIRTH','WORKER_READY','KNOWN_ROOT_JOB_DOMAIN','PROCESS_API','ROOT_LIVENESS','FILE_OPEN_RESULT','FILE_DESCRIPTOR_HANDLE','FILE_NATIVE_QUERY','FILE_IDENTITY_SNAPSHOT','CANONICAL_FILE_COMPARISON','CANONICAL_FILE_HALT','FILE_CLOSE_RESULT','ROOT_IDENTITY','STAGE_A_SUBGATE_OBSERVED','WORKER_RELEASE','ROOT_WAIT','WORKER_COMPLETE','OWN_JOB_CLEANUP_REQUEST','OWN_JOB_CLEANUP_OBSERVATION','CLEANUP_UNKNOWN','OWN_RESOURCE_CLOSE','HALT','RUN_RESULT'))
EVENTS=EVENTS|frozenset(('AUDIT_CREATEPROCESS','OWN_JOB_CLEANUP_FINAL'))
class Journal:
 def __init__(self,root,head,rid,role):self.root=root;self.head=head;self.rid=rid;self.role=role;self.sequence=0;self.previous=None;self.jobs_created=0;self.children_created=0
 def emit(self,event,data):
  proof.need(event in EVENTS and self.sequence<1024,'FIXED_STAGE_A_EVENT_BOUND');self.sequence+=1
  row={'sequence':self.sequence,'previous_sha256':self.previous,'source_head':self.head,'run_id':self.rid,'attempt':1,'role':self.role,'event':event,'utc_ns':time.time_ns(),'monotonic_ns':time.monotonic_ns(),'data':data}
  raw=auth.canonical(row);proof.need(len(raw)<=65536,'EVENT_BYTES');auth.save(self.root/f'{self.sequence:04d}_{event}.json',row);self.previous=hashlib.sha256(raw).hexdigest()
  if event=='JOB_API' and data['api']=='CreateJobObjectW' and data['ok'] is True and data['already_exists'] is False:self.jobs_created+=1
  if event=='JOB_API' and data['api']=='CreateProcess' and data['ok'] is True:self.children_created+=1
class PhaseTimer:
 def __init__(self,seconds):self.timer=threading.Timer(seconds,self.expire);self.timer.daemon=True
 def start(self):self.timer.start()
 def expire(self):os._exit(124)
 def quiesce(self):
  self.timer.cancel();self.timer.join(1);proof.need(not self.timer.is_alive(),'WATCHDOG_QUIESCENCE_UNKNOWN')
def safe_error(exc):
 if isinstance(exc,(proof.Refused,transport.Rejected,ValueError,RuntimeError)) and re.fullmatch('[A-Z][A-Z0-9_]{0,95}',str(exc) or ''):return str(exc)
 return 'OS_OPERATION_UNKNOWN' if isinstance(exc,OSError) else 'UNEXPECTED_STAGE_A_UNKNOWN'
def native_error(exc):
 value=getattr(exc,'win32_error',getattr(exc,'winerror',None));return value if type(value) is int and -(2**31)<=value<2**32 else None
def cleanup_resources(job,emit):
 cleanup=None;closed=None;errors=[]
 try:
  try:cleanup=job.cleanup()
  except BaseException as exc:
   errors.append('CLEANUP_UNKNOWN')
   try:emit('CLEANUP_UNKNOWN',{'error_code':safe_error(exc),'win32_error':native_error(exc),'not_containment_PASS':True})
   except BaseException:errors.append('CLEANUP_EVIDENCE_UNKNOWN')
 finally:
  try:
   try:closed=job.close()
   except BaseException:closed={'status':'UNKNOWN','resources':[]};errors.append('CLOSE_UNKNOWN')
   if closed['status']!='CLOSED':errors.append('CLOSE_UNKNOWN')
   try:emit('OWN_RESOURCE_CLOSE',closed)
   except BaseException:errors.append('CLOSE_EVIDENCE_UNKNOWN')
  finally:job.proof=None
 if cleanup is not None and not errors:
  try:
   cleanup=job.complete_cleanup(cleanup,closed);emit('OWN_JOB_CLEANUP_FINAL',cleanup)
  except BaseException as exc:
   cleanup=None;errors.append('CLEANUP_FINALIZATION_UNKNOWN')
   try:emit('CLEANUP_UNKNOWN',{'error_code':safe_error(exc),'win32_error':native_error(exc),'not_containment_PASS':True})
   except BaseException:errors.append('CLEANUP_EVIDENCE_UNKNOWN')
 elif cleanup is not None:cleanup=None
 return cleanup,closed,errors
def run(boundary):
 credentials=transport.Credentials.consume_environment();pre_timer=None;native_timer=None;job=None;token=None
 try:
  role,head,rid=auth.validate_context(os.environ,os.name,(sys.implementation.name,sys.version_info[:3]),sys.argv)
  proof.need(os.environ.get('PF002_WORK_ORDER_SHA256')==auth.WORK_ORDER_SHA256,'EXACT_WORK_ORDER_SCOPE_BINDING')
  manifest=source.closed(SRC);manifest_sha=hashlib.sha256((SRC/'SOURCE_MANIFEST_V1.json').read_bytes()).hexdigest();worker_sha=hashlib.sha256((SRC/'normal_worker.py').read_bytes()).hexdigest()
  runner=Path(r'D:\a\_temp');source.physical(runner);root=runner/f'PF002-C04-R3-{rid}-1-{role}';source.physical(root);proof.need(not root.exists(),'ONE_SHOT_ROOT_EXISTS')
  root.mkdir();public=root/'public';public.mkdir();private=root/'normal';private.mkdir();(private/'tmp').mkdir();j=Journal(public,head,rid,role);nonce=os.urandom(32).hex()
  auth.save(public/'ONE_SHOT_INTENT.json',{'source_head':head,'run_id':rid,'attempt':1,'role':role,'nonce':nonce,'realm':'HOSTED_STAGE_A_ROOT_ONLY_NOT_OWNER_CONSENT','work_order_sha256':auth.WORK_ORDER_SHA256,'max_normal_cases':1,'NoRetry':True,'NoResume':True,'NoFallback':True,'NoAutoNext':True})
  auth.save(public/'PREAUTH_DEADLINE_POLICY.json',{'seconds':60,'self_exit_code':124,'partial_is_unknown':True,'must_quiesce_before_native':True,'hard_realtime_claimed':False})
  pre_timer=PhaseTimer(60);pre_timer.start();t=transport.Transport(head,rid,credentials,j.emit);details=None;authenticated=False
  try:
   token,details=auth.authenticate(t,head,rid,role,manifest);authenticated=True;j.emit('PREAUTH_PASS',{'signed_oidc_verified':True,'exact_source_verified':True,'receipt_is_native_authorization':False})
  except BaseException as exc:
   t.halt();j.emit('PREAUTH_HALT',{'reason':safe_error(exc),'native_owned_job_created':False})
  auth.save(public/'PREAUTH_DIAGNOSTIC_RECEIPT.json',auth.receipt(head,rid,role,t.records,authenticated,details));auth.save(public/'SOURCE_MANIFEST.json',manifest)
  pre_timer.quiesce();pre_timer=None
  if not authenticated:
   auth.save(public/'FINAL_HEAD.json',{'source_head':head,'run_id':rid,'attempt':1,'role':role,'journal_head':j.previous,'process_exit_code':1,'owned_jobs':0,'native_children':0,'RS02':'BLOCKED','NoAutoNext':True});return 1
  env=contract.child_environment(os.environ['SystemRoot'],sys.executable,private,manifest_sha,head,rid,role,nonce,credentials)
  proof.need(all(name not in os.environ for name in contract.SECRET_KEYS),'CREDENTIAL_ENV_NOT_CLEARED')
  credentials.destroy();credentials=None;t=None
  j.emit('NATIVE_STAGE_A_INTENT',{'source_head':head,'source_manifest_sha256':manifest_sha,'worker_source_sha256':worker_sha,'work_order_sha256':auth.WORK_ORDER_SHA256,'fixed_executable':sys.executable,'child_environment_keys':sorted(env),'credential_variables_absent':True,'scope':'SINGLE_ROOT_CANONICAL_FILE_IDENTITY_ONLY','NoAutoNext':True})
  boundary.bind_evidence(j.emit);boundary.arm();cleanup=None;closed=None;ready=None;complete=None;before=None;after=None;exit_code=None;native_error_code=None
  try:
   from stage_a import StageAJob
   job=StageAJob(token,env,j.emit,time.monotonic()+10)
   j.emit('OWN_JOB_CREATED',{'job_name':job.job_name,'job_handle':int(job.job),'kill_on_close_configured':True,'active_limit':4,'authorized_domain':'SINGLE_CREATED_ROOT_ONLY','breakaway':False})
   armed=time.monotonic_ns();auth.save(public/'NATIVE_DEADLINE_POLICY.json',{'armed_monotonic_ns':armed,'target_expiry_monotonic_ns':armed+20_000_000_000,'normal_bound_seconds':10,'cleanup_bound_seconds':10,'timer_self_exit_code':124,'job_name':job.job_name,'job_handle':int(job.job),'kill_on_close_already_configured':True,'abrupt_cleanup_outcome':'NOT_OBSERVED_MUST_REMAIN_UNKNOWN','hard_realtime_claimed':False,'no_timer_individual_pid_termination':True})
   native_timer=PhaseTimer(20);native_timer.start()
   birth=job.launch([sys.executable,'-I','-B','-S',str(SRC/'normal_worker.py')],ROOT,env,private,token);j.emit('ROOT_BIRTH',birth)
   job.await_ready(job.end)
   ready=contract.worker_receipt((private/'WORKER_READY.json').read_bytes(),'READY',head,rid,role,nonce,birth['pid'],sys.executable,manifest_sha,worker_sha);j.emit('WORKER_READY',ready)
   before=job.root_identity('ROOT_BEFORE',sys.executable);after=job.root_identity('ROOT_AFTER',sys.executable)
   j.emit('STAGE_A_SUBGATE_OBSERVED',{'canonical_comparator_equal':True,'retained_root_identity_equal':True,'worker_held_during_both_observations':True,'loaded_image_attestation':False,'not_final_run_acceptance':True})
   job.release_worker();j.emit('WORKER_RELEASE',{'root_pid':birth['pid'],'one_byte_fixed_release':'1','nonce':nonce,'sent_once':True})
   wait=job.wait_owned(max(0,job.end-time.monotonic()));j.emit('ROOT_WAIT',{'root_pid':birth['pid'],'root_handle':int(job.hp),'raw_wait':wait});proof.need(wait==0,'ROOT_NORMAL_EXIT_TIMEOUT_UNKNOWN')
   code=job.w.DWORD();ok=job.k.GetExitCodeProcess(job.hp,job.c.byref(code));job.record_api('GetExitCodeProcess',ok,{'handle':int(job.hp),'exit_code':code.value});exit_code=code.value;proof.need(exit_code==0,'ROOT_EXIT_NONZERO')
   complete=contract.worker_receipt((private/'WORKER_COMPLETE.json').read_bytes(),'COMPLETE',head,rid,role,nonce,birth['pid'],sys.executable,manifest_sha,worker_sha);j.emit('WORKER_COMPLETE',complete);job.bounded()
  except BaseException as exc:
   native_error_code=safe_error(exc);j.emit('HALT',{'stage':'NATIVE_STAGE_A','status':'UNKNOWN','error_code':native_error_code,'win32_error':native_error(exc),'NoRetry':True,'NoResume':True,'NoFallback':True})
  finally:
   try:
    if job is not None:
     cleanup,closed,resource_errors=cleanup_resources(job,j.emit)
     if resource_errors:native_error_code=native_error_code or resource_errors[0]
   finally:
    if native_timer is not None:native_timer.quiesce();native_timer=None
  token=None;boundary.stop()
  proof.need(auth.canonical(source.closed(SRC))==auth.canonical(manifest) and hashlib.sha256((SRC/'SOURCE_MANIFEST_V1.json').read_bytes()).hexdigest()==manifest_sha,'POST_NATIVE_SOURCE_CHANGED')
  passed=False
  if native_error_code is None:
   contract.stage_pass(authenticated,ready is not None,before is not None,after is not None,complete is not None,exit_code,cleanup is not None,closed is not None and closed['status']=='CLOSED');passed=True
  result={'version':'PF002_C04_R3_STAGE_A_V1','source_head':head,'run_id':rid,'attempt':1,'role':role,'status':'PASS_STAGE_A_ONLY' if passed else 'HALT_UNKNOWN','native_comparator':'PASS' if passed else 'UNQUALIFIED','root_identity':'PASS' if passed else 'UNQUALIFIED','preauth_completed':authenticated,'worker_ready':ready,'worker_complete':complete,'root_before':before,'root_after':after,'cleanup':cleanup,'resource_close':closed,'error_code':native_error_code,'owned_jobs':1 if job is not None else 0,'native_children':boundary.creations,'StageB_executed':False,'loaded_image_attestation':False,'UnknownMemberOrigin':'UNPROVEN','PF002-C01-OWNERSHIP-001':'OPEN','PF002-CONTAINMENT-001':'OPEN','RS02':'BLOCKED','CompletePF002Runtime':'BLOCKED','OwnerConsent':'NOT_ISSUED','OriginalHostExecution':'NOT_AUTHORIZED','OriginalGUIHALTRootCause':'UNKNOWN','NoAutoNext':True}
  result['owned_jobs']=j.jobs_created if j.jobs_created else (1 if job is not None else None);result['native_children']=max(j.children_created,int(job is not None and hasattr(job,'hp')));result['native_child_creation_attempts']=boundary.creations;result['unassigned_root_cleanup']=getattr(job,'unassigned_root_cleanup',None)
  j.emit('RUN_RESULT',{'status':result['status'],'process_exit_code':0 if passed else 1,'StageB_executed':False,'RS02':'BLOCKED'});result['journal_head']=j.previous
  auth.save(public/'STAGE_A_RESULT.json',result);auth.save(public/'FINAL_HEAD.json',{'source_head':head,'run_id':rid,'attempt':1,'role':role,'journal_head':j.previous,'process_exit_code':0 if passed else 1,'stage_a_result_sha256':hashlib.sha256((public/'STAGE_A_RESULT.json').read_bytes()).hexdigest(),'owned_jobs':result['owned_jobs'],'native_children':result['native_children'],'StageB_executed':False,'RS02':'BLOCKED','NoAutoNext':True})
  return 0 if passed else 1
 finally:
  if pre_timer is not None:pre_timer.quiesce()
  if native_timer is not None:native_timer.quiesce()
  if credentials is not None:credentials.destroy()
  token=None
