from __future__ import annotations
from .feature_math import pctl
def sma(xs,n):
 if len(xs)<n: raise ValueError(f'DATA_INCOMPLETE:HISTORY_{n}')
 return sum(xs[-n:])/n
def ema(xs,n):
 if len(xs)<n: raise ValueError(f'DATA_INCOMPLETE:HISTORY_{n}')
 e=sum(xs[:n])/n; a=2/(n+1)
 for x in xs[n:]: e=a*x+(1-a)*e
 return e
def rsi14(xs):
 if len(xs)<15: raise ValueError('DATA_INCOMPLETE:HISTORY_14')
 gains=[];losses=[]
 for a,b in zip(xs[-15:-1],xs[-14:]): gains.append(max(b-a,0));losses.append(max(a-b,0))
 g=sum(gains)/14;l=sum(losses)/14
 if l==0:return 100.0 if g else 50.0
 return 100-100/(1+g/l)
def returns(xs,n):
 if len(xs)<=n: raise ValueError(f'DATA_INCOMPLETE:HISTORY_{n}')
 return xs[-1]/xs[-1-n]-1
def technical_record(rows,bench):
 rows=sorted(rows,key=lambda r:r['trade_date']); dates={r['trade_date']:r for r in bench}; aligned=[(r,dates[r['trade_date']]) for r in rows if r['trade_date'] in dates]
 if len(aligned)<120: raise ValueError('DATA_INCOMPLETE:BENCHMARK_ALIGNMENT')
 c=[r['close'] for r,b in aligned];v=[r['volume'] for r,b in aligned];t=[r['turnover'] for r,b in aligned];bc=[b['close'] for r,b in aligned]
 ma20=sma(c,20);ma60=sma(c,60);ma120=sma(c,120); rv20=returns(c,20); rs20=returns(c,20)-returns(bc,20);rs60=returns(c,60)-returns(bc,60);rs120=returns(c,120)-returns(bc,120)
 macd=ema(c,12)-ema(c,26); sig=ema([macd],9) if len(c)<34 else ema([ema(c[:i+1],12)-ema(c[:i+1],26) for i in range(25,len(c))],9); hist=macd-sig
 return {'MA20':ma20,'MA60':ma60,'MA120':ma120,'RET5':returns(c,5),'RET20':rv20,'RET60':returns(c,60),'RET120':returns(c,120),'AVG_VOLUME_5':sum(v[-5:])/5,'AVG_VOLUME_20':sum(v[-20:])/20,'AVG_TURNOVER_20':sum(t[-20:])/20,'RSI14':rsi14(c),'EMA12':ema(c,12),'EMA26':ema(c,26),'MACD':macd,'MACD_SIGNAL9':sig,'MACD_HISTOGRAM':hist,'EXCESS_RET20':rs20,'EXCESS_RET60':rs60,'EXCESS_RET120':rs120}
def compute_scores(records, benchmark):
 tech=[technical_record(r,benchmark) for r in records]; n=len(tech)
 if n<20: raise ValueError('DATA_INCOMPLETE:PERCENTILE_UNIVERSE_TOO_SMALL')
 bclose=[x['close'] for x in benchmark]; ex5=[returns([x['close'] for x in r],5)-returns(bclose,5) for r in records]
 for i,(r,t) in enumerate(zip(records,tech)):
  c=r[-1]['close']; old=[x['close'] for x in r[:-5]]; pt=.6*(25*(c>t['MA20'])+35*(c>t['MA60'])+40*(c>t['MA120']))+.4*(50*(t['MA20']>sma(old,20))+30*(t['MA60']>sma(old,60))+20*(t['MA120']>sma(old,120)))
  total=sum(x['volume'] for x in r[-20:]); ups=sum(x['volume'] for a,x in zip(r[-20:-1],r[-19:]) if x['close']>a['close']); ratios=[z['AVG_VOLUME_5']/z['AVG_VOLUME_20'] for z in tech]; pv=.7*100*ups/total+.3*pctl(t['AVG_VOLUME_5']/t['AVG_VOLUME_20'],ratios)
  macn=t['MACD_HISTOGRAM']/c; mo=.4*t['RSI14']+.3*pctl(t['RET20'],[z['RET20'] for z in tech])+.3*pctl(macn,[z['MACD_HISTOGRAM']/records[j][-1]['close'] for j,z in enumerate(tech)])
  rs=.4*pctl(t['EXCESS_RET20'],[z['EXCESS_RET20'] for z in tech])+.35*pctl(t['EXCESS_RET60'],[z['EXCESS_RET60'] for z in tech])+.25*pctl(t['EXCESS_RET120'],[z['EXCESS_RET120'] for z in tech])
  tf={'PT':round(pt,2),'PV':round(pv,2),'MO':round(mo,2),'RS':round(rs,2),'RelativeStrength':round(rs,2),'H5':round(.5*pctl(t['RET5'],[z['RET5'] for z in tech])+.5*pctl(ex5[i],ex5),2),'H20':round(.5*pctl(t['RET20'],[z['RET20'] for z in tech])+.5*pctl(t['EXCESS_RET20'],[z['EXCESS_RET20'] for z in tech]),2),'H60':round(.5*pctl(t['RET60'],[z['RET60'] for z in tech])+.5*pctl(t['EXCESS_RET60'],[z['EXCESS_RET60'] for z in tech]),2),'H120':round(.5*pctl(t['RET120'],[z['RET120'] for z in tech])+.5*pctl(t['EXCESS_RET120'],[z['EXCESS_RET120'] for z in tech]),2),'Liquidity':round(pctl(t['AVG_TURNOVER_20'],[z['AVG_TURNOVER_20'] for z in tech]),2)}
  r['technical_features']=tf; r['feature_evidence']={k:{'symbol':r.get('symbol'),'feature_name':k,'calculation_spec_version':'RATE-DFCS-V1.0','raw_input_values':t,'derived_value':v,'calculation_status':'PASS'} for k,v in tf.items()}
 return records
