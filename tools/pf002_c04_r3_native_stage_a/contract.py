"""Pure Stage-A contracts. No Native, credential acquisition or execution authority."""
import hashlib,json,re
from pathlib import PureWindowsPath
import runner_proof as proof
ENV_KEYS={'SystemRoot','WINDIR','PATH','TEMP','TMP','PYTHONDONTWRITEBYTECODE','PF002_PRIVATE_ROOT','PF002_RUNNER_ROOT','PF002_ROLE','PF002_HEAD','PF002_RUN_ID','PF002_RUN_ATTEMPT','PF002_SCOPE','C04_R3_NONCE','PF002_MANIFEST_SHA256'}
SECRET_KEYS=('PF002_R3_API_TOKEN','PF002_R2_API_TOKEN','GITHUB_TOKEN','GH_TOKEN','ACTIONS_ID_TOKEN_REQUEST_TOKEN','ACTIONS_ID_TOKEN_REQUEST_URL')
READY_KEYS={'state','head','role','run_id','attempt','nonce','pid','executable','source_manifest_sha256','worker_source_sha256','credential_variables_absent','NoAutoNext'}
KERNEL_APIS=frozenset(('CreateJobObjectW','SetInformationJobObject','QueryInformationJobObject','AssignProcessToJobObject','TerminateJobObject','ResumeThread','CloseHandle','WaitForSingleObject','GetExitCodeProcess','IsProcessInJob','GetDriveTypeW','GetProcessId','GetProcessTimes','QueryFullProcessImageNameW','GetFileInformationByHandleEx','GetLastError'))
def need(ok,code):proof.need(ok,code)
def canonical(v):return json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()+b'\n'
def context(head,rid,role,nonce):
 need(type(head) is str and re.fullmatch('[0-9a-f]{40}',head) and type(rid) is str and re.fullmatch('[1-9][0-9]{0,19}',rid) and role in ('qualification','reproduction') and type(nonce) is str and re.fullmatch('[0-9a-f]{64}',nonce),'EXACT_STAGE_A_CONTEXT')
def child_environment(systemroot,executable,private,manifest_sha,head,rid,role,nonce,credentials):
 context(head,rid,role,nonce)
 for p in (systemroot,executable,str(private)):
  q=PureWindowsPath(p);need(type(p) is str and q.is_absolute() and not p.startswith(('\\\\','//')) and not any(ord(c)<32 for c in p) and not any(':' in part for part in q.parts[1:]),'CHILD_PHYSICAL_PATH_CONTRACT')
 need(type(manifest_sha) is str and re.fullmatch('[0-9a-f]{64}',manifest_sha),'MANIFEST_HASH')
 tmp=str(PureWindowsPath(str(private))/'tmp');v={'SystemRoot':systemroot,'WINDIR':systemroot,'PATH':str(PureWindowsPath(executable).parent)+';'+str(PureWindowsPath(systemroot)/'System32'),'TEMP':tmp,'TMP':tmp,'PYTHONDONTWRITEBYTECODE':'1','PF002_PRIVATE_ROOT':str(private),'PF002_RUNNER_ROOT':r'D:\a\_temp','PF002_ROLE':role,'PF002_HEAD':head,'PF002_RUN_ID':rid,'PF002_RUN_ATTEMPT':'1','PF002_SCOPE':'STAGE_A_ROOT_ONLY','C04_R3_NONCE':nonce,'PF002_MANIFEST_SHA256':manifest_sha}
 need(set(v)==ENV_KEYS and len({k.upper() for k in v})==len(v) and not any(k.upper() in {x.upper() for x in SECRET_KEYS} for k in v),'EXACT_CHILD_ENVIRONMENT')
 need(all(not credentials.child_reflected(value) for value in v.values()),'CHILD_SECRET_VALUE_REFLECTION')
 return v
def worker_receipt(raw,state,head,rid,role,nonce,pid,executable,manifest_sha,worker_sha):
 context(head,rid,role,nonce);v=proof.strict(raw,16384)
 need(raw==canonical(v) and type(v) is dict and set(v)==READY_KEYS,'WORKER_CANONICAL_SCHEMA')
 need(state in ('READY','COMPLETE') and v['state']==state and v['head']==head and v['run_id']==rid and v['role']==role and v['nonce']==nonce and type(v['attempt']) is int and v['attempt']==1,'WORKER_CONTEXT_BINDING')
 need(type(v['pid']) is int and type(pid) is int and 0<pid<=0xffffffff and v['pid']==pid and v['executable']==executable and v['source_manifest_sha256']==manifest_sha and v['worker_source_sha256']==worker_sha and v['credential_variables_absent'] is True and v['NoAutoNext'] is True,'WORKER_IDENTITY_OR_CREDENTIALS')
 return v
def known_domain(accounting,ids,pid,alive):
 need(type(pid) is int and 0<pid<=0xffffffff and type(alive) is bool,'ROOT_DOMAIN_TYPE')
 expected=[pid] if alive else []
 need(type(accounting) is dict and type(accounting.get('ActiveProcesses')) is int and type(ids) is dict and type(ids.get('pids')) is list and all(type(x) is int for x in ids['pids']),'ROOT_ACCOUNTING_TYPE')
 need(accounting['ActiveProcesses']==len(expected) and ids['pids']==expected and type(ids.get('assigned')) is int and type(ids.get('listed')) is int and ids['assigned']==ids['listed']==len(expected),'UNKNOWN_JOB_MEMBER_OR_ACCOUNTING_HALT')
 return {'authorized_pids':expected,'unknown_members_trusted':False,'no_member_inspection':True}
def root_equivalent(a,b):
 import canonical_file
 for row in (a,b):
  need(all(type(row[k]) is int and row[k]>0 for k in ('pid','handle','creation_time_100ns','wait_result','exit_code')),'ROOT_IDENTITY_STRICT_TYPES')
 need(canonical_file.same_across_process_observations(a,b) and a['handle']==b['handle'] and a['membership_before'] is a['membership_after'] is b['membership_before'] is b['membership_after'] is True and a['wait_result']==b['wait_result']==258 and a['exit_code']==b['exit_code']==259,'ROOT_IDENTITY_INTERVAL_CHANGED')
 return True
def fixed_command(command,executable,worker):
 need(type(command) is list and command==[executable,'-I','-B','-S',str(worker)],'FIXED_WORKER_COMMAND_ONLY')
 return True
def stage_pass(preauth,ready,before,after,complete,exit_code,cleanup,closed):
 need(preauth is True and ready is True and before is True and after is True and complete is True and type(exit_code) is int and exit_code==0 and cleanup is True and closed is True,'INCOMPLETE_STAGE_A_NOT_PASS')
 return {'native_comparator':'PASS','root_identity':'PASS','loaded_image_attestation':False,'RS02':'BLOCKED','NoAutoNext':True}
