"""C01 signed hosted-runner OWNED PROCESS ONLY entry. No CIM/Registry/GUI dispatch."""
import hashlib,json,os,re,sys,time,urllib.parse,urllib.request
from pathlib import Path
SRC=Path(__file__).resolve().parent;ROOT=SRC.parent.parent
_m=json.loads((SRC/'SOURCE_MANIFEST_V1.json').read_bytes());_raw=(SRC/'source_loader.py').read_bytes()
if _m['files']['source_loader.py']!={'bytes':len(_raw),'sha256':hashlib.sha256(_raw).hexdigest()}:raise ValueError('BOOTSTRAP_SOURCE_HASH')
_ns={'__file__':str(SRC/'source_loader.py')};exec(compile(_raw,str(SRC/'source_loader.py'),'exec',dont_inherit=True),_ns)
loader=_ns['Loader'](SRC);proof=loader.load('runner_proof');state=loader.load('state')
def canonical(v):return json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()+b'\n'
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
        'GITHUB_REPOSITORY':proof.REPO,'GITHUB_REF':proof.REF,'PF002_C01_PROFILE':'SIGNED_HOSTED_RUNNER_CONTAINMENT_ONLY'}
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
 proof.need(run['head_sha']==head and run['head_branch']==proof.BRANCH and run['event']=='push' and run['run_attempt']==1 and run['path']=='.github/workflows/rate_pf002_c01_containment.yml','OFFICIAL_RUN_HEAD_WORKFLOW')
 proof.need(run['repository']['id']==1370145728,'OFFICIAL_REPOSITORY_ID')
 accepted=fetch('https://api.github.com/repos/'+proof.REPO+'/git/ref/heads/codex/pf-personal-readonly-collector-v1')
 proof.need(accepted['object']['sha']=='90b27e3dd5f328883e1c9c809173df6ec61c9373','STACKED_BASE_MOVED_HALT')
 current=fetch('https://api.github.com/repos/'+proof.REPO+'/git/trees/'+head+'?recursive=1')
 prior=fetch('https://api.github.com/repos/'+proof.REPO+'/git/trees/90b27e3dd5f328883e1c9c809173df6ec61c9373?recursive=1')
 proof.need(not current['truncated'] and not prior['truncated'],'SOURCE_TREE_BOUND')
 ct={r['path']:r for r in current['tree'] if r['type']=='blob'};pt={r['path']:r for r in prior['tree'] if r['type']=='blob'}
 proof.need(len(pt)==652 and all(n in ct and ct[n]['sha']==v['sha'] and ct[n]['mode']==v['mode'] for n,v in pt.items()),'ACCEPTED_BASE_UNCHANGED')
 names=set(ct)-set(pt)
 proof.need(all(n.startswith('tools/pf002_containment_c01/') or n=='.github/workflows/rate_pf002_c01_containment.yml' for n in names),'ADDITIVE_ONLY_SOURCE')
 for name in names:
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
def run():
 token,claims,role,head,rid,attempt=authenticate();runner=Path(os.environ['RUNNER_TEMP']);physical(runner)
 root=runner/('PF002-C01-'+rid+'-1-'+role);physical(root);proof.need(not root.exists(),'ONE_SHOT_ROOT_EXISTS')
 save(runner/(root.name+'.intent'),{'realm':'CONTAINMENT_ONLY_NOT_OWNER_AUTHORIZATION','head':head,'role':role,'run_id':rid,'nonce':os.urandom(16).hex()})
 root.mkdir();public=root/'public';public.mkdir();(public/'cases').mkdir()
 image_os=os.environ.get('ImageOS','');image_version=os.environ.get('ImageVersion','')
 proof.need(re.fullmatch('[A-Za-z0-9-]{1,32}',image_os) is not None and re.fullmatch('[0-9.]{1,48}',image_version) is not None,'BOUNDED_PUBLIC_IMAGE_IDENTITY')
 save(public/'PROVENANCE.json',{'head':head,'base':'90b27e3dd5f328883e1c9c809173df6ec61c9373','claims':claims,'role':role,'runner_image_os':image_os,'runner_image_version':image_version,
  'python_version':'.'.join(map(str,sys.version_info[:3])),'source_manifest_sha256':hashlib.sha256((SRC/'SOURCE_MANIFEST_V1.json').read_bytes()).hexdigest(),
  'realm':'HOSTED_RUNNER_CONTAINMENT_ONLY_NOT_ORIGINAL_HOST','source_CIM_registry_reads':0,'original_host_queries':0,'owner_consent_issued':False,'NoAutoNext':True})
 save(public/'SOURCE_MANIFEST.json',sources());results=[]
 for mode,deadline in [('normal',10),('crash',10),('hang',2),('descendant_hang',3)]:
  private=root/('fault_'+mode);private.mkdir();evidence=public/'cases'/mode;evidence.mkdir();j=Journal(evidence,mode,head,role,rid);job=None
  j.emit('CASE_INTENT',{'status':'STARTED','root_pid':None,'descendant_pid':None,'execution_bound_seconds':deadline,'cancellation_bound_seconds':10,'NoRetry':True})
  try:
   env=environment(private,role,head,rid,runner);job=loader.load('job').WindowsJob(token,env)
   j.emit('JOB_CREATED',{'job_name':job.job_name,'job_handle':int(job.job),'active_before':job.active(),'job_pids':job.pids(),'kill_on_close':True,'active_process_limit':4,'breakaway':False})
   birth=job.launch([sys.executable,'-I','-B','-S',str(SRC/'fault_worker.py'),mode],ROOT,env,private,token);known={birth['pid']}
   birth.update(observation_monotonic_ns=time.monotonic_ns(),observation_utc_ns=time.time_ns())
   pending=[('ROOT_CREATED_SUSPENDED_ASSIGNED_RESUMED',birth)]
   def case_emit(event,data):
    while pending:
     e,v=pending.pop(0);j.emit(e,v)
    j.emit(event,data)
   if mode=='descendant_hang':
    end=time.monotonic()+5
    while not (private/'DESCENDANT_STARTED.json').exists() and time.monotonic()<end:time.sleep(.002)
    receipt=proof.strict((private/'DESCENDANT_STARTED.json').read_bytes())
    proof.need(set(receipt)=={'pid','parent_pid'} and type(receipt['pid']) is int and receipt['pid']>0 and receipt['parent_pid']==birth['pid'] and receipt['pid']!=birth['pid'],'DESCENDANT_IDENTITY')
    job.hold_owned_pid(receipt['pid']);known.add(receipt['pid']);pending.append(('OWNED_DESCENDANT_CONFIRMED',{'pid':receipt['pid'],'parent_pid':birth['pid'],'same_job_confirmed':True,'retained_handle':int(job.handles[-1]),'observation_monotonic_ns':time.monotonic_ns()}))
   result=state.qualify(job,mode,deadline,known,case_emit)
   results.append({'case':mode,'job_name':job.job_name,'root_pid':birth['pid'],'descendant_pid':next(iter(known-{birth['pid']}),None),**result,'journal_head':j.prev})
  except Exception as exc:
   if 'pending' in locals():
    while pending:
     e,v=pending.pop(0);j.emit(e,v)
   code=str(exc) if re.fullmatch('[A-Z_]{1,120}',str(exc)) else type(exc).__name__
   j.emit('CASE_ABORT',{'status':'UNKNOWN','error_code':code,'win32_error':getattr(exc,'win32_error',None),'NoRetry':True,'NoResume':True})
   if job is not None:
    try:
     job.terminate_owned(126);j.emit('FAIL_CLOSED_OWN_JOB_TERMINATION',{'requested_exit':126,'job_name':job.job_name})
     if hasattr(job,'hp'):job.confirm_handles(time.monotonic()+10);j.emit('FAILURE_OWN_HANDLES',job.snapshot())
    except Exception as cleanup:j.emit('CLEANUP_OUTCOME_UNKNOWN',{'error_type':type(cleanup).__name__,'win32_error':getattr(cleanup,'win32_error',None)})
   save(public/'HALT.json',{'status':'HALT','case':mode,'error_code':code,'journal_head':j.prev,'NoRetry':True,'NoResume':True,'source_reads':0,'original_host_queries':0});return 1
  finally:
   if job is not None:
    closed=job.close();closed['job_name']=job.job_name
    j.emit('OWN_JOB_RESOURCES_CLOSED' if closed['status']=='CLOSED' else 'OWN_JOB_RESOURCE_CLOSE_UNKNOWN',closed)
    if closed['status']!='CLOSED':
     save(public/'RESOURCE_CLOSE_HALT.json',{'status':'HALT','case':mode,'journal_head':j.prev,'error_code':'OWN_RESOURCE_CLOSE_UNKNOWN','NoRetry':True,'NoResume':True});return 1
 reds=[x['case'] for x in results if x['legacy_zero_gate']=='REJECT_OBSERVED']
 summary={'status':'CONTAINMENT_CASES_PASS' if reds else 'BLOCKED_RED_NOT_REPRODUCED','head':head,'role':role,'cases':results,'observed_legacy_red_cases':reds,
  'root_cause_evidence':'IMMEDIATE_LEGACY_GATE_REJECTED_PROVEN_SIGNALED_OWNED_PROCESSES' if reds else 'ORIGINAL_NONZERO_NOT_REPRODUCED',
  'handle_release_vs_elapsed_time_causal_isolation':False,'original_failed_case_pid':'UNKNOWN','original_GUI_HALT_root_cause':'UNKNOWN','overall_PF002_runtime':'BLOCKED','source_CIM_registry_reads':0,'owner_consent_issued':False,'NoAutoNext':True}
 save(public/'QUALIFICATION.json',summary);print(summary['status']);return 0 if reds else 1
if __name__=='__main__':
 try:raise SystemExit(run())
 except Exception as exc:print('HALT_C01_AUTH_OR_BOUNDARY_'+type(exc).__name__);raise SystemExit(1)
