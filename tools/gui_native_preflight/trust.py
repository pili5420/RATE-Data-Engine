"""Public-key verification for a strictly synthetic namespace, no signing/loader.

Ed25519 uses the preinstalled pinned PyCA package; no ctypes/Windows API binding.
All public roots must be independent ephemeral TEST roles. This is not a real
issuer/root, host attestation service, or live authorization capability.
"""
import copy,re
import cryptography
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from .contracts import *
from .protocol import require,exact,uint,rawhex,canonical,digest,hash64,code_identity,schema_bound,check_schema
require(cryptography.__version__=='50.0.2','PINNED_CRYPTOGRAPHY_50_0_2_REQUIRED')
def signed_bytes(kind,role,payload):return b'RATE-NQ-SYNTHETIC-ED25519-V1\0'+canonical({'realm':REALM,'kind':kind,'role':role,'payload':payload})
class SyntheticTrust:
 def __init__(self,bundle):
  exact(bundle,{'realm','origin','keys'});require(bundle['realm']==REALM and bundle['origin']=='SYNTHETIC_EPHEMERAL_INDEPENDENT_TEST_KEYS','NO_PRODUCTION_TRUST_ROOT')
  require(type(bundle['keys']) is list and len(bundle['keys'])==len(ROLES),'INDEPENDENT_ROLE_KEY_COUNT');self.bundle=copy.deepcopy(bundle);self.pin=digest(bundle);self.keys={};roles=set();pubs=set()
  for key in bundle['keys']:
   exact(key,{'id','role','public_hex'});require(type(key['id']) is str and key['id'].startswith('SYNTHETIC-') and key['id'] not in self.keys and key['role'] in set(ROLES.values()) and key['role'] not in roles,'KEY_ID_OR_ROLE')
   public=rawhex(key['public_hex'],32);require(len(public)==32 and public not in pubs,'SHARED_OR_INVALID_ROLE_KEY');pubs.add(public);roles.add(key['role']);self.keys[key['id']]=dict(key)
  self.key_pin=digest(self.keys)
 def verify(self,envelope,kind):
  require(digest(self.bundle)==self.pin and digest(self.keys)==self.key_pin,'TRUST_BUNDLE_MUTATED');exact(envelope,{'version','realm','kind','role','signer','payload','signature_hex'})
  require(type(envelope['version']) is int and envelope['version']==1 and envelope['realm']==REALM and envelope['kind']==kind and kind in ROLES and envelope['role']==ROLES[kind],'SIGNATURE_PURPOSE_OR_REALM')
  require(envelope['signer'] in self.keys and self.keys[envelope['signer']]['role']==ROLES[kind],'SIGNER_ROLE_SEPARATION');signature=rawhex(envelope['signature_hex'],64);require(len(signature)==64,'ED25519_SIGNATURE_LENGTH')
  key=self.keys[envelope['signer']]
  try:Ed25519PublicKey.from_public_bytes(bytes.fromhex(key['public_hex'])).verify(signature,signed_bytes(kind,ROLES[kind],envelope['payload']))
  except InvalidSignature as exc:raise ValueError('INVALID_ED25519_SIGNATURE') from exc
  return copy.deepcopy(envelope['payload'])

HOST_KEYS={'source','host','boot','session','desktop','station','operator_sid','observer_pid','observer_tid','observer_creation','parent_pid','parent_creation','operator_token','clock_domain','utc_ns'}
def host_identity(payload):
 exact(payload,HOST_KEYS);require(payload['source']=='SYNTHETIC_HOST_ORACLE_NOT_NATIVE_ATTESTATION','UNTRUSTED_HOST_SOURCE')
 for k in ['host','boot','clock_domain']:require(type(payload[k]) is str and re.fullmatch('SYNTHETIC-[A-Za-z0-9-]{1,128}',payload[k]) is not None,'HOST_BOOT_CLOCK_NAMESPACE')
 for k in ['session','observer_pid','observer_tid','parent_pid']:require(uint(payload[k],32,1),'HOST_PROCESS_SESSION_TYPE')
 for k in ['observer_creation','parent_creation','utc_ns']:require(uint(payload[k],64,1),'HOST_TIME_TYPE')
 for k in ['desktop','station','operator_sid']:require(type(payload[k]) is str and 0<len(payload[k])<=256 and '\0' not in payload[k],'HOST_STRING')
 require(re.fullmatch(r'S-1-[0-9]+(?:-[0-9]+){1,15}',payload['operator_sid']) is not None,'OPERATOR_SID_CANONICAL')
 parts=payload['operator_sid'].split('-');require(int(parts[2])<2**48 and all(int(v)<2**32 and str(int(v))==v for v in parts[3:]) and str(int(parts[2]))==parts[2],'OPERATOR_SID_RANGE_OR_ALIAS')
 t=payload['operator_token'];exact(t,{'elevated','elevation_type','integrity_sid','admin_enabled','deny_only'})
 require(t['elevated'] is True and type(t['elevation_type']) is int and t['elevation_type']==2 and t['admin_enabled'] is True and t['deny_only'] is False and t['integrity_sid']=='S-1-16-12288','OPERATOR_ADMIN_FULL_HIGH_MODEL_REQUIRED')
 return payload

class Admission:
 """Verified synthetic claims; a process-local DTO, never a native capability."""
 def __init__(self,payload,host,trust_pin,revocations):self.payload=copy.deepcopy(payload);self.host=copy.deepcopy(host);self.trust_pin=trust_pin;self.revocations=copy.deepcopy(revocations);self.pin=digest({'payload':payload,'host':host,'trust':trust_pin,'revocations':revocations})
 def unchanged(self):require(self.pin==digest({'payload':self.payload,'host':self.host,'trust':self.trust_pin,'revocations':self.revocations}),'ADMISSION_MUTATED')

def verify_identity_model(trust,envelope,host_envelope,revocations,expected):
 require(type(trust) is SyntheticTrust,'SEALED_SYNTHETIC_TRUST');exact(expected,{'scope_sha256','host_sha256','transport_sha256','revocation_epoch','revocation_sha256','workspace','now_utc_ns'})
 require(all(hash64(expected[k]) for k in ['scope_sha256','host_sha256','transport_sha256','revocation_sha256']) and uint(expected['revocation_epoch'],64,1) and type(expected['workspace']) is str,'EXTERNAL_PINS_NATIVE_TYPES')
 schema,pin=schema_bound();model=trust.verify(envelope,MODEL_KIND);check_schema(model,schema)
 exact(model,{'artifact_kind','realm','stage','attempt_id','nonce','issuer_sequence','issued_utc_ns','expires_utc_ns','tool_sha256','schema_sha256','scope','scope_sha256','host_sha256','transport_sha256','revocation_epoch','revocation_sha256','witness_anchor_sha256','workspace','native_execution_authorized','diagnostic_authorized'})
 require(model['artifact_kind']==MODEL_KIND and model['realm']==REALM and model['stage']=='IDENTITY_ONLY' and model['native_execution_authorized'] is False and model['diagnostic_authorized'] is False,'NO_LIVE_OR_DIAGNOSTIC_AUTHORITY')
 for k in ['attempt_id','nonce']:require(type(model[k]) is str and model[k].startswith('SYNTHETIC-') and 16<=len(model[k])<=96,'SYNTHETIC_ATTEMPT_NONCE')
 require(uint(model['issuer_sequence'],64,1),'ISSUER_SEQUENCE_TYPE')
 require(model['tool_sha256']==code_identity() and model['schema_sha256']==pin,'EXACT_TOOL_SCHEMA')
 require(hash64(model['witness_anchor_sha256']),'WITNESS_ANCHOR_PIN')
 require(model['transport_sha256']==expected['transport_sha256'],'EXTERNAL_TRANSPORT_PIN')
 scope=model['scope'];exact(scope,{'boundary','abi','target','max_calls','per_call_ns','total_ns','evidence_root','journal_root'})
 require(canonical(scope['boundary'])==canonical(BOUNDARY) and scope['abi'] in {'win32','win64'} and uint(scope['max_calls'],32,1) and scope['max_calls']<=64 and uint(scope['per_call_ns'],64,1) and uint(scope['total_ns'],64,1) and scope['per_call_ns']<=scope['total_ns']<=60_000_000_000,'EXACT_READ_BOUNDARY_AND_BOUNDS')
 require(hash64(model['scope_sha256']) and digest(scope)==model['scope_sha256']==expected['scope_sha256'] and model['workspace']==expected['workspace'],'EXTERNAL_SCOPE_ROOT_PIN')
 host=host_identity(trust.verify(host_envelope,HOST_KIND));require(digest(host)==model['host_sha256']==expected['host_sha256'],'HOST_BINDING_MISMATCH')
 target=scope['target'];exact(target,{'host','boot','session','desktop','station','operator_sid','pid','creation','hwnd','tid','class_name','executable_path','executable_sha256','file_id','generation'})
 for k in ['host','boot','session','desktop','station','operator_sid']:require(type(target[k]) is type(host[k]) and target[k]==host[k],'HOST_BOOT_SESSION_OPERATOR_MISMATCH')
 for k in ['pid','tid']:require(uint(target[k],32,1),'TARGET_PROCESS_TYPE')
 for k in ['hwnd','generation','creation']:require(uint(target[k],64,1),'TARGET_IDENTITY_TYPE')
 require(hash64(target['executable_sha256']) and type(target['file_id']) is str and len(rawhex(target['file_id'],16))==16 and type(target['class_name']) is str and target['class_name']=='#32770' and type(target['executable_path']) is str and target['executable_path']==r'C:\SYNTHETIC-NQ\Fixture.exe','SYNTHETIC_EXECUTABLE_TARGET')
 now=expected['now_utc_ns'];require(uint(now,64,1) and now==host['utc_ns'] and uint(model['issued_utc_ns'],64,1) and uint(model['expires_utc_ns'],64,1) and model['issued_utc_ns']<=now<model['expires_utc_ns'] and model['expires_utc_ns']-model['issued_utc_ns']<=60_000_000_000,'VALIDITY_UTC_WINDOW')
 rev=trust.verify(revocations,REVOKE_KIND);exact(rev,{'source','epoch','issued_utc_ns','expires_utc_ns','revoked_keys','revoked_nonces','revoked_attempts'})
 require(rev['source']=='SYNTHETIC_REVOCATION_ORACLE' and uint(rev['epoch'],64,1) and rev['epoch']==model['revocation_epoch']==expected['revocation_epoch'] and digest(rev)==model['revocation_sha256']==expected['revocation_sha256'],'REVOCATION_EXTERNAL_EPOCH_HEAD')
 require(uint(rev['issued_utc_ns'],64,1) and uint(rev['expires_utc_ns'],64,1) and rev['issued_utc_ns']<=now<rev['expires_utc_ns'],'STALE_REVOCATION')
 for k in ['revoked_keys','revoked_nonces','revoked_attempts']:require(type(rev[k]) is list and len(rev[k])<=1024 and all(type(v) is str for v in rev[k]) and len(set(rev[k]))==len(rev[k]),'REVOCATION_SCHEMA')
 require(all(e['signer'] not in rev['revoked_keys'] for e in [envelope,host_envelope,revocations]) and model['nonce'] not in rev['revoked_nonces'] and model['attempt_id'] not in rev['revoked_attempts'],'REVOKED_AUTHORITY_OR_ATTEMPT')
 return Admission(model,host,trust.pin,rev),rev

def verify_review_ack(trust,envelope,result,admission):
 require(type(admission) is Admission and type(trust) is SyntheticTrust and trust.pin==admission.trust_pin,'SYNTHETIC_ADMISSION_TRUST_BINDING');admission.unchanged();payload=trust.verify(envelope,REVIEW_KIND);exact(payload,{'artifact_kind','model_sha256','evidence_sha256','scope_sha256','identity_sha256','native_execution_authorized','diagnostic_authorized'})
 require(payload['artifact_kind']==REVIEW_KIND and payload['native_execution_authorized'] is False and payload['diagnostic_authorized'] is False,'ACK_NOT_EXECUTION')
 require(envelope['signer'] not in admission.revocations['revoked_keys'],'REVOKED_REVIEW_AUTHORITY')
 require(result.get('native_execution_authorized') is False and result.get('diagnostic_authorized') is False and result.get('gate2_final')=='BLOCKED' and result.get('no_auto_next') is True and result.get('atomic_snapshot') is False,'ACK_CANNOT_PROMOTE_RUNTIME')
 require(result['status']=='RESOLVED_OFFLINE_IDENTITY_ONLY' and result['model_sha256']==payload['model_sha256']==digest(admission.payload) and result['scope_sha256']==payload['scope_sha256']==admission.payload['scope_sha256'] and result['identity_sha256']==payload['identity_sha256']==digest(admission.payload['scope']['target']) and digest(result)==payload['evidence_sha256'],'ACK_EXACT_MODEL_RESULT_BINDING')
 return {'status':'SYNTHETIC_REVIEW_ACK_ONLY','native_execution_authorized':False,'diagnostic_authorized':False}
