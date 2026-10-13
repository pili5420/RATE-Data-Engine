"""Opt-in accepted-snapshot adapter. No acquisition, ranking or publication path."""
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
import re

from .eps_duration_facts.model import require
from .fundamental import calculate_fundamental
from .fundamental_first_refresh_execution import (
    PlanDispatchGate, build_request_plan, digest, exact_universe, read_fundamental_committed,
)
from .provider_eps_candidate import _canonical, _time, map_basic_eps_label
from .provider_eps_metadata import read_metadata

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "docs/contracts/RATE_FUNDAMENTAL_RANKING_CONSUMER_V1.json"
CONTRACT = read_metadata(CONTRACT_PATH.read_bytes())
VERSION = CONTRACT["version"]
KIND = CONTRACT["artifact_kind"]
EPS_ORDER = tuple(CONTRACT["eps_order"])
REVENUE_ORDER = tuple(CONTRACT["revenue_order"])
RANK_INPUTS = {k: tuple(v) for k, v in CONTRACT["component_requirements"].items()}
FLAGS = CONTRACT["governance"]
SYNTHETIC = "SYNTHETIC_ENGINEERING_ONLY_NOT_PRODUCTION_ACCEPTANCE"
REAL = "ACCEPTED_PROSPECTIVE_PRODUCTION_READ_ONLY"


def now():
    return datetime.now(timezone.utc).isoformat()


def exact_date(quarter):
    require(quarter in CONTRACT["provider_periods"], "CONSUMER_PERIOD_SUBSTITUTION")
    return CONTRACT["provider_periods"][quarter]


def pinned(ref):
    require(isinstance(ref, dict) and set(ref) == {"path", "sha256"}, "CONSUMER_REFERENCE_INVALID")
    body = Path(ref["path"]).read_bytes()
    require(digest(body) == ref["sha256"], "CONSUMER_SOURCE_HASH_MISMATCH")
    return read_metadata(body)


def owner_identities():
    result = {}
    for path, expected in CONTRACT["owner_code_sha256_lf"].items():
        body = (ROOT / path).read_bytes()
        require(digest(body.replace(b"\r\n", b"\n")) == expected,
                "GOVERNANCE_ESCALATION_REQUIRED_OWNER_DRIFT:" + path)
        result[path] = {"code_sha256_lf": expected, "file_sha256": digest(body)}
    return result


def number(value):
    require(isinstance(value, str) and value.strip() == value and bool(value), "CONSUMER_NUMERIC_INVALID")
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("CONSUMER_NUMERIC_INVALID") from exc
    require(result.is_finite(), "CONSUMER_NUMERIC_NONFINITE")
    return result


def _max_time(values):
    return max(values, key=_time)


def _binding(binding, synthetic):
    require(set(binding) == {"material_scope", "source", "artifacts_root", "acceptance",
            "lineage_root", "config_sha256", "producer_main_sha"}, "CONSUMER_BINDING_SCHEMA")
    require(binding["material_scope"] == (SYNTHETIC if synthetic else REAL), "CONSUMER_MATERIAL_SCOPE")
    require(binding["producer_main_sha"] == CONTRACT["base_sha"], "CONSUMER_PRODUCER_PIN")
    require(set(binding["source"]) == set(CONTRACT["accepted_source"]), "CONSUMER_SOURCE_PINS")
    require(binding["acceptance"]["sha256"] == binding["source"]["acceptance_sha256"],
            "CONSUMER_ACCEPTANCE_PIN")
    if not synthetic:
        require(binding["source"] == CONTRACT["accepted_source"], "CONSUMER_UNACCEPTED_SOURCE")


def read_accepted(binding, *, as_of, synthetic=False):
    _binding(binding, synthetic)
    owner_identities()
    acceptance = pinned(binding["acceptance"])
    pins = binding["source"]
    require(acceptance["01_Final_Status"] == "FUNDAMENTAL_FIRST_REFRESH_PRODUCTION_ACCEPTED"
            and acceptance["19_Fundamental_Latest_Identity"] == pins["latest_identity"]
            and acceptance["23_Snapshot_ID"] == pins["snapshot_id"]
            and acceptance["24_Snapshot_Content_SHA"] == pins["snapshot_content_sha256"]
            and acceptance["25_Snapshot_Cold_Read"]["raw_bytes_sha256"] == pins["snapshot_file_sha256"]
            and acceptance["29_Exact_Universe_Match"]["universe_identity"] == pins["universe_identity"],
            "CONSUMER_PRODUCTION_ACCEPTANCE_MISMATCH")
    if synthetic:
        require(acceptance.get("evidence_scope") == SYNTHETIC, "CONSUMER_SYNTHETIC_SCOPE_REQUIRED")
    loaded = read_fundamental_committed(binding["artifacts_root"], pins["latest_identity"])
    snapshot, manifest = loaded["snapshot"], loaded["manifest"]
    require(manifest["fundamental_snapshot"]["sha256"] == pins["snapshot_file_sha256"]
            and snapshot["fundamental_snapshot_id"] == pins["snapshot_id"]
            and snapshot["content_sha256"] == pins["snapshot_content_sha256"], "CONSUMER_SNAPSHOT_PIN")
    core = {k: v for k, v in snapshot.items() if k not in
            {"fundamental_snapshot_id", "content_sha256", "fundamental_production_eligible"}}
    require(digest(core) == pins["snapshot_content_sha256"]
            and pins["snapshot_id"] == "rate-fundamental-first-refresh-" + digest(core),
            "CONSUMER_SNAPSHOT_CONTENT_TAMPER")
    require(snapshot["execution_main_sha"] == binding["producer_main_sha"]
            and snapshot["historical_pit"] == "UNPROVEN"
            and snapshot["original_eight_quarter_coverage_credit"] == 0
            and snapshot["fallback_allowed"] is False
            and snapshot["fundamental_production_eligible"] is True
            and snapshot["ranking_authorized"] is False
            and snapshot["decision_state_authorized"] is False, "CONSUMER_GOVERNANCE_INVALID")
    require(_time(manifest["commit_timestamp"]) <= _time(as_of) <= _time(now()), "CONSUMER_NOT_YET_AVAILABLE")
    rows = snapshot["issuer_readiness"]
    require(isinstance(rows, list) and snapshot["issuer_count"] == len(rows), "CONSUMER_ISSUER_COUNT")
    stocks, identity = exact_universe({"verification_status": "PASS", "stocks": rows})
    require(identity == pins["universe_identity"] == snapshot["universe_identity"], "CONSUMER_UNIVERSE_MISMATCH")
    if synthetic:
        require(all(s["symbol"].startswith(("T", "P")) for s in stocks), "CONSUMER_SYNTHETIC_UNIVERSE_REQUIRED")
    require(manifest["authority_id"] == snapshot["authority_id"]
            and manifest["request_plan_id"] == snapshot["request_plan_id"], "CONSUMER_MANIFEST_BINDING")
    return loaded, stocks


def verify_lineage(binding, loaded, stocks, as_of):
    """Validate provenance only; scoring values are never taken from this folder."""
    root = Path(binding["lineage_root"])
    config = pinned({"path": str(root / "CONFIG.json"), "sha256": binding["config_sha256"]})
    snapshot = loaded["snapshot"]
    universe = {"verification_status": "PASS", "stocks": stocks}
    require(exact_universe(config["universe"])[1] == snapshot["universe_identity"]
            and config["authority_id"] == snapshot["authority_id"], "CONSUMER_LINEAGE_CONFIG_BINDING")
    plan = build_request_plan(universe, snapshot["authority_id"], binding["producer_main_sha"])
    require(plan["request_plan_id"] == snapshot["request_plan_id"]
            and plan["request_plan_sha256"] == snapshot["request_plan_sha256"], "CONSUMER_LINEAGE_PLAN")
    entries = snapshot["evidence_index"]
    events = sorted((root / "events").iterdir())
    require(len(entries) == len(events) == len(plan["entries"]), "CONSUMER_EVIDENCE_INDEX_COUNT")
    require(not (root / "STOP.json").exists(), "CONSUMER_LINEAGE_STOP_PRESENT")
    result, row_bindings, completed, receipts, scopes = {}, {}, set(), set(), {}
    head = None
    prior_seen = None
    for i, (ref, entry, path) in enumerate(zip(entries, plan["entries"], events)):
        body = path.read_bytes()
        event = read_metadata(body)
        event_hash = digest(body)
        require(path.name == f"{i:08d}-" + event_hash + ".json" and event["previous_head"] == head
                and event["config_sha256"] == binding["config_sha256"], "CONSUMER_EVENT_CHAIN_TAMPER")
        record = event["record"]
        ident = event["intent_id"]
        require(isinstance(ident, str) and re.fullmatch(r"[a-zA-Z0-9_-]+", ident), "CONSUMER_INTENT_ID")
        intent_ref = {"path": str(root / "intents" / (ident + ".json")), "sha256": event["intent_sha256"]}
        intent = pinned(intent_ref)
        require(ident not in completed and intent["intent_id"] == ident
                and intent["config_sha256"] == binding["config_sha256"]
                and intent["authority_id"] == snapshot["authority_id"]
                and intent["provider"] == record["provider"] == entry["provider"]
                and intent["target"] == record["target"] == entry["target"]
                and intent["dispatch"]["plan_binding"] == PlanDispatchGate(plan, entry, None)._binding(),
                "CONSUMER_INTENT_BINDING")
        expected_ref = {"ordinal": entry["ordinal"], "request_key": entry["request_key"], "intent_id": ident,
                        "event_sha256": event_hash, "raw_sha256": record["raw_sha256"],
                        "receipt_sha256": record["receipt_sha256"],
                        "immutable_snapshot_id": record["immutable_snapshot_id"],
                        "provider": entry["provider"], "target": entry["target"]}
        require(ref == expected_ref and record["authority_id"] == snapshot["authority_id"],
                "CONSUMER_EVIDENCE_REFERENCE_TAMPER")
        record_core = {k: v for k, v in record.items() if k != "immutable_snapshot_id"}
        require(record["immutable_snapshot_id"] == "authorized-prospective-acquisition-" + digest(_canonical(record_core))
                and record["historical_pit"] == "UNPROVEN" and record["fallback_allowed"] is False
                and record["original_publication_timestamp"] is None
                and record["source_identity_gate"] == "PASS", "CONSUMER_OBSERVATION_TAMPER")
        times = [record["activation_timestamp"], intent["requested_at"], record["requested_at"],
                 record["received_at"], record["validation_timestamp"], record["first_seen_at"], as_of]
        require(all(_time(a) <= _time(b) for a, b in zip(times, times[1:]))
                and (prior_seen is None or _time(prior_seen) <= _time(record["first_seen_at"])),
                "CONSUMER_SOURCE_TIME_ORDER")
        require(_time(record["requested_at"]) <= _time(record["source_observed_at"]) <=
                _time(record["validation_timestamp"]), "CONSUMER_OBSERVATION_TIME")
        scope = digest(_canonical(record["scope"]))
        require(event["previous_scope_observation"] == scopes.get(scope)
                and record["receipt_sha256"] not in receipts, "CONSUMER_OBSERVATION_CHAIN")
        raw_path = root / "raw" / (record["raw_sha256"] + ".bin")
        receipt_ref = {"path": str(root / "receipts" / (record["receipt_sha256"] + ".json")),
                       "sha256": record["receipt_sha256"]}
        require(digest(raw_path.read_bytes()) == record["raw_sha256"], "CONSUMER_RAW_TAMPER")
        receipt = pinned(receipt_ref)
        require(receipt.get("http_status") == 200 and receipt.get("fallback_used", False) is False,
                "CONSUMER_RECEIPT_STATUS")
        lineage = {**deepcopy(ref), "event_reference": {"path": str(path), "sha256": event_hash},
                   "intent_reference": intent_ref, "raw_reference": {"path": str(raw_path), "sha256": ref["raw_sha256"]},
                   "receipt_reference": receipt_ref, "observed_at": record["source_observed_at"],
                   "validated_at": record["validation_timestamp"], "first_seen_at": record["first_seen_at"]}
        result[entry["request_key"]] = lineage
        for row in record["rows"]:
            key = (entry["provider"], row["symbol"], row["period"])
            require(key not in row_bindings, "CONSUMER_DUPLICATE_SOURCE_ROW")
            row_bindings[key] = digest(row)
        head, prior_seen = event_hash, record["first_seen_at"]
        scopes[scope] = record["immutable_snapshot_id"]
        completed.add(ident)
        receipts.add(record["receipt_sha256"])
    require(head == snapshot["acquisition_ledger_head"]
            and {p.stem for p in (root / "intents").iterdir()} == completed, "CONSUMER_LEDGER_HEAD_OR_UNKNOWN_OUTCOME")
    expected_rows = {(provider, row["symbol"], period): digest(value)
                     for row in snapshot["issuer_readiness"] for field, provider in
                     (("eps", "FinMind"), ("revenue", "MOPS Official"))
                     for period, value in row["feature_inputs"][field].items()}
    require(row_bindings == expected_rows, "CONSUMER_SNAPSHOT_ROW_LINEAGE_MISMATCH")
    return result


def adapt(rows):
    """Use labeled periods, not source JSON order; retain partial input separately."""
    adapted, missing = [], {}
    for row in rows:
        require(set(row) == {"symbol", "market", "fundamental_input_status", "eps_status", "revenue_status",
                "missing_reasons", "feature_inputs", "ranking_eligible", "score", "rank"}
                and row["ranking_eligible"] is False and row["score"] is None and row["rank"] is None,
                "CONSUMER_ISSUER_SCHEMA_OR_RANKING_PROMOTION")
        require(set(row["feature_inputs"]) == {"eps", "revenue"}, "CONSUMER_FEATURE_SCHEMA")
        values, reasons = {}, {}
        for field, periods, provider in (("eps", EPS_ORDER, "FinMind"), ("revenue", REVENUE_ORDER, "MOPS Official")):
            inputs = row["feature_inputs"][field]
            require(isinstance(inputs, dict) and set(inputs) <= set(periods), "CONSUMER_PERIOD_SUBSTITUTION")
            values[field], reasons[provider] = [], []
            for period in periods:
                source = inputs.get(period)
                if source is None:
                    reasons[provider].append(period)
                    continue
                require(source["symbol"] == row["symbol"] and source["market"] == row["market"]
                        and source["period"] == period and "json_locator" in source, "CONSUMER_INPUT_IDENTITY")
                if field == "eps":
                    require(source["provider_date"] == exact_date(period), "CONSUMER_EPS_PERIOD_IDENTITY")
                    map_basic_eps_label(source["provider_type"], source["provider_origin_name"])
                    require(type(source["raw_row_index_zero_based"]) is int and source["raw_row_index_zero_based"] >= 0
                            and source["json_locator"] == f"$.data[{source['raw_row_index_zero_based']}]",
                            "CONSUMER_EPS_LOCATOR")
                if source["numeric_status"] == "VALID_NUMERIC":
                    values[field].append(number(source["value"]))
                else:
                    require(field == "revenue" and source["numeric_status"] == "UNDEFINED_ZERO_BASE"
                            and source["value"] is None, "CONSUMER_INVALID_NUMERIC_STATUS")
                    reasons[provider].append(period)
            reasons[provider].reverse()
            expected = "READY" if not reasons[provider] else "NOT_READY_MISSING_REQUIRED_PERIOD"
            require(row[field + "_status"] == expected, "CONSUMER_READINESS_CONFLICT")
        complete = not any(reasons.values())
        require(row["missing_reasons"] == reasons and row["fundamental_input_status"] ==
                ("READY" if complete else "NOT_READY_MISSING_REQUIRED_PERIOD"), "CONSUMER_MISSINGNESS_OR_ZERO_FILL")
        missing[row["symbol"]] = reasons
        adapted.append({"symbol": row["symbol"], "market": row["market"],
                        "quarterly_eps": values["eps"], "revenue_yoy": values["revenue"]})
    return adapted, missing


def score_value(value):
    require(type(value) in (int, float, Decimal) and Decimal(str(value)).is_finite()
            and 0 <= Decimal(str(value)) <= 100, "CONSUMER_OWNER_SCORE_INVALID")


def build(binding, *, generated_at, validated_at, synthetic=False):
    require(_time(generated_at) <= _time(validated_at) <= _time(now()), "CONSUMER_RUN_TIME_INVALID")
    loaded, stocks = read_accepted(binding, as_of=generated_at, synthetic=synthetic)
    lineage = verify_lineage(binding, loaded, stocks, generated_at)
    snapshot, manifest = loaded["snapshot"], loaded["manifest"]
    by_symbol = {r["symbol"]: r for r in snapshot["issuer_readiness"]}
    rows = [by_symbol[s["symbol"]] for s in stocks]
    owner_rows, missing = adapt(rows)
    # The existing owner alone selects its percentile population from all issuers.
    calculated = calculate_fundamental(deepcopy(owner_rows))
    scores = {r["symbol"]: r for r in calculated}
    expected = {r["symbol"] for r in rows if r["fundamental_input_status"] == "READY"}
    require(set(scores) == expected and len(scores) == len(calculated), "CONSUMER_OWNER_POPULATION_MISMATCH")
    population = "rate-fundamental-owner-population-" + digest({
        "snapshot_sha256": snapshot["content_sha256"], "members": sorted(expected),
        "owner_sha256": CONTRACT["owner_code_sha256_lf"][CONTRACT["owner"]]})
    verdicts = []
    for row in rows:
        symbol, market = row["symbol"], row["market"]
        keys = [f"finmind:{market}:{symbol}"] + [f"mops:{market}:{p}" for p in REVENUE_ORDER]
        refs = [lineage[k] for k in keys]
        value = scores[symbol]["Fundamental"] if symbol in scores else None
        if value is not None:
            score_value(value)
        verdicts.append({"symbol": symbol, "market": market, "owner": CONTRACT["owner"],
            "status": "PASS" if symbol in scores else "MISSING_REQUIRED_PERIOD",
            "reason": None if symbol in scores else deepcopy(missing[symbol]), "value": value,
            "observed_at": _max_time([r["observed_at"] for r in refs]),
            "validated_at": _max_time([r["validated_at"] for r in refs]),
            "input_available_at": _max_time([r["first_seen_at"] for r in refs] + [manifest["commit_timestamp"]]),
            "evidence_references": deepcopy(refs), "population_id": population,
            "latest_identity": loaded["latest_identity"], "snapshot_id": snapshot["fundamental_snapshot_id"],
            "snapshot_sha256": snapshot["content_sha256"], "input_row_sha256": digest(row),
            "input_row_locator": f"$.issuer_readiness[{snapshot['issuer_readiness'].index(row)}]",
            "preserved_feature_inputs": deepcopy(row["feature_inputs"]),
            "missing_reasons": deepcopy(missing[symbol]),
            "calculation_spec_version": scores[symbol]["calculation_spec_version"] if symbol in scores else None})
    core = {"version": VERSION, "material_scope": SYNTHETIC if synthetic else REAL,
            "source_binding": deepcopy(binding), "governance": deepcopy(FLAGS),
            "contract_sha256_lf": digest(CONTRACT_PATH.read_bytes().replace(b"\r\n", b"\n")),
            "owner_code_sha256_lf": deepcopy(CONTRACT["owner_code_sha256_lf"]),
            "eps_order": list(EPS_ORDER), "revenue_order": list(REVENUE_ORDER),
            "population_id": population, "universe_identity": snapshot["universe_identity"],
            "counts": {"input_universe": len(rows), "input_ready": len(expected),
                       "input_not_ready": len(rows) - len(expected), "score_pass": len(scores),
                       "score_missing": len(rows) - len(scores),
                       "by_market": {m: dict(Counter(v["status"] for v in verdicts if v["market"] == m))
                                     for m in CONTRACT["universe_counts"]}}, "issuers": verdicts}
    identity = digest(core)
    return {"artifact_kind": KIND, "content_sha256": identity, "verdict_id": "rate-fundamental-verdicts-" + identity,
            "core": core, "consumer_generated_at": generated_at, "consumer_validated_at": validated_at,
            "execution_owner_identities": owner_identities()}


def verify_bundle(bundle, binding, *, as_of, synthetic=False):
    require(set(bundle) == {"artifact_kind", "content_sha256", "verdict_id", "core", "consumer_generated_at",
            "consumer_validated_at", "execution_owner_identities"}, "CONSUMER_VERDICT_SCHEMA")
    require(bundle["artifact_kind"] == KIND and bundle["content_sha256"] == digest(bundle["core"])
            and bundle["verdict_id"] == "rate-fundamental-verdicts-" + bundle["content_sha256"], "CONSUMER_VERDICT_TAMPER")
    require(_time(bundle["consumer_validated_at"]) <= _time(as_of) <= _time(now()), "CONSUMER_VERDICT_FUTURE")
    rebuilt = build(binding, generated_at=bundle["consumer_generated_at"],
                    validated_at=bundle["consumer_validated_at"], synthetic=synthetic)
    require(rebuilt == bundle, "CONSUMER_VERDICT_REPLAY_MISMATCH")
    return bundle


def component_verdict(name, value, as_of):
    """Prospective bridge schema only, independent of engineering eligibility V1."""
    if value is None:
        return {"status": "NOT_EVALUATED", "value": None}
    require(isinstance(value, dict) and set(value) == {"status", "reason", "owner", "observed_at",
            "validated_at", "evidence_references", "period_statuses", "value", "population_id"},
            "CONSUMER_COMPONENT_SCHEMA")
    require(value["owner"] == CONTRACT["component_owners"][name] and value["status"] in
            {"PASS", "MISSING_REQUIRED_PERIOD", "NOT_EVALUATED", "NOT_AUTHORIZED", "UNDEFINED_ZERO_BASE",
             "BLOCKED_EXTERNAL", "INVALID_EVIDENCE", "NOT_COMPUTED"}, "CONSUMER_COMPONENT_OWNER_OR_STATUS")
    require(_time(value["observed_at"]) <= _time(value["validated_at"]) <= _time(as_of), "CONSUMER_COMPONENT_TIME")
    require(value["period_statuses"] == {} and isinstance(value["population_id"], str)
            and bool(value["population_id"]), "CONSUMER_COMPONENT_PERIOD_OR_POPULATION")
    require(isinstance(value["evidence_references"], list) and value["evidence_references"],
            "CONSUMER_COMPONENT_REFERENCE_REQUIRED")
    for ref in value["evidence_references"]:
        require(isinstance(ref, dict) and set(ref) == {"path", "sha256", "json_locator"}
                and isinstance(ref["path"], str) and bool(ref["path"])
                and isinstance(ref["sha256"], str) and re.fullmatch(r"[0-9a-f]{64}", ref["sha256"])
                and isinstance(ref["json_locator"], str) and ref["json_locator"].startswith("$"),
                "CONSUMER_COMPONENT_REFERENCE_INVALID")
    passed = value["status"] == "PASS"
    require((value["reason"] is None if passed else isinstance(value["reason"], str) and bool(value["reason"]))
            and (passed or value["value"] is None), "CONSUMER_COMPONENT_VERDICT_CONFLICT")
    if value["value"] is not None:
        require(type(value["value"]) in (str, int, float, Decimal), "CONSUMER_COMPONENT_SCORE_INVALID")
        score_value(Decimal(str(value["value"])))
    return deepcopy(value)


def eligibility_bridge(bundle, *, expected_content_sha256, symbol, market, components, as_of):
    """Input readiness only; never consumes a ranking result or authorizes ranking."""
    require(bundle["artifact_kind"] == KIND and bundle["content_sha256"] == expected_content_sha256
            == digest(bundle["core"]) and bundle["core"]["governance"] == FLAGS,
            "CONSUMER_BRIDGE_VERDICT_BINDING")
    require(_time(bundle["consumer_validated_at"]) <= _time(as_of) <= _time(now()), "CONSUMER_BRIDGE_TIME")
    require(set(components) <= {n for names in RANK_INPUTS.values() for n in names if n != "Fundamental"},
            "CONSUMER_V1_IMPERSONATION_OR_UNKNOWN_COMPONENT")
    selected = [r for r in bundle["core"]["issuers"] if r["symbol"] == symbol and r["market"] == market]
    require(len(selected) == 1, "CONSUMER_BRIDGE_ISSUER")
    fundamental = selected[0]
    require("rank" not in fundamental and fundamental["owner"] == CONTRACT["owner"]
            and fundamental["status"] in {"PASS", "MISSING_REQUIRED_PERIOD"}, "CONSUMER_BRIDGE_FUNDAMENTAL_SCHEMA")
    if fundamental["status"] == "PASS":
        score_value(fundamental["value"])
    else:
        require(fundamental["value"] is None, "CONSUMER_MISSING_SCORE_FORBIDDEN")
    require(_time(fundamental["input_available_at"]) <= _time(as_of), "CONSUMER_BRIDGE_NOT_YET_AVAILABLE")
    others = {name: component_verdict(name, components.get(name), as_of)
              for name in {n for names in RANK_INPUTS.values() for n in names if n != "Fundamental"}}
    for verdict in others.values():
        if verdict.get("population_id") is not None:
            require(verdict["population_id"] == bundle["core"]["population_id"], "CONSUMER_COMPONENT_POPULATION")
    ready = {name: v["status"] == "PASS" and v.get("value") is not None for name, v in others.items()}
    ready["Fundamental"] = fundamental["status"] == "PASS"
    return {"artifact_kind": "RATE_PROSPECTIVE_FUNDAMENTAL_INPUT_BRIDGE_V1", "symbol": symbol, "market": market,
            "fundamental_ready": ready["Fundamental"], "formal_eps_period_identity": "NOT_ASSERTED_V1_UNCHANGED",
            "ranking_authorized": False, "decision_eligible": False,
            "gates": {kind: {"input_ready": all(ready[n] for n in names), "score": None, "rank": None,
                             "missing_components": [n for n in names if not ready[n]]}
                      for kind, names in RANK_INPUTS.items()}}


def execute_ranking(*args, **kwargs):
    raise ValueError("CONSUMER_RANKING_EXECUTION_NOT_AUTHORIZED")
