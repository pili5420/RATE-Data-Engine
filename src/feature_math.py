from __future__ import annotations
def pctl(value, universe):
    xs=sorted(float(x) for x in universe); n=len(xs)
    if n<20: raise ValueError('DATA_INCOMPLETE:PERCENTILE_UNIVERSE_TOO_SMALL')
    v=float(value); ranks=[i+1 for i,x in enumerate(xs) if x==v]
    if not ranks: ranks=[next(i+1 for i,x in enumerate(xs) if x>v)]
    return round(100*(sum(ranks)/len(ranks)-1)/(n-1),2)
