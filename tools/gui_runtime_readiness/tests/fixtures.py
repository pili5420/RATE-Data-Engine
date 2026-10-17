import copy,hashlib,struct
from pathlib import Path
from uuid import uuid4
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding,PublicFormat
from gui_native_preflight.protocol import digest
from gui_native_preflight.tests.fixtures import allocation,sid_allocation,sid_bytes
from ..contracts import REALM,ROLES,PURPOSES,source_identity,schema_identity
from ..authority import signed_bytes,SyntheticRoot
from ..bindings import PROTOTYPES,FIELDS,RIGHTS,SYNTHETIC_FILE
from ..filesystem import OWNER_EVIDENCE_MASK
DATA=b'RQR-INDEPENDENT-TEST-IMAGE-NOT-AN-EXECUTABLE'
SID='S-1-5-21-111-222-333-1001'

class Keys:
    def __init__(self):
        self.private={};rows=[]
        for role in ROLES:
            private=Ed25519PrivateKey.generate();public=private.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw);name='SYNTHETIC-'+role+'-'+hashlib.sha256(public).hexdigest()[:12];self.private[role]=(name,private);rows.append({'id':name,'role':role,'public_hex':public.hex()})
        self.bundle={'realm':REALM,'source':'EPHEMERAL_INDEPENDENT_TEST_ROOTS','keys':rows}
    def sign(self,role,payload):
        name,key=self.private[role];return {'version':1,'realm':REALM,'purpose':PURPOSES[role],'role':role,'signer':name,'payload':copy.deepcopy(payload),'signature_hex':key.sign(signed_bytes(role,payload)).hex()}
    def root(self):return SyntheticRoot(self.bundle,digest(self.bundle))

def scope():
    return {'stage':'IDENTITY_ONLY','host':'SYNTHETIC-RQR-HOST','boot':'SYNTHETIC-RQR-BOOT','session':1,'desktop':'Default','station':'WinSta0','observer_pid':701,'observer_tid':702,'observer_creation':134000000000000701,'operator_sid':SID,'parent_pid':700,'parent_creation':134000000000000700,'target_pid':1001,'target_tid':1002,'target_hwnd':0x2100,'target_creation':134000000000001001,'target_class':'#32770','target_executable_sha256':hashlib.sha256(DATA).hexdigest(),'target_file_id':'11'*16,'target_volume':17,'generation':7,'max_calls':64,'per_call_ns':100,'total_ns':10000,'apis':sorted(PROTOTYPES),'rights':dict(RIGHTS)}

def wire_data(abi,attempt,s):
    rows=[];ptr=4 if abi=='win32' else 8;subject=digest({k:s[k] for k in ['host','boot','session','target_pid','target_tid','target_hwnd','target_creation','target_class','target_executable_sha256','target_file_id','target_volume','generation']})
    def add(api,args,data=None,out=None,ret=1,capacity=None,handle_return=False):
        row=allocation('out',data,abi,attempt,capacity) if data is not None else None
        receipt={'source':'SYNTHETIC_OWNED_WIRE_RECEIPT','api':api,'abi':abi,'last_error':0,'return_hex':ret.to_bytes(ptr if handle_return else 4,'little').hex(),'outputs':out or {},'allocations':[row] if row else []}
        request={'api':api,'abi':abi,'args':args,'fields':list(FIELDS[api]),'rights':dict(RIGHTS)};start=100+len(rows)*10;rows.append({'request':request,'receipt':receipt,'start_tick':start,'end_tick':start+2,'subject_sha256':subject})
    def text(api,args,value,use_count=True,user_object=False):
        raw=(value+'\0').encode('utf-16-le');count=len(raw)//2-1;out={'buffer':'out'}
        if user_object:out['needed_bytes']=len(raw)
        elif use_count:out['count']=count
        cap=args.get('capacity',args.get('capacity_bytes',1024)//2);add(api,args,raw,out,1 if use_count or user_object else count,cap*2)
    text('GetComputerNameExW',{'format':5,'capacity':256},s['host'])
    add('GetCurrentProcessId',{},ret=s['observer_pid']);add('GetCurrentThreadId',{},ret=s['observer_tid'])
    add('ProcessIdToSessionId',{'pid':s['target_pid']},struct.pack('<I',1),{'buffer':'out'})
    add('GetProcessWindowStation',{},out={'generation':1},ret=0x6100,handle_return=True)
    add('GetThreadDesktop',{'tid':s['target_tid']},out={'generation':1},ret=0x6200,handle_return=True)
    for h,value in [(0x6100,s['station']),(0x6200,s['desktop'])]:text('GetUserObjectInformationW',{'handle':h,'index':2,'capacity_bytes':512},value,user_object=True)
    add('EnumWindows',{'max_windows':16},s['target_hwnd'].to_bytes(ptr,'little'),{'buffer':'out','count':1,'complete':True,'source':'SYNTHETIC_BOUNDED_CALLBACK_TRANSCRIPT'})
    add('IsWindow',{'hwnd':s['target_hwnd']})
    add('GetWindowThreadProcessId',{'hwnd':s['target_hwnd']},struct.pack('<I',s['target_pid']),{'buffer':'out'},s['target_tid'])
    text('GetClassNameW',{'hwnd':s['target_hwnd'],'capacity':256},s['target_class'],False)
    add('OpenProcess',{'access':4096,'inherit':0,'pid':s['target_pid']},out={'generation':1},ret=0x5100,handle_return=True)
    add('GetProcessTimes',{'handle':0x5100},struct.pack('<QQQQ',s['target_creation'],0,0,0),{'buffer':'out'})
    text('QueryFullProcessImageNameW',{'handle':0x5100,'flags':0,'capacity':256},SYNTHETIC_FILE)
    add('OpenProcessToken',{'handle':0x5100,'access':8},(0x5200).to_bytes(ptr,'little'),{'buffer':'out','generation':1})
    for kind in [1,2,18,20,25]:
        row=sid_allocation(kind,abi,attempt) if kind in {1,2,25} else allocation('out',struct.pack('<I',2 if kind==18 else 1),abi,attempt);row['id']='out'
        add('GetTokenInformation',{'handle':0x5200,'info_class':kind,'buffer_bytes':row['capacity']},out={'buffer':'out','returned_bytes':row['initialized']});rows[-1]['receipt']['allocations']=[row]
    add('CreateFileW',{'path':SYNTHETIC_FILE,'access':129,'share':7,'disposition':3,'flags':0x00200000,'inherit':0},out={'generation':1},ret=0x5300,handle_return=True)
    text('GetFinalPathNameByHandleW',{'handle':0x5300,'capacity':256,'flags':0},'\\'*2+'?'+'\\'+SYNTHETIC_FILE,False)
    for kind,data in [(18,struct.pack('<Q',s['target_volume'])+bytes.fromhex(s['target_file_id'])),(0,struct.pack('<QQQQII',s['target_creation'],0,0,0,0x20,0)),(1,struct.pack('<QQIBBxx',4096,len(DATA),1,0,0))]:add('GetFileInformationByHandleEx',{'handle':0x5300,'info_class':kind,'buffer_bytes':len(data)},data,{'buffer':'out'})
    add('ReadFile',{'handle':0x5300,'offset':0,'count':len(DATA)},DATA,{'buffer':'out','returned_bytes':len(DATA)})
    for h,kind in [(0x5300,'file'),(0x5200,'token'),(0x5100,'process')]:add('CloseHandle',{'handle':h,'kind':kind,'generation':1})
    return {'source':'SYNTHETIC_READINESS_TRANSPORT_ONLY','attempt_id':attempt,'scope_sha256':digest(s),'abi':abi,'frames':rows}

def make(keys,abi='win64',root=None):
    s=scope();attempt='SYNTHETIC-'+uuid4().hex;now=10000000000;clock={'source':'SYNTHETIC_INDEPENDENT_UTC_ORACLE','domain':'SYNTHETIC-CLOCK','sample_tick':100,'earliest_utc_ns':now,'latest_utc_ns':now+1,'max_age_ns':10000}
    root=Path(root) if root is not None else Path(r'D:\Codex')/('RATE-Gate2-Native-Offline-Tests-RQR-AUTH-'+uuid4().hex[:8]);s.update(workspace=str(root),journal_root=str(root/'journal'),evidence_root=str(root/'evidence'/attempt))
    claims={}
    for role,fields in [('HOST',['host','session','desktop','station']),('BOOT',['host','boot']),('OPERATOR',['host','boot','operator_sid','observer_pid','observer_creation']),('PARENT',['host','boot','session','operator_sid','observer_pid','observer_creation','parent_pid','parent_creation'])]:claims[role]={'source':'SYNTHETIC_'+role+'_ORACLE','issued_utc_ns':now-1,'expires_utc_ns':now+10000,**{k:s[k] for k in fields}}
    claims['BOOT']['clock_domain']=clock['domain'];claims['OPERATOR'].update(admin_enabled=True,high_integrity=True);claims['PARENT']['parent_path_sha256']='a'*64
    rev={'source':'SYNTHETIC_INDEPENDENT_REVOCATION_ORACLE','epoch':3,'issued_utc_ns':now-1,'expires_utc_ns':now+10000,'revoked_keys':[],'revoked_nonces':[],'revoked_attempts':[]}
    transport=wire_data(abi,attempt,s)
    permit={'artifact_kind':'RQR_SYNTHETIC_IDENTITY_ONLY_NOT_LIVE_PERMIT','attempt_id':attempt,'nonce':'SYNTHETIC-'+uuid4().hex,'issuer_sequence':501,'previous_head':'b'*64,'issued_utc_ns':now-1,'expires_utc_ns':now+10000,'tool_sha256':source_identity(),'schema_sha256':schema_identity(),'scope':s,'scope_sha256':digest(s),'transport_sha256':digest(transport),'provenance_sha256':digest(claims),'clock_sha256':digest(clock),'revocation_sha256':digest(rev),'revocation_epoch':3,'native_execution_authorized':False,'diagnostic_authorized':False}
    claims.update(ISSUER=permit,CLOCK=clock,REVOCATION=rev)
    out={'envelopes':{role:keys.sign(role,value) for role,value in claims.items()},'expected':{'root_sha256':digest(keys.bundle),'scope_sha256':digest(s),'transport_sha256':digest(transport),'provenance_sha256':permit['provenance_sha256'],'clock_sha256':digest(clock),'revocation_sha256':digest(rev),'revocation_epoch':3,'previous_sequence':500,'previous_head':'b'*64},'transport':transport}
    return out

def refresh(b,keys):
    envelopes=b['envelopes'];p=envelopes['ISSUER']['payload'];claims={k:v['payload'] for k,v in envelopes.items() if k in {'HOST','BOOT','OPERATOR','PARENT'}};p.update(scope_sha256=digest(p['scope']),transport_sha256=digest(b['transport']),provenance_sha256=digest(claims),clock_sha256=digest(envelopes['CLOCK']['payload']),revocation_sha256=digest(envelopes['REVOCATION']['payload']),revocation_epoch=envelopes['REVOCATION']['payload']['epoch'])
    b['transport']['scope_sha256']=p['scope_sha256'];p['transport_sha256']=digest(b['transport'])
    b['expected'].update(scope_sha256=p['scope_sha256'],transport_sha256=p['transport_sha256'],provenance_sha256=p['provenance_sha256'],clock_sha256=p['clock_sha256'],revocation_sha256=p['revocation_sha256'],revocation_epoch=p['revocation_epoch'])
    b['envelopes']={k:keys.sign(k,v['payload']) for k,v in envelopes.items()};return b

def descriptor_bytes():
    owner=sid_bytes(SID);ace=struct.pack('<BBHI',0,0,8+len(owner),OWNER_EVIDENCE_MASK)+owner;acl=struct.pack('<BBHHH',2,0,8+len(ace),1,0)+ace
    return struct.pack('<BBHIIII',1,0,0x9004,20,0,0,20+len(owner))+owner+acl

def lifecycle():
    events=[];head='c'*64
    for sequence,tick,kind in [(201,100,'CREATE'),(202,1000,'UNCHANGED')]:
        row={'sequence':sequence,'previous_head':head,'tick':tick,'kind':kind,'generation':7,'hwnd':0x2100,'pid':1001,'tid':1002,'creation':134000000000001001};events.append(row);head=digest(row)
    prefix={'sequence':200,'head':'c'*64,'host':'SYNTHETIC-RQR-HOST','boot':'SYNTHETIC-RQR-BOOT','clock_domain':'SYNTHETIC-CLOCK','generation':7,'begin_tick':100,'end_tick':1000,'final_sequence':202,'final_head':head,'oracle_sha256':digest(events)}
    observation={'source':'SYNTHETIC_COMPLETE_ORACLE','host':prefix['host'],'boot':prefix['boot'],'clock_domain':prefix['clock_domain'],'begin_tick':100,'end_tick':1000,'events_lost':0,'buffers_lost':0,'coverage_certificate':'SYNTHETIC_ORACLE_EXACT_FINITE_INTERVAL','generation_provenance':'SYNTHETIC_INDEPENDENT_GENERATION','events':events}
    return prefix,observation
