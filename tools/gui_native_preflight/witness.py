"""Independent signed synthetic witness plus independent complete oracle.

A signature or WinEvent/ETW label is never evidence of losslessness. Only exact
finite synthetic oracle equality is admitted; real coverage stays UNKNOWN.
"""
import copy
from .contracts import WITNESS_KIND,ANCHOR_KIND
from .protocol import require,exact,uint,digest,hash64
class SyntheticLifecycleOracle:
 def __init__(self,data):
  exact(data,{'source','host','boot','clock_domain','begin_tick','end_tick','events'})
  require(data['source']=='SYNTHETIC_COMPLETE_EVENT_ORACLE_NOT_NATIVE','NATIVE_LIFECYCLE_COVERAGE_UNKNOWN','INDETERMINATE');require(type(data['events']) is list and 2<=len(data['events'])<=512,'ORACLE_EVENT_BOUND')
  self.data=copy.deepcopy(data);self.pin=digest(data)
 def unchanged(self):require(digest(self.data)==self.pin,'LIFECYCLE_ORACLE_MUTATED','INDETERMINATE')

class LifecycleVerifier:
 def __init__(self,trust,checkpoint,anchor,oracle,admission,revocations,expected_pre):
  require(type(oracle) is SyntheticLifecycleOracle,'SYNTHETIC_ORACLE_REQUIRED','INDETERMINATE');oracle.unchanged();admission.unchanged();require(trust.pin==admission.trust_pin,'WITNESS_TRUST_ROOT_BINDING')
  require(all(e['signer'] not in revocations['revoked_keys'] for e in [checkpoint,anchor]),'REVOKED_WITNESS_OR_ANCHOR')
  head=trust.verify(anchor,ANCHOR_KIND);exact(head,{'source','scope_sha256','attempt_id','oracle_sha256','pre_sequence','pre_head','final_sequence','final_head'})
  require(head['source']=='SYNTHETIC_EXTERNAL_ACK_ORACLE' and digest(head)==admission.payload['witness_anchor_sha256'] and head['scope_sha256']==admission.payload['scope_sha256'] and head['attempt_id']==admission.payload['attempt_id'] and head['oracle_sha256']==oracle.pin,'EXTERNAL_ANCHOR_SCOPE_ATTEMPT_BINDING')
  exact(expected_pre,{'sequence','head'});require(uint(expected_pre['sequence'],64) and hash64(expected_pre['head']) and type(head['pre_sequence']) is int and head['pre_sequence']==expected_pre['sequence'] and head['pre_head']==expected_pre['head'],'INDEPENDENT_WITNESS_PREFIX')
  proof=trust.verify(checkpoint,WITNESS_KIND);exact(proof,{'source','oracle_sha256','coverage','loss','pre_sequence','pre_head','events','begin_tick','end_tick','host','boot','clock_domain'})
  require(proof['source']=='SYNTHETIC_INDEPENDENT_WITNESS_NOT_NATIVE' and proof['coverage']=='COMPLETE_SYNTHETIC_ORACLE_ONLY' and type(proof['loss']) is int and proof['loss']==0,'NATIVE_OR_INCOMPLETE_LIFECYCLE_UNKNOWN','INDETERMINATE')
  require(proof['oracle_sha256']==oracle.pin and proof['pre_head']==head['pre_head'] and type(proof['pre_sequence']) is int and proof['pre_sequence']==head['pre_sequence'],'WITNESS_ORACLE_PREFIX_BINDING')
  require(type(proof['events']) is list and digest(proof['events'])==digest(oracle.data['events']),'WITNESS_MISSING_OR_SUBSTITUTED_EVENT','INDETERMINATE')
  for k in ['begin_tick','end_tick','host','boot','clock_domain']:require(type(proof[k]) is type(oracle.data[k]) and proof[k]==oracle.data[k],'WITNESS_ORACLE_CONTEXT')
  for k in ['host','boot','clock_domain']:require(proof[k]==admission.host[k],'WITNESS_HOST_BOOT_CLOCK')
  require(uint(proof['begin_tick'],64,1) and uint(proof['end_tick'],64,1) and proof['begin_tick']<proof['end_tick'],'WITNESS_INTERVAL')
  previous=head['pre_head'];sequence=head['pre_sequence'];last=0;states={};target=admission.payload['scope']['target']
  for event in proof['events']:
   exact(event,{'sequence','previous_head','tick','kind','identity'})
   require(uint(event['sequence'],64,1) and event['sequence']==sequence+1 and event['previous_head']==previous and uint(event['tick'],64,1) and proof['begin_tick']<=event['tick']<=proof['end_tick'] and event['tick']>last,'WITNESS_SEQUENCE_REORDER_OR_HEAD_GAP','INDETERMINATE')
   identity=event['identity'];require(type(identity) is dict and digest(identity)==digest(target),'WITNESS_IDENTITY_GENERATION_MISMATCH','INDETERMINATE');key=identity['hwnd']
   require(event['kind']=='CREATE' if key not in states else event['kind']=='UNCHANGED','DUPLICATE_CREATE_DESTROY_OR_UNKNOWN','INDETERMINATE')
   states[key]=states.get(key,0)+1;sequence+=1;previous=digest(event);last=event['tick']
  require(len(states)==1 and states.get(target['hwnd'],0)>=2 and type(head['final_sequence']) is int and sequence==head['final_sequence'] and hash64(head['final_head']) and previous==head['final_head'],'WITNESS_FINAL_HEAD_OR_STATE')
  self.proof=proof;self.proof_pin=digest(proof);self.oracle=oracle;self.head=copy.deepcopy(head)
 def cover(self,first,last):
  self.oracle.unchanged();require(digest(self.proof)==self.proof_pin,'WITNESS_PROOF_MUTATED')
  require(uint(first,64,1) and uint(last,64,1) and self.proof['begin_tick']<=first<=last<=self.proof['end_tick'] and self.proof['events'][0]['tick']<=first and self.proof['events'][-1]['tick']>=last,'INCOMPLETE_WITNESS_INTERVAL','INDETERMINATE')
  return {'status':'PASS_SYNTHETIC_ORACLE_ONLY','final_sequence':self.head['final_sequence'],'final_head':self.head['final_head'],'native_coverage':'UNKNOWN','atomic_snapshot':False}
