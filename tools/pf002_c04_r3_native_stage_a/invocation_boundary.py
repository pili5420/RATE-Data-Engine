"""Restricted same-process audit guard; not a general sandbox or runtime attestation."""
import hashlib,re,sys
from pathlib import Path
from contract import KERNEL_APIS,need
import runner_proof
class AuditRefused(runner_proof.Refused):
 def __init__(self,receipt,recorded):
  super().__init__('ONE_FIXED_NATIVE_ROOT_ONLY');self.audit_event='_winapi.CreateProcess';self.pre_dispatch=True;self.receipt=receipt;self.recorded=recorded
def value_type(value):
 for cls,name in ((str,'str'),(type(None),'NoneType'),(bool,'bool'),(int,'int'),(tuple,'tuple'),(bytes,'bytes')):
  if type(value) is cls:return name
 return 'OTHER'
def field_evidence(value,expected):
 same=type(value) is str and value==expected
 length=min(len(value),32769) if type(value) is str else None
 # Never hash an unapproved observed command/path/token. No repr/str or user methods.
 return {'expected_type':'str','observed_type':value_type(value),'exact_match':same,'codepoints_capped_32769':length,'approved_value_utf16le_sha256':hashlib.sha256(expected.encode('utf-16-le')).hexdigest() if same else None,'hash_scope':'EXACT_APPROVED_VALUE_ONLY'}
def current_tool_hashes():
 src=Path(__file__).resolve().parent
 return {'boundary_sha256':hashlib.sha256((src/'invocation_boundary.py').read_bytes()).hexdigest(),'source_manifest_sha256':hashlib.sha256((src/'SOURCE_MANIFEST_V1.json').read_bytes()).hexdigest()}
def check_receipt(row,rejected=False):
 keys={'version','audit_event_id','argument_count','fields','boundary_state','invocation_count','observation_count','exact_predicates','decision','tool_hashes','raw_arguments_exported'}
 need(type(row) is dict and set(row)==keys and all(type(row[k]) is str for k in ('version','audit_event_id','boundary_state','decision')) and row['version']=='CB01_AUDIT_V2' and row['audit_event_id']=='_winapi.CreateProcess' and row['raw_arguments_exported'] is False,'CB01_AUDIT_RECEIPT_SCHEMA')
 n=row['argument_count'];need(n is None or type(n) is int and n>=0,'CB01_AUDIT_ARITY_TYPE')
 need(row['boundary_state'] in ('PREAUTH','STAGE_A','TERMINAL') and type(row['invocation_count']) is int and row['invocation_count'] in (0,1) and type(row['observation_count']) is int and 0<row['observation_count']<=2**31,'CB01_AUDIT_STATE_COUNTS')
 fields=row['fields'];need(type(fields) is dict and set(fields)==(set(('application_name','command_line','current_directory')) if n==3 else set()),'CB01_AUDIT_FIELD_SET')
 for field in fields.values():
  need(type(field) is dict and set(field)=={'expected_type','observed_type','exact_match','codepoints_capped_32769','approved_value_utf16le_sha256','hash_scope'} and field['expected_type']=='str' and field['observed_type'] in ('str','NoneType','bool','int','tuple','bytes','OTHER') and type(field['exact_match']) is bool and field['hash_scope']=='EXACT_APPROVED_VALUE_ONLY','CB01_AUDIT_FIELD_SCHEMA')
  length=field['codepoints_capped_32769'];need((type(length) is int and 0<=length<=32769) if field['observed_type']=='str' else length is None,'CB01_AUDIT_FIELD_LENGTH')
  digest=field['approved_value_utf16le_sha256'];need(field['observed_type']=='str' and 0<length<=32768 and type(digest) is str and re.fullmatch('[0-9a-f]{64}',digest) is not None if field['exact_match'] else digest is None,'CB01_AUDIT_FIELD_HASH')
 checks=row['exact_predicates'];expected={'state_is_STAGE_A':row['boundary_state']=='STAGE_A','invocation_count_is_zero':row['invocation_count']==0,'first_observation':row['observation_count']==1,'argument_tuple_exact_type':n is not None,'argument_count_is_three':n==3,'all_fields_exact':n==3 and all(f['exact_match'] for f in fields.values())}
 need(type(checks) is dict and set(checks)==set(expected) and all(type(v) is bool for v in checks.values()) and checks==expected,'CB01_AUDIT_PREDICATE_CONTRADICTION')
 hashes=row['tool_hashes'];need(type(hashes) is dict and set(hashes)=={'boundary_sha256','source_manifest_sha256'} and all(type(v) is str and re.fullmatch('[0-9a-f]{64}',v) is not None for v in hashes.values()),'CB01_AUDIT_TOOL_HASH_SCHEMA')
 need(row['decision']==('ALLOW' if all(checks.values()) else 'REJECT') and (not rejected or row['decision']=='REJECT') and hashes==current_tool_hashes(),'CB01_AUDIT_DECISION_OR_SOURCE_CONTRADICTION')
 return True
def known_no_dispatch_rejection(row):
 check_receipt(row,True)
 need(row['boundary_state']=='STAGE_A' and row['invocation_count']==0 and row['observation_count']==1,'CB01_PRIOR_CREATE_OR_BOUNDARY_STATE_UNKNOWN')
 return True
class Boundary:
 def __init__(self,executable,command,cwd):
  for value in (executable,command,cwd):
   need(type(value) is str and 0<len(value)<=32768 and '\0' not in value,'FIXED_AUDIT_EXPECTATION_TYPE_BOUND')
   try:raw=value.encode('utf-16-le','strict')
   except UnicodeError:raise runner_proof.Refused('FIXED_AUDIT_EXPECTATION_UNICODE') from None
   need(len(raw)<=65536,'FIXED_AUDIT_EXPECTATION_UTF16_BOUND')
  self.state='PREAUTH';self.executable=executable;self.command=command;self.cwd=cwd;self.creations=0;self.observations=0;self.sink=None;self.last_receipt=None
  self.tool_hashes=current_tool_hashes()
 def bind_evidence(self,sink):
  need(self.state=='PREAUTH' and self.sink is None and callable(sink),'AUDIT_EVIDENCE_BIND_ONCE');self.sink=sink
 def arm(self):need(self.state=='PREAUTH','BOUNDARY_ONE_SHOT');self.state='STAGE_A'
 def stop(self):self.state='TERMINAL'
 def audit(self,event,args):
  try:return self._audit(event,args)
  except BaseException:
   self.state='TERMINAL'
   raise
 def _audit(self,event,args):
  if event.startswith('winreg.') or event=='os.system' or event.startswith(('subprocess.','os.spawn','os.exec')):raise PermissionError('NO_SHELL_REGISTRY_OR_UNCONTROLLED_PROCESS')
  if event.startswith('socket.') and self.state!='PREAUTH':raise PermissionError('NO_NETWORK_AFTER_PREAUTH')
  if event=='_winapi.CreateProcess':
   expected=(self.executable,self.command,self.cwd);arity=len(args) if type(args) is tuple else None
   fields={name:field_evidence(args[i],expected[i]) for i,name in enumerate(('application_name','command_line','current_directory'))} if arity==3 else {}
   checks={'state_is_STAGE_A':self.state=='STAGE_A','invocation_count_is_zero':self.creations==0,'first_observation':self.observations==0,'argument_tuple_exact_type':type(args) is tuple,'argument_count_is_three':arity==3,'all_fields_exact':arity==3 and all(v['exact_match'] for v in fields.values())}
   allowed=all(checks.values());self.observations+=1
   row={'version':'CB01_AUDIT_V2','audit_event_id':'_winapi.CreateProcess','argument_count':arity,'fields':fields,'boundary_state':self.state,'invocation_count':self.creations,'observation_count':self.observations,'exact_predicates':checks,'decision':'ALLOW' if allowed else 'REJECT','tool_hashes':self.tool_hashes.copy(),'raw_arguments_exported':False}
   self.last_receipt=row;recorded=False
   try:
    check_receipt(row)
    if self.sink is not None:self.sink('AUDIT_CREATEPROCESS',row);recorded=True
   except BaseException:raise AuditRefused(row,False) from None
   if not allowed:raise AuditRefused(row,recorded)
   self.creations+=1
  if event=='ctypes.dlopen':need(self.state=='STAGE_A' and args[0] in (None,'kernel32'),'FIXED_STAGE_A_DLL_ONLY')
  if event=='ctypes.dlsym':
   library,name=args;need(self.state=='STAGE_A','NATIVE_BEFORE_AUTH_FORBIDDEN')
   if getattr(library,'_name',None)=='kernel32':need(name in KERNEL_APIS,'FIXED_STAGE_A_API_ONLY')
   else:need(getattr(library,'_name',None) is None and name in ('PyObj_FromPtr','Py_IncRef','Py_DecRef'),'ONLY_REQUIRED_CPYTHON_CTYPES_RUNTIME_SYMBOLS')
 def install(self):sys.addaudithook(self.audit)
