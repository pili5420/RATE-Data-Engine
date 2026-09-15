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
