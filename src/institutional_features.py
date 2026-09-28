"""RATE institutional and rotation feature calculations (RATE-DFCS-V1.0)."""
from __future__ import annotations

from .feature_math import pctl
from .rate_logic import calculate_smart_money, calculate_rotation

SPEC_VERSION = "RATE-DFCS-V1.0"
HISTORY_FIELDS = ("rs_history", "volume_ratio_5_20_history", "mo_history")


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


def _validated_feature_history(row, field, symbol, expected_dates):
    history = row.get(field)
    if not isinstance(history, list) or len(history) < 6:
        raise ValueError(f"DATA_INCOMPLETE:ROTATION_HISTORY:{symbol}")
    selected = history[-6:]
    dates = [str(item.get("trade_date", "")) for item in selected if isinstance(item, dict)]
    if len(dates) != 6 or dates != expected_dates or len(set(dates)) != 6:
        raise ValueError(f"DATA_INCOMPLETE:ROTATION_HISTORY:{symbol}:{field}:DATE_ALIGNMENT")
    values = []
    for item in selected:
        value = item.get("value")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"DATA_INCOMPLETE:ROTATION_HISTORY:{symbol}:{field}:VALUE")
        if item.get("calculation_spec_version") != SPEC_VERSION:
            raise ValueError(f"ROTATION_HISTORY_SPEC_MISMATCH:{symbol}:{field}")
        values.append(float(value))
    return selected, values


def calculate_institutional_rotation(rows):
    """Calculate institutional and 5-session feature deltas cross-sectionally.

    Rotation histories must be actual six-session RATE-DFCS feature records,
    with identical dates across the eligible cross-section. Legacy close-price
    and constant placeholder fields are rejected.
    """
    if len(rows) < 20:
        raise ValueError("DATA_INCOMPLETE:PERCENTILE_UNIVERSE_TOO_SMALL")
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
        fc = 100.0 * sum(1 for x in valid if (float(x["foreign_net_shares"]) + float(x["investment_trust_net_shares"])) * float(x["close"]) > 0) / len(valid)
        lh_level = float(tdcc[-1]["holder_pct_400"])
        lh_change = lh_level - float(tdcc[-5]["holder_pct_400"])
        prepared.append({"row": row, "symbol": symbol, "ih": ih, "tdcc": tdcc,
                         "FI5_RAW": fi5, "FI20_RAW": fi20, "IT5_RAW": it5, "IT20_RAW": it20,
                         "FC": fc, "LH_LEVEL": lh_level, "LH_CHANGE_4W": lh_change})

    # A single same-date cross-section is mandatory for each percentile input.
    all_dates = []
    for item in prepared:
        row = item["row"]
        date_sets = []
        for field in HISTORY_FIELDS:
            history = row.get(field)
            if not isinstance(history, list) or len(history) < 6:
                raise ValueError(f"DATA_INCOMPLETE:ROTATION_HISTORY:{item['symbol']}:{field}")
            dates = [str(x.get("trade_date", "")) for x in history[-6:] if isinstance(x, dict)]
            if len(dates) != 6 or len(set(dates)) != 6:
                raise ValueError(f"DATA_INCOMPLETE:ROTATION_HISTORY:{item['symbol']}:{field}:DATE_ALIGNMENT")
            date_sets.append(dates)
        if not all(x == date_sets[0] for x in date_sets[1:]):
            raise ValueError(f"DATA_INCOMPLETE:ROTATION_HISTORY:{item['symbol']}:CROSS_FEATURE_DATE_ALIGNMENT")
        all_dates.append(date_sets[0])
    if any(x != all_dates[0] for x in all_dates[1:]):
        raise ValueError("DATA_INCOMPLETE:ROTATION_CROSS_SECTION_DATE_ALIGNMENT")
    expected_dates = all_dates[0]

    feature_sets = []
    for item in prepared:
        row = item["row"]
        item["rs_records"], item["rs_values"] = _validated_feature_history(row, "rs_history", item["symbol"], expected_dates)
        item["vol_records"], item["vol_values"] = _validated_feature_history(row, "volume_ratio_5_20_history", item["symbol"], expected_dates)
        item["mo_records"], item["mo_values"] = _validated_feature_history(row, "mo_history", item["symbol"], expected_dates)
        if any(float(x["value"]) < 0 for x in item["vol_records"]):
            raise ValueError(f"ROTATION_VOLUME_RATIO_RANGE:{item['symbol']}")
        item["RS_t"], item["RS_t_minus_5"] = item["rs_values"][-1], item["rs_values"][0]
        item["VOL_RATIO_t"], item["VOL_RATIO_t_minus_5"] = item["vol_values"][-1], item["vol_values"][0]
        item["MO_t"], item["MO_t_minus_5"] = item["mo_values"][-1], item["mo_values"][0]
        item["RS_DELTA_5"] = item["RS_t"] - item["RS_t_minus_5"]
        item["VOL_DELTA_5"] = item["VOL_RATIO_t"] - item["VOL_RATIO_t_minus_5"]
        item["MO_DELTA_5"] = item["MO_t"] - item["MO_t_minus_5"]
        feature_sets.append(item)

    fi5s, fi20s = [x["FI5_RAW"] for x in prepared], [x["FI20_RAW"] for x in prepared]
    it5s, it20s = [x["IT5_RAW"] for x in prepared], [x["IT20_RAW"] for x in prepared]
    lhs, lhcs = [x["LH_LEVEL"] for x in prepared], [x["LH_CHANGE_4W"] for x in prepared]
    rs_deltas = [x["RS_DELTA_5"] for x in prepared]
    vol_deltas = [x["VOL_DELTA_5"] for x in prepared]
    mo_deltas = [x["MO_DELTA_5"] for x in prepared]
    for x in prepared:
        fi5_score, fi20_score = pctl(x["FI5_RAW"], fi5s), pctl(x["FI20_RAW"], fi20s)
        it5_score, it20_score = pctl(x["IT5_RAW"], it5s), pctl(x["IT20_RAW"], it20s)
        lh_level_score, lh_change_score = pctl(x["LH_LEVEL"], lhs), pctl(x["LH_CHANGE_4W"], lhcs)
        fi = round(.4 * fi5_score + .6 * fi20_score, 2)
        it = round(.4 * it5_score + .6 * it20_score, 2)
        lh = round(.6 * lh_level_score + .4 * lh_change_score, 2)
        fc = round(x["FC"], 2)
        sm = calculate_smart_money({"FI": fi, "IT": it, "LH": lh, "FC": fc})["smart_money_score"]
        rs_change = round(pctl(x["RS_DELTA_5"], rs_deltas), 2)
        vol_change = round(pctl(x["VOL_DELTA_5"], vol_deltas), 2)
        momentum_change = round(pctl(x["MO_DELTA_5"], mo_deltas), 2)
        rotation_inputs = {"RS_CHANGE": rs_change, "VOL_CHANGE": vol_change,
                           "SMART_MONEY": sm, "MOMENTUM_CHANGE": momentum_change}
        rotation = calculate_rotation(rotation_inputs)["rotation_score"]
        rs_lineage = _lineage(x["symbol"], "RS_CHANGE", x["rs_records"], rs_change,
            {"RS_t": x["RS_t"], "RS_t_minus_5": x["RS_t_minus_5"], "RS_DELTA_5": x["RS_DELTA_5"], "RS_CHANGE": rs_change})
        vol_lineage = _lineage(x["symbol"], "VOL_CHANGE", x["vol_records"], vol_change,
            {"VOL_RATIO_t": x["VOL_RATIO_t"], "VOL_RATIO_t_minus_5": x["VOL_RATIO_t_minus_5"], "VOL_DELTA_5": x["VOL_DELTA_5"], "VOL_CHANGE": vol_change})
        mo_lineage = _lineage(x["symbol"], "MOMENTUM_CHANGE", x["mo_records"], momentum_change,
            {"MO_t": x["MO_t"], "MO_t_minus_5": x["MO_t_minus_5"], "MO_DELTA_5": x["MO_DELTA_5"], "MOMENTUM_CHANGE": momentum_change})
        lineage = {
            "FI": _lineage(x["symbol"], "FI", x["ih"], fi, {"FI5_RAW": x["FI5_RAW"], "FI20_RAW": x["FI20_RAW"], "FI5_SCORE": fi5_score, "FI20_SCORE": fi20_score}),
            "IT": _lineage(x["symbol"], "IT", x["ih"], it, {"IT5_RAW": x["IT5_RAW"], "IT20_RAW": x["IT20_RAW"], "IT5_SCORE": it5_score, "IT20_SCORE": it20_score}),
            "FC": _lineage(x["symbol"], "FC", x["ih"][-20:], fc, {"valid_institutional_days": len(x["ih"][-20:])}),
            "LH": _lineage(x["symbol"], "LH", x["tdcc"][-5:], lh, {"LH_LEVEL": x["LH_LEVEL"], "LH_CHANGE_4W": x["LH_CHANGE_4W"], "LH_LEVEL_SCORE": lh_level_score, "LH_CHANGE_SCORE": lh_change_score}),
            "RS_CHANGE": rs_lineage, "VOL_CHANGE": vol_lineage, "MOMENTUM_CHANGE": mo_lineage,
            "SMART_MONEY": {"calculation_spec_version": SPEC_VERSION, "calculation_status": "PASS", "derived_value": sm},
            "Rotation": {"calculation_spec_version": SPEC_VERSION, "calculation_status": "PASS", "source_dates": expected_dates, "derived_value": rotation},
        }
        x["row"].update({"FI": fi, "IT": it, "FC": fc, "LH": lh, "RS_CHANGE": rs_change,
            "VOL_CHANGE": vol_change, "MOMENTUM_CHANGE": momentum_change,
            "SMART_MONEY": sm, "Rotation": rotation,
            "SmartMoney_inputs": {"FI": fi, "IT": it, "LH": lh, "FC": fc},
            "Rotation_inputs": rotation_inputs, "feature_lineage": lineage})
    return [x["row"] for x in prepared]
