"""Emit versioned offline contract/schema; no host/target observations or grants."""
import json,importlib.util,sys
from pathlib import Path
P=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('gate2_contract_model',P/'identity_binding.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
def obj(props,required=None):return {'type':'object','properties':props,'required':list(props) if required is None else required,'additionalProperties':False}
def arr(item):return {'type':'array','items':item}
def ref(name):return {'$ref':'#/$defs/'+name}
s={'type':'string'};i={'type':'integer','minimum':1,'maximum':2**64-1};u={'type':'integer','minimum':0,'maximum':2**64-1};b={'type':'boolean'};h={'type':'string','pattern':'^[0-9a-f]{64}$'}
ident=obj({k:(h if k=='executable_sha256' else i if k in {'pid','tid','session_id','hwnd','creation_filetime_100ns','window_epoch'} else s) for k in sorted(m.IDENTITY_KEYS)})
policy=obj({k:ident['properties'][k] for k in ['host','session_id','desktop','observer_station','executable_path','executable_sha256','volume_serial','file_id','class_name']})
scope=obj({'allowed_apis':arr({'enum':sorted(m.DIAGNOSTIC_APIS|m.IDENTITY_APIS)}),'read_fields':arr({'enum':sorted(m.DIAGNOSTIC_FIELDS|m.IDENTITY_FIELDS)}),
    'access_rights':obj({'process':{'const':4096},'token':{'const':8},'file':{'const':129}}),
    'enumeration_bounds':obj({'max_windows':{'type':'integer','minimum':0,'maximum':4096},'max_candidates':{'const':1},'max_title_reads':{'type':'integer','minimum':0,'maximum':2}}),
    'timeouts':obj({'per_call_ms':{'type':'integer','minimum':1,'maximum':5000},'total_ms':{'type':'integer','minimum':1,'maximum':60000}}),
    'evidence_destination':s,'target_policy':ref('policy')})
model=obj({'artifact_kind':{'const':m.PURPOSE},'stage':{'enum':['IDENTITY_ONLY','BOUND_DIAGNOSTIC']},'attempt_id':{'type':'string','pattern':'^SYNTHETIC-[A-Za-z0-9-]{8,80}$'},
    'issued_ns':i,'expires_ns':i,'scope':ref('scope'),'scope_sha256':h,'tool_sha256':h,'schema_sha256':h,
    'identity_binding':obj({'mode':{'enum':['UNRESOLVED_IDENTITY_ONLY','EXACT_REVIEWED_TARGET']},'target_identity_sha256':{'type':['string','null']},'resolution_evidence_sha256':{'type':['string','null']},'review_ack_sha256':{'type':['string','null']}})})
life=obj({'source':{'const':m.LIFECYCLE_SOURCE},'coverage':{'const':'COMPLETE_SYNTHETIC_TRACE'},'lost_events':{'const':0},'epoch_before':i,'epoch_after':i,
    'events':arr(obj({'sequence':i,'kind':{'enum':['CREATE','UNCHANGED','DESTROY']},'hwnd':i,'epoch':i}))})
candidate=obj({'before':ref('identity'),'after':ref('identity'),'lifecycle':ref('lifecycle')})
resolution=obj({'artifact_kind':{'const':m.PURPOSE},'scope_sha256':h,'enumeration_count':u,'enumeration_complete':b,'candidates':arr(ref('candidate'))})
resolved=obj({'artifact_kind':{'const':m.PURPOSE},'status':{'const':'RESOLVED_SYNTHETIC_REQUIRES_INDEPENDENT_REVIEW'},'scope_sha256':h,'resolution_evidence_sha256':h,
    'target_identity':ref('identity'),'target_identity_sha256':h,'diagnostic_authorized':{'const':False},'gate2_final_status':{'const':'BLOCKED_PENDING_SEPARATE_IDENTITY_RESOLUTION_AND_REVIEW'}})
ack=obj({'artifact_kind':{'const':m.PURPOSE},'decision':{'const':'SYNTHETIC_REVIEW_ACK_ONLY_NOT_CONTROL_CENTER_AUTHORITY'},'resolution_evidence_sha256':h,'target_identity_sha256':h,
    'diagnostic_scope_sha256':h,'issued_ns':i,'expires_ns':i})
schema={'$schema':'https://json-schema.org/draft/2020-12/schema','$id':'urn:rate:gui:gate2:offline-model:v1','title':'Offline synthetic identity model only; not a live Execution Permit',
    'oneOf':[obj({'operation':{'const':'IDENTITY_RESOLUTION'},'model':ref('model'),'evidence':ref('resolution')}),obj({'operation':{'const':'BOUND_DIAGNOSTIC'},'model':ref('model'),'resolved':ref('resolved'),'ack':ref('ack'),'evidence':{'type':'object'}})],
    '$defs':{'identity':ident,'policy':policy,'scope':scope,'model':model,'lifecycle':life,'candidate':candidate,'resolution':resolution,'resolved':resolved,'ack':ack}}
contract={'contract':'RATE_GUI_TARGET_IDENTITY_BINDING_CONTRACT_V1','engineering_mode':'OFFLINE_SYNTHETIC_ONLY','blocking_defect':'RATE-GUI-AUTH-TARGET-001',
    'gate2_final_status':'BLOCKED_PENDING_SEPARATE_IDENTITY_RESOLUTION_AND_REVIEW','execution_authorized':False,
    'phase_a':'Review a fixed Host/Session/Desktop/observer Station and exact executable path/SHA256/volume+file ID/class predicate. No live target is inferred from historical observations.',
    'phase_b':'Only a separately authorized identity-only adapter may collect bounded descriptor/seed candidates, process creation+image/file identity and independent window-generation evidence. Exactly one valid candidate is required; any unknown or ambiguity halts.',
    'phase_c':'Identity resolution produces evidence only. Independent Control Center review must bind its evidence SHA, exact identity SHA and a separate diagnostic Read Scope SHA; a separate diagnostic authority is required. Identity-only authority never diagnoses.',
    'process_instance':['host','session_id','pid','creation_filetime_100ns','executable_path','executable_sha256','volume_serial','file_id'],
    'window_instance':['hwnd','tid','class_name','desktop','observer_station_scope','independent_window_generation_evidence'],
    'title_role':'Auxiliary evidence only after bound-target verification; original exact three captions, two-read reliability, Full/Admin/High/Session/Desktop and exactly-one requirements retained.',
    'scope_role':'Identity-only permits bounded discovery; Diagnostic forbids EnumWindows and requires the approved exact target before and after each read. No title-driven fallback or rediscovery.',
    'synthetic_schema':'TARGET_IDENTITY_BINDING_SCHEMA_V1.json',
    'future_real_authorization_required_fields':['independent authority/source pins','role identity-only or bound diagnostic','fresh attempt/nonce and UTC validity','exact Tool/Schema SHA256','exact Host/Session/Desktop/observer Station scope','exact executable path/SHA256/volume+file identity/class predicate','phase-specific exact API/read-field map/access rights/bounds/timeouts/output root','for diagnostic: approved resolved PID+creation/HWND+TID+generation identity, resolution evidence SHA and independent review ACK'],
    'native_implementation':'NOT_IMPLEMENTED_NOT_AUTHORIZED; no native Permit loader or transport exists in the new component.',
    'window_generation_requirement':'Synthetic tests use an explicit lossless lifecycle ledger; this is NOT a Win32 window creation timestamp or a claim that such native evidence already exists. A separately engineered/reviewed provider must justify provenance, complete coverage, event loss/order and reuse detection. If unprovable, identity remains UNKNOWN.',
    'non_atomic':'All sequential reads remain non-atomic; change-and-return or later changes cannot be universally excluded. No atomic snapshot/continuous-state guarantee.',
    'real_identity_evidence_requires_new_review':True,'original_halt_root_cause':'UNKNOWN','formal_execution_permits_created':0}
boundary={'contract':'RATE_GUI_AUTHORIZED_READ_BOUNDARY_CONTRACT_V1','read_only':True,'native_execution_authorized':False,
    'identity_only_apis':sorted(m.IDENTITY_APIS),'bound_diagnostic_apis':sorted(m.DIAGNOSTIC_APIS),'api_field_map':{k:sorted(v) for k,v in m.API_FIELDS.items()},
    'identity_only_fields':sorted(m.IDENTITY_FIELDS),'bound_diagnostic_fields':sorted(m.DIAGNOSTIC_FIELDS),
    'access_rights':{'process':4096,'token':8,'file':129},'file_scope':'Only the exact approved executable path may be read/hash-verified; no arbitrary filesystem, process-memory or environment reads.',
    'enumeration':'One separately authorized bounded discovery only, integer1..4096 windows, exactly1 candidate. Diagnostic enumeration bound=0. Registered seeds only; no arbitrary PID probing.',
    'read_plan':'Fixed original title two-read plan; no resize/retry/third read. Generic Read Guard consumes a synthetic attempt before admitted model validation and permanently poisons failed/pending attempts.',
    'timeouts':{'per_call_ms_range':[1,5000],'total_ms_range':[1,60000],'enforcement':'Pre-call expiration/total deadline, post-call duration/total deadline; actual native cancellation/containment must be independently engineered before any real provider is eligible.'},
    'destination':'A separately issued absent physical evidence root under D:\\Codex\\RATE-GUI-GATE2-RUNS; no reparse/junction/redirection or overwrite. This component makes no evidence/OS writes itself.',
    'future_native_prerequisites':['Unforgeable native-adapter capability to honor approved call tickets and API arguments, not untrusted caller assertions','Physical output-root validation plus durable exclusive intent/attempt ledger before first real call; preserve crash/partial/unknown outcome','Independently validated executable canonical path/file identity/hash before and after reads; disk image SHA is not proof of loaded memory image integrity','Explicit lifecycle witness provenance/coverage for HWND replacement; no self-declared boolean assurance','Independent process/token/session/desktop observations and future identity evidence ACK'],
    'prohibited':['GUI control/input/focus/text','Pagefile/CrashControl/system setting change','UAC escalation or privilege adjustment','Process termination/injection','Production/Campaign/Ledger/strategy changes','Retry/Resume/Repair/Cleanup','Original HALT/Collector mutation or rerun','Use of historical PID/HWND as authority','Automatic diagnosis after identity resolution'],
    'original_halting_evidence_preserved':True,'no_auto_next':True}
mode='wb' if sys.argv[1:]==['--update-unsealed-new-contracts'] else 'xb'
for name,value in [('TARGET_IDENTITY_BINDING_SCHEMA_V1.json',schema),('TARGET_IDENTITY_BINDING_CONTRACT_V1.json',contract),('AUTHORIZED_READ_BOUNDARY_CONTRACT_V1.json',boundary)]:
    with (P/name).open(mode) as f:f.write(json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2).encode('utf-8'))
print('GENERATED_OFFLINE_CONTRACTS_NO_EXECUTION_PERMIT')
