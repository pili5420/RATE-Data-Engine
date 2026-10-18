"""Owned-process completion protocol; injectable provider, no native imports."""
import time
class Incomplete(RuntimeError):pass
def need(ok,code):
 if not ok:raise Incomplete(code)

def accounting(active,pids,known):
 need(type(active) is int and 0<=active<=4,'ACTIVE_TYPE_OR_BOUND')
 need(type(pids) is list and len(pids)<=4 and all(type(p) is int and p>0 for p in pids) and len(set(pids))==len(pids),'PID_LIST_TYPE_OR_BOUND')
 need(set(pids)<=known,'UNKNOWN_JOB_MEMBER')

def snapshot_shape(row,known):
 need(type(row) is dict,'SNAPSHOT_TYPE')
 accounting(row['active'],row['job_pids'],known)
 need(type(row['root_exit_code']) is int and 0<=row['root_exit_code']<=0xffffffff,'EXIT_TYPE')
 handles=row['handles'];need(type(handles) is list and len(handles)==len(known) and len(handles)>0,'HANDLE_COUNT')
 for i,h in enumerate(handles):
  need(type(h) is dict and set(h)=={'kind','handle','wait','exit_code'},'HANDLE_FIELDS')
  need(h['kind']==('root' if i==0 else 'descendant') and type(h['handle']) is int and h['handle']>0,'HANDLE_IDENTITY')
  need(type(h['wait']) is int and type(h['exit_code']) is int and 0<=h['exit_code']<=0xffffffff,'HANDLE_STATE_TYPE')
 need(len({h['handle'] for h in handles})==len(handles),'DUPLICATE_HANDLE')
 need(all(type(row[k]) is int and row[k]>0 for k in ('utc_ns','monotonic_ns')),'OBSERVATION_TIME_TYPE')
def qualify(job,mode,seconds,known,emit):
 start=time.monotonic();end=start+seconds;timed=False
 pending=[('WAIT_STARTED',{'execution_bound_seconds':seconds,'cancel_and_drain_bound_seconds':10,'known_pids':sorted(known),'observation_monotonic_ns':time.monotonic_ns()})]
 def flush():
  while pending:
   event,data=pending.pop(0);emit(event,data)
 try:
  need(type(known) is set and 1<=len(known)<=2 and all(type(p) is int and p>0 for p in known),'KNOWN_OWNERSHIP_SET')
  code=job.wait_owned(max(0,end-time.monotonic()))
  need(type(code) is int and code in (0,258),'WAIT_UNKNOWN')
  timed=code==258
  if timed:
   pending.append(('DEADLINE_REACHED',{'elapsed_ms':int((time.monotonic()-start)*1000)}))
   end=time.monotonic()+10 # includes termination call and evidence I/O; no extension
   job.terminate_owned(124);pending.append(('TERMINATE_JOB_SUCCEEDED',{'exit_code_requested':124}))
   job.confirm_handles(end)
  first=job.snapshot();flush();emit('RETAINED_HANDLES_OBSERVATION',first)
  snapshot_shape(first,known)
  need(set(first['job_pids'])<=known,'UNKNOWN_JOB_MEMBER')
  need(all(x['wait']==0 for x in first['handles']),'UNCONFIRMED_OWNED_HANDLE')
  expected={'normal':0,'crash':7,'hang':124,'descendant_hang':124}[mode]
  need(first['root_exit_code']==expected and timed==(mode in ('hang','descendant_hang')),'ROOT_EXIT_OR_TIMEOUT_MISMATCH')
  need(all(x['exit_code']==(124 if timed else expected) for x in first['handles']),'DESCENDANT_EXIT_MISMATCH')
  need(len(first['handles'])==len(known) and first['handles'][0]['kind']=='root' and first['handles'][0]['exit_code']==first['root_exit_code'],'FIRST_HANDLE_IDENTITY_OR_EXIT_CONFLICT')
  # Second retained observation distinguishes temporal movement from handle-release correlation.
  second=job.snapshot();emit('SECOND_RETAINED_OBSERVATION',second)
  snapshot_shape(second,known)
  need(set(second['job_pids'])<=known and all(x['wait']==0 for x in second['handles']),'RETAINED_IDENTITY_OR_EXIT_CHANGED')
  need(second['root_exit_code']==first['root_exit_code'] and second['handles']==first['handles'],'SECOND_HANDLE_OR_EXIT_CONTRADICTION')
  released=job.release_confirmed(first['handles']);emit('CONFIRMED_HANDLE_RELEASE',{'closed_handles':released,'all_signaled_before_release':True})
  observations=[]
  while True:
   active,pids=job.active(),job.pids()
   row={'active':active,'job_pids':pids,'utc_ns':time.time_ns(),'monotonic_ns':time.monotonic_ns()};observations.append(row);emit('POST_RELEASE_JOB_OBSERVATION',row)
   accounting(active,pids,known)
   need(set(pids)<=known,'UNKNOWN_JOB_MEMBER_AFTER_RELEASE')
   need(time.monotonic()<=end,'JOB_OBSERVATION_AFTER_ORIGINAL_BOUND')
   if active==0 and not pids:break
   need(time.monotonic()<end,'JOB_NOT_EMPTY_WITHIN_ORIGINAL_BOUND')
   time.sleep(min(.002,max(0,end-time.monotonic()))) # polling only; PASS requires two actual zero/empty checks
  final={'active':job.active(),'job_pids':job.pids()};emit('FINAL_JOB_GATE',final)
  accounting(final['active'],final['job_pids'],known)
  need(final['active']==0 and not final['job_pids'],'FINAL_JOB_GATE_NOT_EMPTY')
  need(time.monotonic()<=end,'FINAL_GATE_AFTER_ORIGINAL_BOUND')
  result={'status':'PASS','mode':mode,'root_exit_code':first['root_exit_code'],'timeout':timed,'legacy_zero_gate':('NOT_EQUIVALENT_TIMEOUT_PATH' if timed else 'REJECT_OBSERVED' if first['active'] else 'PASS_OBSERVED'),
   'retained_active_first':first['active'],'retained_active_second':second['active'],'temporal_change_while_handles_retained':first['active']!=second['active'],
   'release_causality':'NOT_ISOLATED_FROM_ELAPSED_TIME','root_cause_claim':'TIMEOUT_ACCOUNTING_IS_NOT_ORIGINAL_RED_PROOF' if timed else 'INSTANT_ACCOUNTING_IS_NOT_SUFFICIENT_COMPLETION_PROTOCOL' if first['active'] else 'LEGACY_NONZERO_NOT_REPRODUCED_THIS_CASE',
   'final_active':0,'final_job_pids':[],'elapsed_ms':int((time.monotonic()-start)*1000),'execution_bound_seconds':seconds,'NoRetry':True}
  emit('CASE_TERMINAL',result);return result
 except Exception as exc:
  flush()
  code=str(exc) if str(exc).replace('_','').isalpha() and str(exc).upper()==str(exc) else type(exc).__name__
  emit('CASE_TERMINAL',{'status':'UNKNOWN','error_code':code,'timeout_observed':timed,'NoRetry':True,'NoResume':True})
  raise
