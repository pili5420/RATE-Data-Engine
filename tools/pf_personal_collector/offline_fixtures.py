"""Fictional fixtures ONLY. Never imported by a native/runner entry."""
import copy
import synthetic_fixtures as inherited
import personal_model as base
HEAD='a'*40
RUN='123456'
def packet():
 old=inherited.evidence();records=copy.deepcopy(old['records'])
 for r in records:r.update(elapsed_ms=10,error_kind=None,hresult=None,provider_availability='RESPONSE_RECEIVED_NOT_PROVIDER_BINARY_ATTESTATION')
 return {'version':'PF_PERSONAL_002_NATIVE_PRIVATE_V1','realm':'RUNNER_ONLY_NOT_ORIGINAL_HOST_EVIDENCE','head':HEAD,'run_id':RUN,'run_attempt':'1',
 'started_utc':old['started_utc'],'ended_utc':old['ended_utc'],'elapsed_ms':1000,'status':'COMPLETED','records':records,'powershell_version':'7.4.13'}
def wire(p):return base.canonical(p)+b'\n'
def rows(p,i,v):inherited.set_rows(p,i,v)
def claims():
 import runner_proof as r
 return {'iss':r.ISS,'aud':r.AUD,'repository':r.REPO,'repository_id':'1370145728','repository_owner_id':'325481386','ref':r.REF,
 'event_name':'push','runner_environment':'github-hosted','workflow_ref':r.WORKFLOW,'sha':HEAD,'workflow_sha':HEAD,'run_id':RUN,'run_attempt':'1',
 'sub':f'repo:{r.REPO}:ref:{r.REF}','iat':1000,'nbf':1000,'exp':1300}
