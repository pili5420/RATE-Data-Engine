"""Bounded synthetic counterexample verifier; no Windows provider or live entry.

The externally pinned finite oracle is an ASSUMPTION of this model. No native
source attestation, event emission completeness or real-time clock is obtained.
"""
import hashlib
import json
import re
from dataclasses import dataclass

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

REALM = 'RT04_FINITE_SYNTHETIC_ONLY_V1'
ROLES = ('oracle', 'observer_a', 'observer_b', 'certifier', 'reviewer')
SCOPE_KEYS = {'target_kind', 'host', 'boot', 'session', 'desktop', 'station',
              'pid', 'process_creation_filetime', 'process_creation_tick',
              'executable_path', 'executable_sha256', 'volume_serial', 'file_id',
              'hwnd', 'tid', 'generation', 'class_name'}
COMMON = {'realm', 'model_id', 'scope', 'interval', 'epoch', 'domain'}
DOMAIN = b'RATE_RT04_SYNTHETIC_NOT_NATIVE\0'


class Refused(ValueError):
    pass


def need(condition, reason):
    if not condition:
        raise Refused(reason)


def canonical(value):
    def walk(v, depth):
        need(depth <= 12, 'METADATA_DEPTH')
        if type(v) is dict:
            need(len(v) <= 32 and all(type(k) is str for k in v), 'METADATA_KEYS')
            for k, child in v.items():
                need(0 < len(k) <= 128, 'METADATA_KEY_SIZE')
                walk(child, depth + 1)
        elif type(v) is list:
            need(len(v) <= 64, 'METADATA_LIST_BOUND')
            for child in v:
                walk(child, depth + 1)
        elif type(v) is str:
            need(len(v) <= 2048 and not any(0xd800 <= ord(c) <= 0xdfff for c in v), 'METADATA_STRING')
        else:
            need(type(v) in (int, bool) or v is None, 'METADATA_TYPE')
            if type(v) is int:
                need(-(2**63) < v < 2**63, 'METADATA_INTEGER_BOUND')
    walk(value, 0)
    result = json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(',', ':')).encode('utf-8')
    need(len(result) <= 262144, 'METADATA_BYTE_BOUND')
    return result


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def exact(value, keys, reason):
    need(type(value) is dict and set(value) == set(keys), reason)


def integer(value, low, high, reason):
    need(type(value) is int and low <= value <= high, reason)


def hex64(value, reason):
    need(type(value) is str and re.fullmatch('[0-9a-f]{64}', value) is not None, reason)


@dataclass(frozen=True)
class Anchors:
    roots: tuple
    model_id: str
    scope_bytes: bytes
    interval: tuple
    epoch: str
    oracle_sha256: str
    prefix: str
    final_head: str
    event_count: int
    verification_tick: int
    deadline_tick: int


def validate_anchors(a):
    need(type(a) is Anchors, 'ANCHORS_TYPE')
    need(type(a.roots) is tuple and len(a.roots) == 5, 'ROOTS_TYPE')
    need(all(type(r) is tuple and len(r) == 2 and r[0] in ROLES and type(r[1]) is bytes and len(r[1]) == 32 for r in a.roots), 'ROOT_SCHEMA')
    roots = dict(a.roots)
    need(set(roots) == set(ROLES) and len({v for v in roots.values()}) == 5, 'INDEPENDENT_ROOT_ROLES')
    need(type(a.model_id) is str and 0 < len(a.model_id) <= 128 and type(a.epoch) is str and 0 < len(a.epoch) <= 128, 'MODEL_EPOCH')
    need(type(a.scope_bytes) is bytes, 'SCOPE_BYTES')
    try:
        scope = json.loads(a.scope_bytes)
    except (ValueError, UnicodeError):
        raise Refused('SCOPE_JSON') from None
    need(canonical(scope) == a.scope_bytes, 'CANONICAL_SCOPE')
    exact(scope, SCOPE_KEYS, 'SCOPE_SCHEMA')
    need(scope['target_kind'] == 'SYNTHETIC_COOPERATING_OWNER', 'NO_ORIGINAL_TARGET_TRANSFER')
    for name in SCOPE_KEYS - {'session', 'pid', 'process_creation_filetime', 'process_creation_tick', 'volume_serial', 'hwnd', 'tid'}:
        need(type(scope[name]) is str and 0 < len(scope[name]) <= 256, 'SCOPE_STRING:' + name)
    for name in ('session', 'pid', 'process_creation_filetime', 'process_creation_tick', 'volume_serial', 'hwnd', 'tid'):
        integer(scope[name], 0, 2**63-1, 'SCOPE_INTEGER:' + name)
    need(all(scope[n] > 0 for n in ('pid', 'hwnd', 'tid')), 'IDENTITY_POSITIVE')
    hex64(scope['executable_sha256'], 'EXECUTABLE_SHA256')
    need(re.fullmatch('[0-9a-f]{32}', scope['file_id']) is not None, 'FILE_ID_ENCODING')
    need(type(a.interval) is tuple and len(a.interval) == 2, 'INTERVAL_SCHEMA')
    for n in a.interval:
        integer(n, 0, 1000000, 'INTERVAL_TYPE')
    need(a.interval[0] < a.interval[1], 'INTERVAL_ORDER')
    integer(a.verification_tick, 0, 1000000, 'VERIFICATION_TICK')
    integer(a.deadline_tick, 0, 1000000, 'DEADLINE_TICK')
    need(a.interval[1] <= a.verification_tick <= a.deadline_tick, 'DEADLINE_OR_INCOMPLETE_HORIZON')
    for n in (a.oracle_sha256, a.prefix, a.final_head):
        hex64(n, 'ANCHOR_SHA256')
    integer(a.event_count, 2, 64, 'EXTERNAL_EVENT_COUNT')
    return roots, scope


def signed_message(role, payload):
    need(role in ROLES, 'ROLE')
    return DOMAIN + role.encode('ascii') + b'\0' + canonical(payload)


def envelope(value, role, roots):
    exact(value, {'role', 'payload', 'signature'}, 'ENVELOPE_SCHEMA')
    need(value['role'] == role, 'ROLE_BINDING')
    signature = value['signature']
    need(type(signature) is str and re.fullmatch('[0-9a-f]{128}', signature) is not None, 'SIGNATURE_ENCODING')
    try:
        Ed25519PublicKey.from_public_bytes(roots[role]).verify(bytes.fromhex(signature), signed_message(role, value['payload']))
    except InvalidSignature:
        raise Refused('SIGNATURE_INVALID') from None
    return value['payload']


def common(payload, a, scope):
    need(payload['realm'] == REALM, 'NO_NATIVE_REALM')
    need(payload['model_id'] == a.model_id and payload['epoch'] == a.epoch, 'MODEL_OR_EPOCH_MISMATCH')
    need(payload['domain'] == 'ONE_DECLARED_SYNTHETIC_WINDOW', 'DOMAIN_SCOPE')
    need(canonical(payload['scope']) == canonical(scope), 'EXACT_SCOPE_BINDING')
    need(type(payload['interval']) is list and canonical(payload['interval']) == canonical(list(a.interval)), 'INTERVAL_BINDING')


def validate_trace(events, a, scope):
    need(type(events) is list and len(events) == a.event_count, 'COMPLETE_FINITE_EVENT_COUNT')
    previous = a.prefix
    previous_tick = a.interval[0] - 1
    for index, event in enumerate(events):
        exact(event, {'seq', 'tick', 'kind', 'scope', 'epoch', 'previous', 'head'}, 'EVENT_SCHEMA')
        integer(event['seq'], 1, 64, 'EVENT_SEQUENCE_TYPE')
        need(event['seq'] == index + 1, 'SEQUENCE_GAP_DUPLICATE_OR_REORDER')
        integer(event['tick'], a.interval[0], a.interval[1], 'EVENT_TICK_TYPE_OR_RANGE')
        need(event['tick'] > previous_tick, 'EVENT_COMPLETION_ORDER')
        need(event['epoch'] == a.epoch, 'LISTENER_RESTART')
        need(canonical(event['scope']) == canonical(scope), 'GENERATION_OR_PROCESS_SCOPE_MISMATCH')
        need(event['previous'] == previous, 'EVENT_CHAIN_PREFIX')
        body = {k: v for k, v in event.items() if k != 'head'}
        need(event['head'] == digest(body), 'EVENT_CHAIN_TAMPER')
        need(event['kind'] == ('CREATE' if index == 0 else 'UNCHANGED'), 'DUPLICATE_CREATE_DESTROY_OR_UNKNOWN')
        previous = event['head']
        previous_tick = event['tick']
    need(previous == a.final_head, 'INDEPENDENT_FINAL_HEAD')
    need(events[-1]['tick'] == a.interval[1], 'TERMINAL_INTERVAL_SAMPLE')
    need(scope['process_creation_tick'] < events[0]['tick'], 'PROCESS_CREATION_ORDER')


def verify_model(packet, a):
    """Checks only the pinned finite trace assumption; never a native certificate."""
    roots, scope = validate_anchors(a)
    canonical(packet)
    exact(packet, {'oracle', 'observer_a', 'observer_b', 'certificate', 'review_ack'}, 'PACKET_SCHEMA')
    need(digest(packet['oracle']) == a.oracle_sha256, 'EXTERNAL_ORACLE_PIN')
    oracle = envelope(packet['oracle'], 'oracle', roots)
    exact(oracle, COMMON | {'source_kind', 'events', 'prefix', 'final_head', 'count'}, 'ORACLE_SCHEMA')
    common(oracle, a, scope)
    need(oracle['source_kind'] == 'INDEPENDENT_FINITE_OWNER_ORACLE', 'UNQUALIFIED_SOURCE_KIND')
    integer(oracle['count'], 2, 64, 'ORACLE_COUNT_TYPE')
    need(oracle['count'] == a.event_count and oracle['prefix'] == a.prefix and oracle['final_head'] == a.final_head, 'ORACLE_EXTERNAL_HEADS')
    validate_trace(oracle['events'], a, scope)
    for role in ('observer_a', 'observer_b'):
        data = envelope(packet[role], role, roots)
        exact(data, COMMON | {'source_kind', 'events', 'ready_tick', 'horizon_tick', 'loss', 'restart_count', 'reentrancy_unresolved', 'timeout', 'crash'}, 'OBSERVER_SCHEMA')
        common(data, a, scope)
        need(data['source_kind'] == 'FINITE_MODEL_OBSERVER', 'UNQUALIFIED_SOURCE_KIND')
        integer(data['ready_tick'], 0, 1000000, 'READINESS_TYPE')
        integer(data['horizon_tick'], 0, 1000000, 'HORIZON_TYPE')
        need(data['ready_tick'] < a.interval[0] and data['ready_tick'] < oracle['events'][0]['tick'] and a.interval[1] <= data['horizon_tick'] <= a.verification_tick, 'SUBSCRIPTION_OR_INTERVAL_INCOMPLETE')
        exact(data['loss'], {'events', 'buffers', 'unknown'}, 'LOSS_SCHEMA')
        for name in ('events', 'buffers'):
            integer(data['loss'][name], 0, 1000000, 'LOSS_TYPE')
            need(data['loss'][name] == 0, 'KNOWN_EVENT_OR_BUFFER_LOSS')
        need(data['loss']['unknown'] is False, 'UNKNOWN_LOSS')
        integer(data['restart_count'], 0, 1000000, 'RESTART_COUNT_TYPE')
        need(data['restart_count'] == 0 and data['reentrancy_unresolved'] is False, 'RESTART_OR_REENTRANCY')
        need(data['timeout'] is False and data['crash'] is False, 'TIMEOUT_CRASH_OR_UNKNOWN')
        need(canonical(data['events']) == canonical(oracle['events']), 'SIGNED_STREAM_OR_ORACLE_DISAGREEMENT')
    certificate = envelope(packet['certificate'], 'certifier', roots)
    exact(certificate, COMMON | {'source_kind', 'oracle_sha256', 'observer_a_sha256', 'observer_b_sha256', 'prefix', 'final_head', 'count', 'creation_anchor', 'complete_interval'}, 'CERTIFICATE_SCHEMA')
    common(certificate, a, scope)
    need(certificate['source_kind'] == 'INDEPENDENT_FINITE_MODEL_CERTIFIER', 'UNQUALIFIED_CERTIFIER')
    for key in ('oracle', 'observer_a', 'observer_b'):
        need(certificate[key + '_sha256'] == digest(packet[key]), 'CERTIFICATE_SUBJECT_BINDING')
    integer(certificate['count'], 2, 64, 'CERTIFICATE_COUNT_TYPE')
    need(certificate['prefix'] == a.prefix and certificate['final_head'] == a.final_head and certificate['count'] == a.event_count, 'INDEPENDENT_CERTIFICATE_HEADS')
    need(certificate['creation_anchor'] == digest(oracle['events'][0]) and certificate['complete_interval'] is True, 'CREATION_OR_INTERVAL_CERTIFICATE')
    ack = envelope(packet['review_ack'], 'reviewer', roots)
    exact(ack, COMMON | {'certificate_sha256', 'outcome', 'native_qualified'}, 'REVIEW_ACK_SCHEMA')
    common(ack, a, scope)
    need(ack['certificate_sha256'] == digest(packet['certificate']), 'REVIEW_EVIDENCE_BINDING')
    need(ack['outcome'] == 'SYNTHETIC_MODEL_ONLY' and ack['native_qualified'] is False, 'NO_REVIEW_AUTHORITY_PROMOTION')
    return {'status': 'FINITE_MODEL_CHECKED_ONLY', 'model_id': a.model_id, 'scope': 'ONE_DECLARED_SYNTHETIC_WINDOW', 'native_source_qualified': False, 'original_target_qualified': False, 'RT04': 'BLOCKED', 'RT01_full': 'BLOCKED', 'Gate2': 'BLOCKED', 'original_halt_root_cause': 'UNKNOWN', 'atomic_snapshot': False, 'execution_authorized': False, 'no_auto_next': True}


def assess(packet, anchors):
    try:
        return verify_model(packet, anchors)
    except Refused as error:
        return {'status': 'INDETERMINATE', 'reason': str(error), 'original_target_qualified': False, 'native_source_qualified': False, 'RT04': 'BLOCKED', 'Gate2': 'BLOCKED', 'execution_authorized': False, 'no_auto_next': True}


class OfflineOneShot:
    """In-memory demonstration only; not a durable native attempt journal."""
    def __init__(self, anchors):
        self._anchors = anchors
        self._used = False

    def assess_once(self, packet):
        need(not self._used, 'ATTEMPT_USED_NO_RETRY_RESUME_OR_FALLBACK')
        self._used = True
        return assess(packet, self._anchors)
