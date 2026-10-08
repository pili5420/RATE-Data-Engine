"""Independent shadow composition of verified labelled provider features only."""
from copy import deepcopy
import math
from pathlib import Path
from statistics import median

from .eps_duration_facts.model import require
from .eps_duration_facts.raw import sha256
from .feature_math import pctl
from .provider_eps_candidate import _canonical, _decimal, _time
from .provider_eps_metadata import read_metadata
from .provider_financial_features import (CONTRACT as FEATURE_CONTRACT, EPS_NAMES, REVENUE_NAME,
    hash_object, instant, validate_package, within_git_checkout)

ROOT = Path(__file__).resolve().parents[1]
SPEC = read_metadata((ROOT / "docs/contracts/RATE_PROVIDER_FUNDAMENTAL_SHADOW_V1.json").read_bytes())
KIND = "RATE_PROVIDER_FUNDAMENTAL_SHADOW_PACKAGE_V1"
SCORE = SPEC["score_field"]
NAMES = tuple(c["feature"] for c in SPEC["components"])
FEATURE_NAMES = (*EPS_NAMES, REVENUE_NAME)


def finite_float(value):
    number = float(_decimal(value))
    require(math.isfinite(number), "SHADOW_NONFINITE_FLOAT_CONVERSION")
    return number


def validate_spec(spec):
    require(spec == SPEC and spec["eps_window"] == FEATURE_CONTRACT["window"] and
        spec["revenue_window"] == FEATURE_CONTRACT["revenue_months"], "SHADOW_SPEC_MISMATCH")
    require(sha256((ROOT / spec["percentile"]["path"]).read_bytes().replace(b"\r\n", b"\n")) == spec["percentile"]["sha256"], "SHADOW_PCTL_CODE_TAMPERED")


def population(rows, tag, feature_identity):
    members = [{"symbol": c["symbol"], "market": c["market"]} for c in sorted(rows, key=lambda r: r["symbol"])]
    body = {"role": tag, "members": members, "feature_content_sha256": feature_identity,
        "eps_window": SPEC["eps_window"], "revenue_window": SPEC["revenue_window"]}
    return {**body, "population_id": "provider-shadow-population-" + hash_object(body), "count": len(members)}


def compute_core(feature_package, *, spec=SPEC):
    validate_spec(spec)
    validate_package(feature_package)
    companies = feature_package["core"]["companies"]
    require(len({c["symbol"] for c in companies}) == len(companies), "SHADOW_COMPANY_DUPLICATE")
    complete = lambda c, names: all(c["features"][n]["status"] == "COMPUTABLE" for n in names)
    a = [c for c in companies if complete(c, FEATURE_NAMES)]
    b = [c for c in companies if complete(c, EPS_NAMES)]
    c_pop = [c for c in companies if complete(c, (REVENUE_NAME,))]
    require(len(a) >= spec["minimum_after_filter"], "SHADOW_FILTERED_POPULATION_TOO_SMALL")
    for company in companies:
        for row in company["features"].values():
            if row["status"] == "COMPUTABLE":
                finite_float(row["value"])
    populations = {key: population(rows, key, feature_package["content_sha256"])
        for key, rows in (("A_COMPLETE_INPUT", a), ("B_EIGHT_QUARTER_EPS", b), ("C_REVENUE_3M", c_pop))}
    values = {n: [finite_float(c["features"][n]["value"]) for c in a] for n in NAMES}
    eligible = {r["symbol"] for r in a}
    result = []
    for company in sorted(companies, key=lambda r: r["symbol"]):
        ok = company["symbol"] in eligible
        components = {}
        for component in spec["components"]:
            name, weight = component["feature"], component["weight"]
            raw = company["features"][name]["value"]
            percentile = pctl(finite_float(raw), values[name]) if ok else None
            components[name] = {"raw_feature_value": raw, "raw_decimal_value": raw,
                "percentile": percentile, "weight": weight,
                "weighted_contribution": weight * percentile if ok else None,
                "percentile_population_id": populations["A_COMPLETE_INPUT"]["population_id"] if ok else None}
        score = sum(components[n]["weighted_contribution"] for n in NAMES) if ok else None
        if ok:
            require(math.isfinite(score) and 0 <= score <= 100, "SHADOW_SCORE_OUT_OF_RANGE")
        result.append({"symbol": company["symbol"], "market": company["market"],
            "features": deepcopy(company["features"]), "components": components,
            "shadow_status": "COMPUTABLE" if ok else "NOT_COMPUTABLE",
            "unscored_reasons": [{"feature": n, "status": company["features"][n]["status"],
                "missing_reasons": company["features"][n]["missing_reasons"]} for n in FEATURE_NAMES if company["features"][n]["status"] != "COMPUTABLE"],
            SCORE: score, "shadow_rank": None,
            "shadow_population_id": populations["A_COMPLETE_INPUT"]["population_id"] if ok else None,
            "calculation_version": spec["version"], "decision_eligible": False, "production_eligible": False})
    scores = [r[SCORE] for r in result if r[SCORE] is not None]
    for row in result:
        if row[SCORE] is not None:
            row["shadow_rank"] = 1 + sum(score > row[SCORE] for score in scores)
    sensitivity, sensitivity_summary = [], {}
    for name in NAMES:
        alternative = c_pop if name == REVENUE_NAME else b
        key = "C_REVENUE_3M" if name == REVENUE_NAME else "B_EIGHT_QUARTER_EPS"
        alt_values = [finite_float(r["features"][name]["value"]) for r in alternative]
        rows = []
        for company in sorted(a, key=lambda r: r["symbol"]):
            raw = company["features"][name]["value"]
            pa, alt = pctl(finite_float(raw), values[name]), pctl(finite_float(raw), alt_values)
            rows.append({"symbol": company["symbol"], "market": company["market"], "feature": name,
                "raw_feature_value": raw, "A_percentile": pa, "alternative_percentile": alt,
                "difference_alternative_minus_A": alt - pa, "absolute_difference": abs(alt - pa),
                "A_population_id": populations["A_COMPLETE_INPUT"]["population_id"],
                "alternative_population_id": populations[key]["population_id"]})
        largest = max(r["absolute_difference"] for r in rows)
        sensitivity_summary[name] = {"comparison_count": len(rows), "alternative_count": len(alternative),
            "median_absolute_difference": median(r["absolute_difference"] for r in rows),
            "maximum_absolute_difference": largest,
            "largest_change_companies": [r for r in rows if r["absolute_difference"] == largest]}
        sensitivity.extend(rows)
    by_market = {m: {"data_companies": sum(r["market"] == m for r in result),
        "scored_companies": sum(r["market"] == m and r[SCORE] is not None for r in result)} for m in ("TWSE", "TPEX")}
    return {"artifact_kind": KIND, "spec": spec, "spec_content_sha256": hash_object(spec),
        "feature_content_sha256": feature_package["content_sha256"],
        "source_feature_package_sha256": feature_package["package_sha256"],
        "source_producer_binding": feature_package["execution"]["code_binding"],
        "source_feature_times": feature_package["execution"]["per_feature_time"],
        "source_binding": feature_package["core"]["inputs"]["source_binding"],
        "populations": populations, "companies": result,
        "scored_display_order": [r["symbol"] for r in sorted((r for r in result if r[SCORE] is not None), key=lambda r: (-r[SCORE], r["symbol"]))],
        "sensitivity_matrix": sensitivity, "sensitivity_summary": sensitivity_summary,
        "summary": {"data_population": len(result), "shadow_scoring_population": len(a),
            "not_scored": len(result) - len(a), "eps_sensitivity_population": len(b), "revenue_sensitivity_population": len(c_pop),
            "by_market": by_market}, "shadow_calculation_allowed": True, "decision_eligible": False,
        "production_eligible": False, "original_eight_quarter_coverage_credit": 0, "provider_reply_required": False,
        "historical_pit_status": "UNPROVEN", "sensitivity_not_performance_evidence": True}


def seal(core, source_pin, *, generated_at=None, validated_at=None, code_binding=None):
    generated_at, validated_at = generated_at or instant(), validated_at or instant()
    g, v, e = _time(generated_at), _time(validated_at), _time(SPEC["effective_at"])
    require(e <= g <= v <= _time(instant()), "SHADOW_TIME_INVALID_OR_FABRICATED")
    input_bound = max(_time(time["feature_available_at"]) for company in core["companies"]
        if company[SCORE] is not None for time in core["source_feature_times"][company["symbol"]].values())
    require(input_bound <= g, "SHADOW_GENERATED_BEFORE_FEATURE_AVAILABLE")
    body = {"core": core, "content_sha256": hash_object(core), "execution": {
        "execution_code_binding": code_binding, "source_pin": source_pin,
        "input_available_at_max": input_bound.isoformat(), "shadow_spec_effective_at": SPEC["effective_at"],
        "shadow_generated_at": generated_at, "shadow_validated_at": validated_at,
        "shadow_available_at": max(input_bound, e, g, v).isoformat(), "as_of": max(input_bound, e, g, v).isoformat(),
        "new_financial_requests": 0, "formal_scoring_calls": 0}}
    return {**body, "package_sha256": hash_object(body)}


def validate(package, features, *, as_of=None):
    require(package["package_sha256"] == hash_object({k: v for k, v in package.items() if k != "package_sha256"}), "SHADOW_PACKAGE_TAMPERED")
    require(package["content_sha256"] == hash_object(package["core"]), "SHADOW_CONTENT_TAMPERED")
    require(package["core"] == compute_core(features), "SHADOW_RECOMPUTATION_MISMATCH")
    ex = package["execution"]
    require(package == seal(package["core"], ex["source_pin"], generated_at=ex["shadow_generated_at"],
        validated_at=ex["shadow_validated_at"], code_binding=ex["execution_code_binding"]), "SHADOW_TIME_ENVELOPE_MISMATCH")
    require(_time(as_of or instant()) >= _time(ex["shadow_available_at"]), "SHADOW_TIME_NOT_REACHED")
    return package["core"]["summary"]


def export(package, directory):
    directory = Path(directory).resolve()
    require(not directory.exists() and not within_git_checkout(directory), "SHADOW_NEW_EXTERNAL_OUTPUT_REQUIRED")
    require(not any(p.casefold() in {"production", "latest", "state", "portfolio", "ledger", "data", "artifacts"} for p in directory.parts), "SHADOW_PROTECTED_OUTPUT_FORBIDDEN")
    pin = package["execution"]["source_pin"]
    for key in ("delivery_index", "feature_directory"):
        if pin.get(key):
            source = Path(pin[key]).resolve()
            require(not directory.is_relative_to(source if source.is_dir() else source.parent), "SHADOW_OUTPUT_WITHIN_SOURCE_FORBIDDEN")
    source = package["core"]["source_binding"]
    for key in ("coverage_root", "closeout_manifest_reference"):
        if source.get(key):
            path = Path(source[key]).resolve()
            require(not directory.is_relative_to(path if key == "coverage_root" else path.parent), "SHADOW_OUTPUT_WITHIN_EVIDENCE_FORBIDDEN")
    directory.mkdir(parents=True, exist_ok=False)
    body = _canonical(package) + b"\n"
    (directory / "PROVIDER_FUNDAMENTAL_SHADOW_V1.json").write_bytes(body)
    core = package["core"]
    files = {"PROVIDER_FUNDAMENTAL_SHADOW_V1.json": body,
        "shadow-populations.json": _canonical({"populations": core["populations"], "as_of": package["execution"]["as_of"], "source_pin": pin}) + b"\n",
        "population-sensitivity.json": _canonical({"matrix": core["sensitivity_matrix"], "summary": core["sensitivity_summary"]}) + b"\n",
        "company-status-1978.jsonl": b"".join(_canonical(r) + b"\n" for r in core["companies"])}
    for name, raw in files.items():
        if name != "PROVIDER_FUNDAMENTAL_SHADOW_V1.json":
            (directory / name).write_bytes(raw)
    manifest = {"artifact_kind": KIND, "content_sha256": package["content_sha256"], "files": {
        name: {"bytes": len(raw), "sha256": sha256(raw)} for name, raw in files.items()},
        "source_pin": pin, "decision_eligible": False, "production_eligible": False}
    (directory / "SHADOW_MANIFEST.json").write_bytes(_canonical(manifest) + b"\n")
    return sha256((directory / "SHADOW_MANIFEST.json").read_bytes())


def consume(directory, expected_manifest_sha256, source_loader, *, as_of=None, expected_code_binding=None):
    directory = Path(directory)
    raw = (directory / "SHADOW_MANIFEST.json").read_bytes()
    require(sha256(raw) == expected_manifest_sha256, "SHADOW_MANIFEST_TAMPERED")
    manifest = read_metadata(raw)
    require(manifest["artifact_kind"] == KIND and manifest["decision_eligible"] is False and manifest["production_eligible"] is False, "SHADOW_MANIFEST_IDENTITY_MISMATCH")
    require(set(manifest["files"]) == {"PROVIDER_FUNDAMENTAL_SHADOW_V1.json", "shadow-populations.json", "population-sensitivity.json", "company-status-1978.jsonl"}, "SHADOW_MANIFEST_PATH_INVALID")
    saved = {}
    for name, expected in manifest["files"].items():
        body = (directory / name).read_bytes()
        require(sha256(body) == expected["sha256"] and len(body) == expected["bytes"], "SHADOW_ARTIFACT_TAMPERED")
        saved[name] = body
    package = read_metadata(saved["PROVIDER_FUNDAMENTAL_SHADOW_V1.json"])
    require(package["execution"]["source_pin"] == manifest["source_pin"] and package["content_sha256"] == manifest["content_sha256"], "SHADOW_MANIFEST_BINDING_MISMATCH")
    require(expected_code_binding is None or package["execution"]["execution_code_binding"] == expected_code_binding, "SHADOW_EXECUTION_CODE_MISMATCH")
    features = source_loader(manifest["source_pin"])
    summary = validate(package, features, as_of=as_of)
    core = package["core"]
    require(saved["shadow-populations.json"] == _canonical({"populations": core["populations"], "as_of": package["execution"]["as_of"], "source_pin": manifest["source_pin"]}) + b"\n", "SHADOW_POPULATION_SIDECAR_MISMATCH")
    require(saved["population-sensitivity.json"] == _canonical({"matrix": core["sensitivity_matrix"], "summary": core["sensitivity_summary"]}) + b"\n", "SHADOW_SENSITIVITY_SIDECAR_MISMATCH")
    require(saved["company-status-1978.jsonl"] == b"".join(_canonical(r) + b"\n" for r in core["companies"]), "SHADOW_COMPANY_SIDECAR_MISMATCH")
    return {"status": "PASS", "summary": summary, "content_sha256": package["content_sha256"],
        "source_replay": "PASS", "new_financial_requests": 0, "formal_scoring_calls": 0,
        "decision_eligible": False, "production_eligible": False}
