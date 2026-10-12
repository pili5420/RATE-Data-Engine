"""Opt-in Phase I evidence decisions, not a Production warmup or scoring owner."""
from collections import Counter
from copy import deepcopy
from pathlib import Path
import os

from src.eps_duration_facts.model import require
from src.eps_duration_facts.raw import sha256
from src.finmind_formal_qualification import exact_period, reject_unproved_history
from src.provider_eps_candidate import WINDOW, _time
from src.provider_eps_metadata import read_metadata
from src.provider_financial_features import (CONTRACT as FEATURES, EPS_NAMES, REVENUE_NAME,
    compute_core, hash_object, validate_package, within_git_checkout)

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = read_metadata((ROOT / "docs/contracts/RATE_PROVIDER_WARMUP_READINESS_V1.json").read_bytes())
FLAGS = CONTRACT["boundaries"]


def fingerprint(path):
    import hashlib
    path = Path(path)
    h = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            h.update(chunk)
    return {"bytes": path.stat().st_size, "sha256": h.hexdigest()}


def pinned(path, expected_sha256):
    body = Path(path).read_bytes()
    require(sha256(body) == expected_sha256, "PHASE_I_SOURCE_PIN_MISMATCH:" + str(path))
    return read_metadata(body)


def verify_inventory(inventory):
    for name, expected in inventory.items():
        require(fingerprint(name) == expected, "PHASE_I_PROTECTED_SOURCE_CHANGED:" + name)
    return len(inventory)


def isolation_guard(output):
    """Enforce process writes, not just an after-the-fact equality assertion."""
    output = Path(output).resolve()
    def allowed(path):
        if isinstance(path, int):
            return
        require(Path(os.fsdecode(path)).resolve().is_relative_to(output), "PHASE_I_WRITE_OUTSIDE_SANDBOX")
    def audit(event, args):
        if event in {"socket.connect", "socket.getaddrinfo", "socket.sendto"}:
            raise RuntimeError("PHASE_I_FINANCIAL_NETWORK_FORBIDDEN")
        if event == "open":
            path, mode, flags = args
            if (mode and any(c in mode for c in "wax+")) or flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC):
                allowed(path)
        elif event in {"os.remove", "os.rmdir", "os.mkdir", "os.chmod", "os.utime", "os.truncate"}:
            allowed(args[0])
        elif event in {"os.rename", "os.link", "os.symlink"}:
            allowed(args[0]); allowed(args[1])
    return audit


def external_output(path, source_roots):
    path = Path(path).resolve()
    require(not path.exists() and not within_git_checkout(path), "PHASE_I_NEW_EXTERNAL_OUTPUT_REQUIRED")
    require(not any(p.casefold() in {"production", "latest", "state", "portfolio", "ledger", "snapshots"}
                    for p in path.parts), "PHASE_I_PROTECTED_OUTPUT")
    require(all(not path.is_relative_to(Path(root).resolve()) for root in source_roots), "PHASE_I_OUTPUT_IN_SOURCE")
    return path


def source_evidence(inputs, as_of):
    """Receipt identity is retained; receipt disclosure labels are not PIT proof."""
    result, receipts, pins = {"FinMind": [], "MOPS Official": []}, {}, {}
    for domain, rows in (("EPS", inputs["eps"]), ("REVENUE", inputs["revenue"])):
        for row in rows:
            raw_path, receipt_path = row["raw_reference"], row["receipt_reference"]
            for path, expected in ((raw_path, row["raw_sha256"]), (receipt_path, row["receipt_sha256"])):
                if path not in pins:
                    pins[path] = fingerprint(path)
                require(pins[path]["sha256"] == expected, "PHASE_I_RAW_OR_RECEIPT_TAMPER")
            if receipt_path not in receipts:
                receipts[receipt_path] = read_metadata(Path(receipt_path).read_bytes())
            receipt = receipts[receipt_path]
            if domain == "EPS":
                endpoint = receipt["requested_url"]
                require(endpoint == "https://api.finmindtrade.com/api/v4/data" and
                    receipt["query"]["dataset"] == "TaiwanStockFinancialStatements" and
                    receipt["query"]["data_id"] == row["symbol"] and receipt["http_status"] == 200 and
                    receipt["response_body_sha256"] == row["raw_sha256"], "PHASE_I_PROVIDER_MISMATCH")
                observed, retrieved = row["acquired_observed_at"], receipt["received_at"]
                period, locator, source = row["analysis_quarter"], row["json_locator"], "FinMind"
                exact_period(row["provider_date"], period)
                reject_unproved_history(row)
                require(row["provider_date"] <= _time(as_of).date().isoformat(), "PHASE_I_FUTURE_PERIOD")
                require(row["source"] == source and row["dataset"] == receipt["query"]["dataset"], "PHASE_I_PROVIDER_MISMATCH")
                validated = row["verified_observed_at"]
            else:
                endpoint = receipt["endpoint"]
                require(receipt["source_owner"] == "MOPS Official" and receipt["market"] == row["market"] and
                    receipt["requested_period"] == row["period"] and receipt["body_sha256"] == row["raw_sha256"] and
                    receipt["http_status"] == 200 and receipt["fallback_used"] is False and
                    receipt["final_url"] == endpoint and endpoint.startswith("https://mopsov.twse.com.tw/nas/t21/"),
                    "PHASE_I_PROVIDER_MISMATCH")
                observed, retrieved = row["observed_at"], receipt["retrieval_timestamp"]
                period, locator, source = row["period"], row["row_identity_locator"], "MOPS Official"
                validated = row["source_validated_at"]
                require(row["source"] == source, "PHASE_I_PROVIDER_MISMATCH")
                require(period <= _time(as_of).strftime("%Y-%m"), "PHASE_I_FUTURE_PERIOD")
            require(observed == retrieved and _time(observed) <= _time(validated) <= _time(as_of), "PHASE_I_FUTURE_OR_SUBSTITUTED_TIME")
            result[source].append({"symbol": row["symbol"], "market": row["market"], "period": period,
                "endpoint": endpoint, "observation_timestamp": observed, "retrieved_timestamp": retrieved,
                "source_validated_at": validated, "original_publication_timestamp": None,
                "receipt_disclosure_label_not_verified_publication": receipt.get("official_report_disclosure_date"),
                "revision_history": "UNPROVEN", "restatement_awareness": "UNKNOWN_NO_VERSION_CHAIN",
                "raw_reference": raw_path, "raw_sha256": row["raw_sha256"],
                "receipt_reference": receipt_path, "receipt_sha256": row["receipt_sha256"], "json_locator": locator})
    return result, pins


def decide(package, universe, evidence, execution, as_of):
    """Pure reconstruction from the verified source package, with four separate gates."""
    validate_package(package, as_of=as_of)
    inputs = package["core"]["inputs"]
    universe = deepcopy(universe)
    universe["stocks"].sort(key=lambda r: (r["market"] != "TWSE", r["symbol"]))
    require(inputs["universe"] == universe and universe["verification_status"] == "PASS", "PHASE_I_UNIVERSE_BINDING_MISMATCH")
    require(Counter(r["market"] for r in universe["stocks"]) == CONTRACT["market_counts"], "PHASE_I_EXACT_UNIVERSE_REQUIRED")
    require(set(execution) == {"base_sha", "head_sha"} and execution["base_sha"] == CONTRACT["base_sha"] and
        all(isinstance(v, str) and len(v) == 40 and set(v) <= set("0123456789abcdef") for v in execution.values()),
        "PHASE_I_EXECUTION_BINDING_MISMATCH")
    calculated = compute_core(inputs)
    require(calculated == package["core"], "PHASE_I_SANDBOX_RECOMPUTATION_MISMATCH")
    eps = {(r["symbol"], r["analysis_quarter"]) for r in inputs["eps"]}
    rev = {(r["symbol"], r["period"]): r for r in inputs["revenue"]}
    companies = []
    for company in calculated["companies"]:
        symbol = company["symbol"]
        missing_eps = [q for q in WINDOW if (symbol, q) not in eps]
        missing_rev = [{"period": p, "reason": "MISSING_REVENUE_OBSERVATION" if (symbol, p) not in rev else rev[(symbol, p)]["revenue_yoy_status"]}
                       for p in FEATURES["revenue_months"] if (symbol, p) not in rev or rev[(symbol, p)]["revenue_yoy_status"] != "VALID_NUMERIC"]
        companies.append({**deepcopy(company), "eps_ready": not missing_eps, "revenue_ready": not missing_rev,
            "sandbox_input_ready": not missing_eps and not missing_rev,
            "sandbox_status": "COMPUTABLE" if not missing_eps and not missing_rev else "NOT_READY_MISSING_REQUIRED_PERIOD",
            "missing_eps_quarters": missing_eps, "missing_revenue_periods": missing_rev,
            "valid_eps_positions_retained": 8 - len(missing_eps), "ranking_eligible": False,
            "formal_score": None, "rank": None, "production_eligible": False})
    summary = deepcopy(calculated["summary"])
    summary.update(eps_complete=sum(c["eps_ready"] for c in companies), revenue_complete=sum(c["revenue_ready"] for c in companies),
        sandbox_complete=sum(c["sandbox_input_ready"] for c in companies), incomplete_issuers=sum(not c["eps_ready"] for c in companies),
        incomplete_valid_eps_retained=sum(c["valid_eps_positions_retained"] for c in companies if not c["eps_ready"]))
    matrix = []
    for provider, dataset, ready, required in (("FinMind", "TaiwanStockFinancialStatements", summary["eps_complete"], list(WINDOW)),
        ("MOPS Official", "Official monthly revenue archive", summary["revenue_complete"], FEATURES["revenue_months"])):
        records = evidence[provider]
        require(len(records) == len(inputs["eps"] if provider == "FinMind" else inputs["revenue"]), "PHASE_I_SOURCE_EVIDENCE_COUNT")
        matrix.append({"provider": provider, "dataset_owner": provider, "dataset": dataset,
            "source_validation": "PASS", "semantic_scope": "PROVIDER_CALENDAR_QUARTER_BASIC_EPS" if provider == "FinMind" else "OFFICIAL_MONTHLY_REVENUE_YOY",
            "qualification_scope": "FULL_1978_UNIVERSE_REQUIRED_PERIODS_NOT_ACTIVATION",
            "status": "QUALIFIED" if ready == len(companies) else "NOT_QUALIFIED",
            "reason": None if ready == len(companies) else "REQUIRED_PERIOD_OR_FINITE_NUMERIC_COVERAGE_INCOMPLETE",
            "required_periods": required, "complete_issuers": ready, "universe_issuers": len(companies),
            "endpoints": sorted({r["endpoint"] for r in records}), "source_record_count": len(records),
            "publication_timestamp": None, "historical_pit": "UNPROVEN", "revision_history": "UNPROVEN",
            "first_observed_at": min((r["observation_timestamp"] for r in records), key=_time, default=None),
            "last_observed_at": max((r["observation_timestamp"] for r in records), key=_time, default=None),
            "fallback_allowed": False, "synthesized_values": False})
    blockers = []
    if any(p["status"] != "QUALIFIED" for p in matrix):
        blockers.append("BLOCKED_PROVIDER_QUALIFICATION")
    blockers.extend(["BLOCKED_HISTORICAL_PIT"])
    if summary["sandbox_complete"] != len(companies):
        blockers.append("BLOCKED_DATA_GAP")
    blockers.append("BLOCKED_GOVERNANCE")
    return {"artifact_kind": CONTRACT["artifact_kind"], "contract": CONTRACT,
        "execution_binding": execution, "original_producer_binding": package["execution"]["code_binding"],
        "source_feature_content_sha256": package["content_sha256"], "source_input_content_sha256": calculated["input_content_sha256"],
        "source_binding": deepcopy(inputs["source_binding"]), "universe": universe,
        "gate_i_1_provider_qualification": matrix,
        "gate_i_2_historical_pit": {"status": "UNPROVEN", "information_available_at_decision_time": "NOT_PROVEN",
            "original_publication_timestamp": None, "revision_history": "UNPROVEN", "historical_cutoff": "2026-10-05",
            "reason": "NO_COMPLETE_ORIGINAL_PUBLICATION_AND_RESTATEMENT_CHAIN", "retrieval_is_not_publication": True},
        "gate_i_3_warmup_sandbox": {"status": "PASS", "scope": "EXISTING_PROVIDER_FEATURE_CALCULATION_ONLY_NOT_FORMAL_WARMUP",
            "source_replay_required": True, "inventory_pass_grants_ranking_eligibility": False,
            "summary": summary, "companies": companies, "preserved_gaps": deepcopy(inputs["gaps"])},
        "gate_i_4_production_readiness": {"verdict": blockers[0], "blocking_conditions": blockers,
            "activation_allowed": False, "first_refresh_eligible": False}, "boundaries": deepcopy(FLAGS)}


def envelope(core, generated_at, validated_at):
    require(_time(generated_at) <= _time(validated_at), "PHASE_I_VALIDATION_PRECEDES_GENERATION")
    return {"core": core, "content_sha256": hash_object(core), "generated_at": generated_at, "validated_at": validated_at}


def cold_verify(path, expected_sha256, package, universe, evidence, execution, as_of):
    value = pinned(path, expected_sha256)
    require(_time(value["generated_at"]) <= _time(value["validated_at"]) <= _time(as_of), "PHASE_I_FUTURE_ENVELOPE")
    rebuilt = decide(package, universe, evidence, execution, as_of)
    require(value["core"] == rebuilt and value["content_sha256"] == hash_object(rebuilt), "PHASE_I_COLD_REPLAY_MISMATCH")
    return {"status": "PASS", "content_sha256": value["content_sha256"], "counts": rebuilt["gate_i_3_warmup_sandbox"]["summary"]}
