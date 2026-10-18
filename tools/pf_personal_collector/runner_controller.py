"""GitHub hosted Windows engineering entry ONLY. No owner/target/consent/query arguments."""
import hashlib,json,os,re,sys,time,urllib.parse,urllib.request,shutil
from pathlib import Path
SRC=Path(__file__).resolve().parent;ROOT=SRC.parent.parent
sys.path.append(str(ROOT/'tools/pf_personal_trust'));sys.path.append(str(SRC))
import runner_proof as proof
import personal_model as base
from evidence_protocol import evaluate_private,check_public
class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*a,**k):raise proof.Refused('HTTPS_REDIRECT_FORBIDDEN')
def fetch(url,headers=None,bound=1048576):
 req=urllib.request.Request(url,headers=headers or {})
 with urllib.request.build_opener(NoRedirect()).open(req,timeout=10) as r:
  proof.need(r.url==url,'REDIRECT');b=r.read(bound+1);proof.need(len(b)<=bound,'HTTPS_BYTE_BOUND')
 return proof.strict(b,bound)
def sources():
 manifest=proof.strict((SRC/'SOURCE_MANIFEST_V1.json').read_bytes())
 actual={p.name for p in SRC.iterdir()}
 proof.need(actual==set(manifest['files'])|{'SOURCE_MANIFEST_V1.json'},'EXACT_SOURCE_DIRECTORY')
 for n,row in manifest['files'].items():
  p=SRC/n
  proof.need(p.is_file() and not p.is_symlink() and not(getattr(p.stat(),'st_file_attributes',0)&0x400),'SOURCE_REPARSE')
  b=p.read_bytes();proof.need(row=={'sha256':hashlib.sha256(b).hexdigest(),'bytes':len(b)},'SOURCE_HASH')
 return manifest
def authenticate():
 proof.need(len(sys.argv)==1,'NO_OWNER_CONSENT_OR_COMMAND_ARGUMENTS')
 fixed={'GITHUB_ACTIONS':'true','RUNNER_ENVIRONMENT':'github-hosted','RUNNER_OS':'Windows',
        'GITHUB_REPOSITORY':proof.REPO,'GITHUB_REF':proof.REF,'PF002_PROFILE':'SIGNED_HOSTED_RUNNER_ENGINEERING_ONLY'}
 for k,v in fixed.items():proof.need(os.environ.get(k)==v,'HOSTED_RUNNER_CONTEXT')
 proof.need(os.name=='nt','WINDOWS_HOSTED_RUNNER_ONLY')
 role=os.environ.get('PF002_ROLE');proof.need(role in ('qualification','reproduction'),'EXACT_JOB_ROLE')
 head=os.environ.get('GITHUB_SHA','');rid=os.environ.get('GITHUB_RUN_ID','');attempt=os.environ.get('GITHUB_RUN_ATTEMPT','')
 proof.need(re.fullmatch('[0-9a-f]{40}',head) is not None and rid.isascii() and rid.isdigit() and attempt=='1','EXACT_FRESH_RUN')
 url=os.environ.get('ACTIONS_ID_TOKEN_REQUEST_URL','');u=urllib.parse.urlparse(url)
 proof.need(u.scheme=='https' and type(u.hostname) is str and u.hostname.endswith('.actions.githubusercontent.com') and u.port in (None,443) and not u.username and not u.fragment,'GITHUB_TOKEN_ENDPOINT')
 url+=('&' if '?' in url else '?')+'audience='+proof.AUD
 token_response=fetch(url,{'Authorization':'bearer '+os.environ.get('ACTIONS_ID_TOKEN_REQUEST_TOKEN','')},32768)
 token=token_response.get('value');claims=proof.verify_token(token,(SRC/'GITHUB_OIDC_JWKS_PINNED.json').read_bytes(),int(time.time()),head,rid,attempt)
 # Public official API metadata only; no GitHub bearer is inherited or needed here.
 run=fetch('https://api.github.com/repos/'+proof.REPO+'/actions/runs/'+rid,{'Accept':'application/vnd.github+json','User-Agent':'RATE-PF002-runner-engineering'})
 proof.need(run['head_sha']==head and run['head_branch']==proof.BRANCH and run['event']=='push' and run['run_attempt']==1 and run['path']=='.github/workflows/rate_pf_personal_collector.yml','OFFICIAL_RUN_HEAD_WORKFLOW')
 proof.need(run['repository']['id']==1370145728,'OFFICIAL_REPOSITORY_ID')
 accepted=fetch('https://api.github.com/repos/'+proof.REPO+'/git/ref/heads/codex/pf-personal-owner-trust-v1')
 proof.need(accepted['object']['sha']=='9cec01c262e9d0881432d08c2844924893612cee','STACKED_BASE_MOVED_HALT')
 current=fetch('https://api.github.com/repos/'+proof.REPO+'/git/trees/'+head+'?recursive=1')
 prior=fetch('https://api.github.com/repos/'+proof.REPO+'/git/trees/9cec01c262e9d0881432d08c2844924893612cee?recursive=1')
 proof.need(not current['truncated'] and not prior['truncated'],'SOURCE_TREE_BOUND')
 ct={r['path']:r for r in current['tree'] if r['type']=='blob'};pt={r['path']:r for r in prior['tree'] if r['type']=='blob'}
 proof.need(len(pt)==628 and all(n in ct and ct[n]['sha']==v['sha'] and ct[n]['mode']==v['mode'] for n,v in pt.items()),'ACCEPTED_BASE_UNCHANGED')
 names=set(ct)-set(pt)
 proof.need(all(n.startswith('tools/pf_personal_collector/') or n=='.github/workflows/rate_pf_personal_collector.yml' for n in names),'ADDITIVE_ONLY_SOURCE')
 for name in names|{'tools/pf_personal_trust/READ_SCOPE_V1.json','tools/pf_personal_trust/personal_model.py'}:
  b=(ROOT/name).read_bytes();oid=hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()
  proof.need(oid==ct[name]['sha'],'REMOTE_EXACT_SOURCE_BLOB')
 sources()
 return token,claims,role,head,rid,attempt
def physical(path):
 proof.need(path.is_absolute() and path==path.resolve(),'PHYSICAL_PATH_ALIAS')
 for p in (path,*path.parents):
  if p.exists():proof.need(not p.is_symlink() and not(getattr(p.lstat(),'st_file_attributes',0)&0x400),'REPARSE_ROOT')
def save(path,value):
 b=base.canonical(value)+b'\n'
 with path.open('xb') as f:f.write(b);f.flush();os.fsync(f.fileno())
def native_env(private,role,head,rid,runner):
 names=('PATH','SystemRoot','SYSTEMROOT','WINDIR','COMSPEC','TEMP','TMP','ProgramFiles','ProgramFiles(x86)','PSModulePath','DOTNET_ROOT')
 env={k:os.environ[k] for k in names if k in os.environ}
 env.update(PF002_PRIVATE_ROOT=str(private),PF002_ROLE=role,PF002_HEAD=head,PF002_RUN_ID=rid,PF002_RUN_ATTEMPT='1',PF002_RUNNER_ROOT=str(runner),PYTHONDONTWRITEBYTECODE='1')
 return env
def failure_receipts(private):
 rows=[]
 known_status={'Failed','AccessDenied','InvalidNamespace','InvalidParameter','InvalidClass','NotFound','NotSupported','InvalidQuery','QueryLanguageNotSupported','TypeMismatch','ServerLimitsExceeded','InvalidOperationTimeout'}
 fixed_codes=set(re.findall("throw '([A-Z_]+)'",(SRC/'native_worker.ps1').read_text()))
 for i,name in enumerate(base.ORDER,1):
  path=private/f'error_{i:02d}.json'
  if not path.exists():continue
  raw=path.read_bytes();v=proof.strict(raw,65536)
  kind=v.get('exception_type','')
  proof.need(type(kind) is str and re.fullmatch('[A-Za-z_][A-Za-z0-9_.]{0,199}',kind) is not None,'PRIVATE_ERROR_TYPE')
  def number(key):
   n=v.get(key);proof.need(n is None or type(n) is int and -(2**31)<=n<2**32,'PRIVATE_ERROR_NUMBER');return n
  rows.append({'id':name,'private_error_sha256':hashlib.sha256(raw).hexdigest(),'exception_type':kind,'hresult':number('hresult'),'native_error':number('native_error'),
   'cim_status':v.get('cim_status') if v.get('cim_status') in known_status else 'UNCLASSIFIED_OR_NOT_CIM',
   'fixed_source_error':v.get('message') if v.get('message') in fixed_codes else 'PROVIDER_DETAILS_PRIVATE_NOT_PUBLIC'})
 return {'realm':'RUNNER_ONLY_NOT_ORIGINAL_HOST_EVIDENCE','errors':rows,'private_details_publicly_retained':False}
def one_process(command,private,env,token,deadline,descendant=False):
 from windows_job import WindowsJob
 job=WindowsJob()
 try:
  birth=job.launch(command,ROOT,env,private,token)
  if descendant:
   end=time.monotonic()+5
   while not (private/'DESCENDANT_STARTED.json').exists() and time.monotonic()<end:time.sleep(.02)
   receipt=base.strict((private/'DESCENDANT_STARTED.json').read_bytes())
   base.shape(receipt,('pid','parent_pid'),'DESCENDANT_RECEIPT')
   proof.need(type(receipt['pid']) is int and receipt['pid']>0 and receipt['parent_pid']==birth['pid'] and receipt['pid']!=birth['pid'],'OWN_CHILD_RECEIPT')
   job.hold_owned_pid(receipt['pid']);proof.need(job.active()>=2,'DESCENDANT_NOT_ACTUALLY_RUNNING')
   birth.update(descendant_pid=receipt['pid'],descendant_observed_in_same_job=True,active_before_cancel=job.active())
  result=job.wait(deadline);result.update(birth)
  proof.need(result['active_after']==0,'DESCENDANTS_LEFT_AFTER_ROOT_EXIT')
  return result
 finally:job.close()
def run():
 token,claims,role,head,rid,attempt=authenticate()
 runner=Path(os.environ['RUNNER_TEMP']);physical(runner);proof.need(runner.is_dir(),'RUNNER_TEMP_EXISTS')
 root=runner/('PF-PERSONAL-002-'+rid+'-1-'+role);physical(root)
 proof.need(not root.exists(),'ONE_SHOT_ROOT_EXISTS_NO_RESUME')
 with (runner/(root.name+'.intent')).open('xb') as f:f.write(b'RUNNER_ENGINEERING_INTENT_NOT_OWNER_CONSENT\n');f.flush();os.fsync(f.fileno())
 root.mkdir();private=root/'private';private.mkdir();public=root/'public';public.mkdir()
 nonce=os.urandom(16).hex();save(private/'ATTEMPT.json',{'head':head,'role':role,'run_id':rid,'nonce':nonce,'realm':'RUNNER_ONLY_NOT_ORIGINAL_HOST_EVIDENCE','not_owner_consent':True})
 env=native_env(private,role,head,rid,runner)
 image_os=os.environ.get('ImageOS','');image_version=os.environ.get('ImageVersion','')
 proof.need(re.fullmatch('win[0-9]{2}',image_os) is not None and re.fullmatch('[0-9]+(?:[.][0-9]+){1,3}',image_version) is not None,'SAFE_RUNNER_IMAGE_VERSION')
 save(public/'RUNNER_PROVENANCE.json',{'realm':'RUNNER_ONLY_NOT_ORIGINAL_HOST_EVIDENCE','head':head,'role':role,
  'claims':claims,'GitHub_HTTPS_metadata_requests':5,'collector_remote_sessions':0,'original_host_queries':0,
  'jwks_sha256':proof.JWKS_SHA,'source_manifest_sha256':hashlib.sha256((SRC/'SOURCE_MANIFEST_V1.json').read_bytes()).hexdigest(),
  'accepted_scope_sha256':hashlib.sha256((ROOT/'tools/pf_personal_trust/READ_SCOPE_V1.json').read_bytes()).hexdigest(),
  'runner_image_os':image_os,'runner_image_version':image_version,'python_version':'.'.join(map(str,sys.version_info[:3])),'python_bits':64 if sys.maxsize>2**32 else 32,
  'repository_token_permissions':'contents:read only; id-token:write only for provenance token minting, not repository writes',
  'bearer_proof_is_machine_attestation':False,'native_child_inherited_repository_or_oidc_request_credential':False,'signed_oidc_proof_delivered_by_anonymous_pipe':True})
 save(public/'SOURCE_MANIFEST.json',sources())
 stage='NATIVE_PROCESS'
 try:
  executable=shutil.which('pwsh');proof.need(executable is not None,'POWERSHELL_REQUIRED')
  process=one_process([executable,'-NoProfile','-NonInteractive','-File',str(SRC/'native_worker.ps1')],private,env,token,150)
  save(public/'NATIVE_PROCESS.json',process)
  save(public/'SAFE_FAILURE_RECEIPTS.json',failure_receipts(private))
  proof.need(not process['deadline_triggered'],'NATIVE_OUTCOME_UNKNOWN_TIMEOUT_NO_RETRY')
  stage='PRIVATE_VALIDATION'
  report=evaluate_private((private/'PRIVATE_PACKET.json').read_bytes(),head,rid,attempt)
  check_public(report);save(public/'PUBLIC_SOURCE_REPORT.json',report)
  stage='SEPARATE_PROCESS_PRIVATE_REHASH'
  # A pure separate process; same reviewed semantic implementation is explicitly disclosed.
  import subprocess
  with (private/'verifier.stdout.private').open('xb') as so,(private/'verifier.stderr.private').open('xb') as se:
   checked=subprocess.run([sys.executable,'-I','-B','-S',str(SRC/'verify_private_packet.py'),str(private/'PRIVATE_PACKET.json'),head,rid],env=env,stdin=subprocess.DEVNULL,stdout=so,stderr=se,timeout=15,check=False)
  proof.need(checked.returncode==0,'SEPARATE_PRIVATE_VERIFIER_FAILED')
  receipt=base.strict((private/'verifier.stdout.private').read_bytes())
  proof.need(receipt['public_report_sha256']==hashlib.sha256(base.canonical(report)+b'\n').hexdigest() and receipt['packet_sha256']==report['private_packet_sha256'],'SEPARATE_RAW_RECEIPT_BINDING')
  proof.need(receipt['source_manifest_sha256']==hashlib.sha256((SRC/'SOURCE_MANIFEST_V1.json').read_bytes()).hexdigest(),'SEPARATE_VERIFIER_SOURCE_BINDING')
  save(public/'SEPARATE_RAW_VERIFICATION.json',receipt)
  proof.need(process['exit_code']==0 and report['native_outcome']=='NATIVE_READ_COMPLETED','NATIVE_SOURCE_HALT_PRESERVED')
  # Actual owned-child faults, no source queries. Each has a distinct new private output.
  stage='CONTAINMENT_SELFTEST'
  faults=[]
  for mode,deadline,expected in [('normal',10,0),('crash',10,7),('hang',2,124),('descendant_hang',3,124)]:
   output=root/('fault_'+mode);output.mkdir()
   result=one_process([sys.executable,'-I','-B','-S',str(SRC/'fault_worker.py'),mode],output,native_env(output,role,head,rid,runner),token,deadline,mode=='descendant_hang')
   proof.need(result['exit_code']==expected and result['active_after']==0 and result['deadline_triggered']==(expected==124),'ACTUAL_FAULT_RESULT')
   faults.append({'case':mode,**result})
  save(public/'CONTAINMENT_SELFTEST.json',{'status':'OWNED_PROCESS_TREE_TESTS_PASS','cases':faults,'provider_cancellation':'BLOCKED_OUTSIDE_JOB_NOT_PROVEN','physical_output_atomicity':'BLOCKED_NOT_PROVEN','original_host_protection_against_stolen_bearer':'BLOCKED_NOT_MACHINE_ATTESTATION','parent_death_kill_switch':'DESIGN_KILL_ON_CLOSE_NOT_SEPARATELY_TESTED'})
  save(public/'RUNNER_QUALIFICATION.json',{'status':'RUNNER_NATIVE_READ_COMPLETED','head':head,'role':role,'record_count':12,'realm':'RUNNER_ONLY_NOT_ORIGINAL_HOST_EVIDENCE','original_host_authorized':False,'owner_consent_issued':False,'NoAutoNext':True})
  print('RUNNER_ONLY_NATIVE_READ_AND_OWNED_CONTAINMENT_COMPLETED')
 except Exception as exc:
  code=str(exc) if isinstance(exc,(proof.Refused,base.Refused)) and re.fullmatch('[A-Z_]{1,100}',str(exc)) else type(exc).__name__
  save(public/'HALT.json',{'status':'HALT','stage':stage,'error_code':code,'private_evidence_preserved':True,'private_stdout_sha256':hashlib.sha256((private/'stdout.private').read_bytes()).hexdigest() if (private/'stdout.private').exists() else None,'private_stderr_sha256':hashlib.sha256((private/'stderr.private').read_bytes()).hexdigest() if (private/'stderr.private').exists() else None,'NoRetry':True,'NoResume':True,'original_host_queries':0})
  print('HALT_RUNNER_ENGINEERING_PARTIAL_EVIDENCE_PRESERVED');return 1
 return 0
if __name__=='__main__':
 try:raise SystemExit(run())
 except (proof.Refused,base.Refused):print('HALT_SIGNED_RUNNER_GATE_OR_SOURCE_BINDING');raise SystemExit(1)

