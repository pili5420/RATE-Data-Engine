"""C04 signed hosted-runner OWNED PROCESS ONLY entry. No CIM/Registry/GUI dispatch."""
import hashlib,json,os,re,sys,time,urllib.parse,urllib.request
from pathlib import Path
SRC=Path(__file__).resolve().parent;ROOT=SRC.parent.parent
_m=json.loads((SRC/'SOURCE_MANIFEST_V1.json').read_bytes());_raw=(SRC/'source_loader.py').read_bytes()
if _m['files']['source_loader.py']!={'bytes':len(_raw),'sha256':hashlib.sha256(_raw).hexdigest()}:raise ValueError('BOOTSTRAP_SOURCE_HASH')
_ns={'__file__':str(SRC/'source_loader.py')};exec(compile(_raw,str(SRC/'source_loader.py'),'exec',dont_inherit=True),_ns)
loader=_ns['Loader'](SRC);proof=loader.load('runner_proof');model=loader.load('model');canonical_file=loader.load('canonical_file')
def canonical(v):return json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()+b'\n'
http=loader.load('http_evidence')

def sources():
 manifest=proof.strict((SRC/'SOURCE_MANIFEST_V1.json').read_bytes())
 actual={p.name for p in SRC.iterdir()}
 proof.need(actual==set(manifest['files'])|{'SOURCE_MANIFEST_V1.json'},'EXACT_SOURCE_DIRECTORY')
 for n,row in manifest['files'].items():
  p=SRC/n
  proof.need(p.is_file() and not p.is_symlink() and not(getattr(p.stat(),'st_file_attributes',0)&0x400),'SOURCE_REPARSE')
  b=p.read_bytes();proof.need(row=={'sha256':hashlib.sha256(b).hexdigest(),'bytes':len(b)},'SOURCE_HASH')
 return manifest
def authenticate(transport):
 proof.need(len(sys.argv)==1,'NO_OWNER_CONSENT_OR_COMMAND_ARGUMENTS')
 fixed={'GITHUB_ACTIONS':'true','RUNNER_ENVIRONMENT':'github-hosted','RUNNER_OS':'Windows',
        'GITHUB_REPOSITORY':proof.REPO,'GITHUB_REF':proof.REF,'PF002_C04_R1_PROFILE':'SIGNED_HOSTED_RUNNER_JOB_FORENSICS_ONLY'}
 for k,v in fixed.items():proof.need(os.environ.get(k)==v,'HOSTED_RUNNER_CONTEXT')
 proof.need(os.name=='nt' and sys.implementation.name=='cpython' and sys.version_info[:3]==(3,12,10),'REVIEWED_WINDOWS_CPYTHON_31210_ONLY')
 role=os.environ.get('PF002_ROLE');proof.need(role in ('qualification','reproduction'),'EXACT_JOB_ROLE')
 head=os.environ.get('GITHUB_SHA','');rid=os.environ.get('GITHUB_RUN_ID','');attempt=os.environ.get('GITHUB_RUN_ATTEMPT','')
 proof.need(re.fullmatch('[0-9a-f]{40}',head) is not None and rid.isascii() and rid.isdigit() and attempt=='1','EXACT_FRESH_RUN')
 url=os.environ.get('ACTIONS_ID_TOKEN_REQUEST_URL','');u=urllib.parse.urlparse(url)
 proof.need(u.scheme=='https' and type(u.hostname) is str and u.hostname.endswith('.actions.githubusercontent.com') and u.port in (None,443) and not u.username and not u.fragment,'GITHUB_TOKEN_ENDPOINT')
 url+=('&' if '?' in url else '?')+'audience='+proof.AUD
 token_response=transport.fetch('OIDC_TOKEN',url,{'Authorization':'bearer '+os.environ.get('ACTIONS_ID_TOKEN_REQUEST_TOKEN','')},32768)
 token=token_response.get('value');claims=proof.verify_token(token,(SRC/'GITHUB_OIDC_JWKS_PINNED.json').read_bytes(),int(time.time()),head,rid,attempt)
 # Public official API metadata only; no GitHub bearer is inherited or needed here.
 run=transport.fetch('RUN_RECORD','https://api.github.com/repos/'+proof.REPO+'/actions/runs/'+rid,{'Accept':'application/vnd.github+json','User-Agent':'RATE-PF002-runner-engineering'})
 proof.need(run['head_sha']==head and run['head_branch']==proof.BRANCH and run['event']=='workflow_dispatch' and run['display_title']=='PF002-C04-R1 '+role and run['run_attempt']==1 and run['path']=='.github/workflows/rate_pf002_c04_r1_contract.yml','OFFICIAL_RUN_HEAD_WORKFLOW')
 proof.need(run['repository']['id']==1370145728,'OFFICIAL_REPOSITORY_ID')
 accepted=transport.fetch('PR85_BASE_REF','https://api.github.com/repos/'+proof.REPO+'/git/ref/heads/codex/pf002-c04-image-identity-semantic-v1')
 proof.need(accepted['object']['sha']=='c1280a3eed0610dc0ba9946c4ec628e919f15ee2','STACKED_BASE_MOVED_HALT')
 current=transport.fetch('CURRENT_TREE','https://api.github.com/repos/'+proof.REPO+'/git/trees/'+head+'?recursive=1')
 prior=transport.fetch('PR85_TREE','https://api.github.com/repos/'+proof.REPO+'/git/trees/c1280a3eed0610dc0ba9946c4ec628e919f15ee2?recursive=1')
 proof.need(not current['truncated'] and not prior['truncated'],'SOURCE_TREE_BOUND')
 ct={r['path']:r for r in current['tree'] if r['type']=='blob'};pt={r['path']:r for r in prior['tree'] if r['type']=='blob'}
 modified={n for n in pt if n in ct and (ct[n]['sha']!=pt[n]['sha'] or ct[n]['mode']!=pt[n]['mode'])}
 allowed_modified={'tools/pf002_c02_job_member_provenance/'+n for n in ('probe.py','test_forensics.py','SOURCE_MANIFEST_V1.json')}|{'tools/pf002_c03_forensic_evidence/'+n for n in ('file_evidence.py','test_evidence.py','SOURCE_MANIFEST_V1.json')}
 proof.need(len(pt)==719 and set(pt)<=set(ct) and modified==allowed_modified and all(ct[n]['mode']==pt[n]['mode'] for n in modified),'EXACT_SIX_LEGACY_CONTRACT_FILES_ONLY')
 names=set(ct)-set(pt)
 proof.need(all(n.startswith('tools/pf002_c04_r1_legacy_contract/') or n=='.github/workflows/rate_pf002_c04_r1_contract.yml' for n in names),'ISOLATED_R1_SOURCE_ONLY')
 for name in names|modified:
  b=(ROOT/name).read_bytes();oid=hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()
  proof.need(oid==ct[name]['sha'],'REMOTE_EXACT_SOURCE_BLOB')
 sources()
 return token,claims,role,head,rid,attempt
def physical(path):
 proof.need(path.is_absolute() and path==path.resolve(),'PHYSICAL_PATH_ALIAS')
 for p in (path,*path.parents):
  if p.exists():proof.need(not p.is_symlink() and not(getattr(p.lstat(),'st_file_attributes',0)&0x400),'REPARSE_ROOT')
def save(path,value):
 b=canonical(value)
 with path.open('xb') as f:f.write(b);f.flush();os.fsync(f.fileno())

def environment(private,role,head,rid,runner):
 env={k:os.environ[k] for k in ('PATH','SystemRoot','SYSTEMROOT','WINDIR','TEMP','TMP') if k in os.environ}
 env.update(PF002_PRIVATE_ROOT=str(private),PF002_ROLE=role,PF002_HEAD=head,PF002_RUN_ID=rid,PF002_RUN_ATTEMPT='1',PF002_RUNNER_ROOT=str(runner),PYTHONDONTWRITEBYTECODE='1')
 return env
class Journal:
 def __init__(self,root,case,head,role,runid):self.root=root;self.context={'case':case,'head':head,'role':role,'run_id':runid};self.seq=0;self.prev=None
 def emit(self,event,data):
  proof.need(self.seq<8192 and re.fullmatch('[A-Z_]{1,64}',event) is not None,'EVIDENCE_EVENT_BOUND')
  self.seq+=1;v={'sequence':self.seq,'previous_sha256':self.prev,**self.context,'event':event,'utc_ns':time.time_ns(),'monotonic_ns':time.monotonic_ns(),'data':data}
  b=canonical(v)
  proof.need(len(b)<=65536,'EVIDENCE_RECORD_BOUND')
  with (self.root/f'{self.seq:04d}_{event}.json').open('xb') as f:f.write(b);f.flush();os.fsync(f.fileno())
  self.prev=hashlib.sha256(b).hexdigest()

def preauth_context():
 proof.need(len(sys.argv)==1,'NO_OWNER_CONSENT_OR_COMMAND_ARGUMENTS')
 for k,v in {'GITHUB_ACTIONS':'true','RUNNER_ENVIRONMENT':'github-hosted','RUNNER_OS':'Windows','GITHUB_REPOSITORY':proof.REPO,'GITHUB_REF':proof.REF,'PF002_C04_R1_PROFILE':'SIGNED_HOSTED_RUNNER_JOB_FORENSICS_ONLY'}.items():proof.need(os.environ.get(k)==v,'HOSTED_RUNNER_CONTEXT')
 proof.need(os.name=='nt' and sys.implementation.name=='cpython' and sys.version_info[:3]==(3,12,10),'REVIEWED_WINDOWS_CPYTHON_31210_ONLY')
 role=os.environ.get('PF002_ROLE');head=os.environ.get('GITHUB_SHA','');rid=os.environ.get('GITHUB_RUN_ID','')
 proof.need(role in ('qualification','reproduction') and re.fullmatch('[0-9a-f]{40}',head) and rid.isascii() and rid.isdigit() and os.environ.get('GITHUB_RUN_ATTEMPT')=='1','EXACT_FRESH_RUN')
 runner=Path(r'D:\a\_temp');proof.need(os.environ.get('RUNNER_TEMP')==str(runner),'FIXED_HOSTED_RECEIPT_ROOT')
 physical(runner);sources()
 return runner,role,head,rid

def safe_halt(exc):
 allowed={'IMAGE_DISK_IDENTITY_CHANGED','IMAGE_METADATA_TYPE','DURABLE_IMAGE_EVIDENCE_REQUIRED','IMAGE_DEADLINE','IMAGE_SIZE_BOUND','IMAGE_TRUNCATED','LOCAL_PHYSICAL_IMAGE_ONLY','IMAGE_DRIVE_NOT_FIXED','IMAGE_REPARSE','NORMAL_FORENSICS_DEADLINE','PROCESS_API_UNKNOWN','PID_NOT_THIS_OWN_JOB','PID_HANDLE_MISMATCH','PROCESS_IDENTITY_CHANGED','PBI_QUERY_UNKNOWN_NO_RIGHTS_FALLBACK','PBI_PID_MISMATCH','MEMBER_WAIT_UNKNOWN','NORMAL_ROOT_TIMEOUT_UNKNOWN','NORMAL_ROOT_EXIT_UNKNOWN','PID_REUSE_OR_NOT_OWN_JOB'}
 if isinstance(exc,model.Unknown) and str(exc) in allowed|canonical_file.ERROR_CODES:return str(exc)
 if isinstance(exc,OSError):return 'OS_OPERATION_UNKNOWN'
 if isinstance(exc,proof.Refused):return 'AUTHORIZATION_OR_BOUNDARY_REJECTED'
 return 'UNEXPECTED_OPERATION_UNKNOWN'

def safe_native_error(exc):
 value=getattr(exc,'win32_error',getattr(exc,'winerror',None))
 return value if type(value) is int and -(2**31)<=value<2**32 else None

def run():
 runner,role,head,rid=preauth_context();attempt='1'
 root=runner/('PF002-C04-R1-'+rid+'-1-'+role);physical(root);proof.need(not root.exists(),'ONE_SHOT_ROOT_EXISTS')
 nonce=os.urandom(32).hex();save(runner/(root.name+'.intent'),{'head':head,'role':role,'run_id':rid,'nonce':nonce,'realm':'OWN_JOB_MEMBER_FORENSICS_ONLY_NOT_OWNER_CONSENT'})
 root.mkdir();public=root/'public';public.mkdir();private=root/'normal';private.mkdir();j=Journal(public,'normal',head,role,rid);job=None
 transport=http.Transport(head,rid,j.emit);authenticated=False
 try:
  token,claims,actual_role,actual_head,actual_rid,actual_attempt=authenticate(transport)
  proof.need((role,head,rid,attempt)==(actual_role,actual_head,actual_rid,actual_attempt),'AUTH_CONTEXT_CHANGED')
  authenticated=True
 except Exception:
  j.emit('PREAUTH_HALT',{'fail_closed_reason':'PREAUTHORIZATION_HALTED','native_owned_job_created':False,'receipt_is_execution_authorization':False})
  save(public/'PREAUTH_DIAGNOSTIC_RECEIPT.json',http.receipt(head,role,rid,transport.records,False,True))
  save(public/'FINAL_HEAD.json',{'head':head,'role':role,'journal_head':j.prev,'process_exit_code':1,'root_cause':'UNPROVEN','owner_consent_issued':False,'RS02':'BLOCKED','NoAutoNext':True})
  return 1
 save(public/'PREAUTH_DIAGNOSTIC_RECEIPT.json',http.receipt(head,role,rid,transport.records,True,False))
 image_os=os.environ.get('ImageOS','');image_version=os.environ.get('ImageVersion','');proof.need(re.fullmatch('[A-Za-z0-9-]{1,32}',image_os) and re.fullmatch('[0-9.]{1,48}',image_version),'IMAGE_IDENTITY')
 save(public/'PROVENANCE.json',{'head':head,'base':'c1280a3eed0610dc0ba9946c4ec628e919f15ee2','role':role,'claims':claims,'python_version':'.'.join(map(str,sys.version_info[:3])),'python_executable':sys.executable,'base_executable':sys._base_executable,'runner_image_os':image_os,'runner_image_version':image_version,'source_manifest_sha256':hashlib.sha256((SRC/'SOURCE_MANIFEST_V1.json').read_bytes()).hexdigest(),'source_CIM_registry_reads':0,'original_host_queries':0,'owner_consent_issued':False,'NoAutoNext':True})
 save(public/'SOURCE_MANIFEST.json',sources());j.emit('NORMAL_FORENSICS_INTENT',{'nonce':nonce,'normal_cases':1,'NoRetry':True,'NoResume':True,'normal_bound_seconds':10,'cleanup_bound_seconds':10,'unknown_pid_termination':False})
 try:
  loader.load('job');loader.load('file_evidence');native=loader.load('probe');env=environment(private,role,head,rid,runner);env['C04_R1_NONCE']=nonce
  end=time.monotonic()+10;job=native.Probe(token,env,j.emit,end)
  j.emit('OWN_JOB_CREATED',{'job_name':job.job_name,'job_handle':int(job.job),'accounting':job.query(1),'ids':job.query(3),'kill_on_close':True,'active_limit':4,'breakaway':False})
  birth=job.launch([sys.executable,'-I','-B','-S',str(SRC/'normal_worker.py')],ROOT,env,private,token);j.emit('ROOT_BIRTH',birth)
  stage_a=job.qualify_root_image();j.emit('STAGE_A_ROOT_IMAGE_PASS',{'root_identity':stage_a,'native_comparator':'PASS','root_image_identity':'PASS','loaded_image_attestation':False,'NoAutoNext':True})
  save(public/'STAGE_A_RESULT.json',{'head':head,'role':role,'native_comparator':'PASS','root_image_identity':'PASS','root_identity':stage_a,'journal_head':j.prev,'loaded_image_attestation':False,'RS02':'BLOCKED','NoAutoNext':True})
  pre=job.observe('AFTER_RESUME_BEFORE_WAIT')
  wait=job.wait_owned(max(0,end-time.monotonic()));j.emit('ROOT_WAIT',{'pid':birth['pid'],'handle':birth['root_handle'],'raw_result':wait});proof.need(wait==0,'NORMAL_ROOT_TIMEOUT_UNKNOWN')
  post=job.observe('AFTER_ROOT_WAIT');original=job.root_identity();proof.need(original['wait_result']==0 and original['exit_code']==0,'NORMAL_ROOT_EXIT_UNKNOWN')
  receipt=proof.strict((private/'WORKER_RECEIPT.json').read_bytes(),16384)
  required={'head','role','run_id','launch_nonce','pid','parent_pid','executable','base_executable','worker_source_sha256','self_parent_source','NoAutoNext'}
  proof.need(type(receipt) is dict and set(receipt)==required and receipt['head']==head and receipt['role']==role and receipt['run_id']==rid and receipt['launch_nonce']==nonce and receipt['worker_source_sha256']==hashlib.sha256((SRC/'normal_worker.py').read_bytes()).hexdigest() and receipt['NoAutoNext'] is True,'WORKER_RECEIPT_BINDING')
  proof.need(type(receipt['pid']) is int and receipt['pid'] in ({stage_a['pid']}|{m['pid'] for o in (pre,post) for m in o['members']}) and receipt['self_parent_source']=='CPYTHON_3_12_10_CURRENT_PROCESS_PSS_NONE','WORKER_NOT_OBSERVED_MEMBER')
  j.emit('CONTROLLED_WORKER_RECEIPT',receipt);decision=model.classify(original,receipt,[pre,post]);job.bounded()
  j.emit('FORENSICS_DECISION',decision);save(public/'DECISION.json',{'head':head,'role':role,**decision,'journal_head':j.prev,'NoAutoNext':True})
  outcome=0 if decision['origin_evidence_complete_candidate'] else 1
 except Exception as exc:
  code=safe_halt(exc)
  j.emit('HALT',{'status':'UNKNOWN','error_code':code,'win32_error':safe_native_error(exc),'NoRetry':True,'NoResume':True})
  save(public/'HALT.json',{'head':head,'role':role,'error_code':code,'root_cause':'UNPROVEN','journal_head':j.prev,'RS02':'BLOCKED','NoAutoNext':True});outcome=1
 finally:
  if job is not None:
   try:job.cleanup()
   except Exception as exc:j.emit('CLEANUP_UNKNOWN',{'error_code':safe_halt(exc),'win32_error':safe_native_error(exc),'cleanup_not_containment_PASS':True});outcome=1
   closed=job.close();j.emit('OWN_RESOURCE_CLOSE',closed)
   if closed['status']!='CLOSED':outcome=1
  save(public/'FINAL_HEAD.json',{'head':head,'role':role,'journal_head':j.prev,'process_exit_code':outcome,'owner_consent_issued':False,'RS02':'BLOCKED','native_comparator':'PASS' if job is not None and job.stage_a_passed else 'UNKNOWN','root_image_identity':'PASS' if job is not None and job.stage_a_passed else 'UNKNOWN','NoAutoNext':True})
 return outcome
if __name__=='__main__':
 try:raise SystemExit(run())
 except Exception as exc:print('HALT_C04_BOUNDARY_UNRELIABLE_PRECONTEXT');raise SystemExit(1)
