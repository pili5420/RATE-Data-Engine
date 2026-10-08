"""Independent labelled provider features; no formal scoring/transport dependency."""
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_EVEN, localcontext
from pathlib import Path

from .eps_duration_facts.model import require
from .eps_duration_facts.raw import sha256
from .provider_eps_candidate import WINDOW, _canonical, _decimal, _quarter, _time, _policy, map_basic_eps_label
from .provider_eps_metadata import read_metadata

CONTRACT_PATH = Path(__file__).resolve().parents[1] / "docs/contracts/RATE_PROVIDER_FINANCIAL_FEATURES_V1.json"
CONTRACT = read_metadata(CONTRACT_PATH.read_bytes())
KIND = "RATE_PROVIDER_FINANCIAL_FEATURE_PACKAGE_V1"
EPS_NAMES = ("finmind_eps_sum_latest4q_unadjusted", "finmind_eps_sum_previous4q_unadjusted", "finmind_eps_delta4q_unadjusted")
REVENUE_NAME = "official_revenue_yoy_mean_3m"


def instant():
    return datetime.now(timezone.utc).isoformat()


def hash_object(value):
    return sha256(_canonical(value))


def within_git_checkout(directory):
    # A protected but empty workspace .git marker is not a repository checkout.
    for parent in (directory, *directory.parents):
        marker = parent / ".git"
        if marker.is_file() or (marker.is_dir() and (marker / "HEAD").is_file()):
            return True
    return False


def validate_contract(contract):
    require(contract == CONTRACT and tuple(contract["window"]) == WINDOW, "FEATURE_CONTRACT_MISMATCH")
    _time(contract["contract_effective_at"])


def exact_sum(values):
    values = [_decimal(value) for value in values]
    low = min([0] + [v.as_tuple().exponent for v in values])
    high = max([0] + [v.adjusted() for v in values])
    with localcontext() as context:
        context.prec = max(50, high - low + len(str(len(values))) + 6)
        return sum(values, Decimal(0))


def revenue_mean(values):
    require(len(values) == 3, "REVENUE_FIXED_THREE_REQUIRED")
    numerator = exact_sum(values)
    with localcontext() as context:
        context.prec = max(50, numerator.adjusted() + 30)
        return format((numerator / Decimal(3)).quantize(Decimal("0.000000000001"), rounding=ROUND_HALF_EVEN), "f")


def index_inputs(inputs):
    stocks = inputs["universe"]["stocks"]
    markets = {r["symbol"]: r["market"] for r in stocks}
    require(len(markets) == len(stocks) and stocks, "FEATURE_UNIVERSE_DUPLICATE_OR_EMPTY")
    require(all(m in {"TWSE", "TPEX"} for m in markets.values()), "FEATURE_MARKET_INVALID")
    eps, revenue = {}, {}
    for row in inputs["eps"]:
        require(markets.get(row["symbol"]) == row["market"], "FEATURE_INPUT_IDENTITY_CONFLICT")
        quarter = row["analysis_quarter"]
        require(quarter in CONTRACT["window"] and _quarter(row["provider_date"]) == quarter, "FEATURE_QUARTER_OUT_OF_WINDOW")
        key = (row["symbol"], quarter)
        require(key not in eps, "FEATURE_EPS_DUPLICATE_OR_CONFLICT")
        _policy(row)
        map_basic_eps_label(row["provider_type"], row["provider_origin_name"])
        require(row["provider_basis_label"] == "BASIC" and row["same_public_version_status"] == "UNPROVEN" and
            row["q4_raw_or_derived_classification"] == ("UNPROVEN" if quarter.endswith("Q4") else "NOT_Q4_DATE"), "FEATURE_BASIS_OR_VERSION_CLAIM")
        index = row["raw_row_index_zero_based"]
        require(type(index) is int and index >= 0 and row["json_locator"] == f"$.data[{index}]", "FEATURE_LOCATOR_INVALID")
        _decimal(row["provider_value"])
        require(all(row.get(k) is None and k in row for k in ("filing_id", "revision_id", "public_time")), "FEATURE_UNKNOWN_VERSION_FABRICATED")
        require(row["historical_pit_status"] == "UNPROVEN", "FEATURE_PIT_CLAIM_FORBIDDEN")
        require(_time(row["acquired_observed_at"]) <= _time(row["verified_observed_at"]), "FEATURE_INPUT_TIME_INVALID")
        eps[key] = row
    for row in inputs["revenue"]:
        require(markets.get(row["symbol"]) == row["market"] and row["period"] in CONTRACT["revenue_months"], "FEATURE_REVENUE_IDENTITY_CONFLICT")
        key = (row["symbol"], row["period"])
        require(key not in revenue, "FEATURE_REVENUE_DUPLICATE_OR_CONFLICT")
        require(row["source"] == CONTRACT["revenue_source"], "FEATURE_REVENUE_SOURCE_CHANGED")
        require(_time(row["observed_at"]) <= _time(row["source_validated_at"]), "FEATURE_REVENUE_TIME_INVALID")
        if row["revenue_yoy_status"] == "VALID_NUMERIC":
            _decimal(row["revenue_yoy"])
        else:
            require(row["revenue_yoy_status"] == "UNDEFINED_ZERO_BASE" and row["revenue_yoy"] is None, "FEATURE_REVENUE_INVALID_NONNUMERIC")
        revenue[key] = row
    gaps = {(r["symbol"], r["analysis_quarter"]) for r in inputs["gaps"]}
    require(len(gaps) == len(inputs["gaps"]), "FEATURE_GAP_DUPLICATE")
    require(all(markets.get(r["symbol"]) == r["market"] and r["classification"] in {
        "NO_PROVIDER_ROWS_FOR_QUARTER", "FINANCIAL_ROWS_PRESENT_NO_TYPE_EPS", "RELATED_FIELD_WITHOUT_APPROVED_MAPPING",
        "EXISTING_MATERIAL_INSUFFICIENT_TO_DETERMINE"} for r in inputs["gaps"]), "FEATURE_GAP_IDENTITY_INVALID")
    expected = {(s, q) for s in markets for q in CONTRACT["window"]} - set(eps)
    require(gaps == expected, "FEATURE_GAP_MANIFEST_MISMATCH")
    return stocks, eps, revenue


def reference(row, domain):
    keys = ("receipt_reference", "receipt_sha256", "raw_reference", "raw_sha256", "raw_bytes", "json_locator",
            "raw_row_index_zero_based", "provider_date", "provider_type", "provider_origin_name",
            "filing_id", "revision_id", "public_time", "same_public_version_status", "q4_raw_or_derived_classification") if domain == "EPS" else (
            "receipt_reference", "receipt_sha256", "raw_reference", "raw_sha256", "row_identity_locator", "official_raw_yoy", "revenue_yoy_status")
    return {"domain": domain, "input_key": row["analysis_quarter"] if domain == "EPS" else row["period"],
        "input_observed_at": row["acquired_observed_at"] if domain == "EPS" else row["observed_at"],
        "input_source_validated_at": row["verified_observed_at"] if domain == "EPS" else row["source_validated_at"],
        **{k: row[k] for k in keys if k in row}}


def feature(symbol, name, eps, revenue, contract):
    spec = contract["features"][name]
    periods = contract[spec["input_window"]]
    domain = "REVENUE" if name == REVENUE_NAME else "EPS"
    index = revenue if domain == "REVENUE" else eps
    required, refs, missing, values = [], [], [], []
    for period in periods:
        row = index.get((symbol, period))
        required.append({"domain": domain, "period": period})
        if row is None:
            missing.append({"period": period, "reason": "MISSING_QUARTER" if domain == "EPS" else "MISSING_REVENUE_OBSERVATION"})
            continue
        refs.append(reference(row, domain))
        if domain == "REVENUE" and row["revenue_yoy_status"] != "VALID_NUMERIC":
            missing.append({"period": period, "reason": row["revenue_yoy_status"]})
            continue
        value = _decimal(row["provider_value"] if domain == "EPS" else row["revenue_yoy"])
        values.append(value.copy_negate() if name == EPS_NAMES[2] and period in contract["previous4"] else value)
    value = None if missing else revenue_mean(values) if domain == "REVENUE" else str(exact_sum(values))
    observed = max((_time(r["input_observed_at"]) for r in refs), default=None)
    validated = max((_time(r["input_source_validated_at"]) for r in refs), default=None)
    return {"feature_name": name, "feature_version": contract["version"], "value": value,
        "status": "NOT_COMPUTABLE" if missing else "COMPUTABLE", "calculation_window": periods,
        "necessary_inputs": required, "source_references": refs, "missing_reasons": missing,
        "input_observed_at_max": observed.isoformat() if observed else None,
        "input_source_validated_at_max": validated.isoformat() if validated else None,
        "source_identity": contract["revenue_source"] if domain == "REVENUE" else contract["eps_source"],
        "value_scale": contract["revenue_scale"] if domain == "REVENUE" else "PROVIDER_REPORTED_EPS_SCALE",
        "share_basis_alignment": "NOT_ADJUSTED", "not_official_ttm": True,
        "feature_calculation_allowed": True, "decision_eligible": False, "production_eligible": False}


def ordered_inputs(inputs):
    inputs = deepcopy(inputs)
    inputs["universe"]["stocks"].sort(key=lambda r: (r["market"] != "TWSE", r["symbol"]))
    inputs["eps"].sort(key=lambda r: (r["symbol"], r["analysis_quarter"]))
    inputs["revenue"].sort(key=lambda r: (r["symbol"], r["period"]))
    inputs["gaps"].sort(key=lambda r: (r["symbol"], r["analysis_quarter"]))
    return inputs


def compute_core(inputs, contract=CONTRACT):
    validate_contract(contract)
    inputs = ordered_inputs(inputs)
    stocks, eps, revenue = index_inputs(inputs)
    companies = []
    for stock in sorted(stocks, key=lambda r: (r["market"] != "TWSE", r["symbol"])):
        features = {name: feature(stock["symbol"], name, eps, revenue, contract) for name in contract["features"]}
        companies.append({**stock, "features": features, "complete_feature_count": sum(f["status"] == "COMPUTABLE" for f in features.values())})
    counts = {name: sum(c["features"][name]["status"] == "COMPUTABLE" for c in companies) for name in contract["features"]}
    by_market = {market: {"companies": sum(c["market"] == market for c in companies),
        "all_four_features": sum(c["market"] == market and c["complete_feature_count"] == 4 for c in companies),
        "feature_counts": {name: sum(c["market"] == market and c["features"][name]["status"] == "COMPUTABLE" for c in companies) for name in counts}}
        for market in ("TWSE", "TPEX")}
    return {"artifact_kind": KIND, "contract": contract, "contract_content_sha256": hash_object(contract),
        "input_content_sha256": hash_object(inputs), "inputs": inputs, "companies": companies,
        "summary": {"companies": len(companies), "valid_eps_positions_retained": len(eps), "gap_positions_retained": len(inputs["gaps"]),
            "feature_counts": counts, "all_three_eps_features": counts[EPS_NAMES[2]],
            "all_four_features": sum(c["complete_feature_count"] == 4 for c in companies),
            "partial_features": sum(0 < c["complete_feature_count"] < 4 for c in companies),
            "no_computable_features": sum(c["complete_feature_count"] == 0 for c in companies), "by_market": by_market},
        "feature_calculation_allowed": True, "decision_eligible": False, "production_eligible": False,
        "original_eight_quarter_coverage_credit": 0, "historical_pit_status": "UNPROVEN"}


def seal(core, *, generated_at=None, validated_at=None, code_binding=None):
    generated_at, validated_at = generated_at or instant(), validated_at or instant()
    generation, validation = _time(generated_at), _time(validated_at)
    require(generation <= validation <= _time(instant()), "FEATURE_EXECUTION_TIME_FABRICATED")
    require(generation >= _time(CONTRACT["contract_effective_at"]), "FEATURE_CONTRACT_NOT_EFFECTIVE")
    times = {}
    for company in core["companies"]:
        times[company["symbol"]] = {}
        for name, row in company["features"].items():
            bounds = [_time(CONTRACT["contract_effective_at"]), generation, validation]
            for key in ("input_observed_at_max", "input_source_validated_at_max"):
                if row[key]:
                    require(_time(row[key]) <= generation, "FEATURE_GENERATED_BEFORE_INPUT")
                    bounds.append(_time(row[key]))
            times[company["symbol"]][name] = {"input_observed_at_max": row["input_observed_at_max"],
                "feature_generated_at": generated_at, "feature_validated_at": validated_at,
                "contract_effective_at": CONTRACT["contract_effective_at"],
                "feature_available_at": max(bounds).isoformat() if row["status"] == "COMPUTABLE" else None}
    package = {"core": core, "content_sha256": hash_object(core), "execution": {"feature_generated_at": generated_at,
        "feature_validated_at": validated_at, "code_binding": code_binding, "per_feature_time": times,
        "new_financial_requests": 0, "formal_score_calls": 0}}
    return {**package, "package_sha256": hash_object(package)}


def validate_package(package, *, as_of=None):
    require(package["package_sha256"] == hash_object({k: v for k, v in package.items() if k != "package_sha256"}), "FEATURE_PACKAGE_TAMPERED")
    core = package["core"]
    require(package["content_sha256"] == hash_object(core), "FEATURE_CONTENT_TAMPERED")
    require(core == compute_core(core["inputs"], core["contract"]), "FEATURE_RECOMPUTATION_MISMATCH")
    execution = package["execution"]
    expected = seal(core, generated_at=execution["feature_generated_at"], validated_at=execution["feature_validated_at"], code_binding=execution["code_binding"])
    require(package == expected, "FEATURE_TIME_OR_ENVELOPE_MISMATCH")
    cutoff = _time(as_of or instant())
    for records in execution["per_feature_time"].values():
        for row in records.values():
            require(row["feature_available_at"] is None or cutoff >= _time(row["feature_available_at"]), "FEATURE_TIME_NOT_REACHED")
    return core["summary"]


def export_package(package, directory):
    directory = Path(directory).resolve()
    repository = Path(__file__).resolve().parents[1]
    require(not directory.exists() and not directory.is_relative_to(repository), "FEATURE_NEW_EXTERNAL_OUTPUT_REQUIRED")
    require(not within_git_checkout(directory), "FEATURE_OUTPUT_IN_GIT_REPOSITORY")
    require(not any(part.casefold() in {"production", "latest", "state", "portfolio", "ledger", "data", "artifacts"} for part in directory.parts), "FEATURE_PROTECTED_OUTPUT_FORBIDDEN")
    source = package["core"]["inputs"]["source_binding"].get("coverage_root")
    require(not source or not directory.is_relative_to(Path(source)), "FEATURE_OUTPUT_WITHIN_SOURCE_FORBIDDEN")
    closeout = package["core"]["inputs"]["source_binding"].get("closeout_manifest_reference")
    require(not closeout or not directory.is_relative_to(Path(closeout).parent), "FEATURE_OUTPUT_WITHIN_CLOSEOUT_FORBIDDEN")
    validate_package(package)
    directory.mkdir(parents=True, exist_ok=False)
    path = directory / "PROVIDER_FINANCIAL_FEATURES_V1.json"
    body = _canonical(package) + b"\n"
    path.write_bytes(body)
    manifest = {"artifact_kind": KIND, "content_sha256": package["content_sha256"], "files": {path.name: {"bytes": len(body), "sha256": sha256(body)}},
        "source_binding": package["core"]["inputs"]["source_binding"], "decision_eligible": False, "production_eligible": False}
    (directory / "FEATURE_MANIFEST.json").write_bytes(_canonical(manifest) + b"\n")
    return manifest


def consume(directory, expected_manifest_sha256, *, as_of=None, source_replayer=None, expected_code_binding=None):
    directory = Path(directory).resolve()
    body = (directory / "FEATURE_MANIFEST.json").read_bytes()
    require(sha256(body) == expected_manifest_sha256, "FEATURE_MANIFEST_TAMPERED")
    manifest = read_metadata(body)
    require(manifest["artifact_kind"] == KIND and manifest["decision_eligible"] is False and manifest["production_eligible"] is False, "FEATURE_MANIFEST_IDENTITY_MISMATCH")
    require(set(manifest["files"]) == {"PROVIDER_FINANCIAL_FEATURES_V1.json"}, "FEATURE_MANIFEST_PATH_INVALID")
    expected = manifest["files"]["PROVIDER_FINANCIAL_FEATURES_V1.json"]
    raw = (directory / "PROVIDER_FINANCIAL_FEATURES_V1.json").read_bytes()
    require(len(raw) == expected["bytes"] and sha256(raw) == expected["sha256"], "FEATURE_ARTIFACT_TAMPERED")
    package = read_metadata(raw)
    require(expected_code_binding is None or package["execution"]["code_binding"] == expected_code_binding, "FEATURE_EXECUTION_CODE_BINDING_MISMATCH")
    require(package["content_sha256"] == manifest["content_sha256"] and package["core"]["inputs"]["source_binding"] == manifest["source_binding"], "FEATURE_MANIFEST_BINDING_MISMATCH")
    result = validate_package(package, as_of=as_of)
    require(source_replayer is not None, "FEATURE_SOURCE_REPLAY_REQUIRED")
    replay = source_replayer(manifest["source_binding"])
    require(ordered_inputs(replay) == package["core"]["inputs"], "FEATURE_SOURCE_INPUT_REPLAY_MISMATCH")
    return {"status": "PASS", "summary": result, "content_sha256": package["content_sha256"], "source_replay": "PASS", "decision_eligible": False, "production_eligible": False}
