import unittest
from datetime import date, timedelta

from scripts.build_live_source_bundle import _t86_history


class FakeT86:
    def fetch_t86(self, trading_date):
        return {'raw_payload':{'data':[
          {'證券代號':'2330','外陸資買進股數(不含外資自營商)':'100','外陸資賣出股數(不含外資自營商)':'40','外陸資買賣超股數(不含外資自營商)':'60',
           '投信買進股數':'30','投信賣出股數':'10','投信買賣超股數':'20',
           '自營商買進股數(自行買賣)':'12','自營商賣出股數(自行買賣)':'7','自營商買賣超股數(自行買賣)':'5',
           '自營商買進股數(避險)':'8','自營商賣出股數(避險)':'3','自營商買賣超股數(避險)':'5'}]},'source_timestamp':trading_date+'T18:00:00Z'}


class T86StageHistoryAdapterTests(unittest.TestCase):
    def test_official_t86_dealer_subcategories_normalize_to_canonical_total(self):
        target=date(2026,9,18); stocks={'2330':[]}
        for i in range(26):
            day=(target-timedelta(days=25-i)).isoformat()
            stocks['2330'].append({'trade_date':day,'close':100.0,'turnover':100000.0})
        history=_t86_history(FakeT86(),['2330'],stocks,target.isoformat())['2330']
        self.assertEqual(len(history),26)
        self.assertEqual(history[-1]['foreign_net_shares'],60)
        self.assertEqual(history[-1]['investment_trust_net_shares'],20)
        self.assertEqual((history[-1]['dealer_buy'],history[-1]['dealer_sell'],history[-1]['dealer_net']),(20,10,10))


if __name__=='__main__': unittest.main()
