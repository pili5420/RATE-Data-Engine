from __future__ import annotations
import argparse,json
from pathlib import Path
def build_query_universe(obj):
 vals=[]; memberships={}; labels={'short_term_top30':'TOP30','short_top30':'TOP30','roy_portfolio':'ROY_PORTFOLIO','required_benchmarks':'BENCHMARK','explicit_production_watchlist':'WATCHLIST'}
 for k in labels:
  for x in obj.get(k,[]):
   s=x.get('symbol') if isinstance(x,dict) else x
   if s: memberships.setdefault(str(s),[]).append(labels[k]); vals.append(str(s))
 return [{'symbol':s,'source_membership':sorted(set(memberships[s]))} for s in dict.fromkeys(vals)]
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--state',required=True); ap.add_argument('--output',default='artifacts/PHASE_B_QUERY_UNIVERSE.json'); a=ap.parse_args(); obj=json.loads(Path(a.state).read_text(encoding='utf-8')); vals=[]; memberships={}; labels={'short_term_top30':'TOP30','short_top30':'TOP30','roy_portfolio':'ROY_PORTFOLIO','required_benchmarks':'BENCHMARK','explicit_production_watchlist':'WATCHLIST'}
 for k in ('short_term_top30','short_top30','roy_portfolio','required_benchmarks','explicit_production_watchlist'):
  for x in obj.get(k,[]):
   s=x.get('symbol') if isinstance(x,dict) else x
   if s:
    s=str(s); memberships.setdefault(s,[]).append(labels[k]);
    if s not in vals: vals.append(s)
 universe=build_query_universe(obj); out={'artifact':'PHASE_B_QUERY_UNIVERSE','source_state':obj.get('current_state_id'),'symbols':universe,'record_count':len(universe),'validation_status':'PASS' if universe else 'BLOCKED:EMPTY_QUERY_UNIVERSE'}; Path(a.output).write_text(json.dumps(out,indent=2)+'\n',encoding='utf-8'); print(json.dumps(out,indent=2)); return 0
if __name__=='__main__': raise SystemExit(main())
