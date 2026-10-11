"""Synthetic engineering fixtures only; never imported financial evidence."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from src import historical_replay_portability as p

ROOT = Path(__file__).resolve().parents[1]
READER = '''import json
from pathlib import Path
import subprocess
import sys
import importlib.util
HERE = Path(__file__).resolve().parent
CONFIG = json.loads((HERE / "CONFIG.json").read_text())
CHECKOUT = Path(CONFIG["execution_checkout"])
sys.path.insert(0, str(CHECKOUT))
from src import sample
def cold(output):
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=CHECKOUT).decode().strip()
    assert git("rev-parse", "HEAD") == CONFIG["execution_head"]
    assert git("rev-parse", "origin/main") == CONFIG["execution_head"]
    assert not git("status", "--porcelain")
    legacy = json.loads((HERE / "LEGACY.json").read_text())
    spec = importlib.util.spec_from_file_location("pinned_engine", Path(legacy["legacy_checkout"]) / "scripts/engine.py")
    engine = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(engine)
    result = {"intent_ids":["intent-1"], "event_ids":["event-1"], "raw_sha256":"raw-pin", "receipt_sha256":"receipt-pin",
      "immutable_snapshot_id":"snapshot-1", "ledger_head":"trusted-head", "resolution":"http-502-resolution",
      "checkpoint":"checkpoint-pin", "provider":"synthetic", "target":"2026-09", "order":[1,2],
      "primary_value":sample.VALUE, "legacy_value":engine.VALUE, "legacy_origin":engine.__file__}
    with Path(output).open("x") as stream: json.dump(result, stream)
    print("Original reader diagnostic preserved")
if __name__ == "__main__": cold(Path(sys.argv[1]))
'''


class PortabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="rp-", dir=ROOT.parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "r"
        self.repo.mkdir()
        self.g("init", "-q")
        self.g("config", "user.name", "Synthetic CI")
        self.g("config", "user.email", "synthetic@example.invalid")
        self.g("config", "core.autocrlf", "false")
        self.g("remote", "add", "origin", p.REPOSITORY)
        for name, body in {"src/__init__.py":"", "src/sample.py":"VALUE = 'PRODUCER'\n",
                           "scripts/__init__.py":"", "scripts/engine.py":"VALUE = 'LEGACY_PRODUCER'\n"}.items():
            path = self.repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body)
        self.g("add", "."); self.g("commit", "-qm", "Synthetic historical producer")
        self.producer = self.g("rev-parse", "HEAD")
        self.primary, self.legacy = self.root / "p", self.root / "l"
        self.g("worktree", "add", "--detach", str(self.primary), self.producer)
        self.g("worktree", "add", "--detach", str(self.legacy), self.producer)
        self.g("update-ref", "refs/remotes/origin/main", self.producer)
        self.reader = self.root / "reader.py"
        self.reader.write_text(READER)
        pins = {name:{"sha256":p.sha((self.repo / name).read_bytes()), "bytes":(self.repo / name).stat().st_size}
                for name in self.g("ls-files").splitlines()}
        self.cfg = self.root / "CONFIG.json"
        self.cfg.write_bytes(p.canonical({"execution_checkout":str(self.primary), "execution_head":self.producer,
            "coordinator_sha256":p.sha(self.reader.read_bytes()), "main_code_pins":pins}))
        self.legacy_cfg = self.root / "LEGACY.json"
        self.legacy_cfg.write_bytes(p.canonical({"legacy_checkout":str(self.legacy), "legacy_execution":{"head_sha":self.producer}}))
        self.accepted = self.root / "ACCEPTED.json"
        original = subprocess.run([sys.executable, "-B", str(self.reader), str(self.accepted)], capture_output=True, env=p.clean_env())
        self.assertEqual(original.returncode, 0, original.stderr.decode())
        (self.repo / "src/sample.py").write_text("VALUE = 'CURRENT_SOURCE_MUST_NOT_EXECUTE'\n")
        self.g("add", "."); self.g("commit", "-qm", "Synthetic legitimate main advance")
        self.main = self.g("rev-parse", "HEAD")
        (self.repo / "consumer.txt").write_text("synthetic consumer")
        self.g("add", "."); self.g("commit", "-qm", "Synthetic readiness consumer")
        self.consumer = self.g("rev-parse", "HEAD")
        self.g("update-ref", "refs/remotes/origin/main", self.main)
        self.binding = {"artifact_kind":p.KIND, "repository_checkout":str(self.repo), "producer_sha":self.producer,
            "current_main_sha":self.main, "consumer_head_sha":self.consumer, "consumer_checkout":str(self.repo),
            "accepted_reader":self.pin(self.reader), "accepted_output":self.pin(self.accepted), "fallback_allowed":False,
            "read_only_roots":[str(self.primary),str(self.legacy)],
            "evidence_pins":{"configuration":self.pin(self.cfg),"recovery_binding":self.pin(self.legacy_cfg)}}

    def g(self, *args):
        return subprocess.check_output(["git", *args], cwd=self.repo, stderr=subprocess.PIPE, env=p.clean_env()).decode().strip()

    def pin(self, path): return {"path":str(path), "sha256":p.sha(path.read_bytes())}

    def worker(self, name, binding=None):
        path = self.root / (name + ".json")
        path.write_bytes(p.canonical(binding or self.binding))
        output = self.root / name
        result = subprocess.run([sys.executable,"-B",str(ROOT / "scripts/run_historical_replay_portability.py"),
            "--binding",str(path),"--binding-sha256",p.sha(path.read_bytes()),"--output",str(output)], capture_output=True, env=p.clean_env())
        return result, output

    def rejection(self, **fields):
        binding = {**self.binding, **fields}
        with self.assertRaises((ValueError, subprocess.CalledProcessError)):
            p.verify_binding(self.repo, binding)

    def test_three_identities_separate(self):
        self.assertEqual(p.verify_binding(self.repo,self.binding)["producer_sha"],self.producer)
        self.assertNotEqual(self.main,self.producer)
        self.assertNotEqual(self.consumer,self.main)

    def test_original_failure_preserved(self):
        result = subprocess.run([sys.executable,"-B",str(self.reader),str(self.root / "failure.json")], capture_output=True, env=p.clean_env())
        self.assertNotEqual(result.returncode,0)
        self.assertIn(b"AssertionError",result.stderr)

    def test_two_independent_cold_replays_full_equivalence(self):
        before = self.g("show-ref")
        outputs = []
        for name in ("one","two"):
            result, path = self.worker(name)
            self.assertEqual(result.returncode,0,result.stderr.decode())
            outputs.append(p.read((path / "REPLAY.json").read_bytes()))
            proof = p.read(result.stdout)
            self.assertFalse(proof["historical_functions_patched"])
            self.assertTrue(proof["executed_sources"])
            self.assertEqual(proof["network_requests"],0)
        self.assertEqual(outputs[0],outputs[1])
        self.assertEqual(outputs[0],p.read(self.accepted.read_bytes()))
        self.assertEqual(outputs[0]["primary_value"],"PRODUCER")
        self.assertEqual(self.g("show-ref"),before)

    def test_wrong_producer(self): self.rejection(producer_sha=self.consumer)
    def test_original_reader_diagnostic_preserved(self):
        result,_=self.worker("diagnostic")
        self.assertEqual(result.returncode,0,result.stderr.decode())
        self.assertEqual(p.read(result.stdout)["status"],"PASS")
        self.assertIn(b"Original reader diagnostic preserved",result.stderr)
    def test_producer_not_ancestor(self):
        self.g("checkout","--orphan","unrelated")
        self.g("commit","--allow-empty","-qm","Unrelated synthetic producer")
        unrelated=self.g("rev-parse","HEAD")
        self.g("checkout","--detach",self.consumer)
        self.rejection(producer_sha=unrelated)
    def test_missing_commit(self): self.rejection(producer_sha="f"*40)
    def test_invalid_commit_expression(self): self.rejection(producer_sha="HEAD")
    def test_wrong_main(self): self.rejection(current_main_sha=self.producer)
    def test_wrong_consumer(self): self.rejection(consumer_head_sha=self.producer)
    def test_dirty_consumer(self):
        (self.repo / "dirty.txt").write_text("dirty")
        self.rejection()
    def test_wrong_repository(self):
        self.g("remote","set-url","origin","https://example.invalid/other.git")
        self.rejection()
    def test_fallback_rejected(self): self.rejection(fallback_allowed=True)
    def test_reader_tamper(self):
        self.reader.write_text(READER + "\n# mutation\n")
        self.rejection()
    def test_checkpoint_tamper(self):
        self.cfg.write_bytes(b"{}")
        self.rejection()
    def test_pinned_historical_ledger_files_mutation(self):
        for name,value,changed in (
            ("CHECKPOINT.json",{"ledger_head":"trusted-head"},{"ledger_head":"changed-head"}),
            ("CONTINUATION_EVENT.json",{"intent_id":"intent-1"},{"intent_id":"changed-intent"}),
            ("INTENT.json",{"requested_at":"2026-10-11T03:00:00Z"},{"requested_at":"2026-10-10T03:00:00Z"}),
        ):
            with self.subTest(name=name):
                path=self.root/name
                path.write_bytes(p.canonical(value))
                binding=deepcopy(self.binding)
                binding["evidence_pins"][name]=self.pin(path)
                path.write_bytes(p.canonical(changed))
                with self.assertRaisesRegex(ValueError,"EVIDENCE_HASH_MISMATCH"):
                    p.verify_binding(self.repo,binding)
    def test_event_mutation_rejected(self):
        a=p.read(self.accepted.read_bytes()); b=deepcopy(a); b["event_ids"]=["changed"]
        with self.assertRaisesRegex(ValueError,"HISTORICAL_OUTPUT_MISMATCH"): p.equivalence(a,b)
    def test_ledger_head_mutation_rejected(self):
        a=p.read(self.accepted.read_bytes()); b=deepcopy(a); b["ledger_head"]="changed"
        with self.assertRaises(ValueError): p.equivalence(a,b)
    def test_identity_not_counts(self):
        a=p.read(self.accepted.read_bytes()); b=deepcopy(a); b["raw_sha256"]="changed"
        with self.assertRaises(ValueError): p.equivalence(a,b)
    def test_path_traversal(self):
        for name in ("../x","/x","a/../x","a\\x","C:/x","","a//x"):
            with self.subTest(name=name),self.assertRaises(ValueError): p.relative(name)
    def test_source_blob_mutation(self):
        target=self.root / "reconstructed"; pins=p.reconstruct(self.repo,self.producer,target)
        (target / "src/sample.py").write_text("MUTATED=1")
        sandbox=p.SourceSandbox({str(self.primary):str(target)},{str(self.primary):pins},str(self.primary))
        spec=sandbox.spec_from_file_location("probe",self.primary / "src/sample.py")
        with self.assertRaisesRegex(ValueError,"SOURCE_BLOB_MISMATCH"): spec.loader.exec_module(__import__("types").ModuleType("probe"))
    def test_current_source_substitution(self):
        target=self.root / "new"; pins=p.reconstruct(self.repo,self.main,target)
        binding=deepcopy(self.binding)
        cfg=p.read(self.cfg.read_bytes()); cfg["main_code_pins"]=pins
        self.cfg.write_bytes(p.canonical(cfg)); binding["evidence_pins"]["configuration"]=self.pin(self.cfg)
        result,_=self.worker("substitution",binding)
        self.assertNotEqual(result.returncode,0)
        self.assertIn(b"SOURCE_BLOB_MISMATCH",result.stderr)
    def test_shared_ref_write_attempt(self):
        resolver=p.GitResolver({str(self.primary):str(self.repo)})
        with self.assertRaisesRegex(ValueError,"SHARED_REF_MUTATION"): resolver.run(["git","update-ref","refs/remotes/origin/main",self.producer],cwd=self.primary)
    def test_network_attempt(self):
        guard=p.ReadOnlyRuntime(self.root / "result.json",[self.repo])
        for event,args in (("socket.connect",()),("urllib.Request",("https://example.invalid",))):
            with self.subTest(event=event),self.assertRaisesRegex(ValueError,"NETWORK_FORBIDDEN"): guard(event,args)
    def test_non_git_process_rejected(self):
        with self.assertRaises(ValueError): p.GitResolver({}).run(["curl","example.invalid"],cwd=self.repo)
    def test_protected_write_rejected(self):
        guard=p.ReadOnlyRuntime(self.root / "result.json",[self.repo])
        with self.assertRaisesRegex(ValueError,"WRITE_FORBIDDEN"): guard("open",(str(self.cfg),"w",os.O_WRONLY))
    def test_output_overwrite_rejected(self):
        result,_=self.worker("repeat")
        self.assertEqual(result.returncode,0,result.stderr.decode())
        path=self.root / "repeat.json"
        result=subprocess.run([sys.executable,"-B",str(ROOT / "scripts/run_historical_replay_portability.py"),"--binding",str(path),
            "--binding-sha256",p.sha(path.read_bytes()),"--output",str(self.root / "repeat")],capture_output=True,env=p.clean_env())
        self.assertNotEqual(result.returncode,0)
    def test_no_authority_or_production_promotion(self):
        contract=p.read((ROOT / "docs/contracts/RATE_HISTORICAL_REPLAY_PORTABILITY_V1.json").read_bytes())
        self.assertFalse(contract["isolated_git_view_grants_authority"])
        self.assertFalse(contract["production_eligible"])
        self.assertFalse(contract["first_refresh_authorized"])
        self.assertEqual(contract["historical_pit"],"UNPROVEN")


if __name__ == "__main__": unittest.main()
