"""Phase 2 evaluation. Canonical state and calculation owners stay authoritative."""
from __future__ import annotations

import copy
import math
from datetime import date

from .cer074_acceptance import sha256
from .fundamental import calculate_fundamental
from .production_live_state import load_live_state, require
from .rate_logic import (calculate_m7, calculate_mhe, calculate_rotation,
                         calculate_smart_money, rank_candidates, rank_composites)
from .stage_evidence import build_production_stage_evidence
from .stage_history import build_stage_feature_histories

CONTINUITY = "PREVIOUS_VALIDATION_PASS_DECISION_STATE_SHORT_TERM_TOP30"
UNIVERSE = "FULL_TAIWAN_ELIGIBLE_MARKET_UNIVERSE"
EXTERNAL_FEED = "EXTERNAL_AUTHORIZED_INTRADAY_FEED_DEPENDENCY"
CADENCES = ("07:30", "09:30", "12:00", "19:30")


def _symbols(rows, reason):
    require(isinstance(rows, list), reason)
    symbols = [row.get("symbol") if isinstance(row, dict) else row for row in rows]
    require(all(isinstance(symbol, str) and symbol for symbol in symbols), reason)
    require(len(symbols) == len(set(symbols)), reason)
    return symbols


def _pass(payload, reason):
    require(isinstance(payload, dict), reason)
    require(all(payload.get(key) == "PASS" for key in
                ("validation_status", "source_status", "freshness_status")), reason)
    require(payload.get("blocked_dependencies") == [], reason)
    require(payload.get("fallback_used") is False, "FULL_MARKET_FALLBACK_FORBIDDEN")


def bind_full_universe(catalogue, contract, trading_date, previous_symbols):
    require(isinstance(contract, dict) and contract.get("artifact") == "RATE_FULL_MARKET_ROTATION_CONTRACT",
            "FULL_MARKET_CONTRACT_REQUIRED")
    require(contract.get("validation_status") == "PASS", "ELIGIBILITY_POLICY_AUTHORIZATION_REQUIRED")
    require(contract.get("candidate_universe_source") == UNIVERSE
            and contract.get("continuity_baseline_source") == CONTINUITY
            and contract.get("ranking_refresh_source") == "FULL_MARKET_SCAN"
            and contract.get("bootstrap_seed_normal_production_allowed") is False
            and contract.get("fallback_allowed") is False, "FULL_MARKET_CONTRACT_INVALID")
    policy_hash = contract.get("eligibility_policy_sha256")
    require(isinstance(contract.get("eligibility_policy_id"), str) and contract["eligibility_policy_id"]
            and isinstance(policy_hash, str) and len(policy_hash) == 64
            and all(ch in "0123456789abcdef" for ch in policy_hash), "ELIGIBILITY_POLICY_AUTHORIZATION_REQUIRED")
    _pass(catalogue, "FULL_MARKET_CATALOGUE_NOT_PASS")
    require(catalogue.get("universe_mode") == UNIVERSE
            and catalogue.get("valid_scope") == "NORMAL_PRODUCTION", "BOOTSTRAP_UNIVERSE_NOT_NORMAL_PRODUCTION")
    require(catalogue.get("trading_date") == trading_date, "FULL_MARKET_CATALOGUE_DATE_MISMATCH")
    require(catalogue.get("approved_by") == "CONTROL_CENTER"
            and catalogue.get("eligibility_policy_id") == contract["eligibility_policy_id"]
            and catalogue.get("eligibility_policy_sha256") == policy_hash, "ELIGIBILITY_POLICY_BINDING_INVALID")
    markets = catalogue.get("markets")
    require(isinstance(markets, list) and len(markets) == 2
            and sorted(item.get("market", "") for item in markets) == ["TPEX", "TWSE"],
            "FULL_MARKET_CATALOGUE_INCOMPLETE")
    symbols, seen, market_by_symbol = [], set(), {}
    for market in markets:
        rows = market.get("records")
        require(market.get("complete") is True and market.get("validation_status") == "PASS"
                and market.get("authority") == market["market"]
                and isinstance(rows, list) and rows and market.get("record_count") == len(rows)
                and market.get("records_sha256") == sha256(rows), "FULL_MARKET_CATALOGUE_INCOMPLETE")
        for row in rows:
            symbol = row.get("symbol")
            require(isinstance(symbol, str) and symbol and symbol not in seen, "FULL_MARKET_CATALOGUE_DUPLICATE_OR_INVALID")
            require(type(row.get("eligible")) is bool and isinstance(row.get("eligibility_reason"), str)
                    and bool(row["eligibility_reason"]), "ELIGIBILITY_DECISION_MISSING")
            seen.add(symbol)
            if row["eligible"]:
                symbols.append(symbol)
                market_by_symbol[symbol] = market["market"]
    require(len(symbols) > 30 and bool(set(symbols) - set(previous_symbols)), "PREVIOUS_TOP30_ONLY_UNIVERSE_FORBIDDEN")
    return sorted(symbols), market_by_symbol


def _history(rows, *, minimum, end, source, fields, date_key="trade_date"):
    require(isinstance(rows, list) and len(rows) >= minimum, "HISTORICAL_WARMUP_REQUIRED")
    dates = [row.get(date_key) for row in rows]
    require(all(isinstance(day, str) and date.fromisoformat(day).isoformat() == day for day in dates),
            "HISTORICAL_RECORD_INVALID")
    require(dates == sorted(dates) and len(dates) == len(set(dates)), "HISTORICAL_RECORD_DUPLICATE_OR_UNORDERED")
    require(dates[-1] == end if date_key == "trade_date" else dates[-1] <= end, "HISTORICAL_ASOF_BINDING_INVALID")
    for row in rows:
        allowed_sources = {source, source + "_STOCK_DAY", source + "_BENCHMARK_HISTORY",
                           source + " Official Historical Query", source + " Official Daily History"}
        require(row.get("source") in allowed_sources and row.get("source_timestamp")
                and row.get("synthetic") is not True and row.get("fallback_used") is not True,
                "OFFICIAL_HISTORY_REQUIRED")
        require(all(type(row.get(field)) in (int, float) and math.isfinite(row[field]) for field in fields),
                "HISTORICAL_RECORD_INVALID")


def derive_full_market_inputs(inputs, catalogue, contract, symbols, markets, trading_date, previous):
    _pass(inputs, "FULL_MARKET_INPUTS_NOT_PASS")
    require(inputs.get("artifact") == "RATE_FULL_MARKET_EOD_INPUTS"
            and inputs.get("trading_date") == trading_date and inputs.get("cadence") == "19:30",
            "FULL_MARKET_INPUT_BINDING_INVALID")
    require(inputs.get("catalogue_sha256") == sha256(catalogue)
            and inputs.get("contract_sha256") == sha256(contract), "FULL_MARKET_INPUT_BINDING_INVALID")
    require(isinstance(inputs.get("production_snapshot_id"), str) and inputs["production_snapshot_id"],
            "MISSING_PRODUCTION_SNAPSHOT_ID")
    require(isinstance(inputs.get("input_snapshot_id"), str) and inputs["input_snapshot_id"],
            "MISSING_INPUT_SNAPSHOT_ID")
    expected = set(symbols)
    stock, bench, inst, tdcc = (inputs.get(key) for key in
                              ("stock_histories", "benchmark_by_symbol", "institutional_histories", "tdcc_histories"))
    require(all(isinstance(group, dict) and set(group) == expected for group in (stock, bench, inst, tdcc)),
            "FULL_MARKET_INPUTS_INCOMPLETE")
    require(contract.get("market_history_minimum_sessions") == 180
            and contract.get("stage_history_sessions") == 7, "FULL_MARKET_HISTORY_CONTRACT_INVALID")
    for symbol in symbols:
        source = markets[symbol]
        _history(stock[symbol], minimum=180, end=trading_date, source=source,
                 fields=("open", "high", "low", "close", "volume", "turnover"))
        require(all(row.get("symbol") == symbol and row["close"] > 0
                    and row["volume"] >= 0 and row["turnover"] >= 0 for row in stock[symbol]), "HISTORICAL_RECORD_INVALID")
        _history(bench[symbol], minimum=180, end=trading_date, source=source, fields=("close",))
        require(all(row["close"] > 0 and row.get("benchmark_symbol") ==
                    ("TAIEX" if source == "TWSE" else "TPEX") for row in bench[symbol]), "BENCHMARK_MARKET_BINDING_INVALID")
        require(len(set(row["trade_date"] for row in stock[symbol]) &
                    set(row["trade_date"] for row in bench[symbol])) >= 180, "HISTORICAL_WARMUP_REQUIRED")
        _history(inst[symbol], minimum=26, end=trading_date, source=source,
                 fields=("foreign_net_shares", "investment_trust_net_shares", "close", "turnover"))
        require(all(row["close"] > 0 and row["turnover"] >= 0 for row in inst[symbol]), "HISTORICAL_RECORD_INVALID")
        _history(tdcc[symbol], minimum=5, end=trading_date, source="TDCC", fields=("holder_pct_400",), date_key="period_end")
    fundamental_rows = inputs.get("fundamental_records")
    require(set(_symbols(fundamental_rows, "FULL_MARKET_FUNDAMENTAL_INCOMPLETE")) == expected,
            "FULL_MARKET_FUNDAMENTAL_INCOMPLETE")
    for row in fundamental_rows:
        require(row.get("source") == "MOPS" and row.get("source_timestamp")
                and isinstance(row.get("as_of_date"), str) and row["as_of_date"] <= trading_date
                and row.get("synthetic") is not True, "OFFICIAL_FUNDAMENTAL_REQUIRED")
        for key, count in (("revenue_yoy", 3), ("quarterly_eps", 8)):
            require(isinstance(row.get(key), list) and len(row[key]) >= count, "HISTORICAL_WARMUP_REQUIRED")
            require(all(type(value) in (int, float) and math.isfinite(value) for value in row[key]), "FUNDAMENTAL_INPUT_INVALID")
    try:
        histories = build_stage_feature_histories(stock, bench, inst, tdcc, as_of_date=trading_date, sessions=7)
    except ValueError as exc:
        raise RuntimeError("HISTORICAL_WARMUP_REQUIRED:" + str(exc)) from exc
    fundamentals = {row["symbol"]: row for row in calculate_fundamental(copy.deepcopy(fundamental_rows))}
    require(set(fundamentals) == expected, "FULL_MARKET_FUNDAMENTAL_INCOMPLETE")
    prior_rows = previous["decision"].get("records", [])
    if previous["decision"].get("report_runtime_status") == "PARTIAL_VALID":
        from .public_official_partial_valid import validate_partial_state
        validate_partial_state(previous["decision"])
        prior_rows = previous["decision"]["previous_state_records"]
    prior = {"state_id": previous["current_state_id"], "symbols": {row["symbol"]:
             {"stage_current": (row.get("Stage_output") or {}).get("stage_current")} for row in prior_rows}}
    snapshot_id = inputs["input_snapshot_id"]
    records = []
    for symbol in symbols:
        latest = histories[symbol][-1]
        tf = latest["technical_features"]
        smart = calculate_smart_money({key: latest[key] for key in ("FI", "IT", "LH", "FC")})
        stage = build_production_stage_evidence(
            symbol=symbol, stock_history=stock[symbol], technical_record=latest["technical_record"],
            technical_features=tf, m7_score=latest["M7"], mhe_score=latest["MHE"], rotation_score=latest["Rotation"],
            prior_state=prior, input_snapshot_id=snapshot_id, feature_history=histories[symbol],
            control_state_id=previous["current_state_id"])
        m7_inputs = {key: tf[key] for key in ("PT", "PV", "MO", "RS")} | {key: latest[key] for key in ("FI", "IT", "LH")}
        mhe_inputs = {key: tf[key] for key in ("H5", "H20", "H60", "H120")}
        records.append({"symbol": symbol, "M7": calculate_m7(m7_inputs)["m7_score"],
                        "MHE": calculate_mhe(mhe_inputs)["mhe_score"], "SmartMoney": smart["smart_money_score"],
                        "Rotation": calculate_rotation(latest["Rotation_inputs"])["rotation_score"],
                        "Stage": stage["stage_normalized_score"], "Stage_output": stage,
                        "Fundamental": fundamentals[symbol]["Fundamental"],
                        "RelativeStrength": tf["RelativeStrength"], "Liquidity": tf["Liquidity"]})
    return records


def rank_full_market(records):
    rows = copy.deepcopy(records)
    for row in rows:
        row.update(rank_composites(row))
    # Preserve the existing owners' selection scope as well as their tie-breaks.
    return {"records": rows, "top50": rank_candidates(rows, "rate_composite_score", 50),
            "short_top30": rank_candidates(rows, "short_score", 30),
            "long_top30": rank_candidates(rows, "long_score", 30)}


def evaluate_rotation(*, state_root, previous_trading_date, previous_cadence, trading_date, cadence,
                      catalogue=None, inputs=None, contract=None, intraday_feed=None, verification_only=False,
                      first_refresh=False):
    result = {"artifact": "RATE_PHASE2_FULL_MARKET_ROTATION_REVIEW", "validation_status": "FAIL_CLOSED",
              "trading_date": trading_date, "cadence": cadence, "previous_state_preserved": True,
              "continuity_baseline_source": CONTINUITY, "candidate_universe_source": UNIVERSE,
              "ranking_refresh_source": "FULL_MARKET_SCAN", "blocked_dependencies": [],
              "production_publication_allowed": False, "production_authoritative": False,
              "state_mutation_allowed": False, "portfolio_mutation_allowed": False,
              "ledger_mutation_allowed": False, "fallback_used": False, "ranking": None}
    try:
        require(cadence in CADENCES, "UNSUPPORTED_CADENCE")
        require(date.fromisoformat(trading_date).isoformat() == trading_date, "TRADING_DATE_INVALID")
        if cadence in {"09:30", "12:00"}:
            feed = intraday_feed or {}
            require(feed.get("authorization_status") == "PASS" and feed.get("validation_status") == "PASS"
                    and feed.get("source_status") == "PASS" and feed.get("freshness_status") == "PASS"
                    and feed.get("fallback_used") is False and feed.get("blocked_dependencies") == []
                    and feed.get("source_authority") == "AUTHORIZED_TWSE_INTRADAY_FEED"
                    and feed.get("trading_date") == trading_date and feed.get("cadence") == cadence, EXTERNAL_FEED)
        loaded = load_live_state(state_root, previous_trading_date, previous_cadence)
        previous = loaded["state"]
        result.update(previous_state_id=previous["current_state_id"], previous_state_hash=previous["decision_payload_hash"])
        require(previous_trading_date <= trading_date
                and (previous_trading_date < trading_date or CADENCES.index(previous_cadence) < CADENCES.index(cadence)),
                "PREVIOUS_STATE_TIME_BINDING_INVALID")
        if first_refresh:
            from .phase2_production import validate_first_refresh
            validate_first_refresh(previous, state_root, trading_date, cadence)
            baseline = []
            result.update(continuity_baseline_source="FIRST_FULL_MARKET_REFRESH_AUTHORITY",
                          ranking_turnover_status="NOT_APPLICABLE_FIRST_FULL_MARKET_REFRESH")
        else:
            baseline = _symbols(previous["decision"].get("short_top30"), "PREVIOUS_DECISION_SHORT_TOP30_MISSING")
            require(len(baseline) == 30, "PREVIOUS_DECISION_SHORT_TOP30_INVALID")
            result["ranking_turnover_status"] = "RANKED_PREDECESSOR_COMPARISON"
        if cadence != "19:30":
            if cadence in {"09:30", "12:00"}:
                require(previous_trading_date == trading_date and previous_cadence ==
                        ("07:30" if cadence == "09:30" else "09:30"), "INCREMENTAL_PREVIOUS_SLOT_INVALID")
            require(previous["decision"].get("candidate_universe_source") == UNIVERSE
                    and previous["decision"].get("ranking_refresh_source") == "FULL_MARKET_SCAN",
                    "BOOTSTRAP_UNIVERSE_NOT_NORMAL_PRODUCTION")
            if cadence == "07:30":
                require(previous_cadence == "19:30", "LATEST_PASS_1930_STATE_REQUIRED")
                # Never skip a newer slot and silently consume an older ranking.
                from pathlib import Path
                newer = [path.parent.name for path in (Path(state_root) / "live").glob("*/1930")
                         if previous_trading_date < path.parent.name < trading_date]
                require(not newer, "LATEST_PASS_1930_STATE_REQUIRED")
            for key, count in (("top50", 50), ("short_top30", 30), ("long_top30", 30)):
                require(len(_symbols(previous["decision"].get(key), "PREVIOUS_RANKING_INCOMPLETE")) == count,
                        "PREVIOUS_RANKING_INCOMPLETE")
            result.update(validation_status="PASS", full_market_refresh=False,
                          mode="CONSUME_LATEST_PASS_1930" if cadence == "07:30" else "AUTHORIZED_INCREMENTAL_ONLY",
                          ranking={key: copy.deepcopy(previous["decision"][key]) for key in ("top50", "short_top30", "long_top30")})
            return result
        require(verification_only or (inputs or {}).get("evidence_scope") == "PRODUCTION", "ENGINEERING_INPUTS_NOT_PRODUCTION")
        if not verification_only:
            from .full_market_catalogue import validate_catalogue
            validate_catalogue(catalogue, trading_date)
        symbols, markets = bind_full_universe(catalogue, contract, trading_date, baseline)
        result.update(candidate_universe_count=len(symbols), outside_previous_top30=sorted(set(symbols) - set(baseline)))
        records = derive_full_market_inputs(inputs, catalogue, contract, symbols, markets, trading_date, previous)
        ranking = rank_full_market(records)
        require(len(ranking["top50"]) == 50, "TOP50_COVERAGE_INCOMPLETE")
        result.update(validation_status="PASS", mode="FULL_MARKET_REFRESH", full_market_refresh=True,
                      ranking=ranking, ranking_inputs_sha256=sha256(records), ranking_result_sha256=sha256(ranking),
                      production_snapshot_id=inputs["production_snapshot_id"], historical_warmup="PASS")
        result["input_snapshot_id"] = inputs["input_snapshot_id"]
        result["short_term_entries"] = None if first_refresh else sorted(set(row["symbol"] for row in ranking["short_top30"]) - set(baseline))
        result["short_term_exits"] = None if first_refresh else sorted(set(baseline) - set(row["symbol"] for row in ranking["short_top30"]))
        return result
    except (RuntimeError, ValueError, TypeError, KeyError, AttributeError, ArithmeticError) as exc:
        reason = str(exc) or type(exc).__name__
        result.update(blocking_reason=reason, ranking=None)
        if EXTERNAL_FEED in reason:
            result["blocked_dependencies"] = [EXTERNAL_FEED]
        return result
