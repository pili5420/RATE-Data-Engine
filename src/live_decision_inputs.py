from __future__ import annotations
import json

TECHNICAL_REQUIRED=('PT','PV','MO','RS','H5','H20','H60','H120','RelativeStrength','Liquidity')
REQUIRED=TECHNICAL_REQUIRED
def build_live_decision_records(production_sources,trading_date,universe):
    records=[]; evidence=[]; errors=[]
    for symbol in universe:
        source=production_sources.get(str(symbol),{})
        tf=source.get('technical_features', source)
        missing=[x for x in TECHNICAL_REQUIRED if x not in tf]
        if missing: errors.append({'symbol':str(symbol),'calculation_status':'DATA_INCOMPLETE','missing_components':missing}); continue
        record={'symbol':str(symbol),
                'M7_inputs':{k:tf[k] for k in ('PT','PV','MO','RS')},
                'MHE_inputs':{k:tf[k] for k in ('H5','H20','H60','H120')},
                'RelativeStrength':tf['RelativeStrength'],
                'Liquidity':tf['Liquidity'],
                'Fundamental':source.get('Fundamental'),
                'Rotation_inputs':source.get('Rotation_inputs'),
                'SmartMoney_inputs':source.get('SmartMoney_inputs'),
                'Stage_inputs':source.get('Stage_inputs'),
                'Stage_evidence':source.get('Stage_evidence'),
                'feature_lineage':source.get('feature_lineage')}
        for key in ('FI', 'IT', 'LH'):
            if key in source:
                record['M7_inputs'][key] = source[key]
        if source.get('SmartMoney_inputs') is not None:
            record['SmartMoney_inputs'] = source['SmartMoney_inputs']
            record['SMART_MONEY'] = source.get('SMART_MONEY')
        if source.get('Rotation_inputs') is not None:
            record['Rotation_inputs'] = source['Rotation_inputs']
            record['Rotation'] = source.get('Rotation')
        records.append(record); evidence.append({'symbol':str(symbol),'features':{x:{'raw_values':tf[x],'derived_value':tf[x],'calculation_status':'PASS'} for x in TECHNICAL_REQUIRED},'trading_date':trading_date})
    return {'decision_records':records,'feature_evidence':evidence,'feature_validation':{'status':'PASS' if records and not errors else 'BLOCKED:PRODUCTION_DECISION_INPUT_UNAVAILABLE','errors':errors}}
