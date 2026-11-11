"""Fictional data only; never queries OS state."""
import base64
import copy
import hashlib
import json
from evidence import ORDER, query_spec


def encode(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(',', ':')).encode()


def set_data(packet, qid, value):
    record = next(r for r in packet['records'] if r['id'] == qid)
    raw = encode(value)
    record['raw_utf8_b64'] = base64.b64encode(raw).decode()
    record['raw_sha256'] = hashlib.sha256(raw).hexdigest()


def get_data(packet, qid):
    return json.loads(base64.b64decode(next(r for r in packet['records'] if r['id'] == qid)['raw_utf8_b64']))


def packet():
    result = {'version': 'PAGEFILE_NON_GUI_V1', 'realm': 'SYNTHETIC_ONLY', 'target_path': 'D:\\pagefile.sys', 'started_utc': '2026-10-18T00:00:00.000000Z', 'ended_utc': '2026-10-18T00:00:12.000000Z', 'runner': {'run_id': '1', 'run_attempt': '1', 'head': 'a'*40, 'image_os': 'SYNTHETIC', 'image_version': 'SYNTHETIC'}, 'records': []}
    defaults = {
        'computer': [{'Name': 'FICTIONAL_HOST', 'AutomaticManagedPagefile': False}],
        'boot': [{'CSName': 'FICTIONAL_HOST', 'LastBootUpTime': '2026-10-17T00:00:00.000000Z', 'Version': 'FICTIONAL_VERSION', 'BuildNumber': 'FICTIONAL_BUILD'}],
        'product': [{'UUID': '12345678-1234-1234-1234-123456789abc'}],
        'volumes': [{'DeviceID': '\\\\?\\Volume{12345678-1234-1234-1234-123456789abc}\\', 'DriveLetter': 'D:', 'SerialNumber': 123}],
        'settings': [{'Name': 'D:\\pagefile.sys', 'InitialSize': 512, 'MaximumSize': 2048}],
        'usage': [{'Name': 'D:\\pagefile.sys', 'AllocatedBaseSize': 1024, 'CurrentUsage': 12, 'PeakUsage': 20, 'TempPageFile': False}],
        'registry': {'kind': 'MultiString', 'PagingFiles': ['D:\\pagefile.sys 512 2048']},
    }
    for i, qid in enumerate(ORDER):
        ns, klass, fields, provider = query_spec(qid)
        result['records'].append({'id': qid, 'namespace': ns, 'class': klass, 'fields': list(fields), 'provider': provider, 'started_utc': f'2026-10-18T00:00:{i:02}.000000Z', 'ended_utc': f'2026-10-18T00:00:{i:02}.100000Z', 'elapsed_ms': 100, 'status': 'OK', 'error': None, 'raw_utf8_b64': '', 'raw_sha256': ''})
        set_data(result, qid, copy.deepcopy(defaults[qid.removesuffix('_before').removesuffix('_after')]))
    return result
