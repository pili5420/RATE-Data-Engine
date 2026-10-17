"""Durable SYNTHETIC intent test implementation, never a formal Permit ledger.

Exclusive attempt+nonce reservations and immutable terminal records preserve any
partial outcome. Real ACL/directory-handle race resistance and power-loss/media
durability need native qualification; fsync alone is not claimed as that proof.
"""
import hashlib,os,re,threading
from pathlib import Path
from .protocol import need,exact,canonical,decode,digest,hash64,Denied
class SyntheticWorkspace:
 def __init__(self,root):
  self.root=Path(root);need(self.root.is_absolute() and self.root.parent==Path(r'D:\Codex') and re.fullmatch('RATE-Gate2-Native-Offline-(Tests|Review)-[A-Za-z0-9-]+',self.root.name) is not None,'SYNTHETIC_PHYSICAL_WORKSPACE_ONLY')
  self.journal=self.root/'journal';self.evidence=self.root/'evidence';self._claim_lock=threading.Lock();self._claimed=False;self._physical(self.root)
  need(self.root.is_dir(),'PRECREATED_PRIVATE_TEST_WORKSPACE_REQUIRED');s=self.root.stat();self.anchor=(s.st_dev,s.st_ino,s.st_ctime_ns)
  for p in [self.journal,self.evidence]:
   if not p.exists():p.mkdir()
   self._physical(p);need(p.is_dir(),'WORKSPACE_SUBDIRECTORY')
 def _physical(self,p):
  need('..' not in p.parts and str(p)==str(p.resolve()),'PHYSICAL_CANONICAL_PATH')
  for q in [p,*p.parents]:
   if q.exists():need(not q.is_symlink() and not q.lstat().st_file_attributes&1024,'REPARSE_OR_SYMLINK_DENIED')
  if p.exists() and p.is_file():need(p.stat().st_nlink==1,'HARDLINK_DENIED')
 def verify(self):
  self._physical(self.root);s=self.root.stat();need((s.st_dev,s.st_ino,s.st_ctime_ns)==self.anchor,'WORKSPACE_REPLACED','INDETERMINATE')
  for p in [self.journal,self.evidence]:self._physical(p);need(p.is_dir(),'WORKSPACE_DISAPPEARED','INDETERMINATE')
 def write_new(self,path,value):
  self.verify();path=Path(path);need(path.is_relative_to(self.root),'OUTPUT_SCOPE');self._physical(path.parent);self._physical(path)
  with path.open('xb') as f:f.write(canonical(value));f.flush();os.fsync(f.fileno())
  self._physical(path);self.verify();return hashlib.sha256(path.read_bytes()).hexdigest()
 def claim(self,model):
  with self._claim_lock:
   need(not self._claimed,'WORKSPACE_SESSION_ALREADY_CONSUMED');self._claimed=True
  self.verify();attempt=digest(model['attempt_id']);nonce=digest(model['nonce']);self.attempt=self.journal/('attempt-'+attempt+'.json');nonce_path=self.journal/('nonce-'+nonce+'.json')
  need(not self.attempt.exists() and not nonce_path.exists(),'ATTEMPT_OR_NONCE_REPLAY_NO_RESUME')
  lock=self.journal/'CLAIM_IN_PROGRESS.lock';need(not lock.exists(),'ACTIVE_OR_PARTIAL_CLAIM_BLOCKS_REPLAY_NO_RETRY_NO_RESUME','INDETERMINATE')
  lock_value={'artifact_kind':'SYNTHETIC_EXCLUSIVE_CLAIM_NOT_LIVE_AUTHORITY','attempt_id':model['attempt_id'],'nonce_sha256':nonce,'model_sha256':digest(model),'no_resume':True}
  lock_sha=self.write_new(lock,lock_value)  # xb is the cross-process admission point.
  # Any exception/crash from here retains this lock forever. There is no stale-
  # lock timeout, owner-death recovery, retry, cleanup, or repair operation.
  # The first durable attempt record reserves BOTH names. A crash before the
  # secondary nonce index must never allow a fresh attempt to reuse its nonce.
  records=list(self.journal.iterdir());need(len(records)<=60000,'JOURNAL_SCAN_BOUND','INDETERMINATE')
  for path in records:
   self._physical(path)
   if path==lock:continue
   need(path.is_file() and re.fullmatch(r'(attempt|nonce|terminal|claim-completed)-[0-9a-f]{64}\.json',path.name) is not None,'UNKNOWN_JOURNAL_ENTRY','INDETERMINATE')
   if path.name.startswith('attempt-'):
    prior=decode(path.read_bytes());self._validate_intent(prior,path)
    need(prior['nonce_sha256']!=nonce,'DURABLE_INTENT_NONCE_REPLAY_NO_RESUME')
  intent={'artifact_kind':'SYNTHETIC_INTENT_NOT_LIVE_PERMIT','state':'CLAIMED_UNKNOWN_UNTIL_TERMINAL','attempt_id':model['attempt_id'],'nonce_sha256':nonce,'model_sha256':digest(model),'no_resume':True}
  self.write_new(self.attempt,intent)
  self.write_new(nonce_path,{'attempt_sha256':attempt,'model_sha256':digest(model)})
  output=self.evidence/model['attempt_id'];need(not output.exists(),'EVIDENCE_ROOT_ALREADY_EXISTS');output.mkdir();self._physical(output);self.output=output;self.intent=intent
  completed=self.journal/('claim-completed-'+attempt+'.json');self.verify();self._physical(lock);need(hashlib.sha256(lock.read_bytes()).hexdigest()==lock_sha and not completed.exists(),'CLAIM_LOCK_IDENTITY_OR_DESTINATION_UNKNOWN','INDETERMINATE')
  # Normal successful completion preserves the lock header by atomic rename,
  # rather than deleting it. Windows rename does not replace an existing file.
  lock.rename(completed);self._physical(completed);self.verify();return intent
 def finish(self,result):
  need(hasattr(self,'intent'),'NO_CLAIMED_ATTEMPT');self.verify()
  evidence_sha=self.write_new(self.output/'RESULT.json',result)
  self.write_new(self.journal/('terminal-'+digest(self.intent['attempt_id'])+'.json'),{'state':result['status'],'intent_sha256':digest(self.intent),'result_sha256':evidence_sha,'no_resume':True})
 def _validate_intent(self,intent,path):
  exact(intent,{'artifact_kind','state','attempt_id','nonce_sha256','model_sha256','no_resume'})
  need(intent['artifact_kind']=='SYNTHETIC_INTENT_NOT_LIVE_PERMIT' and intent['state']=='CLAIMED_UNKNOWN_UNTIL_TERMINAL' and type(intent['attempt_id']) is str and re.fullmatch('SYNTHETIC-[A-Za-z0-9-]{8,96}',intent['attempt_id']) is not None and hash64(intent['nonce_sha256']) and hash64(intent['model_sha256']) and intent['no_resume'] is True and path.name=='attempt-'+digest(intent['attempt_id'])+'.json','INTENT_SCHEMA_OR_FILE_BINDING','INDETERMINATE')
 def audit_attempt(self,attempt_id):
  need(type(attempt_id) is str and re.fullmatch('SYNTHETIC-[A-Za-z0-9-]{8,96}',attempt_id) is not None,'SYNTHETIC_ATTEMPT_ONLY')
  self.verify();key=digest(attempt_id);a=self.journal/('attempt-'+key+'.json');t=self.journal/('terminal-'+key+'.json')
  if not a.exists():
   if (self.journal/'CLAIM_IN_PROGRESS.lock').exists():return {'state':'UNKNOWN_PARTIAL_OR_CRASH','retry_authorized':False,'resume_authorized':False}
   return {'state':'NOT_ATTEMPTED','retry_authorized':False}
  self._physical(a);intent=decode(a.read_bytes());self._validate_intent(intent,a);need(intent['attempt_id']==attempt_id,'INTENT_SCHEMA')
  if not t.exists():return {'state':'UNKNOWN_PARTIAL_OR_CRASH','retry_authorized':False,'resume_authorized':False}
  self._physical(t);terminal=decode(t.read_bytes());exact(terminal,{'state','intent_sha256','result_sha256','no_resume'});need(terminal['intent_sha256']==digest(intent) and terminal['no_resume'] is True and terminal['state'] in {'RESOLVED_OFFLINE_IDENTITY_ONLY','BLOCKED','INDETERMINATE'},'TERMINAL_INTENT_MISMATCH','INDETERMINATE')
  nonce=self.journal/('nonce-'+intent['nonce_sha256']+'.json');self._physical(nonce);record=decode(nonce.read_bytes());need(record=={'attempt_sha256':key,'model_sha256':intent['model_sha256']},'NONCE_RESERVATION_MISMATCH','INDETERMINATE')
  result_path=self.evidence/attempt_id/'RESULT.json';self._physical(result_path);need(hashlib.sha256(result_path.read_bytes()).hexdigest()==terminal['result_sha256'],'RESULT_FILE_TAMPER','INDETERMINATE')
  return {'state':terminal['state'],'retry_authorized':False,'resume_authorized':False}
