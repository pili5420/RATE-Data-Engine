"""Synthetic only: no live provider calls and no real authority files."""
from copy import deepcopy
import json
from pathlib import Path
import socket
import sys
import unittest
from unittest.mock import patch
from uuid import uuid4

from src import prospective_acquisition_recovery as r
from src.provider_eps_candidate import _canonical
from src.provider_eps_metadata import read_metadata
from src.eps_duration_facts.model import Rejected
from src.eps_duration_facts.raw import sha256
from src.provider_eps_dispatch import DispatchGate
from tests import test_prospective_provider_activation as f

CHECKOUT = Path(__file__).resolve().parents[1]


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.case = f.ActivationTests("test_post_activation_accepted")
        self.addCleanup(self.case.doCleanups)
        self.case.setUp()
        self.head = self.case.add()
        self.overlay = Path(self.case.temp.name) / "recovery"
        self.binding_path = Path(self.case.temp.name) / "BINDING.json"
        self.refs = {}; self.dispatches = []
        self.ident = self.add_failure(singleton=True)
        self.binding = {"artifact_kind":"RATE_KNOWN_FAILURE_RECOVERY_BINDING_V1", "legacy_root":str(self.case.root),
            "legacy_checkout":str(CHECKOUT), "legacy_execution":f.EXECUTION,
            "legacy_pipeline_sha256":sha256((CHECKOUT/"scripts/run_prospective_provider_activation.py").read_bytes()),
            "authority_root":str(self.case.authority),"authority_sha256":self.case.authority_pin,
            "authority_id":r.load(self.case.authority,self.case.authority_pin)["authority_id"],
            "config_sha256":self.case.pin,"trusted_head_before_failure":self.head,
            "failures":self.refs,"dispatches":self.dispatches,"acceptance_target":False}
        def git(command, **kwargs):
            return (f.EXECUTION["head_sha"] if command[1:]==["rev-parse","HEAD"] else
                    f.EXECUTION["base_sha"] if command[1]=="merge-base" else "").encode()
        self.gitpatch=patch.object(r.subprocess,"check_output",side_effect=git)
        self.gitpatch.start(); self.addCleanup(self.gitpatch.stop)
        self.freeze()

    def ref(self, path):
        return {"path":str(path),"sha256":sha256(path.read_bytes())}

    def write(self, path, value):
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(value if isinstance(value,bytes) else _canonical(value))
        return self.ref(path)

    def add_failure(self, singleton=False):
        ident=str(uuid4()); root=self.case.root
        directory=root/"captures"/ident
        auth=r.load(self.case.authority,self.case.authority_pin)
        target={"market":"TWSE","period":"2026-09"}; url=f.p.endpoint(**target)
        tick=[100.0]; gate=DispatchGate(13,prior_dispatch=True,clock=lambda:tick[0],utc=lambda:f.LATER)
        tick[0]=113.0; dispatch=gate.boundary(ident)
        intent={"intent_id":ident,"authority_id":auth["authority_id"],"config_sha256":self.case.pin,
            "provider":"MOPS Official","target":target,"requested_at":f.LATER,"dispatch":dispatch}
        intent_ref=self.write(root/"intents"/(ident+".json"),intent)
        raw=b"synthetic failed response"
        receipt={"http_status":502,"source_owner":"MOPS Official","domain":"revenue",
            "acquisition_intent_id":ident,"authority_id":auth["authority_id"],"market":target["market"],
            "requested_period":target["period"],"endpoint":url,"final_url":url,"fallback_used":False,
            "request_method":"GET","body_sha256":sha256(raw),"response_bytes":len(raw),
            "normalization_version":r.NORMALIZATION_VERSION,
            "parser_sha256":sha256((CHECKOUT/"src/sources/fundamental_history.py").read_bytes()),
            "request_started_at":f.LATER,"retrieval_timestamp":f.LATER}
        refs={"intent":intent_ref,"raw":self.write(directory/"failed.bin",raw),
            "receipt":self.write(directory/"receipt.json",receipt),
            "stop":self.write(root/"STOP.json" if singleton else directory/"STOP.json",
                {"intent_id":ident,"reason":"ACQUISITION_OR_VALIDATION_FAILED_NO_RETRY"}),
            "traceback":self.write(directory/"traceback.txt",b"RuntimeError: MOPS_REVENUE_HTTP_502"),
            "request_start":self.write(directory/"request-start.json",{"intent_id":ident,"authority_id":auth["authority_id"],
                "target":target,"dataset":"MOPS_MONTHLY_REVENUE_ARCHIVE","request_started_at":f.LATER}),
            "dispatch":self.write(directory/"dispatch.json",{"intent_id":ident,"provider":"MOPS Official",
                "target":target,"endpoint":url,"dispatch":dispatch,"observed_at":f.LATER}),
            "intent_binding":self.write(directory/"side.json",{**intent,"dataset":"MOPS_MONTHLY_REVENUE_ARCHIVE",
                "original_intent_sha256":intent_ref["sha256"],"dispatch_authorization":dispatch}),
            "checkpoint":self.write(directory/"checkpoint.json",{"ledger_head":self.head,"config_sha256":self.case.pin})}
        self.refs[ident]=refs; self.dispatches.append(refs["dispatch"])
        return ident

    def freeze(self):
        self.binding["original_files"]={str(p.relative_to(self.case.root)):{"sha256":sha256(p.read_bytes())}
            for p in self.case.root.rglob("*") if p.is_file() and p!=self.case.root/".scan.lock"}
        self.binding_path.write_bytes(_canonical(self.binding))
        self.pin=sha256(self.binding_path.read_bytes())

    def resolve(self, ident=None):
        return r.create_resolution(self.overlay,self.binding_path,self.pin,ident or self.ident,f.LATER)

    def replay(self, pins):
        return r.replay_recovered(self.overlay,self.binding_path,self.pin,pins,f.LATER)

    def change(self, key, field, value):
        path=Path(self.refs[self.ident][key]["path"])
        obj=read_metadata(path.read_bytes()); obj[field]=value; path.write_bytes(_canonical(obj))
        # Model a caller supplying fresh hashes: semantic checks must still reject.
        self.refs[self.ident][key]=self.ref(path)
        if key=="dispatch": self.dispatches[0]=self.refs[self.ident][key]
        self.freeze()

    def test_known_failure_recovered_not_soak_pass(self):
        pin=self.resolve(); result=self.replay({self.ident:pin})
        self.assertEqual(result["runtime_status"],r.RECOVERED)
        self.assertEqual(result["successful_prefix"],1)
        self.assertFalse(result["full_soak_pass"])

    def test_original_files_unchanged(self):
        before=deepcopy(self.binding["original_files"])
        pin=self.resolve(); self.replay({self.ident:pin})
        self.assertEqual(before,{str(p.relative_to(self.case.root)):{"sha256":sha256(p.read_bytes())}
            for p in self.case.root.rglob("*") if p.is_file() and p!=self.case.root/".scan.lock"})

    def test_fake_http_failure_rejected(self):
        self.change("receipt","http_status",200)
        with self.assertRaises(Rejected): self.resolve()

    def test_wrong_intent_rejected(self):
        with self.assertRaises(Rejected): self.resolve(str(uuid4()))

    def test_wrong_authority_rejected(self):
        self.change("receipt","authority_id","wrong")
        with self.assertRaises(Rejected): self.resolve()

    def test_wrong_config_rejected(self):
        self.change("intent","config_sha256","0"*64)
        with self.assertRaises(Rejected): self.resolve()

    def test_wrong_endpoint_rejected(self):
        self.change("receipt","endpoint","https://example.invalid/")
        with self.assertRaises(Rejected): self.resolve()

    def test_missing_receipt_rejected(self):
        Path(self.refs[self.ident]["receipt"]["path"]).unlink()
        with self.assertRaises(FileNotFoundError): self.resolve()

    def test_receipt_tamper_rejected(self):
        Path(self.refs[self.ident]["receipt"]["path"]).write_bytes(b"{}")
        with self.assertRaises(Rejected): self.resolve()

    def test_raw_tamper_rejected(self):
        Path(self.refs[self.ident]["raw"]["path"]).write_bytes(b"tampered")
        with self.assertRaises(Rejected): self.resolve()

    def test_stop_tamper_rejected(self):
        Path(self.refs[self.ident]["stop"]["path"]).write_bytes(b"{}")
        with self.assertRaises(Rejected): self.resolve()

    def test_traceback_tamper_rejected(self):
        Path(self.refs[self.ident]["traceback"]["path"]).write_bytes(b"changed")
        with self.assertRaises(Rejected): self.resolve()

    def test_unknown_intent_still_blocked(self):
        unknown=str(uuid4()); self.write(self.case.root/"intents"/(unknown+".json"),{})
        self.freeze(); pin=self.resolve()
        with self.assertRaisesRegex(Rejected,"UNKNOWN_REQUEST_OUTCOME"):
            self.replay({self.ident:pin})

    def test_unknown_cannot_resolve(self):
        unknown=str(uuid4()); self.write(self.case.root/"intents"/(unknown+".json"),{})
        self.freeze()
        with self.assertRaises(Rejected): self.resolve(unknown)

    def test_duplicate_resolution_rejected(self):
        self.resolve()
        with self.assertRaisesRegex(Rejected,"DUPLICATE_RESOLUTION"): self.resolve()

    def test_overwrite_resolution_rejected(self):
        pin=self.resolve(); slot=self.overlay/"resolutions"/(self.ident+".json")
        slot.write_bytes(b"replacement")
        with self.assertRaises(Rejected): self.replay({self.ident:pin})

    def test_failed_intent_reuse_rejected(self):
        with self.assertRaisesRegex(Rejected,"REUSE_FORBIDDEN"): r.assert_fresh_intent(self.binding,self.ident)

    def test_fresh_intent_not_automatically_authorized(self):
        result=r.assert_fresh_intent(self.binding,str(uuid4()))
        self.assertFalse(result["dispatch_authorized"])

    def test_second_independent_failure_representable(self):
        second=self.add_failure(); self.freeze()
        first_pin=self.resolve(); second_pin=self.resolve(second)
        result=self.replay({self.ident:first_pin,second:second_pin})
        self.assertEqual(len(result["resolutions"]),2)
        self.assertTrue((self.case.root/"STOP.json").exists())
        self.assertEqual(len(list((self.overlay/"failures").iterdir())),2)

    def test_duplicate_dispatch_rejected(self):
        self.dispatches.append(self.dispatches[0]); self.freeze()
        with self.assertRaisesRegex(Rejected,"DISPATCH_COUNT"): self.resolve()

    def test_success_head_tamper_rejected(self):
        self.binding["trusted_head_before_failure"]="0"*64; self.freeze()
        with self.assertRaisesRegex(Rejected,"TRUSTED_HEAD"): self.resolve()

    def test_binding_tamper_rejected(self):
        self.binding_path.write_bytes(b"{}")
        with self.assertRaises(Rejected): self.resolve()

    def test_resolution_object_tamper_rejected(self):
        pin=self.resolve(); (self.overlay/"objects"/(pin+".json")).write_bytes(b"{}")
        with self.assertRaises(Rejected): self.replay({self.ident:pin})

    def test_original_store_output_forbidden(self):
        self.overlay=self.case.root/"recovery"
        with self.assertRaisesRegex(Rejected,"ORIGINAL_OUTPUT"): self.resolve()

    def test_stop_wrong_intent_even_with_new_pin_rejected(self):
        self.change("stop","intent_id",str(uuid4()))
        with self.assertRaisesRegex(Rejected,"STOP_MISMATCH"): self.resolve()

    def test_no_source_success_event_created(self):
        pin=self.resolve(); result=self.replay({self.ident:pin})
        self.assertEqual(len(list((self.case.root/"events").iterdir())),1)
        self.assertFalse(result["new_acquisition_authorized"])
        self.assertEqual(result["historical_pit"],"UNPROVEN")

    def test_recovery_network_attempt_rejected(self):
        # Isolated process: installing an audit hook cannot affect other tests.
        import subprocess
        code="from src.prospective_acquisition_recovery import offline_network_guard; import sys,socket; sys.addaudithook(offline_network_guard); socket.getaddrinfo('localhost',443)"
        result=subprocess.run([sys.executable,"-B","-c",code],cwd=CHECKOUT,capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0)
        self.assertIn("RECOVERY_NETWORK_FORBIDDEN",result.stderr)


if __name__=="__main__": unittest.main()
