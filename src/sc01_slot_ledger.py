"""SC01-B offline atomic slot/lease/fencing model.

The in-memory implementation is a TEST DOUBLE ONLY, never Production storage.
A cloud implementation must provide real transactional uniqueness, durable
fencing and independent publication compare-and-swap/readback.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import re
from threading import RLock
from typing import Protocol

from src.sc01_scheduler_portability import SC01Blocked, SlotContract, require

_HEX = re.compile(r"[0-9a-f]{64}\Z")
_TOKEN = re.compile(r"[A-Za-z0-9_.:-]{12,128}\Z")


@dataclass(frozen=True)
class ClaimTicket:
    slot_key: str
    event_id: str
    event_digest: str
    nonce: str
    execution_id: str
    fencing_token: int
    lease_starts_utc: datetime
    lease_expires_utc: datetime


class TransactionalSlotStore(Protocol):
    """Future durable adapter boundary; does not supply a trusted Store Authority."""
    def claim(self, slot: SlotContract, *, event_id: str, event_digest: str,
              nonce: str, execution_id: str, now: datetime,
              lease_seconds: int) -> ClaimTicket: ...
    def bind_execution(self, ticket: ClaimTicket, execution_name: str,
                       *, now: datetime) -> None: ...
    def publish_candidate(self, ticket: ClaimTicket, *, execution_name: str,
                          material_digest: str, previous_state_id: str,
                          now: datetime) -> None: ...


class InMemorySC01Store:
    """Single-process offline simulation. Explicitly NOT a production adapter."""
    def __init__(self) -> None:
        self._lock = RLock()
        self._slots: dict[str, dict] = {}
        self._nonces: set[str] = set()
        self._event_digests: set[str] = set()
        self._event_ids: set[str] = set()

    @staticmethod
    def _time(now: datetime) -> datetime:
        require(isinstance(now, datetime) and now.tzinfo is not None,
                "SC01_CLOCK_UNTRUSTED")
        return now.astimezone(timezone.utc)

    def claim(self, slot: SlotContract, *, event_id: str, event_digest: str,
              nonce: str, execution_id: str, now: datetime,
              lease_seconds: int) -> ClaimTicket:
        # event_id must ultimately be derived from an authenticated provider
        # receipt. It is only an offline uniqueness key in this test double.
        now = self._time(now)
        require(isinstance(event_id, str) and _TOKEN.fullmatch(event_id) is not None,
                "SC01_EVENT_ID_INVALID")
        require(isinstance(event_digest, str) and _HEX.fullmatch(event_digest) is not None,
                "SC01_EVENT_DIGEST_INVALID")
        require(isinstance(nonce, str) and _TOKEN.fullmatch(nonce) is not None,
                "SC01_NONCE_INVALID")
        require(isinstance(execution_id, str) and _TOKEN.fullmatch(execution_id) is not None,
                "SC01_EXECUTION_ID_INVALID")
        require(type(lease_seconds) is int and 0 < lease_seconds <= 3600,
                "SC01_LEASE_INVALID")
        with self._lock:
            require(event_id not in self._event_ids
                    and nonce not in self._nonces
                    and event_digest not in self._event_digests,
                    "SC01_REPLAY_REJECTED")
            current = self._slots.get(slot.slot_key)
            if current is not None:
                require(current["state"] != "PUBLISHED",
                        "SC01_SLOT_ALREADY_PUBLISHED")
                require(now >= current["ticket"].lease_expires_utc,
                        "SC01_SLOT_ALREADY_CLAIMED")
                # Fencing prevents a late pre-expiry worker from publishing.
                fence = current["ticket"].fencing_token + 1
            else:
                fence = 1
            ticket = ClaimTicket(slot.slot_key, event_id, event_digest,
                                 nonce, execution_id, fence, now,
                                 now + timedelta(seconds=lease_seconds))
            self._slots[slot.slot_key] = {
                "ticket": ticket, "state": "CLAIMED",
                "cloud_execution_name": None, "material_digest": None,
                "previous_state_id": None,
            }
            self._nonces.add(nonce)
            self._event_digests.add(event_digest)
            self._event_ids.add(event_id)
            return ticket

    def _active(self, ticket: ClaimTicket, *, now: datetime) -> dict:
        # Called inside the same transaction/lock as the state transition.
        # No successor claim is required to invalidate an expired ticket.
        # "now" is an explicit deterministic input for OFFLINE tests only;
        # Production must instead use trusted store-transaction time.
        at = self._time(now)
        current = self._slots.get(ticket.slot_key)
        require(current is not None and current["ticket"] == ticket,
                "SC01_FENCING_TOKEN_STALE")
        require(ticket.lease_starts_utc <= at < ticket.lease_expires_utc,
                "SC01_LEASE_EXPIRED_OR_CLOCK_INVALID")
        return current

    def bind_execution(self, ticket: ClaimTicket, execution_name: str,
                       *, now: datetime) -> None:
        with self._lock:
            current = self._active(ticket, now=now)
            require(current["state"] == "CLAIMED",
                    "SC01_EXECUTION_ALREADY_BOUND")
            require(isinstance(execution_name, str) and execution_name.endswith(
                "/executions/" + ticket.execution_id),
                "SC01_EXECUTION_BINDING_INVALID")
            current["cloud_execution_name"] = execution_name
            current["state"] = "EXECUTION_BOUND"

    def publish_candidate(self, ticket: ClaimTicket, *, execution_name: str,
                          material_digest: str, previous_state_id: str,
                          now: datetime) -> None:
        """Offline publication guard only; never writes actual RATE State."""
        with self._lock:
            current = self._active(ticket, now=now)
            require(current["state"] == "EXECUTION_BOUND",
                    "SC01_PUBLICATION_DUPLICATE_OR_UNBOUND")
            require(current["cloud_execution_name"] == execution_name,
                    "SC01_PUBLICATION_EXECUTION_MISMATCH")
            require(isinstance(material_digest, str) and _HEX.fullmatch(material_digest) is not None,
                    "SC01_PUBLICATION_HASH_INVALID")
            require(isinstance(previous_state_id, str) and bool(previous_state_id.strip()),
                    "SC01_PREDECESSOR_NOT_PROVEN")
            current["material_digest"] = material_digest
            current["previous_state_id"] = previous_state_id
            current["state"] = "PUBLISHED"

    def snapshot(self, slot: SlotContract) -> dict | None:
        with self._lock:
            current = self._slots.get(slot.slot_key)
            if current is None:
                return None
            return {
                "state": current["state"],
                "fencing_token": current["ticket"].fencing_token,
                "cloud_execution_name": current["cloud_execution_name"],
                "previous_state_id": current["previous_state_id"],
                "production_state_mutation": 0,
                "store_authority": "UNQUALIFIED_IN_MEMORY_TEST_DOUBLE",
            }
