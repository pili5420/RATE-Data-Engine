"""Engineering-only authority, detached signatures and immutable issuer journals."""
from pathlib import Path
import base64
import os
import re

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from . import history_acceptance_sidecar as sidecar
from .eps_duration_facts.model import require
from .provider_eps_metadata import read_metadata

h, chunks, e = sidecar.h, sidecar.chunks, sidecar.h.evidence
FROZEN_MAIN = sidecar.FROZEN_MAIN
SIDECAR_HEAD = "e3ef25084f17f9073b25555b8c0cf911e1146ec8"
CR_SHA256 = "15ab18a242f509bd5c5257f462afd9690e01deb14615fadb65c2c7d8fb8b909b"
CONTRACT = "RATE_HISTORY_CONTROLLED_BATCH_POLICY_V1"
SCOPE = "SYNTHETIC_ONLY"
DOMAIN = b"RATE_CONTROLLED_BATCH_ED25519_V1\x00"


def load(path):
    raw = e.safe(path).read_bytes()
    value = read_metadata(raw)
    require(raw == e.canonical(value), "BATCH_CANONICAL_JSON_REQUIRED")
    return value


def put(path, value):
    path = e.safe(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(e.canonical(value)); stream.flush(); os.fsync(stream.fileno())
    if os.name != "nt":
        descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    require(load(path) == value, "BATCH_EXCLUSIVE_CREATE_READBACK_FAILED")


def sandbox(path):
    path = Path(os.path.abspath(path))
    require(path.name.startswith("SYNTHETIC-batch-"), "BATCH_SYNTHETIC_SANDBOX_REQUIRED")
    require(not any(path == Path(p) or Path(p) in path.parents for p in (sidecar.CAMPAIGN, sidecar.LEDGER)),
            "BATCH_FORMAL_ROOT_FORBIDDEN")
    path = e.safe(path)
    require(path.is_dir(), "BATCH_SYNTHETIC_SANDBOX_REQUIRED")
    require(not path.is_relative_to(h.ROOT), "BATCH_CHECKOUT_WRITE_FORBIDDEN")
    return path


def child_root(path, base):
    base, path = sandbox(base), Path(os.path.abspath(path))
    require(path != base and path.is_relative_to(base), "BATCH_ROOT_ISOLATION_REQUIRED")
    return e.safe(path)


def decode(raw, length):
    require(type(raw) is str, "BATCH_SIGNATURE_ENCODING_INVALID")
    try:
        value = base64.b64decode(raw, validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError("BATCH_SIGNATURE_ENCODING_INVALID") from exc
    require(len(value) == length and base64.b64encode(value).decode() == raw, "BATCH_SIGNATURE_ENCODING_INVALID")
    return value


def envelope(core, sign):
    require(core["material_scope"] == SCOPE, "BATCH_REAL_SIGNING_NOT_AUTHORIZED")
    return {"core": core, "signature": base64.b64encode(sign(DOMAIN + e.canonical(core))).decode()}


def verify_envelope(value, artifact, *, registry, registry_pin, purpose, policy_sha256,
                    sequence, previous_head, nonce):
    require(e.sha(registry) == registry_pin and registry["material_scope"] == SCOPE, "BATCH_EXTERNAL_KEY_REGISTRY_PIN_REQUIRED")
    require(set(value) == {"core", "signature"}, "BATCH_ENVELOPE_FIELDS_INVALID")
    core = value["core"]
    fields = {"artifact_kind", "algorithm", "material_scope", "key_id", "key_epoch", "purpose", "policy_sha256",
              "artifact_file_sha256", "sequence", "previous_head", "nonce"}
    require(set(core) == fields and core["artifact_kind"] == "RATE_BATCH_DETACHED_ENVELOPE_V1"
            and core["algorithm"] == "Ed25519" and core["material_scope"] == SCOPE, "BATCH_ENVELOPE_FIELDS_INVALID")
    require(type(core["sequence"]) is int and core["sequence"] == sequence and type(sequence) is int
            and sequence > 0 and core["previous_head"] == previous_head and core["nonce"] == nonce,
            "BATCH_ENVELOPE_SEQUENCE_OR_NONCE_MISMATCH")
    require(core["purpose"] == purpose and core["policy_sha256"] == policy_sha256
            and core["artifact_file_sha256"] == e.sha(artifact), "BATCH_ENVELOPE_ARTIFACT_OR_PURPOSE_MISMATCH")
    key = registry["keys"].get(core["key_id"])
    require(key is not None and key["epoch"] == core["key_epoch"] and type(core["key_epoch"]) is int
            and purpose in key["purposes"] and key["revoked"] is False, "BATCH_UNTRUSTED_OR_REVOKED_KEY")
    public_bytes, signature = decode(key["public_key"], 32), decode(value["signature"], 64)
    try:
        Ed25519PublicKey.from_public_bytes(public_bytes).verify(signature, DOMAIN + e.canonical(core))
    except (InvalidSignature, ValueError) as exc:
        raise ValueError("BATCH_SIGNATURE_INVALID") from exc
    return core


def release_core(artifact, *, key_id, purpose, policy_sha256, sequence, previous_head, nonce):
    return {"artifact_kind": "RATE_BATCH_DETACHED_ENVELOPE_V1", "algorithm": "Ed25519", "material_scope": SCOPE,
            "key_id": key_id, "key_epoch": 1, "purpose": purpose, "policy_sha256": policy_sha256,
            "artifact_file_sha256": e.sha(artifact), "sequence": sequence, "previous_head": previous_head, "nonce": nonce}


def validate_policy(policy, ctx, *, at):
    fields = {"artifact_kind", "contract", "material_scope", "engineering_cr_sha256", "nonce", "approved",
              "main_sha", "sidecar_head", "execution_owner_sha256_lf", "sidecar_owner_sha256_lf", "binding",
              "ordinals", "chunk_ids", "per_chunk_requests", "maximum_requests", "start_head", "start_ordinal",
              "genesis_file_sha256", "activation_file_sha256", "initial_record_pins", "not_before", "not_after",
              "delegations", "runtime", "roots"}
    require(type(policy) is dict and set(policy) == fields and policy["artifact_kind"] == "RATE_BATCH_POLICY_V1"
            and policy["contract"] == CONTRACT and policy["material_scope"] == SCOPE,
            "BATCH_REAL_ACTIVATION_NOT_AUTHORIZED")
    require(policy["engineering_cr_sha256"] == CR_SHA256 and policy["approved"] is True, "BATCH_POLICY_NOT_APPROVED")
    require(policy["main_sha"] == FROZEN_MAIN and policy["sidecar_head"] == SIDECAR_HEAD
            and policy["execution_owner_sha256_lf"] == h.owners() and policy["sidecar_owner_sha256_lf"] == sidecar.owners(),
            "BATCH_SOURCE_HEAD_OR_OWNER_MISMATCH")
    require(ctx["synthetic"] is True and policy["binding"] == ctx["binding"], "BATCH_MANIFEST_SCOPE_UNIVERSE_MISMATCH")
    require(policy["delegations"] == ["AUTHORIZATION", "ACCEPTANCE", "HEAD_ACK"], "BATCH_ACCEPTANCE_DELEGATION_REQUIRED")
    require(e.canonical(policy["runtime"]) == e.canonical({"sequential": True, "single_writer": True, "timeout": 30, "interval": 13,
            "retry": 0, "redirect": False, "fallback": False, "auto_resume": False, "live_execution": False}), "BATCH_POLICY_RUNTIME_MISMATCH")
    ordinals = policy["ordinals"]
    require(type(policy["start_ordinal"]) is int and policy["start_ordinal"] >= 0
            and type(ordinals) is list and 1 <= len(ordinals) <= 10 and all(type(n) is int for n in ordinals)
            and ordinals == list(range(policy["start_ordinal"] + 1, policy["start_ordinal"] + 1 + len(ordinals))),
            "BATCH_WINDOW_RANGE_INVALID")
    require(ordinals[-1] <= ctx["manifest"]["chunk_count"], "BATCH_WINDOW_RANGE_INVALID")
    selected = [ctx["manifest"]["chunks"][n - 1] for n in ordinals]
    require(policy["chunk_ids"] == [c["chunk_id"] for c in selected]
            and policy["per_chunk_requests"] == [c["request_count"] for c in selected]
            and all(type(n) is int and 1 <= n <= 100 for n in policy["per_chunk_requests"])
            and type(policy["maximum_requests"]) is int and policy["maximum_requests"] == sum(policy["per_chunk_requests"]),
            "BATCH_WINDOW_IDENTITY_OR_BUDGET_MISMATCH")
    require(type(policy["nonce"]) is str and re.fullmatch(r"[a-zA-Z0-9_-]{16,128}", policy["nonce"]), "BATCH_POLICY_NONCE_INVALID")
    require(e.stamp(policy["not_before"]) <= e.stamp(at) <= e.stamp(policy["not_after"]), "BATCH_POLICY_EXPIRED_OR_FUTURE")
    roots = policy["roots"]
    require(set(roots) == {"sandbox", "issuer", "witness", "runner", "campaign", "ledger"}, "BATCH_ROOT_FIELDS_INVALID")
    base = sandbox(roots["sandbox"])
    checked = [child_root(roots[name], base) for name in roots if name != "sandbox"]
    require(len(set(checked)) == len(checked) and not any(a in b.parents for a in checked for b in checked if a != b),
            "BATCH_ROOT_OVERLAP")
    require(e.safe(roots["campaign"]) == e.safe(ctx["campaign_root"]) and
            e.safe(roots["ledger"]) == e.safe(ctx["ledger_root"]), "BATCH_ROOT_BINDING_MISMATCH")
    sidecar._check_context(ctx)
    chunks.validate_manifest(ctx["manifest"], ctx["scope"], ctx["approval"],
        trusted_approval_sha256=ctx["approval"]["approval_sha256"], main_sha=ctx["manifest"]["main_sha"],
        universe=ctx["universe"], synthetic=True)


class Journal:
    """Checkpoint-last commit; an external expected head detects truncation."""
    def __init__(self, root, base):
        self.root = child_root(root, base)
        self.root.mkdir(parents=True, exist_ok=True)

    def replay(self, expected_head):
        require(not (self.root / "HALTED.json").exists(), "BATCH_JOURNAL_HALTED")
        events, expected, previous = [], set(), None
        for path in sorted((self.root / "events").glob("*.json")):
            ordinal = len(events) + 1
            require(path.name == f"{ordinal:06}.json", "BATCH_JOURNAL_SEQUENCE_INVALID")
            event = load(path)
            core = e.verify_identity(event, "rate-batch-journal-", "event_id", "event_sha256")
            require(type(core["sequence"]) is int and core["sequence"] == ordinal and core["previous_head"] == previous,
                    "BATCH_JOURNAL_CHAIN_INVALID")
            require(all((self.root / directory / path.name).is_file() for directory in ("intents", "checkpoints")),
                    "BATCH_JOURNAL_INCOMPLETE")
            require(load(self.root / "intents" / path.name) == {"event": event}, "BATCH_JOURNAL_INCOMPLETE")
            require(load(self.root / "checkpoints" / path.name) == {"sequence": ordinal, "head": event["event_sha256"]},
                    "BATCH_JOURNAL_INCOMPLETE")
            expected.update(str(Path(folder) / path.name) for folder in ("intents", "events", "checkpoints"))
            previous = event["event_sha256"]; events.append(event)
        actual = sidecar.snapshot(self.root, exclude={self.root / ".scan.lock"})
        require(all(p.is_file() or str(p.relative_to(self.root)) in {"intents", "events", "checkpoints"}
                    for p in self.root.rglob("*")), "BATCH_JOURNAL_UNEXPECTED_DIRECTORY")
        require(set(actual) == expected, "BATCH_JOURNAL_ORPHAN_OR_INCOMPLETE")
        require(previous == expected_head, "BATCH_JOURNAL_STALE_OR_TRUNCATED_HEAD")
        return events

    def append(self, payload, expected_head, *, fault=lambda stage: None):
        with h.exclusive_scan(self.root):
            events = self.replay(expected_head)
            event = e.identified({"sequence": len(events) + 1, "previous_head": expected_head, "payload": payload},
                                 "rate-batch-journal-", "event_id", "event_sha256")
            name = f"{len(events) + 1:06}.json"
            for folder, value in (("intents", {"event": event}), ("events", event),
                                  ("checkpoints", {"sequence": len(events) + 1, "head": event["event_sha256"]})):
                put(self.root / folder / name, value)
                fault(folder)
            self.replay(event["event_sha256"])
            return event["event_sha256"]


class Issuer:
    """Used only by the isolated synthetic key worker, never by the launcher."""
    def __init__(self, policy, ctx, registry, registry_pin, policy_envelope, sign, witness_sign, *, at):
        validate_policy(policy, ctx, at=at)
        verify_envelope(policy_envelope, e.canonical(policy), registry=registry, registry_pin=registry_pin,
            purpose="POLICY", policy_sha256=e.sha(policy), sequence=1, previous_head=None, nonce=policy["nonce"])
        require(registry["issuer_root_identity"] == e.root_identity(policy["roots"]["issuer"])
                and registry["witness_root_identity"] == e.root_identity(policy["roots"]["witness"]),
                "BATCH_GLOBAL_ISSUER_ROOT_PIN_MISMATCH")
        self.policy, self.ctx, self.registry, self.registry_pin = policy, ctx, registry, registry_pin
        self.sign, self.witness_sign = sign, witness_sign
        self.journal = Journal(policy["roots"]["issuer"], policy["roots"]["sandbox"])
        self.witness = Journal(policy["roots"]["witness"], policy["roots"]["sandbox"])
        self.head = self.witness_head = None
        # No restart can silently adopt an old journal; inspection is a different operation.
        require(not self.journal.replay(None) and not self.witness.replay(None), "BATCH_RESTART_OR_RESUME_FORBIDDEN")
        self.accepted_head, self.accepted_ordinal = policy["start_head"], policy["start_ordinal"]
        self.release, self.accepted = None, None
        self.revoked, self.halted = False, False
        self.reserved = set()
        self.record_pins = dict(policy["initial_record_pins"])
        initial = sidecar.replay(ctx, genesis_path=ctx["genesis_path"],
            trusted_genesis_sha256=policy["genesis_file_sha256"], trusted_records=self.record_pins,
            expected_head=policy["start_head"])
        require(initial["status"] == "PASS" and initial["accepted_chunks"] == policy["start_ordinal"],
                "BATCH_BOOTSTRAP_ACCEPTANCE_REQUIRED")

    def guard(self, at):
        require(not self.halted and not self.revoked, "BATCH_ISSUER_HALTED_OR_REVOKED")
        validate_policy(self.policy, self.ctx, at=at)
        self.journal.replay(self.head); self.witness.replay(self.witness_head)

    def persist(self, purpose, artifact, *, at, fault=lambda stage: None):
        self.guard(at)
        sequence = len(self.journal.replay(self.head)) + 1
        core = release_core(e.canonical(artifact), key_id="issuer", purpose=purpose,
            policy_sha256=e.sha(self.policy), sequence=sequence, previous_head=self.head, nonce=self.policy["nonce"])
        signed = envelope(core, self.sign)
        self.head = self.journal.append({"purpose": purpose, "artifact": artifact, "envelope": signed}, self.head, fault=fault)
        acknowledgement = {"issuer_head": self.head, "issuer_sequence": sequence}
        ack_core = release_core(e.canonical(acknowledgement), key_id="witness", purpose="WITNESS",
            policy_sha256=e.sha(self.policy), sequence=sequence, previous_head=self.witness_head, nonce=self.policy["nonce"])
        witness = envelope(ack_core, self.witness_sign)
        self.witness_head = self.witness.append({"acknowledgement": acknowledgement, "envelope": witness}, self.witness_head)
        return {"artifact": artifact, "envelope": signed, "witness": witness, "acknowledgement": acknowledgement,
                "issuer_head": self.head, "witness_head": self.witness_head,
                "journal_events": self.journal.replay(self.head), "witness_event": self.witness.replay(self.witness_head)[-1]}

    def authorize(self, ordinal, predecessor_head, *, at):
        self.guard(at)
        require(type(ordinal) is int and ordinal in self.policy["ordinals"] and ordinal == self.accepted_ordinal + 1
                and predecessor_head == self.accepted_head and self.release is None, "BATCH_PREDECESSOR_OR_WINDOW_MISMATCH")
        chunk = self.ctx["manifest"]["chunks"][ordinal - 1]
        require(chunk["chunk_id"] not in self.reserved, "BATCH_GLOBAL_DOUBLE_ISSUANCE")
        bundle = chunks.materials(self.ctx["manifest"], self.ctx["scope"], self.ctx["approval"],
            trusted_approval_sha256=self.ctx["approval"]["approval_sha256"], main_sha=self.ctx["manifest"]["main_sha"],
            universe=self.ctx["universe"], chunk_id=chunk["chunk_id"], campaign_root=self.ctx["campaign_root"], synthetic=True)
        require(not Path(bundle["execution_root"]).exists() and not list(Path(bundle["consumption_root"]).glob("*.json")),
                "BATCH_PRIOR_CONSUMPTION_OR_EXECUTION")
        core = {k: v for k, v in bundle["candidate"].items() if k not in ("authorization_id", "authorization_sha256")}
        core["status"] = h.AUTHORIZED
        auth = e.identified(core, "rate-history-acquisition-authorization-", "authorization_id", "authorization_sha256")
        h.validate_authorization(auth, bundle["seal"])
        # Reservation is durable before an authorization release can be delivered.
        self.head = self.journal.append({"purpose": "RESERVE", "chunk_id": chunk["chunk_id"], "nonce": self.policy["nonce"]}, self.head)
        self.reserved.add(chunk["chunk_id"])
        self.release = {"ordinal": ordinal, "bundle": bundle, "authorization": auth}
        return self.persist("AUTHORIZATION", auth, at=at)

    def accept(self, ordinal, *, at):
        self.guard(at)
        require(self.release is not None and self.release["ordinal"] == ordinal and self.accepted is None,
                "BATCH_ACCEPTANCE_RELEASE_MISMATCH")
        proof = sidecar.verify_chunk(self.ctx, ordinal)
        require(proof["binding"]["authorization_sha256"] == self.release["authorization"]["authorization_sha256"],
                "BATCH_ACCEPTANCE_AUTHORIZATION_MISMATCH")
        require(e.stamp(proof["latest_validation"]) <= e.stamp(at), "BATCH_ACCEPTANCE_BEFORE_SOURCE_VALIDATION")
        record = e.identified({"artifact_kind": "RATE_HISTORY_CHUNK_CONTROL_CENTER_ACCEPTANCE_V1", "contract": sidecar.CONTRACT,
            "issuer": "CONTROL_CENTER", "decision": "CHUNK_ACCEPTED", **proof["binding"], "accepted_at": at},
            "rate-history-acceptance-record-", "acceptance_id", "acceptance_sha256")
        result = self.persist("ACCEPTANCE", record, at=at)
        self.accepted = record
        return {**result, "source_cold_replay": proof["cold_replay"]}

    def acknowledge(self, head, *, genesis_path, activation_path, record_paths, at):
        self.guard(at)
        require(self.accepted is not None, "BATCH_ACCEPTANCE_BEFORE_ACK_REQUIRED")
        require(e.sha(e.safe(genesis_path).read_bytes()) == self.policy["genesis_file_sha256"]
                and e.sha(e.safe(activation_path).read_bytes()) == self.policy["activation_file_sha256"], "BATCH_GENESIS_OR_PERMIT_PIN_MISMATCH")
        pins = {**self.record_pins, e.sha(self.accepted): record_paths[e.sha(self.accepted)]}
        replay = sidecar.replay(self.ctx, genesis_path=genesis_path,
            trusted_genesis_sha256=self.policy["genesis_file_sha256"], trusted_records=pins, expected_head=head)
        require(replay["status"] == "PASS" and replay["accepted_chunks"] == self.release["ordinal"]
                and replay["events"][-1]["acceptance_file_sha256"] == e.sha(self.accepted), "BATCH_EXTERNAL_HEAD_ACK_MISMATCH")
        ack = self.persist("HEAD_ACK", {"acceptance_head": head, "ordinal": self.release["ordinal"]}, at=at)
        self.accepted_ordinal, self.accepted_head = self.release["ordinal"], head
        self.record_pins = pins
        self.release = self.accepted = None
        return ack

    def revoke(self, *, at):
        result = self.persist("REVOCATION", {"nonce": self.policy["nonce"], "revoked": True}, at=at)
        self.revoked = True
        return result


def verify_packet(packet, *, policy, registry, registry_pin, purpose, previous_issuer_head, previous_witness_head):
    events, head, found_previous = packet["journal_events"], None, previous_issuer_head is None
    for sequence, event in enumerate(events, 1):
        core = e.verify_identity(event, "rate-batch-journal-", "event_id", "event_sha256")
        require(core["previous_head"] == head and core["sequence"] == sequence, "BATCH_RELEASE_JOURNAL_CHAIN_INVALID")
        head = event["event_sha256"]
        if head == previous_issuer_head:
            found_previous = True
    require(events and found_previous and head == packet["issuer_head"] and head != previous_issuer_head,
            "BATCH_RELEASE_REPLAY_OR_STALE_HEAD")
    last = events[-1]
    require(last["payload"] == {"purpose": purpose, "artifact": packet["artifact"], "envelope": packet["envelope"]},
            "BATCH_RELEASE_EVENT_ARTIFACT_MISMATCH")
    common = {"registry": registry, "registry_pin": registry_pin, "policy_sha256": e.sha(policy),
              "sequence": last["sequence"], "nonce": policy["nonce"]}
    verify_envelope(packet["envelope"], e.canonical(packet["artifact"]), purpose=purpose,
                    previous_head=last["previous_head"], **common)
    ack = {"issuer_head": head, "issuer_sequence": last["sequence"]}
    require(packet["acknowledgement"] == ack, "BATCH_RELEASE_WITNESS_ACK_MISMATCH")
    verify_envelope(packet["witness"], e.canonical(ack), purpose="WITNESS", previous_head=previous_witness_head, **common)
    witness = packet["witness_event"]
    core = e.verify_identity(witness, "rate-batch-journal-", "event_id", "event_sha256")
    require(core["previous_head"] == previous_witness_head and witness["event_sha256"] == packet["witness_head"]
            and core["payload"] == {"acknowledgement": ack, "envelope": packet["witness"]}, "BATCH_RELEASE_EXTERNAL_HEAD_MISMATCH")
    return packet["issuer_head"], packet["witness_head"]
