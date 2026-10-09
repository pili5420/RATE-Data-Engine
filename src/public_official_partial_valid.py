"""Report-only official evidence. Never supplies a current quote or executes a trade."""
from __future__ import annotations

import copy
import hashlib
import json
import math
from datetime import date, datetime, timezone
from pathlib import Path

from src.cer074_acceptance import atomic_write_json, sha256, strip_runtime
from src.production_live_state import ARTIFACTS, CADENCE_DIR, load_live_state, require, validate_material
from src.provider_eps_metadata import read_metadata, _object, _constant, _finite

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "config/RATE_PUBLIC_OFFICIAL_PARTIAL_VALID_RUNTIME_V1.json"
KIND = "RATE_PUBLIC_OFFICIAL_EVIDENCE_BUNDLE_V1"
DEPENDENCY = "EXTERNAL_AUTHORIZED_INTRADAY_FEED_DEPENDENCY"
BLOCKED = "BLOCKED_BY_INTRADAY_PRICE_FEED"


def now():
    return datetime.now(timezone.utc).isoformat()


def timestamp(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    require(parsed.tzinfo is not None, "PUBLIC_OBSERVATION_TIMEZONE_REQUIRED")
    return parsed


def digest_bytes(body):
    return hashlib.sha256(body).hexdigest()


def read_rows(body):
    payload = json.loads(body, object_pairs_hook=_object, parse_constant=_constant)
    _finite(payload)
    return payload


def policy():
    contract = read_metadata(CONTRACT_PATH.read_bytes())
    gov = read_metadata((ROOT / "config/RATE_PUBLIC_INTRADAY_REFERENCE_GOVERNANCE_V1.json").read_bytes())
    dependencies = read_metadata((ROOT / "config/RATE_EXTERNAL_PRODUCTION_DEPENDENCIES.json").read_bytes())
    dependency = next(d for d in dependencies["dependencies"] if d["dependency_id"] == DEPENDENCY)
    require(gov["status"] == "APPROVED" and dependency["status"] == "BLOCKED_EXTERNAL"
        and dependency["fallback_allowed"] is False
        and dependency["production_acceptance_allowed_while_blocked"] is False, "PUBLIC_GOVERNANCE_BOUNDARY_INVALID")
    return contract


def entries():
    from scripts.build_production_source_bundle_from_official import load_source_registry
    registry = load_source_registry(ROOT / "config/RATE_PRODUCTION_OFFICIAL_SOURCE_REGISTRY_V1.json")
    wanted = policy()["required_dataset_ids"]
    result = [item for item in registry["datasets"] if item["dataset_id"] in wanted]
    require(len(result) == len(wanted), "PUBLIC_SOURCE_MISSING")
    for item in result:
        require(item["authorization_status"] == "PASS" and item["fallback_allowed"] is False
            and item["domain"] != "market_intraday", "PUBLIC_SOURCE_AUTHORIZATION_INVALID")
        endpoint = item["endpoint"]
        prefix = "https://openapi.twse.com.tw/v1/" if item["authority"] == "TWSE" else "https://www.tpex.org.tw/openapi/v1/"
        require(endpoint.startswith(prefix), "PUBLIC_DOCUMENTED_ENDPOINT_REQUIRED")
    return result


def _first(row, fields):
    present = [row[field] for field in fields if field in row]
    require(present, "PUBLIC_SCHEMA_FIELD_MISSING:" + fields[0])
    return present[0]


def _numeric(value, *, minimum=None):
    if value is None or isinstance(value, str) and value.strip() in ("", "-", "--", "---"):
        return
    require(not isinstance(value, bool), "PUBLIC_INVALID_NUMERIC")
    try:
        number = float(str(value).replace(",", ""))
    except (ValueError, TypeError, OverflowError) as error:
        raise RuntimeError("PUBLIC_INVALID_NUMERIC") from error
    require(math.isfinite(number), "PUBLIC_INVALID_NUMERIC")
    require(minimum is None or number >= minimum, "PUBLIC_INVALID_NUMERIC")


def validate_rows(payload, entry, trading_date):
    # Do not infer a trading status or financial score from generic issuer metadata.
    from scripts.build_production_source_bundle_from_official import _normalize_source_date
    from scripts.resolve_production_runtime_context import _previous_legal_trading_day
    require(isinstance(payload, list) and payload and all(isinstance(row, dict) for row in payload), "PUBLIC_SCHEMA_INVALID")
    contract = policy()
    result, seen = [], set()
    domain = entry["domain"]
    for index, row in enumerate(payload):
        if domain == "benchmark":
            raw_identity = _first(row, ("IndexName", "Name", "指數", "symbol"))
            _numeric(_first(row, ("ClosingIndex", "收盤指數", "close")), minimum=0)
        else:
            raw_identity = _first(row, ("Code", "SecuritiesCompanyCode", "公司代號", "CompanyCode", "symbol"))
        require(isinstance(raw_identity, str) and raw_identity.strip(), "PUBLIC_IDENTITY_INVALID")
        identity = raw_identity.strip()
        require(identity and identity not in seen, "PUBLIC_DUPLICATE_INVALID")
        seen.add(identity)
        raw_day = _first(row, ("Date", "日期", "出表日期", "資料日期", "publication_date"))
        day = _normalize_source_date(raw_day)
        date.fromisoformat(day)
        require(day <= trading_date, "PUBLIC_FUTURE_DATED")
        if domain in ("market_daily", "benchmark") or entry["dataset_id"] == "tpex_trading_metadata":
            require(day == _previous_legal_trading_day(trading_date), "PUBLIC_PREVIOUS_EOD_DATE_MISMATCH")
        else:
            require((date.fromisoformat(trading_date) - date.fromisoformat(day)).days <= contract["publication_max_age_days"][domain],
                "PUBLIC_PUBLICATION_STALE")
        if domain == "market_daily":
            _numeric(_first(row, ("ClosingPrice", "Close")), minimum=0)
            _numeric(_first(row, ("TradeVolume", "TradingShares", "TradingVolume")), minimum=0)
        if domain == "fundamental":
            period = str(_first(row, ("資料年月", "reporting_month"))).replace("/", "").replace("-", "")
            require(period.isdigit() and len(period) in (5, 6), "PUBLIC_REPORTING_PERIOD_INVALID")
            year = int(period[:-2]) + (1911 if len(period) == 5 else 0)
            month = int(period[-2:])
            require(date(year, month, 1) <= date.fromisoformat(trading_date), "PUBLIC_FUTURE_REPORTING_PERIOD")
            _numeric(_first(row, ("營業收入-當月營收", "revenue")))
        result.append({"identity": identity, "publication_or_source_date": day,
            "raw_row_index": index, "json_locator": f"$[{index}]", "raw_fields": copy.deepcopy(row)})
    return result


def validate_bundle(bundle, *, trading_date, cadence, as_of=None, archive_directory=None):
    contract = policy()
    require(cadence in contract["cadences"], "PUBLIC_CADENCE_FORBIDDEN")
    require(bundle.get("artifact") == KIND and bundle.get("trading_date") == trading_date
        and bundle.get("cadence") == cadence, "PUBLIC_BUNDLE_IDENTITY_INVALID")
    core = {k: v for k, v in bundle.items() if k != "content_sha256"}
    require(bundle.get("content_sha256") == sha256(core), "PUBLIC_BUNDLE_HASH_MISMATCH")
    require(bundle.get("contract_sha256") == digest_bytes(CONTRACT_PATH.read_bytes()), "PUBLIC_CONTRACT_HASH_MISMATCH")
    require(bundle.get("validation_status") == "PASS" and bundle.get("public_official_evidence_gate") == "PASS"
        and bundle.get("market_intraday_price_gate") == "BLOCKED_EXTERNAL"
        and bundle.get("full_intraday_decision_status") == "BLOCKED_EXTERNAL"
        and bundle.get("report_runtime_status") == "PARTIAL_VALID"
        and bundle.get("full_production_acceptance") == "NOT_ALLOWED"
        and bundle.get("fallback_allowed") is False, "PUBLIC_GATE_INVALID")
    required = {item["dataset_id"]: item for item in entries()}
    require(isinstance(bundle.get("sources"), list) and len(bundle["sources"]) == len(required)
        and {s["dataset_id"] for s in bundle["sources"]} == set(required), "PUBLIC_SOURCE_MISSING")
    clock = timestamp(as_of or now())
    require(timestamp(bundle["generated_at"]) <= clock, "PUBLIC_FUTURE_OBSERVATION")
    for source in bundle["sources"]:
        entry = required[source["dataset_id"]]
        require(source["authority"] == entry["authority"] and source["domain"] == entry["domain"], "PUBLIC_SOURCE_IDENTITY_INVALID")
        archive = Path(archive_directory) / "public_sources" if archive_directory is not None else None
        receipt_bytes = (archive / (source["dataset_id"] + ".receipt.json") if archive else Path(source["receipt_path"])).read_bytes()
        require(digest_bytes(receipt_bytes) == source["receipt_sha256"], "PUBLIC_RECEIPT_HASH_MISMATCH")
        receipt = read_metadata(receipt_bytes)
        body = (archive / (source["dataset_id"] + ".response") if archive else Path(receipt["raw_path"])).read_bytes()
        require(receipt["endpoint"] == entry["endpoint"] == receipt["final_url"] and receipt["http_status"] == 200
            and receipt["parser_version"] == entry["parser"] and receipt["dataset_id"] == source["dataset_id"], "PUBLIC_SOURCE_IDENTITY_INVALID")
        require(digest_bytes(body) == receipt["raw_sha256"] and len(body) == receipt["bytes"], "PUBLIC_RAW_HASH_MISMATCH")
        require(timestamp(receipt["observed_at"]) <= timestamp(receipt["validated_at"]) <= timestamp(bundle["generated_at"]) <= clock,
            "PUBLIC_OBSERVATION_ORDER_INVALID")
        require(0 <= (clock - timestamp(receipt["observed_at"])).total_seconds() <= contract["observation_max_age_minutes"][cadence] * 60,
            "PUBLIC_OBSERVATION_STALE_OR_FUTURE")
        rows = validate_rows(read_rows(body), entry, trading_date)
        require(source["rows"] == rows and source["raw_sha256"] == receipt["raw_sha256"], "PUBLIC_SOURCE_REPLAY_MISMATCH")
    return {"public_official_evidence_gate": "PASS", "market_intraday_price_gate": "BLOCKED_EXTERNAL",
        "report_runtime_status": "PARTIAL_VALID", "full_intraday_decision_status": "BLOCKED_EXTERNAL",
        "full_production_acceptance": "NOT_ALLOWED", "fallback_allowed": False}


def acquire(*, trading_date, cadence, output, evidence_output, fetcher=None):
    from scripts.build_production_source_bundle_from_official import fetch_url
    require(cadence in policy()["cadences"], "PUBLIC_CADENCE_FORBIDDEN")
    output = Path(output)
    archive = output.parent / (output.stem + "-public-sources")
    require(not output.exists() and not archive.exists(), "PUBLIC_IMMUTABLE_OUTPUT_EXISTS")
    archive.mkdir(parents=True)
    fetcher = fetcher or (lambda endpoint: fetch_url(endpoint, preserve_body=True))
    sources, cache = [], {}
    try:
        for index, entry in enumerate(entries()):
            endpoint = entry["endpoint"]
            if endpoint not in cache:
                cache[endpoint] = fetcher(endpoint)
            fetched = cache[endpoint]
            body = fetched["raw_bytes"]
            raw_path = archive / f"{index:02d}.response"
            raw_path.write_bytes(body)
            receipt = {"dataset_id": entry["dataset_id"], "endpoint": endpoint,
                "final_url": fetched["final_url"], "http_status": fetched["http_status"],
                "observed_at": fetched["retrieval_timestamp"], "validated_at": now(),
                "raw_path": str(raw_path.resolve()), "raw_sha256": digest_bytes(body), "bytes": len(body),
                "parser_version": entry["parser"], "source_role": "PUBLIC_OFFICIAL_NOT_CURRENT_INTRADAY"}
            receipt_path = archive / f"{index:02d}.receipt.json"
            atomic_write_json(receipt_path, receipt)
            require(receipt["http_status"] == 200 and receipt["final_url"] == endpoint, "PUBLIC_HTTP_OR_REDIRECT_INVALID")
            rows = validate_rows(read_rows(body), entry, trading_date)
            sources.append({"dataset_id": entry["dataset_id"], "domain": entry["domain"], "authority": entry["authority"],
                "raw_sha256": receipt["raw_sha256"], "receipt_path": str(receipt_path.resolve()),
                "receipt_sha256": digest_bytes(receipt_path.read_bytes()), "rows": rows})
        bundle = {"artifact": KIND, "contract_sha256": digest_bytes(CONTRACT_PATH.read_bytes()),
            "trading_date": trading_date, "cadence": cadence, "generated_at": now(), "sources": sources,
            "validation_status": "PASS", "public_official_evidence_gate": "PASS", "market_intraday_price_gate": "BLOCKED_EXTERNAL",
            "report_runtime_status": "PARTIAL_VALID", "full_intraday_decision_status": "BLOCKED_EXTERNAL",
            "full_production_acceptance": "NOT_ALLOWED", "fallback_allowed": False,
            "unconfigured_evidence": {name: "NOT_CONFIGURED_NOT_ASSERTED_CLEAR" for name in policy()["unconfigured_evidence"]}}
        bundle["content_sha256"] = sha256(bundle)
        gates = validate_bundle(bundle, trading_date=trading_date, cadence=cadence)
        atomic_write_json(output, bundle)
        evidence = {"artifact": "RATE_PUBLIC_OFFICIAL_ACQUISITION_EVIDENCE", "validation_status": "PASS",
            **gates, "public_source_bundle_path": str(output), "content_sha256": bundle["content_sha256"],
            "request_count": len(cache), "fallback_used": False, "full_production_pass": False}
        atomic_write_json(Path(evidence_output), evidence)
        return evidence
    except Exception as error:
        atomic_write_json(Path(evidence_output), {"artifact": "RATE_PUBLIC_OFFICIAL_ACQUISITION_EVIDENCE",
            "validation_status": "FAIL_CLOSED", "public_official_evidence_gate": "FAIL", "report_runtime_status": "FAIL_CLOSED",
            "reason": str(error), "acquired_datasets": [s["dataset_id"] for s in sources], "fallback_used": False})
        raise


def transition(previous, bundle):
    day, cadence = bundle["trading_date"], bundle["cadence"]
    previous_decision = previous["decision"]
    expected = "07:30" if cadence == "09:30" else "09:30"
    require(previous_decision["trading_date"] == day and previous_decision["cadence"] == expected, "PUBLIC_PREVIOUS_STATE_SCOPE_INVALID")
    require(previous["decision_payload_hash"] == sha256(strip_runtime(previous_decision))
        and previous["current_state_id"] == "rate-state-" + previous["decision_payload_hash"][:24], "PUBLIC_PREVIOUS_STATE_CORRUPTED")
    gates = validate_bundle(bundle, trading_date=day, cadence=cadence)
    if cadence == "12:00":
        require(previous_decision.get("report_runtime_status") == "PARTIAL_VALID", "PUBLIC_0930_STATE_REQUIRED")
    old_evidence = previous_decision.get("public_official_evidence_state", {})
    current_evidence = {source["dataset_id"]: {"raw_sha256": source["raw_sha256"],
        "row_content_sha256": sha256(source["rows"]), "receipt_path": source["receipt_path"],
        "receipt_sha256": source["receipt_sha256"]} for source in bundle["sources"]}
    changed = [key for key, value in current_evidence.items()
        if old_evidence.get(key, {}).get("row_content_sha256") != value["row_content_sha256"]]
    decision = copy.deepcopy(previous_decision)
    decision.update(trading_date=day, cadence=cadence, execution_scope="PRODUCTION",
        previous_state_resolution="PERSISTED_PRODUCTION_STATE", previous_state_id=previous["current_state_id"],
        previous_state_hash=previous["decision_payload_hash"], **gates,
        public_official_evidence_state=current_evidence, public_official_bundle=copy.deepcopy(bundle),
        public_official_delta="DETECTED" if changed else "NONE", public_official_changed_datasets=changed,
        blocked_modules=policy()["blocked_modules"], updated_modules=policy()["updated_modules"],
        full_production_pass=False, scheduled_soak_credit=False, ai_paper_execution_status=BLOCKED,
        ai_signal_status="PRESERVED_NOT_RECALCULATED", trade_intent_status="PRESERVED_NOT_EXECUTED",
        intraday_modules={name: {"status": BLOCKED, "value": None} for name in policy()["blocked_modules"]},
        ranking_observation_role="PREVIOUS_STATE_NOT_INTRADAY_RERANKED")
    if cadence == "09:30":
        decision["previous_state_records"] = copy.deepcopy(previous_decision.get("records", []))
    decision["records"] = [{"symbol": row["symbol"], "current_price": None, "current_volume": None,
        "intraday_status": BLOCKED, "previous_record_locator": f"$.previous_state_records[{i}]"}
        for i, row in enumerate(decision["previous_state_records"])]
    decision["watchlist_evidence"] = [{"symbol": row["symbol"], "source_rows": [
        {"dataset_id": source["dataset_id"], "json_locator": item["json_locator"],
            "raw_sha256": source["raw_sha256"], "publication_or_source_date": item["publication_or_source_date"]}
        for source in bundle["sources"] for item in source["rows"] if item["identity"] == row["symbol"]],
        "intraday_price_status": BLOCKED} for row in decision["records"]]
    decision["report_commentary_inputs"] = {**gates, "public_official_delta": decision["public_official_delta"],
        "changed_datasets": changed, "unconfigured_evidence": copy.deepcopy(bundle["unconfigured_evidence"]),
        "prior_ranking_role": "PREVIOUS_STATE_NOT_INTRADAY_RERANKED"}
    digest = sha256(strip_runtime(decision))
    return {"current_state_id": "rate-state-" + digest[:24], "decision_payload_hash": digest,
        "previous_state_id": previous["current_state_id"], "decision": decision}


def validate_partial_state(decision):
    require(decision["cadence"] in policy()["cadences"], "PUBLIC_STATE_CADENCE_INVALID")
    require(decision.get("report_runtime_status") == "PARTIAL_VALID"
        and decision.get("public_official_evidence_gate") == "PASS"
        and decision.get("market_intraday_price_gate") == "BLOCKED_EXTERNAL"
        and decision.get("full_intraday_decision_status") == "BLOCKED_EXTERNAL"
        and decision.get("full_production_acceptance") == "NOT_ALLOWED"
        and decision.get("fallback_allowed") is False and decision.get("full_production_pass") is False
        and decision.get("ai_paper_execution_status") == BLOCKED, "PUBLIC_STATE_GATE_INVALID")
    require(decision.get("intraday_modules") == {name: {"status": BLOCKED, "value": None} for name in policy()["blocked_modules"]},
        "PUBLIC_INTRADAY_VALUE_FORBIDDEN")
    expected = [{"symbol": row["symbol"], "current_price": None, "current_volume": None,
        "intraday_status": BLOCKED, "previous_record_locator": f"$.previous_state_records[{i}]"}
        for i, row in enumerate(decision["previous_state_records"])]
    require(decision["records"] == expected, "PUBLIC_CURRENT_PRICE_FORBIDDEN")


def run(*, source_bundle, previous_evidence, output_dir, state_root, cadence):
    from src.production_live_state import PERSIST_NAME
    path = Path(previous_evidence).resolve()
    require(path.name == PERSIST_NAME and path.parent.parent.parent.name == "live", "PUBLIC_CANONICAL_PREVIOUS_STATE_REQUIRED")
    day = path.parent.parent.name
    previous_cadence = "07:30" if cadence == "09:30" else "09:30"
    loaded = load_live_state(path.parents[3], day, previous_cadence)
    require(loaded["path"].resolve() == path, "PUBLIC_PREVIOUS_PATH_MISMATCH")
    bundle = read_metadata(Path(source_bundle).read_bytes())
    state = transition(loaded["state"], bundle)
    require(bundle["cadence"] == cadence, "PUBLIC_CADENCE_MISMATCH")
    validate_partial_state(state["decision"])
    for key in ("roy_portfolio", "ai_paper_portfolio", "ai_paper_portfolio_ledger", "transaction_ledger", "model_learning_state", "top50", "short_top30", "long_top30"):
        require(state["decision"].get(key) == loaded["state"]["decision"].get(key), "PUBLIC_PROTECTED_STATE_CHANGED:" + key)
    entry = {key: state["decision"][key] for key in ("trading_date", "cadence", "execution_scope", "previous_state_resolution", "previous_state_id")}
    entry.update(current_state_id=state["current_state_id"], decision_payload_hash=state["decision_payload_hash"],
        report_runtime_status="PARTIAL_VALID")
    material = {"state_entry": entry, "decision_state": state}
    persist = {"artifact": ARTIFACTS[cadence], "validation_status": "PASS", "report_runtime_status": "PARTIAL_VALID",
        "full_production_acceptance": "NOT_ALLOWED", "current_state_id": state["current_state_id"],
        "current_state_hash": state["decision_payload_hash"], "previous_state_id": state["previous_state_id"],
        "persist_result": {"status": "PERSISTED", "state_entry": entry}}
    validate_material(persist, material, day, cadence)
    target = Path(state_root) / "decision_state" / CADENCE_DIR[cadence] / (state["current_state_id"] + ".json")
    if target.exists():
        require(read_metadata(target.read_bytes()) == material, "PUBLIC_STATE_IDEMPOTENCY_CONFLICT")
    else:
        atomic_write_json(target, material)
    out = Path(output_dir)
    filename = ARTIFACTS[cadence] + ".json"
    atomic_write_json(out / filename, persist)
    atomic_write_json(out / "RATE_PUBLIC_OFFICIAL_RUNTIME_RESULT.json", {"validation_status": "PASS",
        **{k: state["decision"][k] for k in ("public_official_evidence_gate", "market_intraday_price_gate", "report_runtime_status",
            "full_intraday_decision_status", "full_production_acceptance", "blocked_modules", "updated_modules", "public_official_delta")},
        "previous_state_id": state["previous_state_id"], "current_state_id": state["current_state_id"],
        "transaction_ledger_mutated": False, "new_intraday_fills": 0, "ai_paper_execution_status": BLOCKED})
    return persist


def publish_report(*, source_bundle_path, trading_date, cadence, artifacts_root, workflow_run_id, workflow_job_id, evidence_output):
    import os
    require(os.getenv("GITHUB_EVENT_NAME") == "schedule" and os.getenv("GITHUB_REF") == "refs/heads/main"
        and str(workflow_run_id).isdigit() and str(workflow_job_id).isdigit(), "PUBLIC_REPORT_SCHEDULE_PROVENANCE_REQUIRED")
    bundle = read_metadata(Path(source_bundle_path).read_bytes())
    gates = validate_bundle(bundle, trading_date=trading_date, cadence=cadence)
    source = Path(source_bundle_path).resolve()
    directory = Path(artifacts_root) / "production_state/live" / trading_date / CADENCE_DIR[cadence]
    # These references travel with the canonical state tree, not runner-local paths.
    published = copy.deepcopy(bundle)
    archive_references = []
    for item in published["sources"]:
        receipt_body = Path(item["receipt_path"]).read_bytes()
        receipt = read_metadata(receipt_body)
        for key, body in (("response", Path(receipt["raw_path"]).read_bytes()), ("receipt.json", receipt_body)):
            target = directory / "public_sources" / (item["dataset_id"] + "." + key)
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                require(target.read_bytes() == body, "PUBLIC_REPORT_IMMUTABLE_CONFLICT")
            else:
                target.write_bytes(body)
        archive_references.append({"dataset_id": item["dataset_id"],
            "raw_reference": "public_sources/" + item["dataset_id"] + ".response",
            "receipt_reference": "public_sources/" + item["dataset_id"] + ".receipt.json",
            "raw_sha256": item["raw_sha256"], "receipt_sha256": item["receipt_sha256"]})
    summary = {"artifact": "RATE_PUBLIC_OFFICIAL_REPORT_CONSUMPTION_EVIDENCE_V1", "validation_status": "PASS", **gates,
        "source_bundle_content_sha256": bundle["content_sha256"], "source_bundle_path_at_acquisition": str(source),
        "workflow_run_id": workflow_run_id, "workflow_job_id": workflow_job_id,
        "sources": archive_references,
        "formal_source_bundle_latest_updated": False}
    target = directory / "RATE_PUBLIC_OFFICIAL_REPORT_CONSUMPTION_EVIDENCE.json"
    if target.exists():
        require(read_metadata(target.read_bytes()) == summary, "PUBLIC_REPORT_IMMUTABLE_CONFLICT")
    else:
        atomic_write_json(target, summary)
    result = {**summary, "publish_result": "PASS", "published_report_path": str(target)}
    atomic_write_json(Path(evidence_output), result)
    return result
