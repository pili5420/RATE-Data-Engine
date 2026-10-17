"""Data-only Job Object/cancel/unknown-outcome state machine. No OS dispatch."""
import copy
from gui_native_preflight.protocol import require,exact,uint,digest,hash64
from .contracts import blocked_runtime

JOB_KILL_ON_CLOSE=0x2000
JOB_ACTIVE_PROCESS_LIMIT=0x8
JOB_FLAGS=JOB_KILL_ON_CLOSE|JOB_ACTIVE_PROCESS_LIMIT

def extended_job_limits(abi):
    require(abi in {'win32','win64'},'WINDOWS_ABI')
    return {'basic_limit_size':48 if abi=='win32' else 64,
            'extended_limit_size':112 if abi=='win32' else 144,
            'limit_flags_offset':16,'active_process_limit_offset':28 if abi=='win32' else 40,
            'flags':JOB_FLAGS,'active_process_limit':1,'native_qualified':False}

class ContainmentModel:
    """Only signed/mock supervisor observations can drive this offline model.

    A cancellation request never proves cancellation. All timeout/crash/unknown
    outcomes remain UNKNOWN even after a later child-exit observation.
    """
    def __init__(self,attempt_id,deadline):
        require(type(attempt_id) is str and attempt_id.startswith('SYNTHETIC-') and uint(deadline,64,1),'SYNTHETIC_CONTAINMENT_CONTEXT')
        self.attempt=attempt_id;self.deadline=deadline;self.state='NEW';self.last_tick=0;self.sequence=0;self.head='0'*64;self.child=None;self.records=[];self.stopped=False
    def event(self,event):
        require(not self.stopped,'TERMINAL_NO_RESUME_RETRY')
        try:
            exact(event,{'source','sequence','previous_head','tick','kind','data'})
            require(event['source']=='SYNTHETIC_SUPERVISOR_ORACLE' and uint(event['sequence'],64,1) and event['sequence']==self.sequence+1 and event['previous_head']==self.head and uint(event['tick'],64,1) and event['tick']>self.last_tick,'CONTAINMENT_EVENT_LOSS_OR_REORDER','INDETERMINATE')
            kind,data=event['kind'],event['data'];require(type(data) is dict,'EVENT_SCHEMA')
            if kind in {'CRASH','IPC_LOSS','ASSIGN_FAILED','UNKNOWN_RESULT','TIMEOUT'}:
                exact(data,set());self.state='UNKNOWN';self.stopped=True
            elif event['tick']>=self.deadline:
                self.state='UNKNOWN';self.stopped=True
            elif self.state=='NEW' and kind=='JOB_CONFIGURED':
                exact(data,{'flags','active_process_limit','inherit_job_handle','job_nonce'});require(type(data['flags']) is int and data['flags']==JOB_FLAGS and type(data['active_process_limit']) is int and data['active_process_limit']==1 and data['inherit_job_handle'] is False and type(data['job_nonce']) is str and data['job_nonce'].startswith('SYNTHETIC-'),'JOB_BREAKAWAY_INHERITANCE_OR_LIMIT');self.job_nonce=data['job_nonce'];self.state='JOB_CONFIGURED'
            elif self.state=='JOB_CONFIGURED' and kind=='CHILD_SUSPENDED':
                exact(data,{'pid','creation','suspended','inherited_handles'});require(uint(data['pid'],32,1) and uint(data['creation'],64,1) and data['suspended'] is True and data['inherited_handles']==['SYNTHETIC-IPC-ONLY'],'CHILD_SUSPENSION_HANDLE_BOUNDARY');self.child=copy.deepcopy(data);self.state='CHILD_SUSPENDED'
            elif self.state=='CHILD_SUSPENDED' and kind=='ASSIGNED':
                exact(data,{'pid','creation','job_nonce'});require(type(data['pid']) is int and type(data['creation']) is int and data['pid']==self.child['pid'] and data['creation']==self.child['creation'] and data['job_nonce']==self.job_nonce,'ASSIGNMENT_PID_REUSE_JOB_MISMATCH');self.state='ASSIGNED'
            elif self.state=='ASSIGNED' and kind=='INTENT_DURABLE':
                exact(data,{'attempt_id','intent_sha256','outside_head_sha256'});require(data['attempt_id']==self.attempt and hash64(data['intent_sha256']) and hash64(data['outside_head_sha256']),'DURABLE_INTENT_REQUIRED');self.intent=copy.deepcopy(data);self.state='INTENT_DURABLE'
            elif self.state=='INTENT_DURABLE' and kind=='RESUME':
                exact(data,{'pid','creation'});require(type(data['pid']) is int and type(data['creation']) is int and data['pid']==self.child['pid'] and data['creation']==self.child['creation'],'RESUME_PID_IDENTITY');self.state='RUNNING'
            elif self.state=='RUNNING' and kind=='CANCEL_REQUESTED':
                exact(data,{'pid','creation'});require(data['pid']==self.child['pid'] and type(data['pid']) is int and data['creation']==self.child['creation'] and type(data['creation']) is int,'CANCEL_WRONG_PROCESS');self.state='UNKNOWN';self.stopped=True
            elif self.state=='RUNNING' and kind=='RESULT_AND_EXIT':
                exact(data,{'pid','creation','exit_code','active_processes','result_sha256','external_ack_sha256'});require(type(data['pid']) is int and type(data['creation']) is int and data['pid']==self.child['pid'] and data['creation']==self.child['creation'] and type(data['exit_code']) is int and data['exit_code']==0 and type(data['active_processes']) is int and data['active_processes']==0 and hash64(data['result_sha256']) and hash64(data['external_ack_sha256']),'EXIT_DESCENDANT_OR_RESULT_UNKNOWN');self.state='OFFLINE_TRANSCRIPT_COMPLETE';self.stopped=True
            else:raise ValueError('INVALID_CONTAINMENT_TRANSITION')
        except Exception:
            self.state='UNKNOWN';self.stopped=True;raise
        finally:
            self.records.append(copy.deepcopy(event))
            if type(event) is dict and all(k in event for k in ['sequence','tick']):self.sequence=event['sequence'];self.last_tick=event['tick']
            self.head=digest({'event':event,'state':self.state})
        return {'state':self.state,'kill_tree_required':self.state=='UNKNOWN','native_job_object_verified':False,**blocked_runtime()}
