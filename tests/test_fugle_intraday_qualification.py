"""Synthetic-only tests for Fugle free/basic intraday feasibility."""
from __future__ import annotations
from datetime import datetime, timezone
import io, json, unittest
from urllib.error import HTTPError

from src.provider_fugle_intraday_candidate import FugleDiagnosticError, qualify

NOW=datetime(2026,11,3,1,30,30,tzinfo=timezone.utc)
DATE="2026-11-03"

def binding():
    rows=[]
    for i in range(25): rows.append({"symbol":str(1000+i),"market":"TWSE"})
    for i in range(5): rows.append({"symbol":str(2000+i),"market":"TPEX"})
    return {"validation_status":"PASS","records":rows}

def quote(symbol,market="TWSE",stamp=1793669400000000):
    return {"symbol":symbol,"exchange":market,"date":DATE,"lastUpdated":stamp,"lastPrice":100.0,
            "total":{"tradeVolume":1000,"tradeValue":100000.0},"lastTrade":{"price":100.0}}

class Response:
    status=200
    def __init__(self,value): self.value=value
    def read(self): return json.dumps(self.value).encode()

class Provider:
    def __init__(self, mode=None): self.calls=[]; self.mode=mode
    def __call__(self, request, timeout=10):
        symbol=request.full_url.rsplit("/",1)[-1]
        self.calls.append((symbol,request.headers.get("X-api-key") or request.headers.get("X-Api-Key")))
        if self.mode==403: raise HTTPError(request.full_url,403,"Forbidden",{},io.BytesIO())
        if self.mode==429: raise HTTPError(request.full_url,429,"Too Many",{},io.BytesIO())
        market="TPEX" if symbol.startswith("2") else "TWSE"
        return Response(quote(symbol,market))

class FugleFreeDiagnosticTests(unittest.TestCase):
    def test_exact_30_dual_market_pass_is_still_not_production_eligible(self):
        p=Provider(); result=qualify("SECRET",binding(),trading_date=DATE,cadence="09:30",now_utc=NOW,opener=p)
        self.assertEqual(result["technical_validation_status"],"PASS")
        self.assertEqual(result["market_coverage"],"30/30")
        self.assertEqual(result["market_counts"],{"TWSE":25,"TPEX":5})
        self.assertEqual(result["network_requests"],30)
        self.assertEqual(result["automatic_retries"],0)
        self.assertFalse(result["production_eligible"])
        self.assertFalse(result["external_dependency_resolved"])
        self.assertNotIn("SECRET",json.dumps(result))

    def test_free_plan_403_and_rate_limit_429_fail_closed(self):
        with self.assertRaisesRegex(FugleDiagnosticError,"FREE_PLAN_NOT_AUTHORIZED"):
            qualify("x",binding(),trading_date=DATE,cadence="09:30",now_utc=NOW,opener=Provider(403))
        with self.assertRaisesRegex(FugleDiagnosticError,"FREE_PLAN_RATE_LIMIT"):
            qualify("x",binding(),trading_date=DATE,cadence="09:30",now_utc=NOW,opener=Provider(429))

    def test_missing_token_fails_before_network(self):
        p=Provider()
        with self.assertRaisesRegex(FugleDiagnosticError,"API_KEY_MISSING"):
            qualify("",binding(),trading_date=DATE,cadence="09:30",now_utc=NOW,opener=p)
        self.assertEqual(p.calls,[])

    def test_market_mismatch_freshness_and_schema_fail_closed(self):
        class Wrong(Provider):
            def __call__(self,request,timeout=10):
                symbol=request.full_url.rsplit("/",1)[-1]
                return Response(quote(symbol,"TWSE"))
        with self.assertRaisesRegex(FugleDiagnosticError,"MARKET_MISMATCH"):
            qualify("x",binding(),trading_date=DATE,cadence="09:30",now_utc=NOW,opener=Wrong())
        class Stale(Provider):
            def __call__(self,request,timeout=10):
                symbol=request.full_url.rsplit("/",1)[-1]
                market="TPEX" if symbol.startswith("2") else "TWSE"
                return Response(quote(symbol,market,1793668800000000))
        with self.assertRaisesRegex(FugleDiagnosticError,"FRESHNESS_FAIL"):
            qualify("x",binding(),trading_date=DATE,cadence="09:30",now_utc=NOW,opener=Stale())

    def test_binding_must_be_exact_25_plus_5(self):
        bad=binding(); bad["records"][0]["market"]="TPEX"
        with self.assertRaisesRegex(FugleDiagnosticError,"MARKET_COUNTS_INVALID"):
            qualify("x",bad,trading_date=DATE,cadence="09:30",now_utc=NOW,opener=Provider())

if __name__=="__main__": unittest.main()
