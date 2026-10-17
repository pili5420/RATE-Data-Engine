"""Fixed no-descendant SYNTHETIC fault worker. No real Permit/native arguments."""
import argparse,hashlib,json,os,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from gui_native_identity.journal import SyntheticWorkspace
def main():
 p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--mode',choices=['after_lock','after_attempt','after_claim','after_result','sleep','clean'],required=True);p.add_argument('--attempt',required=True);p.add_argument('--nonce',required=True);a=p.parse_args()
 for value in [a.attempt,a.nonce]:
  if not value.startswith('SYNTHETIC-'):raise ValueError('SYNTHETIC_ONLY')
 w=SyntheticWorkspace(Path(a.root));m={'artifact_kind':'NQ_SYNTHETIC_OWNED_CHILD_ONLY','attempt_id':a.attempt,'nonce':a.nonce};original=w.write_new
 def fault(path,value):
  pin=original(path,value)
  if a.mode=='after_lock' and path.name=='CLAIM_IN_PROGRESS.lock' or a.mode=='after_attempt' and path.name.startswith('attempt-') or a.mode=='after_result' and path.name=='RESULT.json':os._exit(73)
  return pin
 w.write_new=fault;w.claim(m)
 if a.mode=='after_claim':os._exit(73)
 (w.root/'CHILD_READY.json').write_text(json.dumps({'pid':os.getpid(),'mode':a.mode,'secret_present':'NQ_SYNTHETIC_SECRET_SENTINEL' in os.environ,'source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}));print('SYNTHETIC_CHILD_READY',flush=True)
 if a.mode=='sleep':time.sleep(30)
 w.finish({'status':'RESOLVED_OFFLINE_IDENTITY_ONLY','native_execution_authorized':False,'diagnostic_authorized':False})
if __name__=='__main__':main()
