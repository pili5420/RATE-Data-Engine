"""RATE institutional and rotation feature calculations (RATE-DFCS-V1.0).

This module only calculates data features.  It does not contain decision or
portfolio policy and keeps raw inputs and lineage alongside each result.
"""
from __future__ import annotations

from .feature_math import pctl
from .rate_logic import calculate_smart_money, calculate_rotation

SPEC_VERSION = "RATE-DFCS-V1.0"


def _raw(history, field, window):
    valid = [r for r in history[-window:] if r.get(field) is not None and r.get("close") is not None and r.get("turnover") is not None]
    if len(valid) < window:
        raise ValueError(f"DATA_INCOMPLETE:{field}_{window}")
    return sum(float(r[field]) * float(r["close"]) for r in valid) / sum(float(r["turnover"]) for r in valid)


def _lineage(symbol, name, history, value, intermediates=None):
    return {"symbol": str(symbol), "feature_name": name,
            "raw_source_ids": [str(r.get("source_id", r.get("trade_date", ""))) for r in history],
            "raw_source_timestamps": [r.get("source_timestamp") for r in history],
            "raw_periods": [r.get("trade_date", r.get("period_end")) for r in history],
            "raw_input_values": history, "derived_intermediates": intermediates or {},
            "derived_value": value, "calculation_spec_version": SPEC_VERSION,
            "calculation_status": "PASS"}


def calculate_institutional_rotation(rows):
    """Calculate FI/IT/FC/LH and rotation inputs cross-sectionally.

    ``rows`` is a list of mappings containing ``institutional_history``,
    ``tdcc_history``, ``rs_history``, ``volume_5_history`` and ``mo_history``.
    All calculations are deterministic and fail closed on insufficient history.
    """
    prepared = []
    for row in rows:
        symbol = row.get("symbol")
        ih = row.get("institutional_history", [])
        tdcc = row.get("tdcc_history", [])
        if len(ih) < 20:
            raise ValueError(f"DATA_INCOMPLETE:INSTITUTIONAL_HISTORY:{symbol}")
        if len(tdcc) < 5 or any(x.get("period_end") is None for x in tdcc[-5:]):
            raise ValueError(f"DATA_INCOMPLETE:LH_HISTORY:{symbol}")
        fi5, fi20 = _raw(ih, "foreign_net_shares", 5), _raw(ih, "foreign_net_shares", 20)
        it5, it20 = _raw(ih, "investment_trust_net_shares", 5), _raw(ih, "investment_trust_net_shares", 20)
        valid = [x for x in ih[-20:] if x.get("foreign_net_shares") is not None and x.get("investment_trust_net_shares") is not None and x.get("close") is not None]
        if len(valid) < 15:
            raise ValueError(f"DATA_INCOMPLETE:FC_HISTORY:{symbol}")
        fc = 100.0 * sum(1 for x in valid if float(x["foreign_net_shares"]) * float(x["close"]) + float(x["investment_trust_net_shares"]) * float(x["close"]) > 0) / len(valid)
        lh_level = float(tdcc[-1]["holder_pct_400"])
        lh_change = lh_level - float(tdcc[-5]["holder_pct_400"])
        prepared.append({"row": row, "symbol": symbol, "ih": ih, "tdcc": tdcc,
                         "FI5_RAW": fi5, "FI20_RAW": fi20, "IT5_RAW": it5, "IT20_RAW": it20,
                         "FC": fc, "LH_LEVEL": lh_level, "LH_CHANGE_4W": lh_change})
    fi5s, fi20s = [x["FI5_RAW"] for x in prepared], [x["FI20_RAW"] for x in prepared]
    it5s, it20s = [x["IT5_RAW"] for x in prepared], [x["IT20_RAW"] for x in prepared]
    lhs, lhcs = [x["LH_LEVEL"] for x in prepared], [x["LH_CHANGE_4W"] for x in prepared]
    rsd, vold, mod = [], [], []
    for x in prepared:
        row = x["row"]
        rs = row.get("rs_history", []); vh = row.get("volume_5_history", []); mh = row.get("mo_history", [])
        if len(rs) < 6 or len(vh) < 1 or len(mh) < 6:
            raise ValueError(f"DATA_INCOMPLETE:ROTATION_HISTORY:{x['symbol']}")
        rsd.append(float(rs[-1]) - float(rs[-6])); vold.append(float(vh[-1]) - 1.0); mod.append(float(mh[-1]) - float(mh[-6]))
    for i, x in enumerate(prepared):
        fi5_score, fi20_score = pctl(x["FI5_RAW"], fi5s), pctl(x["FI20_RAW"], fi20s)
        it5_score, it20_score = pctl(x["IT5_RAW"], it5s), pctl(x["IT20_RAW"], it20s)
        lh_level_score, lh_change_score = pctl(x["LH_LEVEL"], lhs), pctl(x["LH_CHANGE_4W"], lhcs)
        fi = round(.4 * fi5_score + .6 * fi20_score, 2); it = round(.4 * it5_score + .6 * it20_score, 2)
        lh = round(.6 * lh_level_score + .4 * lh_change_score, 2)
        fc = round(x["FC"], 2); sm = calculate_smart_money({"FI": fi, "IT": it, "LH": lh, "FC": fc})["smart_money_score"]
        rs_change, vol_change, momentum_change = round(pctl(rsd[i], rsd), 2), round(pctl(vold[i], vold), 2), round(pctl(mod[i], mod), 2)
        rotation = calculate_rotation({"RS_CHANGE": rs_change, "VOL_CHANGE": vol_change, "SMART_MONEY": sm, "MOMENTUM_CHANGE": momentum_change})["rotation_score"]
        rs_hist = [{"value": v} for v in x["row"].get("rs_history", [])]
        vol_hist = [{"value": v} for v in x["row"].get("volume_5_history", [])]
        mo_hist = [{"value": v} for v in x["row"].get("mo_history", [])]
        lineage = {
            "FI": _lineage(x["symbol"], "FI", x["ih"], fi, {"FI5_RAW": x["FI5_RAW"], "FI20_RAW": x["FI20_RAW"], "FI5_SCORE": fi5_score, "FI20_SCORE": fi20_score}),
            "IT": _lineage(x["symbol"], "IT", x["ih"], it, {"IT5_RAW": x["IT5_RAW"], "IT20_RAW": x["IT20_RAW"], "IT5_SCORE": it5_score, "IT20_SCORE": it20_score}),
            "FC": _lineage(x["symbol"], "FC", x["ih"][-20:], fc, {"valid_institutional_days": len(x["ih"][-20:])}),
            "LH": _lineage(x["symbol"], "LH", x["tdcc"][-5:], lh, {"LH_LEVEL": x["LH_LEVEL"], "LH_CHANGE_4W": x["LH_CHANGE_4W"], "LH_LEVEL_SCORE": lh_level_score, "LH_CHANGE_SCORE": lh_change_score}),
            "RS_CHANGE": _lineage(x["symbol"], "RS_CHANGE", rs_hist, rs_change, {"RS_DELTA_5": rsd[i]}),
            "VOL_CHANGE": _lineage(x["symbol"], "VOL_CHANGE", vol_hist, vol_change, {"VOL_CHANGE_RAW": vold[i]}),
            "MOMENTUM_CHANGE": _lineage(x["symbol"], "MOMENTUM_CHANGE", mo_hist, momentum_change, {"MO_DELTA_5": mod[i]}),
        }
        x["row"].update({"FI": fi, "IT": it, "FC": fc, "LH": lh, "RS_CHANGE": rs_change,
                          "VOL_CHANGE": vol_change, "MOMENTUM_CHANGE": momentum_change,
                          "SMART_MONEY": sm, "Rotation": rotation, "SmartMoney_inputs": {"FI": fi, "IT": it, "LH": lh, "FC": fc},
                          "Rotation_inputs": {"RS_CHANGE": rs_change, "VOL_CHANGE": vol_change, "SMART_MONEY": sm, "MOMENTUM_CHANGE": momentum_change},
                          "feature_lineage": lineage})
    return [x["row"] for x in prepared]
