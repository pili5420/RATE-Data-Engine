"""Build an in-memory RATE intraday activation candidate scaffold.

The scaffold is design material only. It reads the current repository, renders
candidate contents in memory, and immediately runs the static candidate validator.
It never writes candidate files or authorizes activation.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from .intraday_activation_candidate_review import (
    canonical_digest,
    validate_activation_candidate,
)
from .intraday_activation_delta_plan import NEW_RUNTIME_FILES
from .intraday_activation_readiness import (
    ALLOWED_EXISTING_MUTATION_PATHS,
    repo_preimage_hashes,
)

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_MARKETS = ["TWSE", "TPEX"]
CADENCE_MAP = {
    "07:30": "NOT_APPLICABLE",
    "09:30": "REQUIRED",
    "12:00": "REQUIRED",
    "19:30": "NOT_APPLICABLE",
}


class ActivationCandidateScaffoldError(RuntimeError):
    pass


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ActivationCandidateScaffoldError(reason)


def _read(path: str) -> str:
    target = ROOT / path
    require(target.is_file(), "ACTIVATION_SCAFFOLD_SOURCE_MISSING:" + path)
    return target.read_text(encoding="utf-8")


def _json(path: str) -> dict[str, Any]:
    try:
        value = json.loads(_read(path))
    except json.JSONDecodeError as exc:
        raise ActivationCandidateScaffoldError(
            "ACTIVATION_SCAFFOLD_SOURCE_JSON_INVALID:" + path
        ) from exc
    require(isinstance(value, dict), "ACTIVATION_SCAFFOLD_SOURCE_JSON_NOT_OBJECT:" + path)
    return value


def _replace_once(text: str, old: str, new: str, reason: str) -> str:
    require(text.count(old) == 1, reason)
    return text.replace(old, new, 1)


def _render_dependency() -> str:
    value = _json("config/RATE_EXTERNAL_PRODUCTION_DEPENDENCIES.json")
    matches = [
        item for item in value.get("dependencies", [])
        if isinstance(item, dict)
        and item.get("dependency_id") == "EXTERNAL_AUTHORIZED_INTRADAY_FEED_DEPENDENCY"
    ]
    require(len(matches) == 1, "ACTIVATION_SCAFFOLD_DEPENDENCY_RECORD_INVALID")
    item = matches[0]
    item["status"] = "PASS"
    item["engineering_resolution_available"] = True
    item["required_market_coverage"] = list(REQUIRED_MARKETS)
    item["fallback_allowed"] = False
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def _render_source_registry(provider: str, endpoint: str) -> str:
    value = _json("config/SOURCE_REGISTRY.json")
    matches = [
        item for item in value.get("domains", [])
        if isinstance(item, dict) and item.get("domain") == "market_intraday"
    ]
    require(len(matches) == 1, "ACTIVATION_SCAFFOLD_SOURCE_REGISTRY_RECORD_INVALID")
    item = matches[0]
    item["provider"] = provider
    item["access_method"] = "authorized HTTPS provider API"
    item["endpoint_or_path"] = endpoint
    item["authorization_status"] = "PASS"
    item["operational_use_allowed"] = True
    item["freshness_policy"] = "09:30/12:00 exact-cadence authorized provider freshness"
    item.pop("blocking_reason", None)
    value["intraday_status"] = {
        "0930": "AUTHORIZED_PROVIDER_READY",
        "1200": "AUTHORIZED_PROVIDER_READY",
    }
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def _render_official_registry(provider: str, endpoint: str) -> str:
    value = _json("config/RATE_PRODUCTION_OFFICIAL_SOURCE_REGISTRY_V1.json")
    matches = [
        item for item in value.get("datasets", [])
        if isinstance(item, dict) and item.get("dataset_id") == "authorized_market_intraday"
    ]
    require(len(matches) == 1, "ACTIVATION_SCAFFOLD_OFFICIAL_REGISTRY_RECORD_INVALID")
    item = matches[0]
    item["authority"] = provider
    item["required_market_coverage"] = list(REQUIRED_MARKETS)
    item["endpoint"] = endpoint
    item["authorization_status"] = "PASS"
    item["cadence_applicability"] = dict(CADENCE_MAP)
    item["fallback_allowed"] = False
    item.pop("blocked_dependency", None)
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def _render_phase2() -> str:
    text = _read("src/phase2_production.py")
    text = _replace_once(
        text,
        "from .full_market_rotation import (CONTINUITY, EXTERNAL_FEED, UNIVERSE, bind_full_universe,\n",
        "from .full_market_rotation import (CADENCES, CONTINUITY, EXTERNAL_FEED, UNIVERSE, bind_full_universe,\n",
        "ACTIVATION_SCAFFOLD_PHASE2_IMPORT_ANCHOR_INVALID",
    )
    text = _replace_once(
        text,
        '    raise RuntimeError("PUBLIC_OFFICIAL_PARTIAL_RUNTIME_REQUIRED")\n\n\ndef canonical_slots',
        '    return True\n\n\ndef intraday_decision_gate_status(cadence):\n'
        '    require(cadence in CADENCES, "PHASE2_CADENCE_INVALID")\n'
        '    return "PASS" if cadence in {"09:30", "12:00"} else "NOT_APPLICABLE"\n\n\ndef canonical_slots',
        "ACTIVATION_SCAFFOLD_PHASE2_AUTHORITY_ANCHOR_INVALID",
    )
    text = _replace_once(
        text,
        '    decision.update(report_runtime_status="EOD_VALIDATED" if cadence == "19:30" else "CARRIED_VALID",\n'
        '        market_intraday_price_gate="BLOCKED_EXTERNAL", full_intraday_decision_status="BLOCKED_EXTERNAL",\n',
        '    intraday_status = intraday_decision_gate_status(cadence)\n'
        '    decision.update(report_runtime_status="EOD_VALIDATED" if cadence == "19:30" else "CARRIED_VALID",\n'
        '        market_intraday_price_gate=intraday_status, full_intraday_decision_status=intraday_status,\n',
        "ACTIVATION_SCAFFOLD_PHASE2_DECISION_ANCHOR_INVALID",
    )
    text = _replace_once(
        text,
        '            and decision.get("market_intraday_price_gate") == "BLOCKED_EXTERNAL"\n'
        '            and decision.get("full_intraday_decision_status") == "BLOCKED_EXTERNAL", "PHASE2_GOVERNANCE_INVALID")\n',
        '            and decision.get("market_intraday_price_gate") == intraday_decision_gate_status(cadence)\n'
        '            and decision.get("full_intraday_decision_status") == intraday_decision_gate_status(cadence), "PHASE2_GOVERNANCE_INVALID")\n',
        "ACTIVATION_SCAFFOLD_PHASE2_TRANSITION_ANCHOR_INVALID",
    )
    text = _replace_once(
        text,
        '        require(cadence in {"07:30", "19:30"}, "PUBLIC_OFFICIAL_PARTIAL_RUNTIME_REQUIRED")\n',
        '        require(cadence in CADENCES, "PHASE2_CADENCE_INVALID")\n',
        "ACTIVATION_SCAFFOLD_PHASE2_SOURCE_CADENCE_ANCHOR_INVALID",
    )
    return text


def _render_scheduler(cadence: str, secret_name: str) -> str:
    compact = cadence.replace(":", "")
    path = f".github/workflows/rate_production_{compact}_scheduler.yml"
    text = _read(path)
    env_anchor = f'      GITHUB_EVENT_SCHEDULE: ${{{{ github.event.schedule }}}}\n'
    env_add = (
        env_anchor
        + f'      {secret_name}: ${{{{ secrets.{secret_name} }}}}\n'
        + f'      RATE_AUTHORIZED_INTRADAY_FEED_PATH: "artifacts/production_{compact}/RATE_AUTHORIZED_INTRADAY_FEED.json"\n'
        + '      EXECUTION_AUTHORITY: "MAIN_ONLY"\n'
    )
    text = _replace_once(
        text,
        env_anchor,
        env_add,
        "ACTIVATION_SCAFFOLD_SCHEDULER_ENV_ANCHOR_INVALID:" + cadence,
    )
    start = "      - name: Build official production source bundle\n"
    end = "      - name: Archive public report-consumption evidence before state readiness\n"
    require(text.count(start) == 1 and text.count(end) == 1,
            "ACTIVATION_SCAFFOLD_SCHEDULER_RUNTIME_ANCHOR_INVALID:" + cadence)
    before, remainder = text.split(start, 1)
    _, after = remainder.split(end, 1)
    block = f'''      - name: Acquire authorized intraday provider feed
        if: ${{{{ github.event_name != 'push' && env.RATE_PRODUCTION_RUNTIME_MODE == 'RUN' }}}}
        run: >
          python scripts/acquire_intraday_provider_feed.py
          --trading-date "${{{{ env.RATE_PRODUCTION_TRADING_DATE }}}}"
          --cadence "{cadence}"
          --previous-state-id "${{{{ env.RATE_PREVIOUS_STATE_ID }}}}"
          --previous-state-hash "${{{{ env.RATE_PREVIOUS_STATE_HASH }}}}"
          --output "$RATE_AUTHORIZED_INTRADAY_FEED_PATH"
          --raw-evidence-output "artifacts/production_{compact}/RATE_AUTHORIZED_INTRADAY_RAW_EVIDENCE.json"

      - name: Build Phase2 authorized intraday production source bundle
        if: ${{{{ github.event_name != 'push' && env.RATE_PRODUCTION_RUNTIME_MODE == 'RUN' }}}}
        run: >
          python scripts/build_phase2_production_source.py
          --trading-date "${{{{ env.RATE_PRODUCTION_TRADING_DATE }}}}"
          --cadence "{cadence}"
          --output "artifacts/production_{compact}/RATE_PRODUCTION_SOURCE_BUNDLE.json"
          --evidence-output "artifacts/production_{compact}/RATE_PRODUCTION_OFFICIAL_SOURCE_INGESTION_EVIDENCE.json"
          --state-root artifacts/production_state
          --history-root data/production/history

      - name: Execute Phase2 authorized intraday runtime
        if: ${{{{ github.event_name != 'push' && env.RATE_PRODUCTION_RUNTIME_MODE == 'RUN' }}}}
        env:
          GITHUB_SHA: ${{{{ github.sha }}}}
          GITHUB_RUN_ID: ${{{{ github.run_id }}}}
          GITHUB_EVENT_NAME: ${{{{ github.event_name }}}}
        run: >
          python scripts/run_phase2_production.py
          --cadence "{cadence}"
          --source-bundle "artifacts/production_{compact}/RATE_PRODUCTION_SOURCE_BUNDLE.json"
          --canonical-state-root artifacts/production_state
          --state-root "data/production/scheduler_{compact}"
          --output-dir "artifacts/production_{compact}"
          --actions-job-id "$ACTIONS_JOB_ID"
          --expected-previous-state-evidence "$RATE_PREVIOUS_STATE_EVIDENCE_PATH"

'''
    text = before + block + end + after
    text = text.replace("--public-official-partial", "--phase2")
    require("--public-official-partial" not in text,
            "ACTIVATION_SCAFFOLD_SCHEDULER_PUBLIC_PARTIAL_REMAINS:" + cadence)
    return text


def _runtime_source(secret_name: str) -> str:
    return f'''"""Design scaffold for the authorized intraday provider runtime."""
from __future__ import annotations

from http.client import HTTPSConnection
import json

MAX_REQUESTS = 30
MAX_RETRIES = 0
FALLBACK_ALLOWED = False
API_HOST = "api.fugle.tw"
SECRET_NAME = "{secret_name}"


def acquire_intraday_feed(symbols, *, trading_date, cadence, api_key):
    if len(symbols) != MAX_REQUESTS:
        raise RuntimeError("INTRADAY_RUNTIME_EXACT_30_REQUIRED")
    records = []
    raw = []
    for symbol, market in symbols:
        conn = HTTPSConnection(API_HOST, timeout=10)
        path = f"/marketdata/v1.0/stock/intraday/quote/{{symbol}}"
        conn.request("GET", path, headers={{"X-API-KEY": api_key}})
        response = conn.getresponse()
        body = response.read()
        if response.status != 200:
            raise RuntimeError(f"INTRADAY_RUNTIME_HTTP_{{response.status}}")
        payload = json.loads(body)
        raw.append({{"symbol": symbol, "market": market, "payload": payload}})
        records.append({{"symbol": symbol, "market": market, "raw": payload}})
    return {{"records": records, "raw_evidence": raw, "requests": MAX_REQUESTS,
            "automatic_retries": MAX_RETRIES, "fallback_used": FALLBACK_ALLOWED}}
'''


def _acquisition_source(secret_name: str) -> str:
    return f'''"""Design scaffold CLI for authorized intraday provider acquisition."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

from src.authorized_intraday_feed import load_authoritative_universe_binding
from src.intraday_provider_runtime import acquire_intraday_feed

SECRET_NAME = "{secret_name}"
RATE_AUTHORIZED_INTRADAY_FEED_PATH = "RATE_AUTHORIZED_INTRADAY_FEED_PATH"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--trading-date", required=True)
    parser.add_argument("--cadence", required=True, choices=["09:30", "12:00"])
    parser.add_argument("--previous-state-id", required=True)
    parser.add_argument("--previous-state-hash", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--raw-evidence-output", required=True)
    args = parser.parse_args()

    api_key = os.getenv(SECRET_NAME)
    if not api_key:
        raise RuntimeError("INTRADAY_RUNTIME_API_KEY_MISSING")
    universe, _ = load_authoritative_universe_binding()
    result = acquire_intraday_feed(
        list(universe.items()),
        trading_date=args.trading_date,
        cadence=args.cadence,
        api_key=api_key,
    )
    raw_path = Path(args.raw_evidence_output)
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_bytes = json.dumps(result["raw_evidence"], sort_keys=True, separators=(",", ":")).encode()
    raw_path.write_bytes(raw_bytes)

    feed = {{
        "artifact": "RATE_AUTHORIZED_TAIWAN_INTRADAY_FEED_V1",
        "authorization_status": "PASS",
        "validation_status": "PASS",
        "source_status": "PASS",
        "freshness_status": "PASS",
        "blocked_dependencies": [],
        "source_authority": "AUTHORIZED_TAIWAN_INTRADAY_FEED",
        "provider_authority": "CONTROL_CENTER_ACCEPTED_PROVIDER",
        "license_scope": {{"automated_production_use": True, "markets": ["TWSE", "TPEX"]}},
        "trading_date": args.trading_date,
        "cadence": args.cadence,
        "fallback_used": False,
        "records": result["records"],
        "previous_state_id": args.previous_state_id,
        "previous_state_hash": args.previous_state_hash,
        "payload_references": [{{
            "path": str(raw_path),
            "sha256": hashlib.sha256(raw_bytes).hexdigest(),
        }}],
    }}
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(feed, sort_keys=True), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


def build_activation_candidate_scaffold(
    delta_plan: Mapping[str, Any],
    *,
    expected_delta_plan_sha256: str,
    expected_main_sha: str,
    expected_provider_name: str,
    expected_endpoint_template: str,
    expected_secret_name: str,
) -> dict[str, Any]:
    require(isinstance(delta_plan, Mapping), "ACTIVATION_SCAFFOLD_DELTA_PLAN_INVALID")
    require(
        canonical_digest(delta_plan) == expected_delta_plan_sha256,
        "ACTIVATION_SCAFFOLD_DELTA_PLAN_HASH_MISMATCH",
    )
    require(delta_plan.get("main_sha") == expected_main_sha,
            "ACTIVATION_SCAFFOLD_MAIN_SHA_MISMATCH")
    require(delta_plan.get("provider_name") == expected_provider_name,
            "ACTIVATION_SCAFFOLD_PROVIDER_MISMATCH")
    require(delta_plan.get("provider_endpoint_template") == expected_endpoint_template,
            "ACTIVATION_SCAFFOLD_ENDPOINT_MISMATCH")
    require(delta_plan.get("apply_allowed") is False,
            "ACTIVATION_SCAFFOLD_DELTA_PLAN_APPLY_FORBIDDEN")
    require(delta_plan.get("existing_file_preimage_sha256") == repo_preimage_hashes(),
            "ACTIVATION_SCAFFOLD_REPO_PREIMAGE_MISMATCH")
    require(
        set(delta_plan.get("existing_mutation_paths", [])) == set(ALLOWED_EXISTING_MUTATION_PATHS)
        and set(delta_plan.get("new_runtime_files", [])) == set(NEW_RUNTIME_FILES),
        "ACTIVATION_SCAFFOLD_PATH_BOUNDARY_INVALID",
    )

    candidate_files = {
        "config/RATE_EXTERNAL_PRODUCTION_DEPENDENCIES.json": _render_dependency(),
        "config/SOURCE_REGISTRY.json": _render_source_registry(
            expected_provider_name, expected_endpoint_template
        ),
        "config/RATE_PRODUCTION_OFFICIAL_SOURCE_REGISTRY_V1.json": _render_official_registry(
            expected_provider_name, expected_endpoint_template
        ),
        "src/phase2_production.py": _render_phase2(),
        "scripts/build_phase2_production_source.py": _read(
            "scripts/build_phase2_production_source.py"
        ),
        ".github/workflows/rate_production_0930_scheduler.yml": _render_scheduler(
            "09:30", expected_secret_name
        ),
        ".github/workflows/rate_production_1200_scheduler.yml": _render_scheduler(
            "12:00", expected_secret_name
        ),
        "src/intraday_provider_runtime.py": _runtime_source(expected_secret_name),
        "scripts/acquire_intraday_provider_feed.py": _acquisition_source(expected_secret_name),
    }

    review = validate_activation_candidate(
        delta_plan,
        candidate_files,
        expected_delta_plan_sha256=expected_delta_plan_sha256,
        expected_main_sha=expected_main_sha,
        expected_provider_name=expected_provider_name,
        expected_endpoint_template=expected_endpoint_template,
        expected_secret_name=expected_secret_name,
    )
    hashes = {
        path: hashlib.sha256(content.encode("utf-8")).hexdigest()
        for path, content in sorted(candidate_files.items())
    }
    return {
        "artifact": "RATE_INTRADAY_ACTIVATION_CANDIDATE_SCAFFOLD_V1",
        "validation_status": "PASS",
        "scaffold_status": "DESIGN_SCAFFOLD_ONLY",
        "main_sha": expected_main_sha,
        "delta_plan_sha256": expected_delta_plan_sha256,
        "provider_name": expected_provider_name,
        "candidate_file_sha256": hashes,
        "candidate_files": deepcopy(candidate_files),
        "static_review": review,
        "apply_allowed": False,
        "activation_execution_allowed": False,
        "external_dependency_resolved": False,
        "registry_activation_allowed": False,
        "repository_writes": 0,
        "network_requests": 0,
        "credential_access": 0,
        "production_credit": 0,
        "cer081_credit": 0,
    }
