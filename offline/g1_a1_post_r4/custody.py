"""Synthetic custody boundary. The memory anchor is not immutable host custody."""
from __future__ import annotations

from datetime import datetime, timezone
from threading import Lock
from typing import Any, Protocol

from offline.model_s_s2_r2.simulator import (Decision, ReplayLedger, canonical, digest,
    evidence_package_valid, receipt_binding_valid, HEX64)


class ImmutableAnchorPort(Protocol):
    """Operational implementations require separate authority and review."""
    def create_once(self, key: str, binding: str, *, failure: str | None = None) -> Decision: ...
    def exact(self, key: str, binding: str, ack: str) -> bool: ...


class SyntheticMemoryAnchor:
    def __init__(self) -> None:
        self._lock = Lock()
        self._seen: dict[str, tuple[str, str | None]] = {}

    def create_once(self, key: str, binding: str, *, failure: str | None = None) -> Decision:
        if not key.startswith("SYNTHETIC_") or len(binding) != 64:
            return Decision("BLOCKED", "ANCHOR_INPUT_INVALID")
        with self._lock:
            if key in self._seen:
                return Decision("BLOCKED", "ANCHOR_REPLAY_OR_CONFLICT")
            self._seen[key] = (binding, None)
            if failure == "partial":
                return Decision("UNKNOWN", "ANCHOR_PARTIAL_FAIL_CLOSED")
            ack = digest(canonical({"key": key, "binding": binding}))
            self._seen[key] = (binding, ack)
            if failure == "lost_ack":
                return Decision("UNKNOWN", "ANCHOR_ACK_LOST_FAIL_CLOSED")
            return Decision("PASS", "SYNTHETIC_ANCHOR_ACK", {"ack": ack})

    def exact(self, key: str, binding: str, ack: str) -> bool:
        with self._lock:
            return self._seen.get(key) == (binding, ack)


class CustodyCoordinator:
    def __init__(self, anchor: ImmutableAnchorPort, ledger: ReplayLedger, destination: str) -> None:
        if not destination.startswith("SYNTHETIC_"):
            raise ValueError("UNBOUND_OR_OPERATIONAL_DESTINATION")
        self.anchor, self.ledger, self.destination = anchor, ledger, destination

    def record(self, *, permit: Decision, receipt: Decision, package: bytes,
               references: list[dict[str, str]], backup_inventory: list[dict[str, str]],
               now: datetime, failure: str | None = None) -> Decision:
        if now.tzinfo != timezone.utc:
            return Decision("BLOCKED", "CLOCK_UNKNOWN")
        if permit.status != "PASS" or permit.reason != "SYNTHETIC_PERMIT_ACK" or not permit.evidence:
            return Decision("BLOCKED", "PERMIT_UNVERIFIED")
        if receipt.status != "PASS" or receipt.reason != "SYNTHETIC_RECEIPT_ACCEPTED" or not receipt.evidence:
            return Decision("BLOCKED", "RECEIPT_UNVERIFIED")
        p, r = permit.evidence, receipt.evidence
        if not self.ledger.has_exact(p.get("token", ""), p.get("binding", ""), p.get("anchor", "")):
            return Decision("BLOCKED", "PERMIT_OWNERSHIP_UNVERIFIED")
        if not receipt_binding_valid(r) or not self.ledger.has_exact(r.get("token", ""), r.get("binding", ""), r.get("anchor", "")):
            return Decision("BLOCKED", "RECEIPT_OWNERSHIP_UNVERIFIED")
        if p.get("custody_id") != self.destination or any(p.get(k) != r.get(k) for k in ("scope", "run_id", "attempt")):
            return Decision("BLOCKED", "CUSTODY_BINDING_MISMATCH")
        if p.get("operational_authorization") is not False or r.get("operational_authorization") is not False:
            return Decision("BLOCKED", "OPERATIONAL_AUTHORITY_FORBIDDEN")
        if not evidence_package_valid(package) or r.get("package_sha256") != digest(package):
            return Decision("BLOCKED", "PACKAGE_INTEGRITY")
        if not references or any(not isinstance(x, dict) or set(x) != {"id", "sha256"} or not isinstance(x["id"], str) or not x["id"].startswith("SYNTHETIC_") or not isinstance(x["sha256"], str) or not HEX64.fullmatch(x["sha256"]) for x in references):
            return Decision("BLOCKED", "PACKAGE_REFERENCES_INVALID")
        if not backup_inventory or any(not isinstance(x, dict) or set(x) != {"copy_id", "state"} or not isinstance(x["copy_id"], str) or not x["copy_id"].startswith("SYNTHETIC_") or x["state"] not in {"PRESENT", "ABSENT"} for x in backup_inventory):
            return Decision("BLOCKED", "BACKUP_INVENTORY_UNKNOWN")
        if len({x["copy_id"] for x in backup_inventory}) != len(backup_inventory):
            return Decision("BLOCKED", "BACKUP_INVENTORY_DUPLICATE")
        binding = digest(canonical({"permit": p, "receipt": r, "references": references,
                                    "backup_inventory": backup_inventory, "destination": self.destination}))
        key = "SYNTHETIC_CUSTODY_" + r["token"]
        result = self.anchor.create_once(key, binding, failure=failure)
        if result.status != "PASS":
            return result
        ack = result.evidence["ack"]
        if not self.anchor.exact(key, binding, ack):
            return Decision("UNKNOWN", "CUSTODY_READBACK_UNKNOWN")
        return Decision("PASS", "SYNTHETIC_CUSTODY_RECEIPT", {"ack": ack, "binding": binding,
                "receipt_at": r["receipt_at"], "retention_anchor": r["receipt_at"],
                "operational_custody": False})
