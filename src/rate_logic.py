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

STAGE_NORMALIZED_SCORES = {"MARKUP": 90, "PRE_MARKUP": 80, "STRENGTHENING": 70,
    "HIGH_ROTATION": 65, "HIGH_CONSOLIDATION": 60, "BASE_BUILDING": 50,
    "CONSOLIDATION": 40, "DEFENSIVE": 20}

def _first(evidence: Mapping[str, object], *keys: str):
    for key in keys:
        if key in evidence and evidence[key] is not None:
            return evidence[key]
    return None

def classify_stage(evidence: Mapping[str, object]) -> dict:
    """RATE-SPEC-20260914-003 priority-ordered deterministic classifier."""
    structural_failure = evidence.get("structural_failure") is True
    previous = evidence.get("previous_stage")
    price = _first(evidence, "price", "Price")
    ma20 = _first(evidence, "ma20", "MA20")
    ma60 = _first(evidence, "ma60", "MA60")
    ma120 = _first(evidence, "ma120", "MA120")
    m7 = _first(evidence, "m7_score", "M7")
    mhe = _first(evidence, "mhe_score", "MHE")
    rs_strong = evidence.get("relative_strength_strong", evidence.get("rs_strong"))
    ma20_slope_positive = evidence.get("ma20_slope_positive")
    ma60_trend_non_negative = evidence.get("ma60_trend_non_negative")
    near_ma = evidence.get("price_near_ma20_ma60")
    long_bull = evidence.get("long_term_bullish")
    mhe_improving = evidence.get("short_swing_mhe_improving")
    recent_low_stable = evidence.get("recent_low_no_longer_deteriorating")
    m7_rising = evidence.get("m7_rising")
    mhe_rising = evidence.get("mhe_rising")
    mixed = evidence.get("evidence_state_mixed")
    def concrete(*values): return all(value is not None for value in values)
    price_above_all = evidence.get("price_above_all") if evidence.get("price_above_all") is not None else concrete(price, ma20, ma60, ma120) and price > ma20 and price > ma60 and price > ma120
    ma20_above_ma60 = evidence.get("ma20_above_ma60") if evidence.get("ma20_above_ma60") is not None else concrete(ma20, ma60) and ma20 > ma60
    price_below_ma60 = concrete(price, ma60) and price < ma60
    if structural_failure or (price_below_ma60 and m7 is not None and m7 < 35):
        adjacent = {"DEFENSIVE", "BASE_BUILDING", "CONSOLIDATION"}
        override = structural_failure and previous not in adjacent
        return {"stage_current":"DEFENSIVE", "stage_normalized_score":20, "stage_override":override,
                "stage_override_reason":"STRUCTURAL_FAILURE" if override else None}
    markup = (price_above_all is True and ma20_above_ma60 is True and ma20_slope_positive is True and
              m7 is not None and m7 >= 75 and mhe is not None and mhe >= 60 and rs_strong is True)
    if markup:
        return {"stage_current":"MARKUP", "stage_normalized_score":90, "stage_override":False, "stage_override_reason":None}
    pre_markup = (concrete(price, ma20, ma60) and price > ma20 and price > ma60 and ma20_slope_positive is True and
                  m7 is not None and m7 >= 65 and mhe is not None and mhe >= 60)
    if pre_markup:
        return {"stage_current":"PRE_MARKUP", "stage_normalized_score":80, "stage_override":False, "stage_override_reason":None}
    strengthening = (concrete(price, ma20) and price > ma20 and m7 is not None and m7 >= 65 and mhe_improving is True)
    if strengthening:
        return {"stage_current":"STRENGTHENING", "stage_normalized_score":70, "stage_override":False, "stage_override_reason":None}
    rotation_deteriorated = evidence.get("rotation_deteriorated") is True
    high_rotation = (long_bull is True and (ma60_trend_non_negative is True or evidence.get("price_above_ma60") is True) and
                     ((evidence.get("prior_m7") is not None and m7 is not None and evidence["prior_m7"] >= 75 and m7 < 75) or rotation_deteriorated))
    if high_rotation:
        return {"stage_current":"HIGH_ROTATION", "stage_normalized_score":65, "stage_override":False, "stage_override_reason":None}
    high_consolidation = (long_bull is True and near_ma is True and mhe is not None and mhe >= 45 and m7 is not None and 35 <= m7 < 65)
    if high_consolidation:
        return {"stage_current":"HIGH_CONSOLIDATION", "stage_normalized_score":60, "stage_override":False, "stage_override_reason":None}
    base = ((price is not None and ((ma60 is not None and price <= ma60) or (ma120 is not None and price <= ma120))) and
            recent_low_stable is True and (m7_rising is True or mhe_rising is True))
    if base:
        return {"stage_current":"BASE_BUILDING", "stage_normalized_score":50, "stage_override":False, "stage_override_reason":None}
    if (m7 is not None and 35 <= m7 < 65) or mixed is True:
        return {"stage_current":"CONSOLIDATION", "stage_normalized_score":40, "stage_override":False, "stage_override_reason":None}
    raise LogicDataIncomplete("MISSING_REQUIRED_DATA:STAGE_RULE_FIELDS")

def stage_fixture(evidence: Mapping[str, object]) -> dict:
    """Backward-compatible fixture adapter using the frozen fixture's evidence aliases."""
    return classify_stage(evidence)
