"""Opt-in, non-production eligibility overlay over existing owner verdicts.

This is not a financial parser, factor calculator, ranking owner or trade owner.
Readiness never authorizes a provider, warmup, publication or order.
"""
from collections import Counter
from copy import deepcopy
from decimal import Decimal
from pathlib import Path

from .eps_duration_facts.model import Rejected, require
from .eps_duration_facts.raw import sha256
from .provider_eps_candidate import WINDOW, _canonical, _decimal, _time
from .provider_eps_metadata import read_metadata

VERSION = "RATE_FUNDAMENTAL_ELIGIBILITY_SUBGATE_V1"
KIND = "FUNDAMENTAL_ELIGIBILITY_ENGINEERING_ONLY"
COUNTS = {"TWSE": 1085, "TPEX": 893}
REVENUE_PERIODS = ("2026-07", "2026-08", "2026-09")
OWNERS = {
    "eps_8q": "EPS_PERIOD_EVIDENCE_OWNER",
    "revenue_3m": "OFFICIAL_REVENUE_EVIDENCE_OWNER",
    "formal_eps_period_identity": "FORMAL_EPS_QUALIFICATION_OWNER",
    "Fundamental": "src/fundamental.py",
    "Stage": "src/stage_evidence.py",
    "Rotation": "src/institutional_features.py",
    "M7": "src/rate_logic.py",
    "MHE": "src/rate_logic.py",
    "SmartMoney": "src/institutional_features.py",
    "RelativeStrength": "src/technical_features.py",
    "Liquidity": "src/technical_features.py",
}
STATUSES = {"PASS", "MISSING_REQUIRED_PERIOD", "NOT_EVALUATED", "NOT_AUTHORIZED",
            "UNDEFINED_ZERO_BASE", "BLOCKED_EXTERNAL", "INVALID_EVIDENCE", "NOT_COMPUTED"}
REQUIREMENTS = {
    "eps_ready": ("eps_8q",),
    "revenue_ready": ("revenue_3m",),
    "fundamental_ready": ("eps_8q", "revenue_3m", "formal_eps_period_identity", "Fundamental"),
    "stage_input_ready": ("Stage",),
    "rotation_input_ready": ("Rotation",),
    "m7_input_ready": ("M7",),
    "mhe_input_ready": ("MHE",),
}
RANK_INPUTS = {
    "top50": ("M7", "MHE", "Stage", "Rotation", "SmartMoney", "Fundamental", "RelativeStrength", "Liquidity"),
    "long": ("Fundamental", "Stage", "MHE", "SmartMoney", "RelativeStrength", "M7", "Liquidity"),
    "short": ("M7", "Rotation", "SmartMoney", "MHE", "Stage", "RelativeStrength", "Liquidity"),
}
FLAGS = {
    "production_eligible": False, "decision_eligible": False, "fallback_allowed": False,
    "formal_provider_activation": "NOT_AUTHORIZED", "warmup_activation": "NOT_AUTHORIZED",
    "warmup_acceptance": "UNCHANGED_NOT_PERFORMED", "historical_pit": "UNPROVEN",
    "full_production_acceptance": "NOT_ALLOWED",
    "external_authorized_intraday_feed_dependency": "BLOCKED_EXTERNAL",
    "original_eight_quarter_coverage_credit": 0,
}


def digest(value):
    return sha256(_canonical(value))


def read_pinned(path, expected_sha256):
    body = Path(path).read_bytes()
    require(isinstance(expected_sha256, str) and len(expected_sha256) == 64
            and sha256(body) == expected_sha256, "ELIGIBILITY_INPUT_HASH_MISMATCH")
    return read_metadata(body)


def _score_number(value):
    require(type(value) in (str, int, float, Decimal), "ELIGIBILITY_SCORE_INVALID")
    try:
        number = _decimal(str(value))
    except Rejected as exc:
        raise Rejected("ELIGIBILITY_SCORE_INVALID") from exc
    require(0 <= number <= 100, "ELIGIBILITY_SCORE_INVALID")
    return number


def _verdict(name, value, as_of):
    if value is None:
        return {"status": "MISSING_REQUIRED_PERIOD" if name in {"eps_8q", "revenue_3m"} else "NOT_EVALUATED",
                "reason": "OWNER_EVIDENCE_NOT_PROVIDED", "owner": OWNERS[name],
                "missing_periods": list(WINDOW if name == "eps_8q" else REVENUE_PERIODS if name == "revenue_3m" else ()),
                "evidence_references": []}
    require(isinstance(value, dict) and set(value) == {"status", "reason", "owner", "observed_at",
            "validated_at", "evidence_references", "period_statuses", "value", "population_id"},
            "ELIGIBILITY_VERDICT_SCHEMA_INVALID:" + name)
    require(value["owner"] == OWNERS[name] and value["status"] in STATUSES,
            "ELIGIBILITY_OWNER_OR_STATUS_INVALID:" + name)
    require(_time(value["observed_at"]) <= _time(value["validated_at"]) <= _time(as_of),
            "ELIGIBILITY_EVIDENCE_NOT_YET_AVAILABLE:" + name)
    require(isinstance(value["evidence_references"], list) and value["evidence_references"],
            "ELIGIBILITY_OWNER_PROVENANCE_REQUIRED:" + name)
    for ref in value["evidence_references"]:
        require(isinstance(ref, dict) and set(ref) == {"path", "sha256", "json_locator"}
                and isinstance(ref["path"], str) and bool(ref["path"])
                and isinstance(ref["sha256"], str) and len(ref["sha256"]) == 64
                and all(c in "0123456789abcdef" for c in ref["sha256"])
                and isinstance(ref["json_locator"], str) and ref["json_locator"].startswith("$"),
                "ELIGIBILITY_REFERENCE_INVALID")
    passed = value["status"] == "PASS"
    require(value["reason"] is None if passed else isinstance(value["reason"], str) and bool(value["reason"]),
            "ELIGIBILITY_MISSING_REASON_REQUIRED:" + name)
    periods = WINDOW if name == "eps_8q" else REVENUE_PERIODS if name == "revenue_3m" else ()
    require(isinstance(value["period_statuses"], dict) and set(value["period_statuses"]) == set(periods),
            "ELIGIBILITY_REQUIRED_WINDOW_MISMATCH:" + name)
    require(all(status in STATUSES for status in value["period_statuses"].values()), "ELIGIBILITY_PERIOD_STATUS_INVALID")
    if periods:
        require(passed == all(status == "PASS" for status in value["period_statuses"].values()),
                "ELIGIBILITY_PERIOD_VERDICT_CONFLICT:" + name)
    if name not in {"eps_8q", "revenue_3m", "formal_eps_period_identity"}:
        require(value["population_id"] is not None, "ELIGIBILITY_COMPONENT_POPULATION_REQUIRED:" + name)
        require(value["value"] is None if not passed else value["value"] is not None,
                "ELIGIBILITY_COMPONENT_VALUE_CONFLICT:" + name)
        if passed:
            _score_number(value["value"])
    else:
        require(value["value"] is None and value["population_id"] is None, "ELIGIBILITY_NON_SCORE_VALUE_FORBIDDEN")
    return {**deepcopy(value), "missing_periods": [p for p in periods if value["period_statuses"][p] != "PASS"]}


def issuer_eligibility(row, *, symbol, market, as_of, population_id):
    require(isinstance(row, dict) and set(row) == {"symbol", "market", "inputs"}
            and row["symbol"] == symbol and row["market"] == market, "ELIGIBILITY_ISSUER_IDENTITY_MISMATCH")
    require(isinstance(row["inputs"], dict) and not set(row["inputs"]) - set(OWNERS), "ELIGIBILITY_UNKNOWN_INPUT")
    verdicts = {name: _verdict(name, row["inputs"].get(name), as_of) for name in OWNERS}
    for name, verdict in verdicts.items():
        if verdict.get("population_id") is not None:
            require(verdict["population_id"] == population_id, "ELIGIBILITY_COMPONENT_POPULATION_MISMATCH:" + name)
    ready = lambda names: all(verdicts[name]["status"] == "PASS" for name in names)
    state = {"symbol": symbol, "market": market, "universe_eligible": True,
             **{name: ready(inputs) for name, inputs in REQUIREMENTS.items()}}
    fundamental_reasons = [{"input": name, "status": verdicts[name]["status"], "reason": verdicts[name]["reason"],
                            "missing_periods": verdicts[name]["missing_periods"]}
                           for name in REQUIREMENTS["fundamental_ready"] if verdicts[name]["status"] != "PASS"]
    state["fundamental_status"] = ("PASS" if not fundamental_reasons else "MISSING_REQUIRED_PERIOD"
        if any(r["status"] == "MISSING_REQUIRED_PERIOD" for r in fundamental_reasons) else "BLOCKED_REQUIRED_INPUT")
    state["fundamental_missing_reasons"] = fundamental_reasons
    rankings = {}
    for kind, inputs in RANK_INPUTS.items():
        eligible = ready(inputs) and (kind == "short" or state["fundamental_ready"])
        state[{"top50": "top50_input_ready", "short": "short_rank_input_ready", "long": "long_rank_input_ready"}[kind]] = eligible
        reasons = [{"input": name, "status": verdicts[name]["status"], "reason": verdicts[name]["reason"]}
                   for name in inputs if verdicts[name]["status"] != "PASS"]
        if kind != "short":
            reasons += [r for r in fundamental_reasons if r["input"] not in inputs]
        rankings[kind] = {"ranking_eligible": eligible, "score": None, "rank": None,
                          "status": "INPUT_READY_NOT_CALCULATED" if eligible else "INELIGIBLE_REQUIRED_INPUT",
                          "missing_reasons": reasons}
    return {**state, "input_verdicts": verdicts, "ranking_gates": rankings}


def gate_owner_ranking(row, *, kind, owner_result, symbol, market, as_of, population_id):
    """Mask an existing ranking owner's result; never calculate or reweight it."""
    require(kind in RANK_INPUTS, "ELIGIBILITY_RANKING_KIND_INVALID")
    gate = issuer_eligibility(row, symbol=symbol, market=market, as_of=as_of, population_id=population_id)["ranking_gates"][kind]
    if not gate["ranking_eligible"]:
        return gate
    require(isinstance(owner_result, dict) and set(owner_result) == {"score", "rank"}, "ELIGIBILITY_OWNER_RANKING_REQUIRED")
    _score_number(owner_result["score"])
    require(type(owner_result["rank"]) is int and 1 <= owner_result["rank"] <= sum(COUNTS.values()),
            "ELIGIBILITY_OWNER_RANKING_INVALID")
    return {**gate, **deepcopy(owner_result), "status": "OWNER_RESULT_PRESERVED_ENGINEERING_ONLY"}


def _held_symbols(context):
    symbols = set()
    for key in ("roy_portfolio", "ai_paper_portfolio"):
        account = context[key]
        if isinstance(account, dict):
            keys = [k for k in ("positions", "position_lots", "holdings") if k in account]
            require(len(keys) == 1, "ELIGIBILITY_HELD_POSITION_SCHEMA_INVALID")
            positions = account[keys[0]]
        else:
            positions = account
        require(isinstance(positions, list), "ELIGIBILITY_HELD_POSITION_SCHEMA_INVALID")
        for position in positions:
            require(isinstance(position, dict) and isinstance(position.get("symbol"), str) and position["symbol"],
                    "ELIGIBILITY_HELD_POSITION_SCHEMA_INVALID")
            symbols.add(position["symbol"])
    return symbols


def verify_overlay(value):
    require(isinstance(value, dict) and set(value) == {"artifact_kind", "snapshot_id", "content_sha256", "core", "generated_at"},
            "ELIGIBILITY_OVERLAY_SCHEMA_INVALID")
    require(value["artifact_kind"] == KIND and value["content_sha256"] == digest(value["core"])
            and value["snapshot_id"] == "rate-eligibility-" + value["content_sha256"], "ELIGIBILITY_OVERLAY_TAMPERED")
    require(value["core"].get("version") == VERSION and value["core"].get("governance") == FLAGS,
            "ELIGIBILITY_GOVERNANCE_INVALID")
    require(_time(value["generated_at"]) >= _time(value["core"]["as_of"]), "ELIGIBILITY_GENERATION_TIME_INVALID")
    return value


def build_overlay(bundle, universe, *, expected_bundle_sha256, expected_universe_sha256,
                  context, previous=None, generated_at):
    require(digest(bundle) == expected_bundle_sha256 and digest(universe) == expected_universe_sha256,
            "ELIGIBILITY_TRUSTED_BINDING_MISMATCH")
    require(set(bundle) == {"artifact_kind", "universe_id", "as_of", "rows"}
            and bundle["artifact_kind"] == "RATE_OWNER_INPUT_VERDICTS_V1", "ELIGIBILITY_BUNDLE_SCHEMA_INVALID")
    require(universe.get("verification_status") == "PASS" and bundle["universe_id"] == universe["catalogue_id"],
            "ELIGIBILITY_UNIVERSE_BINDING_MISMATCH")
    stocks = universe["stocks"]
    require(len({s["symbol"] for s in stocks}) == len(stocks)
            and dict(Counter(s["market"] for s in stocks)) == COUNTS, "ELIGIBILITY_EXACT_UNIVERSE_REQUIRED")
    require(_time(bundle["as_of"]) <= _time(generated_at), "ELIGIBILITY_GENERATION_TIME_INVALID")
    require(isinstance(context, dict) and {"current_state_id", "issuer_history", "roy_portfolio",
            "ai_paper_portfolio", "transaction_ledger"}.issubset(context), "ELIGIBILITY_CONTINUITY_CONTEXT_REQUIRED")
    require(isinstance(context["current_state_id"], str) and bool(context["current_state_id"]),
            "ELIGIBILITY_PREVIOUS_STATE_ID_REQUIRED")
    held = _held_symbols(context)
    expected = {s["symbol"]: s["market"] for s in stocks}
    require(isinstance(bundle["rows"], list) and len(bundle["rows"]) == len(expected)
            and {r.get("symbol") for r in bundle["rows"]} == set(expected), "ELIGIBILITY_ISSUER_DROPPED_OR_DUPLICATED")
    old = {}
    if previous is not None:
        verify_overlay(previous)
        core = previous["core"]
        require(core["universe_sha256"] == expected_universe_sha256 and core["universe_id"] == bundle["universe_id"],
                "ELIGIBILITY_PREVIOUS_UNIVERSE_MISMATCH")
        require(core["continuity_context"] == context, "ELIGIBILITY_ACCOUNT_OR_ISSUER_HISTORY_MUTATION")
        require(_time(core["as_of"]) <= _time(bundle["as_of"]), "ELIGIBILITY_TIME_BACKFILL_FORBIDDEN")
        old = {r["symbol"]: r for r in core["issuers"]}
        require(set(old) == set(expected), "ELIGIBILITY_PREVIOUS_ISSUER_SET_INVALID")
    issuers = []
    for row in sorted(bundle["rows"], key=lambda r: r["symbol"]):
        state = issuer_eligibility(row, symbol=row["symbol"], market=expected[row["symbol"]],
                                  as_of=bundle["as_of"], population_id=bundle["universe_id"])
        state["held_position_status"] = ("RANKING_INELIGIBLE_HELD_POSITION"
            if row["symbol"] in held and not all(g["ranking_eligible"] for g in state["ranking_gates"].values())
            else "NO_ELIGIBILITY_TRADE_ACTION")
        history = deepcopy(old.get(row["symbol"], {}).get("eligibility_history", []))
        history.append({"as_of": bundle["as_of"], "evidence_bundle_sha256": expected_bundle_sha256,
                        "readiness": {k: v for k, v in state.items() if k.endswith("_ready")},
                        "fundamental_status": state["fundamental_status"]})
        issuers.append({**state, "eligibility_history": history})
    core = {"version": VERSION, "governance": deepcopy(FLAGS), "universe_id": bundle["universe_id"],
            "universe_sha256": expected_universe_sha256, "as_of": bundle["as_of"],
            "input_bundle_sha256": expected_bundle_sha256,
            "previous_eligibility_snapshot_id": previous["snapshot_id"] if previous else None,
            "previous_eligibility_content_sha256": previous["content_sha256"] if previous else None,
            "previous_decision_state_id": context["current_state_id"],
            "continuity_context": deepcopy(context), "issuers": issuers,
            "counts": {"universe": len(issuers), **{k: sum(r[k] for r in issuers) for k in
                ("eps_ready", "revenue_ready", "fundamental_ready", "short_rank_input_ready",
                 "long_rank_input_ready", "top50_input_ready", "stage_input_ready", "rotation_input_ready", "m7_input_ready", "mhe_input_ready")}}}
    identity = digest(core)
    return verify_overlay({"artifact_kind": KIND, "snapshot_id": "rate-eligibility-" + identity,
                           "content_sha256": identity, "core": core, "generated_at": generated_at})


def replay_references(bundle):
    """Byte integrity only. The existing owner is still responsible for its verdict."""
    checked = {}
    for row in bundle["rows"]:
        for verdict in row["inputs"].values():
            for ref in verdict["evidence_references"]:
                path = str(Path(ref["path"]).resolve())
                if path in checked:
                    require(checked[path] == ref["sha256"], "ELIGIBILITY_REFERENCE_CONFLICT")
                else:
                    require(sha256(Path(path).read_bytes()) == ref["sha256"], "ELIGIBILITY_SOURCE_HASH_MISMATCH")
                    checked[path] = ref["sha256"]
    return checked
