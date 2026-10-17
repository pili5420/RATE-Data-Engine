import copy,hashlib
from uuid import uuid4
from ..contracts import KIND,PROVIDER_KIND,WITNESS_KIND,SCOPE
from ..protocol import digest,code_identity,schema_identity
from ..provider import ScriptedWindowsProvider
IMAGE=r'C:\Windows\System32\SystemPropertiesPerformance.exe'
DATA=b'SYNTHETIC-WINDOWS-IMAGE-ONLY-NO-REAL-EXECUTABLE'
CREATION=134366334000000000
def identity(n=1):
 return {'host':'SYNTHETIC-HOST-ONLY','session_id':1,'desktop':'Default','observer_station':'WinSta0','pid':100+n,'tid':200+n,'hwnd':n,'class_name':'#32770','creation_filetime_100ns':CREATION+n,'executable_path':IMAGE,'executable_sha256':hashlib.sha256(DATA).hexdigest(),'volume_serial':'0000000000000001','file_id':'11'*16,'window_epoch':7+n}
def scenario(count=1):
 token={'elevated':1,'elevation_type':2,'integrity_rid':12288,'admin_attributes':15}
 processes={str(p):{'creation':CREATION+p,'session_id':1,'path':IMAGE,'token':copy.deepcopy(token)} for p in [10,11]}
 windows=[]
 for n in range(1,count+1):
  i=identity(n);windows.append({k:i[k] for k in ['hwnd','pid','tid','class_name','session_id','desktop']}|{'alive':True});processes[str(i['pid'])]={'creation':i['creation_filetime_100ns'],'session_id':1,'path':IMAGE,'token':copy.deepcopy(token)}
 return {'artifact_kind':PROVIDER_KIND,'host':'SYNTHETIC-HOST-ONLY','observer':{'pid':10,'tid':20,'desktop':'Default','station':'WinSta0'},'windows':windows,'processes':processes,'file':{'path':IMAGE,'hex':DATA.hex(),'volume_serial':1,'file_id':'11'*16,'creation':100,'write':200,'change':300,'attributes':32},'faults':[],'start_ns':10000,'step_ns':1000}
def witness(count=1):
 proof={'artifact_kind':WITNESS_KIND,'boot_id':'SYNTHETIC-BOOT-001','coverage':'COMPLETE_SYNTHETIC_STREAM','lost_events':0,'begin_ns':500,'end_ns':10000000+max(count,1),'pre_head':'0'*64,'events':[]}
 for n in range(1,count+1):proof['events'].append({'sequence':len(proof['events'])+1,'kind':'CREATE','identity':identity(n),'tick_ns':100+n,'previous_head':''})
 for n in range(1,count+1):proof['events'].append({'sequence':len(proof['events'])+1,'kind':'UNCHANGED','identity':identity(n),'tick_ns':10000000+n,'previous_head':''})
 rehead(proof);return proof
def rehead(proof):
 prev=proof['pre_head']
 for e in proof['events']:e['previous_head']=prev;prev=digest(e)
 return prev
def bundle(workspace,count=1,attempt=None,nonce=None):
 world=scenario(count);proof=witness(max(count,1));provider=ScriptedWindowsProvider(world);i=identity();policy={k:i[k] for k in ['host','session_id','desktop','observer_station','executable_path','executable_sha256','volume_serial','file_id','class_name']}|{'boot_id':'SYNTHETIC-BOOT-001'}
 scope={'read_boundary':copy.deepcopy(SCOPE),'policy':policy,'observer':{'pid':10,'tid':20,'parent_pid':11,'creation':CREATION+10,'parent_creation':CREATION+11,'origin':'SYNTHETIC_OWNER_HANDOFF_NOT_NATIVE_PROVENANCE'},'max_windows':8,'max_file_bytes':4096,'chunk_bytes':16,'max_calls':500,'per_call_ms':1000,'total_ms':10000}
 attempt=attempt or 'SYNTHETIC-'+uuid4().hex;nonce=nonce or 'SYNTHETIC-'+uuid4().hex
 model={'artifact_kind':KIND,'stage':'IDENTITY_ONLY','attempt_id':attempt,'nonce':nonce,'issued_tick_ns':1000,'expires_tick_ns':1000000000000,'tool_sha256':code_identity(),'schema_sha256':schema_identity(),'scope':scope,'scope_sha256':digest(scope),'provider_sha256':provider.identity,'witness_sha256':digest(proof),'witness_pre_head':proof['pre_head'],'witness_final_head':rehead(proof),'workspace':str(workspace.root),'journal_root':str(workspace.journal),'evidence_root':str(workspace.evidence/attempt)}
 return model,provider,proof
def replace_provider(model,world):p=ScriptedWindowsProvider(world);model['provider_sha256']=p.identity;return p
def bind_witness(model,proof):model['witness_final_head']=rehead(proof);model['witness_sha256']=digest(proof)
def ack(result,model):return {'artifact_kind':'SYNTHETIC_REVIEW_ACK_NOT_EXECUTION_AUTHORITY','decision':'INDEPENDENT_REVIEW_ONLY','identity_sha256':result['identity_sha256'],'evidence_sha256':digest(result),'scope_sha256':model['scope_sha256'],'tool_sha256':model['tool_sha256'],'schema_sha256':model['schema_sha256'],'diagnostic_authorized':False}
