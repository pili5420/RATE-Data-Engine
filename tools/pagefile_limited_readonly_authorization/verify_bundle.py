"""Engineering integrity check only, NOT a Permit/attestation or target loader."""
import hashlib,json
from pathlib import Path

NAMES=('.gitattributes','candidate.py','synthetic_fixtures.py','test_candidate.py','run_offline_tests.py','verify_bundle.py',
 'READ_SCOPE_V1.json','EXECUTION_SAFETY_CONTRACT_V1.json','CANDIDATE_SCHEMA_V1.json','EXTERNAL_EVIDENCE_REQUEST_V1.json',
 'SOURCE_GAP_SEPARATION_V1.json','UNISSUED_REQUEST_V1.json','THREAT_MODEL_V1.json','ENGINEERING_CR_V1.json','README.txt','SOURCE_AUTHORITY_REVIEW_V1.json')
DEPENDENCIES=('tools/pagefile_non_gui_evidence/evidence.py','tools/pagefile_non_gui_evidence/EVIDENCE_SCHEMA_V1.json','tools/pagefile_non_gui_evidence/EVIDENCE_DECISION_CONTRACT_V1.json','tools/pagefile_non_gui_evidence/fixtures.py','tools/pagefile_non_gui_evidence/test_evidence.py','tools/pagefile_non_gui_evidence/evaluate_runner.py')
REFERENCE_NAMES=('.gitattributes','ENGINEERING_CR_V1.json','evaluate_runner.py','EVIDENCE_DECISION_CONTRACT_V1.json','EVIDENCE_SCHEMA_V1.json','evidence.py','FEASIBILITY_DECISION_V1.json','fixtures.py','NEXT_AUTHORIZATION_BOUNDARY_V1.json','OFFICIAL_SOURCE_QUALIFICATION_V1.json','READ_BOUNDARY_V1.json','RESEARCH_GUIDE.txt','run_tests.py','runner_collect.ps1','test_collector_boundary.ps1','test_evidence.py')

def need(ok,reason):
 if not ok:raise ValueError(reason)

def check_package_siblings(names):
 for stem in ('pagefile_non_gui_evidence','pagefile_limited_readonly_authorization'):
  need(not any(name.startswith(stem+'.') for name in names),'PACKAGE_SIBLING_SHADOW_FORBIDDEN:'+stem)

def _verify(repo,reference_tree):
 repo=Path(repo);source=repo/'tools/pagefile_limited_readonly_authorization'
 manifest=json.loads((source/'BUNDLE_MANIFEST_V1.json').read_bytes())
 need(manifest['version']=='PF_LRO_CLOSED_OFFLINE_BUNDLE_V1','BUNDLE_VERSION')
 need(manifest['accepted_base_head']=='7208a58e3b0eadc3ee910d508af04191b018a219','BUNDLE_BASE')
 need(manifest['native_transport'] is False and manifest['execution_authorized'] is False,'BUNDLE_NO_EXECUTION')
 expected={'tools/pagefile_limited_readonly_authorization/'+n for n in NAMES}|set(DEPENDENCIES)
 need(set(manifest['files'])==expected,'CLOSED_BUNDLE_FILE_SET')
 need({p.name for p in source.iterdir()}==set(NAMES)|{'BUNDLE_MANIFEST_V1.json'},'UNEXPECTED_CANDIDATE_FILE_OR_DIRECTORY')
 dependency=repo/'tools/pagefile_non_gui_evidence'
 expected_context=set(REFERENCE_NAMES) if reference_tree else {Path(n).name for n in DEPENDENCIES}
 need({p.name for p in dependency.iterdir()}==expected_context,'DEPENDENCY_DIRECTORY_NOT_EXACT')
 for directory in [repo/'tools',dependency,source]:
  need(not any(p.name.startswith('__init__.') for p in directory.iterdir()),'NAMESPACE_INITIALIZER_FORBIDDEN')
 need(not any(p.name.startswith('tools.') for p in repo.iterdir()),'ROOT_NAMESPACE_SHADOW_FORBIDDEN')
 check_package_siblings([p.name for p in (repo/'tools').iterdir()])
 if reference_tree:
  context=manifest['accepted_reference_context']
  need(set(context)==set(REFERENCE_NAMES),'ACCEPTED_REFERENCE_CONTEXT_SET')
  for name,row in context.items():
   b=(dependency/name).read_bytes();need(len(b)==row['bytes'] and hashlib.sha256(b).hexdigest()==row['sha256'],'ACCEPTED_REFERENCE_BYTES:'+name)
 else:
  expected_paths=expected|{'tools/pagefile_limited_readonly_authorization/BUNDLE_MANIFEST_V1.json'}
  expected_dirs={parent.as_posix() for name in expected_paths for parent in Path(name).parents if parent.as_posix()!='.'}
  actual_paths=set();actual_dirs=set()
  for p in repo.rglob('*'):
   need(not p.is_symlink() and not(getattr(p.lstat(),'st_file_attributes',0)&0x400),'REPARSE_BUNDLE_TREE')
   (actual_dirs if p.is_dir() else actual_paths).add(p.relative_to(repo).as_posix())
  need(actual_paths==expected_paths and actual_dirs==expected_dirs,'PHYSICAL_BUNDLE_TREE_NOT_CLOSED')
 for name,row in manifest['files'].items():
  need(name in expected and '..' not in Path(name).parts,'BUNDLE_PATH')
  p=repo/name
  for component in [p,*p.parents]:
   if component==repo.parent:break
   need(not component.is_symlink() and not(getattr(component.lstat(),'st_file_attributes',0)&0x400),'REPARSE_BUNDLE')
  raw=p.read_bytes();need(len(raw)==row['bytes'] and hashlib.sha256(raw).hexdigest()==row['sha256'],'BUNDLE_BYTES_TAMPER:'+name)
 return {'status':'PASS_SOURCE_REFERENCE_SELECTION_INTEGRITY' if reference_tree else 'PASS_CLOSED_OFFLINE_BUNDLE_INTEGRITY','profile':'SOURCE_REFERENCE_PROFILE' if reference_tree else 'CLOSED_BUNDLE_PROFILE','files':len(expected),'native_transport':False,'execution_authorized':False,'limitation':'Reference profile may contain unchanged legacy source outside selected bundle. Neither profile is hostile-code sandbox, atomic code-root/ACL guarantee, signature/root/permit verification or target filesystem safety qualification.'}

def verify(repo):return _verify(repo,False)
def verify_reference_tree(repo):return _verify(repo,True)
