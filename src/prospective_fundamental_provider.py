"""Prospective acceptance sandbox only. No acquisition, activation or scoring calls."""
from copy import deepcopy
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

from .eps_duration_facts.model import require
from .eps_duration_facts.raw import sha256, verify_receipt
from .finmind_formal_qualification import exact_period
from .full_market_history import put_bytes
from .provider_eps_candidate import API, WINDOW, _canonical, _json, _time, extract_provider_eps
from .provider_eps_dispatch import exclusive_scan
from .provider_eps_metadata import read_metadata
from .provider_financial_features import CONTRACT as FEATURES, hash_object, within_git_checkout
from .provider_revenue_snapshot import endpoint
from .sources.fundamental_history import _warmup_revenue_rows, _decode_response, validate_revenue_semantics
from .sources.mops_raw_evidence import NORMALIZATION_VERSION

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = read_metadata((ROOT / "docs/contracts/RATE_PROSPECTIVE_FUNDAMENTAL_PROVIDER_V1.json").read_bytes())
DATASETS = {"FinMind": "TaiwanStockFinancialStatements", "MOPS Official": "MOPS_MONTHLY_REVENUE_ARCHIVE"}


def parser_identity(provider):
    path = "src/provider_eps_candidate.py" if provider == "FinMind" else "src/sources/fundamental_history.py"
    return {"owner": path, "sha256": sha256((ROOT / path).read_bytes()),
            "bridge_version": CONTRACT["contract_id"], "bridge_sha256": sha256(Path(__file__).read_bytes())}


def inspect_source(provider, target, raw, receipt_bytes, raw_sha256, receipt_sha256, universe, validated_at,
                   original_parser_bytes=None):
    """A1 uses existing parsers; legitimate missing periods do not fail a provider."""
    require(provider in DATASETS, "PROSPECTIVE_PROVIDER_MISMATCH")
    require(sha256(raw) == raw_sha256 and sha256(receipt_bytes) == receipt_sha256, "PROSPECTIVE_SOURCE_TAMPER")
    receipt = read_metadata(receipt_bytes)
    markets = {s["symbol"]: s["market"] for s in universe["stocks"]}
    require(len(markets) == len(universe["stocks"]) and target["market"] in {"TWSE", "TPEX"}, "PROSPECTIVE_UNIVERSE_INVALID")
    identity = parser_identity(provider)
    source_parser_sha = identity["sha256"]
    if original_parser_bytes is not None:
        # Original producer bytes stay pinned separately; only code line endings may differ.
        owner = (ROOT / identity["owner"]).read_bytes()
        require(original_parser_bytes.replace(b"\r\n", b"\n") == owner.replace(b"\r\n", b"\n"),
            "PROSPECTIVE_ORIGINAL_PARSER_CODE_MISMATCH")
        source_parser_sha = sha256(original_parser_bytes)
    if provider == "FinMind":
        require(set(target) == {"symbol", "market"} and markets.get(target["symbol"]) == target["market"], "PROSPECTIVE_ISSUER_MISMATCH")
        query = receipt["query"]
        require(set(query) == {"dataset", "data_id", "start_date", "end_date"} and query["dataset"] == DATASETS[provider] and
            query["data_id"] == target["symbol"] and date.fromisoformat(query["start_date"]) <= date.fromisoformat(query["end_date"]),
            "PROSPECTIVE_DATASET_OR_PERIOD_MISMATCH")
        require(receipt["requested_url"] == API and receipt.get("attempts") == 1, "PROSPECTIVE_ENDPOINT_OR_RETRY_MISMATCH")
        source_url = API + "?" + urlencode({k: query[k] for k in ("dataset", "data_id", "start_date", "end_date")})
        received, requested = receipt["received_at"], receipt["started_at"]
        metadata = {"endpoint": source_url, "fallback_used": receipt.get("fallback_used", False), "attempts": [{
            "transport_integrity": "PASS", "final_url": receipt["final_url"], "http_status": receipt["http_status"],
            "response_bytes": receipt["bytes"], "content_length": receipt.get("content_length"),
            "body_sha256": receipt["response_body_sha256"], "retrieved_at": received}]}
        payload = _json(raw)
        require(payload.get("status") == 200 and isinstance(payload.get("data"), list), "PROSPECTIVE_SCHEMA_MISMATCH")
        selected = extract_provider_eps(payload["data"], query)
        rows = []
        for index, row in selected.items():
            quarter = next((q for q in WINDOW if exact_date(q) == row["date"]), None)
            require(quarter is not None, "PROSPECTIVE_NON_EXACT_PERIOD")
            exact_period(row["date"], quarter)
            require(row["date"] <= _time(received).date().isoformat(), "PROSPECTIVE_FUTURE_PERIOD")
            rows.append({"symbol": target["symbol"], "market": target["market"], "period": quarter,
                "value": str(row["value"]), "numeric_status": "VALID_NUMERIC", "provider_date": row["date"],
                "provider_type": row["type"], "provider_origin_name": row["origin_name"], "json_locator": f"$.data[{index}]",
                "raw_row_index_zero_based": index, "filing_id": None, "revision_id": None, "public_time": None})
        expected_symbols, required = [target["symbol"]], list(WINDOW)
        scope = {"provider": provider, **target}
        require(_time(received) <= _time(receipt["finished_at"]) <= _time(validated_at), "PROSPECTIVE_FUTURE_TIMESTAMP")
    else:
        require(set(target) == {"market", "period"} and target["period"] in FEATURES["revenue_months"], "PROSPECTIVE_PERIOD_MISMATCH")
        source_url = endpoint(target["market"], target["period"])
        require(receipt["source_owner"] == provider and receipt["domain"] == "revenue" and
            receipt["market"] == target["market"] and receipt["requested_period"] == target["period"] and
            receipt["endpoint"] == source_url and receipt["normalization_version"] == NORMALIZATION_VERSION and
            receipt["parser_sha256"] == source_parser_sha, "PROSPECTIVE_PROVIDER_DATASET_ENDPOINT_MISMATCH")
        received, requested = receipt["retrieval_timestamp"], receipt.get("request_started_at")
        require(target["period"] < _time(received).strftime("%Y-%m"), "PROSPECTIVE_FUTURE_PERIOD")
        metadata = {"endpoint": source_url, "fallback_used": receipt["fallback_used"], "attempts": [{
            "transport_integrity": "PASS", "final_url": receipt["final_url"], "http_status": receipt["http_status"],
            "response_bytes": receipt["response_bytes"], "content_length": receipt.get("content_length"),
            "body_sha256": receipt["body_sha256"], "retrieved_at": received}]}
        parsed, failures = _warmup_revenue_rows(_decode_response(raw), target["market"], target["period"],
            {**receipt, "raw_response_reference": {"path": "CONTENT_ADDRESSED_SANDBOX_RECEIPT", "sha256": receipt_sha256}})
        require(not failures, "PROSPECTIVE_REVENUE_SCHEMA_MISMATCH")
        require(len({r["symbol"] for r in parsed}) == len(parsed), "PROSPECTIVE_DUPLICATE_ISSUER")
        rows = []
        for index, row in enumerate(parsed):
            validate_revenue_semantics(row)
            if row["symbol"] not in markets:
                continue
            require(markets[row["symbol"]] == row["market"], "PROSPECTIVE_ISSUER_MISMATCH")
            rows.append({"symbol": row["symbol"], "market": row["market"], "period": row["revenue_period"],
                "value": str(row["revenue_yoy"]) if row["revenue_yoy"] is not None else None,
                "numeric_status": row["revenue_yoy_status"], "json_locator": {"parsed_row_index_zero_based": index,
                    "symbol": row["symbol"], "market": row["market"], "period": row["revenue_period"]}})
        expected_symbols = sorted(s for s, m in markets.items() if m == target["market"])
        required, scope = [target["period"]], {"provider": provider, **target}
    verify_receipt(metadata, raw, source_url)
    require(_time(received) <= _time(validated_at) <= datetime.now(timezone.utc), "PROSPECTIVE_FUTURE_TIMESTAMP")
    if requested is not None:
        require(_time(requested) <= _time(received), "PROSPECTIVE_TIMESTAMP_ORDER")
    require(all(r.get("original_publication_timestamp") is None for r in (receipt,)), "PROSPECTIVE_PUBLICATION_CLAIM_FORBIDDEN")
    return {"provider": provider, "dataset": DATASETS[provider], "target": target, "scope": scope,
        "source_url": source_url, "endpoint": API if provider == "FinMind" else source_url,
        "requested_at": requested, "received_at": received, "source_observed_at": received,
        "original_publication_timestamp": None, "historical_pit": "UNPROVEN",
        "raw_sha256": raw_sha256, "receipt_sha256": receipt_sha256, "parser_version": identity,
        "source_parser_sha256": source_parser_sha,
        "validation_timestamp": validated_at, "expected_symbols": expected_symbols, "required_periods": required,
        "rows": rows, "source_identity_gate": "PASS", "fallback_allowed": False}


def exact_date(quarter):
    from .finmind_formal_qualification import ENDS
    return ENDS[quarter]


def prospective_record(inspection, activation_timestamp, first_seen_at):
    """A proposed timestamp is sandbox input, never an authorization command."""
    require(inspection["source_identity_gate"] == "PASS", "PROSPECTIVE_SOURCE_NOT_VALIDATED")
    require(inspection["requested_at"] is not None, "PROSPECTIVE_REQUEST_TIME_NOT_EVIDENCED")
    activation, requested, received, observed, validated, first = map(_time, (activation_timestamp,
        inspection["requested_at"], inspection["received_at"], inspection["source_observed_at"],
        inspection["validation_timestamp"], first_seen_at))
    require(activation <= requested <= received == observed <= validated <= first <= datetime.now(timezone.utc),
        "PROSPECTIVE_PRE_ACTIVATION_OR_FUTURE_OBSERVATION")
    require(inspection["original_publication_timestamp"] is None and inspection["historical_pit"] == "UNPROVEN" and
        inspection["fallback_allowed"] is False, "PROSPECTIVE_HISTORICAL_OR_FALLBACK_PROMOTION")
    core = {**deepcopy(inspection), "candidate_activation_timestamp": activation_timestamp,
        "first_seen_at": first_seen_at, "decision_available_at": first_seen_at,
        "availability_semantics": "SYSTEM_OBSERVATION_NOT_ORIGINAL_PUBLICATION",
        "provider_authorization": "NOT_AUTHORIZED", "sandbox_only": True,
        "production_eligible": False, "original_eight_quarter_coverage_credit": 0}
    core["issuer_acquisition_records"] = [{"symbol": symbol, "market": inspection["target"]["market"],
        "provider": inspection["provider"], "dataset": inspection["dataset"],
        "required_periods": inspection["required_periods"],
        "observed_periods": [r["period"] for r in inspection["rows"] if r["symbol"] == symbol],
        "receipt_sha256": inspection["receipt_sha256"], "raw_sha256": inspection["raw_sha256"],
        "requested_at": inspection["requested_at"], "received_at": inspection["received_at"],
        "source_observed_at": inspection["source_observed_at"], "first_seen_at": first_seen_at,
        "source_url": inspection["source_url"], "parser_version": inspection["parser_version"],
        "validation_timestamp": inspection["validation_timestamp"]} for symbol in inspection["expected_symbols"]]
    return {**core, "immutable_snapshot_id": "prospective-acquisition-" + hash_object(core)}


def new_store(root, universe, execution, candidate_activation_timestamp):
    root = Path(root).resolve()
    require(not root.exists() and not within_git_checkout(root) and not any(p.casefold() in
        {"production", "latest", "state", "portfolio", "ledger", "artifacts", "snapshots"} for p in root.parts),
        "PROSPECTIVE_FRESH_EXTERNAL_SANDBOX_REQUIRED")
    require(universe["verification_status"] == "PASS" and
        Counter(s["market"] for s in universe["stocks"]) == {"TWSE": 1085, "TPEX": 893} and
        len({s["symbol"] for s in universe["stocks"]}) == 1978 and
        set(execution) == {"base_sha", "head_sha"} and execution["base_sha"] == CONTRACT["base_sha"] and
        all(isinstance(v, str) and len(v) == 40 and set(v) <= set("0123456789abcdef") for v in execution.values()),
        "PROSPECTIVE_STORE_BINDING_MISMATCH")
    _time(candidate_activation_timestamp)
    root.mkdir(parents=True, exist_ok=False)
    (root / "events").mkdir()
    config = {"artifact_kind": "RATE_PROSPECTIVE_PROVIDER_EVIDENCE_SANDBOX_V1", "contract": CONTRACT,
        "universe": universe, "execution": execution, "activation_timestamp": None,
        "candidate_activation_timestamp": candidate_activation_timestamp, "production_eligible": False}
    put_bytes(root, "SANDBOX.json", _canonical(config))
    return sha256((root / "SANDBOX.json").read_bytes())


def replay(root, config_sha256, trusted_head, as_of):
    root = Path(root)
    body = (root / "SANDBOX.json").read_bytes()
    require(sha256(body) == config_sha256, "PROSPECTIVE_CONFIG_TAMPER")
    config = read_metadata(body)
    require(config["contract"] == CONTRACT and config["activation_timestamp"] is None and config["production_eligible"] is False,
        "PROSPECTIVE_ACTIVATION_FORBIDDEN")
    events, head, previous_scope = [], None, {}
    paths = sorted((root / "events").iterdir())
    for index, path in enumerate(paths):
        event_bytes = path.read_bytes()
        event = read_metadata(event_bytes)
        require(path.name == f"{index:08d}-" + sha256(event_bytes) + ".json" and event["previous_head"] == head and
            event["config_sha256"] == config_sha256, "PROSPECTIVE_CHAIN_TAMPER")
        saved = event["record"]
        require(saved["candidate_activation_timestamp"] == config["candidate_activation_timestamp"], "PROSPECTIVE_ACTIVATION_BINDING_MISMATCH")
        scope_key = hash_object(saved["scope"])
        require(event["previous_scope_observation"] == previous_scope.get(scope_key), "PROSPECTIVE_REVISION_CHAIN_TAMPER")
        raw = (root / "raw" / (saved["raw_sha256"] + ".bin")).read_bytes()
        receipt = (root / "receipts" / (saved["receipt_sha256"] + ".json")).read_bytes()
        inspected = inspect_source(saved["provider"], saved["target"], raw, receipt, saved["raw_sha256"],
            saved["receipt_sha256"], config["universe"], saved["validation_timestamp"])
        require(saved == prospective_record(inspected, saved["candidate_activation_timestamp"], saved["first_seen_at"]),
            "PROSPECTIVE_RECORD_REPLAY_MISMATCH")
        require(_time(saved["first_seen_at"]) <= _time(as_of) and (not events or
            _time(events[-1]["record"]["first_seen_at"]) <= _time(saved["first_seen_at"])), "PROSPECTIVE_FIRST_SEEN_ORDER_INVALID")
        previous_scope[scope_key] = saved["immutable_snapshot_id"]
        events.append(event)
        head = sha256(event_bytes)
    require(head == trusted_head, "PROSPECTIVE_TRUSTED_HEAD_MISMATCH")
    return config, events


def append(root, config_sha256, trusted_head, provider, target, raw, receipt, activation_timestamp, observed_now):
    """CAS head + existing OS writer lock; no existing evidence is overwritten."""
    with exclusive_scan(root):
        config, events = replay(root, config_sha256, trusted_head, observed_now)
        require(activation_timestamp == config["candidate_activation_timestamp"], "PROSPECTIVE_ACTIVATION_BINDING_MISMATCH")
        inspection = inspect_source(provider, target, raw, receipt, sha256(raw), sha256(receipt), config["universe"], observed_now)
        record = prospective_record(inspection, activation_timestamp, observed_now)
        require(all(e["record"]["receipt_sha256"] != record["receipt_sha256"] for e in events), "PROSPECTIVE_DUPLICATE_OBSERVATION")
        prior = next((e["record"]["immutable_snapshot_id"] for e in reversed(events) if e["record"]["scope"] == record["scope"]), None)
        event = {"config_sha256": config_sha256, "previous_head": trusted_head, "previous_scope_observation": prior,
            "version_semantics": "LOCAL_OBSERVATION_ORDER_NOT_PROVIDER_REVISION_ORDER", "record": record}
        body = _canonical(event)
        put_bytes(root, "raw/" + record["raw_sha256"] + ".bin", raw)
        put_bytes(root, "receipts/" + record["receipt_sha256"] + ".json", receipt)
        put_bytes(root, f"events/{len(events):08d}-" + sha256(body) + ".json", body)
        return sha256(body)


def issuer_readiness(config, events):
    # Replace a whole acquisition scope, never silently keep a removed old row.
    latest = {}
    for event in events:
        record = event["record"]
        latest[hash_object(record["scope"])] = record
    index = {}
    for record in latest.values():
        for row in record["rows"]:
            key = (record["provider"], row["symbol"], row["period"])
            require(key not in index, "PROSPECTIVE_OVERLAPPING_SCOPE")
            index[key] = row
    result = []
    for stock in config["universe"]["stocks"]:
        missing = {}
        for provider, periods in (("FinMind", WINDOW), ("MOPS Official", FEATURES["revenue_months"])):
            missing[provider] = [{"period": p, "reason": "MISSING_REQUIRED_PERIOD" if (provider, stock["symbol"], p) not in index
                else index[(provider, stock["symbol"], p)]["numeric_status"]} for p in periods
                if (provider, stock["symbol"], p) not in index or index[(provider, stock["symbol"], p)]["numeric_status"] != "VALID_NUMERIC"]
        result.append({**stock, "eps_status": "READY" if not missing["FinMind"] else "NOT_READY_MISSING_REQUIRED_PERIOD",
            "revenue_status": "READY" if not missing["MOPS Official"] else "NOT_READY_MISSING_REQUIRED_PERIOD",
            "fundamental_input_status": "READY" if not any(missing.values()) else "NOT_READY_MISSING_REQUIRED_PERIOD",
            "missing_reasons": missing, "valid_partial_periods": [deepcopy(r) for (provider, symbol, period), r in index.items() if symbol == stock["symbol"]],
            "ranking_eligible": False, "production_eligible": False})
    return result


def review_decision(identity_results, engineering_pass):
    require(set(identity_results) == set(DATASETS) and all(v in {"PASS", "FAIL"} for v in identity_results.values()),
        "PROSPECTIVE_PROVIDER_MATRIX_INCOMPLETE")
    ready = engineering_pass is True and all(v == "PASS" for v in identity_results.values())
    return {"gate_a7": "READY_FOR_PROSPECTIVE_PROVIDER_ACTIVATION_REVIEW" if ready else "BLOCKED",
        "providers": [{"provider": p, "dataset": DATASETS[p], "gate_a1": identity_results[p],
            "proposed_authorization": "AUTHORIZED" if identity_results[p] == "PASS" and engineering_pass is True else "NOT_AUTHORIZED",
            "provider_authorization": "NOT_AUTHORIZED", "issuer_completeness_is_not_provider_qualification": True}
            for p in DATASETS], "activation_timestamp": None, "historical_pit": "UNPROVEN",
        "production_eligible": False, "original_eight_quarter_coverage_credit": 0,
        "first_refresh_allowed": False, "ranking_activation_allowed": False, "fallback_allowed": False}
