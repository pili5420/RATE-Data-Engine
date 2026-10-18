import ast
import base64
import copy
import hashlib
import json
from pathlib import Path
import unittest
import evidence as m
from fixtures import encode, get_data, packet, set_data
from evaluate_runner import evaluate


class Contract(unittest.TestCase):
    def setUp(self):
        self.p = packet()

    def result(self):
        return m.assess(encode(self.p))

    def unknown(self, why=None):
        r = self.result(); self.assertEqual(r['status'], 'INDETERMINATE')
        self.assertFalse(r['target_host_qualified']); self.assertFalse(r['execution_authorized'])
        self.assertEqual(r['GUI_Gate2'], 'BLOCKED')
        if why: self.assertIn(why, r['reason'])

    def mutate(self, qid, key, value, index=0):
        rows = get_data(self.p, qid); rows[index][key] = value; set_data(self.p, qid, rows)

    def both(self, key, field, value):
        for suffix in ('before', 'after'): self.mutate(key+'_'+suffix, field, value)

    def test_documented_limited_observations_do_not_qualify_target(self):
        r = self.result(); self.assertEqual(r['status'], 'BLOCKED')
        self.assertEqual(r['observations']['D_config']['status'], 'CONFIG_INTENT_OBSERVED')
        self.assertEqual(r['observations']['D_runtime']['status'], 'RUNTIME_PAGEFILE_OBSERVED')
        self.assertEqual(r['observations']['D_system_managed']['status'], 'BLOCKED')
        self.assertEqual(r['observations']['boot_applied']['status'], 'REBOOT_APPLICABILITY_UNPROVEN')
        self.assertFalse(r['target_host_qualified']); self.assertFalse(r['atomic_snapshot'])

    def test_global_true_is_system_wide_only(self):
        self.both('computer', 'AutomaticManagedPagefile', True); r = self.result()
        self.assertEqual(r['observations']['global_policy']['status'], 'SYSTEM_MANAGED_POLICY_OBSERVED')
        self.assertEqual(r['observations']['global_policy']['scope'], 'SYSTEM_WIDE_ONLY')
        self.assertFalse(r['observations']['global_policy']['D_system_managed_inferred'])
        self.assertEqual(r['observations']['D_system_managed']['status'], 'BLOCKED')

    def test_global_true_but_d_missing(self):
        self.both('computer', 'AutomaticManagedPagefile', True)
        set_data(self.p, 'volumes_before', []); set_data(self.p, 'volumes_after', []); self.unknown('D_VOLUME_NOT_OBSERVED')

    def test_no_settings_instance_not_system_managed(self):
        set_data(self.p, 'settings', []); r = self.result()
        self.assertEqual(r['status'], 'INDETERMINATE'); self.assertIsNone(r['observations']['D_config']['values'])
        self.assertEqual(r['observations']['D_system_managed']['status'], 'BLOCKED')

    def test_config_exists_runtime_missing(self):
        set_data(self.p, 'usage', []); self.assertEqual(self.result()['status'], 'CONFIG_RUNTIME_CONFLICT')

    def test_runtime_exists_config_unproven(self):
        set_data(self.p, 'settings', []); r = self.result()
        self.assertEqual(r['observations']['D_runtime']['status'], 'RUNTIME_PAGEFILE_OBSERVED')
        self.assertEqual(r['status'], 'INDETERMINATE'); self.assertFalse(r['target_host_qualified'])

    def test_runtime_outside_requested_range_not_definite_reboot(self):
        self.mutate('usage', 'AllocatedBaseSize', 4096); r = self.result()
        self.assertEqual(r['status'], 'CONFIG_RUNTIME_CONFLICT')
        self.assertIn('PENDING_REBOOT_NOT_PROVEN', ' '.join(r['missing_evidence']))

    def test_zero_zero_cannot_prove_d_policy(self):
        set_data(self.p, 'settings', [{'Name': 'D:\\pagefile.sys', 'InitialSize': 0, 'MaximumSize': 0}])
        set_data(self.p, 'registry', {'kind': 'MultiString', 'PagingFiles': ['D:\\pagefile.sys 0 0']})
        r = self.result(); self.assertEqual(r['observations']['D_system_managed']['status'], 'BLOCKED')
        self.assertEqual(r['observations']['D_config']['status'], 'CONFIG_INTENT_OBSERVED')

    def test_last_boot_is_not_applied_config(self):
        self.assertEqual(self.result()['observations']['boot_applied']['status'], 'REBOOT_APPLICABILITY_UNPROVEN')

    def test_boot_evidence_missing(self):
        set_data(self.p, 'boot_before', []); self.unknown('SINGLETON_REQUIRED')

    def test_boot_changed(self):
        self.mutate('boot_after', 'LastBootUpTime', '2026-10-17T01:00:00.000000Z'); self.unknown('IDENTITY_OR_POLICY_CHANGED')

    def test_host_changed(self):
        self.mutate('computer_after', 'Name', 'OTHER'); self.unknown('IDENTITY_OR_POLICY_CHANGED')

    def test_cross_source_host_mismatch(self):
        self.both('boot', 'CSName', 'OTHER'); self.unknown('HOST_MISMATCH')

    def test_volume_letter_changed(self):
        self.mutate('volumes_after', 'DriveLetter', 'E:'); self.unknown('VOLUME_MAPPING_CHANGED')

    def test_volume_identity_changed(self):
        self.mutate('volumes_after', 'DeviceID', '\\\\?\\Volume{87654321-1234-1234-1234-123456789abc}\\'); self.unknown('VOLUME_MAPPING_CHANGED')

    def test_volume_serial_changed(self):
        self.mutate('volumes_after', 'SerialNumber', 124); self.unknown('VOLUME_MAPPING_CHANGED')

    def test_malformed_volume_guid_not_identity(self):
        self.both('volumes','DeviceID','\\\\?\\Volume{'+'-'*36+'}\\');self.unknown('VOLUME_DEVICE_ID')

    def test_query_wall_interval_cannot_hide_behind_claimed_elapsed(self):
        self.p['ended_utc']='2026-10-18T00:00:32.000000Z'
        self.p['records'][0]['ended_utc']='2026-10-18T00:00:20.000000Z'
        for i,record in enumerate(self.p['records'][1:],1):
            record['started_utc']=f'2026-10-18T00:00:{i+20:02}.000000Z';record['ended_utc']=f'2026-10-18T00:00:{i+20:02}.100000Z'
        self.unknown('QUERY_WALL_CLOCK_BOUND')

    def test_multiple_pagefiles_not_summed_or_globalized(self):
        settings = get_data(self.p, 'settings'); settings.append({'Name':'C:\\pagefile.sys','InitialSize':256,'MaximumSize':512}); set_data(self.p,'settings',settings)
        usage = get_data(self.p, 'usage'); usage.append({'Name':'C:\\pagefile.sys','AllocatedBaseSize':256,'CurrentUsage':0,'PeakUsage':0,'TempPageFile':False}); set_data(self.p,'usage',usage)
        set_data(self.p,'registry',{'kind':'MultiString','PagingFiles':['C:\\pagefile.sys 256 512','D:\\pagefile.sys 512 2048']})
        r=self.result(); self.assertEqual(r['observations']['D_runtime']['values']['AllocatedBaseSize'],1024)
        self.assertEqual(r['status'],'BLOCKED')

    def test_temporary_pagefile(self):
        self.mutate('usage','TempPageFile',True);self.unknown('TEMPORARY_OR_UNKNOWN_PAGEFILE')

    def test_historical_peak_can_exceed_current_allocation(self):
        self.mutate('usage','PeakUsage',4096);self.assertEqual(self.result()['observations']['D_runtime']['status'],'RUNTIME_PAGEFILE_OBSERVED')

    def test_registry_cim_conflict(self):
        set_data(self.p,'registry',{'kind':'MultiString','PagingFiles':['D:\\pagefile.sys 1024 4096']});self.assertEqual(self.result()['status'],'CONFIG_RUNTIME_CONFLICT')

    def test_missing_registry_corrob_not_false_conflict(self):
        set_data(self.p,'registry',{'kind':'MultiString','PagingFiles':[]});self.assertEqual(self.result()['status'],'INDETERMINATE')

    def test_unsupported_automatic_registry_marker(self):
        set_data(self.p,'registry',{'kind':'MultiString','PagingFiles':['?:\\pagefile.sys']});self.unknown('REGISTRY_GRAMMAR_SOURCE_GAP')

    def test_registry_wrong_type(self):
        set_data(self.p,'registry',{'kind':'String','PagingFiles':['D:\\pagefile.sys 512 2048']});self.unknown('REGISTRY_KIND_OR_BOUND')

    def test_registry_duplicate_target(self):
        set_data(self.p,'registry',{'kind':'MultiString','PagingFiles':['D:\\pagefile.sys 512 2048']*2});self.unknown('DUPLICATE_REGISTRY')

    def test_wrong_field_schema(self):
        self.mutate('usage','InjectedCommand','Set-CimInstance');self.unknown('CIM_FIELD_SCHEMA')

    def test_path_injection(self):
        self.mutate('settings','Name','D:\\pagefile.sys;Set-CimInstance');self.unknown('UNSUPPORTED_PAGEFILE_PATH')

    def test_unc_path(self):
        self.mutate('usage','Name','\\\\other\\pagefile.sys');self.unknown('UNSUPPORTED_PAGEFILE_PATH')

    def test_provider_mismatch(self):
        self.p['records'][0]['provider']='Other';self.unknown('QUERY_SCOPE_OR_PROVIDER')

    def test_previously_assumed_volume_provider_is_not_accepted(self):
        self.p['records'][3]['provider']='MS_VOLUME';self.unknown('QUERY_SCOPE_OR_PROVIDER')

    def test_provider_dll_name_is_not_registration_identity(self):
        self.p['records'][3]['provider']='Vdswmi';self.unknown('QUERY_SCOPE_OR_PROVIDER')

    def test_class_injection(self):
        self.p['records'][0]['class']='Win32_Process';self.unknown('QUERY_SCOPE_OR_PROVIDER')

    def test_remote_namespace_injection(self):
        self.p['records'][0]['namespace']='\\\\other\\ROOT\\CIMV2';self.unknown('QUERY_SCOPE_OR_PROVIDER')

    def test_unrequested_property(self):
        self.p['records'][0]['fields'].append('UserName');self.unknown('QUERY_SCOPE_OR_PROVIDER')

    def test_query_reorder(self):
        self.p['records'][0],self.p['records'][1]=self.p['records'][1],self.p['records'][0];self.unknown('QUERY_SCOPE_OR_PROVIDER')

    def test_partial_query_set(self):
        self.p['records'].pop();self.unknown('INCOMPLETE_QUERY_SET')

    def test_query_timeout(self):
        self.p['records'][0]['elapsed_ms']=10001;self.unknown('QUERY_TIMEOUT')

    def test_query_clock_backwards(self):
        self.p['records'][0]['ended_utc']='2026-10-17T00:00:00.000000Z';self.unknown('QUERY_CLOCK_OR_ORDER')

    def test_timestamp_invalid_calendar(self):
        self.p['started_utc']='2026-99-18T00:00:00.000000Z';self.unknown('INVALID_UTC')

    def test_naive_timestamp(self):
        self.p['started_utc']='2026-10-18T00:00:00';self.unknown('UTC_ENCODING')

    def test_boot_in_future(self):
        self.both('boot','LastBootUpTime','2026-10-19T00:00:00.000000Z');self.unknown('BOOT_TIME_OR_CLOCK_MISMATCH')

    def test_raw_digest_mismatch(self):
        self.p['records'][0]['raw_sha256']='0'*64;self.unknown('RAW_DIGEST')

    def test_corrupt_base64(self):
        self.p['records'][0]['raw_utf8_b64']='!';self.unknown('RAW_BASE64')

    def test_boolean_config_size(self):
        self.mutate('settings','InitialSize',True);self.unknown('CONFIG_SIZE_TYPE')

    def test_boolean_runtime_size(self):
        self.mutate('usage','CurrentUsage',False);self.unknown('RUNTIME_SIZE_TYPE')

    def test_boolean_global_as_integer(self):
        self.both('computer','AutomaticManagedPagefile',1);self.unknown('GLOBAL_POLICY_STRICT_BOOL')

    def test_unknown_host_uuid(self):
        self.both('product','UUID','00000000-0000-0000-0000-000000000000');self.unknown('UNKNOWN_HOST_UUID')

    def test_duplicate_drive_letter(self):
        for qid in ('volumes_before','volumes_after'):
            rows=get_data(self.p,qid);other=copy.deepcopy(rows[0]);other['DeviceID']='\\\\?\\Volume{87654321-1234-1234-1234-123456789abc}\\';rows.append(other);set_data(self.p,qid,rows)
        self.unknown('DUPLICATE_DRIVE_LETTER')

    def test_duplicate_usage(self):
        set_data(self.p,'usage',get_data(self.p,'usage')*2);self.unknown('DUPLICATE_USAGE')

    def test_duplicate_config(self):
        set_data(self.p,'settings',get_data(self.p,'settings')*2);self.unknown('DUPLICATE_SETTINGS')

    def test_source_error_cases(self):
        for error in ('ACCESS_DENIED','WMI_FAILURE','PROVIDER_UNAVAILABLE','TIMEOUT','PARTIAL'):
            with self.subTest(error=error):
                self.p=packet();self.p['records'][4]['status']=error;self.p['records'][4]['error']=error;self.unknown('SOURCE_ERROR_PARTIAL_OR_UNAVAILABLE')

    def test_malformed_outer_inputs(self):
        for raw in (b'',b'null',b'{"x":1,"x":2}',b'{} garbage',b'\xff',b'NaN',b'1.0',b'{'):
            with self.subTest(raw=raw):self.assertEqual(m.assess(raw)['status'],'INDETERMINATE')

    def test_no_unknown_data_promotion(self):
        self.p['realm']='TARGET_HOST_QUALIFIED';self.unknown('NO_TARGET_ACTIVATION_OR_SCOPE_CHANGE')

    def test_no_extra_permit_or_review_authority(self):
        self.p['execution_permit']={'allow':True};self.unknown('PACKET_SCHEMA')

    def test_runner_does_not_transfer_to_original_host(self):
        self.p['realm']='RUNNER_ONLY_NOT_TARGET_HOST_EVIDENCE';r=self.result()
        self.assertFalse(r['target_host_qualified']);self.assertFalse(r['execution_authorized']);self.assertEqual(r['original_halt_root_cause'],'UNKNOWN')

    def test_evidence_fields_attached_to_subconclusions(self):
        r=self.result()
        for field in ('identity','query_interval','clock','raw_packet_sha256','provider_records','missing_evidence','reason'):self.assertIn(field,r)
        self.assertEqual(len(r['provider_records']),11);self.assertFalse(r['identity']['trusted_host_boot_volume_attestation'])


class StaticBoundary(unittest.TestCase):
    def test_validator_has_no_os_collector(self):
        tree=ast.parse(Path(m.__file__).read_text())
        imports={n.names[0].name.split('.')[0] for n in ast.walk(tree) if isinstance(n,ast.Import)}
        self.assertTrue(imports <= {'base64','binascii','datetime','hashlib','json','re'})
        self.assertFalse(any(isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id in {'eval','exec','open','compile','__import__'} for n in ast.walk(tree)))

    def test_exact_readonly_plan(self):
        self.assertEqual(len(m.ORDER),11);self.assertEqual(m.ORDER.count('registry'),1)
        self.assertEqual(set(m.CLASSES),{'computer','boot','product','volumes','settings','usage'})


class ArtifactBinding(unittest.TestCase):
    def setUp(self):self.p=packet();self.p['realm']='RUNNER_ONLY_NOT_TARGET_HOST_EVIDENCE'
    def test_runner_bound_is_still_unqualified(self):
        r=evaluate(encode(self.p),'a'*40,'1','1');self.assertEqual(r['status'],'BLOCKED');self.assertFalse(r['target_host_qualified'])
    def test_wrong_head_rejected(self):
        self.assertEqual(evaluate(encode(self.p),'b'*40,'1','1')['status'],'INDETERMINATE')
    def test_wrong_run_rejected(self):
        self.assertEqual(evaluate(encode(self.p),'a'*40,'2','1')['status'],'INDETERMINATE')
    def test_wrong_attempt_rejected(self):
        self.assertEqual(evaluate(encode(self.p),'a'*40,'1','2')['status'],'INDETERMINATE')
    def test_synthetic_not_transferable_to_runner(self):
        self.p['realm']='SYNTHETIC_ONLY';self.assertEqual(evaluate(encode(self.p),'a'*40,'1','1')['status'],'INDETERMINATE')


if __name__=='__main__':unittest.main(verbosity=2)
