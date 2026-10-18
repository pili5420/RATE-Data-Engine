"""Pure runner provenance validation; no Windows calls, token minting, consent or network here."""
import base64,hashlib,hmac,json,re
ISS='https://token.actions.githubusercontent.com'
AUD='rate-pf-personal-002-runner-only'
REPO='pili5420/RATE-Data-Engine'
BRANCH='codex/pf-personal-readonly-collector-v1'
REF='refs/heads/'+BRANCH
WORKFLOW=REPO+'/.github/workflows/rate_pf_personal_collector.yml@'+REF
JWKS_SHA='5f8164c9696c27837ad18c5fe7c7022a433bd5390183e8ff15c74d82233270f4'
class Refused(ValueError):pass
def need(ok,why):
 if not ok:raise Refused(why)
def strict(raw,max_bytes=65536):
 need(type(raw) is bytes and 0<len(raw)<=max_bytes,'JSON_BYTE_BOUND')
 def pairs(items):
  d={}
  for k,v in items:need(k not in d,'DUPLICATE_KEY');d[k]=v
  return d
 def bad(_):raise Refused('NONFINITE')
 try:return json.loads(raw.decode('utf-8','strict'),object_pairs_hook=pairs,parse_constant=bad)
 except (UnicodeError,ValueError,RecursionError):raise Refused('JSON_INVALID') from None
def b64(v):
 need(type(v) is str and re.fullmatch('[A-Za-z0-9_-]+',v) is not None,'BASE64URL')
 try:b=base64.b64decode(v.replace('-','+').replace('_','/')+'='*((-len(v))%4),validate=True)
 except ValueError:raise Refused('BASE64URL') from None
 need(base64.urlsafe_b64encode(b).decode().rstrip('=')==v,'BASE64URL_CANONICAL')
 return b
def verify_token(token,jwks_raw,now,head,run_id,attempt):
 need(type(token) is str and len(token)<=16384 and token.count('.')==2,'SIGNED_RUNNER_PROOF_REQUIRED')
 need(hashlib.sha256(jwks_raw).hexdigest()==JWKS_SHA,'PINNED_GITHUB_KEYS_REQUIRED')
 h,p,s=token.split('.');header=strict(b64(h));claims=strict(b64(p))
 need(type(header) is dict and set(header)<=set(('alg','kid','typ','x5t')) and header.get('alg')=='RS256' and header.get('typ')=='JWT','JOSE_HEADER')
 keys=strict(jwks_raw)['keys'];matched=[k for k in keys if k.get('kid')==header.get('kid')]
 need(len(matched)==1,'UNKNOWN_OR_AMBIGUOUS_KEY_NO_REFRESH')
 k=matched[0];need(k['kty']=='RSA' and k.get('use')=='sig' and k.get('alg','RS256')=='RS256','RSA_KEY')
 n,e=int.from_bytes(b64(k['n']),'big'),int.from_bytes(b64(k['e']),'big')
 need(2048<=n.bit_length()<=4096 and e==65537,'RSA_STRENGTH')
 sig=b64(s);size=(n.bit_length()+7)//8
 need(len(sig)==size and int.from_bytes(sig,'big')<n,'RSA_SIGNATURE_SIZE')
 encoded=pow(int.from_bytes(sig,'big'),e,n).to_bytes(size,'big')
 der=bytes.fromhex('3031300d060960864801650304020105000420')+hashlib.sha256((h+'.'+p).encode('ascii')).digest()
 expected=b'\0\1'+b'\xff'*(size-len(der)-3)+b'\0'+der
 need(hmac.compare_digest(encoded,expected),'RUNNER_SIGNATURE')
 return check_claims(claims,now,head,run_id,attempt)
def check_claims(c,now,head,run_id,attempt):
 need(type(c) is dict and type(now) is int,'CLAIMS_TYPE')
 exact={'iss':ISS,'aud':AUD,'repository':REPO,'repository_id':'1370145728',
 'repository_owner_id':'325481386','ref':REF,'event_name':'push','runner_environment':'github-hosted',
 'workflow_ref':WORKFLOW,'sha':head,'workflow_sha':head,'run_id':run_id,'run_attempt':attempt}
 need(type(head) is str and re.fullmatch('[0-9a-f]{40}',head) is not None,'EXACT_HEAD')
 need(type(run_id) is str and run_id.isascii() and run_id.isdigit() and int(run_id)>0 and attempt=='1','FRESH_RUN_ATTEMPT_ONLY')
 for k,v in exact.items():need(type(c.get(k)) is str and c[k]==v,'CLAIM_'+k)
 # Both documented GitHub subject encodings bind the same literal repository/ref and immutable IDs.
 subjects=(f'repo:{REPO}:ref:{REF}',f'repo:pili5420@325481386/RATE-Data-Engine@1370145728:ref:{REF}')
 need(c.get('sub') in subjects,'SUBJECT_BINDING')
 for k in ('iat','nbf','exp'):need(type(c.get(k)) is int,'TIME_TYPE')
 need(c['nbf']<=now<c['exp'] and c['iat']<=now and 0<c['exp']-c['iat']<=900 and now-c['iat']<=600,'RUNNER_PROOF_TIME')
 return {k:c[k] for k in exact} # selected nonsecret provenance only; never token/signature/jti

