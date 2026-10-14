"""SYNTHETIC ONLY: approvals/authorizations here are never live governance evidence."""
from collections import Counter
from copy import deepcopy
from datetime import date, timedelta
from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts.verify_ci_applicability import network_guard
sys.addaudithook(network_guard)
from src import history_acquisition_execution as h
from src import history_chunk_planning as c
from src.history_chunk_aggregation import aggregate
from tests.test_history_acquisition_wiring import universe, payload, Clock

MAIN = "a" * 40
CUTOFFS = {"TWSE":"2026-10-12", "TPEX":"2026-10-13"}
MONTHS = [f"2026{n:02}" for n in range(1,11)]


def approval(scope, *, status="CONTROL_CENTER_ACCEPTED_EXACT_SCOPE"):
    return h.evidence.identified({"artifact_kind":"RATE_HISTORY_STOCK_SCOPE_APPROVAL_V1", "contract":c.CONTRACT,
        "status":status, **{k:scope[k] for k in ("scope_id","scope_sha256","main_sha","universe_sha256","market","scope_evidence_sha256","material_scope")}},
        "rate-history-stock-scope-approval-","approval_id","approval_sha256")


def authorized(bundle):
    candidate = bundle["candidate"]
    core = {k:v for k,v in candidate.items() if k not in ("authorization_id","authorization_sha256")}
    core["status"] = h.AUTHORIZED
    return h.evidence.identified(core,"rate-history-acquisition-authorization-","authorization_id","authorization_sha256")


def binding(bundle, auth):
    return {"execution_root":bundle["execution_root"], "consumption_root":bundle["consumption_root"],
            "plan":bundle["plan"], "seal":bundle["seal"], "authorization":auth}


def supplied(bundle, auth):
    b = binding(bundle,auth)
    return {"chunk_id":bundle["chunk_id"], "binding":b, "trusted_binding_sha256":h.evidence.sha(b)}


class ChunkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bench_tmp = tempfile.TemporaryDirectory(prefix="chunk-synthetic-benchmark-")
        cls.u = universe()
        cls.days, specs = {}, []
        for market, cutoff in CUTOFFS.items():
            cursor, days = date(2026,1,1), []
            while cursor <= date.fromisoformat(cutoff):
                if cursor.weekday() < 5: days.append(cursor.isoformat())
                cursor += timedelta(days=1)
            cls.days[market] = days[-180:]
            specs.extend({"market":market,"product":"benchmark","symbol":None,"period":m} for m in sorted({d[:7].replace("-","") for d in days[-180:]}))
        root = Path(cls.bench_tmp.name)
        plan = h.build_plan(MAIN,cls.u,specs,CUTOFFS,synthetic=True)
        seal = h.build_seal(plan,root/"evidence",root/"consumption")
        bundle = {"candidate":h.candidate_authorization(seal)}
        auth = authorized(bundle)
        clock = Clock()
        def capture(entry):
            fields = ["Date","收盤指數" if entry["market"]=="TWSE" else "收市"]
            rows = [[d.replace("-","/"),"100"] for d in cls.days[entry["market"]] if d[:7].replace("-","")==entry["period"]]
            return {"raw_bytes":h.evidence.canonical({"fields":fields,"data":rows}),"http_status":200,
                    "final_url":entry["request_url"],"content_type":"application/json"}
        result = h.execute(plan,seal,auth,artifacts_root=root/"evidence",consumption_root=root/"consumption",output_root=root/"evidence/run",
            trusted_authorization_sha256=auth["authorization_sha256"],synthetic=True,transport=capture,
            utc=lambda:"2026-10-14T00:00:00Z",monotonic=clock.now,sleep=clock.sleep)
        assert result["status"] == "PASS"
        cls.benchmark = {"execution_root":str(root/"evidence/run"),"consumption_root":str(root/"consumption"),
                         "plan":plan,"seal":seal,"authorization":auth}
        cls.benchmark_pin = h.evidence.sha(cls.benchmark)

    @classmethod
    def tearDownClass(cls):
        cls.bench_tmp.cleanup()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="chunk-synthetic-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.calls = []
        self.make(11,periods=["202609"])

    def make(self,n,market="TWSE",periods=MONTHS,entries=None):
        symbols = sorted(r["symbol"] for r in self.u["stocks"] if r["market"]==market)[:n]
        entries = entries if entries is not None else [{"market":market,"symbol":s,"period":p} for s in symbols for p in periods]
        self.scope = c.stock_scope(MAIN,self.u,entries,CUTOFFS,market,"b"*64,synthetic=True)
        self.approval = approval(self.scope)
        self.manifest = self.plan()
        return self.manifest

    def plan(self,**kwargs):
        return c.build_manifest(self.scope,self.approval,trusted_approval_sha256=kwargs.pop("pin",self.approval["approval_sha256"]),
            main_sha=kwargs.pop("main_sha",MAIN),universe=kwargs.pop("universe",self.u),synthetic=kwargs.pop("synthetic",True),**kwargs)

    def material(self,n=0):
        return c.materials(self.manifest,self.scope,self.approval,trusted_approval_sha256=self.approval["approval_sha256"],
            main_sha=MAIN,universe=self.u,chunk_id=self.manifest["chunks"][n]["chunk_id"],campaign_root=self.root/"campaign",synthetic=True)

    def capture(self,entry):
        self.calls.append(entry["request_key"])
        p = payload(entry)
        table = p["tables"][0] if "tables" in p else p
        table["data"][0][0] = entry["period"][:4]+"/"+entry["period"][4:]+"/01"
        return {"raw_bytes":h.evidence.canonical(p),"http_status":200,"final_url":entry["request_url"],"content_type":"application/json"}

    def run_chunk(self,bundle,auth=None,capture=None):
        auth = authorized(bundle) if auth is None else auth
        clock = Clock()
        result = c.execute_chunk(self.manifest,self.scope,self.approval,bundle,auth,
            trusted_approval_sha256=self.approval["approval_sha256"],main_sha=MAIN,universe=self.u,
            trusted_authorization_sha256=auth["authorization_sha256"],synthetic=True,transport=capture or self.capture,
            utc=lambda:"2026-10-14T00:00:00Z",monotonic=clock.now,sleep=clock.sleep)
        return result,auth

    def agg(self,chunks,**kwargs):
        return aggregate(self.manifest,self.scope,self.approval,chunks,kwargs.pop("benchmark",self.benchmark),
            trusted_approval_sha256=self.approval["approval_sha256"],trusted_benchmark_sha256=kwargs.pop("benchmark_pin",self.benchmark_pin),
            main_sha=MAIN,universe=self.u,synthetic=True,**kwargs)

    def test_one_issuer_ten_months(self):
        m = self.make(1)
        self.assertEqual((m["chunk_count"],m["chunks"][0]["request_count"]),(1,10))

    def test_ten_issuers_hundred_requests(self):
        m = self.make(10)
        self.assertEqual((m["chunk_count"],m["chunks"][0]["request_count"]),(1,100))

    def test_eleven_issuers_two_chunks(self):
        self.assertEqual([x["request_count"] for x in self.make(11)["chunks"]],[100,10])

    def test_twentyone_issuers_three_chunks(self):
        self.assertEqual([x["request_count"] for x in self.make(21)["chunks"]],[100,100,10])

    def test_partial_windows_retained_exactly(self):
        self.make(11)
        entries = self.scope["entries"][:-5]
        self.make(11,entries=entries)
        self.assertEqual([x["request_count"] for x in self.manifest["chunks"]],[100,5])

    def test_request_limit_can_bind_before_issuer_limit(self):
        periods = ["202511","202512",*MONTHS]
        m = self.make(9,periods=periods)
        self.assertEqual([x["issuer_count"] for x in m["chunks"]],[8,1])
        self.assertEqual([x["request_count"] for x in m["chunks"]],[96,12])

    def test_shuffle_produces_identical_canonical_scope_and_manifest(self):
        m = self.make(21)
        original = h.evidence.canonical(m)
        self.make(21,entries=list(reversed(self.scope["entries"])))
        self.assertEqual(h.evidence.canonical(self.manifest),original)

    def test_entry_union_exact_no_duplicates(self):
        m = self.make(21)
        entries = [e for ch in m["chunks"] for e in ch["entries"]]
        self.assertEqual(entries,self.scope["entries"])
        self.assertEqual(len(entries),len({(e["market"],e["symbol"],e["period"]) for e in entries}))
        for ch in m["chunks"]:
            self.assertLessEqual(ch["issuer_count"],10); self.assertLessEqual(ch["request_count"],100)

    def test_no_caller_endpoint_or_ranking_fields(self):
        for key in ("endpoint","request_url","score","rank","liquidity"):
            entries = deepcopy(self.scope["entries"]); entries[0][key] = "forbidden"
            with self.assertRaisesRegex(ValueError,"SCOPE_FIELDS_INVALID"):
                c.stock_scope(MAIN,self.u,entries,CUTOFFS,"TWSE","b"*64,synthetic=True)

    def test_mixed_market_scope_rejected(self):
        entries = deepcopy(self.scope["entries"]); entries[0]["market"] = "TPEX"
        with self.assertRaisesRegex(ValueError,"MIXED_MARKET"):
            c.stock_scope(MAIN,self.u,entries,CUTOFFS,"TWSE","b"*64,synthetic=True)

    def test_wrong_symbol_market_rejected(self):
        entries = deepcopy(self.scope["entries"]); entries[0]["symbol"] = "6488"
        with self.assertRaisesRegex(ValueError,"UNIVERSE_MISMATCH"):
            c.stock_scope(MAIN,self.u,entries,CUTOFFS,"TWSE","b"*64,synthetic=True)

    def test_duplicate_scope_entry_rejected(self):
        with self.assertRaisesRegex(ValueError,"DUPLICATE_REQUEST"):
            c.stock_scope(MAIN,self.u,[self.scope["entries"][0]]*2,CUTOFFS,"TWSE","b"*64,synthetic=True)

    def test_future_and_older_substitution_rejected(self):
        for period in ("202611","202410"):
            entries = deepcopy(self.scope["entries"]); entries[0]["period"] = period
            with self.assertRaises(ValueError):
                c.stock_scope(MAIN,self.u,entries,CUTOFFS,"TWSE","b"*64,synthetic=True)

    def test_main_drift_rejected(self):
        with self.assertRaisesRegex(ValueError,"SCOPE_BINDING_MISMATCH"): self.plan(main_sha="c"*40)

    def test_universe_drift_rejected(self):
        u = deepcopy(self.u); u["stocks"][0]["symbol"] = "DIFFERENT"
        with self.assertRaises(ValueError): self.plan(universe=u)

    def test_synthetic_never_real(self):
        with self.assertRaises(ValueError): self.plan(synthetic=False)

    def test_scope_evidence_tamper_rejected(self):
        self.scope["scope_evidence_sha256"] = "d"*64
        with self.assertRaises(ValueError): self.plan()

    def test_scope_evidence_resigned_but_old_approval_rejected(self):
        self.scope = c.stock_scope(MAIN,self.u,self.scope["entries"],CUTOFFS,"TWSE","d"*64,synthetic=True)
        with self.assertRaisesRegex(ValueError,"NOT_EXTERNALLY_APPROVED"): self.plan()

    def test_external_pin_required(self):
        for pin in (None,"0"*64):
            with self.assertRaisesRegex(ValueError,"APPROVAL_PIN_REQUIRED"): self.plan(pin=pin)

    def test_pending_scope_approval_rejected(self):
        self.approval = approval(self.scope,status="PENDING_CONTROL_CENTER_AUTHORIZATION")
        with self.assertRaisesRegex(ValueError,"NOT_EXTERNALLY_APPROVED"): self.plan()

    def test_approval_owner_or_market_tamper_rejected(self):
        self.approval["market"] = "TPEX"
        with self.assertRaises(ValueError): self.plan()

    def test_plan_reproduced_through_existing_owner(self):
        self.make(21)
        for ch in self.manifest["chunks"]:
            p = c.chunk_plan(self.manifest,ch["chunk_id"])
            self.assertEqual(p,h.build_plan(MAIN,self.u,[{**e,"product":"stock"} for e in ch["entries"]],CUTOFFS,synthetic=True))
            self.assertEqual(len(p["universe"]),1978)
            self.assertEqual(p["maximum_authorized_requests"],ch["request_count"])
            self.assertFalse(p["fallback"] or p["redirect"] or p["auto_resume"])
            self.assertEqual(p["retry"],0)

    def test_independent_seals_candidates_and_roots(self):
        a,b = self.material(0),self.material(1)
        for key in ("seal_id","seal_sha256"): self.assertNotEqual(a["seal"][key],b["seal"][key])
        self.assertNotEqual(a["candidate"]["authorization_id"],b["candidate"]["authorization_id"])
        for key in ("execution_root","consumption_root","artifacts_root"): self.assertNotEqual(a[key],b[key])
        self.assertEqual(a["candidate"]["status"],h.PENDING)

    def test_pending_candidate_rejected_before_consumption(self):
        b = self.material()
        with self.assertRaises(ValueError): self.run_chunk(b,auth=b["candidate"])
        self.assertFalse(self.calls); self.assertFalse(Path(b["execution_root"]).exists())

    def test_empty_stops_chunk_no_next_ordinal_or_chunk(self):
        b,next_b = self.material(0),self.material(1)
        def empty(entry):
            r = self.capture(entry); p = payload(entry); p["data"] = []; r["raw_bytes"] = h.evidence.canonical(p); return r
        result,auth = self.run_chunk(b,capture=empty)
        self.assertEqual(result["orchestration_status"],"HALTED_FOR_CONTROL_CENTER_REVIEW")
        self.assertEqual(result["result"]["actual_requests"],1)
        self.assertEqual(len(self.calls),1)
        stop = h.read_metadata((Path(b["execution_root"])/"STOP.json").read_bytes())
        self.assertEqual(stop["reason"],"HISTORY_EMPTY_PERIOD_UNQUALIFIED")
        self.assertTrue((Path(b["consumption_root"])/(auth["authorization_id"]+".json")).exists())
        self.assertFalse(Path(next_b["consumption_root"]).exists())
        self.assertFalse(result["next_chunk_started"])
        with self.assertRaisesRegex(ValueError,"HALTED_FOR_CONTROL_CENTER_REVIEW"): self.run_chunk(next_b)
        self.assertEqual(len(self.calls),1)

    def test_single_stop_blast_radius_is_one_bounded_chunk(self):
        self.make(21)
        b = self.material()
        def failure(entry):
            r = self.capture(entry); r["http_status"] = 503; return r
        result,_ = self.run_chunk(b,capture=failure)
        self.assertEqual(result["result"]["actual_requests"],1)
        self.assertEqual(b["plan"]["maximum_authorized_requests"],100)
        for ch in self.manifest["chunks"][1:]:
            self.assertFalse((self.root/"campaign"/ch["chunk_id"]/"consumption").exists())

    def test_successful_prior_chunk_preserved_after_second_stop(self):
        a,b = self.material(0),self.material(1)
        first,aa = self.run_chunk(a)
        before = {str(p):p.read_bytes() for p in Path(a["execution_root"]).rglob("*") if p.is_file()}
        def failure(entry):
            r = self.capture(entry); r["raw_bytes"] = b"invalid"; return r
        second,ab = self.run_chunk(b,capture=failure)
        self.assertEqual(first["result"]["status"],"PASS")
        self.assertEqual(second["result"]["status"],"STOPPED")
        self.assertEqual(before,{str(p):p.read_bytes() for p in Path(a["execution_root"]).rglob("*") if p.is_file()})
        replay = h.replay(a["execution_root"],a["plan"],a["seal"],aa,a["consumption_root"])
        self.assertEqual(replay,first["result"])
        result = self.agg([supplied(b,ab),supplied(a,aa)])
        self.assertEqual(result["status"],"PARTIAL_HALTED")
        self.assertEqual(result["accepted_scope_entries"],10)

    def test_success_never_auto_executes_next(self):
        a,b = self.material(0),self.material(1)
        result,_ = self.run_chunk(a)
        self.assertEqual(result["orchestration_status"],"AWAITING_SEPARATE_CHUNK_AUTHORIZATION")
        self.assertFalse(result["next_chunk_started"])
        self.assertFalse(Path(b["execution_root"]).exists())

    def test_complete_aggregate_only_when_every_chunk_passes(self):
        a,b = self.material(0),self.material(1)
        _,aa = self.run_chunk(a)
        partial = self.agg([supplied(a,aa)])
        self.assertEqual(partial["status"],"PARTIAL_HALTED")
        self.assertEqual(len(partial["required_chunks_without_supplied_execution"]),1)
        self.assertEqual(partial["unsupplied_claim_status"],"UNPROVEN_NOT_INFERRED_FROM_ABSENCE_OF_INPUT")
        _,ab = self.run_chunk(b)
        result = self.agg([supplied(b,ab),supplied(a,aa)])
        self.assertEqual(result["status"],"COMPLETE")
        self.assertEqual((result["accepted_scope_entries"],result["scope_entries"]),(11,11))
        self.assertEqual(result["coverage"]["issuer_count"],1978)
        self.assertFalse(result["coverage"]["calendar_180_ready"])
        self.assertEqual(result,self.agg([supplied(a,aa),supplied(b,ab)]))

    def test_empty_aggregate_keeps_entire_universe(self):
        result = self.agg([])
        self.assertEqual(result["status"],"PARTIAL_HALTED")
        self.assertEqual(result["accepted_scope_entries"],0)
        self.assertEqual(result["coverage"]["issuer_count"],1978)

    def test_duplicate_chunk_rejected(self):
        b = self.material(); _,auth = self.run_chunk(b); item = supplied(b,auth)
        self.assertEqual(self.agg([item,item])["status"],"INVALID")

    def test_unmanifested_chunk_rejected(self):
        b = self.material(); _,auth = self.run_chunk(b); item = supplied(b,auth); item["chunk_id"] = "foreign"
        self.assertEqual(self.agg([item])["status"],"INVALID")

    def test_execution_binding_pin_not_self_accepted(self):
        b = self.material(); _,auth = self.run_chunk(b); item = supplied(b,auth); item["trusted_binding_sha256"] = "0"*64
        result = self.agg([item]); self.assertEqual(result["status"],"INVALID"); self.assertIsNone(result["coverage"])

    def test_manifest_duplicate_stock_scope_tamper_rejected(self):
        self.manifest["chunks"][1]["entries"] = deepcopy(self.manifest["chunks"][0]["entries"])
        self.assertEqual(self.agg([])["status"],"INVALID")

    def test_material_root_or_seal_drift_rejected(self):
        b = self.material(); b["execution_root"] = str(self.root/"other")
        with self.assertRaisesRegex(ValueError,"MATERIAL_BINDING"): self.run_chunk(b)
        self.assertFalse(self.calls)

    def test_campaign_stop_survives_independent_cold_process(self):
        b = self.material()
        def failure(entry): raise TimeoutError("SYNTHETIC_ONLY")
        self.run_chunk(b,capture=failure)
        next_b = self.material(1)
        args = {"manifest":self.manifest,"scope":self.scope,"approval":self.approval,"bundle":next_b,"authorization":authorized(next_b)}
        path = self.root/"cold.json"; path.write_bytes(h.evidence.canonical(args))
        code = "import json,sys;from scripts.verify_ci_applicability import network_guard;sys.addaudithook(network_guard);from src.history_chunk_planning import execute_chunk;d=json.load(open(sys.argv[1]));a=d['approval'];au=d['authorization'];execute_chunk(**d,trusted_approval_sha256=a['approval_sha256'],main_sha='a'*40,universe={'verification_status':'PASS','stocks':d['manifest']['universe']},trusted_authorization_sha256=au['authorization_sha256'],synthetic=True)"
        run = subprocess.run([sys.executable,"-B","-c",code,str(path)],capture_output=True,cwd=h.ROOT)
        self.assertNotEqual(run.returncode,0); self.assertIn(b"HALTED_FOR_CONTROL_CENTER_REVIEW",run.stderr)
        self.assertFalse(Path(next_b["consumption_root"]).exists())

    def test_tp_ex_partition_same_and_unit_retained_synthetic(self):
        self.make(11,market="TPEX",periods=["202609"])
        self.assertEqual([ch["issuer_count"] for ch in self.manifest["chunks"]],[10,1])
        b = self.material(); _,auth = self.run_chunk(b)
        result = self.agg([supplied(b,auth)])
        self.assertEqual(result["tpex_unit_status"],"BLOCKED_EXTERNAL_DOCUMENTATION")
        rows = [r for r in result["coverage"]["issuers"] if r["symbol"] in self.manifest["chunks"][0]["symbols"]]
        self.assertTrue(all(r["status"]=="NOT_READY" and "TPEX_UNIT_SCALE_QUALIFICATION_REQUIRED" in r["reasons"] for r in rows))

    def test_real_tp_ex_hold_has_no_executable_seal_or_candidate(self):
        self.make(1,market="TPEX",periods=["202609"])
        # Only isolate the real HOLD branch; this does not qualify a synthetic scope for real use.
        with patch.object(c,"validate_manifest"), patch.object(c,"chunk_plan",return_value={"SYNTHETIC_ONLY_TEST":"PLAN"}):
            b = c.materials(self.manifest,self.scope,self.approval,trusted_approval_sha256="0"*64,
                main_sha=MAIN,universe=self.u,chunk_id=self.manifest["chunks"][0]["chunk_id"],campaign_root=self.root/"held",synthetic=False)
        self.assertEqual(b["execution_status"],"HOLD_EXTERNAL_UNIT_DOCUMENTATION")
        self.assertIsNone(b["seal"]); self.assertIsNone(b["candidate"])
        with patch.object(c,"materials",return_value=b),patch.object(h,"execute") as run:
            with self.assertRaisesRegex(ValueError,"TPEX_UNIT_HOLD"):
                c.execute_chunk(self.manifest,self.scope,self.approval,b,{},trusted_approval_sha256="0"*64,
                    main_sha=MAIN,universe=self.u,trusted_authorization_sha256="0"*64)
            run.assert_not_called()

    def test_aggregate_calls_existing_coverage_owner(self):
        owner = h.coverage_inventory
        with patch.object(h,"coverage_inventory",wraps=owner) as check:
            result = self.agg([])
        self.assertEqual(result["status"],"PARTIAL_HALTED")
        self.assertGreaterEqual(check.call_count,1)

    def test_benchmark_pin_and_cutoff_rejected(self):
        self.assertEqual(self.agg([],benchmark_pin="0"*64)["status"],"INVALID")
        b = deepcopy(self.benchmark); b["plan"]["source_native_cutoffs"]["TWSE"] = "2026-10-11"
        self.assertEqual(self.agg([],benchmark=b,benchmark_pin=h.evidence.sha(b))["status"],"INVALID")

    def test_benchmark_keeps_original_producer_and_observations(self):
        result = self.agg([])
        self.assertEqual(result["benchmark_producer_main_sha"],self.benchmark["plan"]["main_sha"])
        self.assertEqual(result["benchmark_binding_sha256"],self.benchmark_pin)
        self.assertNotIn("generated_at",result)

    def test_unknown_outcome_stops_and_never_resumes(self):
        b = self.material()
        def unknown(entry): self.calls.append(entry["request_key"]); raise TimeoutError("synthetic")
        result,auth = self.run_chunk(b,capture=unknown)
        self.assertEqual(result["result"]["status"],"STOPPED"); self.assertEqual(len(self.calls),1)
        with self.assertRaisesRegex(ValueError,"HALTED_FOR_CONTROL_CENTER_REVIEW"): self.run_chunk(b,auth=auth)
        with self.assertRaisesRegex(ValueError,"RESUME_FORBIDDEN"): h.resume()

    def test_campaign_second_writer_rejected(self):
        b = self.material(); Path(b["campaign_root"]).mkdir(parents=True)
        with h.exclusive_scan(Path(b["campaign_root"])):
            with self.assertRaisesRegex(RuntimeError,"WRITER_ALREADY_ACTIVE"): self.run_chunk(b)
        self.assertFalse(self.calls)

    def test_authorization_for_other_chunk_rejected_before_claim(self):
        a,b = self.material(0),self.material(1)
        with self.assertRaisesRegex(ValueError,"AUTHORIZATION_MISMATCH"):
            self.run_chunk(b,auth=authorized(a))
        self.assertFalse(Path(b["execution_root"]).exists()); self.assertFalse(self.calls)

    def test_successful_consumed_authorization_not_reusable(self):
        b = self.material(); result,auth = self.run_chunk(b)
        before = len(self.calls)
        with self.assertRaisesRegex(ValueError,"ALREADY_CONSUMED"): self.run_chunk(b,auth=auth)
        self.assertEqual(len(self.calls),before)
        self.assertEqual(h.replay(b["execution_root"],b["plan"],b["seal"],auth,b["consumption_root"]),result["result"])

    def test_manifest_resigned_omission_still_rejected(self):
        core = {k:v for k,v in self.manifest.items() if k not in ("manifest_id","manifest_sha256")}
        core["chunks"] = core["chunks"][:-1]
        self.manifest = h.evidence.identified(core,"rate-history-stock-chunk-manifest-","manifest_id","manifest_sha256")
        self.assertEqual(self.agg([])["status"],"INVALID")

    def test_plan_from_other_chunk_rejected(self):
        a,b = self.material(0),self.material(1); _,auth = self.run_chunk(a)
        item = supplied(a,auth); item["binding"]["plan"] = b["plan"]
        item["trusted_binding_sha256"] = h.evidence.sha(item["binding"])
        self.assertEqual(self.agg([item])["status"],"INVALID")

    def test_owner_drift_rejected_before_materialization(self):
        with patch.object(c,"owners",return_value={"changed":"0"*64}),self.assertRaises(ValueError): self.material()
        self.assertFalse((self.root/"campaign").exists())

    def test_aggregate_cold_process_replay_no_dispatch(self):
        b = self.material(); _,auth = self.run_chunk(b)
        obj = {"manifest":self.manifest,"scope":self.scope,"approval":self.approval,"chunks":[supplied(b,auth)],"benchmark":self.benchmark}
        path = self.root/"cold-aggregate.json"; path.write_bytes(h.evidence.canonical(obj))
        code = "import json,sys;from scripts.verify_ci_applicability import network_guard;sys.addaudithook(network_guard);from src.history_chunk_aggregation import aggregate;d=json.load(open(sys.argv[1]));r=aggregate(**d,trusted_approval_sha256=d['approval']['approval_sha256'],trusted_benchmark_sha256=sys.argv[2],main_sha='a'*40,universe={'verification_status':'PASS','stocks':d['manifest']['universe']},synthetic=True);print(r['aggregate_sha256'])"
        run = subprocess.run([sys.executable,"-B","-c",code,str(path),self.benchmark_pin],capture_output=True,text=True,cwd=h.ROOT)
        self.assertEqual(run.returncode,0,run.stderr)
        self.assertEqual(run.stdout.strip(),self.agg([supplied(b,auth)])["aggregate_sha256"])

    def test_root_identity_or_consumption_tamper_rejected(self):
        b = self.material(); _,auth = self.run_chunk(b); item = supplied(b,auth)
        item["binding"]["consumption_root"] = str(self.root/"other-consumption")
        item["trusted_binding_sha256"] = h.evidence.sha(item["binding"])
        self.assertEqual(self.agg([item])["status"],"INVALID")

    def test_second_chunk_consumption_distinct_after_separate_explicit_invocation(self):
        a,b = self.material(0),self.material(1); _,aa = self.run_chunk(a); _,ab = self.run_chunk(b)
        self.assertNotEqual(aa["authorization_id"],ab["authorization_id"])
        ra = h.read_metadata((Path(a["execution_root"])/"consumption.json").read_bytes())
        rb = h.read_metadata((Path(b["execution_root"])/"consumption.json").read_bytes())
        self.assertNotEqual(ra["consumption_sha256"],rb["consumption_sha256"])
        self.assertNotEqual(ra["execution_root_identity"],rb["execution_root_identity"])

    def test_scanner_stop_survives_crash_before_outer_halt_write(self):
        a,b = self.material(0),self.material(1)
        put = h.evidence.put_json
        def crash(path,value):
            if Path(path).name == "HALTED.json": raise OSError("SYNTHETIC_OUTER_CRASH")
            return put(path,value)
        def fail(entry):
            result = self.capture(entry); result["http_status"] = 503; return result
        with patch.object(h.evidence,"put_json",side_effect=crash),self.assertRaisesRegex(OSError,"OUTER_CRASH"):
            self.run_chunk(a,capture=fail)
        self.assertFalse((self.root/"campaign/HALTED.json").exists())
        self.assertTrue((Path(a["execution_root"])/"STOP.json").exists())
        with self.assertRaisesRegex(ValueError,"HALTED_FOR_CONTROL_CENTER_REVIEW"): self.run_chunk(b)
        self.assertFalse(Path(b["consumption_root"]).exists()); self.assertEqual(len(self.calls),1)

    def test_unknown_claim_without_result_blocks_later_chunk(self):
        a,b = self.material(0),self.material(1)
        def killed(entry):
            self.calls.append(entry["request_key"]); raise SystemExit("SYNTHETIC_PROCESS_EXIT")
        with self.assertRaises(SystemExit): self.run_chunk(a,capture=killed)
        self.assertFalse((Path(a["execution_root"])/"RESULT.json").exists())
        self.assertTrue(list(Path(a["consumption_root"]).glob("*.json")))
        with self.assertRaisesRegex(ValueError,"HALTED_FOR_CONTROL_CENTER_REVIEW"): self.run_chunk(b)
        self.assertFalse(Path(b["consumption_root"]).exists()); self.assertEqual(len(self.calls),1)

    def test_prior_success_tamper_rejected_before_later_claim(self):
        a,b = self.material(0),self.material(1); self.run_chunk(a)
        path = next((Path(a["execution_root"])/"raw").glob("*.bin"))
        path.write_bytes(path.read_bytes()+b" ")
        before = len(self.calls)
        with self.assertRaises(ValueError): self.run_chunk(b)
        self.assertEqual(len(self.calls),before); self.assertFalse(Path(b["consumption_root"]).exists())

    def test_aggregate_no_network_ranking_or_publication(self):
        result = self.agg([])
        self.assertEqual((result["network_requests"],result["ranking_executions"],result["production_publications"]),(0,0,0))
        self.assertFalse(result["production_eligible"] or result["fallback"] or result["auto_resume"])
        self.assertEqual(result["historical_pit"],"UNPROVEN")

    def test_no_production_state_paths_written(self):
        b = self.material(); self.run_chunk(b)
        names = {p.name for p in self.root.rglob("*") if p.is_file()}
        for name in ("LATEST.json","RATE_PRODUCTION_SOURCE_BUNDLE_LATEST.json","DecisionState.json","Portfolio.json","Ledger.json"):
            self.assertNotIn(name,names)

    def test_manifest_clock_free_and_no_unresolved_real_scope_budgets(self):
        self.assertNotIn("generated_at",self.manifest)
        source = Path(c.__file__).read_text(encoding="utf-8")
        self.assertNotIn("10760",source)
        self.assertNotIn("8842",source)


def manifest_tamper(field,value):
    def test(self):
        self.manifest[field] = value
        self.assertEqual(self.agg([])["status"],"INVALID")
    return test

for field,value in {"main_sha":"c"*40,"universe_sha256":"d"*64,"market":"TPEX",
                    "source_native_cutoff":"2026-10-11","scope_sha256":"e"*64,"scope_entry_count":0,
                    "issuer_count":0,"chunk_count":0,"chunk_policy":{},"orchestration_owner_sha256_lf":{}}.items():
    setattr(ChunkTests,"test_manifest_tamper_"+field,manifest_tamper(field,value))


def original_tamper(family):
    def test(self):
        b = self.material(); _,auth = self.run_chunk(b)
        path = next((Path(b["execution_root"])/family).glob("*"))
        if family in ("raw","receipts"):
            path.write_bytes(path.read_bytes()+b" ")
        else:
            obj = h.read_metadata(path.read_bytes()); obj["TAMPER"] = True
            path.write_bytes(h.evidence.canonical(obj))
        self.assertEqual(self.agg([supplied(b,auth)])["status"],"INVALID")
    return test

for family in ("raw","receipts","intents","events","checkpoints"):
    setattr(ChunkTests,"test_original_tamper_"+family,original_tamper(family))


if __name__ == "__main__": unittest.main()
