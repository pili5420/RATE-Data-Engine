"""Engineering integrity check only, NOT a Permit/attestation or target loader."""
import hashlib,json
from pathlib import Path

NAMES=('.gitattributes','candidate.py','synthetic_fixtures.py','test_candidate.py','run_offline_tests.py','verify_bundle.py',
 'READ_SCOPE_V1.json','EXECUTION_SAFETY_CONTRACT_V1.json','CANDIDATE_SCHEMA_V1.json','EXTERNAL_EVIDENCE_REQUEST_V1.json',
 'SOURCE_GAP_SEPARATION_V1.json','UNISSUED_REQUEST_V1.json','THREAT_MODEL_V1.json','ENGINEERING_CR_V1.json','README.txt','SOURCE_AUTHORITY_REVIEW_V1.json')
DEPENDENCIES=('tools/pagefile_non_gui_evidence/evidence.py','tools/pagefile_non_gui_evidence/EVIDENCE_SCHEMA_V1.json','tools/pagefile_non_gui_evidence/EVIDENCE_DECISION_CONTRACT_V1.json')

def need(ok,reason):
 if not ok:raise ValueError(reason)

def verify(repo):
 repo=Path(repo);source=repo/'tools/pagefile_limited_readonly_authorization'
 manifest=json.loads((source/'BUNDLE_MANIFEST_V1.json').read_bytes())
 need(manifest['version']=='PF_LRO_CLOSED_OFFLINE_BUNDLE_V1','BUNDLE_VERSION')
 need(manifest['accepted_base_head']=='7208a58e3b0eadc3ee910d508af04191b018a219','BUNDLE_BASE')
 need(manifest['native_transport'] is False and manifest['execution_authorized'] is False,'BUNDLE_NO_EXECUTION')
 expected={'tools/pagefile_limited_readonly_authorization/'+n for n in NAMES}|set(DEPENDENCIES)
 need(set(manifest['files'])==expected,'CLOSED_BUNDLE_FILE_SET')
 need({p.name for p in source.iterdir()}==set(NAMES)|{'BUNDLE_MANIFEST_V1.json'},'UNEXPECTED_CANDIDATE_FILE_OR_DIRECTORY')
 for name,row in manifest['files'].items():
  need(name in expected and '..' not in Path(name).parts,'BUNDLE_PATH')
  p=repo/name
  for component in [p,*p.parents]:
   if component==repo.parent:break
   need(not component.is_symlink() and not(getattr(component.lstat(),'st_file_attributes',0)&0x400),'REPARSE_BUNDLE')
  raw=p.read_bytes();need(len(raw)==row['bytes'] and hashlib.sha256(raw).hexdigest()==row['sha256'],'BUNDLE_BYTES_TAMPER:'+name)
 return {'status':'PASS_CLOSED_OFFLINE_BUNDLE_INTEGRITY','files':len(expected),'native_transport':False,'execution_authorized':False,'limitation':'Not hostile-code sandbox, signature/root/permit verification or target filesystem safety qualification.'}
