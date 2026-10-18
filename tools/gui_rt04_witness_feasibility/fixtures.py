"""Ephemeral Ed25519 test keys and finite invented data; never live permits."""
from copy import deepcopy

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import finite_model as m


class Fixture:
    def __init__(self):
        self.keys = {role: Ed25519PrivateKey.generate() for role in m.ROLES}
        self.scope = {'target_kind': 'SYNTHETIC_COOPERATING_OWNER', 'host': 'SYN_HOST_A',
                      'boot': 'SYN_BOOT_A', 'session': 1, 'desktop': 'SYN_DESKTOP',
                      'station': 'SYN_STATION', 'pid': 101, 'process_creation_filetime': 1000,
                      'process_creation_tick': 1, 'executable_path': 'C:\\SYNTHETIC\\owner.exe',
                      'executable_sha256': 'a'*64, 'volume_serial': 21, 'file_id': 'b'*32,
                      'hwnd': 700, 'tid': 201, 'generation': 'SYN_GEN_A', 'class_name': 'SYN_CLASS'}
        self.common = {'realm': m.REALM, 'model_id': 'SYNTHETIC_MODEL_01', 'scope': self.scope,
                       'interval': [1, 5], 'epoch': 'SYN_EPOCH_A', 'domain': 'ONE_DECLARED_SYNTHETIC_WINDOW'}
        self.prefix = 'c'*64
        self.packet = {}
        self.events = [{'seq': i+1, 'tick': tick, 'kind': 'CREATE' if i == 0 else 'UNCHANGED',
                        'scope': deepcopy(self.scope), 'epoch': 'SYN_EPOCH_A'} for i, tick in enumerate([2, 3, 5])]
        self.rebuild_oracle()
        for role in ('observer_a', 'observer_b'):
            data = {**deepcopy(self.common), 'source_kind': 'FINITE_MODEL_OBSERVER',
                    'events': deepcopy(self.events), 'ready_tick': 0, 'horizon_tick': 5,
                    'loss': {'events': 0, 'buffers': 0, 'unknown': False}, 'restart_count': 0,
                    'reentrancy_unresolved': False, 'timeout': False, 'crash': False}
            self.packet[role] = self.sign(role, data)
        self.refresh_certificate()

    def sign(self, role, payload):
        return {'role': role, 'payload': deepcopy(payload), 'signature': self.keys[role].sign(m.signed_message(role, payload)).hex()}

    def rebuild_oracle(self):
        previous = self.prefix
        for event in self.events:
            event.pop('head', None)
            event['previous'] = previous
            event['head'] = m.digest(event)
            previous = event['head']
        data = {**deepcopy(self.common), 'source_kind': 'INDEPENDENT_FINITE_OWNER_ORACLE',
                'events': deepcopy(self.events), 'prefix': self.prefix, 'final_head': previous, 'count': len(self.events)}
        self.packet['oracle'] = self.sign('oracle', data)
        self.anchors = m.Anchors(tuple((role, self.keys[role].public_key().public_bytes_raw()) for role in m.ROLES),
                                 self.common['model_id'], m.canonical(self.scope), tuple(self.common['interval']),
                                 self.common['epoch'], m.digest(self.packet['oracle']), self.prefix, previous,
                                 len(self.events), 5, 6)

    def refresh_certificate(self):
        data = {**deepcopy(self.common), 'source_kind': 'INDEPENDENT_FINITE_MODEL_CERTIFIER',
                'oracle_sha256': m.digest(self.packet['oracle']),
                'observer_a_sha256': m.digest(self.packet['observer_a']),
                'observer_b_sha256': m.digest(self.packet['observer_b']),
                'prefix': self.anchors.prefix, 'final_head': self.anchors.final_head,
                'count': self.anchors.event_count, 'creation_anchor': m.digest(self.packet['oracle']['payload']['events'][0]),
                'complete_interval': True}
        self.packet['certificate'] = self.sign('certifier', data)
        self.refresh_ack()

    def refresh_ack(self):
        data = {**deepcopy(self.common), 'certificate_sha256': m.digest(self.packet['certificate']),
                'outcome': 'SYNTHETIC_MODEL_ONLY', 'native_qualified': False}
        self.packet['review_ack'] = self.sign('reviewer', data)

    def resign(self, slot):
        role = 'certifier' if slot == 'certificate' else 'reviewer' if slot == 'review_ack' else slot
        self.packet[slot] = self.sign(role, self.packet[slot]['payload'])
        if slot in ('observer_a', 'observer_b', 'oracle'):
            self.refresh_certificate()
        elif slot == 'certificate':
            self.refresh_ack()

    def sync_observers(self):
        for role in ('observer_a', 'observer_b'):
            self.packet[role]['payload']['events'] = deepcopy(self.events)
            self.resign(role)

    def replace_oracle_scenario(self):
        """Trusted TEST oracle re-anchoring only; not an attacker capability."""
        self.rebuild_oracle()
        self.sync_observers()
