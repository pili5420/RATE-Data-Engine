"""Manual-only Fugle free/basic feasibility diagnostic. No Production mutation."""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from src.provider_fugle_intraday_candidate import load_binding, qualify

ROOT = Path(__file__).resolve().parents[1]
BINDING_PATH = ROOT / "docs" / "contracts" / "RATE_FUGLE_FREE_INTRADAY_UNIVERSE_BINDING_V1.json"
OUTPUT_ROOT = ROOT / "artifacts" / "diagnostics" / "fugle-free-intraday"


def _load_fixed_binding() -> dict:
    try:
        value = json.loads(BINDING_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("FUGLE_DIAGNOSTIC_BINDING_UNREADABLE") from exc
    # Validate the fixed mirror against RATE's authoritative Production universe
    # before credential access or any network request.
    load_binding(value)
    return value


def _safe_output_path(output_name: str) -> Path:
    if not isinstance(output_name, str) or not output_name:
        raise RuntimeError("FUGLE_DIAGNOSTIC_OUTPUT_NAME_INVALID")
    if Path(output_name).name != output_name or "/" in output_name or "\\" in output_name:
        raise RuntimeError("FUGLE_DIAGNOSTIC_OUTPUT_PATH_FORBIDDEN")
    if not output_name.endswith(".json") or output_name in {".json", "..json"}:
        raise RuntimeError("FUGLE_DIAGNOSTIC_OUTPUT_NAME_INVALID")
    target = OUTPUT_ROOT / output_name
    if target.exists() or target.is_symlink():
        raise RuntimeError("FUGLE_DIAGNOSTIC_OUTPUT_EXISTS")
    if OUTPUT_ROOT.exists() and OUTPUT_ROOT.is_symlink():
        raise RuntimeError("FUGLE_DIAGNOSTIC_OUTPUT_ROOT_SYMLINK_FORBIDDEN")
    return target


def _write_new_result(target: Path, result: dict) -> None:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    # Exclusive create is the final race-safe no-overwrite gate.
    with target.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trading-date", required=True)
    parser.add_argument("--cadence", required=True, choices=["09:30", "12:00"])
    parser.add_argument(
        "--output-name",
        required=True,
        help="New JSON basename under artifacts/diagnostics/fugle-free-intraday; existing files are rejected.",
    )
    args = parser.parse_args()

    # All filesystem scope/binding gates execute before credential access/network.
    target = _safe_output_path(args.output_name)
    binding = _load_fixed_binding()
    token = os.getenv("FUGLE_API_KEY", "")

    result = qualify(
        token,
        binding,
        trading_date=args.trading_date,
        cadence=args.cadence,
        now_utc=datetime.now(timezone.utc),
    )
    _write_new_result(target, result)
    print(json.dumps({
        key: result[key]
        for key in ("technical_validation_status", "market_coverage", "license_gate", "production_eligible")
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
