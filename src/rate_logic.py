from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Mapping

SPEC_VERSION = "RATE-PLS-V1.1"
DATA_CONTRACT_VERSION = "RATE-DC-V1.0"
ENGINE_VERSION = "RATE-ENGINE-1.1.0"

M7_WEIGHTS = {"PT": Decimal("0.20"), "PV": Decimal("0.15"), "MO": Decimal("0.15"), "FI": Decimal("0.15"), "IT": Decimal("0.10"), "LH": Decimal("0.15"), "RS": Decimal("0.10")}
MHE_WEIGHTS = {"H5": Decimal("0.20"), "H20": Decimal("0.30"), "H60": Decimal("0.30"), "H120": Decimal("0.20")}
ROTATION_WEIGHTS = {"RS_CHANGE": Decimal("0.30"), "VOL_CHANGE": Decimal("0.25"), "SMART_MONEY": Decimal("0.25"), "MOMENTUM_CHANGE": Decimal("0.20")}
SMART_MONEY_WEIGHTS = {"FI": Decimal("0.30"), "IT": Decimal("0.25"), "LH": Decimal("0.25"), "FC": Decimal("0.20")}

class LogicDataIncomplete(ValueError):
    pass

def _score(values: Mapping[str, object], weights: Mapping[str, Decimal], label: str) -> float:
    missing = [key for key in weights if values.get(key) is None]
    if missing:
        raise LogicDataIncomplete(f"{label}_DATA_INCOMPLETE:{','.join(missing)}")
    for key in weights:
        value = values[key]
        if type(value) not in (int, float, Decimal) or not 0 <= float(value) <= 100:
            raise ValueError(f"{label}_RANGE:{key}")
    result = sum(Decimal(str(values[key])) * weight for key, weight in weights.items())
    return float(result.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

def classify_m7(score: float) -> str:
    if score >= 80: return "STRONG_CONFIRM"
    if score >= 65: return "STRENGTHENING"
    if score >= 50: return "NEUTRAL"
    if score >= 35: return "WEAKENING"
    return "WEAK"

def calculate_m7(values: Mapping[str, object]) -> dict:
    score = _score(values, M7_WEIGHTS, "M7")
    return {"m7_score": score, "m7_state": classify_m7(score), "components": {key: values[key] for key in M7_WEIGHTS}}

def classify_mhe(score: float) -> str:
    if score >= 75: return "MULTI_HORIZON_BULLISH"
    if score >= 60: return "BULLISH"
    if score >= 45: return "MIXED_NEUTRAL"
    if score >= 30: return "BEARISH"
    return "MULTI_HORIZON_BEARISH"

def calculate_mhe(values: Mapping[str, object]) -> dict:
    score = _score(values, MHE_WEIGHTS, "MHE")
    short_bull = float(values["H5"]) >= 60 and float(values["H20"]) >= 60
    long_bear = float(values["H60"]) < 45 and float(values["H120"]) < 45
    short_bear = float(values["H5"]) < 45 and float(values["H20"]) < 45
    long_bull = float(values["H60"]) >= 60 and float(values["H120"]) >= 60
    conflict = "SHORT_BULL_LONG_BEAR" if short_bull and long_bear else "SHORT_BEAR_LONG_BULL" if short_bear and long_bull else "NONE"
    return {"mhe_score": score, "mhe_state": classify_mhe(score), "mhe_conflict_state": conflict, "components": {key: values[key] for key in MHE_WEIGHTS}}

def calculate_rotation(values: Mapping[str, object]) -> dict:
    score = _score(values, ROTATION_WEIGHTS, "ROTATION")
    state = "ACCELERATING" if score >= 80 else "STRENGTHENING" if score >= 65 else "FLAT" if score >= 45 else "WEAKENING" if score >= 30 else "WARNING"
    return {"rotation_score": score, "rotation_state": state, "components": {key: values[key] for key in ROTATION_WEIGHTS}}

def calculate_smart_money(values: Mapping[str, object]) -> dict:
    score = _score(values, SMART_MONEY_WEIGHTS, "SMART_MONEY")
    state = "STRONG_INFLOW" if score >= 75 else "INFLOW" if score >= 60 else "NEUTRAL" if score >= 45 else "OUTFLOW" if score >= 30 else "STRONG_OUTFLOW"
    return {"smart_money_score": score, "smart_money_state": state, "components": {key: values[key] for key in SMART_MONEY_WEIGHTS}}

def rank_composites(values: Mapping[str, float]) -> dict:
    rate = .20*values["M7"] + .15*values["MHE"] + .15*values["Stage"] + .15*values["Rotation"] + .15*values["SmartMoney"] + .10*values["Fundamental"] + .10*values["RelativeStrength"]
    short = .25*values["M7"] + .20*values["Rotation"] + .20*values["SmartMoney"] + .15*values["MHE"] + .10*values["Stage"] + .10*values["RelativeStrength"]
    long = .25*values["Fundamental"] + .20*values["Stage"] + .20*values["MHE"] + .15*values["SmartMoney"] + .10*values["RelativeStrength"] + .10*values["M7"]
    return {"rate_composite_score": round(rate, 2), "short_score": round(short, 2), "long_score": round(long, 2)}

def rank_candidates(rows: list[Mapping[str, object]], score_key: str, limit: int) -> list[dict]:
    required = {"symbol", score_key, "SmartMoney", "MHE", "RelativeStrength", "Liquidity"}
    if any(not required.issubset(row) for row in rows):
        raise LogicDataIncomplete("RANKING_DATA_INCOMPLETE")
    ordered = sorted(rows, key=lambda row: (-float(row[score_key]), -float(row["SmartMoney"]), -float(row["MHE"]), -float(row["RelativeStrength"]), -float(row["Liquidity"]), str(row["symbol"])))
    return [{**dict(row), "rank": index + 1} for index, row in enumerate(ordered[:limit])]

def stage_fixture(evidence: Mapping[str, object]) -> dict:
    """Evaluate only the frozen golden scenarios; general mapping is unspecified in V1.1."""
    if evidence.get("structural_failure") is True:
        return {"stage_current": "DEFENSIVE", "stage_override": True, "stage_override_reason": "STRUCTURAL_FAILURE"}
    if evidence.get("previous_stage") == "PRE_MARKUP" and evidence.get("price_above_all") is True and evidence.get("ma20_above_ma60") is True and evidence.get("ma20_slope_positive") is True and float(evidence.get("m7_score", -1)) >= 80 and float(evidence.get("mhe_score", -1)) >= 60:
        return {"stage_current": "MARKUP", "stage_override": False, "stage_override_reason": None}
    if evidence.get("previous_stage") == "HIGH_ROTATION" and evidence.get("long_term_bullish") is True and evidence.get("price_near_ma20_ma60") is True and float(evidence.get("mhe_score", 100)) < 60 and float(evidence.get("m7_score", 100)) < 65:
        return {"stage_current": "HIGH_CONSOLIDATION", "stage_override": False, "stage_override_reason": None}
    raise LogicDataIncomplete("STAGE_UNDEFINED_CLASSIFICATION_MAPPING")
