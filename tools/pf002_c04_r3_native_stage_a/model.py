"""Exact pure C04 subset; no parent/StageB classification or Native dispatch."""
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
