"""Read-only Phase C qualification, not an EPS owner or activation adapter."""
from collections import Counter
from copy import deepcopy
from datetime import date
from pathlib import Path

from .eps_duration_facts.model import require
from .eps_duration_facts.raw import sha256
from .provider_eps_candidate import (
    POLICY, WINDOW, _canonical, _decimal, _json, _policy, _time, map_basic_eps_label,
)
from .provider_financial_feature_inputs import load_closeout, verify_file

CONTRACT = "RATE-FINMIND-FORMAL-EPS-PROVIDER-V1"
ENDS = dict(zip(WINDOW, ("2024-09-30", "2024-12-31", "2025-03-31", "2025-06-30",
                         "2025-09-30", "2025-12-31", "2026-03-31", "2026-06-30")))
GAP_CLASSES = {"NO_PROVIDER_ROWS_FOR_QUARTER", "FINANCIAL_ROWS_PRESENT_NO_TYPE_EPS",
               "POSSIBLE_RELATED_UNAPPROVED_FIELD", "INSUFFICIENT_MATERIAL"}


def exact_period(provider_date, quarter):
    require(quarter in ENDS, "OLDER_OR_OUTSIDE_QUARTER_SUBSTITUTION")
    require(provider_date == ENDS[quarter], "AMBIGUOUS_PROVIDER_PERIOD")
    parsed = date.fromisoformat(provider_date)
    return {"provider_calendar_year": parsed.year, "provider_calendar_quarter": int(quarter[-1]),
            "exact_provider_date": provider_date, "mapping_rule": "EXACT_QUARTER_END_V1",
            "mapping_status": "PASS", "fiscal_year": None, "fiscal_quarter": None,
            "report_period_start": None, "report_period_end": None,
            "formal_period_identity": "NOT_PROVEN",
            "limitation": "CALENDAR_DATE_MAPPING_IS_NOT_INDEPENDENT_FISCAL_PERIOD_EVIDENCE"}


def reject_unproved_history(row):
    # This version has no verified publication/revision source. Never promote observations.
    require(all(row.get(k) is None for k in ("filing_id", "revision_id", "public_time")),
            "UNSUPPORTED_PUBLICATION_OR_REVISION_CLAIM")
    require(row.get("historical_pit_status") == "UNPROVEN" and
            row.get("same_public_version_status") == "UNPROVEN", "UNSUPPORTED_HISTORICAL_CLAIM")


def future_observation_allowed(observed_at, activation_at, qualified):
    """Necessary temporal condition only; this never grants Production eligibility."""
    require(type(qualified) is bool, "QUALIFICATION_TYPE_INVALID")
    return qualified and activation_at is not None and _time(observed_at) >= _time(activation_at)


def qualification_outcome(period_proven, historical_proven):
    """Decision table, not a caller-supplied substitute for source verification."""
    require(type(period_proven) is bool and type(historical_proven) is bool, "PROOF_TYPE_INVALID")
    if not period_proven:
        return "NOT_QUALIFIED"
    return "FULLY_QUALIFIED" if historical_proven else "PROSPECTIVE_QUALIFIED"


def verify_gap_evidence(gap):
    """Count actual rows at the missing position; do not infer an issuer's history."""
    proof, total, eps_count = [], 0, 0
    quarter = gap["analysis_quarter"]
    require(quarter in WINDOW and gap.get("receipt_evidence"), "GAP_SOURCE_REQUIRED")
    for evidence in gap["receipt_evidence"]:
        receipt_bytes = Path(evidence["receipt_reference"]).read_bytes()
        require(sha256(receipt_bytes) == evidence["receipt_sha256"], "GAP_RECEIPT_TAMPERED")
        receipt = _json(receipt_bytes)
        raw = verify_file(evidence["raw_reference"], {"bytes": evidence["raw_bytes"], "sha256": evidence["raw_sha256"]})
        require(receipt["query"]["data_id"] == gap["symbol"] and
                receipt["response_body_sha256"] == evidence["raw_sha256"] and receipt["http_status"] == 200,
                "GAP_RECEIPT_IDENTITY_MISMATCH")
        query = receipt["query"]
        if not query["start_date"] <= ENDS[quarter] <= query["end_date"]:
            continue
        matching = []
        for index, row in enumerate(_json(raw)["data"]):
            require(row["stock_id"] == gap["symbol"], "GAP_WRONG_SYMBOL")
            if row["date"] == ENDS[quarter]:
                matching.append({"json_locator": f"$.data[{index}]", "raw_row_index_zero_based": index,
                    "provider_date": row["date"], "provider_type": row["type"], "provider_origin_name": row["origin_name"]})
        total += len(matching)
        eps_count += sum(r["provider_type"] == "EPS" for r in matching)
        proof.append({**deepcopy(evidence), "replayed_position_rows": matching})
    require(proof, "GAP_QUERY_DOES_NOT_COVER_POSITION")
    classification = "NO_PROVIDER_ROWS_FOR_QUARTER" if not total else "FINANCIAL_ROWS_PRESENT_NO_TYPE_EPS" if not eps_count else "POSSIBLE_RELATED_UNAPPROVED_FIELD"
    require(classification == gap["classification"], "GAP_CLASSIFICATION_REPLAY_MISMATCH")
    return {**deepcopy(gap), "receipt_evidence": proof, "quarter_provider_row_count": total,
            "type_eps_row_count": eps_count, "classification_replay": "PASS"}


def qualify_material(material, validated_at):
    """Requires the existing source replay; additionally bind every row to exact bytes."""
    now = _time(validated_at)
    stocks = material["universe"]["stocks"]
    markets = {r["symbol"]: r["market"] for r in stocks}
    require(len(markets) == len(stocks) and all(m in {"TWSE", "TPEX"} for m in markets.values()),
            "UNIVERSE_IDENTITY_INVALID")
    records, keys, raw_cache, inventory = [], {}, {}, {}
    for row in material["eps"]:
        symbol, quarter = row["symbol"], row["analysis_quarter"]
        require(symbol in markets, "WRONG_SYMBOL")
        require(row["market"] == markets[symbol], "WRONG_MARKET")
        period = exact_period(row["provider_date"], quarter)
        _policy(row)
        mapping = map_basic_eps_label(row["provider_type"], row["provider_origin_name"])
        require(row["provider_basis_label"] == "BASIC" and all(row[k] == v for k, v in mapping.items()),
                "BASIC_LABEL_IDENTITY_MISMATCH")
        value = _decimal(row["provider_value"])
        key = (symbol, quarter)
        require(key not in keys, "CONFLICTING_QUARTER" if key in keys and keys[key] != value else "DUPLICATE_QUARTER")
        keys[key] = value
        reject_unproved_history(row)
        observed, verified = _time(row["acquired_observed_at"]), _time(row["verified_observed_at"])
        require(observed <= verified <= now, "FUTURE_OR_SUBSTITUTED_OBSERVATION")
        raw_path, receipt_path = row["raw_reference"], row["receipt_reference"]
        expected = {"bytes": row["raw_bytes"], "sha256": row["raw_sha256"]}
        if raw_path not in raw_cache:
            raw_cache[raw_path] = _json(verify_file(raw_path, expected))
        else:
            require(inventory[raw_path] == expected, "RAW_IDENTITY_CONFLICT")
        inventory[raw_path] = expected
        receipt_bytes = Path(receipt_path).read_bytes()
        require(sha256(receipt_bytes) == row["receipt_sha256"], "RECEIPT_TAMPERED")
        inventory[receipt_path] = {"bytes": len(receipt_bytes), "sha256": row["receipt_sha256"]}
        receipt = _json(receipt_bytes)
        require(receipt["query"]["data_id"] == symbol and receipt["query"]["dataset"] == POLICY["dataset"] and
                receipt["response_body_sha256"] == row["raw_sha256"] and
                receipt["received_at"] == row["acquired_observed_at"], "RECEIPT_IDENTITY_MISMATCH")
        index = row["raw_row_index_zero_based"]
        require(type(index) is int and 0 <= index < len(raw_cache[raw_path]["data"]) and
                row["json_locator"] == f"$.data[{index}]", "RAW_LOCATOR_INVALID")
        original = raw_cache[raw_path]["data"][index]
        require(original["stock_id"] == symbol and original["date"] == row["provider_date"] and
                original["type"] == row["provider_type"] and original["origin_name"] == row["provider_origin_name"] and
                _decimal(original["value"]) == value, "RAW_ROW_IDENTITY_MISMATCH")
        records.append({**deepcopy(row), "period_qualification": period,
                        "raw_observed_fields": sorted(original), "qualification_validated_at": validated_at,
                        "formal_observation_eligible": False, "activation_required": True})
    gaps = {(g["symbol"], g["analysis_quarter"]): deepcopy(g) for g in material["gaps"]}
    require(len(gaps) == len(material["gaps"]), "DUPLICATE_GAP")
    expected_keys = {(s, q) for s in markets for q in WINDOW}
    require(set(keys).isdisjoint(gaps) and set(keys) | set(gaps) == expected_keys, "GAP_OR_UNIVERSE_MISMATCH")
    require(all(g["market"] == markets[s] and g["classification"] in GAP_CLASSES for (s, _), g in gaps.items()),
            "GAP_IDENTITY_INVALID")
    companies = []
    for symbol in sorted(markets):
        rows = sorted((r for r in records if r["symbol"] == symbol), key=lambda r: WINDOW.index(r["analysis_quarter"]), reverse=True)
        missing = [q for q in WINDOW if (symbol, q) not in keys]
        companies.append({"symbol": symbol, "market": markets[symbol], "valid_quarters": len(rows),
            "eight_consecutive_calendar_quarters": not missing, "missing_quarters": missing,
            "status": "COMPLETE" if not missing else "NO_EPS" if not rows else "HISTORICAL_INSUFFICIENT",
            "formal_period_identity": "NOT_PROVEN", "quarters": rows,
            "gaps": [gaps[(symbol, q)] for q in missing], "production_eligible": False})
    def counts(items):
        return {"companies": len(items), "accounted_for": len(items),
            "eps_complete_companies": sum(c["eight_consecutive_calendar_quarters"] for c in items),
            "valid_company_quarters": sum(c["valid_quarters"] for c in items),
            "quarter_gaps": sum(len(c["missing_quarters"]) for c in items),
            "statuses": dict(Counter(c["status"] for c in items)), "NOT_ATTEMPTED": 0}
    summary = counts(companies)
    summary["incomplete_issuers"] = summary["companies"] - summary["eps_complete_companies"]
    summary["incomplete_issuer_valid_rows_retained"] = sum(c["valid_quarters"] for c in companies if c["missing_quarters"])
    summary["by_market"] = {m: counts([c for c in companies if c["market"] == m]) for m in ("TWSE", "TPEX")}
    summary["gap_classification"] = dict(Counter(g["classification"] for g in gaps.values()))
    summary["provider_date_counts"] = dict(sorted(Counter(r["provider_date"] for r in records).items()))
    summary["raw_field_sets"] = sorted({tuple(r["raw_observed_fields"]) for r in records})
    # V1 only recognizes date/stock_id/type/origin_name/value. No fiscal context proof is supplied.
    formal_proven = bool(records) and all(r["period_qualification"]["formal_period_identity"] == "PASS" for r in records)
    historical_proven = bool(records) and all(r["historical_pit_status"] == "PASS" for r in records)
    core = {"contract": CONTRACT, "source_policy": POLICY, "source_binding": material["source_binding"],
        "universe": material["universe"], "window": list(WINDOW), "summary": summary,
        "companies": [{**c, "quarters": [{k: v for k, v in r.items() if k != "qualification_validated_at"} for r in c["quarters"]]} for c in companies],
        "FINMIND_FORMAL_EPS_PROVIDER": qualification_outcome(formal_proven, historical_proven),
        "FORMAL_PERIOD_IDENTITY": "PASS" if formal_proven else "NOT_PROVEN",
        "PROSPECTIVE_FORMAL_USE": "QUALIFIED" if formal_proven else "NOT_QUALIFIED",
        "HISTORICAL_PIT": "PASS" if historical_proven else "UNPROVEN", "REVISION_HISTORY": "UNPROVEN",
        "calculation_boundary": "PROVIDER_DEFINED_UNADJUSTED_QUARTER_SUM",
        "provider_calendar_mapping": "PASS", "issuer_fiscal_context": "UNPROVEN",
        "activation_cr_recommended": False, "period_semantics_resolution_required": True,
        "activation_required": True, "production_eligible": False, "provider_reply_required": False,
        "formal_warmup_gate": "FUNDAMENTAL_EPS_PERIOD_IDENTITY_UNPROVEN",
        "fallback_allowed": False, "original_eight_quarter_coverage_credit": 0,
        "historical_cutoff": "2026-10-05", "new_financial_requests": 0}
    for path, expected in inventory.items():
        verify_file(path, expected)
    return {"core": core, "content_sha256": sha256(_canonical(core)), "validated_at": validated_at,
            "source_inventory": inventory, "old_sources_unchanged": True}


def replay_closeout(reference, trusted_sha256, validated_at):
    material = load_closeout(reference, trusted_sha256)
    material["gaps"] = [verify_gap_evidence(gap) for gap in material["gaps"]]
    return qualify_material(material, validated_at)
