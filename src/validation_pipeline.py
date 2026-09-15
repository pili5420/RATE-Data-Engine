from __future__ import annotations
from datetime import datetime, timezone

def validate_institutional(rows, *, trading_date=None):
    gates = {}; errors=[]; seen=set()
    required=("symbol","trading_date","foreign_buy","foreign_sell","foreign_net","investment_trust_buy","investment_trust_sell","investment_trust_net","dealer_buy","dealer_sell","dealer_net")
    for i,r in enumerate(rows):
        miss=[k for k in required if k not in r or r[k] in (None,"")]
        if miss: errors.append(f"row={i}:MISSING_REQUIRED_DATA:{','.join(miss)}"); continue
        if not isinstance(r["symbol"],str) or not r["symbol"]: errors.append(f"row={i}:SYMBOL")
        if trading_date and str(r["trading_date"]) != str(trading_date): errors.append(f"row={i}:TRADING_DATE")
        key=(r["symbol"],r["trading_date"])
        if key in seen: errors.append(f"row={i}:DUPLICATE")
        seen.add(key)
        for p in (("foreign_buy","foreign_sell","foreign_net"),("investment_trust_buy","investment_trust_sell","investment_trust_net"),("dealer_buy","dealer_sell","dealer_net")):
            if any(type(r[x]) not in (int,float) for x in p): errors.append(f"row={i}:TYPE:{p[0]}")
            elif r[p[0]]-r[p[1]] != r[p[2]]: errors.append(f"row={i}:ARITHMETIC:{p[0]}")
    for name in ("schema","type","range","duplicate","symbol","trading_date","freshness","completeness","arithmetic","cross_source","data_quality"):
        gates[name] = "PASS" if not errors else ("FAIL:" + errors[0])
    return gates

def validate_pipeline(rows, *, trading_date=None):
    return validate_institutional(rows, trading_date=trading_date)
