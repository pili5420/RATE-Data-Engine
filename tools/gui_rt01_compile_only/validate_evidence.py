"""Read-only artifact checks. Never compiles, links, loads or runs an object."""
import argparse
import hashlib
import json
import re
import struct
from pathlib import Path

BASE = '070faf7783e5b867b995ee3584a61fa71206e2f3'
SOURCE_PINS = {
    'windows_abi_compile_only.cpp': '4b642fdb1b5a165abf7e0fc6ad4f6f351875224048c4857e5d52b5f456bf5299',
    'windows_support_compile_only.cpp': 'e164e8ba6697568e318fb0103b0f46d1a5aea0c81527f9fa19d064381c950fd9',
}
FLAGS = ['/nologo', '/std:c++17', '/W4', '/WX', '/c', '/Bv', '/showIncludes']


class Rejected(ValueError):
    pass


def require(condition, reason):
    if not condition:
        raise Rejected(reason)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def validate_command(arguments, source, object_path):
    require(type(arguments) is list and arguments == FLAGS + ['/Fo' + object_path, source], 'EXACT_COMPILE_COMMAND')
    require(source.endswith(tuple(SOURCE_PINS)), 'ORIGINAL_SOURCE_NAME')
    require(object_path.endswith('.obj'), 'OBJECT_EXTENSION')


def coff(data, architecture):
    """Reject PE/images, code sections, unresolved imports and callable entries."""
    require(architecture in ('x86', 'x64'), 'ARCHITECTURE')
    require(type(data) is bytes and len(data) >= 20, 'COFF_HEADER')
    machine, count, timestamp, symptr, symcount, optional, characteristics = struct.unpack_from('<HHIIIHH', data)
    require(machine == {'x86': 0x014c, 'x64': 0x8664}[architecture], 'COFF_MACHINE')
    require(optional == 0 and not characteristics & (0x0002 | 0x2000), 'COFF_NOT_IMAGE')
    require(0 < count <= 64 and 20 + count * 40 <= len(data), 'COFF_SECTIONS')
    sections = []
    for offset in range(20, 20 + count * 40, 40):
        name = data[offset:offset + 8].rstrip(b'\0').decode('ascii', 'strict')
        rawsize, rawptr = struct.unpack_from('<II', data, offset + 16)
        flags, = struct.unpack_from('<I', data, offset + 36)
        require(rawsize == 0 or (rawptr >= 20 + count * 40 and rawptr + rawsize <= len(data)), 'COFF_SECTION_BOUNDS')
        require(not ((flags & (0x20 | 0x20000000) or name.startswith('.text')) and rawsize), 'COFF_EXECUTABLE_CODE')
        sections.append({'name': name, 'bytes': rawsize, 'flags': flags})
    symbols = []
    if symcount:
        require(symptr >= 20 + count * 40 and symcount <= 10000 and symptr + symcount * 18 + 4 <= len(data), 'COFF_SYMBOL_BOUNDS')
        stringptr = symptr + symcount * 18
        stringsize, = struct.unpack_from('<I', data, stringptr)
        require(stringsize >= 4 and stringptr + stringsize <= len(data), 'COFF_STRING_BOUNDS')
        i = 0
        while i < symcount:
            offset = symptr + i * 18
            namebytes, value, section, kind, storage, auxiliary = struct.unpack_from('<8sIhHBB', data, offset)
            if namebytes[:4] == b'\0' * 4:
                stringoffset, = struct.unpack_from('<I', namebytes, 4)
                require(4 <= stringoffset < stringsize, 'COFF_SYMBOL_STRING')
                end = data.find(b'\0', stringptr + stringoffset, stringptr + stringsize)
                require(end != -1, 'COFF_UNTERMINATED_SYMBOL')
                name = data[stringptr + stringoffset:end].decode('ascii', 'strict')
            else:
                name = namebytes.rstrip(b'\0').decode('ascii', 'strict')
            require(not (storage == 2 and section == 0), 'COFF_UNRESOLVED_EXTERNAL')
            require(not (kind & 0x20 and section > 0), 'COFF_DEFINED_FUNCTION')
            require(not re.search(r'(?:main|DllMain|WinMain|LoadLibrary|GetProcAddress|__imp_)', name, re.I), 'COFF_LIVE_SYMBOL')
            require(i + 1 + auxiliary <= symcount, 'COFF_AUXILIARY_BOUNDS')
            symbols.append({'name': name, 'section': section, 'kind': kind, 'storage': storage})
            i += 1 + auxiliary
    else:
        require(symptr == 0, 'COFF_EMPTY_SYMBOL_POINTER')
    return {'machine': machine, 'sections': sections, 'symbols': symbols, 'timestamp': timestamp, 'bytes': len(data)}


def validate_artifact(root, head, architecture, role):
    root = Path(root)
    require(re.fullmatch('[0-9a-f]{40}', head) is not None, 'EXACT_HEAD')
    require(architecture in ('x86', 'x64') and role in ('qualification', 'independent'), 'ROLE_ARCHITECTURE')
    def load(name):
        return json.loads((root / name).read_bytes())
    index = load('FILE_SHA256_INDEX.json')
    require(index['exact_head'] == head and index['index_excludes_itself'] is True, 'INDEX_HEAD')
    require(set(p.name for p in root.iterdir()) == set(index['files']) | {'FILE_SHA256_INDEX.json'}, 'MANIFEST_FILE_SET')
    for name, row in index['files'].items():
        require('/' not in name and '\\' not in name and name not in ('.', '..'), 'MANIFEST_PATH')
        data = (root / name).read_bytes()
        require(len(data) == row['bytes'] and sha(data) == row['sha256'], 'MEMBER_SHA256:' + name)
        require(name.endswith(('.json', '.log', '.obj')), 'UNEXPECTED_OUTPUT')
    require('FAILURE.json' not in index['files'], 'FAILURE_PRESERVED')
    attempt = load('ATTEMPT.json')
    require(attempt['expected_head'] == head and attempt['accepted_base'] == BASE and attempt['architecture'] == architecture and attempt['role'] == role, 'ATTEMPT_BINDING')
    runner = load('RUNNER_IDENTITY.json')
    require(runner['image_os'] == 'win22' and bool(runner['image_version']) and runner['runner_os'] == 'Windows' and runner['exact_head'] == head and runner['base_sha'] == BASE, 'RUNNER_IDENTITY')
    before, after = load('ACCEPTED_SOURCE_BEFORE.json'), load('ACCEPTED_SOURCE_AFTER.json')
    require(before == after and len(before) == 701, 'ACCEPTED_SOURCE_NONINTERFERENCE')
    env = load('CONTROLLED_COMPILER_ENVIRONMENT.json')
    require(not {'cl', '_cl_', 'link', '_link_'} & {k.lower() for k in env}, 'COMPILER_ENV_INJECTION')
    require(env['VSCMD_ARG_TGT_ARCH'] == architecture and env['VSCMD_ARG_HOST_ARCH'] == 'x64', 'TARGET_ENV')
    tool = load('TOOLCHAIN_IDENTITY.json')
    require(tool['signature_status'] == 'Valid' and 'Microsoft Corporation' in tool['signer_subject'], 'MICROSOFT_COMPILER_IDENTITY')
    require(tool['compiler_path'].replace('/', '\\').lower().endswith('\\bin\\hostx64\\' + architecture + '\\cl.exe') and re.fullmatch('[0-9a-f]{64}', tool['compiler_sha256']) is not None, 'COMPILER_PATH_HASH')
    require(tool['target_architecture'] == architecture and re.fullmatch(r'10\.0\.[0-9]+\.[0-9]+', tool['sdk_version']) is not None, 'SDK_TARGET')
    require(len(tool['headers']) == 6 and all(re.fullmatch('[0-9a-f]{64}', h['sha256']) and h['bytes'] > 0 for h in tool['headers'].values()), 'SDK_HEADER_IDENTITIES')
    require(tool['link_invoked'] is False and tool['target_execution'] is False and tool['native_gui_dispatch'] is False, 'TOOLCHAIN_BOUNDARY')
    cases = []
    for name, source_sha in SOURCE_PINS.items():
        stem = name[:-4]
        case, process = load(stem + '.RESULT.json'), load(stem + '.PROCESS.json')
        require(case['status'] == 'PASS_COMPILE_ONLY' and case['exact_head'] == head and case['architecture'] == architecture and case['role'] == role and case['source_sha256'] == source_sha, 'CASE_BINDING')
        require(case['compiler_exit_code'] == process['exit_code'] == 0 and not process['timed_out'] and process['start_or_io_error'] is None and process['child_pid'] > 0, 'COMPILER_PROCESS')
        require(case['command_executable'] == process['exe'] == tool['compiler_path'] and case['command_arguments'] == process['arguments'] and process['raw_arguments'] == '', 'COMMAND_EVIDENCE')
        validate_command(process['arguments'], case['source'], case['object']['path'])
        for stream in ('stdout', 'stderr'):
            require(sha((root / (stem + '.' + stream + '.log')).read_bytes()) == process[stream + '_sha256'], 'COMPILER_LOG_HASH')
        raw = (root / (stem + '.stdout.log')).read_bytes() + (root / (stem + '.stderr.log')).read_bytes()
        require(re.search(rb'19\.[0-9]+\.[0-9]+', raw) is not None, 'RAW_COMPILER_VERSION')
        obj = (root / (stem + '.obj')).read_bytes()
        require(sha(obj) == case['object']['sha256'] and len(obj) == case['object']['bytes'], 'OBJECT_HASH')
        shape = coff(obj, architecture)
        require(shape['machine'] == case['object']['coff_machine'] and case['object']['optional_header_size'] == 0, 'OBJECT_EVIDENCE')
        require(case['no_link'] is True and case['no_target_execution'] is True and case['no_native_GUI_dispatch'] is True, 'CASE_BOUNDARY')
        cases.append({'source': name, 'source_sha256': source_sha, 'object_sha256': sha(obj), 'coff': shape})
    summary = load('ARCHITECTURE_RESULT.json')
    require(summary['status'] == 'RT01_COMPILE_ONLY_SUBGATE_PASS' and summary['exact_head'] == head and summary['architecture'] == architecture and summary['role'] == role and len(summary['cases']) == 2 and summary['unchanged_accepted_source_files'] == 701, 'SUMMARY_BINDING')
    require(summary['rt01_full'] == summary['gate2'] == 'BLOCKED' and summary['runtime_gates'] == 'RT01-RT10_BLOCKED' and summary['original_halt_root_cause'] == 'UNKNOWN', 'NO_RUNTIME_PROMOTION')
    return {'status': 'VERIFIED_REAL_ARTIFACT_RECORDS_AND_OBJECTS', 'head': head, 'architecture': architecture, 'role': role, 'compiler': tool, 'runner': runner, 'cases': cases, 'rt01_full': 'BLOCKED', 'gate2': 'BLOCKED', 'limitation': 'Compiler/platform authenticity relies on separately fetched GitHub run/log/artifact provenance, not self-asserted JSON alone.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--artifact', required=True)
    parser.add_argument('--head', required=True)
    parser.add_argument('--architecture', choices=['x86', 'x64'], required=True)
    parser.add_argument('--role', choices=['qualification', 'independent'], required=True)
    args = parser.parse_args()
    print(json.dumps(validate_artifact(args.artifact, args.head, args.architecture, args.role), indent=2))
