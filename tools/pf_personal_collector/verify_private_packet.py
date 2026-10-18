"""Separate-process pure verification of private Runner evidence; never an acquisition entry.

This wrapper independently rehashes record files and raw bytes, but deliberately uses
the reviewed protocol for semantics. It is NOT an independent implementation of all
semantics and provides neither source authentication nor physical-host attestation.
Run only as Python -I -B -S <script> PRIVATE_PACKET.json EXACT_HEAD RUN_ID.
The caller verifies the source manifest against the official Exact Git Head first.
"""
import base64
import hashlib
import types
import json
import os
from pathlib import Path
import re
import sys

BASE_SHA='f28c9e71578fe98800e66257e7150e11a565e7e6367775760ca992a45dd72d06'
SCOPE_SHA='f96d742c5da542e1f2cd99cc6d49cd1b751ac0cb999c10d159ecb3f283ec5bd3'
REALM='RUNNER_ONLY_NOT_ORIGINAL_HOST_EVIDENCE'

class Rejected(ValueError):
    pass

def need(ok, code):
    if not ok:
        raise Rejected(code)

def sha(data):
    return hashlib.sha256(data).hexdigest()

def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode('utf-8')+b'\n'

def strict_json(data, bound=524288):
    need(type(data) is bytes and 0<len(data)<=bound,'VERIFIER_JSON_BYTE_BOUND')
    def pairs(items):
        value={}
        for key,item in items:
            need(key not in value,'VERIFIER_DUPLICATE_KEY')
            value[key]=item
        return value
    def no_constant(_):
        raise Rejected('VERIFIER_NONFINITE')
    try:
        return json.loads(data.decode('utf-8','strict'),object_pairs_hook=pairs,parse_constant=no_constant)
    except (UnicodeError,ValueError,RecursionError):
        raise Rejected('VERIFIER_JSON_INVALID') from None

def ordinary_file(path, bound):
    need(path.is_absolute() and path.resolve(strict=True)==path,'VERIFIER_PATH_ALIAS')
    for ancestor in (path,*path.parents):
        st=ancestor.lstat()
        need(not ancestor.is_symlink() and not(getattr(st,'st_file_attributes',0)&0x400),'VERIFIER_REPARSE')
    need(path.is_file() and 0<path.stat().st_size<=bound,'VERIFIER_FILE_BOUND')
    data=path.read_bytes()
    need(0<len(data)<=bound,'VERIFIER_FILE_CHANGED_OR_BOUND')
    return data

def read_sources(source):
    manifest_path=source/'SOURCE_MANIFEST_V1.json'
    manifest_raw=ordinary_file(manifest_path,262144)
    manifest=strict_json(manifest_raw,262144)
    need(type(manifest) is dict and type(manifest.get('files')) is dict,'VERIFIER_SOURCE_MANIFEST')
    entries=manifest['files']
    need(0<len(entries)<=128 and set(p.name for p in source.iterdir())==set(entries)|{'SOURCE_MANIFEST_V1.json'},'VERIFIER_EXACT_SOURCE_SET')
    for name,row in entries.items():
        need(type(name) is str and re.fullmatch(r'[A-Za-z0-9_.-]+',name) is not None and name not in ('.','..'),'VERIFIER_SOURCE_NAME')
        need(type(row) is dict and set(row)=={'bytes','sha256'} and type(row['bytes']) is int and 0<row['bytes']<=1048576 and type(row['sha256']) is str and re.fullmatch('[0-9a-f]{64}',row['sha256']) is not None,'VERIFIER_SOURCE_ENTRY')
        raw=ordinary_file(source/name,1048576)
        need(row=={'bytes':len(raw),'sha256':sha(raw)},'VERIFIER_SOURCE_HASH')
    need('evidence_protocol.py' in entries,'VERIFIER_PROTOCOL_REQUIRED')
    accepted=source.parent/'pf_personal_trust'
    base_raw=ordinary_file(accepted/'personal_model.py',1048576)
    scope_raw=ordinary_file(accepted/'READ_SCOPE_V1.json',65536)
    need(sha(base_raw)==BASE_SHA and sha(scope_raw)==SCOPE_SHA,'VERIFIER_ACCEPTED_BASE_UNCHANGED')
    return manifest_raw,entries,accepted

def load_exact(name, path, expected_sha):
    need(name not in sys.modules,'VERIFIER_MODULE_ALREADY_LOADED')
    # Execute the bytes we rehash, never a timestamp/hash-validated __pycache__ substitute.
    raw=ordinary_file(path,1048576)
    need(sha(raw)==expected_sha,'VERIFIER_COMPILED_SOURCE_HASH')
    module=types.ModuleType(name)
    module.__file__=str(path)
    sys.modules[name]=module
    exec(compile(raw,str(path),'exec',dont_inherit=True),module.__dict__)
    need(Path(module.__file__).resolve()==path,'VERIFIER_MODULE_ORIGIN')
    return module

def audit(event,args):
    if event.startswith(('ctypes.','socket.','subprocess.','os.spawn','winreg.')) or event=='os.system':
        raise Rejected('VERIFIER_NATIVE_OR_NETWORK_BOUNDARY')
    if event in ('os.remove','os.rmdir','os.rename','os.mkdir','os.chmod','os.chown','os.link','os.symlink','os.truncate'):
        raise Rejected('VERIFIER_READ_ONLY_BOUNDARY')
    if event=='open':
        path,mode,flags=args
        write=(isinstance(mode,str) and any(c in mode for c in 'wax+')) or (isinstance(flags,int) and flags&(os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND))
        if write:
            raise Rejected('VERIFIER_READ_ONLY_BOUNDARY')

def run(argv):
    need(len(argv)==4,'VERIFIER_EXACT_ARGUMENTS')
    _,packet_arg,head,run_id=argv
    need(type(head) is str and re.fullmatch('[0-9a-f]{40}',head) is not None,'VERIFIER_EXACT_HEAD')
    need(type(run_id) is str and re.fullmatch('[1-9][0-9]{0,19}',run_id) is not None,'VERIFIER_RUN_ID')
    need(sys.flags.isolated==1 and sys.flags.no_site==1 and sys.dont_write_bytecode,'VERIFIER_ISOLATED_PROCESS_REQUIRED')
    source=Path(__file__).resolve().parent
    manifest_raw,entries,accepted=read_sources(source)
    sys.addaudithook(audit)
    base=load_exact('personal_model',accepted/'personal_model.py',BASE_SHA)
    protocol=load_exact('evidence_protocol',source/'evidence_protocol.py',entries['evidence_protocol.py']['sha256'])
    packet_path=Path(packet_arg)
    need(packet_path.name=='PRIVATE_PACKET.json','VERIFIER_FIXED_PACKET_NAME')
    packet_raw=ordinary_file(packet_path,524288)
    packet=strict_json(packet_raw)
    need(type(packet) is dict and packet_raw==canonical(packet),'VERIFIER_PACKET_CANONICAL')
    report=protocol.evaluate_private(packet_raw,head,run_id,'1')
    protocol.check_public(report)
    need(type(packet.get('records')) is list and 0<len(packet['records'])<=12,'VERIFIER_RECORD_BOUND')
    checked=[]
    for index,record in enumerate(packet['records'],1):
        record_path=packet_path.parent/f'record_{index:02d}.json'
        record_raw=ordinary_file(record_path,65536)
        need(record_raw==canonical(record),'VERIFIER_RECORD_FILE_PACKET_MISMATCH')
        raw=record['raw_base64']
        if raw is None:
            need(record['raw_sha256'] is None,'VERIFIER_NULL_RAW_DIGEST_CONFLICT')
            count=0
        else:
            need(type(raw) is str,'VERIFIER_RAW_TYPE')
            try:
                data=base64.b64decode(raw,validate=True)
            except ValueError:
                raise Rejected('VERIFIER_RAW_BASE64') from None
            need(0<len(data)<=16384 and base64.b64encode(data).decode('ascii')==raw,'VERIFIER_RAW_ENCODING_BOUND')
            need(sha(data)==record['raw_sha256'],'VERIFIER_RAW_DIGEST_MISMATCH')
            need(data==canonical(strict_json(data,16384)),'VERIFIER_RAW_CANONICAL')
            count=len(data)
        checked.append({'id':record['id'],'record_file_sha256':sha(record_raw),'raw_sha256':record['raw_sha256'],'raw_bytes':count,'status':record['status']})
    receipt={
        'version':'PF_PERSONAL_002_SEPARATE_PROCESS_RAW_RECEIPT_V1',
        'realm':REALM,'head':head,'run_id':run_id,'run_attempt':'1',
        'status':'PRIVATE_PACKET_REHASH_AND_REVIEWED_SEMANTICS_PASS',
        'native_outcome':report['native_outcome'],
        'packet_sha256':sha(packet_raw),'public_report_sha256':sha(canonical(report)),
        'source_manifest_sha256':sha(manifest_raw),
        'verifier_sha256':entries[Path(__file__).name]['sha256'],
        'protocol_sha256':entries['evidence_protocol.py']['sha256'],
        'accepted_model_sha256':BASE_SHA,'accepted_scope_sha256':SCOPE_SHA,
        'records':checked,
        'separate_process':True,'independent_semantic_implementation':False,
        'source_authentication_or_host_attestation':False,
        'private_raw_publicly_retained':False,
        'posthoc_private_raw_rehash':'UNAVAILABLE_AFTER_EPHEMERAL_RUNNER_TEARDOWN',
        'original_host_authorized':False,'owner_consent_issued':False,'NoAutoNext':True,
    }
    sys.stdout.buffer.write(canonical(receipt))
    return 0

if __name__=='__main__':
    try:
        raise SystemExit(run(sys.argv))
    except Exception as exc:
        code=str(exc) if re.fullmatch('[A-Z_]{1,120}',str(exc)) else type(exc).__name__
        sys.stderr.write('PRIVATE_VERIFICATION_FAILED:'+code+'\n')
        raise SystemExit(2)
