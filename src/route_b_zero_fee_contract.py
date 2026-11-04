"""Validator for RATE V11 Route B zero-fee Production contract."""
from __future__ import annotations
from typing import Any, Mapping

class RouteBContractError(RuntimeError):
    pass

def require(condition: bool, reason: str) -> None:
    if not condition:
        raise RouteBContractError(reason)

def validate_route_b_contract(contract: Mapping[str,Any]) -> dict[str,Any]:
    require(isinstance(contract,Mapping),"ROUTE_B_CONTRACT_INVALID")
    require(contract.get("artifact")=="RATE_ZERO_FEE_PRODUCTION_CONTRACT_V1","ROUTE_B_ARTIFACT_INVALID")
    require(contract.get("status")=="ADOPTED_ROUTE_B","ROUTE_B_NOT_ADOPTED")
    require(contract.get("effective_cadences")==["09:30","12:00"],"ROUTE_B_CADENCE_SCOPE_INVALID")
    require(contract.get("market_intraday_real_time_required") is False
            and contract.get("authorized_intraday_feed_required") is False
            and contract.get("twse_tpex_non_display_authority_required") is False,
            "ROUTE_B_REALTIME_DEPENDENCY_NOT_REMOVED")
    require(contract.get("monthly_market_data_license_budget_twd")==0,"ROUTE_B_ZERO_FEE_BUDGET_INVALID")
    require(contract.get("allowed_source_class")=="OPEN_OFFICIAL_NON_INTRADAY_API","ROUTE_B_SOURCE_CLASS_INVALID")
    require(contract.get("allowed_automation")=="DOCUMENTED_OFFICIAL_API_ONLY"
            and contract.get("website_scraping_allowed") is False
            and contract.get("undocumented_endpoint_allowed") is False
            and contract.get("fallback_allowed") is False,
            "ROUTE_B_AUTOMATION_BOUNDARY_INVALID")
    model=contract.get("decision_model")
    require(isinstance(model,Mapping),"ROUTE_B_DECISION_MODEL_MISSING")
    for cadence in ("09:30","12:00"):
        spec=model.get(cadence)
        require(isinstance(spec,Mapping),"ROUTE_B_CADENCE_MODEL_MISSING:"+cadence)
        require(spec.get("price_role")=="PREVIOUS_VALIDATED_MARKET_STATE","ROUTE_B_PRICE_ROLE_INVALID:"+cadence)
        require(spec.get("current_intraday_price") is None and spec.get("current_intraday_volume") is None,
                "ROUTE_B_CURRENT_INTRADAY_VALUE_FORBIDDEN:"+cadence)
        require(spec.get("intraday_rerank_allowed") is False and spec.get("paper_trade_fill_allowed") is False,
                "ROUTE_B_INTRADAY_ACTION_FORBIDDEN:"+cadence)
        require(spec.get("freshness_contract")=="LATEST_OFFICIAL_AVAILABLE_WITH_PREVIOUS_EOD_MARKET_BASELINE",
                "ROUTE_B_FRESHNESS_INVALID:"+cadence)
    semantics=contract.get("production_semantics")
    require(isinstance(semantics,Mapping)
            and semantics.get("state_chain_continues") is True
            and semantics.get("portfolio_continues") is True
            and semantics.get("transaction_ledger_continues") is True
            and semantics.get("ranking_carries_forward_until_19_30") is True
            and semantics.get("19_30_full_eod_refresh_remains_required") is True
            and semantics.get("09_30_12_00_are_decision_checkpoints") is True
            and semantics.get("09_30_12_00_are_intraday_price_decisions") is False,
            "ROUTE_B_PRODUCTION_SEMANTICS_INVALID")
    acceptance=contract.get("acceptance")
    require(isinstance(acceptance,Mapping)
            and acceptance.get("production_acceptance_allowed_under_route_b") is True
            and acceptance.get("cer081_allowed_under_route_b") is True
            and acceptance.get("real_time_intraday_coverage_required") is False
            and acceptance.get("official_public_evidence_gate_required") is True
            and acceptance.get("zero_current_intraday_price_required") is True
            and acceptance.get("zero_intraday_trade_fill_required") is True,
            "ROUTE_B_ACCEPTANCE_BOUNDARY_INVALID")
    return {
        "artifact":"RATE_ZERO_FEE_PRODUCTION_CONTRACT_QUALIFICATION_V1",
        "validation_status":"PASS",
        "route":"B_ZERO_FEE",
        "effective_cadences":["09:30","12:00"],
        "real_time_intraday_required":False,
        "exchange_non_display_authority_required":False,
        "monthly_license_budget_twd":0,
        "production_acceptance_permitted_by_contract":True,
        "cer081_permitted_by_contract":True,
        "next_gate":"ROUTE_B_RUNTIME_PROMOTION"
    }
