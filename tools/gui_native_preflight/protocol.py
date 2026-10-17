"""Canonical bounded synthetic data; no file-based real Permit loading."""
import hashlib,json,re
from pathlib import Path
from .contracts import RUNTIME_FILES,SCHEMA_FILE
HERE=Path(__file__).resolve().parent
class Blocked(ValueError):
 def __init__(self,reason,state='BLOCKED'):self.state=state;super().__init__(reason)
def require(ok,reason,state='BLOCKED'):
 if not ok:raise Blocked(reason,state)
def exact(value,keys):require(type(value) is dict and set(value)==set(keys),'EXACT_SCHEMA_KEYS')
def uint(value,bits=64,minimum=0):return type(value) is int and minimum<=value<2**bits
def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode('ascii')
def digest(value):return hashlib.sha256(canonical(value)).hexdigest()
def hash64(value):return type(value) is str and re.fullmatch('[0-9a-f]{64}',value) is not None
def rawhex(value,max_bytes):
 require(type(value) is str and len(value)%2==0 and len(value)<=max_bytes*2,'HEX_BOUND')
 data=bytes.fromhex(value);require(data.hex()==value,'CANONICAL_HEX');return data
def decode(data):
 require(type(data) is bytes and len(data)<=4*1024*1024,'BOUNDED_BYTES')
 def pairs(items):
  result={}
  for key,value in items:require(key not in result,'DUPLICATE_KEY');result[key]=value
  return result
 try:out=json.loads(data.decode('utf-8'),object_pairs_hook=pairs,parse_constant=lambda value:(_ for _ in ()).throw(Blocked('NONFINITE_JSON')))
 except (UnicodeError,json.JSONDecodeError) as exc:raise Blocked('MALFORMED_JSON') from exc
 require(canonical(out)==data,'CANONICAL_JSON_REQUIRED');return out
def code_identity():return digest({n:hashlib.sha256((HERE/n).read_bytes()).hexdigest() for n in RUNTIME_FILES})
def schema_identity():return hashlib.sha256((HERE/SCHEMA_FILE).read_bytes()).hexdigest()
def schema_bound():
 data=(HERE/SCHEMA_FILE).read_bytes();return json.loads(data),hashlib.sha256(data).hexdigest()
def check_schema(value,node):
 if 'type' in node:require(type(value) is {'object':dict,'array':list,'integer':int,'string':str,'boolean':bool}[node['type']],'SCHEMA_NATIVE_TYPE')
 if 'const' in node:require(canonical(value)==canonical(node['const']),'SCHEMA_CONST')
 if 'enum' in node:require(any(canonical(value)==canonical(v) for v in node['enum']),'SCHEMA_ENUM')
 if type(value) is dict:
  require(set(node.get('required',[]))<=set(value),'SCHEMA_REQUIRED')
  if node.get('additionalProperties') is False:require(set(value)<=set(node.get('properties',{})),'SCHEMA_EXTRA_FIELD')
  for k,v in value.items():
   if k in node.get('properties',{}):check_schema(v,node['properties'][k])
 if type(value) is list:
  require(node.get('minItems',0)<=len(value)<=node.get('maxItems',10000),'SCHEMA_LIST_BOUND')
  for v in value:check_schema(v,node.get('items',{}))
 if type(value) is str:
  require(len(value)<=node.get('maxLength',4096),'SCHEMA_STRING_BOUND')
  if 'pattern' in node:require(re.fullmatch(node['pattern'],value) is not None,'SCHEMA_PATTERN')
 if type(value) is int:require(node.get('minimum',0)<=value<=node.get('maximum',2**64-1),'SCHEMA_INTEGER_BOUND')
