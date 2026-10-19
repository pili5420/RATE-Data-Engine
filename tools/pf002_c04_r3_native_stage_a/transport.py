"""Five ordered GETs, distinct short-lived credentials; no body/exception export."""
import base64,os,re,time,urllib.error,urllib.parse,urllib.request
import runner_proof as proof

STAGES=('OIDC_TOKEN','RUN_RECORD','PR87_BASE_REF','CURRENT_TREE','PR87_TREE')
BASE='1d32415ed1c3747b2ed7cba4ac19ccdeaaf78848'
BASE_BRANCH='codex/pf002-c04-r2-preauth-transport-v1'
HEADER_FIELDS={'X-GitHub-Request-Id':'github_request_id','X-RateLimit-Limit':'rate_limit_limit','X-RateLimit-Remaining':'rate_limit_remaining','X-RateLimit-Reset':'rate_limit_reset','Retry-After':'retry_after_seconds'}
class Rejected(ValueError):pass
def need(ok,code):
 if not ok:raise Rejected(code)
def credential(value):
 need(type(value) is str and 20<=len(value)<=8192 and re.fullmatch(r'[A-Za-z0-9._~+/=-]+',value) is not None,'CREDENTIAL_MISSING_OR_INVALID')
 return value
def oidc_endpoint(raw):
 need(type(raw) is str and 0<len(raw)<=8192,'OIDC_ENDPOINT')
 try:u=urllib.parse.urlsplit(raw)
 except ValueError:raise Rejected('OIDC_ENDPOINT') from None
 need(u.scheme=='https' and type(u.hostname) is str and re.fullmatch(r'[a-z0-9.-]{1,253}',u.hostname) and u.hostname.endswith('.actions.githubusercontent.com') and u.port in (None,443) and not u.username and not u.password and not u.fragment and u.path.startswith('/') and not any(c in raw for c in ('\r','\n','\\',' ')),'OIDC_ENDPOINT')
 need(not any(k.lower()=='audience' for k,v in urllib.parse.parse_qsl(u.query)),'OIDC_AUDIENCE_PRESET')
 return raw+('&' if u.query else '?')+'audience='+proof.AUD
class Credentials:
 __slots__=('_api','_oidc','_url','_sensitive','_child_sensitive')
 def __init__(self,api,oidc,url):
  self._api=credential(api);self._oidc=credential(oidc);self._url=oidc_endpoint(url)
  need(self._api!=self._oidc,'CREDENTIAL_CHANNELS_MUST_DIFFER')
  self._sensitive=[];self._child_sensitive=[]
  for value in (self._api,self._oidc):self.add_secret(value)
  for key,value in urllib.parse.parse_qsl(urllib.parse.urlsplit(self._url).query):
   if len(value)>=8:self.add_secret(value,child=key.lower()!='audience')
 @classmethod
 def consume_environment(cls):
  # Pop all three before validation: malformed/missing secrets cannot remain inheritable.
  api=os.environ.pop('PF002_R3_API_TOKEN',None)
  os.environ.pop('PF002_R2_API_TOKEN',None) # discarded alias, never a fallback credential
  oidc=os.environ.pop('ACTIONS_ID_TOKEN_REQUEST_TOKEN',None)
  url=os.environ.pop('ACTIONS_ID_TOKEN_REQUEST_URL',None)
  os.environ.pop('GITHUB_TOKEN',None);os.environ.pop('GH_TOKEN',None)
  return cls(api,oidc,url)
 def __repr__(self):return '<Credentials REDACTED>'
 def headers(self,stage):
  need(stage in STAGES,'STAGE')
  if stage=='OIDC_TOKEN':return {'Authorization':'bearer '+self._oidc}
  return {'Authorization':'Bearer '+self._api,'Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28','User-Agent':'RATE-PF002-C04-R3-preauth-only'}
 def add_secret(self,value,child=True):
  if type(value) is str and 8<=len(value)<=16384:
   raw=value.encode('utf-8');variants=[value.lower(),raw.hex(),base64.b64encode(raw).decode().rstrip('=').lower(),base64.urlsafe_b64encode(raw).decode().rstrip('=').lower()];self._sensitive.extend(variants)
   if child:self._child_sensitive.extend(variants)
 def reflected(self,value):
  if type(value) is not str or len(value)<8:return False
  value=value.lower()
  return any(value[i:i+8] in secret for i in range(len(value)-7) for secret in self._sensitive)
 def clean_diagnostics(self,diag):
  result=dict(diag);blocked=False
  for key,value in result.items():
   if self.reflected(value):result[key]=None;blocked=True
  return result,blocked
 def child_reflected(self,value):
  if type(value) is not str or len(value)<8:return False
  value=value.lower();return any(value[i:i+8] in secret for i in range(len(value)-7) for secret in self._child_sensitive)
 def destroy(self):self._api=None;self._oidc=None;self._url=None;self._sensitive=[];self._child_sensitive=[]

class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*args,**kwargs):raise Rejected('REDIRECT_FORBIDDEN')

def diagnostics(headers,stage):
 result={v:None for v in HEADER_FIELDS.values()};invalid=False
 if stage=='OIDC_TOKEN':return result,False
 for name,key in HEADER_FIELDS.items():
  values=headers.get_all(name) if hasattr(headers,'get_all') else ([headers.get(name)] if headers.get(name) is not None else [])
  if not values:continue
  value=values[0]
  pattern=r'[A-Za-z0-9:-]{1,128}' if key=='github_request_id' else r'(0|[1-9][0-9]{0,11})'
  if len(values)!=1 or type(value) is not str or re.fullmatch(pattern,value) is None:invalid=True;continue
  result[key]=value
 return result,invalid
def category(status,diag,kind):
 if kind in ('INVALID_DIAGNOSTIC_HEADERS','SECRET_REFLECTION_BLOCKED'):return kind
 if status in (403,429) and diag['rate_limit_remaining']=='0':return 'PRIMARY_RATE_LIMIT_HEADER_EVIDENCE'
 if status==401:return 'AUTHENTICATION_REJECTED'
 if status==403:return 'ACCESS_OR_POLICY_REJECTED_UNDETERMINED'
 if status==429:return 'RATE_LIMIT_STATUS_CAUSE_UNDETERMINED'
 return kind

class Transport:
 def __init__(self,head,run_id,credentials,emit,opener=None,clock=time.monotonic):
  need(type(head) is str and re.fullmatch('[0-9a-f]{40}',head) and type(run_id) is str and re.fullmatch('[1-9][0-9]{0,19}',run_id),'REQUEST_CONTEXT')
  need(type(credentials) is Credentials,'CREDENTIAL_BOUNDARY')
  self.head=head;self.run_id=run_id;self.credentials=credentials;self.emit=emit;self.clock=clock;self.deadline=clock()+60
  self.records=[];self.state='ACTIVE';self.index=0
  # No Windows proxy/Registry discovery and no automatic HTTP redirect handler.
  self.opener=opener if opener is not None else urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
 def endpoint(self,stage):
  need(stage in STAGES,'STAGE')
  if stage=='OIDC_TOKEN':return self.credentials._url
  paths={'RUN_RECORD':'actions/runs/'+self.run_id,'PR87_BASE_REF':'git/ref/heads/'+BASE_BRANCH,'CURRENT_TREE':'git/trees/'+self.head+'?recursive=1','PR87_TREE':'git/trees/'+BASE+'?recursive=1'}
  return 'https://api.github.com/repos/'+proof.REPO+'/'+paths[stage]
 def fetch(self,stage):
  try:return self._fetch(stage)
  except BaseException:
   # Preconditions and evidence writes are part of the attempt, never a retryable prelude.
   self.state='HALTED'
   raise
 def _fetch(self,stage):
  need(self.state=='ACTIVE' and self.index<5 and stage==STAGES[self.index],'ORDERED_ONE_SHOT_NO_RETRY')
  need(self.clock()<self.deadline,'PREAUTH_DEADLINE')
  self.index+=1
  url=self.endpoint(stage);host=urllib.parse.urlsplit(url).hostname
  start={'fixed_request_stage':stage,'endpoint_host':host,'fixed_path_id':stage+'_FIXED_ENDPOINT'}
  self.emit('PREAUTH_HTTP_START',start)
  status=None;diag={v:None for v in HEADER_FIELDS.values()};kind='UNEXPECTED_TRANSPORT_ERROR'
  try:
   request=urllib.request.Request(url,headers=self.credentials.headers(stage),method='GET')
   response=self.opener.open(request,timeout=min(10,max(0.001,self.deadline-self.clock())))
   with response:
    status=response.getcode();diag,invalid=diagnostics(response.headers,stage);diag,reflected=self.credentials.clean_diagnostics(diag)
    need(not reflected,'SECRET_REFLECTION_BLOCKED')
    need(not invalid,'INVALID_DIAGNOSTIC_HEADERS')
    need(type(status) is int and status==200 and response.url==url,'HTTP_STATUS_OR_REDIRECT')
    bound=32768 if stage=='OIDC_TOKEN' else 1048576
    raw=response.read(bound+1);need(type(raw) is bytes and len(raw)<=bound,'RESPONSE_BYTE_BOUND')
   result=proof.strict(raw,bound);need(self.clock()<self.deadline,'PREAUTH_DEADLINE')
   if stage=='OIDC_TOKEN' and type(result) is dict:self.credentials.add_secret(result.get('value'))
  except Exception as exc:
   if isinstance(exc,urllib.error.HTTPError):
    status=exc.code if type(exc.code) is int and 100<=exc.code<=599 else None
    diag,invalid=diagnostics(exc.headers or {},stage);diag,reflected=self.credentials.clean_diagnostics(diag);kind='SECRET_REFLECTION_BLOCKED' if reflected else 'INVALID_DIAGNOSTIC_HEADERS' if invalid else 'HTTP_STATUS_ERROR'
    exc.close()  # Never read the error body.
   elif isinstance(exc,Rejected):kind=str(exc) if str(exc) in ('INVALID_DIAGNOSTIC_HEADERS','HTTP_STATUS_OR_REDIRECT','RESPONSE_BYTE_BOUND','PREAUTH_DEADLINE','REDIRECT_FORBIDDEN','SECRET_REFLECTION_BLOCKED') else 'REQUEST_REJECTED'
   elif isinstance(exc,proof.Refused):kind='RESPONSE_JSON_REJECTED'
   elif isinstance(exc,(TimeoutError,urllib.error.URLError,OSError)):kind='BOUNDED_TRANSPORT_ERROR'
   self.state='HALTED';self.record(stage,host,status,diag,category(status,diag,kind),'HALT')
   raise Rejected('PREAUTH_HTTP_HALTED') from None
  self.record(stage,host,status,diag,'RESPONSE_PARSED_NOT_AUTHORIZATION','RESPONSE_PARSED_NOT_AUTHORIZATION')
  if self.index==5:self.state='COMPLETE'
  return result
 def record(self,stage,host,status,diag,kind,outcome):
  row={'fixed_request_stage':stage,'endpoint_host':host,'fixed_path_id':stage+'_FIXED_ENDPOINT','http_status':status,'safe_error_category':kind,'outcome':outcome,**diag}
  self.records.append(row);self.emit('PREAUTH_HTTP_RESULT',row)
 def halt(self):self.state='HALTED'
