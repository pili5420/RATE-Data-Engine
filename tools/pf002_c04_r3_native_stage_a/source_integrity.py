"""Pure fixed-source/tree binding. Reads bytes only; never imports legacy executables."""
import hashlib,re
from pathlib import Path,PurePosixPath
import runner_proof as proof
BASE='1d32415ed1c3747b2ed7cba4ac19ccdeaaf78848'
SCOPE='tools/pf002_c04_r3_native_stage_a/'
WORKFLOW='.github/workflows/rate_pf002_c04_r3_stage_a.yml'
def need(ok,why):proof.need(ok,why)
def physical(path):
 need(path.is_absolute() and path==path.resolve(),'PHYSICAL_PATH')
 for p in (path,*path.parents):
  if p.exists():need(not p.is_symlink() and not(getattr(p.lstat(),'st_file_attributes',0)&0x400),'REPARSE_PATH')
def closed(source):
 physical(source);raw=(source/'SOURCE_MANIFEST_V1.json').read_bytes();m=proof.strict(raw,262144)
 need(type(m) is dict and set(m)=={'version','files'} and m['version']=='PF002_C04_R3_SOURCE_V1' and type(m['files']) is dict,'SOURCE_MANIFEST_SCHEMA')
 need({p.name for p in source.iterdir()}==set(m['files'])|{'SOURCE_MANIFEST_V1.json'},'CLOSED_SOURCE_DIRECTORY')
 for n,row in m['files'].items():
  need(type(n) is str and re.fullmatch('[A-Za-z0-9_.-]+',n) and n not in ('.','..'),'SOURCE_NAME')
  p=source/n;physical(p);need(p.is_file(),'SOURCE_REGULAR_FILE');b=p.read_bytes()
  need(type(row) is dict and set(row)=={'bytes','sha256'} and type(row['bytes']) is int and type(row['sha256']) is str and row=={'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()},'SOURCE_HASH')
 return m
def run_record(run,head,rid,role):
 need(type(run) is dict and run.get('head_sha')==head and run.get('head_branch')==proof.BRANCH and run.get('event')=='workflow_dispatch' and run.get('display_title')=='PF002-C04-R3 '+role and type(run.get('run_attempt')) is int and run['run_attempt']==1 and type(run.get('id')) is int and str(run['id'])==rid and run.get('path')==WORKFLOW,'OFFICIAL_RUN_BINDING')
 repo=run.get('repository');need(type(repo) is dict and type(repo.get('id')) is int and repo['id']==1370145728 and repo.get('full_name')==proof.REPO,'OFFICIAL_REPOSITORY_BINDING')
def tree(value,baseline=None):
 need(type(value) is dict and value.get('truncated') is False and type(value.get('tree')) is list and len(value['tree'])<=4096,'TREE_BOUND')
 result={};seen=set()
 for row in value['tree']:
  need(type(row) is dict and type(row.get('path')) is str,'TREE_ROW')
  n=row['path'];p=PurePosixPath(n)
  need(n and n==p.as_posix() and not p.is_absolute() and not any(x in ('','.','..') for x in n.split('/')) and '\\' not in n and ':' not in n and n not in seen,'TREE_PATH')
  seen.add(n);need(row.get('type') in ('blob','tree') and re.fullmatch('[0-9a-f]{40}',row.get('sha','')) is not None,'TREE_OBJECT')
  if row['type']=='tree':need(row.get('mode')=='040000','TREE_DIRECTORY_MODE');continue
  size=row.get('size')
  size_ok=size==baseline[n]['size'] if baseline is not None and n in baseline else type(size) is int and 0<=size<=262144
  need(row.get('mode')=='100644' and type(size) is int and size_ok,'TREE_BLOB_MODE_SIZE')
  result[n]={k:row[k] for k in ('mode','sha','type','size')}
 return result
def verify_trees(current,prior,root,manifest):
 source=root/SCOPE;expected=proof.strict((source/'BASE_TREE_V1.json').read_bytes(),262144)
 need(expected.get('head')==BASE and len(expected.get('files',{}))==748,'BASE_SOURCE_PIN')
 ct=tree(current,expected['files']);pt=tree(prior,expected['files']);need(pt==expected['files'],'EXACT_BASE_TREE')
 names={SCOPE+n for n in manifest['files']}|{SCOPE+'SOURCE_MANIFEST_V1.json',WORKFLOW}
 need(set(ct)==set(pt)|names and not(set(pt)&names) and all(ct[n]==pt[n] for n in pt),'ISOLATED_ADDITIVE_SOURCE_ONLY')
 for name,row in ct.items():
  p=root/name;physical(p);need(p.is_file(),'SOURCE_REGULAR_FILE');b=p.read_bytes()
  need(len(b)==row['size'] and hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()==row['sha'],'REMOTE_EXACT_BLOB')
 closed(source)
 return {'base_files':len(pt),'new_files':len(names),'current_files':len(ct),'base_unchanged':True,'exact_blob_integrity':True}
