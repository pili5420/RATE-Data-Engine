from __future__ import annotations
import json

REQUIRED=('PT','PV','MO','FI','IT','LH','RS','H5','H20','H60','H120','RS_CHANGE','VOL_CHANGE','SMART_MONEY','MOMENTUM_CHANGE','FC','Fundamental','RelativeStrength','Liquidity')
def build_live_decision_records(production_sources,trading_date,universe):
    records=[]; evidence=[]; errors=[]
    for symbol in universe:
        source=production_sources.get(str(symbol),{})
        missing=[x for x in REQUIRED if x not in source]
        if missing: errors.append({'symbol':str(symbol),'calculation_status':'DATA_INCOMPLETE','missing_components':missing}); continue
        records.append(source); evidence.append({'symbol':str(symbol),'features':{x:{'raw_values':source[x],'derived_value':source[x],'calculation_status':'PASS'} for x in REQUIRED},'trading_date':trading_date})
    return {'decision_records':records,'feature_evidence':evidence,'feature_validation':{'status':'PASS' if records and not errors else 'BLOCKED:PRODUCTION_DECISION_INPUT_UNAVAILABLE','errors':errors}}
