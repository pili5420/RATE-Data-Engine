"""Sequential synthetic owner integration. Never activates real batch execution."""
from pathlib import Path
import subprocess
import sys

from . import history_batch_authority as a


def cold_acceptance(ctx, policy, record_paths, head, output):
    binding = {"ctx": ctx, "genesis_path": ctx["genesis_path"], "genesis_sha256": policy["genesis_file_sha256"],
        "record_paths": record_paths, "head": head,
        "source_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=a.h.ROOT).decode().strip(),
        "source_owner_sha256_lf": {**a.h.owners(), **a.sidecar.owners()}}
    command = [sys.executable, "-I", "-B", str(a.h.ROOT / "scripts/history_batch_cold_acceptance.py")]
    child = subprocess.run(command, input=a.e.canonical(binding), capture_output=True, cwd=a.h.ROOT, timeout=300)
    a.require(child.returncode == 0, "BATCH_COLD_ACCEPTANCE_CHILD_FAILED:" + child.stderr.decode(errors="replace"))
    proof = a.read_metadata(child.stdout)
    a.require(proof["status"] == "PASS" and proof["head"] == head and proof["pid"] != __import__("os").getpid()
        and proof["parent_pid"] == __import__("os").getpid() and proof["isolated"] and proof["network_attempts"] == 0
        and proof["source_head"] == binding["source_head"] and proof["source_owner_sha256_lf"] == binding["source_owner_sha256_lf"],
        "BATCH_COLD_ACCEPTANCE_BINDING_MISMATCH")
    a.put(output, {"command": command, "exit_code": child.returncode, "proof": proof})
    return proof


class Orchestrator:
    def __init__(self, policy, ctx, registry, client, *, at):
        a.validate_policy(policy, ctx, at=at)
        self.policy, self.ctx, self.registry, self.client = policy, ctx, registry, client
        self.root = a.child_root(policy["roots"]["runner"], policy["roots"]["sandbox"])
        self.root.mkdir(parents=True, exist_ok=True)
        self.journal = a.Journal(self.root, policy["roots"]["sandbox"])
        a.require(not self.journal.replay(None), "BATCH_ORCHESTRATOR_RESUME_FORBIDDEN")
        self.head = self.issuer_head = self.witness_head = None
        self.accepted_head = policy["start_head"]
        self.records = dict(policy["initial_record_pins"])
        self.completed, self.halted = [], False

    def packet(self, value, purpose):
        self.issuer_head, self.witness_head = a.verify_packet(value, policy=self.policy, registry=self.registry,
            registry_pin=a.e.sha(self.registry), purpose=purpose, previous_issuer_head=self.issuer_head,
            previous_witness_head=self.witness_head)
        return value["artifact"]

    def step(self, ordinal, stage, proof):
        self.head = self.journal.append({"ordinal": ordinal, "stage": stage, "proof": proof}, self.head)

    def run(self, *, transport, utc, monotonic, sleep, at, fault=lambda stage, ordinal: None):
        a.require(not self.halted and not self.completed, "BATCH_ORCHESTRATOR_NO_RETRY_OR_RESUME")
        # Different lock from every acquisition/campaign/Sidecar owner lock.
        lock_root = a.child_root(Path(self.policy["roots"]["sandbox"]) / "orchestrator-lock", self.policy["roots"]["sandbox"])
        lock_root.mkdir(exist_ok=True)
        try:
            with a.h.exclusive_scan(lock_root):
                for ordinal in self.policy["ordinals"]:
                    a.validate_policy(self.policy, self.ctx, at=at())
                    fault("before_release", ordinal)
                    released = self.client.call("AUTHORIZE", ordinal=ordinal, predecessor_head=self.accepted_head, at=at())
                    auth = self.packet(released, "AUTHORIZATION")
                    chunk = self.ctx["manifest"]["chunks"][ordinal - 1]
                    bundle = a.chunks.materials(self.ctx["manifest"], self.ctx["scope"], self.ctx["approval"],
                        trusted_approval_sha256=self.ctx["approval"]["approval_sha256"], main_sha=self.ctx["manifest"]["main_sha"],
                        universe=self.ctx["universe"], chunk_id=chunk["chunk_id"], campaign_root=self.ctx["campaign_root"], synthetic=True)
                    a.h.validate_authorization(auth, bundle["seal"])
                    self.step(ordinal, "RELEASE_VERIFIED", {"authorization_sha256": auth["authorization_sha256"],
                        "authorization_file_sha256": a.e.sha(auth), "issuer_head": self.issuer_head})
                    fault("before_claim", ordinal)
                    self.step(ordinal, "PRECLAIM_BINDING_PASS", {"authorization_file_sha256": a.e.sha(auth)})
                    result = a.chunks.execute_chunk(self.ctx["manifest"], self.ctx["scope"], self.ctx["approval"], bundle, auth,
                        trusted_approval_sha256=self.ctx["approval"]["approval_sha256"], main_sha=self.ctx["manifest"]["main_sha"],
                        universe=self.ctx["universe"], trusted_authorization_sha256=auth["authorization_sha256"],
                        synthetic=True, transport=transport, utc=utc, monotonic=monotonic, sleep=sleep)
                    a.require(result["result"]["status"] == "PASS" and result["orchestration_status"] == "AWAITING_SEPARATE_CHUNK_AUTHORIZATION"
                              and not result["next_chunk_started"], "BATCH_EXECUTION_NOT_PASS")
                    claim_path = Path(bundle["consumption_root"]) / (auth["authorization_id"] + ".json")
                    claim = a.load(claim_path)
                    a.require(claim["status"] == "CONSUMED" and claim["authorization_sha256"] == auth["authorization_sha256"],
                              "BATCH_ORIGINAL_OWNER_CLAIM_MISMATCH")
                    self.step(ordinal, "CLAIM_SOURCE_VERIFIED", {"file_sha256": a.e.sha(claim_path.read_bytes()),
                        "consumed_at": claim["consumed_at"], "owner": "history_acquisition_execution.execute"})
                    self.step(ordinal, "EXECUTION_PASS", {"ledger_head": result["result"]["ledger_head"]})
                    fault("after_execution", ordinal)
                    replay = a.sidecar.verify_chunk(self.ctx, ordinal)
                    self.step(ordinal, "COLD_REPLAY_PASS", replay["cold_replay"])
                    fault("after_cold", ordinal)
                    accepted = self.client.call("ACCEPT", ordinal=ordinal, at=at())
                    record = self.packet(accepted, "ACCEPTANCE")
                    a.require(record["chunk_ordinal"] == ordinal and
                        all(record[k] == v for k, v in replay["binding"].items()), "BATCH_ACCEPTANCE_BINDING_MISMATCH")
                    # Copies stay outside the immutable runner journal and outside the acceptance ledger.
                    record_dir = a.child_root(Path(self.policy["roots"]["sandbox"]) / "signed-record-copies", self.policy["roots"]["sandbox"])
                    record_dir.mkdir(exist_ok=True)
                    path = record_dir / (a.e.sha(record) + ".json")
                    a.put(path, record)
                    self.records[a.e.sha(record)] = str(path)
                    self.step(ordinal, "ACCEPTANCE_VERIFIED", {"record_file_sha256": a.e.sha(record)})
                    fault("before_append", ordinal)
                    appended = a.sidecar.append_acceptance(self.ctx, record_path=path, trusted_record_sha256=a.e.sha(record),
                        genesis_path=self.ctx["genesis_path"], trusted_genesis_sha256=self.policy["genesis_file_sha256"],
                        trusted_records=self.records, expected_head=self.accepted_head, activation_path=self.ctx["activation_path"],
                        trusted_activation_sha256=self.policy["activation_file_sha256"])
                    a.require(appended["status"] == "PASS" and not appended["idempotent_noop"], "BATCH_APPEND_NOT_NEW_CREDIT")
                    self.step(ordinal, "APPEND_PASS", {"head": appended["head"]})
                    fault("after_append", ordinal)
                    cold_dir = a.child_root(Path(self.policy["roots"]["sandbox"]) / "cold-proofs", self.policy["roots"]["sandbox"])
                    cold_dir.mkdir(exist_ok=True)
                    cold = cold_acceptance(self.ctx, self.policy, self.records, appended["head"], cold_dir / f"{ordinal:06}.json")
                    fault("before_external_ack", ordinal)
                    ack = self.client.call("ACK", head=appended["head"], genesis_path=self.ctx["genesis_path"],
                        activation_path=self.ctx["activation_path"], record_paths=self.records, at=at())
                    acknowledged = self.packet(ack, "HEAD_ACK")
                    a.require(acknowledged == {"acceptance_head": cold["head"], "ordinal": ordinal}, "BATCH_ACK_HEAD_MISMATCH")
                    self.accepted_head = cold["head"]
                    self.step(ordinal, "EXTERNAL_HEAD_ACK_PASS", acknowledged)
                    self.completed.append(ordinal)
                    fault("after_external_ack", ordinal)
                return {"status": "SYNTHETIC_WINDOW_PASS", "completed_ordinals": self.completed,
                    "acceptance_head": self.accepted_head, "issuer_head": self.issuer_head, "witness_head": self.witness_head,
                    "runner_head": self.head, "real_authorizations": 0, "live_requests": 0, "effective_No_Auto_Next": True}
        except BaseException as exc:
            self.halted = True
            if not (self.root / "HALTED.json").exists():
                a.put(self.root / "HALTED.json", {"status": "HALTED_FOR_CONTROL_CENTER_REVIEW", "completed": self.completed,
                    "last_accepted_head": self.accepted_head, "runner_head": self.head,
                    "error": type(exc).__name__ + ": " + str(exc), "auto_resume": False})
            self.client.close()
            raise
