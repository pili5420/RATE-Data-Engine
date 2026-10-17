"""Closed canonical data protocols. These models are NOT live Execution Permits."""
import hashlib,json,re
from pathlib import Path,PureWindowsPath
from .contracts import KIND,SCOPE,RUNTIME_FILES
HERE=Path(__file__).resolve().parent
class Denied(ValueError):
 def __init__(self,reason,state='BLOCKED'):
  self.reason,self.state=reason,state;super().__init__(reason)
def need(ok,reason,state='BLOCKED'):
 if not ok:raise Denied(reason,state)
def exact(x,keys):need(type(x) is dict and set(x)==set(keys),'EXACT_KEYS')
def integer(x,lo=0,hi=2**64):return type(x) is int and lo<=x<hi
def canonical(x):return json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode('ascii')
def digest(x):return hashlib.sha256(canonical(x)).hexdigest()
def hash64(x):return type(x) is str and re.fullmatch('[0-9a-f]{64}',x) is not None
def decode(raw):
 need(type(raw) is bytes and len(raw)<=4*1024*1024,'BOUNDED_BYTES')
 def pairs(items):
  out={}
  for k,v in items:need(k not in out,'DUPLICATE_KEY');out[k]=v
  return out
 try:x=json.loads(raw.decode('utf-8'),object_pairs_hook=pairs,parse_constant=lambda x:(_ for _ in ()).throw(Denied('NONFINITE_JSON')))
 except (UnicodeError,json.JSONDecodeError) as exc:raise Denied('MALFORMED_JSON') from exc
 need(canonical(x)==raw,'CANONICAL_JSON_REQUIRED');return x
def code_identity():return digest({n:hashlib.sha256((HERE/n).read_bytes()).hexdigest() for n in RUNTIME_FILES})
def schema_identity():return hashlib.sha256((HERE/'NATIVE_IDENTITY_SCHEMA_V1.json').read_bytes()).hexdigest()

def bound_schema():
 raw=(HERE/'NATIVE_IDENTITY_SCHEMA_V1.json').read_bytes();return json.loads(raw),hashlib.sha256(raw).hexdigest()
def schema_check(value,node,root=None):
 root=node if root is None else root
 if '$ref' in node:return schema_check(value,root['$defs'][node['$ref'].split('/')[-1]],root)
 if 'const' in node:need(canonical(value)==canonical(node['const']),'SCHEMA_CONST_NATIVE_TYPE')
 if 'enum' in node:need(any(canonical(value)==canonical(x) for x in node['enum']),'SCHEMA_ENUM')
 if 'type' in node:need(type(value) is {'object':dict,'array':list,'string':str,'integer':int,'boolean':bool,'null':type(None)}[node['type']],'SCHEMA_NATIVE_TYPE')
 if type(value) is dict:
  need(set(node.get('required',[]))<=set(value),'SCHEMA_REQUIRED')
  if node.get('additionalProperties') is False:need(set(value)<=set(node.get('properties',{})),'SCHEMA_ADDITIONAL')
  for k,v in value.items():
   if k in node.get('properties',{}):schema_check(v,node['properties'][k],root)
 if type(value) is list:
  need(len(value)<=node.get('maxItems',1000000),'SCHEMA_ARRAY_BOUND')
  for v in value:schema_check(v,node.get('items',{}),root)
 if 'pattern' in node:need(re.fullmatch(node['pattern'],value) is not None,'SCHEMA_PATTERN')
 if 'minimum' in node:need(value>=node['minimum'],'SCHEMA_MINIMUM')
 if 'maximum' in node:need(value<=node['maximum'],'SCHEMA_MAXIMUM')
def windows_path(value,extended=False):
 need(type(value) is str and value,'PATH_STRING')
 if extended and value.startswith('\\\\?\\'):value=value[4:]
 p=PureWindowsPath(value)
 need(not value.startswith('\\\\') and p.is_absolute() and re.fullmatch('[A-Za-z]:',p.drive) is not None and str(p)==value and '..' not in p.parts and '/' not in value,'CANONICAL_LOCAL_DOS_PATH')
 need(':' not in value[2:] and not any(x.endswith((' ','.')) for x in p.parts[1:]),'PATH_ALIAS_OR_ADS')
 return str(p)
MODEL_KEYS={'artifact_kind','stage','attempt_id','nonce','issued_tick_ns','expires_tick_ns','tool_sha256','schema_sha256','scope','scope_sha256','provider_sha256','witness_sha256','witness_pre_head','witness_final_head','workspace','evidence_root','journal_root'}
def validate_model(x,workspace,provider_sha,witness_sha):
 schema,schema_sha=bound_schema();schema_check(x,schema)
 exact(x,MODEL_KEYS);need(x['artifact_kind']==KIND and x['stage']=='IDENTITY_ONLY','NO_LIVE_PERMIT_OR_DIAGNOSTIC_MODEL')
 for k in ['attempt_id','nonce']:need(type(x[k]) is str and re.fullmatch('SYNTHETIC-[A-Za-z0-9-]{8,96}',x[k]) is not None,'SYNTHETIC_ATTEMPT_NONCE_ONLY')
 need(integer(x['issued_tick_ns'],1) and integer(x['expires_tick_ns'],1) and x['issued_tick_ns']<x['expires_tick_ns'],'MODEL_TIME_WINDOW')
 need(x['tool_sha256']==code_identity() and x['schema_sha256']==schema_sha,'EXACT_TOOL_SCHEMA_BINDING')
 s=x['scope'];exact(s,{'read_boundary','policy','observer','max_windows','max_file_bytes','chunk_bytes','max_calls','per_call_ms','total_ms'})
 need(canonical(s['read_boundary'])==canonical(SCOPE) and digest(s)==x['scope_sha256'],'EXACT_READ_SCOPE_BINDING')
 policy=s['policy'];exact(policy,{'host','session_id','desktop','observer_station','executable_path','executable_sha256','volume_serial','file_id','class_name','boot_id'})
 need(policy['host']=='SYNTHETIC-HOST-ONLY' and type(policy['boot_id']) is str and policy['boot_id'].startswith('SYNTHETIC-'),'SYNTHETIC_HOST_BOOT_ONLY')
 for k in ['desktop','observer_station','class_name']:need(type(policy[k]) is str and 0<len(policy[k])<=256,'POLICY_STRING')
 need(integer(policy['session_id'],1,2**32),'SESSION_NATIVE_INTEGER');windows_path(policy['executable_path'])
 need(hash64(policy['executable_sha256']) and type(policy['volume_serial']) is str and re.fullmatch('[0-9a-f]{16}',policy['volume_serial']) is not None and type(policy['file_id']) is str and re.fullmatch('[0-9a-f]{32}',policy['file_id']) is not None,'FILE_IDENTITY_PINS')
 observer=s['observer'];exact(observer,{'pid','tid','parent_pid','creation','parent_creation','origin'})
 need(observer['origin']=='SYNTHETIC_OWNER_HANDOFF_NOT_NATIVE_PROVENANCE' and all(integer(observer[k],1,2**32) for k in ['pid','tid','parent_pid']) and all(integer(observer[k],1) for k in ['creation','parent_creation']),'OBSERVER_HANDOFF')
 for k,lo,hi in [('max_windows',1,129),('max_file_bytes',1,16*1024*1024+1),('chunk_bytes',1,65537),('max_calls',1,20001),('per_call_ms',1,5001),('total_ms',1,60001)]:need(integer(s[k],lo,hi),'BOUNDED_SCOPE:'+k)
 need(s['per_call_ms']<=s['total_ms'],'BOUNDED_SCOPE:deadline')
 need(x['provider_sha256']==provider_sha and x['witness_sha256']==witness_sha and hash64(x['witness_pre_head']) and hash64(x['witness_final_head']),'EXTERNAL_PROVIDER_WITNESS_PINS')
 need(x['workspace']==str(workspace.root) and x['journal_root']==str(workspace.journal) and x['evidence_root']==str(workspace.evidence/x['attempt_id']),'EXACT_PHYSICAL_ROOT_BINDING')
 workspace.verify();return x
