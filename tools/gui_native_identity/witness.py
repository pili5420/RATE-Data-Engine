"""Verifiable synthetic lifecycle contract; never claims WinEvent hooks are lossless."""
from .contracts import WITNESS_KIND
from .protocol import need,exact,integer,digest
from .baseline import accepted
class LifecycleWitness:
 def __init__(self,proof,model):
  exact(proof,{'artifact_kind','boot_id','coverage','lost_events','begin_ns','end_ns','pre_head','events'})
  need(proof['artifact_kind']==WITNESS_KIND and proof['coverage']=='COMPLETE_SYNTHETIC_STREAM','NATIVE_LIFECYCLE_PROVENANCE_UNKNOWN','INDETERMINATE')
  need(type(proof['lost_events']) is int and proof['lost_events']==0,'LIFECYCLE_EVENT_LOSS','INDETERMINATE')
  need(proof['boot_id']==model['scope']['policy']['boot_id'],'BOOT_CONTEXT_MISMATCH')
  need(integer(proof['begin_ns'],1) and integer(proof['end_ns'],1) and proof['begin_ns']<proof['end_ns'],'LIFECYCLE_HORIZON_UNKNOWN','INDETERMINATE')
  need(proof['pre_head']==model['witness_pre_head'] and digest(proof)==model['witness_sha256'],'EXTERNAL_WITNESS_PREHEAD_BINDING')
  need(type(proof['events']) is list and 2<=len(proof['events'])<=8192,'LIFECYCLE_TRACE_BOUND','INDETERMINATE')
  prev=proof['pre_head'];last_time=0;groups={}
  for sequence,event in enumerate(proof['events'],1):
   exact(event,{'sequence','kind','identity','tick_ns','previous_head'})
   need(type(event['sequence']) is int and event['sequence']==sequence and event['previous_head']==prev,'LIFECYCLE_ORDER_OR_HEAD_GAP','INDETERMINATE')
   need(integer(event['tick_ns'],1) and event['tick_ns']>last_time,'LIFECYCLE_TIME_REORDER','INDETERMINATE');last_time=event['tick_ns']
   accepted().identity(event['identity']);key=event['identity']['hwnd'];groups.setdefault(key,[]).append(event)
   prev=digest(event)
  need(prev==model['witness_final_head'],'EXTERNAL_WITNESS_FINAL_HEAD')
  for events in groups.values():
   self._state_machine(events)
  self.proof=proof;self.groups=groups;self.final_head=prev;self.source_hash=digest(proof)
 @staticmethod
 def _state_machine(events):
  need(len(events)>=2,'INCOMPLETE_WINDOW_LIFECYCLE','INDETERMINATE');identity=events[0]['identity']
  for row in events:need(row['identity']==identity,'LIFECYCLE_IDENTITY_OR_GENERATION_MISMATCH','INDETERMINATE')
  minimal={'source':'SYNTHETIC_LOSSLESS_LIFECYCLE_LEDGER','coverage':'COMPLETE_SYNTHETIC_TRACE','lost_events':0,'epoch_before':identity['window_epoch'],'epoch_after':identity['window_epoch'],
   'events':[{'sequence':i,'kind':row['kind'],'hwnd':identity['hwnd'],'epoch':row['identity']['window_epoch']} for i,row in enumerate(events,1)]}
  try:accepted().lifecycle(minimal,identity,identity)
  except ValueError as exc:raise ValueError('LIFECYCLE_STATE_MACHINE:'+str(exc)) from exc
 def generation(self,hwnd,pid,tid,creation):
  need(digest(self.proof)==self.source_hash,'WITNESS_MUTATED')
  need(hwnd in self.groups,'MISSING_WINDOW_LIFECYCLE','INDETERMINATE');row=self.groups[hwnd][0]['identity']
  need(row['pid']==pid and row['tid']==tid and row['creation_filetime_100ns']==creation,'WINDOW_REUSE_OR_PROCESS_RESTART','INDETERMINATE');return row['window_epoch']
 def verify(self,identity,start,end,enumerated):
  need(digest(self.proof)==self.source_hash,'WITNESS_MUTATED')
  need(set(self.groups)==set(enumerated),'ENUMERATION_LIFECYCLE_SET_MISMATCH','INDETERMINATE')
  need(self.proof['begin_ns']<=start<=end<=self.proof['end_ns'],'INCOMPLETE_LIFECYCLE_COVERAGE','INDETERMINATE')
  for group in self.groups.values():need(group[0]['tick_ns']<=start and group[-1]['tick_ns']>=end,'INCOMPLETE_WINDOW_INTERVAL','INDETERMINATE')
  events=self.groups.get(identity['hwnd'],[]);need(len(events)>=2,'INCOMPLETE_WINDOW_LIFECYCLE','INDETERMINATE')
  need(events[0]['tick_ns']<=start and events[-1]['tick_ns']>=end,'INCOMPLETE_WINDOW_INTERVAL','INDETERMINATE')
  for row in events:need(row['identity']==identity,'LIFECYCLE_IDENTITY_OR_GENERATION_MISMATCH','INDETERMINATE')
  self._state_machine(events)
  return {'status':'VERIFIED_SYNTHETIC_LIFECYCLE_ONLY','head':self.final_head,'generation':identity['window_epoch'],'native_lossless_claim':False}
