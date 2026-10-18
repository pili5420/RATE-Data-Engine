"""Offline verifier of complete public journals; never dispatches native calls."""
import hashlib,json,re
from pathlib import Path

class Invalid(ValueError):pass
def need(ok,why):
 if not ok:raise Invalid(why)
def read(path):
 b=path.read_bytes();need(0<len(b)<=65536,'RECORD_BOUND')
 def pairs(items):
  d={}
  for k,v in items:need(k not in d,'DUPLICATE_KEY');d[k]=v
  return d
 v=json.loads(b.decode('utf-8','strict'),object_pairs_hook=pairs,parse_constant=lambda _:(_ for _ in ()).throw(Invalid('NONFINITE')))
 need(json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()+b'\n'==b,'CANONICAL_RECORD')
 return v,hashlib.sha256(b).hexdigest()
def positive(v):return type(v) is int and v>0

def verify(root,head,role,rid,require_red=True):
 need(re.fullmatch('[0-9a-f]{40}',head) is not None and role in ('qualification','reproduction') and rid.isdigit(),'EXPECTED_CONTEXT')
 need({p.name for p in root.iterdir()}=={'PROVENANCE.json','SOURCE_MANIFEST.json','QUALIFICATION.json','cases'},'PUBLIC_ROOT_CLOSURE')
 for p in (root,*root.rglob('*')):need(not p.is_symlink() and not(getattr(p.lstat(),'st_file_attributes',0)&0x400),'EVIDENCE_REPARSE')
 provenance,_=read(root/'PROVENANCE.json');summary,_=read(root/'QUALIFICATION.json')
 import runner_proof as proof
 local=Path(__file__).resolve().parent/'SOURCE_MANIFEST_V1.json';manifest,_=read(root/'SOURCE_MANIFEST.json')
 need(manifest==json.loads(local.read_bytes()) and provenance['source_manifest_sha256']==hashlib.sha256(local.read_bytes()).hexdigest(),'EXACT_TOOL_MANIFEST_BINDING')
 expected={'iss':proof.ISS,'aud':proof.AUD,'repository':proof.REPO,'repository_id':'1370145728','repository_owner_id':'325481386','ref':proof.REF,'event_name':'push','runner_environment':'github-hosted','workflow_ref':proof.WORKFLOW,'sha':head,'workflow_sha':head,'run_id':rid,'run_attempt':'1'}
 need(provenance['claims']==expected,'CLAIMS_CONTEXT_BINDING')
 need(provenance['head']==head and provenance['role']==role and provenance['claims']['run_id']==rid and provenance['claims']['run_attempt']=='1','PROVENANCE_BINDING')
 need(type(provenance['source_CIM_registry_reads']) is int and provenance['source_CIM_registry_reads']==0 and type(provenance['original_host_queries']) is int and provenance['original_host_queries']==0 and provenance['owner_consent_issued'] is False and provenance['NoAutoNext'] is True,'SAFETY_BOUNDARY')
 need(summary['head']==head and summary['role']==role and summary['overall_PF002_runtime']=='BLOCKED' and type(summary['source_CIM_registry_reads']) is int and summary['source_CIM_registry_reads']==0 and summary['owner_consent_issued'] is False and summary['NoAutoNext'] is True,'SUMMARY_BOUNDARY')
 need(summary['original_GUI_HALT_root_cause']=='UNKNOWN' and summary['handle_release_vs_elapsed_time_causal_isolation'] is False,'CAUSALITY_LIMIT')
 modes=('normal','crash','hang','descendant_hang');need({p.name for p in (root/'cases').iterdir()}==set(modes),'FOUR_CASE_CLOSURE')
 need([r['case'] for r in summary['cases']]==list(modes),'FOUR_CASE_SUMMARY')
 reds=[];jobs=set();records=0
 for mode,s in zip(modes,summary['cases']):
  rows=[];digests=[];prev=None;lastmono=0
  files=sorted((root/'cases'/mode).iterdir());need(1<=len(files)<=8192,'EVENT_COUNT_BOUND')
  for seq,p in enumerate(files,1):
   v,d=read(p);need(p.name==f"{seq:04d}_{v['event']}.json",'EVENT_NAME_SEQUENCE')
   need(set(v)=={'sequence','previous_sha256','case','head','role','run_id','event','utc_ns','monotonic_ns','data'},'JOURNAL_EXACT_FIELDS')
   need(v['sequence']==seq and type(v['sequence']) is int and v['previous_sha256']==prev,'HASH_CHAIN')
   need(v['head']==head and v['role']==role and v['run_id']==rid and v['case']==mode,'EVENT_BINDING')
   need(positive(v['utc_ns']) and positive(v['monotonic_ns']) and v['monotonic_ns']>=lastmono,'EVENT_TIME')
   lastmono=v['monotonic_ns'];prev=d;rows.append(v);digests.append(d)
  records+=len(rows);events=[r['event'] for r in rows]
  fixed=['CASE_INTENT','JOB_CREATED','ROOT_CREATED_SUSPENDED_ASSIGNED_RESUMED']
  if mode=='descendant_hang':fixed+=['OWNED_DESCENDANT_CONFIRMED']
  fixed+=['WAIT_STARTED']
  if mode in ('hang','descendant_hang'):fixed+=['DEADLINE_REACHED','TERMINATE_JOB_SUCCEEDED']
  fixed+=['RETAINED_HANDLES_OBSERVATION','SECOND_RETAINED_OBSERVATION','CONFIRMED_HANDLE_RELEASE']
  tail=['FINAL_JOB_GATE','CASE_TERMINAL','OWN_JOB_RESOURCES_CLOSED']
  need(events[:len(fixed)]==fixed and events[-3:]==tail and len(events)>len(fixed)+3,'EVENT_PROTOCOL')
  need(all(e=='POST_RELEASE_JOB_OBSERVATION' for e in events[len(fixed):-3]),'UNEXPECTED_OR_MISSING_EVENT')
  data={r['event']:r['data'] for r in rows if r['event']!='POST_RELEASE_JOB_OBSERVATION'}
  closed=data['OWN_JOB_RESOURCES_CLOSED'];need(closed['status']=='CLOSED' and all(r['closed'] is True for r in closed['resources']) and closed['not_a_termination_proof'] is True,'RESOURCE_CLOSE_EVIDENCE')
  job,birth=data['JOB_CREATED'],data['ROOT_CREATED_SUSPENDED_ASSIGNED_RESUMED'];pid=birth['pid'];known={pid}
  need(closed['resources']==[{'kind':'job','handle':job['job_handle'],'closed':True,'win32_error':None}]+[{'kind':'stream','index':i,'closed':True,'win32_error':None} for i in range(3)] and closed['job_name']==job['job_name'],'RESOURCE_CLOSE_IDENTITY')
  need(positive(pid) and positive(birth['tid']) and positive(birth['root_handle']),'ROOT_IDENTITY')
  need(birth['assigned_before_resume'] is True and birth['suspended_creation'] is True and birth['thread_handle_closed'] is True and birth['active_before_resume']==1 and birth['job_pids_before_resume']==[pid],'SUSPENDED_JOB_MEMBERSHIP')
  need(job['active_before']==0 and job['job_pids']==[] and job['active_process_limit']==4 and job['kill_on_close'] is True and job['breakaway'] is False,'JOB_LIMITS')
  need(job['job_name'] not in jobs and job['job_name'].startswith('Local\\RATE-PF002-C01-'+rid+'-'+role+'-') and positive(job['job_handle']),'UNIQUE_JOB_IDENTITY');jobs.add(job['job_name'])
  if mode=='descendant_hang':
   desc=data['OWNED_DESCENDANT_CONFIRMED'];need(positive(desc['pid']) and desc['pid']!=pid and desc['parent_pid']==pid and desc['same_job_confirmed'] is True,'DESCENDANT_IDENTITY');known.add(desc['pid'])
  first,second=data['RETAINED_HANDLES_OBSERVATION'],data['SECOND_RETAINED_OBSERVATION'];expected=0 if mode=='normal' else 7 if mode=='crash' else 124
  import state
  for snap in (first,second):
   state.snapshot_shape(snap,known)
   need(snap['root_exit_code']==expected and all(h['wait']==0 and h['exit_code']==expected for h in snap['handles']),'SIGNALED_EXPECTED_EXIT')
  need(first['handles']==second['handles'] and first['handles'][0]['handle']==birth['root_handle'],'RETAINED_HANDLE_IDENTITY')
  if mode=='descendant_hang':need(first['handles'][1]['handle']==desc['retained_handle'],'DESCENDANT_HANDLE_IDENTITY')
  released=data['CONFIRMED_HANDLE_RELEASE'];need(released['all_signaled_before_release'] is True and released['closed_handles']==[{'handle':h['handle'],'wait':0,'exit_code':expected,'closed':True} for h in first['handles']],'RELEASE_PROOF')
  for r in rows:
   if r['event']=='POST_RELEASE_JOB_OBSERVATION':state.accounting(r['data']['active'],r['data']['job_pids'],known)
  need(rows[-4]['data']['active']==0 and rows[-4]['data']['job_pids']==[] and data['FINAL_JOB_GATE']=={'active':0,'job_pids':[]},'DOUBLE_ZERO_EMPTY_GATE')
  terminal=data['CASE_TERMINAL'];deadline=3 if mode=='descendant_hang' else 2 if mode=='hang' else 10
  need(terminal['status']=='PASS' and terminal['execution_bound_seconds']==deadline and terminal['elapsed_ms']<=(deadline+10 if mode in ('hang','descendant_hang') else deadline)*1000,'ORIGINAL_TIME_BOUND')
  need(terminal['root_exit_code']==expected and terminal['timeout']==(mode in ('hang','descendant_hang')) and terminal['NoRetry'] is True,'EXIT_TIMEOUT_OUTCOME')
  timed=mode in ('hang','descendant_hang');red=first['active']!=0 and not timed
  need(terminal['legacy_zero_gate']==('NOT_EQUIVALENT_TIMEOUT_PATH' if timed else 'REJECT_OBSERVED' if red else 'PASS_OBSERVED') and terminal['retained_active_first']==first['active'] and terminal['retained_active_second']==second['active'],'RAW_RED_GREEN_CONSISTENCY')
  if red:reds.append(mode)
  need(all(s[k]==v for k,v in terminal.items()) and s['journal_head']==digests[-2] and s['root_pid']==pid and s['job_name']==job['job_name'],'SUMMARY_CASE_BINDING')
  need(s['descendant_pid']==(desc['pid'] if mode=='descendant_hang' else None),'SUMMARY_DESCENDANT')
 need(summary['observed_legacy_red_cases']==reds and summary['status']==('CONTAINMENT_CASES_PASS' if reds else 'BLOCKED_RED_NOT_REPRODUCED'),'OVERALL_RED_GATE')
 need(not require_red or bool(reds),'RED_NOT_REPRODUCED')
 return {'status':'PASS','head':head,'role':role,'cases':4,'records':records,'legacy_red_cases':reds,'final_journal_heads':{mode:read(sorted((root/'cases'/mode).iterdir())[-1])[1] for mode in modes},'source_reads':0,'owner_consent_issued':False,'overall_runtime':'BLOCKED'}
