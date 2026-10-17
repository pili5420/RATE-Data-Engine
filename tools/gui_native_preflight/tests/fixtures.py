import copy,hashlib,struct
from pathlib import Path
from uuid import uuid4
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding,PublicFormat
from ..contracts import *
from ..protocol import digest,code_identity,schema_identity
from ..abi import layout
DATA=b'SYNTHETIC-NQ-FIXTURE-IMAGE-NOT-REAL'
SID='S-1-5-21-111-222-333-1001'
class TestKeys:
 """Ephemeral TEST-only private objects; no serialization/export method."""
 def __init__(self):
  self.private={};rows=[]
  for role in ROLES.values():
   key=Ed25519PrivateKey.generate();public=key.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw);name='SYNTHETIC-'+role+'-'+hashlib.sha256(public).hexdigest()[:16];self.private[role]=(name,key);rows.append({'id':name,'role':role,'public_hex':public.hex()})
  self.bundle={'realm':REALM,'origin':'SYNTHETIC_EPHEMERAL_INDEPENDENT_TEST_KEYS','keys':rows}
 def sign(self,kind,payload):
  from ..trust import signed_bytes
  role=ROLES[kind];name,key=self.private[role];return {'version':1,'realm':REALM,'kind':kind,'role':role,'signer':name,'payload':copy.deepcopy(payload),'signature_hex':key.sign(signed_bytes(kind,role,payload)).hex()}
def sid_bytes(text):
 parts=[int(v) for v in text.split('-')[1:]];revision,authority,*subs=parts;return bytes([revision,len(subs)])+authority.to_bytes(6,'big')+struct.pack('<'+'I'*len(subs),*subs)
def allocation(name,data,abi,owner,capacity=None):
 cap=len(data) if capacity is None else capacity;return {'id':name,'owner':owner,'generation':1,'base':0x10000 if abi=='win32' else 0x100000000,'capacity':cap,'initialized':len(data),'data_hex':(data+b'\0'*(cap-len(data))).hex()}
def sid_allocation(info_class,abi,owner):
 l=layout(abi);ptr=l['pointer'];base=0x10000 if abi=='win32' else 0x100000000;group=info_class==2;offset=l['TOKEN_GROUPS_OFFSET'] if group else 0;table_end=offset+l['SID_AND_ATTRIBUTES'];text='S-1-5-32-544' if group else SID if info_class==1 else 'S-1-16-12288';attrs=15 if group else 0 if info_class==1 else 96
 table=bytearray(table_end)
 if group:table[:4]=(1).to_bytes(4,'little')
 table[offset:offset+ptr]=(base+table_end).to_bytes(ptr,'little');table[offset+ptr:offset+ptr+4]=attrs.to_bytes(4,'little');data=bytes(table)+sid_bytes(text);return allocation('token',data,abi,owner)
def target():return {'host':'SYNTHETIC-NQ-HOST','boot':'SYNTHETIC-NQ-BOOT','session':1,'desktop':'Default','station':'WinSta0','operator_sid':SID,'pid':1001,'creation':134366334000001000,'hwnd':0x2100,'tid':1002,'class_name':'#32770','executable_path':r'C:\SYNTHETIC-NQ\Fixture.exe','executable_sha256':hashlib.sha256(DATA).hexdigest(),'file_id':'11'*16,'generation':7}
def scenario(abi,attempt):
 t=target();handles={'process':0x5100,'token':0x5200,'file':0x5300,'generation':1};frames=[]
 def add(api,args,out,alloc,ret=1):
  tick=100+len(frames)*10;frames.append({'api':api,'args':args,'subject':{k:t[k] for k in ['pid','hwnd','tid','creation','generation']},'fields':list(APIS[api]),'rights':dict(RIGHTS),'start_tick':tick,'end_tick':tick+2,'status':'OK','last_error':0,'return_hex':struct.pack('<I',ret).hex(),'outputs':out,'allocations':[alloc]})
 for kind in [1,2,18,20,25]:
  row=sid_allocation(kind,abi,attempt) if kind in {1,2,25} else allocation('token',struct.pack('<I',2 if kind==18 else 1),abi,attempt)
  add('GetTokenInformation',{'handle':handles['token'],'info_class':kind,'buffer_bytes':row['capacity']},{'buffer':'token','returned_bytes':row['initialized']},row)
 add('GetWindowThreadProcessId',{'hwnd':t['hwnd']},{'pid_buffer':'pid'},allocation('pid',struct.pack('<I',t['pid']),abi,attempt),t['tid'])
 text=(t['class_name']+'\0').encode('utf-16-le');add('GetClassNameW',{'hwnd':t['hwnd'],'capacity':512},{'text_buffer':'text'},allocation('text',text,abi,attempt,1024),len(text)//2-1)
 add('GetProcessTimes',{'handle':handles['process']},{'times_buffer':'times'},allocation('times',struct.pack('<QQQQ',t['creation'],0,0,0),abi,attempt))
 text=(t['executable_path']+'\0').encode('utf-16-le');add('QueryFullProcessImageNameW',{'handle':handles['process'],'flags':0,'capacity':512},{'text_buffer':'text','count':len(text)//2-1},allocation('text',text,abi,attempt,1024))
 add('ReadFile',{'handle':handles['file'],'offset':0,'count':len(DATA)},{'data_buffer':'data','returned_bytes':len(DATA)},allocation('data',DATA,abi,attempt))
 return {'source':'SYNTHETIC_NATIVE_FRAME_TRANSPORT_ONLY','abi':abi,'attempt_id':attempt,'target_sha256':digest(t),'start_tick':100,'handles':handles,'frames':frames}
def rehead(events,pre='a'*64):
 previous=pre
 for e in events:e['previous_head']=previous;previous=digest(e)
 return previous
def make(root,keys,abi='win64'):
 root=Path(root);root.mkdir(exist_ok=True);attempt='SYNTHETIC-'+uuid4().hex;t=target();now=10_000_000_000
 scope={'boundary':copy.deepcopy(BOUNDARY),'abi':abi,'target':t,'max_calls':32,'per_call_ns':1000,'total_ns':10000,'evidence_root':str(root/'evidence'/attempt),'journal_root':str(root/'journal')}
 host={'source':'SYNTHETIC_HOST_ORACLE_NOT_NATIVE_ATTESTATION','host':t['host'],'boot':t['boot'],'session':1,'desktop':'Default','station':'WinSta0','operator_sid':SID,'observer_pid':701,'observer_tid':702,'observer_creation':134366334000000701,'parent_pid':700,'parent_creation':134366334000000700,'operator_token':{'elevated':True,'elevation_type':2,'integrity_sid':'S-1-16-12288','admin_enabled':True,'deny_only':False},'clock_domain':'SYNTHETIC-NQ-CLOCK','utc_ns':now}
 events=[{'sequence':98,'previous_head':'a'*64,'tick':2,'kind':'CREATE','identity':copy.deepcopy(t)},{'sequence':99,'previous_head':'','tick':9000,'kind':'UNCHANGED','identity':copy.deepcopy(t)}];end_head=rehead(events)
 oracle={'source':'SYNTHETIC_COMPLETE_EVENT_ORACLE_NOT_NATIVE','host':t['host'],'boot':t['boot'],'clock_domain':host['clock_domain'],'begin_tick':1,'end_tick':10000,'events':copy.deepcopy(events)}
 witness={'source':'SYNTHETIC_INDEPENDENT_WITNESS_NOT_NATIVE','oracle_sha256':digest(oracle),'coverage':'COMPLETE_SYNTHETIC_ORACLE_ONLY','loss':0,'pre_sequence':97,'pre_head':'a'*64,'events':copy.deepcopy(events),'begin_tick':1,'end_tick':10000,'host':t['host'],'boot':t['boot'],'clock_domain':host['clock_domain']}
 anchor={'source':'SYNTHETIC_EXTERNAL_ACK_ORACLE','scope_sha256':digest(scope),'attempt_id':attempt,'oracle_sha256':digest(oracle),'pre_sequence':97,'pre_head':'a'*64,'final_sequence':99,'final_head':end_head}
 rev={'source':'SYNTHETIC_REVOCATION_ORACLE','epoch':3,'issued_utc_ns':now-1,'expires_utc_ns':now+10_000_000,'revoked_keys':[],'revoked_nonces':[],'revoked_attempts':[]}
 model={'artifact_kind':MODEL_KIND,'realm':REALM,'stage':'IDENTITY_ONLY','attempt_id':attempt,'nonce':'SYNTHETIC-'+uuid4().hex,'issuer_sequence':500,'issued_utc_ns':now-1,'expires_utc_ns':now+1_000_000,'tool_sha256':code_identity(),'schema_sha256':schema_identity(),'scope':scope,'scope_sha256':digest(scope),'host_sha256':digest(host),'transport_sha256':'','revocation_epoch':3,'revocation_sha256':digest(rev),'witness_anchor_sha256':digest(anchor),'workspace':str(root),'native_execution_authorized':False,'diagnostic_authorized':False}
 transport=scenario(abi,attempt);model['transport_sha256']=digest(transport);anchor_id={'volume':1,'file_id':'22'*16,'handle_generation':1}
 fs={'source':'SYNTHETIC_ACL_DIRECTORY_ORACLE_NOT_NATIVE','path':str(root),'owner_sid':SID,'dacl_protected':True,'inherited_aces':0,'aces':[{'type':'ALLOW','sid':SID,'rights':'SYNTHETIC_PRIVATE_EVIDENCE_RW'}],'reparse':False,**anchor_id,'before_anchor':copy.deepcopy(anchor_id),'after_anchor':copy.deepcopy(anchor_id)}
 bundle={'issuer':keys.sign(MODEL_KIND,model),'host':keys.sign(HOST_KIND,host),'revocation':keys.sign(REVOKE_KIND,rev),'witness':keys.sign(WITNESS_KIND,witness),'anchor':keys.sign(ANCHOR_KIND,anchor),'oracle':oracle,'expected_pre':{'sequence':97,'head':'a'*64},'filesystem':fs,'expected':{'scope_sha256':digest(scope),'host_sha256':digest(host),'transport_sha256':digest(transport),'revocation_epoch':3,'revocation_sha256':digest(rev),'workspace':str(root),'now_utc_ns':now},'transport':transport}
 return bundle
def refresh(bundle,keys):
 m=bundle['issuer']['payload'];m['scope_sha256']=digest(m['scope']);m['host_sha256']=digest(bundle['host']['payload']);m['transport_sha256']=digest(bundle['transport']);m['revocation_sha256']=digest(bundle['revocation']['payload']);m['revocation_epoch']=bundle['revocation']['payload']['epoch'];m['witness_anchor_sha256']=digest(bundle['anchor']['payload'])
 bundle['expected'].update(scope_sha256=m['scope_sha256'],host_sha256=m['host_sha256'],transport_sha256=m['transport_sha256'],revocation_sha256=m['revocation_sha256'],revocation_epoch=m['revocation_epoch'])
 for key,kind in [('issuer',MODEL_KIND),('host',HOST_KIND),('revocation',REVOKE_KIND),('witness',WITNESS_KIND),('anchor',ANCHOR_KIND)]:bundle[key]=keys.sign(kind,bundle[key]['payload'])
 return bundle
