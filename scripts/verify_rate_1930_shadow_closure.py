"""Real official 19:30 pipeline in a disposable, non-authoritative publication root."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from scripts.materialize_production_history_store import materialize
from scripts.build_production_source_bundle_from_official import build_bundle, TECHNICAL_REQUIRED
from scripts.publish_production_source_bundle_latest import publish_latest, build_delivery_targets, validate_delivery_targets, DELIVERY_TARGET_KINDS
from src.sources.tpex_date_binding import load_material
from scripts.bootstrap_tpex_history import TPEx_SYMBOLS

ROOT = Path("artifacts/1930_shadow")
DATE = "2026-10-02"
CONTRACT = Path("config/RATE_PRODUCTION_UNIVERSE_CONTRACT_V1.json")


def protected_fingerprint():
    files = subprocess.check_output(["git", "ls-files", "-z"]).decode().split("\0")
    files += [str(p) for folder in ("data", "artifacts") for p in Path(folder).rglob("*")
              if p.is_file() and ROOT not in p.parents]
    return {str(Path(name)): hashlib.sha256(Path(name).read_bytes()).hexdigest()
            for name in files if name and Path(name).is_file()}


def main():
    if os.getenv("GITHUB_REF") != "refs/heads/fix/rate-1930-shadow-closure":
        raise RuntimeError("SHADOW_BRANCH_REQUIRED")
    if os.getenv("EXECUTION_AUTHORITY") != "PR_SHADOW":
        raise RuntimeError("SHADOW_AUTHORITY_REQUIRED")
    if ROOT.exists():
        raise RuntimeError("CLEAN_SHADOW_ROOT_REQUIRED")
    before = protected_fingerprint()
    ROOT.mkdir(parents=True)
    history_root = ROOT / "history"
    os.environ["RATE_OFFICIAL_HISTORY_STORE_ROOT"] = str(history_root)
    os.environ["RATE_OFFICIAL_HISTORY_CACHE_ROOT"] = str(ROOT / "history_cache")
    report = {"artifact": "RATE_1930_PRODUCTION_SHADOW_E2E_CLOSURE",
              "run_id": os.getenv("GITHUB_RUN_ID"), "commit_sha": os.getenv("GITHUB_SHA"),
              "github_ref": os.getenv("GITHUB_REF"), "execution_authority": "PR_SHADOW",
              "trading_date": DATE, "cadence": "19:30",
              "authoritative_main_commit": False, "validation_status": "BLOCKED"}
    try:
        # Approved historical benchmark seed, never a current-day market substitute.
        seed = Path("data/staging/step5a_history/benchmark/TPEX.json")
        (history_root / "benchmark").mkdir(parents=True)
        shutil.copyfile(seed, history_root / "benchmark/TPEX.json")
        report["approved_tpex_benchmark_seed_sha256"] = hashlib.sha256(seed.read_bytes()).hexdigest()
        history = materialize(trading_date=DATE, universe_contract=CONTRACT,
                              history_root=history_root, evidence_output=ROOT / "history_evidence.json",
                              max_months=12, minimum_sessions=180, max_runtime_seconds=900)
        report["history"] = history
        if history["status"] != "PASS" or history["symbols_materialized"] != 30:
            raise RuntimeError("HISTORY_MATERIALIZATION_NOT_PASS")
        material, path, file_hash = load_material(history_root, DATE, TPEx_SYMBOLS)
        report["date_bound"] = {"validation_status": material["validation_status"], "path": str(path),
                                "historical_material_id": material["historical_material_id"],
                                "historical_material_hash": material["historical_material_hash"],
                                "file_sha256": file_hash, "symbols": material["required_symbols"],
                                "effective_dates": [e["record"]["trade_date"] for e in material["entries"]]}
        acquisition = build_bundle(rate_source_url="", trading_date=DATE, cadence="19:30",
                                   output=ROOT / "bundle.json", evidence_output=ROOT / "acquisition_evidence.json",
                                   universe_contract=CONTRACT, source_registry="config/RATE_PRODUCTION_OFFICIAL_SOURCE_REGISTRY_V1.json",
                                   freshness_matrix_output=ROOT / "freshness_matrix.json",
                                   requirement_matrix_output=ROOT / "requirements.json",
                                   universe_binding_output=ROOT / "universe.json")
        report["source_acquisition"] = acquisition["validation_status"]
        bundle = json.loads((ROOT / "bundle.json").read_text())
        report["coverage"] = acquisition["coverage"]
        report["blocking_reason"] = acquisition.get("blocking_reason")
        report["sources"] = acquisition["sources"]
        report["freshness_matrix"] = acquisition["freshness_matrix"]["validation_status"]
        report["source_status"] = bundle.get("source_status")
        report["freshness_status"] = bundle.get("freshness_status")
        report["bundle_validation_status"] = bundle["validation_status"]
        report["datasets_missing"] = bundle.get("datasets_missing")
        report["blocked_dependencies"] = bundle.get("blocked_dependencies")
        records = bundle.get("decision_records") or []
        report["decision_records"] = len(records)
        report["technical_records"] = sum(all(key in (r.get("technical_features") or {}) for key in TECHNICAL_REQUIRED)
                                          for r in (bundle.get("production_sources") or {}).values())
        if acquisition["validation_status"] != "PASS":
            raise RuntimeError("SOURCE_ACQUISITION_NOT_PASS")
        publication = publish_latest(source_bundle_path=ROOT / "bundle.json", trading_date=DATE,
                                     cadence="19:30", artifacts_root=ROOT / "publication",
                                     workflow_run_id=os.getenv("GITHUB_RUN_ID"), workflow_job_id=os.getenv("GITHUB_JOB"),
                                     evidence_output=ROOT / "publication_evidence.json")
        report["production_bundle"] = publication["publish_result"]
        report["publication"] = publication
        if publication["publish_result"] != "PASS":
            raise RuntimeError("SHADOW_PUBLICATION_NOT_PASS")
        targets = publication["delivery_targets"]
        constructed = build_delivery_targets(
            snapshot_path=Path(publication["immutable_snapshot_path"]),
            immutable_bundle_path=Path(publication["immutable_bundle_path"]),
            manifest_path=Path(publication["thin_work_manifest_path"]),
            latest_path=Path(publication["latest_path"]),
            manifest_latest_path=Path(publication["thin_work_manifest_latest_path"]))
        dry_run = validate_delivery_targets(constructed)
        report["publisher_construction_dry_run"] = dry_run
        report["delivery_target_count"] = len(targets)
        report["duplicate_delivery_targets"] = len(dry_run["duplicate_pairs"])
        report["thin_work_manifest"] = publication["manifest_validation"]["validation_status"]
        report["input_snapshot_id"] = publication["input_snapshot_id"]
        report["production_snapshot_id"] = publication["production_snapshot_id"]
        if (sorted(t["kind"] for t in targets) != sorted(DELIVERY_TARGET_KINDS)
                or constructed != targets
                or len(targets) != 5 or dry_run["validation_status"] != "PASS"
                or report["technical_records"] != 30 or len(records) != 30
                or report["datasets_missing"] != [] or report["blocked_dependencies"] != []
                or any(report[k] != "PASS" for k in ("freshness_matrix", "source_status", "freshness_status", "bundle_validation_status", "thin_work_manifest"))
                or not report["input_snapshot_id"] or not report["production_snapshot_id"]):
            raise RuntimeError("SHADOW_CLOSURE_GATE_NOT_PASS")
        report["validation_status"] = "PASS"
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}:{exc}"
    finally:
        after = protected_fingerprint()
        changes = [name for name in before if after.get(name) != before[name]]
        additions = [name for name in after if name not in before]
        report["protected_material_changes"] = changes + additions
        report["production_state_mutation"] = 0 if not changes and not additions else None
        report["portfolio_mutation"] = report["production_state_mutation"]
        report["ledger_mutation"] = report["production_state_mutation"]
        report["production_latest_mutation"] = report["production_state_mutation"]
        report["fallback_used"] = any(s.get("fallback_used") is True for s in report.get("sources", []))
        if report["fallback_used"]:
            report["validation_status"] = "BLOCKED"
        if changes or additions:
            report["validation_status"] = "BLOCKED"
        (ROOT / "closure_evidence.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(json.dumps({k: v for k, v in report.items() if k not in ("history", "sources", "publication", "coverage")}, indent=2))
    return 0 if report["validation_status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
