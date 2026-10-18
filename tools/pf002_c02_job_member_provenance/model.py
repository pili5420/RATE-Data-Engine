"""Pure ABI decoding and evidence classification. Never authorizes a member."""
import struct
class Unknown(ValueError):pass
def need(ok,code):
 if not ok:raise Unknown(code)
def acct(raw,returned):
 need(type(raw) is bytes and len(raw)==48 and type(returned) is int and returned==48,'ACCT_ABI_LENGTH')
 keys=('TotalUserTime','TotalKernelTime','ThisPeriodTotalUserTime','ThisPeriodTotalKernelTime','TotalPageFaultCount','TotalProcesses','ActiveProcesses','TotalTerminatedProcesses')
 values=struct.unpack('<4q4I',raw);row=dict(zip(keys,values))
 need(0<=row['ActiveProcesses']<=4 and all(v>=0 for v in values),'ACCT_VALUE_BOUND')
 return row
def ids(raw,returned,ptr):
 need(type(ptr) is int and ptr in (4,8) and type(raw) is bytes and len(raw)==8+4*ptr and type(returned) is int,'IDS_ABI')
 assigned,listed=struct.unpack_from('<II',raw)
 need(assigned==listed and listed<=4 and 8+listed*ptr<=returned<=len(raw),'IDS_INCOMPLETE_OR_BOUND')
 pids=list(struct.unpack_from('<'+('I' if ptr==4 else 'Q')*4,raw,8))[:listed]
 need(all(0<p<=0xffffffff for p in pids) and len(set(pids))==len(pids),'IDS_INVALID_PID')
 return {'assigned':assigned,'listed':listed,'pids':pids}
def pbi(raw,returned,ptr):
 need(type(ptr) is int and ptr in (4,8) and type(raw) is bytes and len(raw)==6*ptr and type(returned) is int and returned==len(raw),'PBI_ABI_LENGTH')
 pid=int.from_bytes(raw[4*ptr:5*ptr],'little');parent=int.from_bytes(raw[5*ptr:6*ptr],'little')
 need(0<pid<=0xffffffff and 0<=parent<=0xffffffff,'PBI_PID_BOUND')
 return {'pid':pid,'parent_pid':parent,'pid_offset':4*ptr,'parent_offset':5*ptr,'pid_raw_hex':raw[4*ptr:5*ptr].hex(),'parent_raw_hex':raw[5*ptr:6*ptr].hex()}
def classify(root,receipt,observations):
 """Specific parent linkage, not lossless lineage or trusted-domain promotion."""
 need(type(root) is dict and type(receipt) is dict and type(observations) is list and len(observations)==2,'DECISION_INPUT')
 need(type(root['pid']) is int and root['pid']>0 and type(root['creation_time_100ns']) is int and type(root['exit_time_100ns']) is int and root['exit_time_100ns']>=root['creation_time_100ns']>0,'ROOT_LIFETIME_UNKNOWN')
 need(type(receipt['pid']) is int and type(receipt['parent_pid']) is int and receipt['pid']>0,'WORKER_RECEIPT_PID')
 members={}
 for o in observations:
  for m in o['members']:
   need(type(m['pid']) is int and type(m['creation_time_100ns']) is int and m['creation_time_100ns']>0 and type(m['pbi']['pid']) is int and type(m['pbi']['parent_pid']) is int and m['pid']==m['pbi']['pid'] and m['membership_before'] is True and m['membership_after'] is True,'UNRELIABLE_MEMBER')
   key=m['pid'];identity=(m['creation_time_100ns'],m['image_path'],m['disk_image']['sha256'],m['pbi']['parent_pid'])
   if key in members:need(members[key][0]==identity,'MEMBER_IDENTITY_CHANGED')
   members[key]=(identity,m)
 unknown=[m[1] for pid,m in members.items() if pid!=root['pid']]
 proofs=[]
 for m in unknown:
  # Parent PID alone is insufficient: require original retained root lifetime,
  # stable native identity and the controlled worker's identity corroboration.
  within=root['creation_time_100ns']<=m['creation_time_100ns']<=root['exit_time_100ns']
  if m['pbi']['parent_pid']==root['pid'] and within:
   if receipt['pid']==m['pid'] and receipt['parent_pid']==root['pid'] and receipt['executable']==m['image_path']:
    proofs.append({'pid':m['pid'],'mechanism':'CREATEPROCESS_ROOT_DIFFERS_FROM_CONTROLLED_WORKER_PID'})
   elif receipt['pid']==root['pid'] and receipt['executable']==root['image_path']:
    proofs.append({'pid':m['pid'],'mechanism':'ADDITIONAL_DIRECT_CHILD_WITHIN_RETAINED_ROOT_LIFETIME'})
 matching=observations[1]['phase']=='AFTER_ROOT_WAIT' and observations[1]['accounting']['ActiveProcesses']>0 and any(p!=root['pid'] for p in observations[1]['ids']['pids'])
 proven=matching and bool(unknown) and len(proofs)==len(unknown)
 return {'root_cause':'PROVEN' if proven else 'UNPROVEN','root_cause_scope':'FRESH_EXPERIMENT_KNOWN_SET_MISMATCH_ONLY','historical_C01_root_cause':'UNPROVEN','job_assignment_origin':'PARENT_FIELD_IS_NOT_ASSIGNMENT_EVENT_TRACE','matching_C01_after_root_exit_pattern':matching,'mechanisms':proofs,'unconfirmed_member_pids':[m['pid'] for m in unknown],'trusted_member_allowlist_modified':False,'owned_domain':'OBSERVED_JOB_MEMBERSHIP_IS_NOT_AUTHORIZED_DOMAIN_EXPANSION','RS02':'BLOCKED','PF002_runtime':'BLOCKED','historical_C01_exact_PID_identities':'NOT_RETROSPECTIVELY_OBTAINABLE','specific_experiment_only':True,'atomic_or_lossless_lineage':False}
