"""Fundamental-only First Refresh execution wiring.

This module owns only the sealed 1,984-request plan, execution binding,
fundamental assembly, and a dedicated atomic Fundamental Latest pointer.
It never imports Phase2 ranking or Decision State owners.
"""
from __future__ import annotations

from copy import deepcopy
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
from typing import Any, Mapping

from .eps_duration_facts.model import require
from .provider_eps_metadata import read_metadata
from . import production_refresh_commit as refresh

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "docs/contracts/RATE_FUNDAMENTAL_FIRST_REFRESH_EXECUTION_V1.json"
CONTRACT = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))

PLAN_KIND = "RATE_FUNDAMENTAL_FIRST_REFRESH_REQUEST_PLAN_V1"
SNAPSHOT_KIND = "RATE_FUNDAMENTAL_FIRST_REFRESH_SNAPSHOT_V1"
LATEST_KIND = "RATE_FUNDAMENTAL_FIRST_REFRESH_LATEST_V1"
LATEST_NAME = "RATE_FUNDAMENTAL_FIRST_REFRESH_LATEST.json"
OBJECT_NAME = "RATE_FUNDAMENTAL_FIRST_REFRESH_SNAPSHOT_V1.json"
CONSUMPTION_NAMESPACE = Path("fundamental_first_refresh/authorization_consumption")
EPS_PERIODS = tuple(CONTRACT["eps_periods"])
REVENUE_PERIODS = tuple(CONTRACT["revenue_periods"])
MOPS_ORDER = tuple((market, period) for market in ("TWSE", "TPEX") for period in REVENUE_PERIODS)
DATASETS = {"FinMind": "TaiwanStockFinancialStatements", "MOPS Official": "MOPS_MONTHLY_REVENUE_ARCHIVE"}


def canonical(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def digest(value: Any) -> str:
    body = value if isinstance(value, (bytes, bytearray)) else canonical(value)
    return hashlib.sha256(body).hexdigest()


def exact_universe(universe: Mapping[str, Any]) -> tuple[list[dict], str]:
    require(universe.get("verification_status") == "PASS", "FIRST_REFRESH_UNIVERSE_NOT_VERIFIED")
    stocks = [{"symbol": str(row["symbol"]), "market": str(row["market"])} for row in universe.get("stocks", [])]
    require(len(stocks) == 1978 and len({row["symbol"] for row in stocks}) == 1978,
            "FIRST_REFRESH_UNIVERSE_CARDINALITY")
    counts = {market: sum(row["market"] == market for row in stocks) for market in ("TWSE", "TPEX")}
    require(counts == {"TWSE": 1085, "TPEX": 893}
            and all(row["market"] in counts for row in stocks), "FIRST_REFRESH_UNIVERSE_MARKETS")
    ordered = sorted(stocks, key=lambda row: (row["symbol"], row["market"]))
    return ordered, digest({"stocks": ordered, "counts": counts})


def publication_destination() -> dict:
    value = deepcopy(CONTRACT["publication_destination"])
    value["identity"] = digest({k: v for k, v in value.items() if k != "identity"})
    return value


def build_request_plan(universe: Mapping[str, Any], authority_id: str, main_sha: str) -> dict:
    require(re.fullmatch(r"[0-9a-f]{40}", str(main_sha)) is not None, "FIRST_REFRESH_MAIN_SHA_INVALID")
    require(isinstance(authority_id, str) and authority_id, "FIRST_REFRESH_AUTHORITY_MISSING")
    stocks, universe_id = exact_universe(universe)
    destination = publication_destination()
    entries = []
    ordinal = 1
    for stock in stocks:
        target = {"symbol": stock["symbol"], "market": stock["market"]}
        entries.append({
            "ordinal": ordinal,
            "request_key": f"finmind:{stock['market']}:{stock['symbol']}",
            "provider": "FinMind",
            "dataset": DATASETS["FinMind"],
            "target": target,
            "timeout_seconds": 20,
            "minimum_dispatch_interval_seconds": 13,
            "authority_id": authority_id,
            "universe_identity": universe_id,
            "execution_main_sha": main_sha,
            "publication_destination_identity": destination["identity"],
        })
        ordinal += 1
    for market, period in MOPS_ORDER:
        target = {"market": market, "period": period}
        entries.append({
            "ordinal": ordinal,
            "request_key": f"mops:{market}:{period}",
            "provider": "MOPS Official",
            "dataset": DATASETS["MOPS Official"],
            "target": target,
            "timeout_seconds": 45,
            "minimum_dispatch_interval_seconds": 13,
            "authority_id": authority_id,
            "universe_identity": universe_id,
            "execution_main_sha": main_sha,
            "publication_destination_identity": destination["identity"],
        })
        ordinal += 1
    core = {
        "artifact_kind": PLAN_KIND,
        "authority_id": authority_id,
        "execution_main_sha": main_sha,
        "universe_identity": universe_id,
        "publication_destination": destination,
        "planned_requests": 1984,
        "maximum_requests": 1984,
        "finmind_requests": 1978,
        "mops_requests": 6,
        "ordering": "FINMIND_CANONICAL_SYMBOL_ORDER_THEN_MOPS_TWSE_TPEX_PERIOD_ORDER",
        "concurrency": "SINGLE_WRITER_SEQUENTIAL",
        "automatic_retry": 0,
        "fallback_allowed": False,
        "first_refresh_authorized": False,
        "ranking_authorized": False,
        "historical_pit": "UNPROVEN",
        "original_eight_quarter_coverage_credit": 0,
        "entries": entries,
    }
    plan_hash = digest(core)
    return {
        **core,
        "request_plan_sha256": plan_hash,
        "request_plan_id": "rate-first-refresh-review-plan-" + plan_hash,
    }


def validate_plan(plan: Mapping[str, Any], universe: Mapping[str, Any], authority_id: str, main_sha: str) -> dict:
    expected = build_request_plan(universe, authority_id, main_sha)
    require(dict(plan) == expected, "FIRST_REFRESH_REQUEST_PLAN_DRIFT")
    ordinals = [row["ordinal"] for row in expected["entries"]]
    keys = [row["request_key"] for row in expected["entries"]]
    require(ordinals == list(range(1, 1985)) and len(keys) == len(set(keys)) == 1984,
            "FIRST_REFRESH_REQUEST_PLAN_ORDER_OR_DUPLICATE")
    return expected


class PlanDispatchGate:
    """Bind the accepted acquisition gate to one immutable request-plan entry."""

    def __init__(self, plan: Mapping[str, Any], entry: Mapping[str, Any], inner):
        self.plan, self.entry, self.inner = dict(plan), dict(entry), inner

    def _binding(self) -> dict:
        return {
            "request_plan_sha256": self.plan["request_plan_sha256"],
            "request_key": self.entry["request_key"],
            "ordinal": self.entry["ordinal"],
            "authority_id": self.plan["authority_id"],
            "main_sha": self.plan["execution_main_sha"],
            "provider": self.entry["provider"],
            "target": deepcopy(self.entry["target"]),
            "publication_destination_identity": self.plan["publication_destination"]["identity"],
        }

    def boundary(self, intent_id):
        evidence = {"plan_binding": self._binding(), "intent_id": intent_id}
        if self.inner is not None:
            evidence["provider_dispatch"] = self.inner.boundary(intent_id)
        return evidence

    def check_outbound(self, evidence):
        require(evidence.get("plan_binding") == self._binding(), "FIRST_REFRESH_DISPATCH_PLAN_MISMATCH")
        if self.inner is not None:
            self.inner.check_outbound(evidence["provider_dispatch"])

    def completed(self):
        if self.inner is not None:
            self.inner.completed()


def simulate_full_plan(plan: Mapping[str, Any], universe: Mapping[str, Any], *,
                       terminal_failure_at: int | None = None,
                       unknown_outcome_at: int | None = None,
                       crash_before_at: int | None = None,
                       crash_after_success_at: int | None = None) -> dict:
    validate_plan(plan, universe, plan["authority_id"], plan["execution_main_sha"])
    dispatched, completed, intents, checkpoints = [], [], set(), []
    for entry in plan["entries"]:
        ordinal = entry["ordinal"]
        if crash_before_at == ordinal:
            return {
                "status": "CRASH_BEFORE_DISPATCH",
                "dispatch_count": len(dispatched),
                "completed_count": len(completed),
                "next_ordinal": ordinal,
                "request_plan_sha256": plan["request_plan_sha256"],
                "auto_resume_allowed": False,
            }
        intent_id = f"synthetic-intent-{ordinal:04d}-{digest(entry['request_key'])[:12]}"
        require(intent_id not in intents, "FIRST_REFRESH_SYNTHETIC_INTENT_REUSE")
        intents.add(intent_id)
        dispatched.append(entry["request_key"])
        if unknown_outcome_at == ordinal:
            return {
                "status": "STOPPED_UNKNOWN_OUTCOME",
                "dispatch_count": len(dispatched),
                "completed_count": len(completed),
                "stopped_ordinal": ordinal,
                "request_key": entry["request_key"],
                "retry_allowed": False,
                "fallback_allowed": False,
                "auto_resume_allowed": False,
            }
        if terminal_failure_at == ordinal:
            return {
                "status": "STOPPED_TERMINAL_FAILURE",
                "dispatch_count": len(dispatched),
                "completed_count": len(completed),
                "stopped_ordinal": ordinal,
                "request_key": entry["request_key"],
                "retry_allowed": False,
                "fallback_allowed": False,
                "auto_resume_allowed": False,
            }
        completed.append(entry["request_key"])
        checkpoint = {
            "request_plan_sha256": plan["request_plan_sha256"],
            "last_completed_ordinal": ordinal,
            "completed_request_count": len(completed),
            "completed_request_keys_sha256": digest(completed),
            "success_count": len(completed),
            "terminal_failure_count": 0,
            "unknown_outcome_count": 0,
            "next_ordinal": ordinal + 1 if ordinal < 1984 else None,
            "current_main": plan["execution_main_sha"],
            "authority_id": plan["authority_id"],
            "auto_resume_allowed": False,
        }
        checkpoints.append(checkpoint)
        if crash_after_success_at == ordinal:
            return {
                "status": "CRASH_AFTER_IMMUTABLE_SUCCESS",
                "dispatch_count": len(dispatched),
                "completed_count": len(completed),
                "completed_request_key": entry["request_key"],
                "cold_replay_proves_completed": True,
                "would_resend_completed_request": False,
                "auto_resume_allowed": False,
                "next_ordinal": ordinal + 1 if ordinal < 1984 else None,
            }
    require(dispatched == [entry["request_key"] for entry in plan["entries"]],
            "FIRST_REFRESH_SYNTHETIC_ORDER_DRIFT")
    return {
        "status": "PASS",
        "dispatch_count": len(dispatched),
        "completed_count": len(completed),
        "unique_intent_count": len(intents),
        "request_plan_sha256": plan["request_plan_sha256"],
        "dispatch_order_sha256": digest(dispatched),
        "final_checkpoint": checkpoints[-1],
        "auto_resume_allowed": False,
    }


def _entry_map(plan: Mapping[str, Any]) -> dict[str, dict]:
    return {row["request_key"]: row for row in plan["entries"]}


def _valid_decimal(value) -> bool:
    try:
        return isinstance(value, str) and Decimal(value).is_finite()
    except Exception:
        return False


def assemble_fundamental(plan: Mapping[str, Any], universe: Mapping[str, Any],
                         observations: list[Mapping[str, Any]]) -> dict:
    validate_plan(plan, universe, plan["authority_id"], plan["execution_main_sha"])
    stocks, universe_id = exact_universe(universe)
    require(universe_id == plan["universe_identity"], "FIRST_REFRESH_ASSEMBLER_UNIVERSE_DRIFT")
    expected = _entry_map(plan)
    require(len(observations) == 1984, "FIRST_REFRESH_ASSEMBLER_REQUEST_COUNT")
    seen = {}
    evidence_index = []
    eps = {}
    revenue = {}
    ledger_head = None
    stock_index = {(row["symbol"], row["market"]) for row in stocks}
    for item in observations:
        key = item.get("request_key")
        require(key in expected and key not in seen, "FIRST_REFRESH_ASSEMBLER_REQUEST_KEY")
        entry = expected[key]
        require(item.get("ordinal") == entry["ordinal"], "FIRST_REFRESH_ASSEMBLER_ORDINAL")
        record = item.get("record") or {}
        intent = item.get("intent") or {}
        require(record.get("provider") == entry["provider"] and record.get("target") == entry["target"],
                "FIRST_REFRESH_ASSEMBLER_TARGET")
        dispatch = intent.get("dispatch", {}).get("plan_binding")
        require(dispatch == PlanDispatchGate(plan, entry, None)._binding(),
                "FIRST_REFRESH_ASSEMBLER_INTENT_BINDING")
        require(intent.get("intent_id") == item.get("intent_id"), "FIRST_REFRESH_ASSEMBLER_INTENT_ID")
        rows = record.get("rows")
        require(isinstance(rows, list), "FIRST_REFRESH_ASSEMBLER_ROWS")
        for row in rows:
            symbol, market, period = str(row.get("symbol")), str(row.get("market")), str(row.get("period"))
            require((symbol, market) in stock_index, "FIRST_REFRESH_ASSEMBLER_ROW_UNIVERSE")
            status = row.get("numeric_status")
            if status == "VALID_NUMERIC":
                require(_valid_decimal(row.get("value")), "FIRST_REFRESH_ASSEMBLER_NONFINITE")
            else:
                require(status == "UNDEFINED_ZERO_BASE" and row.get("value") is None
                        and entry["provider"] == "MOPS Official", "FIRST_REFRESH_ASSEMBLER_NUMERIC_STATUS")
            target_map = eps if entry["provider"] == "FinMind" else revenue
            required_periods = EPS_PERIODS if entry["provider"] == "FinMind" else REVENUE_PERIODS
            require(period in required_periods, "FIRST_REFRESH_ASSEMBLER_PERIOD")
            row_key = (symbol, period)
            require(row_key not in target_map, "FIRST_REFRESH_ASSEMBLER_OVERLAP")
            target_map[row_key] = deepcopy(row)
        seen[key] = True
        ledger_head = item.get("event_sha256")
        require(isinstance(ledger_head, str) and re.fullmatch(r"[0-9a-f]{64}", ledger_head),
                "FIRST_REFRESH_ASSEMBLER_EVENT_HEAD")
        evidence_index.append({
            "ordinal": entry["ordinal"],
            "request_key": key,
            "intent_id": item["intent_id"],
            "event_sha256": ledger_head,
            "raw_sha256": record.get("raw_sha256"),
            "receipt_sha256": record.get("receipt_sha256"),
            "immutable_snapshot_id": record.get("immutable_snapshot_id"),
            "provider": entry["provider"],
            "target": deepcopy(entry["target"]),
        })
    require(set(seen) == set(expected), "FIRST_REFRESH_ASSEMBLER_REQUEST_LOSS")
    matrix = []
    for stock in stocks:
        symbol = stock["symbol"]
        eps_rows = {p: eps[(symbol, p)] for p in EPS_PERIODS if (symbol, p) in eps}
        revenue_rows = {p: revenue[(symbol, p)] for p in REVENUE_PERIODS if (symbol, p) in revenue}
        eps_missing = [p for p in EPS_PERIODS if p not in eps_rows or eps_rows[p]["numeric_status"] != "VALID_NUMERIC"]
        revenue_missing = [p for p in REVENUE_PERIODS if p not in revenue_rows or revenue_rows[p]["numeric_status"] != "VALID_NUMERIC"]
        status = "READY" if not eps_missing and not revenue_missing else "NOT_READY_MISSING_REQUIRED_PERIOD"
        matrix.append({
            **stock,
            "fundamental_input_status": status,
            "eps_status": "READY" if not eps_missing else "NOT_READY_MISSING_REQUIRED_PERIOD",
            "revenue_status": "READY" if not revenue_missing else "NOT_READY_MISSING_REQUIRED_PERIOD",
            "missing_reasons": {"FinMind": eps_missing, "MOPS Official": revenue_missing},
            "feature_inputs": {"eps": eps_rows, "revenue": revenue_rows},
            "ranking_eligible": False,
            "score": None,
            "rank": None,
        })
    core = {
        "artifact_kind": SNAPSHOT_KIND,
        "request_plan_id": plan["request_plan_id"],
        "request_plan_sha256": plan["request_plan_sha256"],
        "authority_id": plan["authority_id"],
        "execution_main_sha": plan["execution_main_sha"],
        "universe_identity": plan["universe_identity"],
        "issuer_count": len(matrix),
        "issuer_readiness": matrix,
        "evidence_index": evidence_index,
        "acquisition_ledger_head": ledger_head,
        "historical_pit": "UNPROVEN",
        "original_eight_quarter_coverage_credit": 0,
        "fallback_allowed": False,
        "ranking_authorized": False,
        "decision_state_authorized": False,
        "production_domain": "fundamental",
        "publication_destination": deepcopy(plan["publication_destination"]),
    }
    snapshot_hash = digest(core)
    return {
        **core,
        "fundamental_snapshot_id": "rate-fundamental-first-refresh-" + snapshot_hash,
        "content_sha256": snapshot_hash,
        "fundamental_production_eligible": True,
    }


def _object_ref(snapshot: Mapping[str, Any]) -> dict:
    body = canonical(snapshot)
    ident = digest(body)
    return {
        "path": (Path("fundamental_first_refresh") / "objects" / ident / OBJECT_NAME).as_posix(),
        "sha256": ident,
        "bytes": len(body),
    }


def _put_object(root: Path, snapshot: Mapping[str, Any]) -> dict:
    root = refresh.safe(root)
    ref = _object_ref(snapshot)
    path = refresh.safe(root / ref["path"])
    path.parent.mkdir(parents=True, exist_ok=True)
    body = canonical(snapshot)
    try:
        with path.open("xb") as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError:
        require(path.read_bytes() == body, "FIRST_REFRESH_IMMUTABLE_OBJECT_CONFLICT")
    require(path.read_bytes() == body, "FIRST_REFRESH_STAGING_VERIFICATION_FAILED")
    for directory in (path.parent, path.parent.parent, path.parent.parent.parent, root):
        refresh.sync_directory(directory)
    return ref


def _manifest_digest(manifest: Mapping[str, Any]) -> str:
    return digest({k: v for k, v in manifest.items() if k != "manifest_sha256"})


def _pointer_body(value: Mapping[str, Any]) -> bytes:
    """Exact bytes written by the accepted atomic_write_json owner."""
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def verify_fundamental_manifest(root: str | Path, manifest: Mapping[str, Any]) -> dict:
    root = refresh.safe(root)
    require(manifest.get("artifact_kind") == LATEST_KIND
            and manifest.get("transaction_status") == "COMMITTED"
            and manifest.get("validation_status") == "PASS"
            and manifest.get("authoritative_commit_points") == 1
            and manifest.get("manifest_sha256") == _manifest_digest(manifest),
            "FIRST_REFRESH_MANIFEST_INVALID")
    ref = manifest.get("fundamental_snapshot")
    require(isinstance(ref, dict), "FIRST_REFRESH_MANIFEST_REFERENCE")
    path = refresh.safe(root / ref["path"])
    require(path.is_file(), "FIRST_REFRESH_SNAPSHOT_MISSING")
    body = path.read_bytes()
    require(digest(body) == ref.get("sha256") and len(body) == ref.get("bytes"),
            "FIRST_REFRESH_SNAPSHOT_TAMPER")
    snapshot = read_metadata(body)
    require(snapshot.get("artifact_kind") == SNAPSHOT_KIND
            and snapshot.get("fundamental_snapshot_id") == manifest.get("fundamental_snapshot_id")
            and snapshot.get("request_plan_sha256") == manifest.get("request_plan_sha256")
            and snapshot.get("universe_identity") == manifest.get("universe_identity")
            and snapshot.get("ranking_authorized") is False
            and snapshot.get("decision_state_authorized") is False,
            "FIRST_REFRESH_SNAPSHOT_BINDING")
    return snapshot


def publish_fundamental_atomic(snapshot: Mapping[str, Any], *, artifacts_root: str | Path,
                               expected_previous_latest: str | None,
                               writer=None, clock=None) -> dict:
    """Dedicated Fundamental Latest; does not mutate the global Source Bundle Latest."""
    from scripts.publish_production_source_bundle_latest import atomic_write_json
    writer = writer or atomic_write_json
    clock = clock or (lambda: datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))
    root = refresh.safe(artifacts_root)
    pointer = root / LATEST_NAME
    prior = refresh.current_identity(pointer)
    require(prior == expected_previous_latest, "FIRST_REFRESH_CAS_STALE_CURRENT")
    ref = _put_object(root, snapshot)
    manifest = {
        "artifact_kind": LATEST_KIND,
        "validation_status": "PASS",
        "transaction_status": "COMMITTED",
        "authoritative_commit_points": 1,
        "prior_latest_identity": prior,
        "commit_timestamp": clock(),
        "fundamental_snapshot_id": snapshot["fundamental_snapshot_id"],
        "request_plan_id": snapshot["request_plan_id"],
        "request_plan_sha256": snapshot["request_plan_sha256"],
        "universe_identity": snapshot["universe_identity"],
        "authority_id": snapshot["authority_id"],
        "fundamental_snapshot": ref,
        "production_domain": "fundamental",
        "ranking_authorized": False,
        "decision_state_authorized": False,
        "historical_pit": "UNPROVEN",
    }
    manifest["manifest_sha256"] = _manifest_digest(manifest)
    verify_fundamental_manifest(root, manifest)
    expected_identity = digest(_pointer_body(manifest))
    with refresh.writer_lock(root):
        require(refresh.current_identity(pointer) == expected_previous_latest, "FIRST_REFRESH_CAS_STALE_CURRENT")
        try:
            writer(pointer, manifest)
        except Exception:
            if refresh.current_identity(pointer) != expected_identity:
                raise
        require(refresh.current_identity(pointer) == expected_identity, "FIRST_REFRESH_COMMIT_NOT_OBSERVED")
    verify_fundamental_manifest(root, manifest)
    return {
        "status": "COMMITTED",
        "latest_identity": expected_identity,
        "previous_latest_identity": expected_previous_latest,
        "fundamental_snapshot_id": snapshot["fundamental_snapshot_id"],
        "authoritative_commit_points": 1,
        "publication_destination": publication_destination(),
    }


def read_fundamental_committed(artifacts_root: str | Path, expected_identity: str | None = None) -> dict:
    root = refresh.safe(artifacts_root)
    pointer = root / LATEST_NAME
    body = pointer.read_bytes()
    require(expected_identity is None or digest(body) == expected_identity, "FIRST_REFRESH_LATEST_IDENTITY_MISMATCH")
    manifest = read_metadata(body)
    snapshot = verify_fundamental_manifest(root, manifest)
    return {"latest_identity": digest(body), "manifest": manifest, "snapshot": snapshot}


def preexecution_seal(plan: Mapping[str, Any], expected_previous_latest: str | None) -> dict:
    owners = {
        "execution_owner": ROOT / "src/fundamental_first_refresh_execution.py",
        "assembler_owner": ROOT / "src/fundamental_first_refresh_execution.py",
        "acquisition_owner": ROOT / "scripts/run_prospective_provider_activation.py",
        "atomic_publication_owner": ROOT / "scripts/publish_production_source_bundle_latest.py",
        "atomic_commit_owner": ROOT / "src/production_refresh_commit.py",
    }
    core = {
        "artifact_kind": "RATE_FUNDAMENTAL_FIRST_REFRESH_PREEXECUTION_SEAL_V1",
        "main_sha": plan["execution_main_sha"],
        "authority_id": plan["authority_id"],
        "universe_identity": plan["universe_identity"],
        "request_plan_id": plan["request_plan_id"],
        "request_plan_sha256": plan["request_plan_sha256"],
        "planned_requests": plan["planned_requests"],
        "maximum_requests": plan["maximum_requests"],
        "expected_previous_fundamental_latest_identity": expected_previous_latest,
        "publication_destination": deepcopy(plan["publication_destination"]),
        "owner_sha256": {name: digest(path.read_bytes()) for name, path in owners.items()},
        "first_refresh_authorized": False,
    }
    identity = digest(core)
    return {**core, "seal_id": "rate-first-refresh-preexecution-" + identity, "seal_sha256": identity}


def authorization_identity(authorization: Mapping[str, Any]) -> str:
    core = {k: v for k, v in authorization.items() if k not in {"authorization_id", "authorization_sha256"}}
    return "rate-first-refresh-authorization-" + digest(core)


def authorization_digest(authorization: Mapping[str, Any]) -> str:
    return digest({k: v for k, v in authorization.items() if k != "authorization_sha256"})


def consumption_root_identity(artifacts_root: str | Path) -> str:
    root = refresh.safe(artifacts_root).resolve()
    return digest({"authoritative_artifacts_root": os.path.normcase(str(root))})


def validate_execution_authorization(authorization: Mapping[str, Any], plan: Mapping[str, Any],
                                     expected_previous_latest: str | None, *,
                                     artifacts_root: str | Path | None = None) -> dict:
    require(authorization.get("status") == "FIRST_REFRESH_EXECUTION_AUTHORIZED",
            "FIRST_REFRESH_EXECUTION_NOT_AUTHORIZED")
    seal = preexecution_seal(plan, expected_previous_latest)
    require(authorization.get("main_sha") == plan["execution_main_sha"]
            and authorization.get("authority_id") == plan["authority_id"]
            and authorization.get("universe_identity") == plan["universe_identity"]
            and authorization.get("request_plan_sha256") == plan["request_plan_sha256"]
            and authorization.get("request_plan_id") == plan["request_plan_id"]
            and type(authorization.get("planned_requests")) is int and authorization["planned_requests"] == 1984
            and type(authorization.get("maximum_requests")) is int
            and authorization.get("maximum_requests") == 1984
            and authorization.get("publication_destination_identity") == plan["publication_destination"]["identity"]
            and authorization.get("expected_previous_fundamental_latest_identity") == expected_previous_latest
            and authorization.get("single_use") is True
            and authorization.get("preexecution_seal_id") == seal["seal_id"]
            and authorization.get("preexecution_seal_sha256") == seal["seal_sha256"]
            and authorization.get("owner_sha256") == seal["owner_sha256"],
            "FIRST_REFRESH_EXECUTION_AUTHORIZATION_BINDING")
    root_identity = authorization.get("authorization_consumption_root_identity")
    require(isinstance(root_identity, str) and re.fullmatch(r"[0-9a-f]{64}", root_identity) is not None
            and (artifacts_root is None or root_identity == consumption_root_identity(artifacts_root)),
            "FIRST_REFRESH_AUTHORIZATION_CONSUMPTION_ROOT_BINDING")
    require(authorization.get("authorization_id") == authorization_identity(authorization),
            "FIRST_REFRESH_AUTHORIZATION_ID_BINDING")
    require(authorization.get("authorization_sha256") == authorization_digest(authorization),
            "FIRST_REFRESH_AUTHORIZATION_HASH_BINDING")
    return seal


def _actual_latest_precheck(artifacts_root: str | Path, expected_previous_latest: str | None) -> None:
    actual = refresh.current_identity(refresh.safe(artifacts_root) / LATEST_NAME)
    require(actual == expected_previous_latest, "FIRST_REFRESH_PREACQUISITION_LATEST_DRIFT")


@contextmanager
def _authorization_claim_lock(root: Path):
    # Reuse the publisher's OS lock; bounded lock contention is not a network retry.
    deadline = time.monotonic() + 10
    while True:
        manager = refresh.writer_lock(root)
        try:
            manager.__enter__()
            break
        except refresh.PublicationError as exc:
            if str(exc) != "REFRESH_WRITER_CONFLICT":
                raise
            remaining = deadline - time.monotonic()
            require(remaining > 0, "FIRST_REFRESH_AUTHORIZATION_CLAIM_LOCK_TIMEOUT")
            time.sleep(min(0.01, remaining))
    try:
        yield
    finally:
        manager.__exit__(None, None, None)


def _consumption_binding(authorization: Mapping[str, Any], plan: Mapping[str, Any], seal: Mapping[str, Any]) -> dict:
    return {
        "artifact_kind": "RATE_FIRST_REFRESH_AUTHORIZATION_CONSUMPTION_V1",
        "authorization_id": authorization["authorization_id"],
        "authorization_sha256": authorization["authorization_sha256"],
        "authorization_consumption_root_identity": authorization["authorization_consumption_root_identity"],
        "preexecution_seal_id": seal["seal_id"],
        "preexecution_seal_sha256": seal["seal_sha256"],
        "request_plan_id": plan["request_plan_id"],
        "request_plan_sha256": plan["request_plan_sha256"],
        "execution_main_sha": plan["execution_main_sha"],
        "authority_id": plan["authority_id"],
        "universe_identity": plan["universe_identity"],
        "expected_previous_fundamental_latest_identity": seal["expected_previous_fundamental_latest_identity"],
        "publication_destination_identity": plan["publication_destination"]["identity"],
        "status": "CONSUMED",
    }


def verify_authorization_consumption(path: str | Path, authorization: Mapping[str, Any],
                                     plan: Mapping[str, Any], seal: Mapping[str, Any]) -> dict:
    path = refresh.safe(path)
    try:
        body = path.read_bytes()
        value = read_metadata(body)
        binding = _consumption_binding(authorization, plan, seal)
        require(isinstance(value, dict) and all(value.get(k) == v for k, v in binding.items()),
                "FIRST_REFRESH_AUTHORIZATION_CONSUMPTION_TAMPER")
        core = {k: v for k, v in value.items() if k != "consumption_sha256"}
        require(value.get("consumption_sha256") == digest(core) and body == canonical(value)
                and path.name == authorization["authorization_id"] + ".json",
                "FIRST_REFRESH_AUTHORIZATION_CONSUMPTION_TAMPER")
        execution = refresh.safe(value["execution_root"]).resolve()
        require(value["execution_root_identity"] == digest({"path": os.path.normcase(str(execution))}),
                "FIRST_REFRESH_AUTHORIZATION_CONSUMPTION_TAMPER")
        consumed = datetime.fromisoformat(value["consumed_at"].replace("Z", "+00:00"))
        require(consumed.tzinfo is not None and consumed <= datetime.now(timezone.utc),
                "FIRST_REFRESH_AUTHORIZATION_CONSUMPTION_TAMPER")
        return value
    except (ValueError, TypeError, KeyError) as exc:
        require(False, "FIRST_REFRESH_AUTHORIZATION_CONSUMPTION_TAMPER")


def claim_authorization(authorization: Mapping[str, Any], plan: Mapping[str, Any], *,
                        artifacts_root: str | Path, execution_root: str | Path,
                        expected_previous_latest: str | None, clock) -> dict:
    root = refresh.safe(artifacts_root).resolve()
    execution = refresh.safe(execution_root).resolve()
    # Validate without writes first, then repeat under the shared publication lock.
    _actual_latest_precheck(root, expected_previous_latest)
    validate_execution_authorization(authorization, plan, expected_previous_latest, artifacts_root=root)
    with _authorization_claim_lock(root):
        _actual_latest_precheck(root, expected_previous_latest)
        seal = validate_execution_authorization(authorization, plan, expected_previous_latest, artifacts_root=root)
        path = refresh.safe(root / CONSUMPTION_NAMESPACE / (authorization["authorization_id"] + ".json"))
        if path.exists():
            verify_authorization_consumption(path, authorization, plan, seal)
            require(False, "FIRST_REFRESH_AUTHORIZATION_ALREADY_CONSUMED")
        require(not execution.exists(), "FIRST_REFRESH_EXECUTION_ROOT_MUST_BE_NEW")
        consumed_at = clock()
        stamp = datetime.fromisoformat(consumed_at.replace("Z", "+00:00"))
        require(stamp.tzinfo is not None and stamp <= datetime.now(timezone.utc),
                "FIRST_REFRESH_AUTHORIZATION_CONSUMPTION_TIME_INVALID")
        core = {**_consumption_binding(authorization, plan, seal), "execution_root": str(execution),
                "execution_root_identity": digest({"path": os.path.normcase(str(execution))}),
                "consumed_at": consumed_at}
        record = {**core, "consumption_sha256": digest(core)}
        # Exclusive creation is the irreversible claim point. Partial/crashed records
        # remain occupied and fail closed, never repaired or deleted for reuse.
        _write_immutable(path, record)
        for directory in (path.parent, path.parent.parent, root):
            refresh.sync_directory(directory)
        return verify_authorization_consumption(path, authorization, plan, seal)


def current_main_guard(plan: Mapping[str, Any], *, repo: str | Path = ROOT) -> None:
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=repo).decode().strip()
    require(git("rev-parse", "HEAD") == plan["execution_main_sha"]
            and git("rev-parse", "origin/main") == plan["execution_main_sha"]
            and not git("status", "--porcelain"), "FIRST_REFRESH_MAIN_OR_WORKTREE_DRIFT")


def _write_immutable(path: Path, value: Any) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = canonical(value)
    with path.open("xb") as stream:
        stream.write(body)
        stream.flush()
        os.fsync(stream.fileno())
    return digest(body)


def _checkpoint(root: Path, plan: Mapping[str, Any], entry: Mapping[str, Any], *,
                event_sha256: str, completed_keys: list[str], previous_checkpoint_sha256: str | None) -> str:
    value = {
        "artifact_kind": "RATE_FUNDAMENTAL_FIRST_REFRESH_EXECUTION_CHECKPOINT_V1",
        "request_plan_sha256": plan["request_plan_sha256"],
        "last_completed_ordinal": entry["ordinal"],
        "completed_request_keys": list(completed_keys),
        "completed_request_keys_sha256": digest(completed_keys),
        "trusted_acquisition_ledger_head": event_sha256,
        "success_count": len(completed_keys),
        "terminal_failure_count": 0,
        "unknown_outcome_count": 0,
        "next_ordinal": entry["ordinal"] + 1 if entry["ordinal"] < 1984 else None,
        "current_main": plan["execution_main_sha"],
        "authority_id": plan["authority_id"],
        "previous_checkpoint_sha256": previous_checkpoint_sha256,
        "auto_resume_allowed": False,
    }
    body_hash = digest(value)
    path = root / "execution-checkpoints" / f"{entry['ordinal']:04d}-{body_hash}.json"
    _write_immutable(path, value)
    return body_hash



def verify_checkpoint(path: str | Path, plan: Mapping[str, Any], expected_previous: str | None) -> dict:
    path = Path(path)
    body = path.read_bytes()
    value = read_metadata(body)
    require(path.name.endswith(digest(body) + ".json"), "FIRST_REFRESH_CHECKPOINT_TAMPER")
    require(value.get("artifact_kind") == "RATE_FUNDAMENTAL_FIRST_REFRESH_EXECUTION_CHECKPOINT_V1"
            and value.get("request_plan_sha256") == plan["request_plan_sha256"]
            and value.get("current_main") == plan["execution_main_sha"]
            and value.get("authority_id") == plan["authority_id"]
            and value.get("previous_checkpoint_sha256") == expected_previous
            and value.get("auto_resume_allowed") is False,
            "FIRST_REFRESH_CHECKPOINT_BINDING")
    ordinal = value.get("last_completed_ordinal")
    require(isinstance(ordinal, int) and 1 <= ordinal <= 1984
            and value.get("completed_request_keys") == [row["request_key"] for row in plan["entries"][:ordinal]]
            and value.get("completed_request_keys_sha256") == digest(value["completed_request_keys"]),
            "FIRST_REFRESH_CHECKPOINT_SEQUENCE")
    return value


def resume_execution(*args, **kwargs):
    require(False, "FIRST_REFRESH_RESUME_REQUIRES_CONTROL_CENTER_CONTINUATION")


def execute_authorized_first_refresh(plan: Mapping[str, Any], universe: Mapping[str, Any], authorization: Mapping[str, Any],
                                     *, authority_root: str | Path, authority_sha256: str,
                                     execution_root: str | Path, captures: Mapping[str, Any],
                                     expected_previous_latest: str | None,
                                     artifacts_root: str | Path,
                                     dispatch_gate, clock,
                                     acquire=None, create_store=None, main_guard=None) -> dict:
    """Live-capable owner. It cannot run without a separately sealed J2 authorization."""
    validate_plan(plan, universe, plan["authority_id"], plan["execution_main_sha"])
    main_guard = main_guard or (lambda: current_main_guard(plan))
    main_guard()
    _actual_latest_precheck(artifacts_root, expected_previous_latest)
    validate_execution_authorization(authorization, plan, expected_previous_latest, artifacts_root=artifacts_root)
    claim_authorization(authorization, plan, artifacts_root=artifacts_root, execution_root=execution_root,
                        expected_previous_latest=expected_previous_latest, clock=clock)
    root = Path(execution_root)
    from scripts.run_prospective_provider_activation import acquire_once as accepted_acquire, create as accepted_create, replay
    acquire = acquire or accepted_acquire
    create_store = create_store or accepted_create
    config_sha256 = create_store(root, authority_root, authority_sha256, universe,
                                 {"base_sha": plan["execution_main_sha"], "head_sha": plan["execution_main_sha"]})
    _write_immutable(root / "REQUEST_PLAN.json", plan)
    (root / "execution-checkpoints").mkdir()
    completed_keys, observations = [], []
    trusted_head = None
    prior_checkpoint = None
    try:
        for entry in plan["entries"]:
            main_guard()
            capture = captures.get(entry["provider"])
            require(callable(capture), "FIRST_REFRESH_CAPTURE_OWNER_MISSING")
            gate = PlanDispatchGate(plan, entry, dispatch_gate)
            new_head = acquire(root, config_sha256, trusted_head, entry["provider"], entry["target"], capture,
                               gate=gate, clock=clock)
            event_path = next(path for path in (root / "events").iterdir()
                              if path.name.endswith(new_head + ".json"))
            event = read_metadata(event_path.read_bytes())
            intent_path = root / "intents" / (event["intent_id"] + ".json")
            intent = read_metadata(intent_path.read_bytes())
            require(intent["dispatch"]["plan_binding"] == gate._binding(), "FIRST_REFRESH_EXECUTED_INTENT_NOT_PLAN_BOUND")
            completed_keys.append(entry["request_key"])
            prior_checkpoint = _checkpoint(root, plan, entry, event_sha256=new_head,
                                           completed_keys=completed_keys,
                                           previous_checkpoint_sha256=prior_checkpoint)
            observations.append({
                "ordinal": entry["ordinal"],
                "request_key": entry["request_key"],
                "intent_id": event["intent_id"],
                "intent": intent,
                "event_sha256": new_head,
                "record": event["record"],
            })
            trusted_head = new_head
        config, auth, replayed = replay(root, config_sha256, trusted_head, clock())
        require(len(replayed) == 1984 and auth["authority_id"] == plan["authority_id"],
                "FIRST_REFRESH_FINAL_REPLAY_INCOMPLETE")
        snapshot = assemble_fundamental(plan, universe, observations)
        publication = publish_fundamental_atomic(snapshot, artifacts_root=artifacts_root,
                                                 expected_previous_latest=expected_previous_latest)
        return {
            "status": "PASS",
            "planned_requests": 1984,
            "actual_requests": 1984,
            "request_plan_sha256": plan["request_plan_sha256"],
            "trusted_acquisition_ledger_head": trusted_head,
            "fundamental_snapshot_id": snapshot["fundamental_snapshot_id"],
            "publication": publication,
            "ranking_executed": False,
            "decision_state_mutations": 0,
            "portfolio_mutations": 0,
            "ledger_mutations": 0,
            "fallback_used": False,
        }
    except Exception as exc:
        stop = {
            "artifact_kind": "RATE_FUNDAMENTAL_FIRST_REFRESH_STOP_V1",
            "request_plan_sha256": plan["request_plan_sha256"],
            "completed_request_count": len(completed_keys),
            "next_ordinal": len(completed_keys) + 1,
            "reason": type(exc).__name__,
            "message": str(exc),
            "automatic_retry_allowed": False,
            "automatic_resume_allowed": False,
            "fallback_allowed": False,
        }
        try:
            _write_immutable(root / "FIRST_REFRESH_STOP.json", stop)
        except FileExistsError:
            pass
        raise
