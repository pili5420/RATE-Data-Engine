"""Offline first-refresh readiness. No acquisition, scoring or publication owner."""
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
import os
from pathlib import Path

from .eps_duration_facts.model import require
from .eps_duration_facts.raw import sha256
from .provider_eps_candidate import _canonical, _time
from .provider_eps_metadata import read_metadata

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = "docs/contracts/RATE_FIRST_REFRESH_READINESS_V1.json"
CONTRACT = read_metadata((ROOT / CONTRACT_PATH).read_bytes())
DATASETS = CONTRACT["providers"]


def identity(value):
    return sha256(_canonical(value))


def exact_universe(universe, trusted_universe):
    require(universe == trusted_universe and universe["verification_status"] == "PASS", "REFRESH_EXACT_UNIVERSE_MISMATCH")
    stocks = universe["stocks"]
    require(len(stocks) == 1978 and len({r["symbol"] for r in stocks}) == 1978
            and Counter(r["market"] for r in stocks) == {"TWSE": 1085, "TPEX": 893}, "REFRESH_UNIVERSE_INVALID")
    return {r["symbol"]: r["market"] for r in stocks}


def evidence_boundary(record, authority, as_of):
    require(record["provider"] in DATASETS and record["dataset"] == DATASETS[record["provider"]], "REFRESH_PROVIDER_MISMATCH")
    require(record["authority_id"] == authority["authority_id"]
            and record["activation_timestamp"] == authority["activation_timestamp"]
            and record["provider_authorization"] == "AUTHORIZED_PROSPECTIVE_ONLY"
            and record["prospective_evidence_credit"] is True, "REFRESH_AUTHORITY_MISMATCH")
    times = [_time(v) for v in (authority["activation_timestamp"], record["requested_at"], record["received_at"],
        record["validation_timestamp"], record["first_seen_at"], as_of)]
    require(all(a <= b for a, b in zip(times, times[1:])) and times[-1] <= datetime.now(timezone.utc),
            "REFRESH_PRE_ACTIVATION_OR_FUTURE_TIME")
    require(record["source_observed_at"] == record["received_at"] and record["original_publication_timestamp"] is None
            and record["historical_pit"] == "UNPROVEN" and record["original_eight_quarter_coverage_credit"] == 0
            and record["fallback_allowed"] is False and record["production_eligible"] is False,
            "REFRESH_HISTORICAL_OR_FALLBACK_PROMOTION")
    require(record["source_identity_gate"] == "PASS", "REFRESH_SOURCE_VALIDATION_FAILED")
    return "AUTHORIZED_PROSPECTIVE_EVIDENCE"


def provider_readiness(events, authority, recovery, as_of):
    require(recovery["runtime_status"] == "RECOVERED_FROM_KNOWN_TERMINAL_FAILURE"
            and recovery["authority_id"] == authority["authority_id"]
            and recovery["resolutions"] and all(r["outcome"] == "TERMINAL_FAILED_KNOWN_OUTCOME" for r in recovery["resolutions"]),
            "REFRESH_RECOVERY_MISMATCH")
    for event in events:
        evidence_boundary(event["record"], authority, as_of)
    result = {}
    for provider in DATASETS:
        selected = [e["record"] for e in events if e["record"]["provider"] == provider]
        scopes = Counter(identity(r["scope"]) for r in selected)
        ready = bool(scopes) and all(count >= 2 for count in scopes.values())
        result[provider] = {"status": "READY" if ready else "BLOCKED", "dataset": DATASETS[provider],
            "authorization": "AUTHORIZED_PROSPECTIVE_ONLY_EFFECTIVE", "authority_seal": "PASS",
            "real_acquisitions": len(selected), "scope_round_counts": dict(sorted(scopes.items())),
            "append_only_replay": "PASS", "known_failure_recovery": "AVAILABLE", "fallback": False, "automatic_retry": False}
    return result


def dry_run(universe, trusted_universe, events, authority, recovery, legacy, as_of, readiness_engine):
    """Inputs must already have passed source replay; CLI is the evidence boundary."""
    markets = exact_universe(universe, trusted_universe)
    require(legacy["classification"] == "LEGACY_HISTORICAL_PIT_UNPROVEN"
            and legacy["prospective_credit"] == 0 and legacy["historical_pit"] == "UNPROVEN", "REFRESH_LEGACY_PROMOTION")
    providers = provider_readiness(events, authority, recovery, as_of)
    receipts, snapshots = set(), set()
    latest = {}
    for event in events:
        r = event["record"]
        require(r["receipt_sha256"] not in receipts and r["immutable_snapshot_id"] not in snapshots, "REFRESH_DUPLICATE_OBSERVATION")
        receipts.add(r["receipt_sha256"]); snapshots.add(r["immutable_snapshot_id"])
        scope_key = identity(r["scope"])
        if scope_key in latest:
            require(_time(latest[scope_key]["record"]["first_seen_at"]) <= _time(r["first_seen_at"]), "REFRESH_OBSERVATION_ORDER")
        latest[scope_key] = event
    selected = [deepcopy(latest[key]) for key in sorted(latest)]
    for event in selected:
        event["record"]["rows"].sort(key=lambda row: (row["symbol"], row["period"]))
    for event in selected:
        r = event["record"]
        required = CONTRACT["eps_periods"] if r["provider"] == "FinMind" else [r["target"]["period"]]
        require(r["required_periods"] == required, "REFRESH_REQUIRED_PERIOD_MISMATCH")
        expected = [r["target"]["symbol"]] if r["provider"] == "FinMind" else sorted(s for s, m in markets.items() if m == r["target"]["market"])
        require(r["expected_symbols"] == expected, "REFRESH_EXPECTED_ISSUER_MISMATCH")
        keys = set()
        for row in r["rows"]:
            require(row["symbol"] in expected and markets.get(row["symbol"]) == row["market"]
                    and row["period"] in required, "REFRESH_ROW_IDENTITY_OR_PERIOD")
            key = (row["symbol"], row["period"])
            require(key not in keys, "REFRESH_DUPLICATE_PERIOD"); keys.add(key)
            if row["numeric_status"] == "VALID_NUMERIC":
                require(isinstance(row["value"], str) and Decimal(row["value"]).is_finite(), "REFRESH_NONFINITE_VALUE")
            else:
                require(r["provider"] == "MOPS Official" and row["numeric_status"] == "UNDEFINED_ZERO_BASE"
                        and row["value"] is None, "REFRESH_INVALID_NUMERIC_STATUS")
    matrix = readiness_engine({"universe": universe}, selected)
    for issuer in matrix:
        issuer["issuer_status"] = issuer["fundamental_input_status"]
        issuer["feature_inputs"] = {"eps": {}, "revenue": {}}
        for event in selected:
            r = event["record"]
            for row in r["rows"]:
                if row["symbol"] == issuer["symbol"]:
                    ref = {**deepcopy(row), "provider": r["provider"], "dataset": r["dataset"],
                        "raw_sha256": r["raw_sha256"], "receipt_sha256": r["receipt_sha256"],
                        "immutable_snapshot_id": r["immutable_snapshot_id"], "observed_at": r["source_observed_at"],
                        "first_seen_at": r["first_seen_at"], "evidence_class": "AUTHORIZED_PROSPECTIVE_EVIDENCE"}
                    issuer["feature_inputs"]["eps" if r["provider"] == "FinMind" else "revenue"][row["period"]] = ref
        issuer["score"] = None; issuer["rank"] = None
    counts = {market: {"universe": sum(r["market"] == market for r in matrix),
        "eps_ready": sum(r["market"] == market and r["eps_status"] == "READY" for r in matrix),
        "revenue_ready": sum(r["market"] == market and r["revenue_status"] == "READY" for r in matrix),
        "fundamental_ready": sum(r["market"] == market and r["issuer_status"] == "READY" for r in matrix)} for market in ("TWSE", "TPEX")}
    core = {"artifact_kind": "RATE_FIRST_REFRESH_READINESS_DRY_RUN_V1", "contract_sha256": identity(CONTRACT),
        "universe_identity": identity(universe), "universe": universe, "providers": providers, "issuers": matrix,
        "market_counts": counts, "legacy_boundary": deepcopy(legacy),
        "latest_scope_snapshots": sorted(e["record"]["immutable_snapshot_id"] for e in selected),
        "historical_pit": "UNPROVEN", "production_eligible": False, "first_refresh_execution_allowed": False,
        "original_eight_quarter_coverage_credit": 0, "fallback_allowed": False,
        "ranking_activation_allowed": False, "intraday_dependency": "BLOCKED_EXTERNAL"}
    return {"core": core, "content_sha256": identity(core)}


def transaction_design(expected_latest, actual_latest, stages):
    """Pure proposal. This module cannot publish, including when all stages pass."""
    require(expected_latest == actual_latest, "REFRESH_STALE_PRODUCTION_LATEST")
    require(set(stages) == set(CONTRACT["transaction_stages"]) - {"Publish"}, "REFRESH_TRANSACTION_STAGES")
    require(all(v in {"PASS", "FAIL", "PENDING"} for v in stages.values()), "REFRESH_TRANSACTION_STAGE_INVALID")
    failures = [s for s in CONTRACT["transaction_stages"][:-1] if stages[s] != "PASS"]
    return {"stages": deepcopy(stages), "publish_allowed": False,
        "status": "FAIL_CLOSED" if failures else "BLOCKED_FIRST_REFRESH_NOT_AUTHORIZED",
        "failed_stages": failures, "production_latest_before": actual_latest, "production_latest_after": actual_latest,
        "partial_publication_allowed": False, "transaction_design": CONTRACT["transaction_design"],
        "requirements": ["SEPARATE_EXECUTION_AND_PUBLICATION_AUTHORIZATION", "IMMUTABLE_COMPLETE_STAGING_MANIFEST",
            "SOURCE_REPLAY_AND_INDEPENDENT_VERIFY", "SINGLE_WRITER_LOCK", "COMPARE_AND_SWAP_CURRENT_LATEST",
            "FLUSH_AND_FSYNC_OBJECTS_BEFORE_SINGLE_ATOMIC_POINTER_REPLACE", "NO_MULTI_POINTER_PARTIAL_COMMIT",
            "FAILURE_BEFORE_REPLACE_PRESERVES_PREVIOUS_SNAPSHOT"],
        "implementation_status": "QUALIFIED_ATOMIC_OWNER_PRESENT_EXECUTION_NOT_AUTHORIZED"}


def publication_readiness():
    """Qualify the merged atomic publication owner without authorizing execution."""
    import ast
    from . import production_refresh_commit as refresh
    owner_path = ROOT / "scripts/publish_production_source_bundle_latest.py"
    owner_body = owner_path.read_bytes()
    atomic_contract = read_metadata((ROOT / "docs/contracts/RATE_ATOMIC_PUBLICATION_OWNER_V1.json").read_bytes())
    diagnostic_contract = read_metadata((ROOT / "docs/contracts/RATE_CER078_NATIVE_QUALIFICATION_V1.json").read_bytes())
    require(atomic_contract["owner"] == owner_path.relative_to(ROOT).as_posix()
            and atomic_contract["authoritative_pointer"] == refresh.LATEST
            and atomic_contract["authoritative_commit_points"] == 1
            and atomic_contract["compatibility_authoritative"] is False
            and atomic_contract["first_refresh_authorized"] is False
            and atomic_contract["historical_pit"] == "UNPROVEN", "REFRESH_ATOMIC_CONTRACT_INVALID")
    require(diagnostic_contract["root_cause"] == "UNRESOLVED"
            and diagnostic_contract["historical_classification"] == "UNRESOLVED_HISTORICAL_NONREPRODUCIBLE"
            and diagnostic_contract["disposition_if_reproduction_and_forward_diagnostics_pass"]
                == "HISTORICAL_NONREPRODUCIBLE_DISPOSITION_ACCEPTED"
            and diagnostic_contract["first_refresh_authorized"] is False, "REFRESH_CER078_DISPOSITION_INVALID")
    tree = ast.parse(owner_body.decode("utf-8-sig"))
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "publish_latest")
    commit_calls = [call for call in ast.walk(function) if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute) and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "refresh" and call.func.attr == "commit"]
    direct_latest_writes = [call for call in ast.walk(function) if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Name) and call.func.id == "atomic_write_json"
        and call.args and isinstance(call.args[0], ast.Name) and call.args[0].id == "latest_path"]
    compatibility_writes = [call for call in ast.walk(function) if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Name) and call.func.id == "atomic_write_json"
        and call.args and isinstance(call.args[0], ast.Name) and call.args[0].id == "manifest_latest_path"]
    require(len(commit_calls) == 1 and not direct_latest_writes and len(compatibility_writes) == 1,
            "REFRESH_ATOMIC_OWNER_STRUCTURE_INVALID")
    return {"status": "PASS", "reason": "FIRST_REFRESH_ATOMIC_PUBLICATION_QUALIFIED",
        "owner": owner_path.relative_to(ROOT).as_posix(), "owner_sha256": sha256(owner_body),
        "commit_module": Path(refresh.__file__).resolve().relative_to(ROOT).as_posix(),
        "commit_module_sha256": sha256(Path(refresh.__file__).read_bytes()),
        "authoritative_pointer": refresh.LATEST, "authoritative_commit_points": 1,
        "compatibility_authoritative": False, "production_owner_modified_by_phase_jr": False,
        "cer078_historical_classification": diagnostic_contract["historical_classification"],
        "cer078_root_cause": diagnostic_contract["root_cause"],
        "cer078_historical_disposition": diagnostic_contract["disposition_if_reproduction_and_forward_diagnostics_pass"],
        "first_refresh_authorized": False}

class ReadOnlyGuard:
    """Allow new evidence output only; financial network and all other writes fail."""
    def __init__(self, output, portability_command=None):
        self.output = Path(output).resolve()
        self.portability_command = tuple(portability_command) if portability_command else None

    def write_path(self, path):
        require(isinstance(path, (str, bytes, os.PathLike)), "READINESS_WRITE_FD_FORBIDDEN")
        target = Path(os.fsdecode(path))
        require(target.is_absolute(), "READINESS_RELATIVE_WRITE_FORBIDDEN")
        require(not any(p.is_symlink() or (hasattr(p, "is_junction") and p.is_junction()) for p in (target, *target.parents))
                and target.resolve().is_relative_to(self.output), "READINESS_PROTECTED_WRITE_FORBIDDEN")

    def __call__(self, event, args):
        if event in {"socket.connect", "socket.getaddrinfo", "socket.sendto", "urllib.Request"}:
            raise RuntimeError("READINESS_NETWORK_FORBIDDEN")
        if event == "open":
            mode, flags = args[1], args[2]
            writing = (isinstance(mode, str) and any(c in mode for c in "wax+")) or (isinstance(flags, int) and flags &
                (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
            if writing: self.write_path(args[0])
        elif event in {"os.mkdir", "os.remove", "os.rmdir", "os.chmod", "os.utime"}:
            require(len(args) < 2 or event != "os.remove" or args[1] == -1, "READINESS_DIR_FD_FORBIDDEN")
            self.write_path(args[0])
        elif event in {"os.rename", "os.replace"}:
            self.write_path(args[0]); self.write_path(args[1])
        elif event in {"os.link", "os.symlink", "os.truncate"}:
            raise RuntimeError("READINESS_UNSAFE_MUTATION_FORBIDDEN")
        elif event == "subprocess.Popen":
            command = args[1]
            if isinstance(command, str):
                import shlex
                command = [part.strip('"') for part in shlex.split(command, posix=False)]
            if self.portability_command and tuple(command) == self.portability_command:
                require(isinstance(args[0], (str, os.PathLike))
                        and Path(args[0]).resolve() == Path(self.portability_command[0]).resolve()
                        and Path(args[2]).resolve() == ROOT, "READINESS_PORTABILITY_PROCESS_BINDING")
                return
            require(isinstance(command, (list, tuple)) and len(command) >= 2
                    and Path(command[0]).stem.lower() == "git"
                    and command[1] in {"rev-parse", "merge-base", "show", "rev-list", "cat-file", "status", "ls-files", "ls-tree"},
                    "READINESS_CHILD_EXECUTION_FORBIDDEN")
        elif event in {"os.system", "os.exec", "os.posix_spawn", "ctypes.dlopen"}:
            raise RuntimeError("READINESS_CHILD_EXECUTION_FORBIDDEN")
