"""Same-date, no-lookahead historical M7/MHE/Rotation inputs for Stage."""
from __future__ import annotations

from .institutional_features import calculate_institutional_rotation
from .rate_logic import calculate_m7, calculate_mhe, calculate_rotation
from .rotation_history import build_rotation_feature_histories
from .technical_features import compute_scores, technical_record


def build_stage_feature_histories(stock_histories, benchmark_by_symbol, institutional_histories,
                                  tdcc_histories, *, as_of_date, sessions=7):
    symbols = sorted(str(s) for s in stock_histories)
    if len(symbols) < 20 or sessions < 7:
        raise ValueError("DATA_INCOMPLETE:STAGE_HISTORY_UNIVERSE_OR_SESSIONS")
    stock = {s: sorted((dict(r) for r in stock_histories[s] if r["trade_date"] <= as_of_date), key=lambda r:r["trade_date"]) for s in symbols}
    bench = {s: sorted((dict(r) for r in benchmark_by_symbol[s] if r["trade_date"] <= as_of_date), key=lambda r:r["trade_date"]) for s in symbols}
    common = set.intersection(*(set(r["trade_date"] for r in stock[s]) & set(r["trade_date"] for r in bench[s]) for s in symbols))
    dates = sorted(common)[-sessions:]
    if len(dates) != sessions or dates[-1] != as_of_date:
        raise ValueError("DATA_INCOMPLETE:STAGE_HISTORY_DATES")
    output = {s: [] for s in symbols}
    for session in dates:
        stocks_asof = {s:[{**r,"symbol":s} for r in stock[s] if r["trade_date"] <= session] for s in symbols}
        benches_asof = {s:[r for r in bench[s] if r["trade_date"] <= session] for s in symbols}
        tech = compute_scores([stocks_asof[s] for s in symbols], benchmark_by_symbol=benches_asof)
        tech_by = {str(r["symbol"]):r["technical_features"] for r in tech}
        records_by = {s: stocks_asof[s] for s in symbols}
        rotation_history = build_rotation_feature_histories(records_by, benches_asof, as_of_date=session, sessions=6)
        institutional_rows = []
        for s in symbols:
            ih = [dict(r) for r in institutional_histories[s] if str(r.get("trading_date", r.get("trade_date", ""))) <= session]
            ih.sort(key=lambda r:str(r.get("trading_date",r.get("trade_date",""))))
            if not ih or str(ih[-1].get("trading_date",ih[-1].get("trade_date",""))) != session:
                raise ValueError(f"DATA_INCOMPLETE:STAGE_INSTITUTIONAL_DATE:{s}:{session}")
            dh = sorted((dict(r) for r in tdcc_histories[s] if str(r.get("period_end", "")) <= session),key=lambda r:str(r.get("period_end","")))
            institutional_rows.append({"symbol":s,"institutional_history":ih,"tdcc_history":dh,**rotation_history[s]})
        inst = {str(r["symbol"]):r for r in calculate_institutional_rotation(institutional_rows)}
        for s in symbols:
            tf=tech_by[s]; ir=inst[s]
            m7=calculate_m7({k:tf[k] for k in ("PT","PV","MO","RS")} | {k:ir[k] for k in ("FI","IT","LH")})
            mhe=calculate_mhe({k:tf[k] for k in ("H5","H20","H60","H120")})
            hist=records_by[s]; tr=technical_record(hist,benches_asof[s])
            output[s].append({"trade_date":session,"M7":m7["m7_score"],"MHE":mhe["mhe_score"],
                "Rotation":ir["Rotation"],"RotationClass":calculate_rotation(ir["Rotation_inputs"])["rotation_state"],
                "close":float(hist[-1]["close"]),
                "technical_features":tf,"technical_record":tr,"stock_low_values":[{"trade_date":r["trade_date"],"low":float(r["low"])} for r in hist],
                "calculation_spec_version":"RATE-SPEC-20260919-004","source_type":"DERIVED_FROM_HISTORICAL_FEATURE_REPLAY"})
    return output
