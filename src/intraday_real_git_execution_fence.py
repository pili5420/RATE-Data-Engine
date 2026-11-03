"""Durable single-use consumption fence for future real Git transaction execution.

This module performs no Git operation. It validates one exact real-execution
authorization qualification and records a write-once consumption receipt before
any future Git mutation is allowed.
"""
from __future__ import annotations

from copy import deepcopy
import re
from typing import Any, Mapping

from .intraday_activation_candidate_review import canonical_digest
from .intraday_real_git_execution_authorization import EXPECTED_BUDGET

HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
EXECUTION_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


class ExecutionFenceError(RuntimeError):
    pass


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ExecutionFenceError(reason)


def _sha40(value: Any, reason: str) -> str:
    text = str(value or "").lower()
    require(bool(HEX40.fullmatch(text)), reason)
    return text


def _sha64(value: Any, reason: str) -> str:
    text = str(value or "").lower()
    require(bool(HEX64.fullmatch(text)), reason)
    return text


class SyntheticWriteOnceReceiptStore:
    """Synthetic durable-store semantics for CI. No filesystem or network I/O."""

    backend = "SYNTHETIC_WRITE_ONCE_RECEIPT_STORE"

    def __init__(self, *, fail_write: bool = False):
        self.records: dict[str, dict[str, Any]] = {}
        self.fail_write = fail_write
        self.write_attempts = 0

    def read(self, execution_id: str):
        value = self.records.get(execution_id)
        return deepcopy(value) if value is not None else None

    def write_once(self, execution_id: str, receipt: Mapping[str, Any]) -> None:
        self.write_attempts += 1
        if self.fail_write:
            raise RuntimeError("SYNTHETIC_RECEIPT_STORE_WRITE_FAILED")
        require(execution_id not in self.records, "EXECUTION_FENCE_ALREADY_CONSUMED")
        self.records[execution_id] = deepcopy(dict(receipt))


def _validate_qualification(
    qualification: Mapping[str, Any],
    *,
    expected_qualification_sha256: str,
    expected_current_main_sha: str,
    expected_target_branch: str,
) -> tuple[str, str]:
    qualification_hash = _sha64(
        expected_qualification_sha256,
        "EXECUTION_FENCE_EXPECTED_QUALIFICATION_HASH_INVALID",
    )
    main_sha = _sha40(
        expected_current_main_sha,
        "EXECUTION_FENCE_EXPECTED_MAIN_INVALID",
    )
    require(
        isinstance(qualification, Mapping),
        "EXECUTION_FENCE_QUALIFICATION_INVALID",
    )
    require(
        canonical_digest(qualification) == qualification_hash,
        "EXECUTION_FENCE_QUALIFICATION_HASH_MISMATCH",
    )
    require(
        qualification.get("artifact")
        == "RATE_INTRADAY_REAL_GIT_TRANSACTION_EXECUTION_AUTHORIZATION_QUALIFICATION_V1"
        and qualification.get("validation_status") == "PASS"
        and qualification.get("authorization_valid") is True,
        "EXECUTION_FENCE_QUALIFICATION_NOT_PASS",
    )
    require(
        qualification.get("base_main_sha") == main_sha,
        "EXECUTION_FENCE_MAIN_BINDING_MISMATCH",
    )
    require(
        qualification.get("target_branch") == expected_target_branch
        and qualification.get("target_base") == "main",
        "EXECUTION_FENCE_BRANCH_BINDING_MISMATCH",
    )
    require(
        qualification.get("operation_budget") == EXPECTED_BUDGET,
        "EXECUTION_FENCE_OPERATION_BUDGET_INVALID",
    )
    require(
        qualification.get("single_use") is True
        and qualification.get("retry_allowed") is False
        and qualification.get("draft_pull_request_required") is True
        and qualification.get("direct_main_update_allowed") is False
        and qualification.get("merge_allowed") is False
        and qualification.get("execution_performed") is False
        and qualification.get("real_git_operations") == 0
        and qualification.get("live_provider_requests") == 0
        and qualification.get("external_dependency_resolved") is False
        and qualification.get("registry_activation_allowed") is False
        and qualification.get("production_credit") == 0
        and qualification.get("cer081_credit") == 0,
        "EXECUTION_FENCE_QUALIFICATION_BOUNDARY_INVALID",
    )
    return qualification_hash, main_sha


def consume_execution_fence(
    qualification: Mapping[str, Any],
    store: SyntheticWriteOnceReceiptStore,
    *,
    execution_id: str,
    expected_qualification_sha256: str,
    expected_current_main_sha: str,
    expected_target_branch: str,
) -> dict[str, Any]:
    require(
        type(store) is SyntheticWriteOnceReceiptStore
        and store.backend == "SYNTHETIC_WRITE_ONCE_RECEIPT_STORE",
        "EXECUTION_FENCE_REAL_STORE_FORBIDDEN_IN_ENGINEERING",
    )
    require(
        isinstance(execution_id, str)
        and bool(EXECUTION_ID.fullmatch(execution_id))
        and ".." not in execution_id
        and not execution_id.endswith(".")
        and not execution_id.lower().endswith(".lock"),
        "EXECUTION_FENCE_EXECUTION_ID_INVALID",
    )
    qualification_hash, main_sha = _validate_qualification(
        qualification,
        expected_qualification_sha256=expected_qualification_sha256,
        expected_current_main_sha=expected_current_main_sha,
        expected_target_branch=expected_target_branch,
    )

    # Replay is rejected before a second write attempt.
    require(store.read(execution_id) is None, "EXECUTION_FENCE_ALREADY_CONSUMED")

    receipt_core = {
        "artifact": "RATE_INTRADAY_REAL_GIT_EXECUTION_CONSUMPTION_RECEIPT_V1",
        "state": "CONSUMED_BEFORE_GIT_MUTATION",
        "execution_id": execution_id,
        "authorization_qualification_sha256": qualification_hash,
        "base_main_sha": main_sha,
        "target_branch": expected_target_branch,
        "transaction_plan_sha256": qualification["transaction_plan_sha256"],
        "candidate_manifest_sha256": qualification["candidate_manifest_sha256"],
        "provider_name": qualification["provider_name"],
        "single_use_consumed": True,
        "retry_allowed": False,
        "git_mutations_before_receipt": 0,
        "live_provider_requests": 0,
        "external_dependency_resolved": False,
        "registry_activation_allowed": False,
        "production_credit": 0,
        "cer081_credit": 0,
    }
    receipt = {
        **receipt_core,
        "receipt_sha256": canonical_digest(receipt_core),
    }
    store.write_once(execution_id, receipt)
    persisted = store.read(execution_id)
    require(persisted == receipt, "EXECUTION_FENCE_PERSISTED_RECEIPT_MISMATCH")
    return deepcopy(receipt)


def validate_consumed_execution_fence(
    store: SyntheticWriteOnceReceiptStore,
    *,
    execution_id: str,
    expected_receipt_sha256: str,
    expected_qualification_sha256: str,
    expected_current_main_sha: str,
    expected_target_branch: str,
) -> dict[str, Any]:
    require(
        type(store) is SyntheticWriteOnceReceiptStore,
        "EXECUTION_FENCE_REAL_STORE_FORBIDDEN_IN_ENGINEERING",
    )
    receipt = store.read(execution_id)
    require(isinstance(receipt, Mapping), "EXECUTION_FENCE_RECEIPT_MISSING")
    receipt_hash = _sha64(
        expected_receipt_sha256,
        "EXECUTION_FENCE_EXPECTED_RECEIPT_HASH_INVALID",
    )
    require(
        receipt.get("receipt_sha256") == receipt_hash,
        "EXECUTION_FENCE_RECEIPT_HASH_MISMATCH",
    )
    core = {k: v for k, v in receipt.items() if k != "receipt_sha256"}
    require(
        canonical_digest(core) == receipt_hash,
        "EXECUTION_FENCE_RECEIPT_SELF_HASH_MISMATCH",
    )
    require(
        receipt.get("state") == "CONSUMED_BEFORE_GIT_MUTATION"
        and receipt.get("single_use_consumed") is True
        and receipt.get("retry_allowed") is False
        and receipt.get("git_mutations_before_receipt") == 0,
        "EXECUTION_FENCE_RECEIPT_STATE_INVALID",
    )
    require(
        receipt.get("authorization_qualification_sha256")
        == expected_qualification_sha256
        and receipt.get("base_main_sha") == expected_current_main_sha
        and receipt.get("target_branch") == expected_target_branch,
        "EXECUTION_FENCE_RECEIPT_BINDING_MISMATCH",
    )
    return deepcopy(dict(receipt))
