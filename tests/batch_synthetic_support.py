"""SYNTHETIC ONLY. Ephemeral control key; real owners use only fake transport."""
import base64
from pathlib import Path
import subprocess
import tempfile
from uuid import uuid4

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from src import history_batch_authority as a
from src.history_batch_launcher import IssuerClient
from src.history_batch_orchestration import Orchestrator
from tests.test_history_acquisition_wiring import universe, payload, Clock
from tests.test_history_chunked_acquisition import approval, authorized

AT = "2026-10-15T00:01:00Z"


class Fixture:
    def __init__(self, window=1):
        self.temporary = tempfile.TemporaryDirectory(prefix="SYNTHETIC-batch-")
        self.base = Path(self.temporary.name)
        self.clock, self.calls = Clock(), 0
        self.u = universe()
        symbols = sorted(r["symbol"] for r in self.u["stocks"] if r["market"] == "TWSE")[:window * 10 + 1]
        self.scope = a.chunks.stock_scope(a.FROZEN_MAIN, self.u,
            [{"market": "TWSE", "symbol": symbol, "period": "202609"} for symbol in symbols],
            {"TWSE": "2026-10-12", "TPEX": "2026-10-13"}, "TWSE", "b" * 64, synthetic=True)
        self.approval = approval(self.scope)
        self.manifest = a.chunks.build_manifest(self.scope, self.approval,
            trusted_approval_sha256=self.approval["approval_sha256"], main_sha=a.FROZEN_MAIN, universe=self.u, synthetic=True)
        self.campaign, self.ledger = self.base / "campaign", self.base / "governance"
        self.ctx = a.sidecar.context(self.manifest, self.scope, self.approval, self.u,
            trusted_approval_sha256=self.approval["approval_sha256"], trusted_manifest_sha256=self.manifest["manifest_sha256"],
            campaign_root=self.campaign, ledger_root=self.ledger, synthetic=True)
        self.ctx.update(scope=self.scope, approval=self.approval, universe=self.u)
        first = self.bundle(1)
        auth = authorized(first)
        result = a.h.execute(first["plan"], first["seal"], auth, artifacts_root=first["artifacts_root"],
            consumption_root=first["consumption_root"], output_root=first["execution_root"],
            trusted_authorization_sha256=auth["authorization_sha256"], synthetic=True, transport=self.capture,
            utc=self.utc, monotonic=self.clock.now, sleep=self.clock.sleep)
        assert result["status"] == "PASS"
        proof = a.sidecar.verify_chunk(self.ctx, 1)
        record = a.e.identified({"artifact_kind": "RATE_HISTORY_CHUNK_CONTROL_CENTER_ACCEPTANCE_V1", "contract": a.sidecar.CONTRACT,
            "issuer": "CONTROL_CENTER", "decision": "CHUNK_ACCEPTED", **proof["binding"], "accepted_at": AT},
            "rate-history-acceptance-record-", "acceptance_id", "acceptance_sha256")
        self.record1 = self.base / "control" / "record1.json"; a.put(self.record1, record)
        self.records = {a.e.sha(record): str(self.record1)}
        genesis = a.e.identified({"artifact_kind": "RATE_HISTORY_ACCEPTANCE_GENESIS_V1", "contract": a.sidecar.CONTRACT,
            "issuer": "CONTROL_CENTER", **self.ctx["binding"], "first_chunk_ordinal": 1,
            "first_acceptance_file_sha256": a.e.sha(record), "prior_accepted_chunks": 0, "prior_accepted_requests": 0},
            "rate-history-acceptance-genesis-", "genesis_id", "genesis_sha256")
        self.genesis = self.base / "control" / "genesis.json"; a.put(self.genesis, genesis)
        self.activation = self.base / "control" / "activation.json"
        permit = {"artifact_kind": "RATE_HISTORY_ACCEPTANCE_SIDECAR_ACTIVATION_V1", "contract": a.sidecar.CONTRACT,
            "issuer": "CONTROL_CENTER", "status": "SIDECAR_LEDGER_BOOTSTRAP_AUTHORIZED", **self.ctx["binding"],
            "sidecar_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=a.h.ROOT).decode().strip(),
            "sidecar_owner_sha256_lf": a.sidecar.owners(), "genesis_file_sha256": a.e.sha(genesis), "maximum_chunk_ordinal": window + 1}
        a.put(self.activation, permit)
        self.ctx.update(genesis_path=str(self.genesis), activation_path=str(self.activation))
        initial = a.sidecar.append_acceptance(self.ctx, record_path=self.record1, trusted_record_sha256=a.e.sha(record),
            genesis_path=self.genesis, trusted_genesis_sha256=a.e.sha(genesis), trusted_records=self.records, expected_head=None,
            activation_path=self.activation, trusted_activation_sha256=a.e.sha(permit))
        self.client = IssuerClient(self.base)
        # Control authority is test-only and independent of the issuer worker key.
        self.control_key = Ed25519PrivateKey.generate()
        self.registry = {"material_scope": a.SCOPE, "issuer_root_identity": a.e.root_identity(self.base / "issuer"),
            "witness_root_identity": a.e.root_identity(self.base / "witness"), "keys": {
                "control": {"epoch": 1, "public_key": base64.b64encode(self.control_key.public_key().public_bytes_raw()).decode(),
                    "purposes": ["POLICY"], "revoked": False},
                "issuer": {"epoch": 1, "public_key": self.client.public["issuer_public_key"],
                    "purposes": ["AUTHORIZATION", "ACCEPTANCE", "HEAD_ACK", "REVOCATION"], "revoked": False},
                "witness": {"epoch": 1, "public_key": self.client.public["witness_public_key"], "purposes": ["WITNESS"], "revoked": False}}}
        # This immutable pin originates in the synthetic external control fixture, not in the runner.
        self.registry_path = self.base / "control" / "public-registry.json"
        a.put(self.registry_path, self.registry)
        self.registry_pin = a.e.sha(self.registry_path.read_bytes())
        selected = self.manifest["chunks"][1:]
        self.policy = {"artifact_kind": "RATE_BATCH_POLICY_V1", "contract": a.CONTRACT, "material_scope": a.SCOPE,
            "engineering_cr_sha256": a.CR_SHA256, "nonce": "TEST_ONLY_" + uuid4().hex, "approved": True,
            "main_sha": a.FROZEN_MAIN, "sidecar_head": a.SIDECAR_HEAD, "execution_owner_sha256_lf": a.h.owners(),
            "sidecar_owner_sha256_lf": a.sidecar.owners(), "binding": self.ctx["binding"],
            "engineering_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=a.h.ROOT).decode().strip(),
            "engineering_owner_sha256_lf": a.engineering_owners(),
            "ordinals": list(range(2, window + 2)), "chunk_ids": [c["chunk_id"] for c in selected],
            "per_chunk_requests": [c["request_count"] for c in selected], "maximum_requests": sum(c["request_count"] for c in selected),
            "start_head": initial["head"], "start_ordinal": 1, "genesis_file_sha256": a.e.sha(genesis),
            "activation_file_sha256": a.e.sha(permit), "initial_record_pins": self.records,
            "not_before": "2026-10-14T00:00:00Z", "not_after": "2099-01-01T00:00:00Z",
            "delegations": ["AUTHORIZATION", "ACCEPTANCE", "HEAD_ACK"],
            "runtime": {"sequential": True, "single_writer": True, "timeout": 30, "interval": 13,
                "retry": 0, "redirect": False, "fallback": False, "auto_resume": False, "live_execution": False},
            "roots": {"sandbox": str(self.base), **{name: str(self.base / name) for name in ("issuer", "witness", "runner", "campaign")},
                      "ledger": str(self.ledger)}}
        self.calls = 0

    @staticmethod
    def utc():
        return "2026-10-14T00:00:00Z"

    def capture(self, entry):
        self.calls += 1
        return {"raw_bytes": a.e.canonical(payload(entry)), "http_status": 200,
                "final_url": entry["request_url"], "content_type": "application/json"}

    def bundle(self, ordinal):
        return a.chunks.materials(self.manifest, self.scope, self.approval,
            trusted_approval_sha256=self.approval["approval_sha256"], main_sha=a.FROZEN_MAIN, universe=self.u,
            chunk_id=self.manifest["chunks"][ordinal - 1]["chunk_id"], campaign_root=self.campaign, synthetic=True)

    def start(self, *, synthetic_fault_stage=None):
        policy_envelope = a.envelope(a.release_core(a.e.canonical(self.policy), key_id="control", purpose="POLICY",
            policy_sha256=a.e.sha(self.policy), sequence=1, previous_head=None, nonce=self.policy["nonce"]), self.control_key.sign)
        self.client.initialize(self.policy, self.ctx, self.registry, policy_envelope, at=AT,
                               trusted_registry_sha256=self.registry_pin, synthetic_fault_stage=synthetic_fault_stage)
        self.runner = Orchestrator(self.policy, self.ctx, self.registry, self.client, at=AT,
                                  trusted_registry_sha256=self.registry_pin)
        return self.runner

    def run(self, **kwargs):
        return self.runner.run(transport=kwargs.pop("transport", self.capture), utc=self.utc, monotonic=self.clock.now,
            sleep=self.clock.sleep, at=lambda: AT, **kwargs)

    def close(self):
        if hasattr(self, "client"):
            self.client.close()
        self.temporary.cleanup()
