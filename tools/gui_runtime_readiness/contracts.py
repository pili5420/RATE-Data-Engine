"""Closed test realm and source identity. These are not execution capabilities."""
import hashlib
from pathlib import Path
from gui_native_preflight.protocol import canonical, digest

BASE_HEAD = '6e4cbdaa660efe645adf276b607cef52916dc92f'
BASE_TOOL_SHA256 = 'b773645bc1a46b957eb24679dc8f362951b2683e876b222def1803fca51a29b3'
REALM = 'RATE_RQR_SYNTHETIC_ONLY_NOT_LIVE_AUTHORITY'
ROLES = ('ISSUER', 'HOST', 'BOOT', 'OPERATOR', 'PARENT', 'CLOCK',
         'REVOCATION', 'WITNESS', 'EXTERNAL', 'REVIEW', 'DIAGNOSTIC')
PURPOSES = {role: 'RQR_SYNTHETIC_' + role + '_NOT_EXECUTABLE' for role in ROLES}
RUNTIME_FILES = ('__init__.py', 'contracts.py', 'bindings.py', 'wire.py',
                 'authority.py', 'containment.py', 'filesystem.py', 'witness.py')
SCHEMA_FILE = 'READINESS_SCHEMA_V1.json'
HERE = Path(__file__).resolve().parent

def source_identity():
    return digest({name: hashlib.sha256((HERE / name).read_bytes()).hexdigest()
                   for name in RUNTIME_FILES})

def schema_identity():
    return hashlib.sha256((HERE / SCHEMA_FILE).read_bytes()).hexdigest()

def blocked_runtime():
    return {'gate2_final': 'BLOCKED', 'runtime_qualification': 'BLOCKED',
            'native_execution_authorized': False, 'diagnostic_authorized': False,
            'no_retry': True, 'no_resume': True, 'no_fallback': True,
            'no_auto_next': True, 'atomic_snapshot': False,
            'original_halt_root_cause': 'UNKNOWN'}
