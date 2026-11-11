"""Synthetic authority adapter; cannot issue an operational permit."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from offline.model_s_s2_r2.simulator import (
    Decision, ReceiptAuthority, ReplayLedger, SyntheticTrust, canonical, digest, utc,
)


PERMIT_FIELDS = {
    "kind", "token", "authority_id", "scope", "run_id", "attempt",
    "source_sha256", "workflow_sha256", "custody_id", "issued_at", "expires_at",
    "operational", 
}


class OfflineAuthorityAdapter:
    """Bind synthetic permits to source/workflow/custody and a durable one-use claim."""

    def __init__(self, *, trust: SyntheticTrust, ledger: ReplayLedger,
                 authority_id: str, scope: str, source_sha256: str,
                 workflow_sha256: str, custody_id: str) -> None:
        if not all(isinstance(v, str) and v.startswith("SYNTHETIC_") for v in
                   (authority_id, scope, custody_id)):
            raise ValueError("SYNTHETIC_AUTHORITY_SCOPE_REQUIRED")
        if not all(isinstance(v, str) and len(v) == 64 and
                   all(c in "0123456789abcdef" for c in v) for v in
                   (source_sha256, workflow_sha256)):
            raise ValueError("EXACT_SOURCE_HASH_REQUIRED")
        self.trust, self.ledger = trust, ledger
        self.authority_id, self.scope = authority_id, scope
        self.source_sha256, self.workflow_sha256 = source_sha256, workflow_sha256
        self.custody_id = custody_id
        self.receiver = ReceiptAuthority(trust, ledger, authority_id, scope)

    def authorize(self, signed: dict[str, Any], *, run_id: str,
                  attempt: int, now: datetime, failure: str | None = None) -> Decision:
        if now.tzinfo != timezone.utc:
            return Decision("BLOCKED", "CLOCK_UNKNOWN")
        verified = self.trust.verify(signed, self.scope, now)
        if verified.status != "PASS":
            return verified
        if signed["identity"] != self.authority_id:
            return Decision("BLOCKED", "AUTHORITY_IDENTITY_MISMATCH")
        p = signed["payload"]
        if not isinstance(p, dict) or set(p) != PERMIT_FIELDS:
            return Decision("BLOCKED", "PERMIT_SCHEMA")
        if not isinstance(p["token"], str) or not p["token"].startswith("SYNTHETIC_"):
            return Decision("BLOCKED", "PERMIT_TOKEN_INVALID")
        expected = {
            "kind": "SYNTHETIC_RECEIPT_PERMIT", "authority_id": self.authority_id,
            "scope": self.scope, "run_id": run_id, "attempt": attempt,
            "source_sha256": self.source_sha256,
            "workflow_sha256": self.workflow_sha256,
            "custody_id": self.custody_id, "operational": False,
        }
        if any(p[k] != v for k, v in expected.items()) or not isinstance(run_id, str) or not run_id.startswith("SYNTHETIC_") or type(attempt) is not int or attempt < 1:
            return Decision("BLOCKED", "PERMIT_BINDING_MISMATCH")
        try:
            if not utc(p["issued_at"]) <= now < utc(p["expires_at"]):
                return Decision("BLOCKED", "PERMIT_EXPIRED_OR_FUTURE")
        except (TypeError, ValueError):
            return Decision("BLOCKED", "PERMIT_TIME_INVALID")
        binding = digest(canonical(p))
        claimed = self.ledger.consume(p["token"], binding, failure=failure)
        if claimed.status != "PASS":
            return claimed
        if self.trust.verify(signed, self.scope, now).status != "PASS":
            return Decision("BLOCKED", "AUTHORITY_REVOKED_AFTER_CLAIM")
        if not self.ledger.has_exact(p["token"], binding, claimed.evidence["anchor"]):
            return Decision("UNKNOWN", "PERMIT_ANCHOR_UNVERIFIED")
        return Decision("PASS", "SYNTHETIC_PERMIT_ACK", {
            **expected, "token": p["token"], "binding": binding,
            "anchor": claimed.evidence["anchor"], "expires_at": p["expires_at"],
            "operational_authorization": False,
        })

    def accept_receipt(self, permit: Decision, signed_receipt: dict[str, Any],
                       package: bytes, now: datetime, *, failure: str | None = None) -> Decision:
        if permit.status != "PASS" or permit.reason != "SYNTHETIC_PERMIT_ACK" or not permit.evidence:
            return Decision("BLOCKED", "PERMIT_NOT_OWNED")
        e = permit.evidence
        if e.get("authority_id") != self.authority_id or e.get("scope") != self.scope or e.get("source_sha256") != self.source_sha256 or e.get("workflow_sha256") != self.workflow_sha256 or e.get("custody_id") != self.custody_id or e.get("operational_authorization") is not False:
            return Decision("BLOCKED", "PERMIT_BINDING_MISMATCH")
        if not self.ledger.has_exact(e.get("token", ""), e.get("binding", ""), e.get("anchor", "")):
            return Decision("BLOCKED", "PERMIT_ANCHOR_UNVERIFIED")
        try:
            if now.tzinfo != timezone.utc or now >= utc(e["expires_at"]):
                return Decision("BLOCKED", "PERMIT_EXPIRED_OR_CLOCK_UNKNOWN")
            p = signed_receipt["payload"]
            if not isinstance(p, dict) or p["run_id"] != e["run_id"] or p["attempt"] != e["attempt"] or p["scope"] != self.scope:
                return Decision("BLOCKED", "RECEIPT_PERMIT_BINDING_MISMATCH")
        except (KeyError, TypeError, ValueError):
            return Decision("BLOCKED", "RECEIPT_PERMIT_SCHEMA")
        return self.receiver.accept(signed_receipt, package, now, failure=failure)


def operational_authority(*_args: Any, **_kwargs: Any) -> Decision:
    """Permanent fence: this module never constructs an operational adapter."""
    return Decision("BLOCKED", "OPERATIONAL_AUTHORITY_NOT_AVAILABLE")
