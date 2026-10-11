"""Synthetic activation authority and existing-transport evidence lifecycle."""
from copy import deepcopy
from contextlib import ExitStack
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.eps_duration_facts.model import Rejected
from src.eps_duration_facts.raw import sha256
from src.full_market_history import put_bytes
from src.provider_eps_candidate import _canonical
from src.provider_eps_dispatch import exclusive_scan
from src.provider_eps_metadata import read_metadata
from src import prospective_provider_activation as a
from scripts import run_prospective_provider_activation as p
from tests.test_prospective_fundamental_provider import (ACTIVATION, REQUESTED, RECEIVED, VALIDATED, LATER,
    EXECUTION, universe, eps, revenue)

COMMIT = "b" * 40
MAIN = "c" * 40


def authority_fixture():
    proof = _canonical({"number": 999, "merged": True, "merged_at": ACTIVATION, "merge_commit_sha": COMMIT,
        "base": {"ref": "main", "repo": {"full_name": a.REPOSITORY}}})
    url = "https://api.github.com/repos/" + a.REPOSITORY + "/pulls/999"
    receipt = _canonical({"endpoint": url, "final_url": url, "http_status": 200, "raw_sha256": sha256(proof),
        "bytes": len(proof), "attempts": 1, "fallback_used": False, "requested_at": REQUESTED, "received_at": RECEIVED})
    return proof, receipt


def authority_patches():
    stack = ExitStack()
    stack.enter_context(patch.object(a, "git", return_value=_canonical(a.CONTRACT)))
    stack.enter_context(patch.object(a, "main_binding", return_value=ACTIVATION))
    stack.enter_context(patch.object(p, "check_execution"))
    return stack


class FakeGate:
    def __init__(self): self.calls = []
    def boundary(self, ident): self.calls.append(ident); return {"request_identity": ident}
    def check_outbound(self, dispatch): pass
    def completed(self): pass


class ActivationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="activation-")
        self.addCleanup(self.temp.cleanup)
        self.patches = authority_patches(); self.addCleanup(self.patches.close)
        self.authority = Path(self.temp.name) / "authority"
        proof, receipt = authority_fixture()
        self.authority_pin = a.seal(self.authority, proof, sha256(proof), receipt, sha256(receipt), MAIN, VALIDATED)
        self.root = Path(self.temp.name) / "evidence"
        self.pin = p.create(self.root, self.authority, self.authority_pin, universe(), EXECUTION)

    def add(self, head=None, data=None, provider="FinMind", target=None, requested=REQUESTED, failure=None):
        if head is not None:
            requested = LATER
        times = iter((requested, requested, requested, LATER if head else VALIDATED, LATER))
        def capture(directory, intent):
            if failure: raise failure
            raw, receipt = data or eps()
            return raw, _canonical(receipt)
        return p.acquire_once(self.root, self.pin, head, provider, target or {"symbol":"1000","market":"TWSE"},
            capture, gate=FakeGate(), clock=lambda: next(times))

    def test_authorization_config(self):
        self.assertEqual(a.CONTRACT["provider_authorization"], "AUTHORIZED_PROSPECTIVE_ONLY")
        self.assertIsNone(a.CONTRACT["activation_timestamp"])
        self.assertEqual(set(a.CONTRACT["providers"]), {"FinMind", "MOPS Official"})

    def test_post_activation_accepted(self):
        head = self.add(); _, auth, events = p.replay(self.root,self.pin,head,LATER)
        self.assertEqual(auth["activation_timestamp"], ACTIVATION)
        self.assertEqual(events[0]["record"]["provider_authorization"], "AUTHORIZED_PROSPECTIVE_ONLY")
        self.assertTrue(events[0]["record"]["prospective_evidence_credit"])

    def test_pre_activation_zero_transport_calls(self):
        calls = []
        with self.assertRaisesRegex(Rejected, "BEFORE_AUTHORIZATION"):
            p.acquire_once(self.root,self.pin,None,"FinMind",{"symbol":"1000","market":"TWSE"},
                lambda *args: calls.append(True),gate=FakeGate(),clock=lambda:"2026-10-09T23:59:59Z")
        self.assertEqual(calls, [])
        self.assertEqual(list((self.root/"intents").iterdir()), [])

    def test_legacy_receipt_not_relabelled(self):
        raw, r = eps(started_at="2026-10-09T23:59:59Z")
        original = _canonical(r)
        with self.assertRaises(Rejected): self.add(data=(raw,r))
        self.assertEqual(_canonical(r), original)
        self.assertTrue((self.root/"STOP.json").exists())
        self.assertEqual(list((self.root/"events").iterdir()), [])

    def test_old_after_activation_but_before_intent_rejected(self):
        with self.assertRaisesRegex(Rejected,"LEGACY_ACQUISITION"):
            self.add(data=eps(started_at=ACTIVATION))

    def test_mops_request_start_missing_rejected(self):
        with self.assertRaisesRegex(Rejected,"REQUEST_TIME_NOT_EVIDENCED"):
            self.add(data=revenue(request_started_at=None),provider="MOPS Official",target={"market":"TWSE","period":"2026-07"})

    def test_mops_complete_receipt_accepted(self):
        head = self.add(data=revenue(),provider="MOPS Official",target={"market":"TWSE","period":"2026-07"})
        _,_,events = p.replay(self.root,self.pin,head,LATER)
        self.assertEqual(events[0]["record"]["requested_at"],REQUESTED)

    def test_mops_existing_opener_hook(self):
        raw, _ = revenue(); calls=[]
        class Response:
            status=200
            headers={"Content-Type":"text/html; charset=utf-8","Content-Length":str(len(raw))}
            def getcode(self): return 200
            def geturl(self): return p.endpoint("TWSE","2026-07")
            def read(self): return raw
        def opener(request,timeout): calls.append(request.full_url); return Response()
        capture=p.mops_capture(opener=opener,clock=lambda:REQUESTED)
        with patch("src.sources.fundamental_history._now",return_value=RECEIVED):
            head=p.acquire_once(self.root,self.pin,None,"MOPS Official",{"market":"TWSE","period":"2026-07"},
                capture,gate=FakeGate(),clock=iter((REQUESTED,REQUESTED,REQUESTED,VALIDATED,LATER)).__next__)
        _,_,events=p.replay(self.root,self.pin,head,LATER)
        receipt=read_metadata((self.root/"receipts"/(events[0]["record"]["receipt_sha256"]+".json")).read_bytes())
        self.assertEqual(receipt["request_started_at"],REQUESTED)
        self.assertEqual(receipt["retrieval_timestamp"],RECEIVED)
        self.assertEqual(len(calls),1)
        self.assertEqual(receipt["acquisition_intent_id"],events[0]["intent_id"])

    def test_raw_tamper(self):
        raw,r=eps(); r["response_body_sha256"]="0"*64
        with self.assertRaises(Rejected): self.add(data=(raw,r))

    def test_receipt_disk_mutation(self):
        head=self.add(); next((self.root/"receipts").iterdir()).write_bytes(b"{}")
        with self.assertRaises(Rejected): p.replay(self.root,self.pin,head,LATER)

    def test_raw_disk_mutation(self):
        head=self.add(); next((self.root/"raw").iterdir()).write_bytes(b"changed")
        with self.assertRaises(Rejected): p.replay(self.root,self.pin,head,LATER)

    def test_intent_mutation(self):
        head=self.add(); path=next((self.root/"intents").iterdir()); path.write_bytes(path.read_bytes()+b" ")
        with self.assertRaises(Rejected): p.replay(self.root,self.pin,head,LATER)

    def test_event_mutation(self):
        head=self.add(); path=next((self.root/"events").iterdir()); path.write_bytes(path.read_bytes()+b" ")
        with self.assertRaises(Rejected): p.replay(self.root,self.pin,head,LATER)

    def test_config_mutation(self):
        (self.root/"CONFIG.json").write_bytes(b"{}")
        with self.assertRaises(Rejected): p.replay(self.root,self.pin,None,LATER)

    def test_authority_mutation(self):
        (self.authority/"ACTIVATION.json").write_bytes(b"{}")
        with self.assertRaises(Rejected): a.load(self.authority,self.authority_pin)

    def test_proof_mutation(self):
        (self.authority/"authorization-proof.json").write_bytes(b"{}")
        with self.assertRaises(Rejected): a.load(self.authority,self.authority_pin)

    def test_proof_receipt_mutation(self):
        (self.authority/"authorization-receipt.json").write_bytes(b"{}")
        with self.assertRaises(Rejected): a.load(self.authority,self.authority_pin)

    def test_timestamp_immutable(self):
        proof,r=authority_fixture(); pr=read_metadata(proof); pr["merged_at"]=REQUESTED
        proof=_canonical(pr); receipt=read_metadata(r); receipt["raw_sha256"]=sha256(proof); receipt["bytes"]=len(proof)
        r=_canonical(receipt)
        with self.assertRaisesRegex(RuntimeError,"IMMUTABLE_HISTORY_CONFLICT"):
            a.seal(self.authority,proof,sha256(proof),r,sha256(r),MAIN,VALIDATED)

    def test_original_authority_unchanged_after_append(self):
        before=(self.authority/"ACTIVATION.json").read_bytes(); self.add()
        self.assertEqual((self.authority/"ACTIVATION.json").read_bytes(),before)

    def test_revision_preserves_evidence(self):
        head=self.add(); before={str(f):f.read_bytes() for f in self.root.rglob("*") if f.is_file() and f.name!=".scan.lock"}
        raw,_=eps(); rows=json.loads(raw)["data"]; rows[0]["value"]="1.234567890123456789"
        head=self.add(head,data=eps(rows,started_at=LATER,received_at=LATER,finished_at=LATER))
        _,_,events=p.replay(self.root,self.pin,head,LATER)
        self.assertEqual(len(events),2)
        self.assertEqual(events[1]["previous_scope_observation"],events[0]["record"]["immutable_snapshot_id"])
        self.assertTrue(all(Path(f).read_bytes()==b for f,b in before.items()))

    def test_overwrite_rejection(self):
        with self.assertRaisesRegex(RuntimeError,"IMMUTABLE_HISTORY_CONFLICT"): put_bytes(self.root,"CONFIG.json",b"replacement")

    def test_duplicate_observation_rejected(self):
        head=self.add()
        with self.assertRaisesRegex(Rejected,"DUPLICATE_OBSERVATION"): self.add(head)

    def test_stale_head_rejected(self):
        self.add()
        with self.assertRaisesRegex(Rejected,"TRUSTED_HEAD_MISMATCH"): p.replay(self.root,self.pin,None,LATER)

    def test_unknown_request_not_retried(self):
        (self.root/"intents"/"unknown.json").write_bytes(b"{}")
        with self.assertRaisesRegex(Rejected,"UNKNOWN_REQUEST_OUTCOME"): self.add()

    def test_error_persists_no_second_transport(self):
        with self.assertRaisesRegex(RuntimeError,"blocked"): self.add(failure=RuntimeError("blocked"))
        calls=[]
        with self.assertRaises(Rejected):
            p.acquire_once(self.root,self.pin,None,"FinMind",{"symbol":"1000","market":"TWSE"},
                lambda *args:calls.append(True),gate=FakeGate(),clock=lambda:LATER)
        self.assertEqual(calls,[])
        self.assertIn("blocked",(self.root/"traceback.txt").read_text())

    def test_http_failure_stops(self):
        with self.assertRaises(Rejected): self.add(data=eps(http_status=429))
        self.assertTrue((self.root/"STOP.json").exists())

    def test_fallback_rejected(self):
        with self.assertRaises(Rejected): self.add(data=eps(fallback_used=True))

    def test_future_request_rejected(self):
        with self.assertRaises(Rejected): self.add(requested="2999-01-01T00:00:00Z")

    def test_future_receipt_rejected(self):
        with self.assertRaises(Rejected): self.add(data=eps(received_at="2999-01-01T00:00:00Z"))

    def test_missing_issuer_retained(self):
        raw,_=eps(); rows=json.loads(raw)["data"][:-1]
        head=self.add(data=eps(rows)); config,_,events=p.replay(self.root,self.pin,head,LATER)
        readiness=p.issuer_readiness(config,events)
        self.assertEqual(len(readiness),1978)
        self.assertEqual(len(readiness[0]["valid_partial_periods"]),7)
        self.assertEqual(readiness[0]["eps_status"],"NOT_READY_MISSING_REQUIRED_PERIOD")

    def test_no_fill_or_imputation(self):
        config,_,events=p.replay(self.root,self.pin,None,LATER)
        readiness=p.issuer_readiness(config,events)
        self.assertTrue(all(r["valid_partial_periods"]==[] and r["fundamental_input_status"]=="NOT_READY_MISSING_REQUIRED_PERIOD" for r in readiness))

    def test_no_historical_credit(self):
        head=self.add(); _,_,events=p.replay(self.root,self.pin,head,LATER); r=events[0]["record"]
        self.assertEqual(r["historical_pit"],"UNPROVEN")
        self.assertEqual(r["original_eight_quarter_coverage_credit"],0)
        self.assertIsNone(r["original_publication_timestamp"])
        self.assertFalse(r["production_eligible"])

    def test_no_first_refresh_ranking_publication(self):
        for key in ("first_refresh_allowed","ranking_activation_allowed","production_publication_allowed","fallback_allowed","decision_eligible"):
            self.assertIs(a.CONTRACT[key],False)
        self.assertEqual(a.CONTRACT["external_authorized_intraday_feed_dependency"],"BLOCKED_EXTERNAL")

    def test_protected_path_rejected(self):
        for name in ("Production","Latest","state","Portfolio","Ledger","artifacts"):
            with self.subTest(name=name):
                with self.assertRaises(Rejected): p.external(Path(self.temp.name)/name/"new")

    def test_second_writer_rejected(self):
        with exclusive_scan(self.root):
            with self.assertRaisesRegex(RuntimeError,"COVERAGE_WRITER_ALREADY_ACTIVE"): self.add()

    def test_wrong_symbol_rejected_before_capture(self):
        with self.assertRaisesRegex(Rejected,"TARGET_INVALID"): self.add(target={"symbol":"XXXX","market":"TWSE"})

    def test_wrong_market_rejected(self):
        with self.assertRaises(Rejected): self.add(target={"symbol":"1000","market":"TPEX"})

    def test_wrong_provider_rejected(self):
        with self.assertRaises(Rejected): self.add(provider="Other")

    def test_wrong_dataset_rejected(self):
        raw,r=eps(); r["query"]["dataset"]="Other"
        with self.assertRaises(Rejected): self.add(data=(raw,r))

    def test_wrong_endpoint_rejected(self):
        with self.assertRaises(Rejected): self.add(data=eps(requested_url="https://example.org"))

    def test_nonquarter_substitution_rejected(self):
        raw,_=eps(); rows=json.loads(raw)["data"]; rows[0]["date"]="2024-06-30"
        with self.assertRaises(Rejected): self.add(data=eps(rows))

    def test_decimal_negative_zero_unchanged(self):
        head=self.add(); _,_,events=p.replay(self.root,self.pin,head,LATER)
        self.assertEqual(events[0]["record"]["rows"][0]["value"],"-0.123456789012345678901")
        self.assertEqual(events[0]["record"]["rows"][1]["value"],"0")

    def test_universe_missing_rejected(self):
        u=universe(); u["stocks"].pop()
        with self.assertRaises(Rejected): p.create(Path(self.temp.name)/"invalid",self.authority,self.authority_pin,u,EXECUTION)

    def test_truncation_rejected(self):
        head=self.add(); next((self.root/"events").iterdir()).unlink()
        with self.assertRaises(Rejected): p.replay(self.root,self.pin,head,LATER)

    def test_cold_process(self):
        head=self.add()
        command=[sys.executable,"-B",str(Path(__file__)),"--synthetic-cold",str(self.root),self.pin,head]
        for _ in range(2):
            result=subprocess.run(command,cwd=a.ROOT,capture_output=True,text=True,encoding="utf-8")
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(json.loads(result.stdout)["events"],1)


class AuthorityNegativeTests(unittest.TestCase):
    def check(self, pr_changes=None, receipt_changes=None, validated=VALIDATED):
        proof,receipt=authority_fixture(); pr=read_metadata(proof); pr.update(pr_changes or {}); proof=_canonical(pr)
        r=read_metadata(receipt); r.update(raw_sha256=sha256(proof),bytes=len(proof)); r.update(receipt_changes or {}); receipt=_canonical(r)
        with authority_patches(): return a.authorization(proof,sha256(proof),receipt,sha256(receipt),MAIN,validated)

    def test_unmerged_rejected(self):
        with self.assertRaises(Rejected): self.check({"merged":False})

    def test_wrong_base_rejected(self):
        with self.assertRaises(Rejected): self.check({"base":{"ref":"other","repo":{"full_name":a.REPOSITORY}}})

    def test_wrong_repository_rejected(self):
        with self.assertRaises(Rejected): self.check({"base":{"ref":"main","repo":{"full_name":"other/repo"}}})

    def test_no_merge_time_rejected(self):
        with self.assertRaises(Rejected): self.check({"merged_at":None})

    def test_future_activation_rejected(self):
        with self.assertRaises(Rejected): self.check({"merged_at":"2999-01-01T00:00:00Z"})

    def test_activation_before_commit_rejected(self):
        with self.assertRaises(Rejected): self.check({"merged_at":"2026-10-09T23:59:59Z"})

    def test_proof_http_error_rejected(self):
        with self.assertRaises(Rejected): self.check(receipt_changes={"http_status":403})

    def test_proof_redirect_rejected(self):
        with self.assertRaises(Rejected): self.check(receipt_changes={"final_url":"https://example.org"})

    def test_proof_retry_rejected(self):
        with self.assertRaises(Rejected): self.check(receipt_changes={"attempts":2})

    def test_proof_fallback_rejected(self):
        with self.assertRaises(Rejected): self.check(receipt_changes={"fallback_used":True})

    def test_external_proof_hash_required(self):
        proof,r=authority_fixture()
        with self.assertRaises(Rejected): a.authorization(proof,"0"*64,r,sha256(r),MAIN,VALIDATED)

    def test_external_receipt_hash_required(self):
        proof,r=authority_fixture()
        with self.assertRaises(Rejected): a.authorization(proof,sha256(proof),r,"0"*64,MAIN,VALIDATED)

    def test_exact_execution_binding(self):
        with self.assertRaises(Rejected): p.check_execution({"base_sha":"0"*40,"head_sha":"0"*40})

    def test_unmerged_current_head_cannot_activate(self):
        # Real Git check, no mocked main binding.
        commit=a.git("rev-parse","HEAD").decode().strip()
        main=a.git("rev-parse","origin/main").decode().strip()
        with self.assertRaises(Rejected): a.main_binding(commit,main,sha256(_canonical(a.CONTRACT)))

    def test_no_existing_entry_imports_activation(self):
        for path in (a.ROOT/"src").rglob("*.py"):
            if path.name!="prospective_provider_activation.py":
                self.assertNotIn("import prospective_provider_activation",path.read_text(encoding="utf-8"))
                self.assertNotIn("from .prospective_provider_activation",path.read_text(encoding="utf-8"))

    def test_main_commit_graph(self):
        with tempfile.TemporaryDirectory(prefix="authority-git-") as directory:
            root=Path(directory)
            def git(*args):
                return subprocess.check_output(["git",*args],cwd=root,stderr=subprocess.DEVNULL).decode().strip()
            git("init"); git("config","user.name","Synthetic Test"); git("config","user.email","synthetic@example.invalid")
            (root/"marker").write_text("synthetic only")
            git("add","."); git("commit","-m","before authorization")
            before=git("rev-parse","HEAD")
            contract=root/a.CONTRACT_PATH; contract.parent.mkdir(parents=True); contract.write_bytes(_canonical(a.CONTRACT))
            git("add","."); git("commit","-m","authorization")
            authorized=git("rev-parse","HEAD")
            git("update-ref","refs/remotes/origin/main",authorized)
            with patch.object(a,"ROOT",root):
                self.assertTrue(a.main_binding(authorized,authorized,sha256(contract.read_bytes())))
                with self.assertRaises(Rejected): a.main_binding(authorized,authorized,"0"*64)
                git("update-ref","refs/remotes/origin/main",before)
                with self.assertRaises(Rejected): a.main_binding(authorized,before,sha256(contract.read_bytes()))
                git("update-ref","refs/remotes/origin/main",authorized)
                (root/"marker").write_text("later")
                git("add","."); git("commit","-m","later main")
                later=git("rev-parse","HEAD"); git("update-ref","refs/remotes/origin/main",later)
                self.assertTrue(a.main_binding(authorized,authorized,sha256(contract.read_bytes())))
                with self.assertRaisesRegex(Rejected,"NOT_FIRST_AUTHORIZATION_COMMIT"):
                    a.main_binding(later,later,sha256(contract.read_bytes()))

    def test_seal_protected_root_rejected(self):
        proof,r=authority_fixture()
        with self.assertRaisesRegex(Rejected,"PROTECTED_OUTPUT"):
            a.seal(a.ROOT/"forbidden",proof,sha256(proof),r,sha256(r),MAIN,VALIDATED)

    def test_normal_merge_first_parent_main_authorization(self):
        with tempfile.TemporaryDirectory(prefix="activation-merge-") as directory:
            root=Path(directory)
            def git(*args):
                return subprocess.check_output(["git",*args],cwd=root,stderr=subprocess.DEVNULL).decode().strip()
            git("init","-b","main"); git("config","user.name","Synthetic Test"); git("config","user.email","synthetic@example.invalid")
            (root/"marker").write_text("before")
            git("add","."); git("commit","-m","before")
            git("checkout","-b","candidate")
            contract=root/a.CONTRACT_PATH; contract.parent.mkdir(parents=True); contract.write_bytes(_canonical(a.CONTRACT))
            git("add","."); git("commit","-m","candidate authorization")
            git("checkout","main"); git("merge","--no-ff","candidate","-m","authorization on main")
            merge=git("rev-parse","HEAD"); git("update-ref","refs/remotes/origin/main",merge)
            with patch.object(a,"ROOT",root):
                self.assertTrue(a.main_binding(merge,merge,sha256(contract.read_bytes())))

    def test_finmind_existing_capture_wrapper(self):
        with tempfile.TemporaryDirectory(prefix="activation-capture-") as directory:
            root=Path(directory); tool=root/"synthetic_capture.py"
            tool.write_text("from pathlib import Path\nimport json\ndef capture(root, ident, url, symbol, **kwargs):\n"
                " (root/'raw/body.json').write_bytes(b'{}')\n"
                " (root/'receipts'/ (ident+'.json')).write_text(json.dumps({'raw_capture_status':'COMPLETE','raw_path':'raw/body.json'}))\n",encoding="utf-8")
            (root/"raw").mkdir(); (root/"receipts").mkdir()
            capture=p.finmind_capture(tool,sha256(tool.read_bytes()))
            raw,receipt=capture(root,{"intent_id":"synthetic","target":{"symbol":"1000"}})
            self.assertEqual(raw,b"{}")
            self.assertEqual(read_metadata(receipt)["raw_capture_status"],"COMPLETE")
            with self.assertRaisesRegex(Rejected,"TRANSPORT_TAMPER"): p.finmind_capture(tool,"0"*64)

    def test_mops_benchmark_endpoint_not_reused(self):
        raw,r=revenue(); r["endpoint"]="https://www.tpex.org.tw/benchmark"
        with tempfile.TemporaryDirectory(prefix="wrong-mops-") as directory, authority_patches():
            root=Path(directory)/"evidence"; authority=Path(directory)/"authority"; proof,receipt=authority_fixture()
            pin=a.seal(authority,proof,sha256(proof),receipt,sha256(receipt),MAIN,VALIDATED)
            config=p.create(root,authority,pin,universe(),EXECUTION)
            with self.assertRaises(Rejected):
                p.acquire_once(root,config,None,"MOPS Official",{"market":"TWSE","period":"2026-07"},
                    lambda *args:(raw,_canonical(r)),gate=FakeGate(),clock=lambda:LATER)


if __name__=="__main__":
    if len(sys.argv)>1 and sys.argv[1]=="--synthetic-cold":
        with authority_patches():
            config,auth,events=p.replay(Path(sys.argv[2]),sys.argv[3],sys.argv[4],LATER)
            print(json.dumps({"events":len(events),"authority_id":auth["authority_id"]}))
    else:
        unittest.main()
