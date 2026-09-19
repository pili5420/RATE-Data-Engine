import unittest
from datetime import date, timedelta
from unittest.mock import patch

from src.institutional_history import (
    INSTITUTIONAL_HISTORY_MINIMUM, canonical_digest, fetch_t86_sessions,
    fetch_tpex_monthly_history, normalize_t86_response, valid_stock_session_dates,
)
from scripts.run_cer072_acceptance import _stable_digest, _tdcc_history, _verify_model_freeze


def _dates(count=26):
    out=[]; day=date(2026,8,1)
    while len(out)<count:
        if day.weekday()<5: out.append(day.isoformat())
        day += timedelta(days=1)
    return out


def _stock_rows(symbols, days):
    return {s:[{'trade_date':d,'close':100.0,'turnover':100000.0} for d in days] for s in symbols}


def _t86(day, symbols):
    fields=['證券代號','外陸資買進股數(不含外資自營商)','外陸資賣出股數(不含外資自營商)',
            '外陸資買賣超股數(不含外資自營商)','投信買進股數','投信賣出股數','投信買賣超股數']
    return {'diagnostics':{'http_status':200},'raw_payload':{'date':day.replace('-',''),
      'fields':fields,'data':[[s,'12','5','7','9','4','5'] for s in symbols]},'source_timestamp':'2026-09-18T09:00:00Z','content_hash':'abc'}


class CER072InstitutionalHistoryTests(unittest.TestCase):
    def test_minimum_is_26_sessions(self):
        self.assertEqual(INSTITUTIONAL_HISTORY_MINIMUM,26)

    def test_common_session_calendar_excludes_weekends_and_is_unique(self):
        days=_dates(); symbols=['2330','2317']
        rows=_stock_rows(symbols,days)
        self.assertEqual(valid_stock_session_dates(rows,symbols,limit=26),days)
        self.assertTrue(all(date.fromisoformat(d).weekday()<5 for d in days))

    def test_duplicate_stock_session_is_rejected(self):
        days=_dates(); rows=_stock_rows(['2330'],days); rows['2330'].append(dict(rows['2330'][0]))
        with self.assertRaisesRegex(ValueError,'DUPLICATE_OR_INVALID'):
            valid_stock_session_dates(rows,['2330'],limit=26)

    def test_t86_explicit_response_date_matches_requested_date(self):
        day=_dates()[0]; symbols=['2330']
        result=normalize_t86_response(_t86(day,symbols),day,_stock_rows(symbols,[day]),symbols)
        self.assertEqual(result['2330']['trading_date'],day)

    def test_t86_response_date_mismatch_fails(self):
        days=_dates(); symbols=['2330']; payload=_t86(days[0],symbols)
        with self.assertRaisesRegex(ValueError,'DATE_IDENTITY_MISMATCH'):
            normalize_t86_response(payload,days[1],_stock_rows(symbols,days),symbols)

    def test_t86_requires_all_fi_it_fields_and_arithmetic(self):
        day=_dates()[0]; symbols=['2330']; payload=_t86(day,symbols)
        payload['raw_payload']['data'][0][3]='99'
        with self.assertRaisesRegex(ValueError,'ARITHMETIC_MISMATCH'):
            normalize_t86_response(payload,day,_stock_rows(symbols,[day]),symbols)

    def test_t86_one_market_request_per_session_for_all_symbols(self):
        days=_dates(); symbols=['2330','2317']; stocks=_stock_rows(symbols,days)
        class Adapter:
            calls=[]
            def fetch_t86(self,day): self.calls.append(day); return _t86(day,symbols)
        adapter=Adapter(); result=fetch_t86_sessions(adapter,stocks,symbols,days)
        self.assertEqual(len(adapter.calls),26)
        self.assertEqual(result['request_count'],26)
        self.assertEqual(result['session_dates'],days)
        self.assertEqual([len(result['records'][s]) for s in symbols],[26,26])

    def test_t86_empty_response_does_not_count(self):
        days=_dates(27); symbols=['2330']; stocks=_stock_rows(symbols,days)
        class Adapter:
            def fetch_t86(self,day):
                payload=_t86(day,symbols)
                if day==days[-1]: payload['raw_payload']['data']=[]
                return payload
        result=fetch_t86_sessions(Adapter(),stocks,symbols,days)
        self.assertEqual(result['request_count'],27)
        self.assertEqual(result['empty_nontrading_dates'],[days[-1]])
        self.assertEqual(len(result['session_dates']),26)

    def test_tpex_monthly_requests_are_deduplicated_and_rows_date_bound(self):
        days=_dates(40); symbols=['6274']; stocks=_stock_rows(symbols,days)
        class Adapter:
            calls=[]
            def fetch_institutional_history(self,symbol,month):
                self.calls.append(month)
                rows=[]
                for d in days:
                    if d[:7].replace('-','')==month:
                        rows.append({'SecuritiesCompanyCode':'6274','Date':d.replace('-','/'),
                          'ForeignBuy':'12','ForeignSell':'5','ForeignNet':'7',
                          'InvestmentTrustBuy':'9','InvestmentTrustSell':'4','InvestmentTrustNet':'5'})
                return {'raw_payload':rows,'source_timestamp':'2026-09-18T09:00:00Z'}
        adapter=Adapter(); result=fetch_tpex_monthly_history(adapter,symbols,stocks,days[:26])
        self.assertEqual(adapter.calls,sorted({d[:7].replace('-','') for d in days[:26]}))
        self.assertEqual(result['monthly_request_deduplication'],'PASS')
        self.assertEqual(len(result['records']['6274']),26)

    def test_tpex_response_period_mismatch_fails(self):
        days=_dates(40); symbols=['6274']; stocks=_stock_rows(symbols,days)
        class Adapter:
            def fetch_institutional_history(self,symbol,month):
                return {'raw_payload':[{'SecuritiesCompanyCode':'6274','Date':'2026/09/01',
                  'ForeignBuy':'12','ForeignSell':'5','ForeignNet':'7','InvestmentTrustBuy':'9',
                  'InvestmentTrustSell':'4','InvestmentTrustNet':'5'}]}
        with self.assertRaisesRegex(ValueError,'PERIOD_MISMATCH'):
            fetch_tpex_monthly_history(Adapter(),symbols,stocks,days[:26])

    def test_prior_stage_identity_hash_is_deterministic(self):
        value={'prior_session':'2026-09-17','symbols':[{'symbol':'2330','previous_stage':'BUILD'}]}
        self.assertEqual(canonical_digest(value),canonical_digest(value))

    def test_prior_stage_package_hash_excludes_volatile_timestamps(self):
        a={'symbol':'2330','evidence':{'derived_value':50,'source_timestamp':'2026-09-18T01:00:00Z'}}
        b={'symbol':'2330','evidence':{'derived_value':50,'source_timestamp':'2026-09-18T02:00:00Z'}}
        self.assertEqual(_stable_digest(a),_stable_digest(b))

    def test_frozen_model_and_spec_files_match_accepted_hashes(self):
        self.assertEqual(_verify_model_freeze()['status'],'PASS')

    def test_tdcc_history_is_filtered_as_of_and_uses_published_holder_tiers(self):
        payload=[]
        for period in ('2026/09/04','2026/09/11','2026/09/18','2026/09/25'):
            payload.extend([
              {'證券代號':'2330','資料日期':period,'持股分級':'11','占集保庫存數比例%':'20.0'},
              {'證券代號':'2330','資料日期':period,'持股分級':'12','占集保庫存數比例%':'30.0'},
              {'證券代號':'2330','資料日期':period,'持股分級':'16','占集保庫存數比例%':'10.0'},
            ])
        with patch('scripts.run_cer072_acceptance.TDCCAdapter.fetch',return_value={'raw_payload':payload,'source_timestamp':'2026-09-18T10:00:00Z'}):
            history,_=_tdcc_history(['2330'],'2026-09-18')
        self.assertEqual([r['period_end'] for r in history['2330']],['2026-09-04','2026-09-11','2026-09-18'])
        self.assertEqual([r['holder_pct_400'] for r in history['2330']],[40.0,40.0,40.0])


if __name__=='__main__': unittest.main()
