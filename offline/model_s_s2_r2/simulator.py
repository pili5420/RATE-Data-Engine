"""Synthetic Model S S2 controls. No host, network, key-store or deletion I/O.

HMAC is deliberately a test-only authentication primitive here. It is not an
operational signing-key design or proof of independent key custody.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


HEX64 = re.compile(r"^[0-9a-f]{64}$")
FROZEN_C03_SHA256 = "a52de44c2980ed44cb2efe6ec893fb130aae6c7fe89e2f1f16b83669bbf5207b"
STATES = (
    "NOT_STARTED", "RECEIPT_PENDING", "RECEIPT_ACCEPTED", "RETENTION_ACTIVE",
    "RETENTION_EXPIRED", "DELETION_AUTHORIZED", "DELETION_PENDING",
    "DELETION_VERIFIED", "BLOCKED",
)


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def utc(value: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("UTC_Z_REQUIRED")
    parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    if parsed.tzinfo != timezone.utc:
        raise ValueError("UTC_REQUIRED")
    return parsed


def at(value: datetime) -> str:
    if value.tzinfo != timezone.utc:
        raise ValueError("UTC_CLOCK_REQUIRED")
    return value.isoformat(timespec="seconds").replace("+00:00", "Z")


@dataclass(frozen=True)
class Decision:
    status: str
    reason: str
    evidence: dict[str, Any] | None = None


class SyntheticTrust:
    """In-memory test keys only; callers cannot obtain a production authority."""

    def __init__(self) -> None:
        self._keys: dict[str, tuple[bytes, str, datetime | None]] = {}

    def register(self, identity: str, secret: bytes, scope: str) -> None:
        if not identity.startswith("SYNTHETIC_") or len(secret) < 32 or not scope.startswith("SYNTHETIC_"):
            raise ValueError("SYNTHETIC_IDENTITY_REQUIRED")
        if identity in self._keys:
            raise ValueError("DUPLICATE_IDENTITY")
        self._keys[identity] = (secret, scope, None)

    def revoke(self, identity: str, when: datetime) -> None:
        if when.tzinfo != timezone.utc or identity not in self._keys:
            raise ValueError("INVALID_REVOCATION")
        secret, scope, _ = self._keys[identity]
        self._keys[identity] = (secret, scope, when)

    def sign(self, identity: str, payload: dict[str, Any]) -> dict[str, Any]:
        secret, _, _ = self._keys[identity]
        return {"payload": payload, "identity": identity, "alg": "HMAC-SHA256-SYNTHETIC",
                "signature": hmac.new(secret, canonical(payload), hashlib.sha256).hexdigest()}

    def verify(self, signed: dict[str, Any], scope: str, now: datetime) -> Decision:
        if now.tzinfo != timezone.utc:
            return Decision("BLOCKED", "CLOCK_UNKNOWN")
        if not isinstance(signed, dict) or set(signed) != {"payload", "identity", "alg", "signature"}:
            return Decision("BLOCKED", "SIGNATURE_SCHEMA")
        identity = signed["identity"]
        if not isinstance(identity, str) or identity not in self._keys:
            return Decision("BLOCKED", "AUTHORITY_UNKNOWN")
        secret, allowed_scope, revoked_at = self._keys[identity]
        if allowed_scope != scope:
            return Decision("BLOCKED", "SCOPE_MISMATCH")
        if revoked_at is not None and now >= revoked_at:
            return Decision("BLOCKED", "AUTHORITY_REVOKED")
        if signed["alg"] != "HMAC-SHA256-SYNTHETIC" or not isinstance(signed["signature"], str):
            return Decision("BLOCKED", "ALGORITHM_UNSUPPORTED")
        try:
            expected = hmac.new(secret, canonical(signed["payload"]), hashlib.sha256).hexdigest()
        except (TypeError, ValueError):
            return Decision("BLOCKED", "PAYLOAD_INVALID")
        if not hmac.compare_digest(expected, signed["signature"]):
            return Decision("BLOCKED", "SIGNATURE_INVALID")
        return Decision("PASS", "SYNTHETIC_AUTHENTICATED")


class ReplayLedger:
    """SQLite exact-once test ledger with a local hash-chain anchor simulation."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        if self.path.name != "ledger.sqlite" or not any(part.startswith("SYNTHETIC_") for part in self.path.parts):
            raise ValueError("SYNTHETIC_LEDGER_PATH_REQUIRED")
        with self._connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS attempts (token TEXT PRIMARY KEY, binding TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS consumed (token TEXT PRIMARY KEY, binding TEXT NOT NULL, anchor TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS anchors (sequence INTEGER PRIMARY KEY AUTOINCREMENT, token TEXT UNIQUE NOT NULL, previous TEXT NOT NULL, hash TEXT NOT NULL)")

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.path, timeout=5.0, isolation_level=None)
        db.execute("PRAGMA busy_timeout=5000")
        try:
            yield db
        finally:
            if db.in_transaction:
                db.rollback()
            db.close()

    def consume(self, token: str, binding: str, *, failure: str | None = None) -> Decision:
        if not token.startswith("SYNTHETIC_") or not HEX64.fullmatch(binding):
            return Decision("BLOCKED", "BINDING_INVALID")
        try:
            with self._connect() as db:
                db.execute("BEGIN IMMEDIATE")
                if db.execute("SELECT 1 FROM attempts WHERE token=?", (token,)).fetchone():
                    db.execute("ROLLBACK")
                    return Decision("BLOCKED", "REPLAY_OR_REENTRY")
                # Durable claim precedes work. Unknown outcomes burn this token.
                db.execute("INSERT INTO attempts VALUES (?, ?)", (token, binding))
                db.execute("COMMIT")
                if failure == "after_claim":
                    return Decision("UNKNOWN", "CLAIM_ACK_UNKNOWN_FAIL_CLOSED")
                db.execute("BEGIN IMMEDIATE")
                previous = db.execute("SELECT hash FROM anchors ORDER BY sequence DESC LIMIT 1").fetchone()
                previous_hash = previous[0] if previous else "0" * 64
                anchor = digest(canonical({"previous": previous_hash, "token": token, "binding": binding}))
                db.execute("INSERT INTO consumed VALUES (?, ?, ?)", (token, binding, anchor))
                if failure == "before_anchor":
                    raise RuntimeError("INJECTED_PARTIAL_PERSISTENCE")
                db.execute("INSERT INTO anchors (token, previous, hash) VALUES (?, ?, ?)", (token, previous_hash, anchor))
                if failure == "before_commit":
                    raise RuntimeError("INJECTED_ROLLBACK")
                db.execute("COMMIT")
                if failure == "lost_ack":
                    # A readback is useful audit evidence, never authority to proceed.
                    return Decision("UNKNOWN", "ACK_LOST_FAIL_CLOSED", {"anchor": anchor})
                return Decision("PASS", "UNIQUE_ACK", {"anchor": anchor, "token": token, "binding": binding})
        except (sqlite3.Error, RuntimeError):
            return Decision("UNKNOWN", "PERSISTENCE_UNKNOWN_FAIL_CLOSED")

    def verify_chain(self) -> Decision:
        try:
            with self._connect() as db:
                rows = db.execute("SELECT token, previous, hash FROM anchors ORDER BY sequence").fetchall()
                consumed = db.execute("SELECT token, binding, anchor FROM consumed").fetchall()
                attempts = db.execute("SELECT token, binding FROM attempts").fetchall()
            if len(rows) != len(consumed):
                return Decision("BLOCKED", "ANCHOR_COUNT_MISMATCH")
            attempt_map = dict(attempts)
            by_token = {token: (binding, anchor) for token, binding, anchor in consumed}
            previous = "0" * 64
            for token, prior, anchor in rows:
                if token not in by_token or prior != previous:
                    return Decision("BLOCKED", "ANCHOR_CHAIN_BROKEN")
                binding, stored_anchor = by_token[token]
                if attempt_map.get(token) != binding:
                    return Decision("BLOCKED", "ATTEMPT_BINDING_MISMATCH")
                if anchor != stored_anchor or anchor != digest(canonical({"previous": previous, "token": token, "binding": binding})):
                    return Decision("BLOCKED", "ANCHOR_TAMPERED")
                previous = anchor
            return Decision("PASS", "LOCAL_ANCHOR_SIMULATION_ONLY", {"count": len(rows)})
        except sqlite3.Error:
            return Decision("UNKNOWN", "ANCHOR_UNREADABLE")

    def has_exact(self, token: str, binding: str, anchor: str) -> bool:
        try:
            with self._connect() as db:
                row = db.execute("SELECT binding, anchor FROM consumed WHERE token=?", (token,)).fetchone()
            return row == (binding, anchor) and self.verify_chain().status == "PASS"
        except sqlite3.Error:
            return False


RECEIPT_FIELDS = {"kind", "token", "scope", "run_id", "attempt", "package_sha256", "package_length", "issued_at", "expires_at"}


def receipt_binding_valid(evidence: dict[str, Any]) -> bool:
    try:
        payload = evidence["payload"]
        receipt_at = evidence["receipt_at"]
        utc(receipt_at)
        return (isinstance(payload, dict) and set(payload) == RECEIPT_FIELDS
                and evidence["binding"] == digest(canonical({"payload": payload, "receipt_at": receipt_at}))
                and all(evidence[k] == payload[k] for k in ("token", "scope", "run_id", "attempt", "package_sha256")))
    except (KeyError, TypeError, ValueError):
        return False


def evidence_package_valid(package: bytes) -> bool:
    try:
        p = json.loads(package.decode("utf-8"))
        if canonical(p) != package or not isinstance(p, dict) or set(p) != {
            "schema", "frozen_c03_sha256", "complete", "redaction_pass", "commands", "results"
        }:
            return False
        if p["schema"] != "SYNTHETIC_EVIDENCE_V1" or p["frozen_c03_sha256"] != FROZEN_C03_SHA256 or p["complete"] is not True or p["redaction_pass"] is not True:
            return False
        commands, results = p["commands"], p["results"]
        if not isinstance(commands, list) or not commands or not isinstance(results, list) or len(commands) != len(results):
            return False
        if any(not isinstance(c, dict) or set(c) != {"id", "sha256"} or not isinstance(c["id"], str) or not HEX64.fullmatch(str(c["sha256"])) for c in commands + results):
            return False
        command_ids = [c["id"] for c in commands]
        result_ids = [r["id"] for r in results]
        return len(set(command_ids)) == len(command_ids) and len(set(result_ids)) == len(result_ids) and set(command_ids) == set(result_ids)
    except (UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        return False


class ReceiptAuthority:
    def __init__(self, trust: SyntheticTrust, ledger: ReplayLedger, authority: str, scope: str) -> None:
        self.trust, self.ledger, self.authority, self.scope = trust, ledger, authority, scope

    def accept(self, signed: dict[str, Any], package: bytes, now: datetime, *, failure: str | None = None) -> Decision:
        auth = self.trust.verify(signed, self.scope, now)
        if auth.status != "PASS":
            return auth
        if signed["identity"] != self.authority:
            return Decision("BLOCKED", "WRONG_AUTHORITY")
        p = signed["payload"]
        if not isinstance(p, dict) or set(p) != RECEIPT_FIELDS or p["kind"] != "RECEIPT_ACCEPTED":
            return Decision("BLOCKED", "RECEIPT_SCHEMA")
        if p["scope"] != self.scope or not isinstance(p["run_id"], str) or not p["run_id"].startswith("SYNTHETIC_"):
            return Decision("BLOCKED", "RUN_OR_SCOPE_INVALID")
        if type(p["attempt"]) is not int or p["attempt"] < 1:
            return Decision("BLOCKED", "ATTEMPT_INVALID")
        if not evidence_package_valid(package):
            return Decision("BLOCKED", "PACKAGE_SCHEMA_OR_REDACTION")
        if not HEX64.fullmatch(str(p["package_sha256"])) or p["package_sha256"] != digest(package) or p["package_length"] != len(package):
            return Decision("BLOCKED", "PACKAGE_DIGEST_OR_LENGTH")
        try:
            issued, expires = utc(p["issued_at"]), utc(p["expires_at"])
        except (TypeError, ValueError):
            return Decision("BLOCKED", "TIME_INVALID")
        if not (issued <= now < expires):
            return Decision("BLOCKED", "AUTHORITY_EXPIRED_OR_FUTURE")
        binding = digest(canonical({"payload": p, "receipt_at": at(now)}))
        result = self.ledger.consume(p["token"], binding, failure=failure)
        if result.status != "PASS":
            return result
        if failure == "revoke_after_ack":
            self.trust.revoke(self.authority, now)
        if self.trust.verify(signed, self.scope, now).status != "PASS":
            return Decision("BLOCKED", "AUTHORITY_REVOKED_DURING_PROCESSING")
        if self.ledger.verify_chain().status != "PASS":
            return Decision("UNKNOWN", "ANCHOR_VERIFICATION_FAILED")
        return Decision("PASS", "SYNTHETIC_RECEIPT_ACCEPTED", {
            "receipt_at": at(now), "binding": binding, "anchor": result.evidence["anchor"],
            "token": p["token"], "scope": p["scope"], "run_id": p["run_id"],
            "attempt": p["attempt"], "package_sha256": p["package_sha256"],
            "payload": dict(p),
            "operational_authorization": False,
        })


def review_acceptance(*, package: bytes, manifest: dict[str, Any], receipt: Decision,
                      owner_signed: dict[str, Any], trust: SyntheticTrust, ledger: ReplayLedger, scope: str,
                      run_id: str, attempt: int, now: datetime) -> Decision:
    if receipt.status != "PASS" or receipt.reason != "SYNTHETIC_RECEIPT_ACCEPTED":
        return Decision("BLOCKED", "RECEIPT_NOT_ACCEPTED")
    evidence = receipt.evidence or {}
    if any(evidence.get(k) != v for k, v in {"scope": scope, "run_id": run_id, "attempt": attempt,
                                            "package_sha256": digest(package),
                                            "operational_authorization": False}.items()):
        return Decision("BLOCKED", "RECEIPT_BINDING_MISMATCH")
    if not receipt_binding_valid(evidence) or not ledger.has_exact(evidence.get("token", ""), evidence.get("binding", ""), evidence.get("anchor", "")):
        return Decision("BLOCKED", "RECEIPT_ANCHOR_UNVERIFIED")
    if not evidence_package_valid(package):
        return Decision("BLOCKED", "PACKAGE_SCHEMA_OR_REDACTION")
    if not isinstance(manifest, dict) or set(manifest) != {"sha256", "length", "complete", "redaction_pass", "frozen_c03_sha256", "commands", "results"}:
        return Decision("BLOCKED", "MANIFEST_SCHEMA")
    if manifest["sha256"] != digest(package) or manifest["length"] != len(package):
        return Decision("BLOCKED", "MANIFEST_DIGEST_OR_LENGTH")
    p = json.loads(package.decode("utf-8"))
    if manifest["complete"] is not True or manifest["redaction_pass"] is not True or manifest["frozen_c03_sha256"] != FROZEN_C03_SHA256 or manifest["commands"] != p["commands"] or manifest["results"] != p["results"]:
        return Decision("BLOCKED", "EVIDENCE_INCOMPLETE")
    auth = trust.verify(owner_signed, scope, now)
    if auth.status != "PASS":
        return auth
    if not owner_signed["identity"].startswith("SYNTHETIC_OWNER_"):
        return Decision("BLOCKED", "OWNER_IDENTITY_INVALID")
    p = owner_signed["payload"]
    if not isinstance(p, dict) or set(p) != {"kind", "scope", "run_id", "attempt", "package_sha256", "receipt_binding"}:
        return Decision("BLOCKED", "OWNER_ATTESTATION_SCHEMA")
    if p != {"kind": "OWNER_ATTESTATION", "scope": scope, "run_id": run_id, "attempt": attempt,
             "package_sha256": digest(package), "receipt_binding": receipt.evidence["binding"]}:
        return Decision("BLOCKED", "OWNER_OR_EVIDENCE_BINDING")
    return Decision("PASS", "TECHNICAL_VALIDATION_ONLY", {"package_sha256": digest(package), "independent_human_review": False})


class RetentionMachine:
    def __init__(self) -> None:
        self.state = "NOT_STARTED"
        self.accepted_at: datetime | None = None
        self.review: Decision | None = None
        self.deletion_receipt_sha256: str | None = None
        self.deletion_copies_sha256: str | None = None

    def pending(self) -> Decision:
        if self.state != "NOT_STARTED":
            return self.block("INVALID_PENDING_TRANSITION")
        self.state = "RECEIPT_PENDING"
        return Decision("PASS", self.state)

    def accept(self, receipt: Decision, *, ledger: ReplayLedger, scope: str,
               run_id: str, attempt: int, package_sha256: str) -> Decision:
        if self.state != "RECEIPT_PENDING" or receipt.status != "PASS" or receipt.reason != "SYNTHETIC_RECEIPT_ACCEPTED":
            return self.block("INVALID_RECEIPT_EVENT")
        evidence = receipt.evidence or {}
        try:
            accepted = utc(evidence["receipt_at"])
        except (KeyError, TypeError, ValueError):
            return self.block("INVALID_RETENTION_TIMESTAMP")
        if any(evidence.get(k) != v for k, v in {
            "scope": scope, "run_id": run_id, "attempt": attempt,
            "package_sha256": package_sha256, "operational_authorization": False,
        }.items()):
            return self.block("RECEIPT_BINDING_MISMATCH")
        if not receipt_binding_valid(evidence) or not ledger.has_exact(evidence.get("token", ""), evidence.get("binding", ""), evidence.get("anchor", "")):
            return self.block("RECEIPT_ANCHOR_UNVERIFIED")
        self.accepted_at, self.state = accepted, "RECEIPT_ACCEPTED"
        return Decision("PASS", self.state)

    def tick(self, now: datetime) -> Decision:
        if now.tzinfo != timezone.utc or self.accepted_at is None or now < self.accepted_at:
            return self.block("CLOCK_OR_START_INVALID")
        if self.state not in {"RECEIPT_ACCEPTED", "RETENTION_ACTIVE", "RETENTION_EXPIRED"}:
            return self.block("INVALID_TICK_TRANSITION")
        self.state = "RETENTION_EXPIRED" if now >= self.accepted_at + timedelta(days=30) else "RETENTION_ACTIVE"
        return Decision("PASS", self.state)

    def authorize_deletion(self, *, signed: dict[str, Any], trust: SyntheticTrust, scope: str,
                           now: datetime, review: Decision, legal_hold: bool,
                           incident_hold: bool, review_hold: bool, copies: list[dict[str, Any]],
                           receipt_sha256: str, ledger: ReplayLedger,
                           failure: str | None = None) -> Decision:
        if self.state != "RETENTION_EXPIRED" or self.accepted_at is None or now.tzinfo != timezone.utc or now < self.accepted_at + timedelta(days=30):
            return self.block("RETENTION_NOT_EXPIRED")
        if review.status != "PASS" or review.reason != "TECHNICAL_VALIDATION_ONLY":
            return self.block("REVIEW_EVIDENCE_MISSING")
        if not HEX64.fullmatch(str(receipt_sha256)) or not review.evidence or review.evidence.get("package_sha256") != receipt_sha256 or review.evidence.get("independent_human_review") is not False:
            return self.block("REVIEW_BINDING_MISMATCH")
        if legal_hold or incident_hold or review_hold or not copies or any(set(c) != {"id", "known", "encrypted", "sha256"} or c["known"] is not True or c["encrypted"] is not True or not HEX64.fullmatch(str(c["sha256"])) for c in copies):
            return self.block("HOLD_OR_COPY_UNKNOWN")
        if len({c["id"] for c in copies}) != len(copies):
            return self.block("DUPLICATE_COPY")
        auth = trust.verify(signed, scope, now)
        if auth.status != "PASS" or not signed["identity"].startswith("SYNTHETIC_OWNER_"):
            return self.block("OWNER_AUTHORIZATION_INVALID")
        p = signed["payload"]
        if not isinstance(p, dict) or set(p) != {"kind", "scope", "receipt_sha256", "copies_sha256", "token", "issued_at", "expires_at"}:
            return self.block("DELETION_BINDING_INVALID")
        if any(p[k] != v for k, v in {"kind": "DELETE_AUTHORIZE", "scope": scope,
                                      "receipt_sha256": receipt_sha256,
                                      "copies_sha256": digest(canonical(copies))}.items()):
            return self.block("DELETION_BINDING_INVALID")
        try:
            if not utc(p["issued_at"]) <= now < utc(p["expires_at"]):
                return self.block("DELETION_AUTH_EXPIRED")
        except (TypeError, ValueError):
            return self.block("DELETION_AUTH_TIME_INVALID")
        claimed = ledger.consume(p["token"], digest(canonical(p)), failure=failure)
        if claimed.status != "PASS":
            return self.block("DELETION_OWNERSHIP_UNKNOWN" if claimed.status == "UNKNOWN" else "DELETION_REPLAY")
        if trust.verify(signed, scope, now).status != "PASS" or ledger.verify_chain().status != "PASS":
            return self.block("DELETION_AUTHORITY_OR_ANCHOR_CHANGED")
        self.state, self.review = "DELETION_AUTHORIZED", review
        self.deletion_receipt_sha256, self.deletion_copies_sha256 = receipt_sha256, p["copies_sha256"]
        return Decision("PASS", "SYNTHETIC_DELETION_AUTHORIZED", {"copies_sha256": p["copies_sha256"], "real_deletion": False})

    def deletion_pending(self) -> Decision:
        if self.state != "DELETION_AUTHORIZED":
            return self.block("INVALID_DELETION_TRANSITION")
        self.state = "DELETION_PENDING"
        return Decision("PASS", self.state)

    def verify_deletion(self, confirmation: dict[str, Any], *, copies: list[dict[str, Any]],
                        trust: SyntheticTrust, ledger: ReplayLedger, scope: str,
                        now: datetime) -> Decision:
        if self.state != "DELETION_PENDING" or trust.verify(confirmation, scope, now).status != "PASS":
            return self.block("DELETION_RECEIPT_INVALID")
        if not confirmation["identity"].startswith("SYNTHETIC_RECEIPT_AUTHORITY"):
            return self.block("DELETION_RECEIPT_AUTHORITY_INVALID")
        p = confirmation["payload"]
        if not isinstance(p, dict) or set(p) != {"kind", "scope", "token", "receipt_sha256", "copies_sha256", "all_copies_accounted", "real_deletion", "issued_at", "expires_at"}:
            return self.block("DELETION_RECEIPT_INVALID")
        if any(p[k] != v for k, v in {"kind": "SYNTHETIC_DELETION_CONFIRMATION", "scope": scope,
                                      "receipt_sha256": self.deletion_receipt_sha256,
                                      "copies_sha256": self.deletion_copies_sha256,
                                      "all_copies_accounted": True, "real_deletion": False}.items()) or p["copies_sha256"] != digest(canonical(copies)):
            return self.block("DELETION_RECEIPT_INVALID")
        try:
            if not utc(p["issued_at"]) <= now < utc(p["expires_at"]):
                return self.block("DELETION_RECEIPT_EXPIRED")
        except (TypeError, ValueError):
            return self.block("DELETION_RECEIPT_TIME_INVALID")
        recorded = ledger.consume(p["token"], digest(canonical(p)))
        if recorded.status != "PASS" or ledger.verify_chain().status != "PASS":
            return self.block("DELETION_RECEIPT_REPLAY_OR_UNKNOWN")
        self.state = "DELETION_VERIFIED"
        return Decision("PASS", self.state, {"real_deletion": False})

    def block(self, reason: str) -> Decision:
        self.state = "BLOCKED"
        return Decision("BLOCKED", reason)
