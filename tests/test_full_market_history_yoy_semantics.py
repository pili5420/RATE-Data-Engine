"""Approved history-only semantics; engineering fixtures grant no Production credit."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import URLError

from scripts import bootstrap_full_market_history as cli
from src import full_market_history as h
from src import full_market_history_acquisition as a
from src.sources.fundamental_history import (EPSPeriodNotAvailable, MOPSHistoricalFundamentalAdapter, FundamentalHistoryStoreV2,
    _eps_official_no_data, _warmup_revenue_rows, validate_revenue_semantics)
from src.sources.mops_raw_evidence import load_response, verify_record
from tests.test_full_market_history import cfg, material, plan
from tests.test_warmup_run1_defects import OfficialArchiveResponse


def archive(rows=(('1000', '', '0', '0'),), month=8, market='TWSE', report='115/10/01'):
    heading = ('\u4e0a\u5e02' if market == 'TWSE' else '\u4e0a\u6ac3') + f'\u516c\u53f8115\u5e74{month}\u6708\u4efd(\u7d2f\u8a08\u8207\u7576\u6708)\u71df\u696d\u6536\u5165\u7d71\u8a08\u8868'
    header = '<tr><th>\u516c\u53f8\u4ee3\u865f</th><th>\u516c\u53f8\u540d\u7a31</th><th>\u7576\u6708\u71df\u6536</th><th>\u53bb\u5e74\u7576\u6708\u71df\u6536</th><th>\u53bb\u5e74\u540c\u6708\u589e\u6e1b(%)</th></tr>'
    body = ''.join(f'<tr><td>{s}</td><td>Engineering</td><td>{current}</td><td>{prior}</td><td>{yoy}</td></tr>' for s,yoy,current,prior in rows)
    return f'<html><font size="5">{heading}</font><div>\u51fa\u8868\u65e5\u671f\uff1a{report}</div><table>{header}{body}</table></html>'


class YoYHistorySemanticsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='rate-yoy-engineering-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.contract_patch = patch('src.full_market_history.contract', side_effect=cfg)
        self.contract_patch.start()
        self.addCleanup(self.contract_patch.stop)
        self.plan = plan()

    def adapter(self, html, *, root=None, final=None, status=200):
        self.last_body = html.encode('utf-8')
        def opener(request, timeout):
            response = OfficialArchiveResponse(html, final or request.full_url)
            response.status = status
            return response
        return MOPSHistoricalFundamentalAdapter(opener=opener, min_interval_seconds=0,
            warmup_evidence_root=root or self.root / 'evidence',
            evidence_context={'plan_id': self.plan['plan_id'], 'acquisition_runtime_authority': self.plan['runtime_authority']})

    def record(self, **kwargs):
        source = self.adapter(archive(**kwargs))
        rows = source.fetch_revenue_period('TWSE', '2026-08')
        return source, rows

    def test_blank_zero_base_is_null_valid_observation_not_zero(self):
        for current in ('0', '100', '1,000'):
            with self.subTest(current=current):
                source, rows = self.record(rows=(('1000', '&nbsp;', current, '0'),))
                self.assertEqual(len(rows), 1)
                row = rows[0]
                self.assertIsNone(row['revenue_yoy'])
                self.assertEqual(row['revenue_yoy_status'], 'UNDEFINED_ZERO_BASE')
                self.assertEqual(row['official_raw_yoy'], '')
                self.assertEqual(row['current_month_revenue'], float(current.replace(',', '')))
                self.assertFalse(row['fallback_used'])
                self.assertEqual(source.row_failures, [])
                FundamentalHistoryStoreV2._validate_revenue_event(row)
                verify_record(self.root / 'evidence', row, self.plan, 'revenue')

    def test_strict_numeric_failures_are_row_level_never_valid_undefined(self):
        cases = [('', '10', '1'), ('', '10', ''), ('', '10', 'bad'), ('', '', '0'), ('', 'bad', '0'),
                 ('--', '10', '0'), ('N/A', '10', '0'), ('nan', '10', '0'), ('inf', '10', '0'),
                 ('', 'nan', '0'), ('', '10', 'inf'), ('', '10%', '0'), ('', '10', '0%'),
                 ('', '10', '1e-400'), ('', '1e-400', '0')]
        for yoy,current,prior in cases:
            with self.subTest(yoy=yoy,current=current,prior=prior):
                source, rows = self.record(rows=(('1000', yoy, current, prior),))
                self.assertEqual(rows, [])
                self.assertEqual(len(source.row_failures), 1)
                failure = source.row_failures[0]
                self.assertEqual(failure['symbol'], '1000')
                self.assertEqual(failure['validation_status'], 'FAIL_CLOSED')
                self.assertNotEqual(failure.get('revenue_yoy_status'), 'UNDEFINED_ZERO_BASE')

    def test_numeric_yoy_unchanged_and_legacy_path_remains_strict(self):
        source, rows = self.record(rows=(('1000', '12.30', '1123', '1000'),))
        self.assertEqual(rows[0]['revenue_yoy'], 12.3)
        self.assertEqual(rows[0]['revenue_yoy_status'], 'VALID_NUMERIC')
        html = archive()
        legacy = MOPSHistoricalFundamentalAdapter(opener=lambda req,timeout: OfficialArchiveResponse(html, req.full_url), min_interval_seconds=0)
        with self.assertRaisesRegex(ValueError, 'FUNDAMENTAL_NUMERIC_MISSING'):
            legacy.fetch_revenue_period('TWSE', '2026-08')

    def test_status_null_coercion_tamper_and_missing_evidence_are_rejected(self):
        _, rows = self.record()
        for key,value in [('revenue_yoy', 0), ('revenue_yoy_status','VALID_NUMERIC'), ('prior_year_same_month_revenue',1),
                          ('official_raw_yoy','N/A'), ('current_month_revenue', True), ('fallback_used',True),
                          ('normalization_version','UNKNOWN'), ('final_url','https://unauthorized.test'),
                          ('market','TPEX'), ('period_identity_evidence',{}), ('raw_response_reference',None)]:
            row = {**rows[0], key:value}
            with self.subTest(key=key), self.assertRaises((ValueError,RuntimeError)):
                FundamentalHistoryStoreV2._validate_revenue_event(row)
        old = material(self.plan)['fundamental']['revenue'][0]
        with self.assertRaisesRegex(RuntimeError, 'UNVERIFIED_REVENUE_EVENT:revenue_yoy'):
            FundamentalHistoryStoreV2._validate_revenue_event({**old,'revenue_yoy':None})
        with self.assertRaisesRegex(RuntimeError, 'UNVERIFIED_REVENUE_EVENT:revenue_yoy'):
            FundamentalHistoryStoreV2._validate_revenue_event({**old,'revenue_yoy':''})
        missing = {k:v for k,v in rows[0].items() if k!='revenue_yoy'}
        with self.assertRaisesRegex(ValueError,'FUNDAMENTAL_NUMERIC_MISSING'):
            FundamentalHistoryStoreV2._validate_revenue_event(missing)

    def test_undefined_store_persist_reload_revision_identity_and_asof_unchanged(self):
        _, rows = self.record()
        store = FundamentalHistoryStoreV2(self.root / 'store')
        saved = store.upsert(rows, [])
        self.assertIsNone(saved['revenue_events'][0]['revenue_yoy'])
        self.assertIsNone(store.load()['revenue_events'][0]['revenue_yoy'])
        selected = store.select_asof(saved, ['1000'], '2026-10-05')
        self.assertIsNone(selected['1000']['revenue']['2026-08']['revenue_yoy'])
        before = store.select_asof(saved, ['1000'], '2026-09-30')
        self.assertEqual(before['1000']['revenue'], {})
        self.assertEqual(store.upsert(rows, [])['_last_upsert_summary']['inserted_revenue_events'], 0)

    def test_undefined_observations_count_as_complete_without_shrinking_coverage(self):
        root = self.root / 'coverage'
        m = material(self.plan)
        rev = []
        for month in (6,7,8):
            source = self.adapter(archive(month=month), root=root)
            rev.extend(source.fetch_revenue_period('TWSE', f'2026-{month:02d}'))
        m['fundamental']['revenue'] = rev
        self.assertEqual(h.validate_symbol(m,self.plan,'1000','TWSE',evidence_root=root)['revenue_periods'],3)
        h.persist_symbol(root,m,self.plan,'1000','TWSE')
        restored, _ = h.load_checkpoint(root,self.plan,'1000','TWSE')
        self.assertTrue(all(r['revenue_yoy'] is None for r in restored['fundamental']['revenue']))
        self.assertEqual(h.aggregate(root,self.plan)['complete_symbols'],1)
        self.assertEqual(h.aggregate(root,self.plan)['validation_status'],'FAIL_CLOSED')
        self.assertEqual(h.contract()['expected_market_counts'],{'TWSE':20,'TPEX':20})

    def test_unrelated_valid_rows_survive_invalid_company_row(self):
        source, rows = self.record(rows=(('1000','','10','1'),('1002','10','110','100'),('1004','','20','0')))
        self.assertEqual([r['symbol'] for r in rows],['1002','1004'])
        self.assertEqual([r['symbol'] for r in source.row_failures],['1000'])
        reports = list((self.root/'evidence/reports/fundamental_rows').glob('*.json'))
        self.assertEqual(len(reports),1)
        self.assertEqual(json.loads(reports[0].read_bytes())['failures'][0]['symbol'],'1000')

    def test_invalid_row_blocks_only_affected_shard_symbol_no_exclusion(self):
        shard = self.plan['shards'][0]
        bad = shard['symbols'][0]
        fundamentals = {s:{'failures':[]} for s in shard['symbols']}
        fundamentals[bad]['failures'] = [{'symbol':bad,'reason':'FUNDAMENTAL_NUMERIC_MISSING','scope':'ROW'}]
        with patch.object(a,'acquire_fundamentals',return_value=fundamentals), patch.object(a,'acquire_symbol',side_effect=lambda s,m,*args:material(self.plan,s,m)) as fetch:
            result = a.acquire_shard(self.plan,shard['shard_id'],self.root/'durable',self.root/'out',authority=self.plan['runtime_authority'])
        self.assertEqual([r['symbol'] for r in result['failed_symbols']],[bad])
        self.assertEqual(len(result['completed_symbols']),len(shard['symbols'])-1)
        self.assertEqual(fetch.call_count,len(shard['symbols'])-1)
        self.assertEqual(result['validation_status'],'FAIL_CLOSED')
        self.assertFalse(result['fallback_used'])
        self.assertFalse((self.root/'out/snapshots').exists())

    def test_market_level_transport_failure_still_marks_market_source_not_company_defect(self):
        shard = self.plan['shards'][0]
        with patch.object(a,'acquire_fundamentals',side_effect=URLError('official transport')), patch.object(a,'acquire_symbol',side_effect=AssertionError('NETWORK')):
            result = a.acquire_shard(self.plan,shard['shard_id'],self.root/'durable',self.root/'out',authority=self.plan['runtime_authority'])
        self.assertEqual(len(result['failed_symbols']),len(shard['symbols']))
        self.assertTrue(all(r['scope']=='MARKET_SOURCE' for r in result['failed_symbols']))
        self.assertEqual(result['validation_status'],'FAIL_CLOSED')

    def test_identity_redirect_http_empty_and_ambiguous_schema_fail_market_closed(self):
        cases = [(archive(month=7),None,200), (archive(market='TPEX'),None,200),
                 (archive().replace('size="5"','size="4"'),None,200),
                 (archive().replace('\u7576\u6708\u71df\u6536','MISSING_COLUMN'),None,200),
                 (archive().replace('<th>\u7576\u6708\u71df\u6536</th>','<th>\u7576\u6708\u71df\u6536</th><th>\u7576\u6708\u71df\u6536</th>'),None,200),
                 (archive(),'https://unauthorized.test',200), (archive(),None,503), ('',None,200),
                 (archive(rows=(('1000','1','1','1'),('1000','2','2','2'))),None,200)]
        for html,final,status in cases:
            with self.subTest(html=html[:60],final=final,status=status), self.assertRaises((RuntimeError,ValueError)):
                self.adapter(html,final=final,status=status).fetch_revenue_period('TWSE','2026-08')

    def test_row_period_and_market_mismatch_are_not_undefined(self):
        for field,value in [('\u8cc7\u6599\u5e74\u6708','11507'),('\u5e02\u5834\u5225','TPEX')]:
            html = archive().replace('<th>\u516c\u53f8\u4ee3\u865f</th>',f'<th>{field}</th><th>\u516c\u53f8\u4ee3\u865f</th>')
            html = html.replace('<td>1000</td>',f'<td>{value}</td><td>1000</td>')
            with self.subTest(field=field),self.assertRaises(RuntimeError):
                self.adapter(html).fetch_revenue_period('TWSE','2026-08')

    def test_exact_raw_receipt_bytes_and_replay_not_postrun_refetch(self):
        source, rows = self.record()
        receipt, body = load_response(self.root/'evidence',rows[0]['raw_response_reference'],self.plan)
        self.assertEqual(body,self.last_body)
        self.assertEqual(hashlib.sha256(body).hexdigest(),rows[0]['content_hash'])
        self.assertEqual(receipt['http_status'],200)
        self.assertEqual(receipt['endpoint'],receipt['final_url'])
        self.assertEqual(receipt['response_bytes'],len(body))
        self.assertEqual(receipt['official_report_disclosure_date'],'2026-10-01')
        self.assertEqual(receipt['parser_sha256'],self.plan['owner_hashes']['src/sources/fundamental_history.py'])
        replay, errors = _warmup_revenue_rows(body.decode(), 'TWSE','2026-08',{**receipt,'raw_response_reference':rows[0]['raw_response_reference']})
        self.assertEqual(replay,rows)
        self.assertEqual(errors,[])
        verify_record(self.root/'evidence',rows[0],self.plan,'revenue')

    def test_raw_byte_and_receipt_tamper_fail_closed(self):
        _, rows = self.record()
        reference = rows[0]['raw_response_reference']
        receipt, body = load_response(self.root/'evidence',reference,self.plan)
        path = self.root/'evidence'/receipt['raw_path']
        path.write_bytes(body+b'changed')
        with self.assertRaisesRegex(RuntimeError,'MOPS_RAW_BODY_HASH_MISMATCH'):
            load_response(self.root/'evidence',reference,self.plan)
        path.write_bytes(body)
        refpath = self.root/'evidence'/reference['path']
        refpath.write_bytes(b'{}')
        with self.assertRaisesRegex(RuntimeError,'MOPS_RAW_RECEIPT_HASH_MISMATCH'):
            load_response(self.root/'evidence',reference,self.plan)

    def test_semantically_consistent_but_fabricated_row_fails_raw_replay(self):
        _, rows = self.record()
        fabricated = {**rows[0],'current_month_revenue':123,'official_raw_current_month_revenue':'123'}
        validate_revenue_semantics(fabricated)
        with self.assertRaisesRegex(RuntimeError,'MOPS_RAW_RECORD_REPLAY_MISMATCH'):
            verify_record(self.root/'evidence',fabricated,self.plan,'revenue')

    def test_raw_evidence_durable_import_even_without_completed_checkpoint(self):
        incoming = self.root/'incoming'
        source = self.adapter(archive(rows=(('1000','','10','1'),)),root=incoming/'shard')
        self.assertEqual(source.fetch_revenue_period('TWSE','2026-08'),[])
        cli.import_progress(self.root/'durable',self.plan,incoming)
        receipts = list((self.root/'durable/reports/mops').glob('*.json'))
        self.assertEqual(len(receipts),1)
        r = json.loads(receipts[0].read_bytes())
        self.assertEqual(hashlib.sha256((self.root/'durable'/r['raw_path']).read_bytes()).hexdigest(),r['body_sha256'])
        self.assertEqual(len(list((self.root/'durable/reports/fundamental_rows').glob('*.json'))),1)

    def test_corrupt_raw_import_writes_nothing(self):
        incoming = self.root/'incoming'
        source = self.adapter(archive(),root=incoming/'shard')
        row = source.fetch_revenue_period('TWSE','2026-08')[0]
        receipt, _ = load_response(incoming/'shard',row['raw_response_reference'],self.plan)
        (incoming/'shard'/receipt['raw_path']).write_bytes(b'tamper')
        with self.assertRaisesRegex(RuntimeError,'MOPS_RAW_BODY_HASH_MISMATCH'):
            cli.import_progress(self.root/'durable',self.plan,incoming)
        self.assertFalse((self.root/'durable').exists())

    def test_normalized_checkpoint_and_raw_material_survive_durable_import(self):
        incoming = self.root/'incoming'
        shard = incoming/'shard'
        m = material(self.plan)
        m['fundamental']['revenue'] = []
        for month in (6,7,8):
            source = self.adapter(archive(month=month),root=shard)
            m['fundamental']['revenue'].extend(source.fetch_revenue_period('TWSE',f'2026-{month:02d}'))
        h.persist_symbol(shard,m,self.plan,'1000','TWSE')
        cli.import_progress(self.root/'durable',self.plan,incoming)
        restored, _ = h.load_checkpoint(self.root/'durable',self.plan,'1000','TWSE')
        self.assertEqual(restored,m)
        self.assertEqual(len(list((self.root/'durable/reports/mops').glob('*.json'))),3)

    def test_content_length_mismatch_is_source_failure_not_undefined(self):
        html = archive()
        def opener(request,timeout):
            response = OfficialArchiveResponse(html,request.full_url)
            response.headers['Content-Length'] = str(len(html.encode())+1)
            return response
        source = MOPSHistoricalFundamentalAdapter(opener=opener,min_interval_seconds=0,
            warmup_evidence_root=self.root/'evidence',evidence_context={'plan_id':self.plan['plan_id'],
                'acquisition_runtime_authority':self.plan['runtime_authority']})
        with self.assertRaisesRegex(RuntimeError,'MOPS_REVENUE_RESPONSE_LENGTH_MISMATCH'):
            source.fetch_revenue_period('TWSE','2026-08')
        self.assertEqual(source.row_failures,[])

    def test_real_owner_row_errors_flow_through_all_planned_months_without_market_abort(self):
        from urllib.parse import parse_qs
        from src.sources.fundamental_history import MOPS_EPS_ENDPOINT
        requests = []
        def opener(request,timeout):
            requests.append(request.full_url)
            if request.full_url == MOPS_EPS_ENDPOINT:
                args = parse_qs(request.data.decode())
                year,quarter = int(args['year'][0]),int(args['season'][0])
                html = f'<html>\u8cc7\u6599\u5e74\u5ea6\uff1a{year}\u5e74 \u7b2c{quarter}\u5b63 \u51fa\u8868\u65e5\u671f\uff1a115/10/01'
                html += '<table><tr><th>\u516c\u53f8\u4ee3\u865f</th><th>\u57fa\u672c\u6bcf\u80a1\u76c8\u9918</th></tr><tr><td>1000</td><td>1</td></tr><tr><td>1002</td><td>1</td></tr></table></html>'
            else:
                month = int(request.full_url.rsplit('_',2)[1])
                html = archive(rows=(('1000','','10','1'),('1002','','20','0')),month=month)
            return OfficialArchiveResponse(html,request.full_url)
        class Adapter(MOPSHistoricalFundamentalAdapter):
            def __init__(self,**kwargs):
                super().__init__(opener=opener,min_interval_seconds=0,**kwargs)
        with patch('src.sources.fundamental_history.MOPSHistoricalFundamentalAdapter',Adapter):
            import time
            result = a.acquire_fundamentals(['1000','1002'],'TWSE',self.plan,self.root/'workspace',time.monotonic(),evidence_root=self.root/'evidence')
        self.assertEqual(len(result['1000']['failures']),6)
        self.assertEqual(result['1002']['failures'],[])
        self.assertEqual(len(result['1002']['revenue']),3)
        self.assertTrue(all(r['revenue_yoy'] is None for r in result['1002']['revenue']))
        self.assertEqual(len(requests),16)
        self.assertEqual(len(list((self.root/'evidence/reports/mops').glob('*.json'))),16)

    def test_downstream_strategy_does_not_coerce_null_to_zero(self):
        from src.fundamental import calculate_fundamental
        rows = [{'symbol':str(i),'revenue_yoy':[None,1,2],'quarterly_eps':[1]*8} for i in range(20)]
        with self.assertRaises(TypeError):
            calculate_fundamental(rows)
        self.assertIsNone(rows[0]['revenue_yoy'][0])

    def test_owner_change_requires_new_plan_not_run3_resume(self):
        old = copy.deepcopy(self.plan)
        old['owner_hashes']['src/sources/fundamental_history.py']='a'*64
        old['plan_id']='rate-history-plan-'+h.digest({k:v for k,v in old.items() if k!='plan_id'})[:24]
        with self.assertRaisesRegex(RuntimeError,'HISTORY_OWNER_OR_POLICY_MISMATCH'):
            h.validate_plan(old)

    def test_full_engineering_cross_section_null_coverage_snapshot_and_reload_pass(self):
        root = self.root/'full-coverage'
        revenue = {}
        for market in ('TWSE','TPEX'):
            market_symbols = [r['symbol'] for r in h.eligible(self.plan['catalogue']) if r['market']==market]
            for month in (6,7,8):
                html = archive(rows=tuple((s,'','100','0') for s in market_symbols),month=month,market=market)
                source = self.adapter(html,root=root)
                for row in source.fetch_revenue_period(market,f'2026-{month:02d}'):
                    revenue.setdefault(row['symbol'],[]).append(row)
        for item in h.eligible(self.plan['catalogue']):
            m = material(self.plan,item['symbol'],item['market'])
            m['fundamental']['revenue'] = revenue[item['symbol']]
            h.persist_symbol(root,m,self.plan,item['symbol'],item['market'])
        snapshot = h.aggregate(root,self.plan)
        self.assertEqual(snapshot['validation_status'],'PASS')
        self.assertEqual(snapshot['fundamental_coverage'],'40/40')
        self.assertEqual(h.reload_snapshot(root,self.plan,snapshot['snapshot_id']),snapshot)
        self.assertFalse((root/'RATE_PRODUCTION_STATE_LATEST.json').exists())
        self.assertFalse((root/'production_state').exists())


    def test_run4_official_eps_no_data_response_is_leading_availability_signal(self):
        # Engineering HTML fixture, not an exact archived Run-4 replay.
        html = """<html><head><title>公開資訊觀測站</title></head><body>
        <div id="div01"><br><h4 align="center"><font color="red">查詢無資料!</font></h4></div>
        <script>var ignored = "查詢無資料!";</script></body></html>"""
        source = self.adapter(html)
        with self.assertRaisesRegex(EPSPeriodNotAvailable, "FUNDAMENTAL_EPS_PERIOD_NOT_AVAILABLE:2026Q3"):
            source.fetch_eps_period("TWSE", 2026, 3)
        reports = [json.loads(p.read_bytes()) for p in (self.root/'evidence/reports/mops').glob('*.json')]
        eps = [r for r in reports if r.get('domain') == 'eps']
        self.assertEqual(len(eps), 1)
        self.assertEqual(eps[0]['requested_period'], '2026Q3')
        self.assertEqual(eps[0]['http_status'], 200)
        self.assertEqual(eps[0]['final_url'], 'https://mopsov.twse.com.tw/mops/web/ajax_t163sb04')

    def test_eps_visible_no_data_whitespace_and_entities(self):
        for text in ('查詢無資料!', '查詢 \n 無\t資料 !', '查詢&nbsp;無&#10;資料&#33;'):
            with self.subTest(text=text):
                self.assertTrue(_eps_official_no_data('<html><body><h4>' + text + '</h4></body></html>'))

    def test_eps_hidden_no_data_is_not_a_signal(self):
        for tag in ('<script>查詢無資料!</script>', '<STYLE>查詢無資料!</STYLE>',
                    '<!-- 查詢無資料! -->', '<head><title>查詢無資料!</title></head>',
                    '<script>查詢無資料!', '<style>查詢無資料!'):
            with self.subTest(tag=tag):
                self.assertFalse(_eps_official_no_data('<html>' + tag + '<body></body></html>'))

    def test_eps_ambiguous_no_data_does_not_bypass_identity_or_schema(self):
        cases = (
            ('<table><tr><th>公司代號</th><th>基本每股盈餘</th></tr></table>',
             'FUNDAMENTAL_EPS_PERIOD_IDENTITY_UNPROVEN'),
            ('<div>資料年度：115年第2季</div>', 'FUNDAMENTAL_EPS_PERIOD_IDENTITY_MISMATCH'),
            ('<div>Internal Server Error</div>', 'FUNDAMENTAL_EPS_PERIOD_IDENTITY_UNPROVEN'),
            ('<div>系統發生錯誤</div>', 'FUNDAMENTAL_EPS_PERIOD_IDENTITY_UNPROVEN'),
            ('<head><title>Internal Server Error</title></head>', 'FUNDAMENTAL_EPS_PERIOD_IDENTITY_UNPROVEN'),
        )
        for extra, reason in cases:
            html = '<html><body><h4>查詢無資料!</h4>' + extra + '</body></html>'
            with self.subTest(extra=extra):
                self.assertFalse(_eps_official_no_data(html))
                with self.assertRaisesRegex(RuntimeError, reason) as caught:
                    self.adapter(html).fetch_eps_period('TWSE', 2026, 3)
                self.assertNotIsInstance(caught.exception, EPSPeriodNotAvailable)

    def test_eps_no_data_preserves_transport_and_integrity_gates(self):
        html = '<html><body><h4>查詢無資料!</h4></body></html>'
        for status, final, reason in ((503, None, 'MOPS_EPS_HTTP_503'),
                (200, 'https://unauthorized.test', 'FUNDAMENTAL_EPS_ENDPOINT_BINDING_INVALID')):
            with self.subTest(status=status, final=final), self.assertRaisesRegex(RuntimeError, reason):
                self.adapter(html, status=status, final=final).fetch_eps_period('TWSE', 2026, 3)
        response = OfficialArchiveResponse(html, 'https://mopsov.twse.com.tw/mops/web/ajax_t163sb04')
        response.headers['Content-Length'] = str(len(html.encode('utf-8')) + 1)
        source = MOPSHistoricalFundamentalAdapter(opener=lambda req,timeout: response, min_interval_seconds=0,
            warmup_evidence_root=self.root/'length-evidence')
        with self.assertRaisesRegex(RuntimeError, 'MOPS_EPS_RESPONSE_LENGTH_MISMATCH'):
            source.fetch_eps_period('TWSE', 2026, 3)

    def test_eps_no_data_is_not_publication_or_returned_period_proof(self):
        source = self.adapter('<html><body><h4>查詢無資料!</h4></body></html>')
        with self.assertRaises(EPSPeriodNotAvailable):
            source.fetch_eps_period('TWSE', 2026, 3)
        diag = source.diagnostics[-1]
        self.assertEqual(diag['availability_status'], 'OFFICIAL_QUERY_NO_DATA')
        self.assertEqual(diag['publication_status'], 'UNPROVEN')
        self.assertEqual(diag['period_identity_source'], 'UNPROVEN')
        self.assertNotIn('returned_period', diag)


if __name__ == '__main__':
    unittest.main()
