from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from src.intraday_exchange_authority_private_evidence import (
    REQUIRED_SCOPE,
    PrivateAuthorityEvidenceError,
    build_private_authority_manifest,
    hash_private_evidence,
)

ROOT=Path(__file__).resolve().parents[1]


class PrivateEvidenceTests(unittest.TestCase):
    def test_hash_returns_metadata_without_path_or_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/"twse-private.pdf"
            p.write_bytes(b"private-authority-evidence")
            result=hash_private_evidence(
                p,market="TWSE",evidence_reference="TWSE_PRIVATE_2026",
                contract_id="twse-123",asserted_scope=REQUIRED_SCOPE,
            )
        self.assertEqual(result["market"],"TWSE")
        self.assertEqual(len(result["evidence_sha256"]),64)
        self.assertFalse(result["private_evidence_content_embedded"])
        self.assertFalse(result["private_source_path_embedded"])
        self.assertNotIn(str(p),json.dumps(result))
        self.assertNotIn("private-authority-evidence",json.dumps(result))

    def test_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            target=root/"real"
            target.write_bytes(b"x")
            link=root/"link"
            try:
                link.symlink_to(target)
            except OSError:
                return
            with self.assertRaisesRegex(PrivateAuthorityEvidenceError,"SYMLINK_FORBIDDEN"):
                hash_private_evidence(
                    link,market="TWSE",evidence_reference="x",
                    contract_id="x",asserted_scope=REQUIRED_SCOPE,
                )

    def test_scope_must_be_explicit(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/"x"
            p.write_bytes(b"x")
            with self.assertRaisesRegex(PrivateAuthorityEvidenceError,"SCOPE_ASSERTION_REQUIRED"):
                hash_private_evidence(
                    p,market="TPEX",evidence_reference="x",
                    contract_id="x",asserted_scope="UNKNOWN",
                )

    def test_manifest_is_pending_not_authority(self):
        twse={
            "market":"TWSE","evidence_reference":"a","evidence_sha256":"a"*64,
            "evidence_size_bytes":1,"contract_id":"a","asserted_scope":REQUIRED_SCOPE,
            "private_evidence_content_embedded":False,"private_source_path_embedded":False,
            "control_center_review_status":"PENDING",
        }
        tpex=dict(twse); tpex["market"]="TPEX"; tpex["evidence_reference"]="b"
        m=build_private_authority_manifest(
            twse,tpex,provider_name="Fugle",service_id="svc",
            credential_secret_name="FUGLE_API_KEY",
            valid_from="2026-11-04",valid_through="2027-11-03",
        )
        self.assertEqual(m["status"],"PENDING_CONTROL_CENTER_REVIEW")
        self.assertFalse(m["authority_granted_by_manifest"])
        self.assertFalse(m["production_activation_allowed"])

    def test_cli_emits_metadata_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            twse=root/"twse.bin"; twse.write_bytes(b"twse-secret-evidence")
            tpex=root/"tpex.bin"; tpex.write_bytes(b"tpex-secret-evidence")
            out=root/"manifest.json"
            script=ROOT/"scripts"/"build_exchange_authority_private_evidence_manifest.py"
            completed=subprocess.run([
                sys.executable,"-I",str(script),
                "--twse-file",str(twse),"--tpex-file",str(tpex),
                "--twse-reference","TWSE_PRIVATE","--tpex-reference","TPEX_PRIVATE",
                "--twse-contract-id","twse-id","--tpex-contract-id","tpex-id",
                "--twse-scope",REQUIRED_SCOPE,"--tpex-scope",REQUIRED_SCOPE,
                "--valid-from","2026-11-04","--valid-through","2027-11-03",
                "--output",str(out),
            ],capture_output=True,text=True,check=False)
            self.assertEqual(completed.returncode,0,msg=completed.stdout+completed.stderr)
            body=out.read_text(encoding="utf-8")
            self.assertNotIn(str(twse),body)
            self.assertNotIn(str(tpex),body)
            self.assertNotIn("twse-secret-evidence",body)
            self.assertNotIn("tpex-secret-evidence",body)
            data=json.loads(body)
            self.assertEqual(data["status"],"PENDING_CONTROL_CENTER_REVIEW")


if __name__=="__main__":
    unittest.main()
