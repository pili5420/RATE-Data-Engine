from __future__ import annotations
from .feature_math import pctl
SPEC_VERSION='RATE-FUND-V1.0'
def calculate_fundamental(rows):
    if len(rows)<20: raise ValueError('DATA_INCOMPLETE:PERCENTILE_UNIVERSE_TOO_SMALL')
    for r in rows:
        if len(r.get('revenue_yoy',[]))<3: r['_error']='DATA_INCOMPLETE:FUNDAMENTAL_REVENUE_HISTORY'; continue
        if len(r.get('quarterly_eps',[]))<8: r['_error']='DATA_INCOMPLETE:FUNDAMENTAL_EPS_HISTORY'; continue
        r['_rev_raw']=sum(r['revenue_yoy'][:3])/3; r['_eps_ttm']=sum(r['quarterly_eps'][:4]); r['_eps_prior']=sum(r['quarterly_eps'][4:8]); r['_eps_delta']=r['_eps_ttm']-r['_eps_prior']
    valid=[r for r in rows if '_error' not in r]
    if not valid: return []
    for r in valid:
        r['Fundamental']=round(.5*pctl(r['_rev_raw'],[x['_rev_raw'] for x in valid])+.3*pctl(r['_eps_delta'],[x['_eps_delta'] for x in valid])+.2*pctl(r['_eps_ttm'],[x['_eps_ttm'] for x in valid]),2); r['calculation_spec_version']=SPEC_VERSION; r['calculation_status']='PASS'
    return valid
