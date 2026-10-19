"""Pure strict cleanup evidence contract; no Windows API imports or dispatch."""
from contract import need,known_domain
NO_ROOT='JOB_CREATED_NO_ROOT'
SUSPENDED='ROOT_CREATED_SUSPENDED_NOT_ASSIGNED'
ASSIGNED='ROOT_ASSIGNED_NOT_RESUMED'
RESUMED='ROOT_ASSIGNED_RESUMED'
TERMINAL='ROOT_TERMINATED_AND_RESOURCES_CLOSED'
ROOT_PHASES=frozenset((SUSPENDED,ASSIGNED,RESUMED))
ACCT_FIELDS=frozenset(('TotalUserTime','TotalKernelTime','ThisPeriodTotalUserTime','ThisPeriodTotalKernelTime','TotalPageFaultCount','TotalProcesses','ActiveProcesses','TotalTerminatedProcesses'))
def accounting_complete(accounting):
 need(type(accounting) is dict and set(accounting)==ACCT_FIELDS and all(type(v) is int and v>=0 for v in accounting.values()),'CB01_ACCOUNTING_COMPLETE_STRICT_TYPES')
 need(accounting['ActiveProcesses']<=accounting['TotalProcesses'] and accounting['TotalTerminatedProcesses']<=accounting['TotalProcesses'],'CB01_ACCOUNTING_COUNT_CONTRADICTION')
def empty_job(accounting,ids):
 need(type(accounting) is dict and type(ids) is dict,'CB01_EMPTY_EVIDENCE_TYPE')
 accounting_complete(accounting)
 need(all(type(accounting.get(k)) is int and accounting[k]==0 for k in ('ActiveProcesses','TotalProcesses','TotalTerminatedProcesses')),'CB01_EMPTY_ACCOUNTING_UNKNOWN')
 need(set(ids)=={'assigned','listed','pids'} and type(ids['assigned']) is int and type(ids['listed']) is int and ids['assigned']==ids['listed']==0 and type(ids['pids']) is list and ids['pids']==[],'CB01_EMPTY_PID_LIST_UNKNOWN')
 return True
def finalize(row,closed):
 need(type(row) is dict and row.get('status') in ('EMPTY_JOB_OBSERVED_PENDING_CLOSE','KNOWN_ROOT_AND_JOB_TERMINAL_OBSERVED'),'CB01_CLEANUP_OBSERVATION_REQUIRED')
 need(type(closed) is dict and closed.get('status')=='CLOSED' and type(closed.get('resources')) is list,'CB01_RESOURCE_CLOSE_REQUIRED')
 resources=closed['resources'];need(resources and all(type(r) is dict and r.get('closed') is True for r in resources),'CB01_ALL_RESOURCES_CLOSE_REQUIRED')
 jobs=[r for r in resources if r.get('kind')=='job'];need(len(jobs)==1 and type(jobs[0].get('handle')) is int and jobs[0]['handle']==row['job_handle'] and type(jobs[0].get('raw_return')) is int and jobs[0]['raw_return']!=0 and jobs[0].get('win32_error') is None,'CB01_EXACT_JOB_CLOSE_REQUIRED')
 empty=row['status']=='EMPTY_JOB_OBSERVED_PENDING_CLOSE'
 processes=[r for r in resources if r.get('kind')=='process']
 if empty:
  empty_job(row['accounting'],row['ids']);need(not processes and row.get('root_handle') is None,'CB01_NO_ROOT_RESOURCE_CONTRADICTION')
 else:
  accounting_complete(row['accounting'])
  need(row['phase'] in ROOT_PHASES and row['accounting']['TotalProcesses']==(0 if row['phase']==SUSPENDED else 1),'CB01_PRIOR_JOB_MEMBER_OR_PHASE_UNKNOWN')
  known_domain(row['accounting'],row['ids'],row['root_pid'],False)
  need(len(processes)==1 and type(processes[0].get('handle')) is int and processes[0]['handle']==row['root_handle'] and type(processes[0].get('raw_return')) is int and processes[0]['raw_return']!=0 and processes[0].get('win32_error') is None,'CB01_EXACT_ROOT_CLOSE_REQUIRED')
  need(type(row.get('root_wait_result')) is int and row['root_wait_result']==0 and type(row.get('root_exit_code')) is int and 0<=row['root_exit_code']<=0xffffffff and row['root_exit_code']!=259,'CB01_ROOT_TERMINAL_REQUIRED')
 return {**row,'status':'EMPTY_JOB_CLEANUP_CONFIRMED' if empty else 'KNOWN_ROOT_AND_JOB_TERMINAL_RESOURCES_CLOSED','final_phase':'RESOURCES_CLOSED_NO_ROOT' if empty else TERMINAL,'resource_close_confirmed':True,'containment_qualified':False,'atomic_snapshot':False}
