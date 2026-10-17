"""Real lifecycle feasibility contract; refuses unverifiable lossless claims."""
import copy
from gui_native_preflight.protocol import require,exact,uint,digest,hash64
from .contracts import blocked_runtime

class WitnessContract:
    def __init__(self,independent_prefix):
        exact(independent_prefix,{'sequence','head','host','boot','clock_domain','generation','begin_tick','end_tick','final_sequence','final_head','oracle_sha256'})
        require(uint(independent_prefix['sequence'],64) and hash64(independent_prefix['head']) and hash64(independent_prefix['final_head']) and hash64(independent_prefix['oracle_sha256']) and uint(independent_prefix['final_sequence'],64,1) and uint(independent_prefix['generation'],64,1) and uint(independent_prefix['begin_tick'],64,1) and uint(independent_prefix['end_tick'],64,1) and independent_prefix['begin_tick']<independent_prefix['end_tick'],'WITNESS_EXTERNAL_PREFIX');self.prefix=copy.deepcopy(independent_prefix);self.pin=digest(self.prefix)
    def assess(self,observation):
        require(digest(self.prefix)==self.pin,'PREFIX_CHANGED')
        exact(observation,{'source','host','boot','clock_domain','begin_tick','end_tick','events_lost','buffers_lost','coverage_certificate','generation_provenance','events'})
        require(type(observation['events_lost']) is int and observation['events_lost']==0 and type(observation['buffers_lost']) is int and observation['buffers_lost']==0,'KNOWN_EVENT_LOSS','INDETERMINATE')
        # Zero loss counters do not show that the provider emitted every event,
        # that the subscriber was ready, or that HWND generation is trustworthy.
        if observation['source'] in {'WinEvent','ETW','HWND_BEFORE_AFTER','SIGNED_NATIVE_LABEL'}:
            return {'state':'INDETERMINATE','RT-04':'BLOCKED','reason':'REAL_SOURCE_COMPLETENESS_GENERATION_AND_INTERVAL_UNPROVEN',**blocked_runtime()}
        require(observation['source']=='SYNTHETIC_COMPLETE_ORACLE' and observation['coverage_certificate']=='SYNTHETIC_ORACLE_EXACT_FINITE_INTERVAL' and observation['generation_provenance']=='SYNTHETIC_INDEPENDENT_GENERATION','UNKNOWN_WITNESS_PROVENANCE','INDETERMINATE')
        for key in ['host','boot','clock_domain','begin_tick','end_tick']:require(type(observation[key]) is type(self.prefix[key]) and observation[key]==self.prefix[key],'WITNESS_CONTEXT_INTERVAL')
        events=observation['events'];require(type(events) is list and 2<=len(events)<=512 and digest(events)==self.prefix['oracle_sha256'],'INCOMPLETE_EVENT_INTERVAL','INDETERMINATE');seq=self.prefix['sequence'];head=self.prefix['head'];last=0
        for i,event in enumerate(events):
            exact(event,{'sequence','previous_head','tick','kind','generation','hwnd','pid','tid','creation'})
            require(uint(event['sequence'],64,1) and event['sequence']==seq+1 and event['previous_head']==head and uint(event['tick'],64,1) and self.prefix['begin_tick']<=event['tick']<=self.prefix['end_tick'] and event['tick']>last,'WITNESS_LOSS_REORDER','INDETERMINATE')
            require(type(event['generation']) is int and event['generation']==self.prefix['generation'] and uint(event['hwnd'],64,1) and uint(event['pid'],32,1) and uint(event['tid'],32,1) and uint(event['creation'],64,1),'WITNESS_IDENTITY_TYPE','INDETERMINATE')
            identity=(event['hwnd'],event['pid'],event['tid'],event['creation'])
            if i==0:require(event['kind']=='CREATE','INITIAL_CREATE_REQUIRED','INDETERMINATE');initial=identity
            else:require(event['kind']=='UNCHANGED' and identity==initial,'DUPLICATE_CREATE_DESTROY_OR_REUSE','INDETERMINATE')
            seq=event['sequence'];head=digest(event);last=event['tick']
        require(events[0]['tick']==self.prefix['begin_tick'] and events[-1]['tick']==self.prefix['end_tick'],'FULL_INTERVAL_REQUIRED','INDETERMINATE')
        require(seq==self.prefix['final_sequence'] and head==self.prefix['final_head'],'EXTERNAL_FINAL_HEAD')
        return {'state':'OFFLINE_SYNTHETIC_WITNESS_ONLY','final_sequence':seq,'final_head':head,'RT-04':'BLOCKED',**blocked_runtime()}

def verify_signed_witness(admission,witness,external_ack,independent_prefix,tick):
    from .authority import Admission
    require(type(admission) is Admission,'ADMISSION_REQUIRED');admission.check(tick)
    for envelope in [witness,external_ack]:require(envelope['signer'] not in admission.revocation['revoked_keys'],'REVOKED_WITNESS_AUTHORITY')
    observation=admission.root.verify(witness,'WITNESS');ack=admission.root.verify(external_ack,'EXTERNAL')
    exact(ack,{'source','permit_sha256','scope_sha256','prefix_sha256','observation_sha256'})
    require(ack['source']=='SYNTHETIC_INDEPENDENT_EXTERNAL_HEAD_ACK' and ack['permit_sha256']==digest(admission.permit) and ack['scope_sha256']==admission.permit['scope_sha256'] and ack['prefix_sha256']==digest(independent_prefix) and ack['observation_sha256']==digest(observation),'INDEPENDENT_WITNESS_ACK_MODEL_SCOPE')
    scope=admission.permit['scope']
    require(all(type(independent_prefix[k]) is type(scope[k]) and independent_prefix[k]==scope[k] for k in ['host','boot','generation']) and independent_prefix['clock_domain']==admission.clock['domain'],'WITNESS_SCOPE_HOST_BOOT_GENERATION_CLOCK')
    result=WitnessContract(independent_prefix).assess(observation)
    if result['state']=='OFFLINE_SYNTHETIC_WITNESS_ONLY':
        identity=observation['events'][0];require(all(identity[k]==scope['target_'+k] for k in ['hwnd','pid','tid','creation']),'WITNESS_TARGET_SCOPE_IDENTITY')
    return result
