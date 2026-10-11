"""Opt-in universe inventory acceptance, never Production warmup authorization."""
from collections import Counter
from copy import deepcopy

from src.eps_duration_facts.model import require
from src.fundamental_eligibility import (COUNTS, FLAGS as ELIGIBILITY_FLAGS, REVENUE_PERIODS,
    WINDOW, digest, issuer_eligibility, replay_references)
from src.provider_eps_candidate import _time

VERSION = "RATE_FULL_MARKET_WARMUP_MISSINGNESS_V1"
KIND = "WARMUP_INVENTORY_ACCEPTANCE_ONLY"
PROJECTION_SCOPE = "READ_ONLY_EXISTING_INPUT_EVIDENCE_NOT_FORMAL_SCORE_OR_STATE"
FLAGS = {"production_eligible": False, "decision_eligible": False, "fallback_allowed": False,
    "historical_pit": "UNPROVEN", "formal_provider_activation": "NOT_AUTHORIZED",
    "ranking_consumer_activation": "NOT_AUTHORIZED", "first_refresh": "NOT_AUTHORIZED",
    "production_publication": "NOT_AUTHORIZED", "full_production_acceptance": "NOT_ALLOWED",
    "live_warmup_execution": "NOT_AUTHORIZED", "original_eight_quarter_coverage_credit": 0,
    "external_authorized_intraday_feed_dependency": "BLOCKED_EXTERNAL"}
READINESS = ("eps_ready", "revenue_ready", "fundamental_ready", "top50_input_ready",
    "long_rank_input_ready", "short_rank_input_ready", "stage_input_ready", "rotation_input_ready",
    "m7_input_ready", "mhe_input_ready")
INVENTORY_STATUSES = {"PASS", "MISSING_REQUIRED_PERIOD", "UNDEFINED_ZERO_BASE"}


def _history(history, state):
    """Check owner certificate completeness, not a new EPS/revenue parser."""
    require(isinstance(history, dict) and history.get("symbol") == state["symbol"]
        and history.get("market") == state["market"] and history.get("market_universe_retained") is True
        and history.get("production_eligible") is False, "INVENTORY_HISTORY_IDENTITY_CONFLICT")
    valid = history["eps_valid_quarter_labels"]
    missing = history["eps_missing_quarters"]
    require(isinstance(valid, list) and isinstance(missing, list)
        and len(valid) == len(set(valid)) and len(missing) == len(set(missing))
        and set(valid).isdisjoint(missing) and set(valid) | set(missing) == set(WINDOW)
        and type(history["eps_valid_quarters"]) is int and history["eps_valid_quarters"] == len(valid),
        "INVENTORY_HISTORY_WINDOW_CONFLICT")
    eps = state["input_verdicts"]["eps_8q"]
    require(set(valid) == {p for p, s in eps["period_statuses"].items() if s == "PASS"}
        and history["eps8_calendar_window_complete"] is state["eps_ready"], "INVENTORY_HISTORY_READINESS_CONFLICT")
    references = history["eps_evidence_references"]
    require(len(references) == len(valid) and {r["quarter"] for r in references} == set(valid),
        "INVENTORY_PARTIAL_HISTORY_REFERENCE_CONFLICT")
    for ref in references:
        require(isinstance(ref.get("json_locator"), str) and ref["json_locator"].startswith("$")
            and isinstance(ref.get("raw_sha256"), str) and len(ref["raw_sha256"]) == 64
            and all(c in "0123456789abcdef" for c in ref["raw_sha256"])
            and bool(ref.get("receipt_reference")), "INVENTORY_PARTIAL_HISTORY_REFERENCE_INVALID")
        require(_time(ref["observed_at"]) <= _time(eps["validated_at"]), "INVENTORY_FUTURE_HISTORY")
    observations = history["three_revenue_observations"]
    require(len(observations) == len(REVENUE_PERIODS)
        and {r["period"] for r in observations} == set(REVENUE_PERIODS), "INVENTORY_REVENUE_WINDOW_CONFLICT")
    for observation in observations:
        status = state["input_verdicts"]["revenue_3m"]["period_statuses"][observation["period"]]
        require(type(observation["finite_numeric_present"]) is bool
            and observation["finite_numeric_present"] == (status == "PASS")
            and (status != "UNDEFINED_ZERO_BASE" or observation["numeric_status"] == "UNDEFINED_ZERO_BASE"),
            "INVENTORY_REVENUE_READINESS_CONFLICT")
    require(history["three_revenue_finite"] is state["revenue_ready"], "INVENTORY_HISTORY_READINESS_CONFLICT")


def _issuer(source, as_of, universe_id, market):
    require(source.get("market") == market, "INVENTORY_MARKET_IDENTITY_MISMATCH")
    inputs = {}
    for name, verdict in source["input_verdicts"].items():
        # Phase G materializes omitted owner verdicts. Keep them omitted on replay.
        if "observed_at" in verdict:
            inputs[name] = {k: deepcopy(v) for k, v in verdict.items() if k != "missing_periods"}
    require({"eps_8q", "revenue_3m"}.issubset(inputs), "INVENTORY_EXPLICIT_EVIDENCE_STATE_REQUIRED")
    for name, verdict in inputs.items():
        require(verdict["status"] != "INVALID_EVIDENCE", "INVENTORY_INVALID_OWNER_EVIDENCE")
        if name in {"eps_8q", "revenue_3m"}:
            require(verdict["status"] in INVENTORY_STATUSES
                and set(verdict["period_statuses"].values()).issubset(INVENTORY_STATUSES),
                "INVENTORY_UNAPPROVED_MISSING_REASON")
        if name == "eps_8q":
            require("UNDEFINED_ZERO_BASE" not in verdict["period_statuses"].values()
                and verdict["status"] != "UNDEFINED_ZERO_BASE", "INVENTORY_EPS_MISSING_REASON_INVALID")
    row = {"symbol": source["symbol"], "market": market, "inputs": inputs}
    state = issuer_eligibility(row, symbol=source["symbol"], market=market, as_of=as_of, population_id=universe_id)
    require(all(type(source.get(key)) is bool for key in (*READINESS, "universe_eligible"))
        and all(source.get(key) == value for key, value in state.items()), "INVENTORY_READINESS_STATE_CONFLICT")
    _history(source["original_source_issuer_evidence"], state)
    status = ("COMPLETE" if state["eps_ready"] and state["revenue_ready"] else "MISSING_REQUIRED_PERIOD"
        if any(v["status"] == "MISSING_REQUIRED_PERIOD" for v in (inputs["eps_8q"], inputs["revenue_3m"]))
        else "UNDEFINED_ZERO_BASE")
    return {"symbol": source["symbol"], "market": market, "accounting_status": status,
            "eligibility": state, "preserved_owner_evidence": deepcopy(source)}


def _counts(issuers):
    total = len(issuers)
    ready = {k: sum(r["eligibility"][k] for r in issuers) for k in READINESS}
    histories = [r["preserved_owner_evidence"]["original_source_issuer_evidence"] for r in issuers]
    return {"universe_accounted": total, "universe_expected": sum(COUNTS.values()), **ready,
        "eps_incomplete": total - ready["eps_ready"], "revenue_incomplete": total - ready["revenue_ready"],
        "fundamental_not_ready": total - ready["fundamental_ready"],
        "candidate_eps_revenue_input_intersection": sum(r["eligibility"]["eps_ready"] and r["eligibility"]["revenue_ready"] for r in issuers),
        "valid_eps_positions": sum(h["eps_valid_quarters"] for h in histories),
        "missing_eps_positions": sum(len(h["eps_missing_quarters"]) for h in histories),
        "incomplete_valid_eps_positions": sum(h["eps_valid_quarters"] for h in histories if not h["eps8_calendar_window_complete"])}


def build_inventory(projection, universe, *, expected_projection_sha256, expected_universe_sha256,
                    generated_at, context=None, previous=None):
    require(digest(projection) == expected_projection_sha256 and digest(universe) == expected_universe_sha256,
            "INVENTORY_TRUSTED_INPUT_MISMATCH")
    require(projection.get("scope") == PROJECTION_SCOPE and digest(projection.get("governance")) == digest(ELIGIBILITY_FLAGS),
            "INVENTORY_SOURCE_GOVERNANCE_INVALID")
    require(universe.get("verification_status") == "PASS" and projection["universe_binding"] == universe,
            "INVENTORY_UNIVERSE_BINDING_MISMATCH")
    stocks = universe["stocks"]
    expected = {s["symbol"]: s["market"] for s in stocks}
    require(len(expected) == len(stocks) and dict(Counter(expected.values())) == COUNTS,
            "INVENTORY_EXACT_UNIVERSE_REQUIRED")
    source = projection["issuers"]
    require(isinstance(source, list) and len(source) == len(expected)
        and {r["symbol"] for r in source} == set(expected), "INVENTORY_ISSUER_MISSING_OR_DUPLICATED")
    as_of = projection["generated_at"]
    require(_time(as_of) <= _time(generated_at), "INVENTORY_TIME_BACKFILL")
    if context is not None:
        require(isinstance(context, dict) and {"current_state_id", "issuer_history", "roy_portfolio",
            "ai_paper_portfolio", "transaction_ledger"}.issubset(context)
            and isinstance(context["current_state_id"], str) and bool(context["current_state_id"]),
            "INVENTORY_CONTINUITY_CONTEXT_INVALID")
    old = {}
    if previous is not None:
        verify_inventory(previous)
        core = previous["core"]
        require(core["universe_sha256"] == expected_universe_sha256 and core["continuity_context"] == context,
                "INVENTORY_STATE_OR_HISTORY_IDENTITY_CONFLICT")
        require(_time(core["as_of"]) <= _time(as_of) and _time(previous["generated_at"]) <= _time(generated_at),
                "INVENTORY_TIME_BACKFILL")
        old = {r["symbol"]: r for r in core["issuers"]}
    issuers = []
    for item in sorted(source, key=lambda r: r["symbol"]):
        result = _issuer(item, as_of, universe["catalogue_id"], expected[item["symbol"]])
        history = deepcopy(old.get(item["symbol"], {}).get("inventory_history", []))
        history.append({"as_of": as_of, "source_projection_sha256": expected_projection_sha256,
                        "owner_evidence_sha256": digest(item), "accounting_status": result["accounting_status"]})
        issuers.append({**result, "inventory_history": history})
    replay_references({"rows": [{"inputs": {name: verdict for name, verdict in r["eligibility"]["input_verdicts"].items()
        if "observed_at" in verdict}} for r in issuers]})
    counts = _counts(issuers)
    layers = {"FULL_MARKET_UNIVERSE_ACCOUNTING": "PASS",
        "FUNDAMENTAL_HISTORY_STATUS": {"eps_complete": counts["eps_ready"], "eps_incomplete": counts["eps_incomplete"],
            "revenue_complete": counts["revenue_ready"], "revenue_incomplete": counts["revenue_incomplete"],
            "fundamental_ready": counts["fundamental_ready"], "fundamental_not_ready": counts["fundamental_not_ready"]},
        "MODULE_READINESS_STATUS": "OWNER_VERDICTS_ONLY_NOT_EXECUTION_AUTHORIZATION",
        "RANKING_ELIGIBILITY_STATUS": "SUBGATE_VERDICTS_ONLY_CONSUMER_NOT_ACTIVATED",
        "PRODUCTION_PUBLICATION_STATUS": "NOT_AUTHORIZED"}
    core = {"version": VERSION, "governance": deepcopy(FLAGS), "universe_id": universe["catalogue_id"],
        "universe_sha256": expected_universe_sha256, "universe_binding": deepcopy(universe), "as_of": as_of,
        "source_projection_sha256": expected_projection_sha256, "layers": layers, "counts": counts,
        "by_market": {m: {**_counts([r for r in issuers if r["market"] == m]), "universe_expected": COUNTS[m]} for m in COUNTS},
        "continuity_context": deepcopy(context),
        "continuity_mode": "PINNED_CONTEXT_PRESERVED" if context is not None else "NOT_SUPPLIED_NOT_INITIALIZED",
        "previous_inventory_id": previous["snapshot_id"] if previous else None,
        "previous_inventory_sha256": previous["content_sha256"] if previous else None, "issuers": issuers}
    identity = digest(core)
    return {"artifact_kind": KIND, "snapshot_id": "rate-warmup-inventory-" + identity,
            "content_sha256": identity, "core": core, "generated_at": generated_at}


def verify_inventory(value):
    require(isinstance(value, dict) and set(value) == {"artifact_kind", "snapshot_id", "content_sha256", "core", "generated_at"}
        and value["artifact_kind"] == KIND and value["content_sha256"] == digest(value["core"])
        and value["snapshot_id"] == "rate-warmup-inventory-" + value["content_sha256"], "INVENTORY_ARTIFACT_TAMPERED")
    core = value["core"]
    require(core["version"] == VERSION and digest(core["governance"]) == digest(FLAGS), "INVENTORY_GOVERNANCE_INVALID")
    require(_time(value["generated_at"]) >= _time(core["as_of"]), "INVENTORY_TIME_BACKFILL")
    # Cold read reconstructs every gate and total; a recomputed digest alone is not acceptance.
    source = {"scope": PROJECTION_SCOPE, "governance": ELIGIBILITY_FLAGS, "generated_at": core["as_of"],
              "universe_binding": core["universe_binding"],
              "issuers": [r["preserved_owner_evidence"] for r in core["issuers"]]}
    replay = build_inventory(source, core["universe_binding"], expected_projection_sha256=digest(source),
        expected_universe_sha256=core["universe_sha256"], generated_at=value["generated_at"], context=core["continuity_context"])
    for key in ("layers", "counts", "by_market", "continuity_mode", "universe_id"):
        require(replay["core"][key] == core[key], "INVENTORY_ACCEPTANCE_STATE_CONFLICT")
    for original, rebuilt in zip(core["issuers"], replay["core"]["issuers"]):
        for key in ("symbol", "market", "eligibility", "accounting_status"):
            require(original[key] == rebuilt[key], "INVENTORY_ACCEPTANCE_STATE_CONFLICT")
        require(isinstance(original["inventory_history"], list) and bool(original["inventory_history"])
            and original["inventory_history"][-1] == {"as_of": core["as_of"],
                "source_projection_sha256": core["source_projection_sha256"],
                "owner_evidence_sha256": digest(original["preserved_owner_evidence"]),
                "accounting_status": original["accounting_status"]}, "INVENTORY_HISTORY_BINDING_INVALID")
    return value
