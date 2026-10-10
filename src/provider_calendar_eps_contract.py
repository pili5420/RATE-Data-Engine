"""Prospective calendar semantics only; reuses source qualification, never activates EPS."""
from copy import deepcopy
from pathlib import Path

from .eps_duration_facts.model import require
from .eps_duration_facts.raw import sha256
from .finmind_formal_qualification import qualify_material, verify_gap_evidence
from .provider_eps_candidate import _canonical, _json, _time
from .provider_financial_feature_inputs import load_closeout

CONTRACT_PATH = Path(__file__).resolve().parents[1] / "docs/contracts/RATE_PROVIDER_CALENDAR_QUARTER_EPS_V1.json"
CONTRACT_SHA256 = "839764f2f97d6d2886db72de9d2c873330f2cb693035a96dbf7ed1365e7a9ead"


def definition():
    value = _json(CONTRACT_PATH.read_bytes())
    require(sha256(_canonical(value)) == CONTRACT_SHA256, "CALENDAR_CONTRACT_TAMPERED")
    return value


def validate_material(material, validated_at):
    """Verify original bytes using existing gates, then add a distinct semantic identity."""
    contract = definition()
    _time(validated_at)
    synthetic = material.get("material_class") == "SYNTHETIC_ONLY"
    if not synthetic:
        require(all(material["universe"].get(k) == v for k, v in contract["universe_binding"].items()),
                "CALENDAR_UNIVERSE_BINDING_INVALID")
    for row in material["eps"]:
        require(all(row.get(k) is None for k in ("fiscal_year", "fiscal_quarter", "report_period_start", "report_period_end")),
                "CALENDAR_FISCAL_INFERENCE_FORBIDDEN")
        require(all(row.get(k, False) is False for k in ("official_ttm", "official_fiscal_quarter_eps", "official_common_share_basis_eps")),
                "CALENDAR_OFFICIAL_PROMOTION_FORBIDDEN")
        require(all(k in row for k in contract["required_binding"]), "CALENDAR_REQUIRED_BINDING_MISSING")
    checked = deepcopy(material)
    checked["gaps"] = [verify_gap_evidence(g) if g.get("receipt_evidence") else g for g in checked["gaps"]]
    require(synthetic or all(g.get("classification_replay") == "PASS" for g in checked["gaps"]),
            "CALENDAR_GAP_SOURCE_REQUIRED")
    source = qualify_material(checked, validated_at)
    source_core = source["core"]
    companies = deepcopy(source_core["companies"])
    for company in companies:
        company["calendar_contract_status"] = "COMPLETE" if company["eight_consecutive_calendar_quarters"] else "INCOMPLETE"
        for row in company["quarters"]:
            require(contract["period_mapping"].get(row["provider_date"]) == row["analysis_quarter"],
                    "CALENDAR_EXACT_MAPPING_REQUIRED")
            row["calendar_contract_validation"] = {"contract_id": contract["contract_id"],
                "contract_sha256": CONTRACT_SHA256, "metric": contract["metric"],
                "period_semantics": contract["period_semantics"], "status": "PASS",
                "historical_pit_status": "UNPROVEN", "production_eligible": False}
    core = {"artifact_kind": "RATE_PROVIDER_CALENDAR_EPS_SEMANTIC_VERIFICATION_V1",
        "contract": contract, "contract_sha256": CONTRACT_SHA256,
        "material_class": "SYNTHETIC_ONLY" if synthetic else material["material_class"],
        "source_qualification_content_sha256": source["content_sha256"],
        "source_binding": deepcopy(source_core["source_binding"]), "universe": deepcopy(source_core["universe"]),
        "window": source_core["window"], "summary": source_core["summary"], "companies": companies,
        "calendar_semantic_contract_validation": "PASS", "formal_period_identity": "NOT_PROVEN",
        "formal_provider_activation": "NOT_AUTHORIZED", "historical_pit_status": "UNPROVEN",
        "production_eligible": False, "warmup_completeness_policy": "UNCHANGED",
        "formal_warmup_gate": contract["formal_warmup_gate"], "fallback_allowed": False,
        "original_eight_quarter_coverage_credit": 0}
    return {"core": core, "content_sha256": sha256(_canonical(core)), "validated_at": validated_at,
            "source_inventory": source["source_inventory"]}


def replay_closeout(reference, expected_sha256, validated_at):
    return validate_material(load_closeout(reference, expected_sha256), validated_at)
