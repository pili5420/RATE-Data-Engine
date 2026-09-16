"""Persistent official fundamental disclosure history."""
from __future__ import annotations
import hashlib, json
from pathlib import Path

class PersistentFundamentalStore:
    def __init__(self, root='data/production/fundamental'):
        self.root=Path(root); self.root.mkdir(parents=True,exist_ok=True)
    def _path(self,symbol): return self.root/(str(symbol)+'.json')
    def load(self,symbol):
        p=self._path(symbol); return json.loads(p.read_text(encoding='utf-8')) if p.exists() else {'revenue_yoy':[],'quarterly_eps':[]}
    def upsert(self,symbol,*,revenue_yoy,quarterly_eps):
        if len(revenue_yoy)<3: raise ValueError('DATA_INCOMPLETE:FUNDAMENTAL_REVENUE_HISTORY')
        if len(quarterly_eps)<8: raise ValueError('DATA_INCOMPLETE:FUNDAMENTAL_EPS_HISTORY')
        value={'symbol':str(symbol),'revenue_yoy':list(revenue_yoy)[-3:],'quarterly_eps':list(quarterly_eps)[-8:]}
        raw=json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode(); value['content_hash']=hashlib.sha256(raw).hexdigest(); self._path(symbol).write_text(json.dumps(value,ensure_ascii=False,sort_keys=True)+'\n',encoding='utf-8'); return value
