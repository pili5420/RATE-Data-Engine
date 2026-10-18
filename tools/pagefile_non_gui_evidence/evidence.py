"""Offline observation semantics only. No host query, trust root or Permit loader."""
import base64
import binascii
import datetime as dt
import hashlib
import json
import re

NS = 'ROOT/CIMV2'
REGKEY = r'SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management'
CLASSES = {
    'computer': ('Win32_ComputerSystem', ('Name', 'AutomaticManagedPagefile'), 'CIMWin32'),
    'boot': ('Win32_OperatingSystem', ('CSName', 'LastBootUpTime', 'Version', 'BuildNumber'), 'CIMWin32'),
    'product': ('Win32_ComputerSystemProduct', ('UUID',), 'CIMWin32'),
    'volumes': ('Win32_Volume', ('DeviceID', 'DriveLetter', 'SerialNumber'), 'MSVDS__PROVIDER'),
    'settings': ('Win32_PageFileSetting', ('Name', 'InitialSize', 'MaximumSize'), 'CIMWin32'),
    'usage': ('Win32_PageFileUsage', ('Name', 'AllocatedBaseSize', 'CurrentUsage', 'PeakUsage', 'TempPageFile'), 'CIMWin32'),
}
ORDER = ('computer_before', 'boot_before', 'product_before', 'volumes_before',
         'settings', 'usage', 'registry', 'computer_after', 'boot_after', 'product_after', 'volumes_after')
REALMS = ('SYNTHETIC_ONLY', 'RUNNER_ONLY_NOT_TARGET_HOST_EVIDENCE')
STATES = ('CONFIG_INTENT_OBSERVED', 'RUNTIME_PAGEFILE_OBSERVED', 'SYSTEM_MANAGED_POLICY_OBSERVED',
          'CONFIG_RUNTIME_CONFLICT', 'REBOOT_APPLICABILITY_UNPROVEN', 'INDETERMINATE', 'BLOCKED')


class Refused(ValueError):
    pass


def need(ok, why):
    if not ok:
        raise Refused(why)


def shape(value, fields, why):
    need(type(value) is dict and set(value) == set(fields), why)


def integer(value, low, high, why):
    need(type(value) is int and low <= value <= high, why)


def text(value, why):
    need(type(value) is str and 0 < len(value) <= 512 and not any(ord(c) < 32 or 0xd800 <= ord(c) <= 0xdfff for c in value), why)


def strict_json(raw):
    need(type(raw) is bytes and 0 < len(raw) <= 1048576, 'RAW_BYTE_BOUND')
    def pairs(items):
        result = {}
        for key, value in items:
            need(key not in result, 'DUPLICATE_KEY')
            result[key] = value
        return result
    def constant(_):
        raise Refused('NONFINITE_NUMBER')
    try:
        result = json.loads(raw.decode('utf-8', errors='strict'), object_pairs_hook=pairs, parse_constant=constant)
    except (UnicodeError, ValueError, RecursionError) as error:
        raise Refused('MALFORMED_JSON:' + type(error).__name__) from None
    def walk(v, depth=0):
        need(depth <= 12, 'DEPTH_BOUND')
        if type(v) is dict:
            need(len(v) <= 32, 'OBJECT_BOUND')
            for k, child in v.items():
                text(k, 'KEY_ENCODING'); walk(child, depth + 1)
        elif type(v) is list:
            need(len(v) <= 64, 'ARRAY_BOUND')
            for child in v:
                walk(child, depth + 1)
        elif type(v) is str:
            need(len(v) <= 131072 and not any(0xd800 <= ord(c) <= 0xdfff for c in v), 'STRING_ENCODING')
        else:
            need(type(v) in (int, bool) or v is None, 'STRICT_JSON_TYPE')
            if type(v) is int:
                integer(v, -(2**63), 2**63-1, 'JSON_INTEGER_BOUND')
    walk(result)
    return result


def stamp(value):
    need(type(value) is str and re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}Z', value) is not None, 'UTC_ENCODING')
    try:
        return dt.datetime.strptime(value, '%Y-%m-%dT%H:%M:%S.%fZ').replace(tzinfo=dt.timezone.utc)
    except ValueError:
        raise Refused('INVALID_UTC') from None


def query_spec(qid):
    if qid == 'registry':
        return 'REGISTRY64', REGKEY, ('PagingFiles',), 'Microsoft.Win32.RegistryKey'
    key = qid.removesuffix('_before').removesuffix('_after')
    need(key in CLASSES, 'SOURCE_NOT_ALLOWED')
    klass, fields, provider = CLASSES[key]
    return NS, klass, fields, provider


def page_path(value):
    need(type(value) is str and re.fullmatch(r'[A-Za-z]:\\pagefile\.sys', value, re.I) is not None, 'UNSUPPORTED_PAGEFILE_PATH')
    return value.casefold()


def decode_record(record, qid, prior, outer_end):
    shape(record, {'id', 'namespace', 'class', 'fields', 'provider', 'started_utc', 'ended_utc', 'elapsed_ms', 'status', 'error', 'raw_utf8_b64', 'raw_sha256'}, 'QUERY_RECORD_SCHEMA')
    namespace, klass, fields, provider = query_spec(qid)
    need(record['id'] == qid and record['namespace'] == namespace and record['class'] == klass and record['fields'] == list(fields) and record['provider'] == provider, 'QUERY_SCOPE_OR_PROVIDER')
    begin, end = stamp(record['started_utc']), stamp(record['ended_utc'])
    need(prior <= begin <= end <= outer_end, 'QUERY_CLOCK_OR_ORDER')
    need((end-begin).total_seconds() <= 10, 'QUERY_WALL_CLOCK_BOUND')
    integer(record['elapsed_ms'], 0, 10000, 'QUERY_TIMEOUT')
    need(record['status'] == 'OK' and record['error'] is None, 'SOURCE_ERROR_PARTIAL_OR_UNAVAILABLE')
    need(type(record['raw_utf8_b64']) is str and len(record['raw_utf8_b64']) <= 131072, 'RAW_BASE64_BOUND')
    try:
        raw = base64.b64decode(record['raw_utf8_b64'], validate=True)
    except (ValueError, binascii.Error):
        raise Refused('RAW_BASE64') from None
    need(base64.b64encode(raw).decode('ascii') == record['raw_utf8_b64'], 'CANONICAL_BASE64')
    need(type(record['raw_sha256']) is str and hashlib.sha256(raw).hexdigest() == record['raw_sha256'], 'RAW_DIGEST')
    data = strict_json(raw)
    if qid == 'registry':
        shape(data, {'kind', 'PagingFiles'}, 'REGISTRY_SCHEMA')
        need(data['kind'] == 'MultiString' and type(data['PagingFiles']) is list and len(data['PagingFiles']) <= 32, 'REGISTRY_KIND_OR_BOUND')
        for entry in data['PagingFiles']:
            text(entry, 'REGISTRY_ENTRY_ENCODING')
    else:
        need(type(data) is list and len(data) <= 64, 'CIM_RESULT_ARRAY')
        for row in data:
            shape(row, fields, 'CIM_FIELD_SCHEMA')
    return data, end


def analyze(raw):
    packet = strict_json(raw)
    shape(packet, {'version', 'realm', 'target_path', 'started_utc', 'ended_utc', 'runner', 'records'}, 'PACKET_SCHEMA')
    need(packet['version'] == 'PAGEFILE_NON_GUI_V1' and packet['realm'] in REALMS and packet['target_path'] == 'D:\\pagefile.sys', 'NO_TARGET_ACTIVATION_OR_SCOPE_CHANGE')
    shape(packet['runner'], {'run_id', 'run_attempt', 'head', 'image_os', 'image_version'}, 'RUNNER_CONTEXT_SCHEMA')
    for v in packet['runner'].values():
        text(v, 'RUNNER_CONTEXT')
    need(re.fullmatch('[0-9a-f]{40}', packet['runner']['head']) is not None, 'HEAD_FORMAT')
    begin, end = stamp(packet['started_utc']), stamp(packet['ended_utc'])
    need(begin <= end and (end-begin).total_seconds() <= 120, 'COLLECTION_DEADLINE')
    need(type(packet['records']) is list and len(packet['records']) == len(ORDER), 'INCOMPLETE_QUERY_SET')
    data = {}; cursor = begin
    for qid, record in zip(ORDER, packet['records']):
        data[qid], cursor = decode_record(record, qid, cursor, end)
    for key in ('computer', 'boot', 'product'):
        need(len(data[key+'_before']) == len(data[key+'_after']) == 1, 'SINGLETON_REQUIRED:' + key)
        need(data[key+'_before'] == data[key+'_after'], 'IDENTITY_OR_POLICY_CHANGED:' + key)
    computer, boot, product = (data[k+'_before'][0] for k in ('computer', 'boot', 'product'))
    text(computer['Name'], 'HOST_NAME')
    need(type(computer['AutomaticManagedPagefile']) is bool, 'GLOBAL_POLICY_STRICT_BOOL')
    need(boot['CSName'] == computer['Name'], 'HOST_MISMATCH')
    boot_time = stamp(boot['LastBootUpTime']); need(boot_time <= begin, 'BOOT_TIME_OR_CLOCK_MISMATCH')
    text(boot['Version'], 'OS_VERSION'); text(boot['BuildNumber'], 'OS_BUILD')
    need(type(product['UUID']) is str and re.fullmatch(r'[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}', product['UUID']) is not None and set(product['UUID'].replace('-', '').lower()) not in ({'0'}, {'f'}), 'UNKNOWN_HOST_UUID')
    def volumes(rows):
        found = {}; devices = set()
        for row in rows:
            need(type(row['DeviceID']) is str and re.fullmatch(r'\\\\\?\\Volume\{[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\}\\', row['DeviceID']) is not None, 'VOLUME_DEVICE_ID')
            need(row['DeviceID'].casefold() not in devices, 'DUPLICATE_VOLUME_ID'); devices.add(row['DeviceID'].casefold())
            integer(row['SerialNumber'], 0, 2**32-1, 'VOLUME_SERIAL_TYPE')
            letter = row['DriveLetter']
            if letter is not None:
                need(type(letter) is str and re.fullmatch('[A-Za-z]:', letter) is not None, 'DRIVE_LETTER')
                need(letter.casefold() not in found, 'DUPLICATE_DRIVE_LETTER'); found[letter.casefold()] = row
        return found
    before, after = volumes(data['volumes_before']), volumes(data['volumes_after'])
    need(before == after, 'VOLUME_MAPPING_CHANGED')
    need('d:' in before, 'D_VOLUME_NOT_OBSERVED')
    configs = {}; usages = {}; registry = {}
    for row in data['settings']:
        path = page_path(row['Name']); need(path not in configs, 'DUPLICATE_SETTINGS'); configs[path] = row
        for key in ('InitialSize', 'MaximumSize'):
            integer(row[key], 0, 2**32-1, 'CONFIG_SIZE_TYPE')
        need((row['InitialSize'] == row['MaximumSize'] == 0) or 0 < row['InitialSize'] <= row['MaximumSize'], 'UNKNOWN_SIZE_COMBINATION')
    for row in data['usage']:
        path = page_path(row['Name']); need(path not in usages, 'DUPLICATE_USAGE'); usages[path] = row
        for key in ('AllocatedBaseSize', 'CurrentUsage', 'PeakUsage'):
            integer(row[key], 0, 2**32-1, 'RUNTIME_SIZE_TYPE')
        need(type(row['TempPageFile']) is bool and row['TempPageFile'] is False, 'TEMPORARY_OR_UNKNOWN_PAGEFILE')
        need(row['AllocatedBaseSize'] > 0 and row['CurrentUsage'] <= row['AllocatedBaseSize'] and row['CurrentUsage'] <= row['PeakUsage'], 'RUNTIME_SIZE_CONTRADICTION')
    for entry in data['registry']['PagingFiles']:
        match = re.fullmatch(r'([A-Za-z]:\\pagefile\.sys) (0|[1-9][0-9]{0,9}) (0|[1-9][0-9]{0,9})', entry, re.I)
        need(match is not None, 'REGISTRY_GRAMMAR_SOURCE_GAP')
        path = page_path(match[1]); need(path not in registry, 'DUPLICATE_REGISTRY'); registry[path] = (int(match[2]), int(match[3]))
        need(all(v <= 2**32-1 for v in registry[path]), 'REGISTRY_SIZE_BOUND')
    # Literal custom-token matching is a narrow corroboration profile, not a
    # normative Registry grammar or a 0/0 system-managed inference rule.
    target = 'd:\\pagefile.sys'; config, usage = configs.get(target), usages.get(target)
    identity = {'host_name': computer['Name'], 'host_uuid_observed': product['UUID'], 'last_boot_utc_observed': boot['LastBootUpTime'], 'volume_observed': before['d:'], 'target_path': packet['target_path'], 'trusted_host_boot_volume_attestation': False}
    common = {'realm': packet['realm'], 'identity': identity, 'query_interval': [packet['started_utc'], packet['ended_utc']], 'clock': 'LOCAL_OS_CLOCK_UNTRUSTED', 'atomic_snapshot': False, 'raw_packet_sha256': hashlib.sha256(raw).hexdigest(), 'provider_records': [{'id': r['id'], 'provider': r['provider'], 'namespace': r['namespace'], 'class': r['class'], 'fields': r['fields'], 'started_utc': r['started_utc'], 'ended_utc': r['ended_utc'], 'raw_sha256': r['raw_sha256']} for r in packet['records']], 'target_host_qualified': False, 'GUI_Gate2': 'BLOCKED', 'RT04': 'BLOCKED', 'original_halt_root_cause': 'UNKNOWN', 'execution_authorized': False, 'no_auto_next': True}
    observations = {'global_policy': {'status': 'SYSTEM_MANAGED_POLICY_OBSERVED' if computer['AutomaticManagedPagefile'] else 'CONFIG_INTENT_OBSERVED', 'scope': 'SYSTEM_WIDE_ONLY', 'automatic': computer['AutomaticManagedPagefile'], 'D_system_managed_inferred': False}, 'D_config': {'status': 'CONFIG_INTENT_OBSERVED' if config else 'INDETERMINATE', 'scope': 'D_CONFIG_INTENT_ONLY', 'values': config}, 'D_runtime': {'status': 'RUNTIME_PAGEFILE_OBSERVED' if usage else 'INDETERMINATE', 'scope': 'D_RUNTIME_PROVIDER_OBSERVATION_ONLY', 'values': usage}, 'D_system_managed': {'status': 'BLOCKED', 'reason': 'SOURCE_GAP_NO_DOCUMENTED_PER_DRIVE_POLICY_CERTIFICATE'}, 'boot_applied': {'status': 'REBOOT_APPLICABILITY_UNPROVEN', 'reason': 'NO_TRUSTED_CONFIG_HISTORY_OR_BOOT_APPLIED_CERTIFICATE'}}
    reason = ['SOURCE_GAP_D_POLICY', 'SOURCE_GAP_BOOT_APPLICABILITY', 'HOST_BOOT_VOLUME_NOT_INDEPENDENTLY_ATTESTED', 'NO_TARGET_HOST_AUTHORIZATION']
    result = 'BLOCKED'
    if config is None:
        result = 'INDETERMINATE'; reason.append('MISSING_D_SETTINGS_NOT_PROOF_OF_AUTOMATIC_POLICY')
    elif target not in registry:
        result = 'INDETERMINATE'; reason.append('MISSING_REGISTRY_CORROBORATION')
    elif registry[target] != (config['InitialSize'], config['MaximumSize']):
        result = 'CONFIG_RUNTIME_CONFLICT'; reason.append('REGISTRY_CIM_CONFIG_CONFLICT')
    elif usage is None:
        result = 'CONFIG_RUNTIME_CONFLICT'; reason.append('CONFIG_PRESENT_RUNTIME_ABSENT_PENDING_REBOOT_NOT_PROVEN')
    elif config['InitialSize'] > 0 and not config['InitialSize'] <= usage['AllocatedBaseSize'] <= config['MaximumSize']:
        result = 'CONFIG_RUNTIME_CONFLICT'; reason.append('CONFIG_RUNTIME_SIZE_MISMATCH_PENDING_REBOOT_NOT_PROVEN')
    return dict(common, status=result, observations=observations, missing_evidence=reason, reason='Limited observation is separate from D policy / boot-applied qualification; hashes and matching sequential reads do not supply authenticity, ABA exclusion or boot history.')


def assess(raw):
    try:
        return analyze(raw)
    except Refused as error:
        return {'status': 'INDETERMINATE', 'reason': str(error), 'observations': {}, 'missing_evidence': [str(error)], 'target_host_qualified': False, 'GUI_Gate2': 'BLOCKED', 'RT04': 'BLOCKED', 'original_halt_root_cause': 'UNKNOWN', 'execution_authorized': False, 'no_auto_next': True}
