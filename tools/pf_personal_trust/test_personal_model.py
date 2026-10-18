import ast
import base64
import copy
import hashlib
import json
from pathlib import Path
import unittest
import personal_model as m
import synthetic_fixtures as f
from offline_paths import approved_output

class PersonalTests(unittest.TestCase):
    def test_output_traversal_rejected_before_any_creation(self):
        out=ENGINEERING_OUTPUT_ROOT/'never-created-by-validation'
        bad=str(ENGINEERING_OUTPUT_ROOT)+'\\..\\PF-PERSONAL-UNAUTHORIZED'
        for raw in [bad,str(ENGINEERING_OUTPUT_ROOT)+'/../PF-PERSONAL-UNAUTHORIZED',str(out)+'/./child']:
            with self.assertRaisesRegex(ValueError,'CANONICAL_ABSOLUTE'):approved_output(raw)
        self.assertFalse(out.exists())
    def test_output_requires_direct_approved_root_and_absolute_fresh_path(self):
        with self.assertRaises(ValueError):approved_output('relative-evidence')
        with self.assertRaises(ValueError):approved_output(str(ENGINEERING_OUTPUT_ROOT))
        with self.assertRaises(ValueError):approved_output(r'D:\Codex\unapproved\RATE-PF-PERSONAL-001-Evidence-20300101-000000\child')
    def test_output_policy_does_not_create_accepted_candidate(self):
        path=ENGINEERING_OUTPUT_ROOT/'fresh-validation-only'
        # Hosted CI uses the caller's exact approved test root, not fabricated original-host context.
        self.assertEqual(approved_output(str(path),str(ENGINEERING_OUTPUT_ROOT)),path)
        self.assertFalse(path.exists())
    def reject(self,e,code=None):
        with self.assertRaises(m.Refused) as got:f.assess(e)
        if code:self.assertIn(code,str(got.exception))
    def consent_reject(self,c):
        with self.assertRaises(m.Refused):m.consent(c,f.ctx(),f.TOOL,f.NOW)
    def test_valid_raw_observation_remains_nonqualification(self):
        r=f.assess(f.evidence())
        self.assertEqual(r['status'],'OFFLINE_COMPLETE_RAW_SEMANTICS_ONLY')
        self.assertEqual(r['configuration']['status'],'CONFIGURATION_OBSERVED')
        self.assertEqual(r['runtime_usage']['status'],'RUNTIME_USAGE_OBSERVED')
        self.assertEqual(r['global_automatic']['status'],'SYSTEM_WIDE_AUTOMATIC_SETTING_OBSERVED')
        self.assertFalse(r['real_execution_authorized'] or r['enterprise_permit'])
        self.assertEqual(r['d_policy'],'D_POLICY_NOT_PROVEN');self.assertEqual(r['boot_applied'],'BOOT_APPLIED_NOT_PROVEN')
    def test_tiers_are_distinct_not_substitutable(self):
        c=f.approval();c['tier']=m.ENTERPRISE;self.consent_reject(c)
        self.assertNotEqual(m.PERSONAL,m.ENTERPRISE)
    def test_implicit_consent_and_numeric_aliases_rejected(self):
        for k,v in [('approved',False),('approved',1),('owner_owns_manages',1),('owner_confirmation','YES')]:
            with self.subTest(k=k,v=v):
                c=f.approval();c[k]=v;self.consent_reject(c)
    def test_each_owner_binding_is_exact(self):
        for k,v in [('tool_sha256','c'*64),('scope_sha256','c'*64),('target','C:\\pagefile.sys'),('operation','MODIFY'),('evidence_destination','D:\\other'),('realm','PERSONAL_LIVE'),('version','ENTERPRISE_PERMIT')]:
            with self.subTest(k=k):
                c=f.approval();c[k]=v;self.consent_reject(c)
    def test_host_consent_not_reused_on_another_context(self):
        c=f.approval();c['host_context']['host']='SYNTHETIC-OTHER';self.consent_reject(c)
    def test_consent_unknown_fields_and_secrets_rejected(self):
        for k in ('password','token','private_key','automatic_next','execution_permit'):
            with self.subTest(k=k):
                c=f.approval();c[k]='forbidden';self.consent_reject(c)
    def test_attempt_nonce_bounds(self):
        for k,v in [('attempt','..'),('attempt','REAL-attempt'),('nonce','x'),('nonce',True)]:
            with self.subTest(k=k,v=v):
                c=f.approval();c[k]=v;self.consent_reject(c)
    def test_risks_cannot_be_removed_or_independent_claim_added(self):
        for v in [[],list(m.RISKS)[:-1],list(m.RISKS)+['INDEPENDENTLY_VERIFIED']]:
            c=f.approval();c['accepted_risks']=v;self.consent_reject(c)
    def test_expired_future_oversize_and_invalid_time(self):
        for k,v in [('expires','2030-01-01T12:00:30Z'),('not_before','2030-01-01T12:02:00Z'),('expires','2030-01-01T12:10:01Z'),('not_before','2030-02-31T00:00:00Z')]:
            with self.subTest(k=k,v=v):
                c=f.approval();c[k]=v;self.consent_reject(c)
    def test_boot_after_approval_rejected(self):
        c=f.approval();ctx=f.ctx();ctx['boot_utc']='2030-01-01T12:00:01Z';c['host_context']=ctx
        with self.assertRaisesRegex(m.Refused,'BOOT_AFTER'):m.consent(c,ctx,f.TOOL,f.NOW)
    def test_output_paths_no_unc_ads_devices_traversal(self):
        for v in ['\\\\host\\share','\\\\?\\D:\\evidence','D:\\RATE-Personal-Evidence\\..','D:\\RATE-Personal-Evidence\\SYNTHETIC-attempt-1:stream','C:\\RATE-Personal-Evidence\\SYNTHETIC-attempt-1']:
            with self.subTest(v=v):
                c=f.approval();c['evidence_destination']=v;self.consent_reject(c)
    def test_original_host_realm_is_not_accepted(self):
        e=f.evidence();e['realm']='ORIGINAL_HOST';self.reject(e,'OFFLINE_REALM')
    def test_nonsynthetic_context_cannot_be_observed(self):
        e=f.evidence();e['context_before']['host']='PERSONAL-PC';self.reject(e,'SYNTHETIC_HOST_ONLY')
    def test_wire_duplicate_key_rejected(self):
        b=f.wire(f.evidence()).replace(b'{"clock_source":',b'{"realm":"x","clock_source":',1)
        with self.assertRaises(m.Refused):m.assess(b,f.ctx(),f.TOOL,f.NOW)
    def test_wire_noncanonical_malformed_truncated_and_duplicate_newline(self):
        for b in [b'{}',b'{',f.wire(f.evidence())[:-4],f.wire(f.evidence())+b'\n',json.dumps(f.evidence(),indent=2).encode()+b'\n']:
            with self.subTest(b=b[:20]):
                with self.assertRaises(m.Refused):m.assess(b,f.ctx(),f.TOOL,f.NOW)
    def test_wire_float_nonfinite_utf16_and_surrogates_rejected(self):
        for b in [b'NaN\n',b'1.1\n',b'{"x":"\\ud800"}\n',b'\xff\n',b'{}\n'.decode().encode('utf-16')]:
            with self.subTest(b=b):
                with self.assertRaises(m.Refused):m.strict(b)
    def test_wire_bounds(self):
        for b in [b'',b' '*524289,m.canonical([[[[[[[[[[[[[[[[[1]]]]]]]]]]]]]]]]])+b'\n']:
            with self.assertRaises(m.Refused):m.strict(b)
    def test_record_extra_field_and_wrong_count_rejected(self):
        e=f.evidence();e['records'][0]['secret']='x';self.reject(e,'RECORD_SHAPE')
        e=f.evidence();e['records'].pop();self.reject(e,'RECORD_COMPLETENESS')
    def test_source_queries_fields_remote_and_alias_tampering(self):
        for k,v in [('api','Set-CimInstance'),('namespace','REMOTE/CIMV2'),('filter','Name LIKE "%"'),('max_rows',True),('fields',['OwnerAuth'])]:
            with self.subTest(k=k):
                e=f.evidence();e['records'][4]['query'][k]=v;self.reject(e,'FIXED_QUERY')
    def test_scope_dynamic_remote_and_modification_rejected(self):
        for k,v in [('remote',True),('local_only',False),('target','C:\\pagefile.sys'),('retry',True),('max_records',True),('native_transport','ENABLED')]:
            e=f.evidence();e['scope'][k]=v;self.reject(e,'EXACT_FIXED_SCOPE')
    def test_record_order_sequence_gap_duplicate_boolean(self):
        for v in [0,2,True]:
            e=f.evidence();e['records'][0]['sequence']=v;self.reject(e,'SEQUENCE_ORDER')
        e=f.evidence();e['records'][1]=copy.deepcopy(e['records'][0]);self.reject(e,'SEQUENCE_ORDER')
    def test_raw_hash_base64_and_noncanonical_rejected(self):
        e=f.evidence();e['records'][5]['raw_sha256']='c'*64;self.reject(e,'RAW_SHA256')
        e=f.evidence();e['records'][5]['raw_base64']='!!!';self.reject(e,'RAW_BASE64')
        e=f.evidence();b=b'[ ]\n';e['records'][5].update(raw_base64=base64.b64encode(b).decode(),raw_sha256=hashlib.sha256(b).hexdigest());self.reject(e,'CANONICAL')
    def test_source_field_extra_cannot_capture_password(self):
        e=f.evidence();v=f.rows(e,4);v[0]['OwnerAuth']='secret';f.set_rows(e,4,v);self.reject(e,'EXACT_READ_FIELDS')
    def test_uint32_bool_negative_float_and_overflow_rejected(self):
        for v in [True,-1,2**32,1.5,'512']:
            e=f.evidence();r=f.rows(e,5);r[0]['InitialSize']=v;f.set_rows(e,5,r);self.reject(e)
    def test_global_and_tpm_boolean_strict(self):
        for index,field in [(2,'AutomaticManagedPagefile'),(4,'IsEnabled_InitialValue')]:
            e=f.evidence();r=f.rows(e,index);r[0][field]=1;f.set_rows(e,index,r);self.reject(e)
    def test_fixed_D_only_and_one_row_bound(self):
        for i,k,v in [(5,'Name','C:\\pagefile.sys'),(6,'Name','\\\\host\\D\\pagefile.sys'),(3,'DriveLetter','C:')]:
            e=f.evidence();r=f.rows(e,i);r[0][k]=v;f.set_rows(e,i,r);self.reject(e)
        e=f.evidence();r=f.rows(e,5);f.set_rows(e,5,r+r);self.reject(e,'SINGLE_ROW')
    def test_zero_sizes_and_global_true_never_prove_policy(self):
        e=f.evidence()
        for i in [2,10]:
            r=f.rows(e,i);r[0]['AutomaticManagedPagefile']=True;f.set_rows(e,i,r)
        r=f.rows(e,5);r[0].update(InitialSize=0,MaximumSize=0);f.set_rows(e,5,r)
        r=f.assess(e);self.assertEqual(r['d_policy'],'D_POLICY_NOT_PROVEN');self.assertEqual(r['boot_applied'],'BOOT_APPLIED_NOT_PROVEN')
    def test_missing_instance_never_becomes_success(self):
        for i in [0,5,6,7]:
            e=f.evidence();f.set_rows(e,i,[]);r=f.assess(e)
            self.assertEqual(r['status'],'INDETERMINATE');self.assertEqual(r['configuration']['status'],'INDETERMINATE')
    def test_unavailable_and_indeterminate_are_not_promoted(self):
        for s in ['UNAVAILABLE','INDETERMINATE']:
            e=f.evidence();e['records'][5].update(status=s,raw_base64=None,raw_sha256=None)
            r=f.assess(e);self.assertEqual(r['status'],'INDETERMINATE');self.assertEqual(r['runtime_usage']['status'],'INDETERMINATE')
    def test_unknown_with_fabricated_raw_rejected(self):
        e=f.evidence();e['records'][5]['status']='UNAVAILABLE';self.reject(e,'UNKNOWN_NO_FABRICATED')
    def test_missing_tpm_never_fabricates_readiness_or_attestation(self):
        e=f.evidence();e['records'][4].update(status='UNAVAILABLE',raw_base64=None,raw_sha256=None)
        r=f.assess(e);self.assertEqual(r['tpm'],'UNAVAILABLE');self.assertEqual(r['tpm_readiness'],'INDETERMINATE')
        self.assertEqual(r['tpm_attestation'],'INDEPENDENTLY_ATTESTED_NOT_ESTABLISHED')
    def test_tpm_initial_flags_are_not_tpmready(self):
        r=f.assess(f.evidence());self.assertEqual(r['tpm'],'LOCAL_OBSERVED');self.assertEqual(r['tpm_readiness'],'INDETERMINATE')
    def test_post_context_race_all_fields_fail_closed(self):
        for k,v in [('host','SYNTHETIC-OTHER'),('sid','S-1-5-21-1-2-3-4'),('session',2),('boot_utc','2030-01-01T01:00:00Z'),('volume_serial',55),('os_build','11111')]:
            e=f.evidence();e['context_after'][k]=v;r=f.assess(e)
            self.assertEqual(r['status'],'INDETERMINATE');self.assertEqual(r['context'],'INDETERMINATE')
    def test_same_declared_context_does_not_hide_source_races(self):
        for i,k,v in [(8,'SessionId',2),(9,'LastBootUpTime','2030-01-01T01:00:00Z'),(10,'Name','SYNTHETIC-OTHER'),(11,'SerialNumber',54321)]:
            e=f.evidence();rows=f.rows(e,i);rows[0][k]=v;f.set_rows(e,i,rows);r=f.assess(e)
            self.assertEqual(r['status'],'INDETERMINATE');self.assertFalse(r['real_execution_authorized'])
    def test_both_matching_sources_on_wrong_host_still_indeterminate(self):
        e=f.evidence()
        for i in (2,10):
            rows=f.rows(e,i);rows[0]['Name']='SYNTHETIC-WRONG';f.set_rows(e,i,rows)
        self.assertEqual(f.assess(e)['status'],'INDETERMINATE')
    def test_local_clock_cannot_be_relabelled_trusted(self):
        e=f.evidence();e['clock_source']='TRUSTED_UTC';self.reject(e,'NO_TRUSTED_CLOCK')
    def test_record_clock_reordering_and_timeout_rejected(self):
        e=f.evidence();e['records'][1]['started_utc']='2030-01-01T12:00:00Z';self.reject(e,'QUERY_WINDOW')
        e=f.evidence();e['records'][5]['ended_utc']='2030-01-01T12:00:30Z';self.reject(e,'QUERY_WINDOW')
    def test_envelope_time_future_out_of_consent_and_total_bound(self):
        for k,v in [('ended_utc','2030-01-01T12:01:01Z'),('started_utc','2030-01-01T11:59:59Z'),('ended_utc','2030-01-01T12:03:02Z')]:
            e=f.evidence();e[k]=v;self.reject(e,'READ_WINDOW')
    def test_evidence_tool_and_scope_exact(self):
        e=f.evidence();e['tool_sha256']='f'*64;self.reject(e,'EVIDENCE_TOOL')
    def test_input_and_child_raw_digest_bindings(self):
        e=f.evidence();r=f.assess(e)
        self.assertEqual(r['input_sha256'],hashlib.sha256(f.wire(e)).hexdigest())
        self.assertEqual(r['configuration']['raw_sha256'],e['records'][5]['raw_sha256'])
        self.assertEqual(r['scope_sha256'],m.digest(m.SCOPE))
    def test_labels_are_not_independent_attestation(self):
        r=f.assess(f.evidence());self.assertEqual(r['context'],'CROSS_CHECKED');self.assertEqual(r['owner_declaration'],'OWNER_CONFIRMED')
        self.assertTrue(all(x['independent_attestation']=='INDEPENDENTLY_ATTESTED_NOT_ESTABLISHED' for x in r['records']))
    def test_original_enterprise_gui_halt_and_gaps_never_change(self):
        r=f.assess(f.evidence());self.assertEqual(r['original_states'],m.IMMUTABLE)
        self.assertEqual(r['original_states']['enterprise_evidence'],'0/12 QUALIFIED')
        self.assertEqual(r['original_states']['original_HALT_root_cause'],'UNKNOWN')
        self.assertEqual(r['original_states']['source_gaps'],list(m.GAPS))
        r['original_states']['source_gaps'].clear();self.assertEqual(len(m.GAPS),3)
    def test_journal_happy_path_is_model_only(self):
        j=f.journal()
        for ev in ['OWNER_APPROVES','BEGIN','COMPLETE_RAW']:
            r=m.model_transition(j,ev);j=r['journal'];self.assertFalse(r['real_execution_authorized'])
        self.assertEqual(r['state'],'CLOSED');self.assertEqual(r['durability'],'NOT_IMPLEMENTED_MODEL_ONLY')
    def test_duplicate_approval_and_begin_fail_closed(self):
        j=m.model_transition(f.journal(),'OWNER_APPROVES')['journal']
        with self.assertRaises(m.Refused):m.model_transition(j,'OWNER_APPROVES')
        j=m.model_transition(j,'BEGIN')['journal']
        with self.assertRaises(m.Refused):m.model_transition(j,'BEGIN')
    def test_crash_timeout_error_cancel_terminal_no_resume(self):
        for ev in ['CRASH','TIMEOUT','ERROR','CANCEL','UNKNOWN_OUTCOME']:
            with self.subTest(ev=ev):
                j=m.model_transition(f.journal(),'OWNER_APPROVES')['journal'];j=m.model_transition(j,'BEGIN')['journal']
                r=m.model_transition(j,ev);self.assertIn(r['state'],['HALTED','UNKNOWN'])
                for next_ev in ['OWNER_APPROVES','BEGIN','COMPLETE_RAW','RETRY','RESUME','NEXT']:
                    with self.assertRaises(m.Refused):m.model_transition(r['journal'],next_ev)
    def test_completed_attempt_does_not_authorize_next(self):
        j=f.journal()
        for ev in ['OWNER_APPROVES','BEGIN','COMPLETE_RAW']:j=m.model_transition(j,ev)['journal']
        with self.assertRaises(m.Refused):m.model_transition(j,'OWNER_APPROVES')
    def test_cancel_before_reading_halts(self):
        j=m.model_transition(f.journal(),'OWNER_APPROVES')['journal'];r=m.model_transition(j,'CANCEL')
        self.assertEqual(r['state'],'HALTED')
    def test_event_gap_sequence_and_hash_tamper_rejected(self):
        j=m.model_transition(f.journal(),'OWNER_APPROVES')['journal']
        for k,v in [('sequence',True),('sequence',2),('previous_sha256','c'*64),('entry_sha256','c'*64)]:
            bad=copy.deepcopy(j);bad['events'][0][k]=v
            with self.assertRaises(m.Refused):m.model_transition(bad,'BEGIN')
    def test_journal_not_transplantable_to_other_nonce_attempt(self):
        j=m.model_transition(f.journal(),'OWNER_APPROVES')['journal']
        for k,v in [('attempt','SYNTHETIC-other'),('nonce','f'*64)]:
            bad=copy.deepcopy(j);bad[k]=v
            with self.assertRaisesRegex(m.Refused,'JOURNAL_HASH'):m.model_transition(bad,'BEGIN')
    def test_invalid_journal_realm_or_transition(self):
        j=f.journal();j['realm']='LIVE'
        with self.assertRaises(m.Refused):m.model_transition(j,'OWNER_APPROVES')
        with self.assertRaises(m.Refused):m.model_transition(f.journal(),'BEGIN')
    def test_source_has_no_io_native_subprocess_network_or_live_entry(self):
        t=ast.parse(Path(m.__file__).read_text(encoding='utf-8'))
        imports={n.names[0].name for n in ast.walk(t) if isinstance(n,ast.Import)}
        self.assertEqual(imports,{'base64','binascii','datetime','hashlib','json','re'})
        calls={n.func.id for n in ast.walk(t) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name)}
        self.assertFalse(calls&{'open','eval','exec','compile','__import__'})
        self.assertFalse(any(isinstance(n,ast.ImportFrom) for n in ast.walk(t)))
    def test_scope_contract_and_schema_match_implementation(self):
        d=Path(m.__file__).parent
        self.assertEqual(json.loads((d/'READ_SCOPE_V1.json').read_bytes()),m.SCOPE)
        schema=json.loads((d/'EVIDENCE_SCHEMA_V1.json').read_bytes())
        self.assertEqual(schema['properties']['scope']['const'],m.SCOPE)
        self.assertEqual(schema['properties']['realm']['const'],m.REALM)
        self.assertEqual(set(schema['required']),set(f.evidence()))
    def test_unissued_request_not_consent_or_permit(self):
        d=json.loads((Path(m.__file__).parent/'FUTURE_OWNER_REQUEST_UNISSUED.json').read_bytes())
        for k in ['host','boot','user_SID','volume','tool_sha256','attempt','nonce','Owner_confirmation','risk_acceptance']:self.assertIsNone(d[k])
        self.assertEqual(d['runtime_entry'],'ABSENT');self.assertFalse(d['auto_next'])
    def test_risk_reductions_and_privacy_are_explicit(self):
        d=Path(m.__file__).parent;trust=json.loads((d/'PERSONAL_TRUST_MODEL_V1.json').read_bytes())
        self.assertEqual(len(trust['enterprise_relaxation_matrix']),8)
        self.assertFalse(trust['tiers'][m.PERSONAL]['independent_identity'])
        self.assertFalse(trust['tiers'][m.ENTERPRISE]['substitutable_by_personal'])
        privacy=json.loads((d/'SAFETY_AND_PRIVACY_V1.json').read_bytes())
        self.assertFalse(privacy['lexical_model_is_physical_root_proof'])
    def test_functions_do_not_mutate_inputs(self):
        e=f.evidence();before=copy.deepcopy(e);f.assess(e);self.assertEqual(e,before)
        j=f.journal();before=copy.deepcopy(j);m.model_transition(j,'OWNER_APPROVES');self.assertEqual(j,before)
