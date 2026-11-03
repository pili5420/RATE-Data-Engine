"""Semantic qualification for the durable authority-store adapter used by real Git execution.

CI uses only a synthetic adapter. The contract models an external durable store with
atomic create-if-absent, strong read-after-write, immutable receipts, and explicit
ambiguous-write recovery by readback without retrying the create operation.
"""
from __future__ import annotations

from copy import deepcopy
import re
from typing import Any, Mapping

from .intraday_activation_candidate_review import canonical_digest

EXECUTION_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


class AuthorityStoreAdapterError(RuntimeError):
    pass


class AmbiguousCreateOutcome(RuntimeError):
    pass


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise AuthorityStoreAdapterError(reason)


def validate_store_capabilities(capabilities: Mapping[str, Any]) -> dict[str, Any]:
    require(isinstance(capabilities, Mapping), "AUTHORITY_STORE_CAPABILITIES_INVALID")
    require(
        capabilities.get("artifact")
        == "RATE_INTRADAY_REAL_AUTHORITY_STORE_CAPABILITIES_V1",
        "AUTHORITY_STORE_CAPABILITIES_ARTIFACT_INVALID",
    )
    require(
        capabilities.get("durability") == "EXTERNAL_PERSISTENT"
        and capabilities.get("atomic_create_if_absent") is True
        and capabilities.get("strong_read_after_write") is True,
        "AUTHORITY_STORE_DURABILITY_SEMANTICS_INVALID",
    )
    require(
        capabilities.get("overwrite_allowed") is False
        and capabilities.get("delete_allowed") is False
        and capabilities.get("unbounded_listing_allowed") is False,
        "AUTHORITY_STORE_MUTATION_BOUNDARY_INVALID",
    )
    require(
        capabilities.get("transport") == "HTTPS_TLS"
        and capabilities.get("server_identity_verified") is True,
        "AUTHORITY_STORE_TRANSPORT_INVALID",
    )
    credential = capabilities.get("credential_boundary")
    require(isinstance(credential, Mapping), "AUTHORITY_STORE_CREDENTIAL_BOUNDARY_MISSING")
    require(
        credential.get("store") in {"GITHUB_ACTIONS_SECRET", "EXTERNAL_SECRET_MANAGER"}
        and isinstance(credential.get("secret_name"), str)
        and credential["secret_name"].strip()
        and credential.get("secret_value_embedded") is False,
        "AUTHORITY_STORE_CREDENTIAL_BOUNDARY_INVALID",
    )
    require(
        capabilities.get("ambiguous_create_policy")
        == "READ_SAME_EXECUTION_ID_DO_NOT_RETRY_CREATE",
        "AUTHORITY_STORE_AMBIGUOUS_CREATE_POLICY_INVALID",
    )
    require(
        capabilities.get("receipt_key_scope") == "EXACT_EXECUTION_ID"
        and capabilities.get("receipt_format")
        == "RATE_INTRADAY_REAL_GIT_EXECUTION_CONSUMPTION_RECEIPT_V1",
        "AUTHORITY_STORE_RECEIPT_SCOPE_INVALID",
    )
    return deepcopy(dict(capabilities))


class SyntheticAuthorityStoreAdapter:
    """Synthetic semantic model only; never contacts an external store."""

    backend = "SYNTHETIC_AUTHORITY_STORE_ADAPTER"

    def __init__(self, *, failure_mode: str | None = None):
        self.records: dict[str, dict[str, Any]] = {}
        self.failure_mode = failure_mode
        self.create_attempts = 0
        self.read_attempts = 0

    def read(self, execution_id: str):
        self.read_attempts += 1
        value = self.records.get(execution_id)
        return deepcopy(value) if value is not None else None

    def create_if_absent(self, execution_id: str, receipt: Mapping[str, Any]) -> str:
        self.create_attempts += 1
        if self.failure_mode == "BEFORE_CREATE":
            raise RuntimeError("SYNTHETIC_AUTHORITY_STORE_FAIL_BEFORE_CREATE")
        if execution_id in self.records:
            return "ALREADY_EXISTS"
        self.records[execution_id] = deepcopy(dict(receipt))
        if self.failure_mode == "AMBIGUOUS_AFTER_CREATE":
            raise AmbiguousCreateOutcome("SYNTHETIC_AUTHORITY_STORE_AMBIGUOUS_AFTER_CREATE")
        return "CREATED"


def _validate_execution_id(execution_id: str) -> None:
    require(
        isinstance(execution_id, str)
        and bool(EXECUTION_ID.fullmatch(execution_id))
        and ".." not in execution_id
        and not execution_id.endswith(".")
        and not execution_id.lower().endswith(".lock"),
        "AUTHORITY_STORE_EXECUTION_ID_INVALID",
    )


def _validate_receipt(receipt: Mapping[str, Any], execution_id: str) -> dict[str, Any]:
    require(isinstance(receipt, Mapping), "AUTHORITY_STORE_RECEIPT_INVALID")
    require(
        receipt.get("artifact")
        == "RATE_INTRADAY_REAL_GIT_EXECUTION_CONSUMPTION_RECEIPT_V1"
        and receipt.get("state") == "CONSUMED_BEFORE_GIT_MUTATION"
        and receipt.get("execution_id") == execution_id,
        "AUTHORITY_STORE_RECEIPT_STATE_INVALID",
    )
    require(
        receipt.get("single_use_consumed") is True
        and receipt.get("retry_allowed") is False
        and receipt.get("git_mutations_before_receipt") == 0,
        "AUTHORITY_STORE_RECEIPT_BOUNDARY_INVALID",
    )
    receipt_hash = receipt.get("receipt_sha256")
    require(
        isinstance(receipt_hash, str) and len(receipt_hash) == 64,
        "AUTHORITY_STORE_RECEIPT_HASH_INVALID",
    )
    core = {k: v for k, v in receipt.items() if k != "receipt_sha256"}
    require(
        canonical_digest(core) == receipt_hash,
        "AUTHORITY_STORE_RECEIPT_SELF_HASH_MISMATCH",
    )
    return deepcopy(dict(receipt))


def persist_receipt_via_adapter(
    capabilities: Mapping[str, Any],
    adapter: SyntheticAuthorityStoreAdapter,
    receipt: Mapping[str, Any],
    *,
    execution_id: str,
) -> dict[str, Any]:
    validate_store_capabilities(capabilities)
    require(
        type(adapter) is SyntheticAuthorityStoreAdapter
        and adapter.backend == "SYNTHETIC_AUTHORITY_STORE_ADAPTER",
        "AUTHORITY_STORE_REAL_ADAPTER_FORBIDDEN_IN_ENGINEERING",
    )
    _validate_execution_id(execution_id)
    expected = _validate_receipt(receipt, execution_id)

    existing = adapter.read(execution_id)
    if existing is not None:
        require(existing == expected, "AUTHORITY_STORE_EXISTING_RECEIPT_CONFLICT")
        raise AuthorityStoreAdapterError("AUTHORITY_STORE_ALREADY_CONSUMED")

    try:
        outcome = adapter.create_if_absent(execution_id, expected)
    except AmbiguousCreateOutcome:
        # Never retry create after an ambiguous outcome. Resolve by one exact-key read.
        persisted = adapter.read(execution_id)
        require(
            persisted is not None,
            "AUTHORITY_STORE_AMBIGUOUS_CREATE_UNRESOLVED",
        )
        require(
            persisted == expected,
            "AUTHORITY_STORE_AMBIGUOUS_CREATE_RECEIPT_CONFLICT",
        )
        return {
            "artifact": "RATE_INTRADAY_REAL_AUTHORITY_STORE_PERSIST_RESULT_V1",
            "validation_status": "PASS",
            "outcome": "AMBIGUOUS_CREATE_CONFIRMED_BY_READBACK",
            "execution_id": execution_id,
            "receipt_sha256": expected["receipt_sha256"],
            "create_attempts": adapter.create_attempts,
            "read_attempts": adapter.read_attempts,
            "create_retries": 0,
            "overwrite_attempts": 0,
            "delete_attempts": 0,
            "real_store_requests": 0,
        }

    require(outcome == "CREATED", "AUTHORITY_STORE_CREATE_IF_ABSENT_FAILED")
    persisted = adapter.read(execution_id)
    require(persisted == expected, "AUTHORITY_STORE_READBACK_MISMATCH")
    return {
        "artifact": "RATE_INTRADAY_REAL_AUTHORITY_STORE_PERSIST_RESULT_V1",
        "validation_status": "PASS",
        "outcome": "CREATED_AND_READBACK_VERIFIED",
        "execution_id": execution_id,
        "receipt_sha256": expected["receipt_sha256"],
        "create_attempts": adapter.create_attempts,
        "read_attempts": adapter.read_attempts,
        "create_retries": 0,
        "overwrite_attempts": 0,
        "delete_attempts": 0,
        "real_store_requests": 0,
    }
