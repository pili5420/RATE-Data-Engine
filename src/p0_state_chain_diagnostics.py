"""P0 predecessor outage diagnostics only. Never creates or admits a State."""
from __future__ import annotations

from datetime import date

CADENCES = ("07:30", "09:30", "12:00", "19:30")


def blocked_predecessor_diagnostic(*, trading_date: str, cadence: str,
                                   previous_legal_trading_day: str,
                                   observed_slots: list[tuple[str, str]],
                                   approved_first_refresh: dict | None = None) -> dict:
    date.fromisoformat(trading_date)
    date.fromisoformat(previous_legal_trading_day)
    if cadence not in CADENCES:
        raise ValueError("P0_PREDECESSOR_CADENCE_INVALID")
    prior = {
        "07:30": (previous_legal_trading_day, "19:30"),
        "09:30": (trading_date, "07:30"),
        "12:00": (trading_date, "09:30"),
    }
    slots = sorted(set((day, time) for day, time in observed_slots
                       if isinstance(day, str) and isinstance(time, str)
                       and time in CADENCES and day <= trading_date))
    expected = prior.get(cadence)
    basis = "EXACT_PREDECESSOR_CADENCE_REQUIRED"
    if cadence == "19:30":
        today_noon = (trading_date, "12:00")
        seed = approved_first_refresh or {}
        seed_slot = (seed.get("predecessor_trading_date"),
                     seed.get("predecessor_cadence"))
        if today_noon in slots:
            expected, basis = today_noon, "TODAY_1200_CANDIDATE_ONLY"
        elif seed_slot in slots:
            expected, basis = seed_slot, "SINGLE_USE_FIRST_REFRESH_CANDIDATE_ONLY"
        else:
            expected = max(slots) if slots else (None, None)
            basis = "LATEST_OBSERVED_SLOT_NOT_ADMITTED"
    return {
        "artifact": "RATE_P0_PREDECESSOR_BLOCKAGE_DIAGNOSTIC_V1",
        "status": "BLOCK",
        "trading_date": trading_date, "cadence": cadence,
        "expected_predecessor_trading_date": expected[0],
        "expected_predecessor_cadence": expected[1],
        "expected_predecessor_basis": basis,
        "expected_slot_present": expected in slots,
        "observed_slot_count": len(slots),
        "latest_observed_slot": list(slots[-1]) if slots else None,
        "state_id_hash_verified": False,
        "first_refresh_authority_consumption_verified": False,
        "publication_permitted": False,
        "forbidden_recovery": "NO_SYNTHETIC_STATE_NO_HISTORICAL_BACKFILL",
    }
