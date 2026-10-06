"""Exact MOPS bytes and receipts in the append-only historical data namespace."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

NORMALIZATION_VERSION = "CR-RATE-PHASE2-FUNDAMENTAL-YOY-UNDEFINED-V1"


def retain_response(root, body, metadata):
    from ..full_market_history import digest, put_bytes, put_json
    sha = hashlib.sha256(body).hexdigest()
    raw_path = "materials/mops/" + sha + ".bin"
    receipt = {**metadata, "artifact": "RATE_EXACT_MOPS_RESPONSE",
               "body_sha256": sha, "response_bytes": len(body), "raw_path": raw_path,
               "normalization_version": NORMALIZATION_VERSION, "fallback_used": False,
               "parser_sha256": hashlib.sha256(Path(__file__).with_name("fundamental_history.py").read_bytes()).hexdigest()}
    put_bytes(root, raw_path, body)
    path = "reports/mops/" + digest(receipt) + ".json"
    put_json(root, path, receipt)
    return {"path": path, "sha256": digest(receipt)}


def load_response(root, reference, plan=None):
    from ..full_market_history import digest, encoded, safe_path, validate_authority
    from ..production_live_state import require
    raw_receipt = safe_path(root, reference["path"]).read_bytes()
    receipt = json.loads(raw_receipt)
    require(reference == {"path": "reports/mops/" + digest(receipt) + ".json", "sha256": digest(receipt)}
            and encoded(receipt) == raw_receipt, "MOPS_RAW_RECEIPT_HASH_MISMATCH")
    sha = receipt["body_sha256"]
    require(re.fullmatch(r"[0-9a-f]{64}", sha) and receipt["raw_path"] == "materials/mops/" + sha + ".bin",
            "MOPS_RAW_PATH_INVALID")
    body = safe_path(root, receipt["raw_path"]).read_bytes()
    require(hashlib.sha256(body).hexdigest() == sha and len(body) == receipt["response_bytes"],
            "MOPS_RAW_BODY_HASH_MISMATCH")
    require(receipt["artifact"] == "RATE_EXACT_MOPS_RESPONSE" and receipt["source_owner"] == "MOPS Official"
            and receipt["normalization_version"] == NORMALIZATION_VERSION and receipt["fallback_used"] is False,
            "MOPS_RAW_OWNER_BINDING_INVALID")
    from .fundamental_history import MOPS_EPS_ENDPOINT, MOPS_REVENUE_ARCHIVE
    market, period, domain = receipt["market"], receipt["requested_period"], receipt["domain"]
    require(market in ("TWSE", "TPEX") and domain in ("revenue", "eps"), "MOPS_RAW_OWNER_BINDING_INVALID")
    if domain == "revenue":
        require(re.fullmatch(r"\d{4}-\d{2}", period), "MOPS_RAW_OWNER_BINDING_INVALID")
        year, month = (int(x) for x in period.split("-"))
        require(1 <= month <= 12, "MOPS_RAW_OWNER_BINDING_INVALID")
        endpoint = MOPS_REVENUE_ARCHIVE.format(market="sii" if market == "TWSE" else "otc", roc_year=year-1911, month=month)
    else:
        require(re.fullmatch(r"\d{4}Q[1-4]", period), "MOPS_RAW_OWNER_BINDING_INVALID")
        endpoint = MOPS_EPS_ENDPOINT
    require(receipt["endpoint"] == endpoint, "MOPS_RAW_OWNER_BINDING_INVALID")
    if plan is not None:
        require(receipt["plan_id"] == plan["plan_id"] and receipt["parser_sha256"] == plan["owner_hashes"]["src/sources/fundamental_history.py"],
                "MOPS_RAW_PLAN_BINDING_INVALID")
        validate_authority(receipt["acquisition_runtime_authority"])
    return receipt, body


def import_responses(root, plan, input_root, *, write=True):
    from ..full_market_history import digest, put_bytes, put_json
    pending = []
    for path in sorted(Path(input_root).glob("*/reports/mops/*.json")):
        shard_root = path.parents[2]
        receipt = json.loads(path.read_bytes())
        reference = {"path": str(path.relative_to(shard_root)).replace("\\", "/"), "sha256": digest(receipt)}
        receipt, body = load_response(shard_root, reference, plan)
        pending.append((reference, receipt, body))
    failures = []
    for path in sorted(Path(input_root).glob("*/reports/fundamental_rows/*.json")):
        report = json.loads(path.read_bytes())
        from ..full_market_history import encoded
        from ..production_live_state import require
        require(path.name == digest(report) + ".json" and path.read_bytes() == encoded(report)
                and report["plan_id"] == plan["plan_id"] and report["fallback_used"] is False,
                "FUNDAMENTAL_ROW_FAILURE_BINDING_INVALID")
        for failure in report["failures"]:
            receipt, _ = load_response(path.parents[2], failure["raw_response_reference"], plan)
            require(receipt["body_sha256"] == failure["content_hash"] and receipt["market"] == failure["market"]
                    and receipt["requested_period"] == failure["requested_period"] and failure["scope"] == "ROW",
                    "FUNDAMENTAL_ROW_FAILURE_BINDING_INVALID")
        failures.append(("reports/fundamental_rows/" + path.name, report))
    if write:
        for reference, receipt, body in pending:
            put_bytes(root, receipt["raw_path"], body)
            put_json(root, reference["path"], receipt)
        for path, report in failures:
            put_json(root, path, report)
    return pending


def verify_record(root, row, plan, domain):
    from ..production_live_state import require
    from .fundamental_history import (_warmup_revenue_rows, _decode_response, _table_records,
        _finite_official_number, discover_eps_identity, extract_disclosure_date)
    receipt, body = load_response(root, row["raw_response_reference"], plan)
    period = row["revenue_period"] if domain == "revenue" else f'{row["fiscal_year"]}Q{row["quarter"]}'
    require(receipt["domain"] == domain and receipt["market"] == row["market"] and receipt["requested_period"] == period
            and receipt["body_sha256"] == row["content_hash"] and receipt["endpoint"] == row["endpoint"]
            and receipt["final_url"] == receipt["endpoint"] and receipt["http_status"] == 200
            and receipt["body_classification"] == "HTML" and len(body) > 0
            and receipt["retrieval_timestamp"] == row["retrieval_timestamp"], "MOPS_RAW_RECORD_BINDING_INVALID")
    length = receipt.get("content_length")
    require(length is None or str(length).isdigit() and int(length) == len(body), "MOPS_RAW_RECORD_BINDING_INVALID")
    html = _decode_response(body)
    if domain == "revenue":
        rows, _ = _warmup_revenue_rows(html, row["market"], period, {**receipt, "raw_response_reference": row["raw_response_reference"]})
        matches = [r for r in rows if r["symbol"] == row["symbol"]]
        require(len(matches) == 1 and matches[0] == row, "MOPS_RAW_RECORD_REPLAY_MISMATCH")
    else:
        identity = discover_eps_identity(html)
        records, _ = _table_records(html, {"symbol": ("\u516c\u53f8\u4ee3\u865f",), "eps": ("\u57fa\u672c\u6bcf\u80a1\u76c8\u9918",)})
        matches = [r for r in records if r["symbol"] == row["symbol"]]
        require(identity["year"] == row["fiscal_year"] and identity["quarter"] == row["quarter"]
                and len(matches) == 1 and _finite_official_number(matches[0]["eps"]) == row["single_quarter_eps"]
                and extract_disclosure_date(html) == row["official_disclosure_date"], "MOPS_RAW_RECORD_REPLAY_MISMATCH")


def retain_failures(root, failures, context):
    if failures:
        from ..full_market_history import digest, put_json
        report = {**context, "artifact": "RATE_FUNDAMENTAL_ROW_FAILURES", "failures": failures, "fallback_used": False}
        put_json(root, "reports/fundamental_rows/" + digest(report) + ".json", report)
