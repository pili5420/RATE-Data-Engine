import unittest
from datetime import date, timedelta
from unittest.mock import patch

from src.institutional_history import (
    INSTITUTIONAL_HISTORY_MINIMUM, canonical_digest, fetch_t86_sessions,
    fetch_tpex_monthly_history, fetch_tpex_daily_sessions, normalize_tpex_daily_response,
    normalize_t86_response, valid_stock_session_dates,
)
from src.sources.tpex import (TPExAdapter, TPExDailyTransportError,
                              _body_prefix_class, _resilient_tpex_daily_json)
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

    @staticmethod
    def _tpex_daily(day, symbols):
        fields = ['代號','外資及陸資(不含外資自營商)買進股數','外資及陸資(不含外資自營商)賣出股數',
                  '外資及陸資(不含外資自營商)買賣超股數','外資自營商買進股數',
                  '投信買進股數','投信賣出股數','投信買賣超股數']
        data = [[s,'12','5','7','1000','9','4','5'] for s in symbols]
        payload = {'tables':[{'date':f'{int(day[:4])-1911:03d}/{day[5:7]}/{day[8:]}',
                              'title':'三大法人買賣明細資訊','fields':fields,'data':data}]}
        return {'raw_payload':payload,'diagnostics':{'http_status':200,'content_type':'application/json',
            'record_count':len(data),'response_date_location':'tables[0].date','body_sha256':'digest'},
            'source_timestamp':'2026-09-18T09:00:00Z','content_hash':'digest'}

    def test_legacy_adapter_route_is_disabled(self):
        with self.assertRaisesRegex(RuntimeError,'LEGACY_INSTITUTIONAL_ROUTE_DISABLED'):
            TPExAdapter().fetch_institutional_history('', '202609')

    def test_current_dailytrade_schema_maps_by_field_names_and_excludes_dealer(self):
        day='2026-09-18'; symbols=['6274']; stocks=_stock_rows(symbols,[day])
        parsed=normalize_tpex_daily_response(self._tpex_daily(day,symbols),day,stocks,symbols)
        row=parsed['records']['6274']
        self.assertEqual(row['foreign_buy'],12)
        self.assertEqual(row['foreign_net'],7)
        self.assertNotEqual(row['foreign_buy'],1012)
        self.assertEqual(parsed['response_date'],day)
        self.assertEqual(parsed['field_mapping']['foreign_ex_dealer.buy'],
                         '外資及陸資(不含外資自營商)買進股數')

    def test_roc_response_date_normalizes_and_requires_exact_identity(self):
        day='2026-09-18'; symbols=['6274']; stocks=_stock_rows(symbols,[day])
        payload=self._tpex_daily(day,symbols)
        self.assertEqual(normalize_tpex_daily_response(payload,day,stocks,symbols)['response_date'],day)
        with self.assertRaisesRegex(ValueError,'RESPONSE_DATE_MISMATCH'):
            normalize_tpex_daily_response(payload,'2026-09-17',stocks,symbols)

    def test_aggregate_foreign_field_cannot_substitute_for_ex_dealer_fi(self):
        day='2026-09-18'; symbols=['6274']; payload=self._tpex_daily(day,symbols)
        table=payload['raw_payload']['tables'][0]
        table['fields']=[x.replace('(不含外資自營商)','合計') for x in table['fields']]
        with self.assertRaisesRegex(ValueError,'REQUIRED_FIELDS_MISSING'):
            normalize_tpex_daily_response(payload,day,_stock_rows(symbols,[day]),symbols)

    def test_foreign_arithmetic_mismatch_fails_closed(self):
        day='2026-09-18'; symbols=['6274']; payload=self._tpex_daily(day,symbols)
        payload['raw_payload']['tables'][0]['data'][0][3]='8'
        with self.assertRaisesRegex(ValueError,'FOREIGN_ARITHMETIC_MISMATCH'):
            normalize_tpex_daily_response(payload,day,_stock_rows(symbols,[day]),symbols)

    def test_investment_trust_arithmetic_mismatch_fails_closed(self):
        day='2026-09-18'; symbols=['6274']; payload=self._tpex_daily(day,symbols)
        payload['raw_payload']['tables'][0]['data'][0][7]='6'
        with self.assertRaisesRegex(ValueError,'IT_ARITHMETIC_MISMATCH'):
            normalize_tpex_daily_response(payload,day,_stock_rows(symbols,[day]),symbols)

    def test_daily_transport_posts_roc_date_and_caches_one_market_request(self):
        adapter=TPExAdapter()
        daily=self._tpex_daily('2026-09-18',['6274'])
        with patch('src.sources.tpex._resilient_tpex_daily_json',return_value={
                'payload':daily['raw_payload'],'body_sha256':'digest','diagnostics':daily['diagnostics']}) as transport:
            first=adapter.fetch_institutional_daily('2026-09-18')
            second=adapter.fetch_institutional_daily('2026-09-18')
        self.assertEqual(transport.call_count,1)
        self.assertEqual(first['request_params']['date'],'115/09/18')
        self.assertTrue(second['diagnostics']['cache_hit'])

    def test_three_probes_are_reused_and_each_session_requested_once_for_five_symbols(self):
        days=['2026-08-14','2026-08-17','2026-08-18']
        while len(days)<26:
            from datetime import date, timedelta
            d=date.fromisoformat(days[-1])+timedelta(days=1)
            while d.weekday()>=5: d+=timedelta(days=1)
            days.append(d.isoformat())
        symbols=['6274','3081','6187','6510','3227']; stocks=_stock_rows(symbols,days)
        class Adapter:
            def __init__(self): self.calls=[]
            def fetch_institutional_daily(self,day):
                self.calls.append(day)
                data=CER072InstitutionalHistoryTests._tpex_daily(day,symbols)
                return {'raw_payload':data['raw_payload'],'diagnostics':data['diagnostics'],
                        'source_timestamp':data['source_timestamp'],'content_hash':'digest','endpoint':'official',
                        'request_params':{'date':day}}
        adapter=Adapter(); contract=[]; evidence=[]
        result=fetch_tpex_daily_sessions(adapter,symbols,stocks,days,probe_dates=days[:3],
            evidence_writer=lambda v,daily=False: (evidence if daily else contract).append(v))
        self.assertEqual(len(adapter.calls),26)
        self.assertEqual(len(set(adapter.calls)),26)
        self.assertEqual(result['session_calendar'],'26/26')
        self.assertEqual(result['session_count_by_symbol'],{s:26 for s in symbols})
        self.assertEqual(result['daily_request_deduplication'],'PASS')
        self.assertEqual(result['valid_responses'],26)

    def test_daily_html_and_json_decode_failure_diagnostics_are_classified(self):
        self.assertEqual(_body_prefix_class(b'<!doctype html><html>challenge</html>'),'HTML')
        class Response:
            status=200
            headers={'Content-Type':'text/html','Content-Length':'37','Date':'Fri, 18 Sep 2026 08:00:00 GMT'}
            def __enter__(self): return self
            def __exit__(self,*args): return False
            def read(self): return b'<!doctype html><html>challenge</html>'
            def geturl(self): return 'https://www.tpex.org.tw/www/zh-tw/insti/dailyTrade'
        class Opener:
            def open(self,*args,**kwargs): return Response()
        with patch('src.sources.tpex.build_opener',return_value=Opener()):
            with self.assertRaises(TPExDailyTransportError) as caught:
                _resilient_tpex_daily_json('https://www.tpex.org.tw/www/zh-tw/insti/dailyTrade',{'date':'115/09/18'},retries=3)
        error=caught.exception
        self.assertEqual(error.diagnostics['http_status'],200)
        self.assertEqual(error.diagnostics['content_type'],'text/html')
        self.assertEqual(error.diagnostics['body_prefix_class'],'HTML')
        self.assertEqual(error.diagnostics['json_decode_status'],'FAIL:JSONDecodeError')
        self.assertEqual(error.diagnostics['body_prefix_class'],'HTML')

    def test_daily_missing_required_value_never_becomes_zero(self):
        day='2026-09-18'; symbols=['6274']; payload=self._tpex_daily(day,symbols)
        payload['raw_payload']['tables'][0]['data'][0][1]='-'
        with self.assertRaisesRegex(ValueError,'MISSING_REQUIRED_INSTITUTIONAL_FIELD'):
            normalize_tpex_daily_response(payload,day,_stock_rows(symbols,[day]),symbols)

    def test_daily_missing_symbol_coverage_fails(self):
        day='2026-09-18'; symbols=['6274','3081']; payload=self._tpex_daily(day,['6274'])
        with self.assertRaisesRegex(ValueError,'SYMBOLS_MISSING'):
            normalize_tpex_daily_response(payload,day,_stock_rows(symbols,[day]),symbols)


if __name__=='__main__': unittest.main()
