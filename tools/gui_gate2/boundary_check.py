"""Closed source/import/package boundary for the offline library; no native transport."""
import ast,hashlib,json
from pathlib import Path
import zipfile

RUNTIME_FILES=('identity_binding.py','title_validation_pure_v2.py','TITLE_EVIDENCE_SCHEMA_V2.json','TITLE_VALIDATION_PROVENANCE.json','TARGET_IDENTITY_BINDING_SCHEMA_V1.json','TARGET_IDENTITY_BINDING_CONTRACT_V1.json','AUTHORIZED_READ_BOUNDARY_CONTRACT_V1.json','DELIVERY_BOUNDARY_V2.json','README.txt')
ENGINEERING_FILES=('.gitattributes','.gitignore','ACCEPTED_BASELINE_PINS.json','boundary_check.py','build_offline_bundle.py','run_synthetic.py','synthetic_fixtures.py','test_identity_binding.py','test_round2_corrective.py')
PURE_SHA='759d049b963287ac7897f0d086883d6aa42084db245566c39b5dcfe81e5f5c5a'
SCHEMA_SHA='4c55b48bc6eb5a9a9d4065a578be355764e5f2541d97089fdc0e35869bd29a02'
POLICY={'version':'RATE_GUI_OFFLINE_DELIVERY_BOUNDARY_V2','runtime_files':list(RUNTIME_FILES),'allowed_entry':'identity_binding offline synthetic library functions only','native_execution_authorized':False,'deployment_authorized':False,'external_legacy_archive_may_be_loaded':False,'native_permit_loader':False,'historical_tests':'Original81 source is unchanged engineering-only; original142 and native baseline are in external quarantine, never packaged. Full223 are rerun outside delivery with frozen pins.','no_auto_next':True}

def need(ok,reason):
    if not ok:raise ValueError(reason)

def physical(p):
    p=Path(p)
    need(p.is_absolute() and '..' not in p.parts and str(p)==str(p.resolve()),'ABSOLUTE_PHYSICAL_PATH')
    for q in [p,*p.parents]:
        if q.exists():need(not q.is_symlink() and not q.lstat().st_file_attributes&1024,'REPARSE_PATH')
    return p

def evidence_path(p):
    p=physical(p)
    try:relative=p.relative_to(Path(r'D:\Codex'))
    except ValueError:raise ValueError('EXTERNAL_ROUND2_EVIDENCE_ONLY')
    need(len(relative.parts)>=2 and relative.parts[0].startswith('RATE-PR72-Round2-'),'EXTERNAL_ROUND2_EVIDENCE_ONLY')
    return p

def audit_boundary(root,packaged=False):
    root=physical(root);need(root.is_dir(),'SOURCE_DIRECTORY_REQUIRED')
    expected=set(RUNTIME_FILES) if packaged else set(RUNTIME_FILES)|set(ENGINEERING_FILES)
    actual={p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()}
    need(actual==expected,'CLOSED_DELIVERY_FILE_SET')
    for p in root.rglob('*'):
        physical(p)
        if p.is_file():need(p.stat().st_nlink==1,'SOURCE_HARDLINK')
    snapshot={name:(root/name).read_bytes() for name in sorted(actual)}
    need(json.loads(snapshot['DELIVERY_BOUNDARY_V2.json'])==POLICY,'DELIVERY_POLICY_MISMATCH')
    need(hashlib.sha256(snapshot['title_validation_pure_v2.py']).hexdigest()==PURE_SHA,'PURE_VALIDATOR_PIN')
    need(hashlib.sha256(snapshot['TITLE_EVIDENCE_SCHEMA_V2.json']).hexdigest()==SCHEMA_SHA,'TITLE_SCHEMA_PIN')
    runtime_imports={'identity_binding.py':{'hashlib','importlib.util','json','pathlib','re'},'title_validation_pure_v2.py':{'datetime','hashlib','pathlib','re'}}
    records=[]
    for p in sorted(root.glob('*.py')):
        tree=ast.parse(snapshot[p.name]);imports=set()
        for n in ast.walk(tree):
            if isinstance(n,(ast.ClassDef,ast.FunctionDef)):need(n.name not in {'NativeBackend','validate_live_permit','collect'},'LEGACY_EXECUTABLE_DEFINITION')
            if isinstance(n,ast.Import):imports.update(x.name for x in n.names)
            if isinstance(n,ast.ImportFrom):imports.add(n.module)
            if p.name in runtime_imports:
                if isinstance(n,ast.Call):
                    call=ast.unparse(n.func)
                    need(call not in {'exec','eval','compile','__import__'} and not any(x in call for x in ['WinDLL','CDLL','windll','import_module','write_bytes','write_text','mkdir','unlink']),'RUNTIME_EXECUTION_OR_MUTATION_CAPABILITY')
                if isinstance(n,ast.If):need('__name__' not in ast.unparse(n.test),'RUNTIME_CLI_ENTRY')
        if p.name in runtime_imports:need(imports==runtime_imports[p.name],'RUNTIME_IMPORT_CLOSURE')
        records.append({'path':p.name,'imports':sorted(imports),'sha256':hashlib.sha256(snapshot[p.name]).hexdigest()})
    source=snapshot['identity_binding.py'].decode('utf-8')
    need("HERE/'title_validation_pure_v2.py'" in source and "HERE/'TITLE_EVIDENCE_SCHEMA_V2.json'" in source and 'accepted_baseline' not in source,'FIXED_PURE_IMPORT_ONLY')
    need("raise Denied('LIVE_IDENTITY_RESOLUTION_AND_DIAGNOSTIC_NOT_IMPLEMENTED_OR_AUTHORIZED')" in source,'LIVE_ENTRY_MUST_REJECT')
    return {'status':'PASS_OFFLINE_DELIVERY_BOUNDARY','files':sorted(actual),'file_pins':{name:hashlib.sha256(data).hexdigest() for name,data in snapshot.items()},'python':records,'native_enforcement_claimed':False,'no_legacy_files_or_loader':True}

def build_bundle(root,destination):
    audit=audit_boundary(root);destination=evidence_path(destination)
    need(destination.parent.is_dir() and not destination.exists() and destination.suffix=='.zip','EXCLUSIVE_NEW_BUNDLE_DESTINATION')
    admitted={name:(root/name).read_bytes() for name in RUNTIME_FILES}
    need(all(hashlib.sha256(data).hexdigest()==audit['file_pins'][name] for name,data in admitted.items()),'SOURCE_CHANGED_AFTER_AUDIT')
    with zipfile.ZipFile(destination,'x',zipfile.ZIP_DEFLATED) as z:
        for name,data in admitted.items():z.writestr(name,data)
    with zipfile.ZipFile(destination) as z:
        need(set(z.namelist())==set(RUNTIME_FILES) and z.testzip() is None,'BUNDLE_CONTENTS')
        need(all(hashlib.sha256(z.read(name)).hexdigest()==audit['file_pins'][name] for name in RUNTIME_FILES),'BUNDLE_ADMITTED_BYTES_MISMATCH')
    return {'path':str(destination),'sha256':hashlib.sha256(destination.read_bytes()).hexdigest(),'files':list(RUNTIME_FILES),'purpose':'OFFLINE_LIBRARY_ONLY_NOT_DEPLOYMENT_AUTHORIZATION'}
