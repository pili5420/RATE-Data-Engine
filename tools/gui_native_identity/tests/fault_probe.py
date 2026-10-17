"""Owned synthetic crash-test child ONLY; not part of runtime manifest or distribution.
No model file/real Permit/native provider/GUI mode is accepted by this test driver.
"""
import argparse,os,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from gui_native_identity import SyntheticWorkspace,OfflineIdentityCandidate
from gui_native_identity.protocol import validate_model,digest
from gui_native_identity.tests.fixtures import bundle
def main():
 p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--mode',choices=['after_attempt','after_claim','after_result'],required=True);p.add_argument('--attempt',required=True);p.add_argument('--nonce',required=True);a=p.parse_args()
 w=SyntheticWorkspace(a.root);m,provider,v=bundle(w,attempt=a.attempt,nonce=a.nonce);validate_model(m,w,provider.identity,digest(v))
 original=w.write_new
 def crash_after(path,value):
  result=original(path,value)
  if a.mode=='after_attempt' and path.name.startswith('attempt-') or a.mode=='after_result' and path.name=='RESULT.json':os._exit(73)
  return result
 w.write_new=crash_after
 if a.mode=='after_result':OfflineIdentityCandidate().run(m,provider,v,w)
 else:w.claim(m);os._exit(73)
 raise RuntimeError('CRASH_TEST_DID_NOT_EXIT')
if __name__=='__main__':main()
