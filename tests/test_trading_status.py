import unittest
from src.sources.trading_status import map_trading_status

class TradingStatusTests(unittest.TestCase):
    def event(self, status, start="2026-09-15T09:00:00+08:00", end=None):
        return {"symbol":"2330","status":status,"effective_start":start,"effective_end":end,
                "source":"TWSE After-hours information Trading Securities Suspended",
                "source_timestamp":"2026-09-15T08:00:00+08:00","retrieval_timestamp":"2026-09-15T08:01:00+08:00","reason":"official event"}
    def test_mapping_states(self):
        base="2026-09-15T10:00:00+08:00"
        self.assertEqual(map_trading_status("2330",base,True,[self.event("SUSPENDED")])["trading_status"],"SUSPENDED")
        self.assertEqual(map_trading_status("2330",base,True,[self.event("RESTRICTED")])["trading_status"],"RESTRICTED")
        self.assertEqual(map_trading_status("2330",base,True,[])["trading_status"],"ACTIVE")
    def test_missing_lineage_fails(self):
        with self.assertRaises(ValueError): map_trading_status("2330","2026-09-15T10:00:00+08:00",True,[{"symbol":"2330","status":"SUSPENDED"}])
