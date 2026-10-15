"""SYNTHETIC ONLY. No real acceptance, activation or campaign writes."""
from copy import deepcopy
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from src.prospective_acquisition_recovery import offline_network_guard
sys.addaudithook(offline_network_guard)
from src import history_acceptance_sidecar as s
from tests.test_history_chunked_acquisition import approval, authorized
from tests.test_history_acquisition_wiring import universe, payload, Clock

h, c = s.h, s.chunks


def identified(core, kind):
    return h.evidence.identified(core, "rate-history-acceptance-" + kind + "-", kind + "_id", kind + "_sha256")


class SidecarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source_tmp = tempfile.TemporaryDirectory(prefix="as-")
        cls.addClassCleanup(cls.source_tmp.cleanup)
        cls.campaign = Path(cls.source_tmp.name) / "campaign"
        cls.u = universe()
        symbols = sorted(row["symbol"] for row in cls.u["stocks"] if row["market"] == "TWSE")[:11]
        cls.scope = c.stock_scope("a" * 40, cls.u,
            [{"market": "TWSE", "symbol": symbol, "period": "202609"} for symbol in symbols],
            {"TWSE": "2026-10-12", "TPEX": "2026-10-13"}, "TWSE", "b" * 64, synthetic=True)
        cls.approval = approval(cls.scope)
        cls.manifest = c.build_manifest(cls.scope, cls.approval,
            trusted_approval_sha256=cls.approval["approval_sha256"], main_sha="a" * 40, universe=cls.u, synthetic=True)
        cls.bundles, cls.auths, cls.results = [], [], []
        for chunk in cls.manifest["chunks"]:
            bundle = c.materials(cls.manifest, cls.scope, cls.approval,
                trusted_approval_sha256=cls.approval["approval_sha256"], main_sha="a" * 40, universe=cls.u,
                chunk_id=chunk["chunk_id"], campaign_root=cls.campaign, synthetic=True)
            auth, clock = authorized(bundle), Clock()
            def capture(entry):
                return {"raw_bytes": h.evidence.canonical(payload(entry)), "http_status": 200,
                        "final_url": entry["request_url"], "content_type": "application/json"}
            result = h.execute(bundle["plan"], bundle["seal"], auth,
                artifacts_root=bundle["artifacts_root"], consumption_root=bundle["consumption_root"],
                output_root=bundle["execution_root"], trusted_authorization_sha256=auth["authorization_sha256"],
                synthetic=True, transport=capture, utc=lambda: "2026-10-14T00:00:00Z",
                monotonic=clock.now, sleep=clock.sleep)
            assert result["status"] == "PASS"
            cls.bundles.append(bundle); cls.auths.append(auth); cls.results.append(result)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="ag-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.ctx = self.context(self.root / "governance")
        self.records = []
        for ordinal, (bundle, auth, result) in enumerate(zip(self.bundles, self.auths, self.results), 1):
            run = Path(bundle["execution_root"])
            claim = Path(bundle["consumption_root"]) / (auth["authorization_id"] + ".json")
            record = identified({"artifact_kind": "RATE_HISTORY_CHUNK_CONTROL_CENTER_ACCEPTANCE_V1",
                "contract": s.CONTRACT, "issuer": "CONTROL_CENTER", "decision": "CHUNK_ACCEPTED",
                **self.ctx["binding"], "chunk_ordinal": ordinal, "chunk_id": bundle["chunk_id"],
                "plan_sha256": bundle["plan"]["plan_sha256"], "seal_sha256": bundle["seal"]["seal_sha256"],
                "authorization_id": auth["authorization_id"], "authorization_sha256": auth["authorization_sha256"],
                "result_sha256": h.evidence.sha((run / "RESULT.json").read_bytes()), "ledger_head": result["ledger_head"],
                "consumption_sha256": h.evidence.sha(claim.read_bytes()), "request_count": result["actual_requests"],
                "execution_evidence_inventory_sha256": h.evidence.sha(s.snapshot(Path(bundle["execution_root"]).parent.parent)),
                "accepted_at": "2026-10-15T00:00:00Z"}, "record")
            # Record identity has the production field names; its scope remains SYNTHETIC_ONLY.
            core = {k: v for k, v in record.items() if k not in {"record_id", "record_sha256"}}
            record = h.evidence.identified(core, "rate-history-acceptance-record-", "acceptance_id", "acceptance_sha256")
            path = self.root / f"record{ordinal}.json"
            path.write_bytes(h.evidence.canonical(record))
            self.records.append(path)
        self.pins = {h.evidence.sha(path.read_bytes()): str(path) for path in self.records}
        self.genesis = self.root / "genesis.json"
        self.genesis.write_bytes(h.evidence.canonical(identified({
            "artifact_kind": "RATE_HISTORY_ACCEPTANCE_GENESIS_V1", "contract": s.CONTRACT,
            "issuer": "CONTROL_CENTER", **self.ctx["binding"], "first_chunk_ordinal": 1,
            "first_acceptance_file_sha256": h.evidence.sha(self.records[0].read_bytes()),
            "prior_accepted_chunks": 0, "prior_accepted_requests": 0}, "genesis")))
        self.genesis_sha = h.evidence.sha(self.genesis.read_bytes())
        self.activation = self.root / "activation.json"
        self.permit = {"artifact_kind": "RATE_HISTORY_ACCEPTANCE_SIDECAR_ACTIVATION_V1", "contract": s.CONTRACT,
            "issuer": "CONTROL_CENTER", "status": "SIDECAR_LEDGER_BOOTSTRAP_AUTHORIZED", **self.ctx["binding"],
            "sidecar_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=h.ROOT).decode().strip(),
            "sidecar_owner_sha256_lf": s.owners(), "genesis_file_sha256": self.genesis_sha, "maximum_chunk_ordinal": 2}
        self.activation.write_bytes(h.evidence.canonical(self.permit))

    def context(self, root, **kwargs):
        return s.context(self.manifest, self.scope, self.approval, self.u,
            trusted_approval_sha256=self.approval["approval_sha256"],
            trusted_manifest_sha256=kwargs.pop("trusted_manifest_sha256", self.manifest["manifest_sha256"]),
            campaign_root=kwargs.pop("campaign_root", self.campaign), ledger_root=root,
            synthetic=kwargs.pop("synthetic", True), **kwargs)

    def append(self, n=0, head=None, **kwargs):
        return s.append_acceptance(self.ctx, record_path=self.records[n],
            trusted_record_sha256=kwargs.pop("record_pin", h.evidence.sha(self.records[n].read_bytes())),
            genesis_path=kwargs.pop("genesis_path", self.genesis),
            trusted_genesis_sha256=kwargs.pop("genesis_pin", self.genesis_sha), trusted_records=self.pins,
            expected_head=head, activation_path=kwargs.pop("activation_path", self.activation),
            trusted_activation_sha256=kwargs.pop("activation_pin", h.evidence.sha(self.activation.read_bytes())), **kwargs)

    def replay(self, head, **kwargs):
        return s.replay(self.ctx, genesis_path=self.genesis, trusted_genesis_sha256=self.genesis_sha,
                        trusted_records=kwargs.pop("trusted_records", self.pins), expected_head=head, **kwargs)

    def test_two_chunks_derive_progress_from_events(self):
        first = self.append()
        second = self.append(1, first["head"])
        self.assertEqual((second["accepted_chunks"], second["accepted_requests"]), (2, 11))
        self.assertEqual((second["total_chunks"], second["total_requests"]), (2, 11))
        self.assertEqual(second["events"][1]["previous_event_sha256"], first["head"])

    def test_same_record_is_idempotent_noop(self):
        first = self.append()
        before = s.snapshot(self.ctx["ledger_root"])
        again = self.append(head=first["head"])
        self.assertTrue(again["idempotent_noop"])
        self.assertEqual(s.snapshot(self.ctx["ledger_root"]), before)

    def test_conflicting_record_halts_without_credit(self):
        first = self.append()
        before = s.snapshot(self.ctx["ledger_root"])
        value = s.load(self.records[0]); value["accepted_at"] = "2026-10-15T00:01:00Z"
        new_path = self.root / "conflicting_record.json"
        self.reidentify_record(value, new_path)
        self.records[0] = new_path
        with self.assertRaisesRegex(ValueError, "ACCEPTANCE_CONFLICT_HALT"):
            self.append(head=first["head"])
        after = s.snapshot(self.ctx["ledger_root"])
        self.assertEqual({k: after[k] for k in before}, before)
        self.assertEqual(set(after) - set(before), {"HALTED.json"})
        with self.assertRaisesRegex(ValueError, "LEDGER_HALTED"):
            self.append(1, first["head"])
        self.assertEqual(s.snapshot(self.ctx["ledger_root"]), after)

    def reidentify_record(self, value, path):
        core = {k: v for k, v in value.items() if k not in {"acceptance_id", "acceptance_sha256"}}
        path.write_bytes(h.evidence.canonical(h.evidence.identified(core,
            "rate-history-acceptance-record-", "acceptance_id", "acceptance_sha256")))

    def test_genesis_absence_fails_before_root_creation(self):
        with self.assertRaises(FileNotFoundError):
            self.append(genesis_path=self.root / "missing.json")
        self.assertFalse(Path(self.ctx["ledger_root"]).exists())

    def test_activation_absence_fails_before_root_creation(self):
        with self.assertRaises(FileNotFoundError):
            self.append(activation_path=self.root / "missing.json")
        self.assertFalse(Path(self.ctx["ledger_root"]).exists())

    def test_external_record_pin_required(self):
        with self.assertRaisesRegex(ValueError, "EXTERNAL_TRUST_PIN"):
            self.append(record_pin="0" * 64)
        self.assertFalse(Path(self.ctx["ledger_root"]).exists())

    def test_external_genesis_pin_required(self):
        with self.assertRaisesRegex(ValueError, "EXTERNAL_TRUST_PIN"):
            self.append(genesis_pin="0" * 64)
        self.assertFalse(Path(self.ctx["ledger_root"]).exists())

    def test_external_activation_pin_required(self):
        with self.assertRaisesRegex(ValueError, "EXTERNAL_TRUST_PIN"):
            self.append(activation_pin="0" * 64)
        self.assertFalse(Path(self.ctx["ledger_root"]).exists())

    def test_chunk2_cannot_bootstrap_chunk1_credit(self):
        with self.assertRaisesRegex(ValueError, "NEXT_CHUNK"):
            self.append(1)
        self.assertFalse((Path(self.ctx["ledger_root"]) / "events").exists())

    def test_manifest_external_pin_required(self):
        with self.assertRaisesRegex(ValueError, "MANIFEST_TRUST"):
            self.context(self.root / "ledger2", trusted_manifest_sha256="0" * 64)

    def test_overlapping_roots_rejected(self):
        with self.assertRaisesRegex(ValueError, "ROOT_OVERLAP"):
            self.context(self.campaign / "ledger")

    def test_real_root_cannot_be_arbitrary_engineering_directory(self):
        with self.assertRaisesRegex(ValueError, "FROZEN_CAMPAIGN_ROOT"):
            self.context(self.root / "ledger2", synthetic=False)

    def test_originals_byte_identical_after_append(self):
        before = s.snapshot(self.campaign)
        first = self.append(); self.append(1, first["head"])
        self.assertEqual(s.snapshot(self.campaign), before)

    def test_fresh_interpreter_and_network_denial_proof(self):
        proof = s.verify_chunk(self.ctx, 1)["cold_replay"]
        self.assertNotEqual(proof["pid"], os.getpid())
        self.assertEqual(proof["parent_pid"], os.getpid())
        self.assertTrue(proof["isolated"] and proof["guard_installed_before_owner_import"])
        self.assertEqual(proof["network_attempts"], 0)

    def test_independent_ledger_cold_read(self):
        first = self.append(); second = self.append(1, first["head"])
        binding = self.root / "cold.json"
        binding.write_bytes(h.evidence.canonical({"ctx": self.ctx, "genesis_path": str(self.genesis),
            "trusted_genesis_sha256": self.genesis_sha, "trusted_records": self.pins, "expected_head": second["head"]}))
        code = """import sys
sys.path.insert(0,sys.argv[1])
from src.prospective_acquisition_recovery import offline_network_guard
sys.addaudithook(offline_network_guard)
from src import history_acceptance_sidecar as s
b=s.load(sys.argv[2]); ctx=b.pop('ctx')
r=s.replay(ctx,**b)
assert r['status']=='PASS' and r['accepted_requests']==11
print(r['head'])
"""
        child = subprocess.run([sys.executable, "-I", "-B", "-c", code, str(h.ROOT), str(binding)], capture_output=True)
        self.assertEqual(child.returncode, 0, child.stderr)
        self.assertEqual(child.stdout.decode().strip(), second["head"])

    def test_network_attempt_is_denied(self):
        code = """import runpy,sys,socket
n=runpy.run_path(sys.argv[1],run_name='probe')
try: socket.getaddrinfo('example.invalid',443)
except RuntimeError as e: assert str(e)=='RECOVERY_NETWORK_FORBIDDEN'
else: raise AssertionError('NETWORK_ALLOWED')
assert n['network_guard'].__globals__['network_attempts']==1
"""
        child = subprocess.run([sys.executable, "-I", "-B", "-c", code,
            str(h.ROOT / "scripts/run_history_acceptance_sidecar.py")], capture_output=True)
        self.assertEqual(child.returncode, 0, child.stderr)

    def test_os_writer_lock_excludes_second_process(self):
        root = Path(self.ctx["ledger_root"]); root.mkdir()
        code = """import sys
sys.path.insert(0,sys.argv[1])
from src.provider_eps_dispatch import exclusive_scan
try:
 with exclusive_scan(sys.argv[2]): pass
except RuntimeError as e: assert str(e)=='COVERAGE_WRITER_ALREADY_ACTIVE'
else: raise AssertionError('SECOND_WRITER_ALLOWED')
"""
        with h.exclusive_scan(root):
            child = subprocess.run([sys.executable, "-I", "-B", "-c", code, str(h.ROOT), str(root)], capture_output=True)
        self.assertEqual(child.returncode, 0, child.stderr)

    def test_two_concurrent_appenders_cannot_duplicate_credit(self):
        data = self.root / "concurrent.json"
        data.write_bytes(h.evidence.canonical({"ctx": self.ctx, "record_path": str(self.records[0]),
            "trusted_record_sha256": h.evidence.sha(self.records[0].read_bytes()),
            "genesis_path": str(self.genesis), "trusted_genesis_sha256": self.genesis_sha,
            "trusted_records": self.pins, "expected_head": None, "activation_path": str(self.activation),
            "trusted_activation_sha256": h.evidence.sha(self.activation.read_bytes())}))
        code = """import sys
sys.path.insert(0,sys.argv[1])
from src.prospective_acquisition_recovery import offline_network_guard
sys.addaudithook(offline_network_guard)
from src import history_acceptance_sidecar as s
b=s.load(sys.argv[2]); ctx=b.pop('ctx')
print(s.append_acceptance(ctx,**b)['head'])
"""
        command = [sys.executable, "-I", "-B", "-c", code, str(h.ROOT), str(data)]
        children = [subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(2)]
        outputs = [child.communicate(timeout=90) for child in children]
        self.assertEqual(sorted(child.returncode == 0 for child in children), [False, True], outputs)
        winner = next(out for child, (out, _) in zip(children, outputs) if child.returncode == 0)
        result = self.replay(winner.decode().strip())
        self.assertEqual((result['accepted_chunks'], result['accepted_requests']), (1, 10))

    def test_stale_head_rejected(self):
        self.append()
        with self.assertRaisesRegex(ValueError, "TRUNCATED_OR_STALE_HEAD"):
            self.replay("0" * 64)

    def test_tail_truncation_rejected(self):
        first = self.append(); second = self.append(1, first["head"])
        root = Path(self.ctx["ledger_root"])
        for directory in ("events", "intents", "checkpoints"):
            (root / directory / "000002.json").unlink()
        (root / "records" / (h.evidence.sha(self.records[1].read_bytes()) + ".json")).unlink()
        with self.assertRaisesRegex(ValueError, "TRUNCATED_OR_STALE_HEAD"):
            self.replay(second["head"])

    def test_prior_record_pin_cannot_be_self_derived_from_ledger(self):
        first = self.append()
        with self.assertRaisesRegex(ValueError, "EXTERNAL_PIN_REQUIRED"):
            self.replay(first["head"], trusted_records={})

    def test_no_progress_pointer_or_production_effect(self):
        self.append()
        root = Path(self.ctx["ledger_root"])
        self.assertEqual({p.name for p in root.iterdir()}, {".scan.lock", "genesis.json", "records", "events", "intents", "checkpoints"})
        contract = s.load(h.ROOT / "docs/contracts/RATE_HISTORY_ACCEPTANCE_SIDECAR_V1.json")
        self.assertFalse(contract["bootstrap_authorized"])
        self.assertEqual(contract["governance"]["historical_pit"], "UNPROVEN")
        self.assertFalse(contract["governance"]["calendar_180_ready"])
        self.assertEqual(contract["governance"]["ranking"], "NOT_AUTHORIZED")
        self.assertFalse(contract["governance"]["production_eligible"])

    def test_only_exact_runtime_lock_is_excluded_before_read(self):
        root = Path(self.ctx["ledger_root"]); root.mkdir()
        lock = root / ".scan.lock"; lock.write_bytes(b"0")
        original = Path.read_bytes
        def read(path):
            if path == lock:
                raise PermissionError("SYNTHETIC_HELD_LOCK")
            return original(path)
        with patch.object(Path, "read_bytes", read):
            self.assertEqual(self.replay(None)["status"], "EMPTY")

    def test_nonlock_permission_error_is_not_suppressed(self):
        first = self.append()
        item = Path(self.ctx["ledger_root"]) / "events/000001.json"
        original = Path.read_bytes
        def read(path):
            if path == item:
                raise PermissionError("SYNTHETIC_EVIDENCE_READ_FAILURE")
            return original(path)
        with patch.object(Path, "read_bytes", read):
            with self.assertRaises(PermissionError):
                self.replay(first["head"])

    def test_context_root_drift_rejected_before_creation(self):
        self.ctx["ledger_root"] = str(self.root / "unapproved")
        with self.assertRaisesRegex(ValueError, "CONTEXT_ROOT_DRIFT"):
            self.append()
        self.assertFalse(Path(self.ctx["ledger_root"]).exists())

    def test_boolean_request_count_cannot_impersonate_one(self):
        value = s.load(self.records[1]); value["request_count"] = True
        self.reidentify_record(value, self.records[1])
        with self.assertRaisesRegex(ValueError, "RECORD_INTEGER"):
            self.append(1)
        self.assertFalse(Path(self.ctx["ledger_root"]).exists())

    def test_boolean_genesis_count_rejected(self):
        value = s.load(self.genesis); value["prior_accepted_chunks"] = False
        core = {k: v for k, v in value.items() if k not in {"genesis_id", "genesis_sha256"}}
        self.genesis.write_bytes(h.evidence.canonical(identified(core, "genesis")))
        with self.assertRaisesRegex(ValueError, "GENESIS_INTEGER"):
            self.append(genesis_pin=h.evidence.sha(self.genesis.read_bytes()))
        self.assertFalse(Path(self.ctx["ledger_root"]).exists())

    def test_noncanonical_duplicate_key_rejected(self):
        self.records[0].write_bytes(b'{"chunk_ordinal":1,"chunk_ordinal":1}')
        with self.assertRaises(ValueError):
            s.trusted_file(self.records[0], h.evidence.sha(self.records[0].read_bytes()))

    def test_future_acceptance_timestamp_rejected(self):
        value = s.load(self.records[0]); value["accepted_at"] = "2999-01-01T00:00:00Z"
        self.reidentify_record(value, self.records[0])
        with self.assertRaisesRegex(ValueError, "DECISION_TIME"):
            self.append()

    def test_pre_acquisition_acceptance_timestamp_rejected(self):
        value = s.load(self.records[0]); value["accepted_at"] = "2020-01-01T00:00:00Z"
        self.reidentify_record(value, self.records[0])
        with self.assertRaisesRegex(ValueError, "DECISION_TIME"):
            self.append()

    def test_exclusive_create_never_overwrites(self):
        path = self.root / "object.json"
        s._put(path, b"original")
        with self.assertRaises(FileExistsError):
            s._put(path, b"changed")
        self.assertEqual(path.read_bytes(), b"original")

    def test_genesis_wrong_first_acceptance_is_rejected(self):
        value = s.load(self.genesis)
        value["first_acceptance_file_sha256"] = h.evidence.sha(self.records[1].read_bytes())
        core = {k: v for k, v in value.items() if k not in {"genesis_id", "genesis_sha256"}}
        self.genesis.write_bytes(h.evidence.canonical(identified(core, "genesis")))
        self.genesis_sha = h.evidence.sha(self.genesis.read_bytes())
        self.permit["genesis_file_sha256"] = self.genesis_sha
        self.activation.write_bytes(h.evidence.canonical(self.permit))
        with self.assertRaisesRegex(ValueError, "GENESIS_TRUST"):
            self.append()
        self.assertFalse((Path(self.ctx["ledger_root"]) / "events").exists())

    def test_incomplete_json_append_is_not_repaired(self):
        first = self.append()
        item = Path(self.ctx["ledger_root"]) / "intents/000002.json"
        item.write_bytes(b'{"artifact_kind":')
        before = s.snapshot(self.ctx["ledger_root"])
        with self.assertRaises(ValueError):
            self.append(1, first["head"])
        self.assertEqual(s.snapshot(self.ctx["ledger_root"]), before)


def binding_tamper(field):
    def test(self):
        value = s.load(self.records[0])
        value[field] = "invalid" if type(value[field]) is not int else 999
        self.reidentify_record(value, self.records[0])
        with self.assertRaises((ValueError, FileNotFoundError)):
            self.append()
        self.assertFalse(Path(self.ctx["ledger_root"]).exists())
    return test


for field in ("issuer", "decision", "repository", "frozen_main_sha", "manifest_sha256", "scope_sha256",
              "universe_sha256", "campaign_root_identity", "acceptance_root_identity", "chunk_ordinal", "chunk_id",
              "plan_sha256", "seal_sha256", "authorization_id", "authorization_sha256", "result_sha256",
              "ledger_head", "consumption_sha256", "request_count", "material_scope", "execution_evidence_inventory_sha256"):
    setattr(SidecarTests, "test_record_binding_tamper_" + field, binding_tamper(field))


def ledger_tamper(family):
    def test(self):
        first = self.append()
        root = Path(self.ctx["ledger_root"])
        path = root / "genesis.json" if family == "genesis" else next((root / family).iterdir())
        before_source = s.snapshot(self.campaign)
        path.write_bytes(path.read_bytes() + b" ")
        with self.assertRaises((ValueError, FileNotFoundError)):
            self.replay(first["head"])
        self.assertEqual(s.snapshot(self.campaign), before_source)
    return test


for family in ("genesis", "records", "events", "intents", "checkpoints"):
    setattr(SidecarTests, "test_ledger_tamper_" + family, ledger_tamper(family))


def original_tamper(family):
    def test(self):
        bundle = self.bundles[0]
        run = Path(bundle["execution_root"])
        path = (next(Path(bundle["consumption_root"]).glob("*.json")) if family == "consumption" else
                run / family if family.endswith(".json") else next((run / family).iterdir()))
        body = path.read_bytes()
        self.addCleanup(path.write_bytes, body)
        path.write_bytes(body + b" ")
        with self.assertRaises((ValueError, FileNotFoundError)):
            self.append()
        self.assertFalse(Path(self.ctx["ledger_root"]).exists())
    return test


for family in ("raw", "receipts", "events", "checkpoints", "RESULT.json", "consumption"):
    setattr(SidecarTests, "test_original_tamper_" + family.replace(".", "_"), original_tamper(family))


def crash_after(n):
    def test(self):
        original, calls = s._put, []
        def fail(path, body):
            original(path, body); calls.append(path)
            if len(calls) == n:
                raise RuntimeError("SYNTHETIC_CRASH")
        with patch.object(s, "_put", side_effect=fail):
            with self.assertRaisesRegex(RuntimeError, "SYNTHETIC_CRASH"):
                self.append()
        after = s.snapshot(self.ctx["ledger_root"])
        with self.assertRaises((ValueError, FileNotFoundError)):
            self.replay(None)
        self.assertEqual(s.snapshot(self.ctx["ledger_root"]), after)
        with self.assertRaises((ValueError, FileNotFoundError)):
            self.append()
        self.assertEqual(s.snapshot(self.ctx["ledger_root"]), after)
    return test


for n in range(1, 5):
    setattr(SidecarTests, f"test_crash_after_write_{n}_halts_preserves_files", crash_after(n))


def activation_tamper(field):
    def test(self):
        self.permit[field] = "invalid" if type(self.permit[field]) is not int else 0
        self.activation.write_bytes(h.evidence.canonical(self.permit))
        with self.assertRaises(ValueError):
            self.append()
        self.assertFalse(Path(self.ctx["ledger_root"]).exists())
    return test


for field in ("sidecar_head", "sidecar_owner_sha256_lf", "genesis_file_sha256", "maximum_chunk_ordinal", "status"):
    setattr(SidecarTests, "test_activation_tamper_" + field, activation_tamper(field))


if __name__ == "__main__":
    unittest.main()
