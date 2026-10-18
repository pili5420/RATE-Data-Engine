"""One request per fixed stage. Export only enum/host/status, never exception text."""
import re,urllib.error,urllib.parse,urllib.request
import runner_proof as proof
STAGES=('OIDC_TOKEN','RUN_RECORD','PR84_BASE_REF','CURRENT_TREE','PR84_TREE')
RESULT_KEYS={'fixed_request_stage','endpoint_host','fixed_path_id','http_status','error_type','nonsecret_error_code','outcome'}
def safe_status(value):return value if type(value) is int and 100<=value<=599 else None
def validate_record(row):
 proof.need(type(row) is dict and set(row)==RESULT_KEYS,'RECEIPT_EXACT_FIELDS')
 stage=row['fixed_request_stage'];proof.need(type(stage) is str and stage in STAGES,'RECEIPT_STAGE')
 host=row['endpoint_host'];path=row['fixed_path_id']
 if stage=='OIDC_TOKEN':proof.need(type(host) is str and re.fullmatch('[a-z0-9.-]{1,253}',host) and host.endswith('.actions.githubusercontent.com') and path=='GITHUB_ACTIONS_OIDC_REQUEST_PATH_NOT_EXPORTED','RECEIPT_HOST')
 else:proof.need(host=='api.github.com' and path==stage+'_FIXED_PUBLIC_PATH','RECEIPT_HOST')
 proof.need(row['http_status'] is None or safe_status(row['http_status'])==row['http_status'] and type(row['http_status']) is int,'RECEIPT_STATUS')
 pairs={('HTTPError','HTTP_STATUS_ERROR'),('URLError','TRANSPORT_ERROR'),('TimeoutError','REQUEST_TIMEOUT'),('Refused','REQUEST_OR_RESPONSE_REJECTED'),('OSError','TRANSPORT_OS_ERROR'),('UnexpectedError','UNEXPECTED_REQUEST_ERROR')}
 if row['outcome']=='HALT':proof.need((row['error_type'],row['nonsecret_error_code']) in pairs,'RECEIPT_ERROR')
 else:proof.need(row['outcome']=='RESPONSE_PARSED_NOT_AUTHORIZATION' and row['http_status']==200 and row['error_type'] is None and row['nonsecret_error_code'] is None,'RECEIPT_SUCCESS')
 return dict(row)
class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*args,**kwargs):raise proof.Refused('HTTPS_REDIRECT_FORBIDDEN')
def safe_error(exc):
 if isinstance(exc,urllib.error.HTTPError):return 'HTTPError','HTTP_STATUS_ERROR'
 if isinstance(exc,urllib.error.URLError):return 'URLError','TRANSPORT_ERROR'
 if isinstance(exc,TimeoutError):return 'TimeoutError','REQUEST_TIMEOUT'
 if isinstance(exc,proof.Refused):return 'Refused','REQUEST_OR_RESPONSE_REJECTED'
 if isinstance(exc,OSError):return 'OSError','TRANSPORT_OS_ERROR'
 return 'UnexpectedError','UNEXPECTED_REQUEST_ERROR'
class Transport:
 def __init__(self,head,runid,emit,opener=None):
  proof.need(type(head) is str and re.fullmatch('[0-9a-f]{40}',head) and type(runid) is str and runid.isascii() and runid.isdigit(),'REQUEST_CONTEXT')
  self.head=head;self.runid=runid;self.emit=emit;self.seen=set();self.records=[]
  # Never discover environment/system proxies (Windows discovery may read Registry).
  self.opener=opener if opener is not None else urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
 def endpoint(self,stage,url):
  proof.need(stage in STAGES and type(url) is str,'FIXED_REQUEST_STAGE')
  u=urllib.parse.urlparse(url)
  proof.need(u.scheme=='https' and not u.username and not u.password and not u.fragment and u.port in (None,443),'FIXED_HTTPS_BOUNDARY')
  if stage=='OIDC_TOKEN':
   proof.need(type(u.hostname) is str and re.fullmatch('[a-z0-9.-]{1,253}',u.hostname) and u.hostname.endswith('.actions.githubusercontent.com'),'FIXED_OIDC_HOST')
   return u.hostname,'GITHUB_ACTIONS_OIDC_REQUEST_PATH_NOT_EXPORTED'
  paths={'RUN_RECORD':'/repos/'+proof.REPO+'/actions/runs/'+self.runid,
         'PR84_BASE_REF':'/repos/'+proof.REPO+'/git/ref/heads/codex/pf002-c03-forensic-evidence-v1',
         'CURRENT_TREE':'/repos/'+proof.REPO+'/git/trees/'+self.head,
         'PR84_TREE':'/repos/'+proof.REPO+'/git/trees/3b3107786da0a3ba54705f6b24ba7b68a2a056e6'}
  proof.need(u.hostname=='api.github.com' and u.path==paths[stage] and u.query==('recursive=1' if stage.endswith('TREE') else ''),'FIXED_PUBLIC_ENDPOINT')
  return 'api.github.com',stage+'_FIXED_PUBLIC_PATH'
 def record(self,stage,host,path,status,error,code,outcome):
  row=validate_record({'fixed_request_stage':stage,'endpoint_host':host,'fixed_path_id':path,'http_status':safe_status(status),'error_type':error,'nonsecret_error_code':code,'outcome':outcome})
  self.records.append(row);self.emit('PREAUTH_HTTP_RESULT',row)
 def fetch(self,stage,url,headers=None,bound=1048576):
  host,path=self.endpoint(stage,url)
  proof.need(stage not in self.seen and type(bound) is int and 0<bound<=1048576,'ONE_REQUEST_PER_STAGE_NO_RETRY')
  self.seen.add(stage)
  self.emit('PREAUTH_HTTP_START',{'fixed_request_stage':stage,'endpoint_host':host,'fixed_path_id':path})
  status=None
  try:
   req=urllib.request.Request(url,headers=headers or {})
   with self.opener.open(req,timeout=10) as response:
    status=response.getcode();proof.need(type(status) is int and status==200 and response.url==url,'HTTP_STATUS_OR_REDIRECT')
    raw=response.read(bound+1);proof.need(len(raw)<=bound,'HTTPS_BYTE_BOUND')
   result=proof.strict(raw,bound)
  except Exception as exc:
   if isinstance(exc,urllib.error.HTTPError):status=exc.code if type(exc.code) is int and 100<=exc.code<=599 else None
   kind,code=safe_error(exc);self.record(stage,host,path,status,kind,code,'HALT')
   raise
  self.record(stage,host,path,status,None,None,'RESPONSE_PARSED_NOT_AUTHORIZATION')
  return result

def receipt(head,role,runid,records,authenticated,failed):
 proof.need(re.fullmatch('[0-9a-f]{40}',head) and role in ('qualification','reproduction') and runid.isascii() and runid.isdigit(),'RECEIPT_CONTEXT')
 proof.need(type(authenticated) is bool and type(failed) is bool and type(records) is list and len(records)<=5,'RECEIPT_BOUND')
 records=[validate_record(r) for r in records]
 proof.need(len({r['fixed_request_stage'] for r in records})==len(records),'RECEIPT_DUPLICATE_STAGE')
 return {'version':'C04_PREAUTH_DIAGNOSTIC_V1','source_head':head,'workflow':'.github/workflows/rate_pf002_c04_semantic.yml',
         'run_id':runid,'attempt':1,'role':role,'requests':records,'authentication_completed':authenticated,
         'fail_closed_reason':'PREAUTHORIZATION_HALTED' if failed else 'NO_NATIVE_AUTHORITY_FROM_RECEIPT',
         'receipt_is_execution_authorization':False,'retry':False,'resume':False,'fallback':False}
