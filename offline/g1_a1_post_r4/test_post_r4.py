"""Executed synthetic controls and adversarial cases; no host/network I/O."""
import copy
import os
import shutil
import tempfile
import threading
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from offline.model_s_s2_r2.simulator import (Decision, FROZEN_C03_SHA256, ReplayLedger,
    SyntheticTrust, at, canonical, digest)
from offline.g1_a1_post_r4.authority import OfflineAuthorityAdapter, operational_authority
from offline.g1_a1_post_r4.custody import CustodyCoordinator, SyntheticMemoryAnchor
from offline.g1_a1_post_r4.host_contracts import HostDeclaration, validate_static_host, operational_host_gate


class PostR4Tests(unittest.TestCase):
    def setUp(self):
        base = Path(os.environ.get("MODEL_S_S2_TEST_TMP", tempfile.gettempdir())).resolve()
        self.tmp = base / ("SYNTHETIC_post_r4_" + uuid.uuid4().hex)
        self.tmp.mkdir()
        self.addCleanup(self.cleanup_tmp, base)
        self.now = datetime(2030, 1, 1, 12, tzinfo=timezone.utc)
        self.scope = "SYNTHETIC_SCOPE"
        self.authority = "SYNTHETIC_AUTHORITY"
        self.custody_id = "SYNTHETIC_CUSTODY"
        self.trust = SyntheticTrust()
        self.trust.register(self.authority, b"SYNTHETIC_KEY_32_BYTES_LONG_FOR_TEST_ONLY", self.scope)
        self.ledger = ReplayLedger(self.tmp / "ledger.sqlite")
        self.adapter = OfflineAuthorityAdapter(trust=self.trust, ledger=self.ledger,
            authority_id=self.authority, scope=self.scope, source_sha256="a"*64,
            workflow_sha256="b"*64, custody_id=self.custody_id)
        self.permit_payload = {"kind": "SYNTHETIC_RECEIPT_PERMIT", "token": "SYNTHETIC_PERMIT_1",
            "authority_id": self.authority, "scope": self.scope, "run_id": "SYNTHETIC_RUN_1",
            "attempt": 1, "source_sha256": "a"*64, "workflow_sha256": "b"*64,
            "custody_id": self.custody_id, "issued_at": at(self.now-timedelta(minutes=1)),
            "expires_at": at(self.now+timedelta(minutes=5)), "operational": False}
        self.package = canonical({"schema": "SYNTHETIC_EVIDENCE_V1", "frozen_c03_sha256": FROZEN_C03_SHA256,
            "complete": True, "redaction_pass": True,
            "commands": [{"id":"SYNTHETIC_W01","sha256":digest(b"cmd")}],
            "results": [{"id":"SYNTHETIC_W01","sha256":digest(b"result")}]})
        self.receipt_payload = {"kind":"RECEIPT_ACCEPTED", "token":"SYNTHETIC_RECEIPT_1",
            "scope":self.scope, "run_id":"SYNTHETIC_RUN_1", "attempt":1,
            "package_sha256":digest(self.package), "package_length":len(self.package),
            "issued_at":at(self.now-timedelta(minutes=1)),
            "expires_at":at(self.now+timedelta(minutes=5))}

    def cleanup_tmp(self, base):
        if self.tmp.resolve().parent != base or not self.tmp.name.startswith("SYNTHETIC_post_r4_"):
            raise RuntimeError("UNSAFE_TEST_CLEANUP")
        shutil.rmtree(self.tmp)

    def permit(self, **changes):
        return self.trust.sign(self.authority, {**self.permit_payload, **changes})

    def grant(self, **kwargs):
        return self.adapter.authorize(self.permit(**kwargs), run_id="SYNTHETIC_RUN_1", attempt=1, now=self.now)

    def receipt(self, grant, **changes):
        return self.adapter.accept_receipt(grant,
            self.trust.sign(self.authority, {**self.receipt_payload, **changes}), self.package, self.now)

    def custody(self, grant, receipt, **kwargs):
        args = {"permit":grant, "receipt":receipt, "package":self.package,
            "references":[{"id":"SYNTHETIC_PACKAGE","sha256":digest(self.package)}],
            "backup_inventory":[{"copy_id":"SYNTHETIC_PRIMARY","state":"PRESENT"}], "now":self.now}
        args.update(kwargs)
        return CustodyCoordinator(SyntheticMemoryAnchor(), self.ledger, self.custody_id).record(**args)

    def test_positive_chain(self):
        p = self.grant(); self.assertEqual(p.status,"PASS")
        r = self.receipt(p); self.assertEqual(r.status,"PASS")
        c = self.custody(p,r); self.assertEqual(c.status,"PASS")
        self.assertFalse(c.evidence["operational_custody"])
        self.assertEqual(c.evidence["retention_anchor"],r.evidence["receipt_at"])

    def test_forged_signature(self):
        s=self.permit(); s["signature"]="0"*64
        self.assertEqual(self.adapter.authorize(s,run_id="SYNTHETIC_RUN_1",attempt=1,now=self.now).status,"BLOCKED")

    def test_expired(self): self.assertEqual(self.grant(expires_at=at(self.now)).status,"BLOCKED")
    def test_future(self): self.assertEqual(self.grant(issued_at=at(self.now+timedelta(seconds=1))).status,"BLOCKED")
    def test_scope(self): self.assertEqual(self.grant(scope="SYNTHETIC_OTHER").status,"BLOCKED")
    def test_source(self): self.assertEqual(self.grant(source_sha256="c"*64).status,"BLOCKED")
    def test_workflow(self): self.assertEqual(self.grant(workflow_sha256="c"*64).status,"BLOCKED")
    def test_attempt(self): self.assertEqual(self.grant(attempt=2).status,"BLOCKED")
    def test_run(self): self.assertEqual(self.grant(run_id="SYNTHETIC_OTHER").status,"BLOCKED")
    def test_custody_binding(self): self.assertEqual(self.grant(custody_id="SYNTHETIC_OTHER").status,"BLOCKED")
    def test_operational_flag(self): self.assertEqual(self.grant(operational=True).status,"BLOCKED")
    def test_reentry(self):
        self.assertEqual(self.grant().status,"PASS")
        self.assertEqual(self.grant().status,"BLOCKED")

    def test_lost_ack(self):
        s=self.permit()
        self.assertEqual(self.adapter.authorize(s,run_id="SYNTHETIC_RUN_1",attempt=1,now=self.now,failure="lost_ack").status,"UNKNOWN")
        self.assertEqual(self.grant().status,"BLOCKED")

    def test_partial(self):
        s=self.permit()
        self.assertEqual(self.adapter.authorize(s,run_id="SYNTHETIC_RUN_1",attempt=1,now=self.now,failure="before_commit").status,"UNKNOWN")
        self.assertEqual(self.grant().status,"BLOCKED")

    def test_concurrent_single_ack(self):
        results=[]; lock=threading.Lock(); barrier=threading.Barrier(4)
        def worker():
            barrier.wait(); value=self.grant()
            with lock: results.append(value.status)
        threads=[threading.Thread(target=worker) for _ in range(4)]
        for t in threads:t.start()
        for t in threads:t.join()
        self.assertEqual(results.count("PASS"),1)
        self.assertEqual(results.count("BLOCKED"),3)

    def test_revoked(self):
        self.trust.revoke(self.authority,self.now)
        self.assertEqual(self.grant().status,"BLOCKED")

    def test_clock_unknown(self):
        self.assertEqual(self.adapter.authorize(self.permit(),run_id="SYNTHETIC_RUN_1",attempt=1,now=datetime(2030,1,1)).status,"BLOCKED")

    def test_receipt_cross_run(self): self.assertEqual(self.receipt(self.grant(),run_id="SYNTHETIC_OTHER").status,"BLOCKED")
    def test_receipt_cross_attempt(self): self.assertEqual(self.receipt(self.grant(),attempt=2).status,"BLOCKED")

    def test_corrupt_package(self):
        p=self.grant(); r=self.receipt(p)
        self.assertEqual(self.custody(p,r,package=self.package+b"x").status,"BLOCKED")

    def test_forged_permit_decision(self):
        p=self.grant(); r=self.receipt(p)
        forged=Decision("PASS",p.reason,{**p.evidence,"anchor":"0"*64})
        self.assertEqual(self.custody(forged,r).status,"BLOCKED")

    def test_forged_receipt_decision(self):
        p=self.grant(); r=self.receipt(p)
        forged=Decision("PASS",r.reason,{**r.evidence,"anchor":"0"*64})
        self.assertEqual(self.custody(p,forged).status,"BLOCKED")

    def test_missing_backup_inventory(self):
        p=self.grant(); r=self.receipt(p)
        self.assertEqual(self.custody(p,r,backup_inventory=[]).status,"BLOCKED")

    def test_duplicate_backup_inventory(self):
        p=self.grant(); r=self.receipt(p)
        inv=[{"copy_id":"SYNTHETIC_PRIMARY","state":"PRESENT"}]*2
        self.assertEqual(self.custody(p,r,backup_inventory=inv).status,"BLOCKED")

    def test_missing_package_reference(self):
        p=self.grant(); r=self.receipt(p)
        self.assertEqual(self.custody(p,r,references=[]).status,"BLOCKED")

    def test_custody_lost_ack(self):
        p=self.grant(); r=self.receipt(p)
        self.assertEqual(self.custody(p,r,failure="lost_ack").status,"UNKNOWN")

    def test_custody_partial(self):
        p=self.grant(); r=self.receipt(p)
        self.assertEqual(self.custody(p,r,failure="partial").status,"UNKNOWN")

    def test_unassigned_verifier_missing_c11_and_destination(self):
        for flags in ((False,False,False),(True,False,True),(True,True,True)):
            self.assertEqual(operational_host_gate(verifier_appointed=flags[0],c11_adopted=flags[1],custody_qualified=flags[2]).status,"BLOCKED")

    def test_operational_authority_unavailable(self):
        self.assertEqual(operational_authority().status,"BLOCKED")

    def test_static_host_positive_and_negative(self):
        h=HostDeclaration("SYNTHETIC_HOST","SYNTHETIC_WINDOWS",True,self.authority,self.custody_id,True,"FAIL_CLOSED_MANUAL_REVIEW")
        self.assertEqual(validate_static_host(h,expected_authority=self.authority,expected_custody=self.custody_id).status,"PASS")
        for key,value in (("credential_isolation",False),("os_family","WINDOWS"),("authority_binding","SYNTHETIC_WRONG"),("custody_binding","SYNTHETIC_WRONG"),("evidence_collection",False),("recovery","AUTO_RETRY")):
            d={**h.__dict__,key:value}
            self.assertEqual(validate_static_host(HostDeclaration(**d),expected_authority=self.authority,expected_custody=self.custody_id).status,"BLOCKED")


if __name__ == "__main__": unittest.main()
