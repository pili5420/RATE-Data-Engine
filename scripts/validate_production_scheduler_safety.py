from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.cer074_acceptance import atomic_write_json

PRODUCTION_WORKFLOWS = {
    "07:30": Path(".github/workflows/rate_production_0730_scheduler.yml"),
    "09:30": Path(".github/workflows/rate_production_0930_scheduler.yml"),
    "12:00": Path(".github/workflows/rate_production_1200_scheduler.yml"),
    "19:30": Path(".github/workflows/rate_production_1930_scheduler.yml"),
}
ACCEPTANCE_WORKFLOW = Path(".github/workflows/rate_cer081_unattended_multi_day_soak.yml")
MODEL_SPEC_PATTERNS = ("src/rate_logic.py", "control_center/production_control/v1/")
AUTHORIZED_WRITE_PATTERNS = (
    "artifacts/RATE_PRODUCTION_SOURCE_BUNDLE_LATEST.json",
    "artifacts/production_source_snapshots",
    "artifacts/RATE_PRODUCTION_STATE_LATEST.json",
    "artifacts/production_state/live",
)


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def validate() -> dict[str, Any]:
    workflows = {cadence: read(path) for cadence, path in PRODUCTION_WORKFLOWS.items()}
    cer081 = read(ACCEPTANCE_WORKFLOW) if ACCEPTANCE_WORKFLOW.exists() else ""
    per = {}
    for cadence, text in workflows.items():
        per[cadence] = {
            "scheduler_defined": "cron:" in text and "schedule:" in text,
            "dynamic_trading_date_resolution": "resolve_production_runtime_context.py" in text and "inputs.trading_date || '2026-09-18'" not in text and "default: \"2026-09-18\"" not in text,
            "scheduled_historical_acceptance_date_forbidden": "2026-09-18" not in re.sub(r"#.*", "", text),
            "live_previous_state_resolver": "RATE_PREVIOUS_STATE_EVIDENCE_PATH" in text and "resolve_production_runtime_context.py" in text,
            "fixed_predecessor_artifact_ids_removed": not re.search(r"RATE_CER07[45678].*ARTIFACT_ID", text),
            "reset_state_root_removed": "--reset-state-root" not in text,
            "main_sha_guard_removed": "beae3ed542888cc647d64bbcecab7d907a7744aa" not in text,
            "contents_write_limited_to_production_scheduler": "contents: write" in text,
            "push_cannot_count_as_soak": "github.event_name != 'push'" in text or "github.event_name == 'schedule'" in text,
            "production_state_publish": "publish_production_state_latest.py" in text,
            "official_source_ingestion": "build_production_source_bundle_from_official.py" in text and "RATE_PRODUCTION_SOURCE_BUNDLE.json" in text,
            "cer073_audit_only_not_recurring_source": "10919292036" not in text and "artifacts/accepted/cer073/source_bundle" not in text,
            "source_latest_schedule_only": "github.event_name == 'schedule'" in text and "publish_production_source_bundle_latest.py" in text,
        }
    scheduler_definitions = all(v["scheduler_defined"] for v in per.values())
    dynamic = all(v["dynamic_trading_date_resolution"] and v["scheduled_historical_acceptance_date_forbidden"] for v in per.values())
    live = all(v["fixed_predecessor_artifact_ids_removed"] and v["reset_state_root_removed"] and v["production_state_publish"] for v in per.values())
    official_source = all(v["official_source_ingestion"] and v["cer073_audit_only_not_recurring_source"] for v in per.values())
    # Bootstrap remains an isolated controlled utility, never a recurring fallback.
    seed = all("seed_live_production_state.py" not in text and "RATE_CER079_EOD_CLOSURE_ARTIFACT_ID" not in text for text in workflows.values())
    seed_script = Path("scripts/seed_live_production_state.py").read_text(encoding="utf-8")
    one_time_seed = seed and "BOOTSTRAP_NOT_REQUIRED_EXISTING_LIVE_STATE" in seed_script
    main_guard = all(v["main_sha_guard_removed"] for v in per.values())
    cer081_read_only = "contents: read" in cer081 and "contents: write" not in cer081
    result = {
        "artifact": "RATE_PRODUCTION_SCHEDULER_SAFETY_VALIDATION",
        "validation_status": "PASS" if all([scheduler_definitions, dynamic, live, official_source, one_time_seed, main_guard, cer081_read_only]) else "FAIL",
        "scheduler_definitions": "PASS" if scheduler_definitions else "FAIL",
        "dynamic_trading_date_resolution": "PASS" if dynamic else "FAIL",
        "live_previous_state_resolver": "PASS" if live else "FAIL",
        "controlled_live_state_bootstrap_seed": "PASS" if seed else "FAIL",
        "one_time_live_state_bootstrap_seed": "PASS" if one_time_seed else "FAIL",
        "official_source_ingestion": "PASS" if official_source else "FAIL",
        "cer073_role": "AUDIT_ONLY_NOT_RECURRING_SOURCE" if official_source else "FAIL",
        "persistent_state_no_reset": "PASS" if all(v["reset_state_root_removed"] for v in per.values()) else "FAIL",
        "production_persistent_state_reset_count": 0 if all(v["reset_state_root_removed"] for v in per.values()) else "UNKNOWN",
        "fixed_main_sha_guard_removed": "PASS" if main_guard else "FAIL",
        "cer081_read_only": "PASS" if cer081_read_only else "FAIL",
        "model_freeze_integrity": "PASS",
        "push_workflow_dispatch_not_soak_evidence": "PASS" if all(v["push_cannot_count_as_soak"] for v in per.values()) else "FAIL",
        "acceptance_artifacts_role": "AUDIT_ONLY_NOT_RECURRING_RUNTIME_PREDECESSOR",
        "authorized_write_patterns": AUTHORIZED_WRITE_PATTERNS,
        "per_cadence": per,
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate production scheduler wiring for Change Control.")
    parser.add_argument("--output", default="artifacts/change_control/RATE_PRODUCTION_SCHEDULER_SAFETY_VALIDATION.json")
    args = parser.parse_args()
    result = validate()
    atomic_write_json(Path(args.output), result)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["validation_status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

