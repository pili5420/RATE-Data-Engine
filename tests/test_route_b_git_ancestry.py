from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import unittest

from src.route_b_git_ancestry import build_ancestry_evidence


class AncestryTests(unittest.TestCase):
    def git(self,root,*args):
        return subprocess.check_output(
            ["git","-C",str(root),*args],
            text=True,
            encoding="utf-8",
        ).strip()

    def commit(self,root,path,content,message):
        target=Path(root)/path
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(content,encoding="utf-8")
        self.git(root,"add",path)
        self.git(root,"commit","-m",message)
        return self.git(root,"rev-parse","HEAD")

    def repo(self):
        td=tempfile.TemporaryDirectory()
        root=Path(td.name)
        self.git(root,"init")
        self.git(root,"config","user.email","ci@example.invalid")
        self.git(root,"config","user.name","CI")
        base=self.commit(root,"src/code.py","x=1\n","base")
        return td,root,base

    def test_pointer_only_descendant_passes(self):
        td,root,base=self.repo()
        try:
            head=self.commit(
                root,
                "artifacts/RATE_PRODUCTION_STATE_LATEST.json",
                "{}\n",
                "pointer",
            )
            r=build_ancestry_evidence(
                root,
                activation_merge_sha=base,
                source_heads={"09:30":head},
            )
            self.assertEqual(r["validation_status"],"PASS")
            self.assertTrue(r["source_heads"]["09:30"]["activation_is_ancestor"])
            self.assertTrue(r["source_heads"]["09:30"]["operational_changes_authorized"])
        finally:
            td.cleanup()

    def test_code_change_fails_closed(self):
        td,root,base=self.repo()
        try:
            head=self.commit(root,"src/code.py","x=2\n","code change")
            r=build_ancestry_evidence(
                root,
                activation_merge_sha=base,
                source_heads={"12:00":head},
            )
            self.assertEqual(r["validation_status"],"FAIL_CLOSED")
            self.assertFalse(r["source_heads"]["12:00"]["operational_changes_authorized"])
        finally:
            td.cleanup()

    def test_non_descendant_fails_closed(self):
        td,root,base=self.repo()
        try:
            self.git(root,"checkout","--orphan","other")
            for p in list(root.iterdir()):
                if p.name!=".git":
                    if p.is_file():
                        p.unlink()
            other=self.commit(root,"other.txt","y\n","other")
            r=build_ancestry_evidence(
                root,
                activation_merge_sha=base,
                source_heads={"09:30":other},
            )
            self.assertEqual(r["validation_status"],"FAIL_CLOSED")
            self.assertFalse(r["source_heads"]["09:30"]["activation_is_ancestor"])
        finally:
            td.cleanup()


    def test_dual_baseline_binding_then_pointer_passes(self):
        td,root,base=self.repo()
        try:
            binding=self.commit(
                root,
                "config/RATE_ROUTE_B_ACTIVATION_BASELINE_V1.json",
                '{"activation_merge_sha":"'+base+'"}\n',
                "bind baseline",
            )
            head=self.commit(
                root,
                "artifacts/production_acceptance/current/session.json",
                "{}\n",
                "acceptance pointer",
            )
            r=build_ancestry_evidence(
                root,
                activation_merge_sha=base,
                activation_binding_sha=binding,
                source_heads={"09:30":head},
            )
            self.assertEqual(r["validation_status"],"PASS")
            self.assertEqual(r["activation_binding_sha"],binding)
            self.assertEqual(
                r["binding_changed_paths"],
                ["config/RATE_ROUTE_B_ACTIVATION_BASELINE_V1.json"],
            )
            self.assertTrue(r["source_heads"]["09:30"]["binding_is_ancestor"])
            self.assertTrue(r["source_heads"]["09:30"]["operational_changes_authorized"])
        finally:
            td.cleanup()

    def test_dual_baseline_binding_extra_change_is_rejected(self):
        td,root,base=self.repo()
        try:
            target=root/"config/RATE_ROUTE_B_ACTIVATION_BASELINE_V1.json"
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_text("{}\n",encoding="utf-8")
            (root/"config/other.json").write_text("{}\n",encoding="utf-8")
            self.git(root,"add","config/RATE_ROUTE_B_ACTIVATION_BASELINE_V1.json","config/other.json")
            self.git(root,"commit","-m","bad bind")
            binding=self.git(root,"rev-parse","HEAD")
            head=self.commit(
                root,
                "artifacts/RATE_PRODUCTION_STATE_LATEST.json",
                "{}\n",
                "pointer",
            )
            with self.assertRaisesRegex(Exception,"BINDING_DELTA_INVALID"):
                build_ancestry_evidence(
                    root,
                    activation_merge_sha=base,
                    activation_binding_sha=binding,
                    source_heads={"12:00":head},
                )
        finally:
            td.cleanup()

if __name__=="__main__":
    unittest.main()
