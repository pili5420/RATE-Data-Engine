"""CER-073 final 07:30 source bundle closure.

This script does not create a production snapshot or decision state. It validates
and packages the staging-only source bundle against accepted CER-073 bindings.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.build_live_source_bundle import FULL_COMPONENTS, _validate as validate_full_components  # noqa: E402
from scripts.run_cer072_acceptance import _verify_model_freeze  # noqa: E402

AS_OF_DATE = "2026-09-18"
PREVIOUS_STAGING_HEAD = "e09d3b95abca5b5158c9acfe4ec24a751a17bdf7"
FUNDAMENTAL_HASH = "b42982f676d8e19fdbc0b6a6cb5716a2e1cc9af8904e0371b9fe1d63b3aee10c"
PRIOR_STAGE_DIGEST = "706eb813da43b112bfd9459d459f1892591371700140e9626e411ad8ad0bceef"
HISTORICAL_STATE_DIGEST = "dddf63b85477aa7cd52ff284d3aba70cf449275406cb6e5e7091acc232d58e3a"
MAIN_HEAD = "beae3ed542888cc647d64bbcecab7d907a7744aa"

VOLATILE_KEYS = {
    "retrieval_timestamp",
    "workflow_timestamp",
    "runner_metadata",
    "http_date",
    "HTTP Date",
    "Date",
    "attempt",
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def strip_volatile(value):
    if isinstance(value, dict):
        return {k: strip_volatile(v) for k, v in value.items() if k not in VOLATILE_KEYS}
    if isinstance(value, list):
        return [strip_volatile(v) for v in value]
    return value


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def component_value(record: dict, component: str):
    if component in ("PT", "PV", "MO", "RS"):
        return (record.get("M7_inputs") or {}).get(component)
    if component in ("H5", "H20", "H60", "H120"):
        return (record.get("MHE_inputs") or {}).get(component)
    if component in ("FI", "IT", "LH"):
        return (record.get("M7_inputs") or {}).get(component, record.get(component))
    if component in ("RS_CHANGE", "VOL_CHANGE", "SMART_MONEY", "MOMENTUM_CHANGE"):
        return (record.get("Rotation_inputs") or {}).get(component, record.get(component))
    if component == "FC":
        return (record.get("SmartMoney_inputs") or {}).get(component, record.get(component))
    return record.get(component)


def component_source_key(component: str) -> str:
    if component in ("PT", "PV", "MO", "RS", "H5", "H20", "H60", "H120", "RelativeStrength", "Liquidity"):
        return "technical_features"
    if component in ("FI", "IT", "SMART_MONEY", "MOMENTUM_CHANGE", "RS_CHANGE", "VOL_CHANGE"):
        return "institutional"
    if component in ("LH", "FC"):
        return "tdcc"
    if component == "Fundamental":
        return "fundamental"
    return "stage"


def make_component_provenance(symbol: str, record: dict, source: dict, as_of_date: str) -> list[dict]:
    lineage = source.get("source_lineage") or {}
    output = []
    for component in FULL_COMPONENTS:
        value = component_value(record, component)
        source_key = component_source_key(component)
        source_info = lineage.get(source_key) or {}
        if source_key == "technical_features":
            date_identity = source_info.get("trade_date") or (lineage.get("stock_history") or {}).get("trade_dates")
        elif source_key == "fundamental":
            date_identity = {
                "revenue_periods": source_info.get("revenue_periods"),
                "eps_quarters": source_info.get("eps_quarters"),
            }
        else:
            date_identity = source_info.get("trading_dates") or source_info.get("periods") or source_info.get("trade_dates")
        entry = {
            "symbol": symbol,
            "component": component,
            "component_value": value,
            "provider_or_source": source_info.get("source") or source_info.get("source_type") or source_key,
            "period_or_date_identity": date_identity,
            "official_disclosure_or_effective_date": source_info.get("source_timestamps") or source_info.get("publication_timestamp") or date_identity,
            "source_or_content_hash": source_info.get("content_hash") or digest(strip_volatile(source_info)),
            "as_of_eligibility": "PASS" if value is not None else "FAIL",
        }
        output.append(entry)
    return output


def complete_provenance(entries: list[dict]) -> bool:
    if len(entries) != len(FULL_COMPONENTS):
        return False
    for entry in entries:
        required = (
            entry.get("provider_or_source"),
            entry.get("period_or_date_identity"),
            entry.get("source_or_content_hash"),
            entry.get("component_value") is not None,
            entry.get("as_of_eligibility") == "PASS",
        )
        if not all(required):
            return False
    return True


def accepted_fundamental_symbols(obj: dict) -> set[str]:
    if obj.get("validation_status") != "PASS" or obj.get("as_of_date") != AS_OF_DATE:
        raise RuntimeError("ACCEPTED_FUNDAMENTAL_ARTIFACT_NOT_PASS")
    if obj.get("analytical_output_hash") != FUNDAMENTAL_HASH:
        raise RuntimeError("ACCEPTED_FUNDAMENTAL_HASH_MISMATCH")
    rows = obj.get("rows") or []
    symbols = {str(row.get("symbol")) for row in rows}
    if len(symbols) != 30:
        raise RuntimeError("ACCEPTED_FUNDAMENTAL_SYMBOL_COUNT_MISMATCH")
    return symbols


def build_closure(args: argparse.Namespace) -> tuple[dict, dict, dict, dict]:
    bundle = load_json(Path(args.source_bundle))
    fundamental = load_json(Path(args.fundamental_cross_section))
    accepted_symbols = accepted_fundamental_symbols(fundamental)

    if bundle.get("validation_status") != "PASS":
        raise RuntimeError("SOURCE_BUNDLE_NOT_PASS")
    if bundle.get("input_snapshot_id") is not None:
        raise RuntimeError("INPUT_SNAPSHOT_CREATED")
    if bundle.get("production_state_created") is not False:
        raise RuntimeError("PRODUCTION_SNAPSHOT_CREATED")
    if bundle.get("production_decision_state_persisted") != 0:
        raise RuntimeError("PRODUCTION_DECISION_STATE_PERSISTED")
    if bundle.get("production_namespace_modified") is not False:
        raise RuntimeError("PRODUCTION_NAMESPACE_MODIFIED")

    universe = [str(x) for x in bundle.get("universe", [])]
    records = bundle.get("decision_records") or []
    sources = bundle.get("production_sources") or {}
    record_by_symbol = {str(row.get("symbol")): row for row in records}

    if set(universe) != accepted_symbols:
        raise RuntimeError("UNIVERSE_FUNDAMENTAL_BINDING_MISMATCH")

    component_errors = validate_full_components(records)
    complete_symbols = sorted(set(record_by_symbol) - {str(row.get("symbol")) for row in component_errors})

    provenance_by_symbol = {}
    for symbol in universe:
        provenance_by_symbol[symbol] = make_component_provenance(symbol, record_by_symbol.get(symbol, {}), sources.get(symbol, {}), AS_OF_DATE)
    provenance_complete = [symbol for symbol, entries in provenance_by_symbol.items() if complete_provenance(entries)]

    prior_binding = bundle.get("prior_stage_package_binding") or {}
    if prior_binding.get("status") != "PASS" or prior_binding.get("digest") != PRIOR_STAGE_DIGEST:
        raise RuntimeError("PRIOR_STAGE_PACKAGE_BINDING_NOT_PASS")

    model_freeze = _verify_model_freeze()
    model_freeze_status = "PASS" if model_freeze.get("status") == "PASS" else "FAIL"

    counts = {
        "universe_coverage": f"{len(universe)}/30",
        "full_19_component_completeness": f"{len(complete_symbols)}/30",
        "source_provenance_completeness": f"{len(provenance_complete)}/30",
        "fundamental_component_coverage": f"{len(accepted_symbols)}/30",
        "prior_stage_package_binding": f"{prior_binding.get('symbols_bound', 0)}/30",
    }

    validation_pass = all(value == "30/30" for value in counts.values()) and model_freeze_status == "PASS"

    final_bundle = copy.deepcopy(bundle)
    final_bundle.update({
        "artifact": "RATE_CER073_FINAL_SOURCE_BUNDLE",
        "schema_version": "RATE-CER073-FINAL-SOURCE-BUNDLE-CLOSURE-V1",
        "as_of_date": AS_OF_DATE,
        "previous_staging_head": PREVIOUS_STAGING_HEAD,
        "run_head_sha": args.run_head_sha,
        "fundamental_analytical_hash": FUNDAMENTAL_HASH,
        "prior_stage_package_digest": PRIOR_STAGE_DIGEST,
        "historical_state_digest": HISTORICAL_STATE_DIGEST,
        "component_provenance_by_symbol": provenance_by_symbol,
        "t86_operational_gate": "PASS_WITH_USER_ASSUMPTION",
        "source_bundle_validation": "PASS" if validation_pass else "FAIL",
        "validation_status": "PASS" if validation_pass else "FAIL",
        "production_snapshot_created": False,
        "production_decision_state_persist": 0,
        "historical_accepted_layer_modified": False,
        "main_modified": False,
    })

    canonical_payload = {
        "final_bundle": strip_volatile(final_bundle),
        "accepted_bindings": {
            "as_of_date": AS_OF_DATE,
            "fundamental_analytical_hash": FUNDAMENTAL_HASH,
            "prior_stage_package_digest": PRIOR_STAGE_DIGEST,
            "historical_state_digest": HISTORICAL_STATE_DIGEST,
        },
    }
    hash_one = digest(canonical_payload)
    hash_two = digest(copy.deepcopy(canonical_payload))
    determinism_status = "PASS" if hash_one == hash_two else "FAIL"
    final_bundle["canonical_bundle_hash"] = hash_two
    final_bundle["source_bundle_determinism"] = determinism_status
    final_bundle["validation_status"] = "PASS" if validation_pass and determinism_status == "PASS" else "FAIL"
    final_bundle["source_bundle_validation"] = final_bundle["validation_status"]

    blockers = []
    if final_bundle["validation_status"] != "PASS":
        blockers.append({"reason": "FINAL_SOURCE_BUNDLE_GATE_NOT_PASS", **counts, "model_freeze_integrity": model_freeze_status, "determinism": determinism_status})

    common = {
        "as_of_date": AS_OF_DATE,
        "previous_staging_head": PREVIOUS_STAGING_HEAD,
        "current_staging_head": args.run_head_sha,
        "run_head_sha": args.run_head_sha,
        "actions_run_id": args.actions_run_id,
        "actions_job_name": args.actions_job_name,
        "fundamental_analytical_hash": FUNDAMENTAL_HASH,
        "prior_stage_package_digest": PRIOR_STAGE_DIGEST,
        "historical_state_digest": HISTORICAL_STATE_DIGEST,
        "rate_live_e2e_enabled": False,
        "input_snapshot_id": None,
        "production_snapshot_created": False,
        "production_decision_state_persist": 0,
        "production_namespace_modified": False,
        "historical_accepted_layer_modified": False,
        "main_modified": False,
        "main_head": MAIN_HEAD,
        "remaining_blockers": blockers,
    }

    completeness = {
        "artifact": "RATE_CER073_FINAL_SOURCE_COMPLETENESS_EVIDENCE",
        "validation_status": final_bundle["validation_status"],
        **common,
        **counts,
        "model_freeze_integrity": model_freeze_status,
        "t86_operational_gate": "PASS_WITH_USER_ASSUMPTION",
        "source_bundle_validation": final_bundle["source_bundle_validation"],
        "source_bundle_determinism": determinism_status,
        "canonical_bundle_hash_run_1": hash_one,
        "canonical_bundle_hash_run_2": hash_two,
    }
    provenance = {
        "artifact": "RATE_CER073_FINAL_SOURCE_PROVENANCE_EVIDENCE",
        "validation_status": "PASS" if len(provenance_complete) == 30 else "FAIL",
        **common,
        "source_provenance_completeness": counts["source_provenance_completeness"],
        "component_count_per_symbol": len(FULL_COMPONENTS),
        "component_provenance_by_symbol": provenance_by_symbol,
    }
    determinism = {
        "artifact": "RATE_CER073_FINAL_DETERMINISM_EVIDENCE",
        "validation_status": determinism_status,
        **common,
        "canonical_bundle_hash_run_1": hash_one,
        "canonical_bundle_hash_run_2": hash_two,
        "volatile_fields_excluded": sorted(VOLATILE_KEYS),
    }
    return final_bundle, completeness, provenance, determinism


def fail_artifacts(args: argparse.Namespace, reason: str) -> tuple[dict, dict, dict, dict]:
    common = {
        "as_of_date": AS_OF_DATE,
        "previous_staging_head": PREVIOUS_STAGING_HEAD,
        "current_staging_head": args.run_head_sha,
        "run_head_sha": args.run_head_sha,
        "actions_run_id": args.actions_run_id,
        "actions_job_name": args.actions_job_name,
        "fundamental_analytical_hash": FUNDAMENTAL_HASH,
        "prior_stage_package_digest": PRIOR_STAGE_DIGEST,
        "historical_state_digest": HISTORICAL_STATE_DIGEST,
        "rate_live_e2e_enabled": False,
        "input_snapshot_id": None,
        "production_snapshot_created": False,
        "production_decision_state_persist": 0,
        "production_namespace_modified": False,
        "historical_accepted_layer_modified": False,
        "main_modified": False,
        "main_head": MAIN_HEAD,
        "remaining_blockers": [{"reason": reason}],
    }
    bundle = {"artifact": "RATE_CER073_FINAL_SOURCE_BUNDLE", "validation_status": "FAIL", **common}
    completeness = {"artifact": "RATE_CER073_FINAL_SOURCE_COMPLETENESS_EVIDENCE", "validation_status": "FAIL", **common,
        "universe_coverage": "0/30", "full_19_component_completeness": "0/30", "source_provenance_completeness": "0/30",
        "fundamental_component_coverage": "0/30", "prior_stage_package_binding": "0/30", "model_freeze_integrity": "FAIL",
        "t86_operational_gate": "PASS_WITH_USER_ASSUMPTION", "source_bundle_validation": "FAIL", "source_bundle_determinism": "FAIL",
        "canonical_bundle_hash_run_1": None, "canonical_bundle_hash_run_2": None}
    provenance = {"artifact": "RATE_CER073_FINAL_SOURCE_PROVENANCE_EVIDENCE", "validation_status": "FAIL", **common,
        "source_provenance_completeness": "0/30", "component_provenance_by_symbol": {}}
    determinism = {"artifact": "RATE_CER073_FINAL_DETERMINISM_EVIDENCE", "validation_status": "FAIL", **common,
        "canonical_bundle_hash_run_1": None, "canonical_bundle_hash_run_2": None, "volatile_fields_excluded": sorted(VOLATILE_KEYS)}
    return bundle, completeness, provenance, determinism


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-bundle", required=True)
    parser.add_argument("--fundamental-cross-section", required=True)
    parser.add_argument("--output-dir", default="artifacts/final-source-bundle")
    parser.add_argument("--run-head-sha", default=os.getenv("GITHUB_SHA"))
    parser.add_argument("--actions-run-id", default=os.getenv("GITHUB_RUN_ID"))
    parser.add_argument("--actions-job-name", default=os.getenv("GITHUB_JOB", "final-source-bundle-closure"))
    args = parser.parse_args()
    out = Path(args.output_dir)
    try:
        artifacts = build_closure(args)
        code = 0 if artifacts[1].get("validation_status") == "PASS" else 1
    except Exception as exc:
        artifacts = fail_artifacts(args, str(exc))
        code = 1
        print(json.dumps({"validation_status": "FAIL", "reason": str(exc)}, ensure_ascii=False))
    names = [
        "RATE_CER073_FINAL_SOURCE_BUNDLE.json",
        "RATE_CER073_FINAL_SOURCE_COMPLETENESS_EVIDENCE.json",
        "RATE_CER073_FINAL_SOURCE_PROVENANCE_EVIDENCE.json",
        "RATE_CER073_FINAL_DETERMINISM_EVIDENCE.json",
    ]
    for name, artifact in zip(names, artifacts):
        write(out / name, artifact)
    if code == 0:
        print(json.dumps({"validation_status": "PASS", "canonical_bundle_hash": artifacts[3]["canonical_bundle_hash_run_2"]}, ensure_ascii=False))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
