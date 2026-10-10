from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.cer074_acceptance import atomic_write_json, load_json
from src.cer080_multi_day_continuity import EXCHANGE_HOLIDAYS, TRADING_CALENDAR_SOURCE, is_trading_day, resolve_next_trading_day
from src.production_live_state import load_live_state

CADENCE_PREDECESSOR = {
    "07:30": "19:30",
    "09:30": "07:30",
    "12:00": "09:30",
    "19:30": "12:00",
}
CADENCE_DIR = {"07:30": "0730", "09:30": "0930", "12:00": "1200", "19:30": "1930"}


def _today_taipei() -> str:
    if ZoneInfo is None:
        raise RuntimeError("ZONEINFO_UNAVAILABLE")
    return datetime.now(ZoneInfo("Asia/Taipei")).date().isoformat()


def _previous_legal_trading_day(trading_date: str) -> str:
    current = datetime.fromisoformat(trading_date).date() - timedelta(days=1)
    while True:
        text = current.isoformat()
        if is_trading_day(text):
            return text
        current -= timedelta(days=1)


def _state_path(root: Path, trading_date: str, cadence: str) -> Path:
    return root / "live" / trading_date / CADENCE_DIR[cadence] / "RATE_PRODUCTION_PERSIST_RESULT_EVIDENCE.json"


def resolve_context(*, cadence: str, event_name: str, dispatch_trading_date: str | None, state_root: Path) -> dict[str, Any]:
    if cadence not in CADENCE_PREDECESSOR:
        raise RuntimeError("UNSUPPORTED_CADENCE")
    if event_name == "schedule":
        trading_date = _today_taipei()
        trading_date_resolution = "DYNAMIC_TAIWAN_TRADING_DATE"
    elif event_name == "workflow_dispatch":
        if not dispatch_trading_date:
            raise RuntimeError("WORKFLOW_DISPATCH_REQUIRES_EXPLICIT_TRADING_DATE")
        trading_date = dispatch_trading_date
        trading_date_resolution = "EXPLICIT_WORKFLOW_DISPATCH_INPUT"
    else:
        trading_date = dispatch_trading_date or _today_taipei()
        trading_date_resolution = "VALIDATION_ONLY_NOT_PRODUCTION_RUNTIME"
    calendar = {
        "trading_calendar_source": TRADING_CALENDAR_SOURCE,
        "exchange_holidays": sorted(EXCHANGE_HOLIDAYS),
        "trading_date": trading_date,
        "is_trading_day": is_trading_day(trading_date),
    }
    runtime_mode = "RUN" if calendar["is_trading_day"] else "NOOP_NON_TRADING_DAY"
    previous_cadence = CADENCE_PREDECESSOR[cadence]
    previous_trading_date = _previous_legal_trading_day(trading_date) if cadence == "07:30" else trading_date
    previous_state_path = _state_path(state_root, previous_trading_date, previous_cadence)
    context = {
        "artifact": "RATE_PRODUCTION_RUNTIME_CONTEXT",
        "validation_status": "PASS",
        "event_name": event_name,
        "cadence": cadence,
        "trading_date": trading_date,
        "trading_date_resolution": trading_date_resolution,
        "scheduled_historical_acceptance_date_fallback": "FORBIDDEN",
        "calendar": calendar,
        "runtime_mode": runtime_mode,
        "previous_trading_date": previous_trading_date,
        "previous_cadence": previous_cadence,
        "previous_state_resolution": "LIVE_PRODUCTION_STATE_STORE",
        "previous_state_evidence_path": str(previous_state_path).replace("\\", "/"),
        "acceptance_artifacts_role": "AUDIT_ONLY_NOT_RECURRING_PREDECESSOR",
        "production_persistent_state_reset_count": 0,
    }
    if event_name in {"schedule", "workflow_dispatch"} and runtime_mode == "RUN":
        try:
            previous = load_live_state(state_root, previous_trading_date, previous_cadence)
            context["previous_state_id"] = previous["state"]["current_state_id"]
            context["previous_state_hash"] = previous["state"]["decision_payload_hash"]
            context["previous_state_match_count"] = 1
        except RuntimeError as exc:
            context["validation_status"] = "BLOCKED"
            context["blocking_reason"] = str(exc)
    return context


def write_env(path: Path, context: dict[str, Any]) -> None:
    lines = [
        f"RATE_PRODUCTION_TRADING_DATE={context['trading_date']}",
        f"RATE_PRODUCTION_RUNTIME_MODE={context['runtime_mode']}",
        f"RATE_PREVIOUS_STATE_EVIDENCE_PATH={context['previous_state_evidence_path']}",
        f"RATE_PREVIOUS_TRADING_DATE={context['previous_trading_date']}",
        f"RATE_PREVIOUS_CADENCE={context['previous_cadence']}",
        f"RATE_RUNTIME_CONTEXT_STATUS={context['validation_status']}",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Resolve RATE production scheduler runtime context without historical acceptance-date fallback.")
    parser.add_argument("--cadence", required=True, choices=sorted(CADENCE_PREDECESSOR))
    parser.add_argument("--event-name", default=os.getenv("GITHUB_EVENT_NAME", "local"))
    parser.add_argument("--dispatch-trading-date", default=None)
    parser.add_argument("--state-root", default="artifacts/production_state")
    parser.add_argument("--evidence-output", default="artifacts/production_runtime/RATE_PRODUCTION_RUNTIME_CONTEXT.json")
    parser.add_argument("--env-output", default=None)
    parser.add_argument("--phase2", action="store_true")
    args = parser.parse_args()
    resolver = resolve_context
    if args.phase2 and args.cadence not in {"09:30", "12:00"}:
        from src.phase2_production import resolve_phase2_context
        resolver = resolve_phase2_context
    try:
        context = resolver(cadence=args.cadence, event_name=args.event_name, dispatch_trading_date=args.dispatch_trading_date, state_root=Path(args.state_root))
    except RuntimeError as exc:
        context = {"validation_status": "BLOCKED", "blocking_reason": str(exc)}
    atomic_write_json(Path(args.evidence_output), context)
    if args.env_output and context["validation_status"] == "PASS":
        write_env(Path(args.env_output), context)
    print(json.dumps(context, ensure_ascii=False, sort_keys=True))
    if context["validation_status"] == "BLOCKED" and args.event_name in {"schedule", "workflow_dispatch"}:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
