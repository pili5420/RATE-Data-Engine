"""Independent role test roots, bounded trusted-time intervals and revocation.

Only in-memory, explicitly synthetic DTOs are accepted. There is no file Permit
loader, native capability or production trust configuration/signing operation.
"""
import copy,re
import cryptography
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from gui_native_preflight.protocol import require, exact, uint, rawhex, canonical, digest, hash64
from .contracts import REALM, ROLES, PURPOSES, source_identity, schema_identity, blocked_runtime
require(cryptography.__version__=='50.0.2','PINNED_CRYPTOGRAPHY_REQUIRED')

def signed_bytes(role,payload):
    return b'RATE-RQR-SYNTHETIC-SIGNATURE-V1\0'+canonical({'realm':REALM,'role':role,'purpose':PURPOSES[role],'payload':payload})

class SyntheticRoot:
    def __init__(self,bundle,expected_sha256):
        exact(bundle,{'realm','source','keys'})
        require(bundle['realm']==REALM and bundle['source']=='EPHEMERAL_INDEPENDENT_TEST_ROOTS','NO_REAL_ROOT')
        require(hash64(expected_sha256) and digest(bundle)==expected_sha256,'INDEPENDENT_ROOT_PIN')
        require(type(bundle['keys']) is list and len(bundle['keys'])==len(ROLES),'ROLE_ROOT_COUNT')
        roles=set();pubs=set();names=set()
        for row in bundle['keys']:
            exact(row,{'id','role','public_hex'})
            require(type(row['id']) is str and row['id'].startswith('SYNTHETIC-') and row['id'] not in names and row['role'] in ROLES and row['role'] not in roles,'ROOT_ROLE_ID')
            raw=rawhex(row['public_hex'],32);require(len(raw)==32 and raw not in pubs,'INDEPENDENT_KEY_ROLES')
            names.add(row['id']);roles.add(row['role']);pubs.add(raw)
        self.bundle=copy.deepcopy(bundle);self.pin=expected_sha256
    def unchanged(self):require(digest(self.bundle)==self.pin,'ROOT_MUTATION')
    def verify(self,envelope,role):
        self.unchanged();require(role in ROLES,'ROLE_PURPOSE')
        exact(envelope,{'version','realm','purpose','role','signer','payload','signature_hex'})
        require(type(envelope['version']) is int and envelope['version']==1 and envelope['realm']==REALM and envelope['purpose']==PURPOSES[role] and envelope['role']==role,'SIGNATURE_AUTHORITY_SEPARATION')
        rows=[r for r in self.bundle['keys'] if r['id']==envelope['signer'] and r['role']==role];require(len(rows)==1,'SIGNER_ROLE')
        sig=rawhex(envelope['signature_hex'],64);require(len(sig)==64,'SIGNATURE_LENGTH')
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(rows[0]['public_hex'])).verify(sig,signed_bytes(role,envelope['payload']))
        return copy.deepcopy(envelope['payload'])

def time_interval(clock,tick):
    exact(clock,{'source','domain','sample_tick','earliest_utc_ns','latest_utc_ns','max_age_ns'})
    require(clock['source']=='SYNTHETIC_INDEPENDENT_UTC_ORACLE' and type(clock['domain']) is str and clock['domain'].startswith('SYNTHETIC-'),'TRUSTED_UTC_SOURCE_UNKNOWN','INDETERMINATE')
    require(all(uint(clock[k],64,1) for k in ['sample_tick','earliest_utc_ns','latest_utc_ns','max_age_ns']) and uint(tick,64,1),'CLOCK_NATIVE_TYPES')
    require(clock['earliest_utc_ns']<=clock['latest_utc_ns'] and tick>=clock['sample_tick'] and tick-clock['sample_tick']<=clock['max_age_ns']<=60_000_000_000,'CLOCK_ROLLBACK_AGE_OR_UNCERTAINTY','INDETERMINATE')
    delta=tick-clock['sample_tick'];lo=clock['earliest_utc_ns']+delta;hi=clock['latest_utc_ns']+delta
    require(uint(lo,64,1) and uint(hi,64,1),'UTC_OVERFLOW','INDETERMINATE')
    return lo,hi

def valid_interval(payload,lo,hi):
    require(uint(payload['issued_utc_ns'],64,1) and uint(payload['expires_utc_ns'],64,1) and payload['issued_utc_ns']<=lo<=hi<payload['expires_utc_ns'],'UTC_UNCERTAINTY_OR_EXPIRY','INDETERMINATE')

class Admission:
    def __init__(self,root,permit,clock,revocation,attestations,signers):
        self.root=root;self.permit=copy.deepcopy(permit);self.clock=copy.deepcopy(clock);self.revocation=copy.deepcopy(revocation);self.attestations=copy.deepcopy(attestations);self.signers=list(signers);self.pin=self._digest();self.last_tick=clock['sample_tick']
    def _digest(self):return digest({'root':self.root.pin,'permit':self.permit,'clock':self.clock,'revocation':self.revocation,'attestations':self.attestations,'signers':self.signers})
    def check(self,tick):
        self.root.unchanged();require(self._digest()==self.pin,'ADMISSION_MUTATED')
        require(self.permit['tool_sha256']==source_identity() and self.permit['schema_sha256']==schema_identity(),'EXACT_TOOL_SCHEMA_CHANGED')
        require(uint(tick,64,1) and tick>=self.last_tick,'MONOTONIC_ROLLBACK','INDETERMINATE')
        lo,hi=time_interval(self.clock,tick);valid_interval(self.permit,lo,hi);valid_interval(self.revocation,lo,hi)
        for value in self.attestations.values():valid_interval(value,lo,hi)
        require(all(v not in self.revocation['revoked_keys'] for v in self.signers) and self.permit['nonce'] not in self.revocation['revoked_nonces'] and self.permit['attempt_id'] not in self.revocation['revoked_attempts'],'REVOKED_AUTHORITY')
        self.last_tick=tick;return {'earliest_utc_ns':lo,'latest_utc_ns':hi,**blocked_runtime()}

def admit(root,envelopes,expected,tick):
    require(type(root) is SyntheticRoot,'SYNTHETIC_ROOT_ONLY')
    exact(envelopes,{'ISSUER','HOST','BOOT','OPERATOR','PARENT','CLOCK','REVOCATION'})
    exact(expected,{'root_sha256','scope_sha256','transport_sha256','provenance_sha256','clock_sha256','revocation_sha256','revocation_epoch','previous_sequence','previous_head'})
    require(all(hash64(expected[k]) for k in ['root_sha256','scope_sha256','transport_sha256','provenance_sha256','clock_sha256','revocation_sha256','previous_head']) and uint(expected['revocation_epoch'],64,1) and uint(expected['previous_sequence'],64),'EXTERNAL_NATIVE_PINS')
    require(root.pin==expected['root_sha256'],'EXTERNAL_ROOT_CHANGED')
    claims={role:root.verify(value,role) for role,value in envelopes.items()};p=claims.pop('ISSUER');clock=claims.pop('CLOCK');rev=claims.pop('REVOCATION')
    exact(p,{'artifact_kind','attempt_id','nonce','issuer_sequence','previous_head','issued_utc_ns','expires_utc_ns','tool_sha256','schema_sha256','scope','scope_sha256','transport_sha256','provenance_sha256','clock_sha256','revocation_sha256','revocation_epoch','native_execution_authorized','diagnostic_authorized'})
    require(p['artifact_kind']=='RQR_SYNTHETIC_IDENTITY_ONLY_NOT_LIVE_PERMIT' and p['native_execution_authorized'] is False and p['diagnostic_authorized'] is False,'NO_LIVE_PERMIT')
    require(uint(p['issued_utc_ns'],64,1) and uint(p['expires_utc_ns'],64,1) and 0<p['expires_utc_ns']-p['issued_utc_ns']<=60_000_000_000,'BOUNDED_PERMIT_VALIDITY')
    for key in ['attempt_id','nonce']:require(type(p[key]) is str and p[key].startswith('SYNTHETIC-') and 16<=len(p[key])<=96,'SYNTHETIC_ATTEMPT_NONCE')
    require(uint(p['issuer_sequence'],64,1) and p['issuer_sequence']==expected['previous_sequence']+1 and p['previous_head']==expected['previous_head'],'INDEPENDENT_ISSUER_SEQUENCE_HEAD')
    require(digest(p['scope'])==p['scope_sha256']==expected['scope_sha256'] and p['transport_sha256']==expected['transport_sha256'] and digest(claims)==p['provenance_sha256']==expected['provenance_sha256'] and digest(clock)==p['clock_sha256']==expected['clock_sha256'],'EXACT_SCOPE_TRANSPORT_PROVENANCE_CLOCK')
    scope=p['scope'];exact(scope,{'stage','host','boot','session','desktop','station','observer_pid','observer_tid','observer_creation','operator_sid','parent_pid','parent_creation','target_pid','target_tid','target_hwnd','target_creation','target_class','target_executable_sha256','target_file_id','target_volume','generation','max_calls','per_call_ns','total_ns','apis','rights','workspace','journal_root','evidence_root'})
    from pathlib import Path
    target_root=Path(scope['workspace']);require(type(scope['workspace']) is str and target_root.parent==Path(r'D:\Codex') and re.fullmatch(r'RATE-Gate2-Native-Offline-(?:Tests|Review)-[A-Za-z0-9-]+',target_root.name) is not None and scope['journal_root']==str(target_root/'journal') and scope['evidence_root']==str(target_root/'evidence'/p['attempt_id']),'EXACT_PRIVATE_PHYSICAL_ROOT_SCOPE')
    from .bindings import PROTOTYPES,RIGHTS
    require(scope['stage']=='IDENTITY_ONLY' and scope['apis']==sorted(PROTOTYPES) and canonical(scope['rights'])==canonical(RIGHTS),'EXACT_IDENTITY_READ_SCOPE')
    for k in ['session','observer_pid','observer_tid','parent_pid','target_pid','target_tid']:require(uint(scope[k],32,1),'PROCESS_SESSION_TYPE')
    for k in ['observer_creation','parent_creation','target_creation','target_hwnd','target_volume','generation']:require(uint(scope[k],64,1),'CREATION_GENERATION_TYPE')
    require(scope['target_class']=='#32770' and hash64(scope['target_executable_sha256']) and len(rawhex(scope['target_file_id'],16))==16,'TARGET_FILE_CLASS_BINDING')
    for k in ['host','boot']:require(type(scope[k]) is str and scope[k].startswith('SYNTHETIC-'),'SYNTHETIC_HOST_BOOT_ONLY')
    for k in ['desktop','station','operator_sid']:require(type(scope[k]) is str and 0<len(scope[k])<=256 and '\0' not in scope[k],'PROVENANCE_STRING')
    require(re.fullmatch(r'S-1-[0-9]+(?:-[0-9]+){1,15}',scope['operator_sid']) is not None,'OPERATOR_SID_SYNTAX')
    sidparts=scope['operator_sid'].split('-')[2:];require(int(sidparts[0])<2**48 and all(str(int(v))==v for v in sidparts) and all(int(v)<2**32 for v in sidparts[1:]),'OPERATOR_SID_CANONICAL_RANGE')
    require(uint(scope['max_calls'],32,1) and scope['max_calls']<=128 and uint(scope['per_call_ns'],64,1) and uint(scope['total_ns'],64,1) and scope['per_call_ns']<=scope['total_ns']<=60_000_000_000,'CALL_DEADLINE_BOUNDS')
    provenance_keys={
      'HOST':{'host','session','desktop','station'},'BOOT':{'host','boot','clock_domain'},
      'OPERATOR':{'host','boot','operator_sid','observer_pid','observer_creation','admin_enabled','high_integrity'},
      'PARENT':{'host','boot','session','operator_sid','observer_pid','observer_creation','parent_pid','parent_creation','parent_path_sha256'}}
    for role,value in claims.items():
        exact(value,provenance_keys[role]|{'source','issued_utc_ns','expires_utc_ns'})
        require(value['source']=='SYNTHETIC_'+role+'_ORACLE','REAL_PROVENANCE_UNQUALIFIED','INDETERMINATE')
        for k in provenance_keys[role]&set(scope):require(type(value[k]) is type(scope[k]) and value[k]==scope[k],'PROVENANCE_LINK_MISMATCH')
    require(claims['OPERATOR']['admin_enabled'] is True and claims['OPERATOR']['high_integrity'] is True and hash64(claims['PARENT']['parent_path_sha256']) and claims['BOOT']['clock_domain']==clock['domain'],'OPERATOR_PARENT_CLOCK_CONTRACT')
    exact(rev,{'source','epoch','issued_utc_ns','expires_utc_ns','revoked_keys','revoked_nonces','revoked_attempts'})
    require(rev['source']=='SYNTHETIC_INDEPENDENT_REVOCATION_ORACLE' and uint(rev['epoch'],64,1) and type(p['revocation_epoch']) is int and rev['epoch']==p['revocation_epoch']==expected['revocation_epoch'] and digest(rev)==p['revocation_sha256']==expected['revocation_sha256'],'REVOCATION_EXTERNAL_EPOCH_HEAD')
    for key in ['revoked_keys','revoked_nonces','revoked_attempts']:require(type(rev[key]) is list and len(rev[key])<=1024 and all(type(v) is str for v in rev[key]) and len(set(rev[key]))==len(rev[key]),'REVOCATION_SCHEMA')
    out=Admission(root,p,clock,rev,claims,[e['signer'] for e in envelopes.values()]);out.check(tick);return out

def review_ack(admission,envelope,evidence,tick):
    require(type(admission) is Admission,'ADMISSION_REQUIRED');admission.check(tick)
    p=admission.root.verify(envelope,'REVIEW');exact(p,{'artifact_kind','permit_sha256','scope_sha256','evidence_sha256','native_execution_authorized','diagnostic_authorized'})
    require(envelope['signer'] not in admission.revocation['revoked_keys'],'REVOKED_REVIEWER')
    require(p['artifact_kind']==PURPOSES['REVIEW'] and p['permit_sha256']==digest(admission.permit) and p['scope_sha256']==admission.permit['scope_sha256'] and p['evidence_sha256']==digest(evidence),'EXACT_REVIEW_BINDING')
    require(p['native_execution_authorized'] is False and p['diagnostic_authorized'] is False and evidence['native_execution_authorized'] is False and evidence['diagnostic_authorized'] is False and evidence['status']=='OFFLINE_WIRE_TRANSCRIPT_ONLY' and evidence['gate2_final']=='BLOCKED' and evidence['no_auto_next'] is True and evidence['atomic_snapshot'] is False,'ACK_NOT_EXECUTION_OR_UNKNOWN_PROMOTION')
    return {'status':'OFFLINE_REVIEW_ACK_ONLY',**blocked_runtime()}
