import dataclasses
import json
import unittest
from copy import deepcopy
from pathlib import Path

import finite_model as m
from fixtures import Fixture


class FiniteProofTests(unittest.TestCase):
    def setUp(self): self.f = Fixture()
    def unknown(self, reason=None):
        result = m.assess(self.f.packet, self.f.anchors)
        self.assertEqual(result['status'], 'INDETERMINATE')
        self.assertFalse(result['original_target_qualified'])
        self.assertFalse(result['execution_authorized'])
        self.assertEqual(result['RT04'], 'BLOCKED')
        if reason is not None: self.assertEqual(result['reason'], reason)
    def test_finite_oracle_only_no_native_or_original_target_pass(self):
        result=m.verify_model(self.f.packet,self.f.anchors)
        self.assertEqual(result['status'],'FINITE_MODEL_CHECKED_ONLY')
        self.assertFalse(result['native_source_qualified'])
        self.assertFalse(result['original_target_qualified'])
        self.assertEqual(result['Gate2'],'BLOCKED')
        self.assertEqual(result['original_halt_root_cause'],'UNKNOWN')
        self.assertFalse(result['atomic_snapshot'])
    def test_input_not_modified(self):
        before=deepcopy(self.f.packet);m.verify_model(self.f.packet,self.f.anchors)
        self.assertEqual(self.f.packet,before)
    def test_window_created_before_subscription(self):
        for role in ('observer_a','observer_b'):
            self.f.packet[role]['payload']['ready_tick']=3;self.f.resign(role)
        self.unknown('SUBSCRIPTION_OR_INTERVAL_INCOMPLETE')
    def test_preexisting_window_missing_creation_anchor(self):
        self.f.events[0]['kind']='UNCHANGED';self.f.replace_oracle_scenario()
        self.unknown('DUPLICATE_CREATE_DESTROY_OR_UNKNOWN')
    def test_matching_hwnd_value_with_reused_generation(self):
        self.f.events[1]['scope']['generation']='SYN_GEN_B';self.f.replace_oracle_scenario()
        self.assertEqual(self.f.events[0]['scope']['hwnd'],self.f.events[1]['scope']['hwnd'])
        self.unknown('GENERATION_OR_PROCESS_SCOPE_MISMATCH')
    def test_duplicate_create_identical_identity(self):
        self.f.events[1]['kind']='CREATE';self.f.replace_oracle_scenario()
        self.unknown('DUPLICATE_CREATE_DESTROY_OR_UNKNOWN')
    def test_destroy_is_terminal_unknown(self):
        self.f.events[1]['kind']='DESTROY';self.f.replace_oracle_scenario()
        self.unknown('DUPLICATE_CREATE_DESTROY_OR_UNKNOWN')
    def test_missed_create_valid_signature(self):
        data=self.f.packet['observer_a']['payload'];data['events']=data['events'][1:];self.f.resign('observer_a')
        m.envelope(self.f.packet['observer_a'],'observer_a',dict(self.f.anchors.roots))
        self.unknown('SIGNED_STREAM_OR_ORACLE_DISAGREEMENT')
    def test_missed_destroy_and_reuse_hidden_by_local_reindex(self):
        self.f.events[1]['kind']='DESTROY';self.f.events[2]['kind']='CREATE';self.f.events[2]['scope']['generation']='SYN_GEN_B'
        self.f.rebuild_oracle()
        # Original observer stream stays stable, freshly signed, with zero loss.
        self.f.resign('observer_a');self.f.resign('observer_b')
        self.unknown('DUPLICATE_CREATE_DESTROY_OR_UNKNOWN')
    def test_listener_restart_epoch(self):
        self.f.events[1]['epoch']='SYN_EPOCH_B';self.f.replace_oracle_scenario()
        self.unknown('LISTENER_RESTART')
    def test_listener_restart_counter(self):
        self.f.packet['observer_a']['payload']['restart_count']=1;self.f.resign('observer_a')
        self.unknown('RESTART_OR_REENTRANCY')
    def test_event_buffer_loss(self):
        self.f.packet['observer_a']['payload']['loss']['buffers']=1;self.f.resign('observer_a')
        self.unknown('KNOWN_EVENT_OR_BUFFER_LOSS')
    def test_event_loss(self):
        self.f.packet['observer_a']['payload']['loss']['events']=1;self.f.resign('observer_a')
        self.unknown('KNOWN_EVENT_OR_BUFFER_LOSS')
    def test_unknown_loss_not_zero(self):
        self.f.packet['observer_a']['payload']['loss']['unknown']=None;self.f.resign('observer_a')
        self.unknown('UNKNOWN_LOSS')
    def test_forged_zero_loss_and_signed_incomplete_stream(self):
        for role in ('observer_a','observer_b'):
            self.f.packet[role]['payload']['events'].pop(1);self.f.resign(role)
            m.envelope(self.f.packet[role],role,dict(self.f.anchors.roots))
        self.unknown('SIGNED_STREAM_OR_ORACLE_DISAGREEMENT')
    def test_signed_replacement_oracle_cannot_replace_external_pin(self):
        self.f.packet['oracle']['payload']['events'].pop(1);self.f.resign('oracle')
        m.envelope(self.f.packet['oracle'],'oracle',dict(self.f.anchors.roots))
        self.unknown('EXTERNAL_ORACLE_PIN')
    def test_reentrant_completion_unresolved(self):
        self.f.packet['observer_a']['payload']['reentrancy_unresolved']=True;self.f.resign('observer_a')
        self.unknown('RESTART_OR_REENTRANCY')
    def test_reordered_completion_ticks(self):
        self.f.events[1]['tick']=5;self.f.events[2]['tick']=3;self.f.replace_oracle_scenario()
        self.unknown('EVENT_COMPLETION_ORDER')
    def test_sequence_gap(self):
        self.f.events[1]['seq']=3;self.f.replace_oracle_scenario()
        self.unknown('SEQUENCE_GAP_DUPLICATE_OR_REORDER')
    def test_sequence_duplicate(self):
        self.f.events[1]['seq']=1;self.f.replace_oracle_scenario()
        self.unknown('SEQUENCE_GAP_DUPLICATE_OR_REORDER')
    def test_pid_restart_creation_time_substitution(self):
        self.f.events[1]['scope']['process_creation_filetime']=2000;self.f.replace_oracle_scenario()
        self.unknown('GENERATION_OR_PROCESS_SCOPE_MISMATCH')
    def test_tid_replacement(self):
        self.f.events[1]['scope']['tid']=202;self.f.replace_oracle_scenario()
        self.unknown('GENERATION_OR_PROCESS_SCOPE_MISMATCH')
    def test_host_boot_session_desktop_station_exact_binding(self):
        for field,value in [('host','SYN_OTHER_HOST'),('boot','SYN_OTHER_BOOT'),('session',2),('desktop','SYN_OTHER_DESKTOP'),('station','SYN_OTHER_STATION')]:
            with self.subTest(field=field):
                self.f=Fixture();self.f.packet['observer_a']['payload']['scope'][field]=value;self.f.resign('observer_a')
                self.unknown('EXACT_SCOPE_BINDING')
    def test_process_creation_after_window(self):
        self.f.scope['process_creation_tick']=3;self.f.common['scope']=self.f.scope
        for event in self.f.events:event['scope']=deepcopy(self.f.scope)
        self.f.replace_oracle_scenario();self.unknown('PROCESS_CREATION_ORDER')
    def test_wrong_independent_prefix(self):
        self.f.anchors=dataclasses.replace(self.f.anchors,prefix='d'*64)
        self.unknown('ORACLE_EXTERNAL_HEADS')
    def test_wrong_independent_final_head(self):
        self.f.packet['certificate']['payload']['final_head']='d'*64;self.f.resign('certificate')
        self.unknown('INDEPENDENT_CERTIFICATE_HEADS')
    def test_concurrent_observer_disagreement(self):
        self.f.packet['observer_b']['payload']['events'][1]['scope']['generation']='SYN_OTHER';self.f.resign('observer_b')
        self.unknown('SIGNED_STREAM_OR_ORACLE_DISAGREEMENT')
    def test_terminal_interval_incomplete(self):
        self.f.events[-1]['tick']=4;self.f.replace_oracle_scenario()
        self.unknown('TERMINAL_INTERVAL_SAMPLE')
    def test_observer_horizon_incomplete(self):
        self.f.packet['observer_b']['payload']['horizon_tick']=4;self.f.resign('observer_b')
        self.unknown('SUBSCRIPTION_OR_INTERVAL_INCOMPLETE')
    def test_future_horizon_cannot_certify_unobserved_time(self):
        self.f.packet['observer_b']['payload']['horizon_tick']=6;self.f.resign('observer_b')
        self.unknown('SUBSCRIPTION_OR_INTERVAL_INCOMPLETE')
    def test_file_identity_must_be_128_bit_hex(self):
        self.f.scope['file_id']='not-a-file-id';self.f.common['scope']=self.f.scope
        for event in self.f.events:event['scope']=deepcopy(self.f.scope)
        for role in ('observer_a','observer_b'):self.f.packet[role]['payload']['scope']=deepcopy(self.f.scope)
        self.f.replace_oracle_scenario();self.unknown('FILE_ID_ENCODING')
    def test_forged_creation_certificate(self):
        self.f.packet['certificate']['payload']['creation_anchor']='d'*64;self.f.resign('certificate')
        self.unknown('CREATION_OR_INTERVAL_CERTIFICATE')
    def test_timeout(self):
        self.f.packet['observer_a']['payload']['timeout']=True;self.f.resign('observer_a')
        self.unknown('TIMEOUT_CRASH_OR_UNKNOWN')
    def test_crash(self):
        self.f.packet['observer_b']['payload']['crash']=True;self.f.resign('observer_b')
        self.unknown('TIMEOUT_CRASH_OR_UNKNOWN')
    def test_unknown_crash_status(self):
        self.f.packet['observer_b']['payload']['crash']=None;self.f.resign('observer_b')
        self.unknown('TIMEOUT_CRASH_OR_UNKNOWN')
    def test_external_deadline_elapsed(self):
        self.f.anchors=dataclasses.replace(self.f.anchors,verification_tick=7)
        self.unknown('DEADLINE_OR_INCOMPLETE_HORIZON')
    def test_missing_review_ack(self):
        del self.f.packet['review_ack'];self.unknown('PACKET_SCHEMA')
    def test_review_ack_not_execution_permit(self):
        self.f.packet['review_ack']['payload']['native_qualified']=True;self.f.resign('review_ack')
        self.unknown('NO_REVIEW_AUTHORITY_PROMOTION')
    def test_independent_roots_cannot_alias(self):
        roots=list(self.f.anchors.roots);roots[1]=(roots[1][0],roots[0][1]);self.f.anchors=dataclasses.replace(self.f.anchors,roots=tuple(roots))
        self.unknown('INDEPENDENT_ROOT_ROLES')
    def test_tampered_signature(self):
        self.f.packet['observer_a']['signature']='0'*128;self.unknown('SIGNATURE_INVALID')
    def test_signature_role_confusion(self):
        self.f.packet['observer_a']=self.f.sign('observer_b',self.f.packet['observer_a']['payload'])
        self.unknown('ROLE_BINDING')
    def test_winevent_etw_and_kernel_labels_do_not_qualify(self):
        for label in ('WINEVENT','ETW','SIGNED_KERNEL_WITNESS'):
            with self.subTest(label=label):
                self.f=Fixture();self.f.packet['observer_a']['payload']['source_kind']=label;self.f.resign('observer_a')
                self.unknown('UNQUALIFIED_SOURCE_KIND')
    def test_original_target_transfer_rejected_even_with_new_pins(self):
        scope=json.loads(self.f.anchors.scope_bytes);scope['target_kind']='ORIGINAL_SYSTEM_DIALOG'
        self.f.anchors=dataclasses.replace(self.f.anchors,scope_bytes=m.canonical(scope))
        self.unknown('NO_ORIGINAL_TARGET_TRANSFER')
    def test_boolean_sequence_not_integer(self):
        self.f.events[0]['seq']=True;self.f.replace_oracle_scenario()
        self.unknown('EVENT_SEQUENCE_TYPE')
    def test_boolean_loss_not_integer(self):
        self.f.packet['observer_a']['payload']['loss']['events']=False;self.f.resign('observer_a')
        self.unknown('LOSS_TYPE')
    def test_float_metadata_rejected(self):
        with self.assertRaises(m.Refused):m.canonical({'tick':1.0})
    def test_bounded_event_universe(self):
        self.f.packet['observer_a']['payload']['events']*=22
        self.unknown('METADATA_LIST_BOUND')
    def test_unknown_extra_schema_field(self):
        self.f.packet['observer_a']['payload']['self_declared_lossless']=True;self.f.resign('observer_a')
        self.unknown('OBSERVER_SCHEMA')
    def test_one_shot_cannot_retry_success(self):
        run=m.OfflineOneShot(self.f.anchors);run.assess_once(self.f.packet)
        with self.assertRaisesRegex(m.Refused,'ATTEMPT_USED'):run.assess_once(self.f.packet)
    def test_one_shot_cannot_retry_or_fallback_after_unknown(self):
        run=m.OfflineOneShot(self.f.anchors);bad=deepcopy(self.f.packet);del bad['review_ack']
        self.assertEqual(run.assess_once(bad)['status'],'INDETERMINATE')
        with self.assertRaisesRegex(m.Refused,'ATTEMPT_USED'):run.assess_once(self.f.packet)


class DocumentationBoundaryTests(unittest.TestCase):
    def load(self,name):return json.loads((Path(__file__).parent/name).read_bytes())
    def test_original_target_nogo_is_valid_research_completion(self):
        v=self.load('FEASIBILITY_DECISION_V1.json');self.assertEqual(v['original_target_decision'],'NO_GO')
        self.assertFalse(v['runtime_execution_authorized']);self.assertEqual(v['engineering_blocking_defects'],0)
    def test_contract_ten_items_have_required_six_fields(self):
        v=self.load('REQUIRED_EVIDENCE_CONTRACT_V1.json');self.assertEqual(len(v['requirements']),10)
        for r in v['requirements']:
            self.assertTrue({'required_evidence','available_windows_mechanism','evidence_gap','counterexample','independent_verification','current_feasibility'}<=set(r))
    def test_cooperating_owner_not_original_target(self):
        v=self.load('OPTION_COMPARISON_V1.json');self.assertEqual(v['options'][1]['original_target_status'],'NO_GO')
        self.assertEqual(v['options'][1]['different_cooperating_target_status'],'CONDITIONAL_GO_NEW_CR_ONLY')
    def test_native_activation_absent(self):
        import ast
        path=Path(__file__).parent/'finite_model.py';tree=ast.parse(path.read_text())
        imports={n.names[0].name for n in ast.walk(tree) if isinstance(n,ast.Import)}
        self.assertFalse(imports & {'ctypes','win32gui','win32api','subprocess','socket'})
        self.assertFalse(any(isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id in {'eval','exec','compile','__import__'} for n in ast.walk(tree)))


if __name__=='__main__':unittest.main(verbosity=2)
