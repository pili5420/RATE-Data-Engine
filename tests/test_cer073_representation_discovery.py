"""Fail-closed evidence identity, date and representation checks."""
import copy
import unittest
from scripts.discover_fundamental_representations import (
    announcement_records, fin_values, join_revenue, revenue_archive, structure, report_records, correction_records,
)


class RepresentationDiscoveryTests(unittest.TestCase):
    def announcement(self):
        return {'status':'success','data':[{'COMPANY_ID':'3661','AN_CODE':'F22','SUBJECT':'115年8月營業收入',
                 'CDATE':'115/09/10','CTIME':'14:03:37',
                 'HYPERLINK':'https://mopsov.twse.com.tw/mops/web/ajax_t05st10_ifrs?co_id=3661&year=115&month=08'}]}

    def test_normal_table_count_independent_of_schema_match(self):
        d=structure('<table><tr><td>unknown schema</td></tr></table>')
        self.assertEqual(d['classification'],'NORMAL_HTML_TABLE')
        self.assertEqual(d['tag_counts']['table'],1)

    def test_escaped_table(self):
        self.assertEqual(structure('&lt;table&gt;&lt;tr&gt;')['classification'],'HTML_ESCAPED_TABLE')

    def test_form_page(self):
        self.assertEqual(structure('<form><input name="year"></form>')['classification'],'FORM_PAGE')

    def test_prefix_bounded_in_bytes_and_session_sanitized(self):
        s=structure('sessionid=SECRET '+ '中文'*2000)
        self.assertNotIn('SECRET',s['first_2kb_sanitized_text'])
        self.assertLessEqual(len(s['first_2kb_sanitized_text'].encode()),2048)

    def test_archive_heading_response_identity(self):
        s='上市公司115年8月份(累計與當月)營業收入統計表 出表日期：115/09/20'
        d,_=revenue_archive(s,'2026-08')
        self.assertEqual(d['returned_period'],'2026-08')
        self.assertFalse(d['report_generation_date_accepted_as_disclosure'])

    def test_request_period_cannot_supply_missing_or_mismatched_identity(self):
        self.assertEqual(revenue_archive('','2026-08')[0]['period_identity_source'],'UNPROVEN')
        s='上市公司115年7月份(累計與當月)營業收入統計表'
        self.assertEqual(revenue_archive(s,'2026-08')[0]['period_identity_source'],'UNPROVEN')

    def test_announcement_independent_period_and_symbol(self):
        rows=announcement_records(self.announcement(),'3661')
        self.assertEqual((rows[0]['revenue_period'],rows[0]['official_disclosure_date']),('2026-08','2026-09-10'))
        self.assertEqual(announcement_records(self.announcement(),'2330'),[])

    def test_announcement_hyperlink_mismatch_rejected(self):
        obj=self.announcement();obj['data'][0]['HYPERLINK']=obj['data'][0]['HYPERLINK'].replace('month=08','month=07')
        self.assertEqual(announcement_records(obj,'3661'),[])

    def test_announcement_nonofficial_link_rejected(self):
        obj=self.announcement();obj['data'][0]['HYPERLINK']=obj['data'][0]['HYPERLINK'].replace('mopsov.twse.com.tw','example.com')
        self.assertEqual(announcement_records(obj,'3661'),[])

    def join_data(self):
        value={'symbol':'3661','revenue_period':'2026-08','revenue_yoy':273.61,
               'value_source':{'content_hash':'a'*64,'provider':'MOPS'}}
        d=announcement_records(self.announcement(),'3661')[0]
        d['date_source']={'content_hash':'b'*64,'provider':'MOPS'}
        return value,d

    def test_exact_dual_source_join(self):
        v,d=self.join_data();event=join_revenue(v,[d],'2026-09-18')
        self.assertEqual(event['classification'],'OFFICIAL_DUAL_SOURCE_LINEAGE')
        self.assertEqual(len(event['provider_lineage']),2)
        self.assertEqual(len(event['content_hash']),64)

    def test_wrong_period_never_joins(self):
        v,d=self.join_data();d['revenue_period']='2026-07'
        self.assertIsNone(join_revenue(v,[d],'2026-09-18'))

    def test_post_asof_rejected(self):
        v,d=self.join_data();d['official_disclosure_date']='2026-09-19'
        self.assertIsNone(join_revenue(v,[d],'2026-09-18'))

    def test_multiple_revisions_fail_closed(self):
        v,d=self.join_data();new=copy.deepcopy(d);new['official_disclosure_date']='2026-09-19'
        self.assertIsNone(join_revenue(v,[d,new],'2026-09-18'))

    def fin(self):
        return {'showNameList':['2330 台積電 (上市半導體業)'],'xaxisList':['2026Q1','2026Q2'],
                'graphData':[{'label':'台積電','data':[[1,27.25,'C'],[0,22.08,'C']]}]}

    def test_eps_uses_explicit_axis_index(self):
        self.assertEqual(fin_values(self.fin(),'2330'),{'2026Q2':27.25,'2026Q1':22.08})

    def test_eps_wrong_company_rejected(self):
        self.assertEqual(fin_values(self.fin(),'3661'),{})

    def test_eps_missing_and_nonfinite_not_zero(self):
        o=self.fin();o['graphData'][0]['data']=[[0,None],[1,float('nan')]]
        self.assertEqual(fin_values(o,'2330'),{})

    def test_eps_duplicate_period_rejected(self):
        o=self.fin();o['graphData'][0]['data'].append([1,99])
        with self.assertRaises(ValueError):fin_values(o,'2330')

    def test_filing_identity_requires_period_filename_agreement(self):
        s='<table><tr><th>證券代號</th><th>資料年度</th><th>資料細節說明</th><th>電子檔案</th><th>上傳日期</th><th>財務報告更(補)正</th></tr><tr><td>2330</td><td>115 年 第二季</td><td>IFRSs合併財報</td><td>202602_2330_AI1.pdf</td><td>115/08/14 13:59:44</td><td>無</td></tr></table>'
        self.assertEqual(report_records(s,'2330')[0]['official_disclosure_date'],'2026-08-14')
        self.assertEqual(report_records(s.replace('202602_2330','202601_2330'),'2330'),[])

    def test_correction_date_requires_response_period_symbol_and_report_type(self):
        s='<table><tr><td>資料年度： 114</td></tr><tr><td>季 別： 03</td></tr></table><table><tr><th>公司代號</th><th>公告日期</th><th>資料說明</th></tr><tr><td>3661</td><td>20251202</td><td>IFRSs合併財報</td></tr></table>'
        self.assertEqual(correction_records(s,'3661','2025Q3')[0]['official_correction_date'],'2025-12-02')
        self.assertEqual(correction_records(s,'3661','2025Q4'),[])
        self.assertEqual(correction_records(s,'2330','2025Q3'),[])
        self.assertEqual(correction_records(s.replace('合併財報','英文版-合併財報'),'3661','2025Q3'),[])


if __name__=='__main__': unittest.main()
