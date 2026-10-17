"""One-shot offline preflight only. Mock PASS never releases native execution."""
import copy,hashlib,threading,traceback
from .contracts import *
from .protocol import require,exact,canonical,digest
from .trust import SyntheticTrust,verify_identity_model
from .witness import SyntheticLifecycleOracle,LifecycleVerifier
from .filesystem import check_root_proof
from .transport import MockNativeTransport,CallSession
from .journal import accepted_workspace

class OfflinePreflight:
 def __init__(self):self._lock=threading.Lock();self._used=False
 def run(self,bundle,trust,root,transport=None):
  workspace=None;claimed=False;session=None
  try:
   with self._lock:require(not self._used,'ENGINE_ONE_SHOT_NO_RETRY');self._used=True
   exact(bundle,{'issuer','host','revocation','witness','anchor','oracle','expected_pre','filesystem','expected','transport'})
   require(type(trust) is SyntheticTrust,'SYNTHETIC_TRUST_ONLY');workspace=accepted_workspace(root)
   admission,revoked=verify_identity_model(trust,bundle['issuer'],bundle['host'],bundle['revocation'],bundle['expected']);self.admission=admission
   model=admission.payload;scope=model['scope'];target=scope['target']
   require(model['workspace']==str(workspace.root) and scope['journal_root']==str(workspace.journal) and scope['evidence_root']==str(workspace.evidence/model['attempt_id']),'PHYSICAL_ROOT_SCOPE_BINDING')
   root_proof=check_root_proof(bundle['filesystem'],str(workspace.root),admission.host['operator_sid'])
   oracle=SyntheticLifecycleOracle(bundle['oracle']);lifecycle=LifecycleVerifier(trust,bundle['witness'],bundle['anchor'],oracle,admission,revoked,bundle['expected_pre'])
   provider=MockNativeTransport(bundle['transport']) if transport is None else transport;require(type(provider) is MockNativeTransport,'REAL_NATIVE_TRANSPORT_DISABLED');require(provider.pin==model['transport_sha256'],'TRANSPORT_EXTERNAL_HASH')
   workspace.claim(model);claimed=True;session=CallSession(admission,provider,workspace);self.session=session
   observations={};tokens={};file_parts=[];offset=0
   for index in range(len(provider.data['frames'])):
    row=session.call(index)
    if 'token_class' in row:require(row['token_class'] not in tokens,'DUPLICATE_TOKEN_OBSERVATION');tokens[row['token_class']]=row['value']
    elif 'file_offset' in row:require(row['file_offset']==offset,'FILE_OFFSET_GAP_OR_REPLAY');data=bytes.fromhex(row['data_hex']);file_parts.append(data);offset+=len(data)
    else:
     for key,value in row.items():require(key not in observations,'DUPLICATE_IDENTITY_OBSERVATION');observations[key]=value
   require(set(observations)=={'pid','tid','class_name','creation','executable_path'} and all(type(v) is type(target[k]) and v==target[k] for k,v in observations.items()),'OBSERVED_IDENTITY_MISMATCH_OR_INCOMPLETE')
   require(file_parts and hashlib.sha256(b''.join(file_parts)).hexdigest()==target['executable_sha256'],'EXECUTABLE_SHA_OR_DATA_INCOMPLETE')
   require(set(tokens)=={1,2,18,20,25} and type(tokens[18]) is int and tokens[18]==2 and type(tokens[20]) is int and tokens[20]==1,'TOKEN_SCALARS_INCOMPLETE_OR_LIMITED')
   require(tokens[1]==[{'sid':target['operator_sid'],'attributes':0}],'TARGET_USER_SID_MISMATCH');admins=[r for r in tokens[2] if r['sid']=='S-1-5-32-544'];require(len(admins)==1 and admins[0]['attributes']&4 and not admins[0]['attributes']&16,'TARGET_ADMIN_DISABLED_OR_DENY_ONLY')
   require(len(tokens[25])==1 and tokens[25][0]['sid']=='S-1-16-12288' and tokens[25][0]['attributes']&32,'TARGET_HIGH_INTEGRITY_REQUIRED')
   proof=lifecycle.cover(session.first,session.last);session.finish()
   result={'artifact_kind':'NQ_OFFLINE_PREFLIGHT_RESULT_NOT_RUNTIME_QUALIFICATION','status':'RESOLVED_OFFLINE_IDENTITY_ONLY','offline_status':'PASS_SYNTHETIC_PREFLIGHT_ONLY','model_sha256':digest(model),'scope_sha256':model['scope_sha256'],'identity_sha256':digest(target),'identity':copy.deepcopy(target),'witness':proof,'root_contract':root_proof,'trace':copy.deepcopy(provider.calls),'native_execution_authorized':False,'diagnostic_authorized':False,'gate2_final':'BLOCKED','runtime_blockers':list(RUNTIME_BLOCKERS),'original_halt_root_cause':'UNKNOWN','no_auto_next':True,'no_retry':True,'no_resume':True,'atomic_snapshot':False}
  except Exception as exc:
   result={'artifact_kind':'NQ_OFFLINE_PREFLIGHT_FAILURE','status':getattr(exc,'state','INDETERMINATE'),'reason':str(exc),'error_type':type(exc).__name__,'traceback':traceback.format_exc(),'native_execution_authorized':False,'diagnostic_authorized':False,'gate2_final':'BLOCKED','no_auto_next':True,'no_retry':True,'no_resume':True,'runtime_blockers':list(RUNTIME_BLOCKERS)}
   if result['status'] not in {'BLOCKED','INDETERMINATE'}:result['status']='INDETERMINATE'
  if session is not None:session.finished=True;session.transport.sealed=True
  if claimed:
   try:workspace.finish(result)
   except Exception as exc:result={'status':'INDETERMINATE','reason':'JOURNAL_OR_OUTPUT_UNKNOWN:'+str(exc),'native_execution_authorized':False,'diagnostic_authorized':False,'gate2_final':'BLOCKED','no_retry':True,'no_resume':True,'no_auto_next':True}
  return result
