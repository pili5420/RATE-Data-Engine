"""Offline provider-only EPS candidate; no Production consumer or scoring dependency."""
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import re
from urllib.parse import urlencode

from .eps_duration_facts.model import Rejected, require
from .eps_duration_facts.raw import sha256, verify_receipt

SCHEMA = "RATE_PROVIDER_EPS_CANDIDATE_V1"
KIND = "PROVIDER_EPS_CANDIDATE_ONLY"
ENGINEERING = "ENGINEERING_FIXTURE_NOT_REAL_FINMIND_REPLAY"
REAL = "LOCAL_SAVED_FINMIND_RESPONSE_REPLAY"
API = "https://api.finmindtrade.com/api/v4/data"
SYMBOLS = ("2330", "6488", "1340")
WINDOW = ("2024Q3", "2024Q4", "2025Q1", "2025Q2", "2025Q3", "2025Q4", "2026Q1", "2026Q2")
DESCENDING = tuple(reversed(WINDOW))
BASIC_LABEL = "\u57fa\u672c\u6bcf\u80a1\u76c8\u9918"
POLICY = {"source": "FinMind", "dataset": "TaiwanStockFinancialStatements",
          "metric_basis": "PROVIDER_DEFINED_QUARTERLY_BASIC_EPS",
          "source_acceptance": "ACCEPTED_AS_PROVIDER_DATA", "provider_reply_required": False}
BOUNDARY = {"local_window_complete": True, "local_window_coverage": "24/24",
            "formal_eight_quarter_acceptance": "NOT_PERFORMED", "production_eligible": False,
            "original_eight_quarter_coverage_credit": 0, "historical_cutoff": "2026-10-05",
            "historical_pit_status": "UNPROVEN"}


def _object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "DUPLICATE_JSON_FIELD")
        result[key] = value
    return result


def _json(body):
    try:
        return json.loads(body, parse_float=Decimal, object_pairs_hook=_object)
    except (ValueError, TypeError, UnicodeError) as exc:
        if isinstance(exc, Rejected):
            raise
        raise Rejected("INVALID_JSON") from exc


def _decimal(value):
    require(isinstance(value, (str, int, Decimal)) and not isinstance(value, bool), "INVALID_EPS_NUMERIC")
    try:
        number = Decimal(value)
    except (ValueError, InvalidOperation) as exc:
        raise Rejected("INVALID_EPS_NUMERIC") from exc
    require(number.is_finite(), "NONFINITE_EPS")
    return number


def _time(value):
    try:
        parsed = datetime.fromisoformat(value)
    except (ValueError, TypeError) as exc:
        raise Rejected("INVALID_OBSERVATION_TIME") from exc
    require(parsed.tzinfo is not None, "OBSERVATION_TIMEZONE_REQUIRED")
    return parsed.astimezone(timezone.utc)


def _quarter(value):
    try:
        require(isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value), "INVALID_PROVIDER_DATE")
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise Rejected("INVALID_PROVIDER_DATE") from exc
    return f"{parsed.year}Q{(parsed.month - 1) // 3 + 1}"


def _equal(actual, expected, reason):
    require(type(actual) is type(expected) and actual == expected, reason)


def _policy(value):
    require(isinstance(value, dict), "SOURCE_POLICY_REQUIRED")
    for key, expected in POLICY.items():
        _equal(value.get(key), expected, "SOURCE_POLICY_MISMATCH:" + key)
    _equal(value.get("production_eligible"), False, "PRODUCTION_BOUNDARY_REQUIRED")
    _equal(value.get("original_eight_quarter_coverage_credit"), 0, "FORMAL_CREDIT_FORBIDDEN")
    _equal(value.get("historical_cutoff"), "2026-10-05", "CUTOFF_CHANGED")


def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _reference(value, directory):
    require(isinstance(value, str) and value, "SOURCE_REFERENCE_REQUIRED")
    path = Path(value)
    return path.resolve() if path.is_absolute() else (directory / path).resolve()


def _read(path, inventory):
    try:
        body = path.read_bytes()
    except OSError as exc:
        raise Rejected("SOURCE_FILE_UNAVAILABLE:" + path.name) from exc
    inventory[str(path)] = {"bytes": len(body), "sha256": sha256(body)}
    return body


def _receipt(path, directory, inventory):
    receipt_bytes = _read(path, inventory)
    receipt = _json(receipt_bytes)
    require(isinstance(receipt, dict), "INVALID_RECEIPT")
    query = receipt.get("query")
    require(isinstance(query, dict) and set(query) == {"dataset", "data_id", "start_date", "end_date"}, "REQUEST_PARAMETERS_INVALID")
    require(query["dataset"] == POLICY["dataset"] and query["data_id"] in SYMBOLS, "REQUEST_BINDING_INVALID")
    _quarter(query["start_date"])
    _quarter(query["end_date"])
    require(query["start_date"] <= query["end_date"], "REQUEST_WINDOW_INVALID")
    require(receipt.get("requested_url") == API, "WRONG_ENDPOINT")
    require(receipt.get("status") == "SAMPLE_BODY_ACQUIRED" and receipt.get("raw_capture_status") == "COMPLETE", "RECEIPT_NOT_COMPLETE")
    require(receipt.get("content_encoding") in (None, "", "identity"), "UNEXPECTED_CONTENT_ENCODING")
    target = API + "?" + urlencode({key: query[key] for key in ("dataset", "data_id", "start_date", "end_date")})
    raw_path = _reference(receipt.get("raw_path"), path.parent.parent)
    body = _read(raw_path, inventory)
    normalized = {"endpoint": target, "fallback_used": receipt.get("fallback_used", False),
                  "attempts": [{"transport_integrity": "PASS", "final_url": receipt.get("final_url"),
                                "http_status": receipt.get("http_status"), "response_bytes": receipt.get("bytes"),
                                "content_length": receipt.get("content_length"),
                                "body_sha256": receipt.get("response_body_sha256"),
                                "retrieved_at": receipt.get("received_at")} ]}
    verify_receipt(normalized, body, target)
    observed = _time(receipt.get("received_at"))
    require(_time(receipt.get("started_at")) <= observed <= _time(receipt.get("finished_at")), "RECEIPT_TIME_ORDER_INVALID")
    payload = _json(body)
    require(isinstance(payload, dict) and payload.get("status") == 200 and isinstance(payload.get("data"), list), "FINMIND_SCHEMA_INVALID")
    selected = {}
    keys = {}
    for index, row in enumerate(payload["data"]):
        require(isinstance(row, dict) and {"stock_id", "date", "type", "origin_name", "value"} <= row.keys(), "FINMIND_ROW_SCHEMA_INVALID")
        require(row["stock_id"] == query["data_id"], "RAW_SYMBOL_MISMATCH")
        period = _quarter(row["date"])
        require(query["start_date"] <= row["date"] <= query["end_date"], "RAW_REQUEST_WINDOW_MISMATCH")
        if row["type"] != "EPS" or period not in WINDOW:
            continue
        require(row["origin_name"] == BASIC_LABEL, "PROVIDER_BASIC_LABEL_MISMATCH")
        value = _decimal(row["value"])
        key = (row["stock_id"], period)
        if key in keys:
            raise Rejected("RAW_CONFLICTING_VALUE" if keys[key] != value else "RAW_DUPLICATE_KEY")
        keys[key] = value
        selected[index] = row
    return receipt, raw_path, selected, receipt_bytes


def _identity(companies):
    fields = ("symbol", "provider_date", "analysis_quarter", "provider_value", "json_locator",
              "raw_sha256", "receipt_sha256", "acquired_observed_at", "filing_id", "revision_id", "public_time")
    return sha256(_canonical([{key: row[key] for key in fields} for c in companies for row in c["quarters"]]))


def build_candidate(directory, code_binding):
    """Replay exact local responses; never fetch or substitute official values."""
    require(isinstance(code_binding, dict) and all(isinstance(code_binding.get(k), str) and
            re.fullmatch(r"[0-9a-f]{40}", code_binding[k]) for k in ("base_sha", "head_sha")), "CODE_BINDING_REQUIRED")
    directory = Path(directory).resolve()
    started = datetime.now(timezone.utc).isoformat()
    inventory = {}
    manifest = _json(_read(directory / "merged_manifest.json", inventory))
    inputs = _json(_read(directory / "analysis_input.json", inventory))
    matrix = _json(_read(directory / "quarter_matrix.json", inventory))
    require(isinstance(manifest, dict) and isinstance(inputs, dict) and isinstance(matrix, dict), "INVALID_INPUT_PACKAGE")
    _policy(manifest.get("policy"))
    require(manifest.get("local_analysis_window") == list(WINDOW) and manifest.get("window_role") == "LOCAL_ANALYSIS_WINDOW", "WINDOW_MISMATCH")
    require(inputs.get("metadata") == manifest, "MANIFEST_INPUT_MISMATCH")
    require(matrix.get("window") == list(WINDOW), "MATRIX_WINDOW_MISMATCH")
    rows = inputs.get("records")
    require(isinstance(rows, list), "INPUT_RECORDS_REQUIRED")
    by_key = {}
    for row in rows:
        require(isinstance(row, dict), "INVALID_INPUT_ROW")
        key = (row.get("symbol"), row.get("analysis_quarter"))
        require(key[0] in SYMBOLS and key[1] in WINDOW, "UNEXPECTED_COMPANY_QUARTER")
        require(_quarter(row.get("provider_date")) == key[1], "DATE_QUARTER_MAPPING_MISMATCH")
        value = _decimal(row.get("provider_value"))
        if key in by_key:
            raise Rejected("CONFLICTING_VALUE" if _decimal(by_key[key]["provider_value"]) != value else "DUPLICATE_KEY")
        by_key[key] = row
    require(set(by_key) == {(s, q) for s in SYMBOLS for q in WINDOW}, "MISSING_QUARTERS")
    require(len(rows) == 24, "ROW_COUNT_MISMATCH")
    matrix_rows = matrix.get("cells")
    require(isinstance(matrix_rows, list) and len(matrix_rows) == 24, "MATRIX_CELL_COUNT_MISMATCH")
    matrix_keys = set()
    for cell in matrix_rows:
        require(isinstance(cell, dict), "INVALID_MATRIX_CELL")
        key = (cell.get("symbol"), cell.get("analysis_quarter"))
        require(key not in matrix_keys and key in by_key, "MATRIX_KEY_MISMATCH")
        matrix_keys.add(key)
        require(_decimal(cell.get("eps")) == _decimal(by_key[key]["provider_value"]), "MATRIX_VALUE_MISMATCH")
    require(not manifest.get("conflicts") and not manifest.get("duplicate_keys") and not manifest.get("missing_company_quarters"), "MANIFEST_HAS_UNRESOLVED_INPUT")
    require(manifest.get("merged_analysis_record_count") == 24 and manifest.get("local_available_company_quarters") == 24, "MANIFEST_COVERAGE_MISMATCH")
    cache = {}
    referenced = set()
    companies = []
    observed_times = []
    for symbol in SYMBOLS:
        verified_rows = []
        for period in DESCENDING:
            row = by_key[(symbol, period)]
            _policy(row)
            require(row.get("provider_type") == "EPS" and row.get("provider_origin_name") == BASIC_LABEL, "PROVIDER_ROW_LABEL_MISMATCH")
            require(row.get("provider_basis_label") == "BASIC", "PROVIDER_BASIS_MISMATCH")
            for field in ("filing_id", "revision_id", "public_time"):
                require(field in row and row[field] is None, "UNSUPPORTED_VERSION_CLAIM:" + field)
            require(row.get("same_public_version_status") == "UNPROVEN", "UNSUPPORTED_VERSION_CLAIM")
            require(row.get("q4_raw_or_derived_classification") == ("UNPROVEN" if period.endswith("Q4") else "NOT_Q4_DATE"), "UNSUPPORTED_Q4_CLAIM")
            receipt_path = _reference(row.get("receipt_reference"), directory)
            if receipt_path not in cache:
                cache[receipt_path] = _receipt(receipt_path, directory, inventory)
            receipt, raw_path, raw_rows, receipt_bytes = cache[receipt_path]
            index = row.get("raw_row_index_zero_based")
            require(type(index) is int and index in raw_rows, "RAW_ROW_LOCATOR_INVALID")
            require(row.get("json_locator") == f"$.data[{index}]", "JSON_LOCATOR_MISMATCH")
            raw = raw_rows[index]
            require(raw["stock_id"] == symbol and raw["date"] == row["provider_date"], "RAW_ROW_IDENTITY_MISMATCH")
            require(_reference(row.get("raw_path"), directory) == raw_path, "RAW_REFERENCE_MISMATCH")
            require(row.get("response_sha256") == receipt["response_body_sha256"], "RAW_HASH_BINDING_MISMATCH")
            require(row.get("receipt_sha256") == sha256(receipt_bytes), "RECEIPT_HASH_BINDING_MISMATCH")
            require(row.get("response_bytes") == receipt["bytes"], "RAW_BYTES_BINDING_MISMATCH")
            require(str(raw["value"]) == row["provider_value"] and row.get("eps") == row["provider_value"], "PROVIDER_VALUE_MISMATCH")
            require(row.get("observed_at") == receipt["received_at"], "OBSERVATION_TIME_BINDING_MISMATCH")
            observed_times.append(_time(receipt["received_at"]))
            referenced.add((receipt_path, index))
            verified_rows.append({"symbol": symbol, "provider_date": raw["date"], "analysis_quarter": period,
                "provider_value": row["provider_value"], "provider_type": "EPS", "provider_origin_name": BASIC_LABEL,
                "provider_basis_label": "BASIC", "raw_row_index_zero_based": index, "json_locator": f"$.data[{index}]",
                "receipt_reference": str(receipt_path), "receipt_sha256": sha256(receipt_bytes),
                "raw_reference": str(raw_path), "raw_sha256": receipt["response_body_sha256"],
                "raw_bytes": receipt["bytes"],
                "acquired_observed_at": receipt["received_at"], "acquisition_executed_at": row.get("acquisition_executed_at"),
                "verified_observed_at": datetime.now(timezone.utc).isoformat(),
                "filing_id": None, "revision_id": None, "public_time": None,
                "same_public_version_status": "UNPROVEN", "historical_pit_status": "UNPROVEN",
                "q4_raw_or_derived_classification": row.get("q4_raw_or_derived_classification"),
                "material_origin": row.get("material_origin"),
                "official_numeric_corroboration": row.get("official_numeric_corroboration"),
                **POLICY, "production_eligible": False, "original_eight_quarter_coverage_credit": 0,
                "historical_cutoff": "2026-10-05"})
        companies.append({"symbol": symbol, "quarter_order": "LATEST_TO_OLDEST", "quarters": verified_rows})
    require(referenced == {(path, i) for path, (_, _, raw_rows, _) in cache.items() for i in raw_rows}, "UNREFERENCED_TARGET_RAW_EPS")
    complete_at = max(observed_times)
    require(_time(manifest.get("generated_at")) >= complete_at, "INPUT_COMPLETENESS_TIME_BACKDATED")
    require(_time(started) >= complete_at, "OBSERVATION_AFTER_VERIFICATION_CLOCK")
    validated = datetime.now(timezone.utc).isoformat()
    generated = datetime.now(timezone.utc).isoformat()
    package = {"schema_version": SCHEMA, "artifact_kind": KIND,
        "artifact_id": "rate-finmind-provider-eps-candidate-" + _identity(companies),
        "material_class": ENGINEERING if manifest.get("engineering_fixture") is True else REAL,
        "source_policy": POLICY, **BOUNDARY, "code_binding": code_binding,
        "quarter_order": "LATEST_TO_OLDEST", "window": list(WINDOW),
        "verification_started_at": started, "validated_at": validated, "generated_at": generated,
        "dataset_complete_observed_at": complete_at.isoformat(), "companies": companies,
        "input_integrity": inventory, "candidate_usage": "OFFLINE_CANDIDATE_CONSUMPTION_ONLY"}
    for filename, expected in inventory.items():
        body = Path(filename).read_bytes()
        require(len(body) == expected["bytes"] and sha256(body) == expected["sha256"], "INPUT_CHANGED_DURING_VERIFICATION")
    package["candidate_payload_sha256"] = sha256(_canonical(package))
    consume_candidate(package)
    return package


def consume_candidate(package):
    """Only the independent candidate schema is accepted; returns labelled ordered rows."""
    require(isinstance(package, dict) and package.get("schema_version") == SCHEMA and package.get("artifact_kind") == KIND, "WRONG_CANDIDATE_ARTIFACT")
    require(not {"quarterly_eps", "single_quarter_eps"}.intersection(package), "FORMAL_EPS_ALIAS_FORBIDDEN")
    require(package.get("candidate_payload_sha256") == sha256(_canonical({k: v for k, v in package.items() if k != "candidate_payload_sha256"})), "CANDIDATE_PAYLOAD_TAMPERED")
    for key, value in BOUNDARY.items():
        _equal(package.get(key), value, "CANDIDATE_BOUNDARY_MISMATCH:" + key)
    require(package.get("source_policy") == POLICY, "CANDIDATE_SOURCE_POLICY_MISMATCH")
    require(package.get("window") == list(WINDOW) and package.get("quarter_order") == "LATEST_TO_OLDEST", "CANDIDATE_WINDOW_MISMATCH")
    companies = package.get("companies")
    require(isinstance(companies, list) and [c.get("symbol") for c in companies] == list(SYMBOLS), "CANDIDATE_COMPANIES_MISMATCH")
    result = {}
    for company in companies:
        require(company.get("quarter_order") == "LATEST_TO_OLDEST", "CANDIDATE_QUARTER_ORDER_INVALID")
        rows = company.get("quarters")
        require(isinstance(rows, list) and [r.get("analysis_quarter") for r in rows] == list(DESCENDING), "CANDIDATE_QUARTER_ORDER_INVALID")
        for row in rows:
            require(not {"quarterly_eps", "single_quarter_eps"}.intersection(row), "FORMAL_EPS_ALIAS_FORBIDDEN")
            require(row["symbol"] == company["symbol"] and _quarter(row["provider_date"]) == row["analysis_quarter"], "CANDIDATE_ROW_IDENTITY_INVALID")
            _decimal(row["provider_value"])
            require(all(row.get(field) is None for field in ("filing_id", "revision_id", "public_time")), "UNSUPPORTED_VERSION_CLAIM")
            require(all(field in row for field in ("filing_id", "revision_id", "public_time")), "VERSION_FIELDS_REQUIRED")
            require(row.get("same_public_version_status") == "UNPROVEN" and row.get("historical_pit_status") == "UNPROVEN", "UNSUPPORTED_VERSION_CLAIM")
            require(row.get("q4_raw_or_derived_classification") == ("UNPROVEN" if row["analysis_quarter"].endswith("Q4") else "NOT_Q4_DATE"), "UNSUPPORTED_Q4_CLAIM")
            _policy(row)
        result[company["symbol"]] = [{"analysis_quarter": r["analysis_quarter"], "provider_date": r["provider_date"],
                                      "provider_value": r["provider_value"]} for r in rows]
    require(package.get("artifact_id") == "rate-finmind-provider-eps-candidate-" + _identity(companies), "CANDIDATE_IDENTITY_MISMATCH")
    latest = max(_time(r["acquired_observed_at"]) for c in companies for r in c["quarters"])
    require(_time(package.get("dataset_complete_observed_at")) == latest, "COMPLETENESS_TIME_MISMATCH")
    require(latest <= _time(package.get("verification_started_at")) <= _time(package.get("validated_at")) <= _time(package.get("generated_at")), "CANDIDATE_TIME_ORDER_INVALID")
    require(all(_time(package["verification_started_at"]) <= _time(r["verified_observed_at"]) <= _time(package["validated_at"])
                for c in companies for r in c["quarters"]), "ROW_VERIFICATION_TIME_INVALID")
    return {"artifact_kind": KIND, "quarter_order": "LATEST_TO_OLDEST", "companies": result,
            "production_eligible": False, "original_eight_quarter_coverage_credit": 0}
