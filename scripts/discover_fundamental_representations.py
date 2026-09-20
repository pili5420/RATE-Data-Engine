"""Bounded, read-only official representation discovery; never materializes history."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
from html.parser import HTMLParser
import json
import math
import os
from pathlib import Path
import re
import sys
from urllib.error import HTTPError
from urllib.parse import urlencode, urljoin, urlparse, parse_qs
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.sources.fundamental_history import _tables, _table_records

PERIODS = ('2026-08', '2026-07', '2026-06')
QUARTERS = ('2026Q2', '2026Q1', '2025Q4', '2025Q3')
SAMPLES = ('2330', '6274', '3661')


class Structure(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = Counter()
        self.controls = []
        self.links = []
        self.text = []
    def handle_starttag(self, tag, attrs):
        self.tags[tag] += 1
        attrs = dict(attrs)
        if tag in ('form', 'input', 'select'):
            self.controls.append({k: attrs.get(k) for k in ('name', 'id', 'type', 'action') if attrs.get(k)})
        for key in ('src', 'href'):
            if attrs.get(key): self.links.append(attrs[key])
    def handle_data(self, data):
        self.text.append(data)


def structure(text):
    p = Structure(); p.feed(text)
    tags = {k:p.tags[k] for k in ('table','tr','td','div','script')}
    escaped = {k:text.lower().count('&lt;'+k) for k in ('table','tr')}
    if tags['table']: classification = 'NORMAL_HTML_TABLE'
    elif escaped['table']: classification = 'HTML_ESCAPED_TABLE'
    elif p.tags['form']: classification = 'FORM_PAGE'
    elif tags['script'] and ('<table' in text.lower() or '\\u003ctable' in text.lower()): classification = 'JAVASCRIPT_WRAPPED_HTML'
    else: classification = 'OTHER_OFFICIAL_REPRESENTATION'
    # At most 2 KiB, no complete HTML, session tokens, input values or cookies.
    prefix = re.sub(r'(?i)(token|nonce|sessionid)\s*[:=]\s*[\"\']?[^\s\"\'<>]+', r'\1=[REDACTED]', text[:2048])
    return {'classification':classification, 'first_2kb_sanitized_text':prefix.encode('utf-8')[:2048].decode('utf-8','ignore'),
            'tag_counts':tags, 'escaped_tag_counts':escaped,
            'keyword_presence':{k:k in text for k in ('公司代號','基本每股盈餘','年度','季別','year','season','TYPEK')},
            'form_input_select_names':list({json.dumps(x,sort_keys=True):x for x in p.controls}.values()),
            'javascript_assignment_names':sorted(set(re.findall(r'\b(?:var|let|const)\s+([A-Za-z_$][\w$]*)\s*=', text)))[:100]}


def fetch(url, params=None, json_body=False):
    host = urlparse(url).hostname or ''
    if not (host.endswith('.twse.com.tw') or host.endswith('.tpex.org.tw')):
        raise ValueError('NON_OFFICIAL_SOURCE')
    body = (json.dumps(params).encode() if json_body else urlencode(params, doseq=True).encode()) if params is not None else None
    headers = {'User-Agent':'RATE-CER073-Representation-Discovery/1.0', 'Referer':urljoin(url,'/'), 'Accept-Encoding':'identity'}
    if body is not None: headers['Content-Type'] = 'application/json' if json_body else 'application/x-www-form-urlencoded'
    evidence = {'official_endpoint':url, 'method':'POST' if body is not None else 'GET', 'request_parameters':params,
                'retrieval_timestamp':datetime.now(timezone.utc).isoformat()}
    try:
        try: r = urlopen(Request(url,data=body,headers=headers),timeout=30)
        except HTTPError as exc: r = exc
        with r:
            b = r.read(); evidence.update(http_status=r.status,final_url=r.url,response_bytes=len(b),
                  content_hash=hashlib.sha256(b).hexdigest(),content_type=r.headers.get('Content-Type'),content_encoding=r.headers.get('Content-Encoding','identity'))
        for encoding in ('utf-8-sig','cp950','big5'):
            try: text = b.decode(encoding); break
            except UnicodeDecodeError: continue
        else: encoding='utf-8-replacement'; text=b.decode('utf-8','replace')
        evidence['decoded_encoding'] = encoding
        return text, evidence
    except Exception as exc:
        evidence.update(http_status=None,final_url=None,error=f'{type(exc).__name__}: {exc}')
        return '', evidence


def write(path, value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def official_date(value):
    match = re.fullmatch(r'(\d{3,4})/(\d{2})/(\d{2})(?: \d{2}:\d{2}:\d{2})?', value)
    if not match: raise ValueError('INVALID_OFFICIAL_DATE')
    y,m,d = map(int,match.groups())
    return datetime(y+1911 if y<1911 else y,m,d).date().isoformat()


def base_params(symbol, year):
    return {'encodeURIComponent':'1','step':'1','firstin':'1','off':'1','isQuery':'Y',
            'co_id':symbol,'year':str(year-1911),'TYPEK':'all','isnew':'false'}


def revenue_archive(text, requested_period):
    # Response-owned report heading, never URL/request-derived identity.
    m = re.search(r'(上市|上櫃)公司(\d{3})年(\d{1,2})月份\(累計與當月\)營業收入統計表', text)
    period = f'{int(m[2])+1911:04d}-{int(m[3]):02d}' if m else None
    rows, schema = _table_records(text, {'symbol':('公司代號',),'yoy':('去年同月增減(%)',)})
    values = {}
    for r in rows:
        try: value = float(r['yoy'].replace(',','').strip())
        except ValueError: continue
        if not math.isfinite(value): continue
        if r['symbol'] in values and values[r['symbol']] != value: raise ValueError('CONFLICTING_ARCHIVE_VALUES')
        values[r['symbol']] = value
    date = re.search(r'出表日期[：:]\s*(\d{3}/\d{2}/\d{2})',text)
    return {'returned_period':period,'period_identity_evidence':m[0] if m else None,
            'period_identity_source':'VERIFIED_OFFICIAL_HISTORICAL_RESPONSE_METADATA' if period==requested_period else 'UNPROVEN',
            'schema':schema[:1], 'parsed_symbol_count':len(values),
            'report_generation_date':date[1] if date else None,
            'report_generation_date_accepted_as_disclosure':False}, values


def announcement_records(obj, symbol):
    result = []
    if obj.get('status') != 'success': return result
    for r in obj.get('data',[]):
        if r.get('COMPANY_ID') != symbol or r.get('AN_CODE') != 'F22': continue
        m = re.fullmatch(r'(\d{3})年(\d{1,2})月營業收入',r.get('SUBJECT',''))
        if not m: continue
        period = f'{int(m[1])+1911:04d}-{int(m[2]):02d}'
        if period not in PERIODS: continue
        link = urlparse(r.get('HYPERLINK','')); query = parse_qs(link.query)
        if link.hostname not in ('mopsov.twse.com.tw','mops.twse.com.tw'): continue
        if query.get('co_id') != [symbol] or query.get('year') != [m[1]] or query.get('month') != [f'{int(m[2]):02d}']: continue
        result.append({'symbol':symbol,'revenue_period':period,'official_disclosure_date':official_date(r['CDATE']),
                       'official_disclosure_time':r.get('CTIME'),'evidence':r})
    return result


def join_revenue(value, announcements, as_of):
    matches = [r for r in announcements if (r['symbol'],r['revenue_period']) == (value['symbol'],value['revenue_period'])]
    # Never hide post-cutoff revisions by filtering dates before choosing the latest record.
    dates = {(r['official_disclosure_date'],r.get('official_disclosure_time','')) for r in matches}
    if len(dates) != 1: return None
    record = matches[0]
    if record['official_disclosure_date'] > as_of: return None
    return {**value, 'official_disclosure_date':record['official_disclosure_date'],
            'classification':'OFFICIAL_DUAL_SOURCE_LINEAGE',
            'join_key':['symbol','revenue_period'], 'disclosure_evidence':record['evidence'],
            'provider_lineage':[value['value_source'],record['date_source']],
            'content_hash':hashlib.sha256((value['value_source']['content_hash']+record['date_source']['content_hash']).encode()).hexdigest()}


def probe_revenue(universe, as_of):
    archives=[]; values={}; dates=[]; date_probes=[]; ky_candidates=[]
    for market,code in [('TWSE','sii'),('TPEX','otc')]:
        wanted = {r['symbol'] for r in universe if r['market']==market}
        for period in PERIODS:
            for variant in (0,1):
                url = f'https://mopsov.twse.com.tw/nas/t21/{code}/t21sc03_115_{int(period[-2:])}_{variant}.html'
                text,e = fetch(url); info,rows = revenue_archive(text,period)
                e.update(info,market=market,variant=variant,requested_period=period,
                         actual_hit_symbols=sorted(wanted & set(rows)),
                         disclosure_date_location='ABSENT; header 出表日期 is report generation only')
                e['value_transport_verified']=e.get('http_status')==200 and info['returned_period']==period and bool(rows)
                archives.append(e)
                if e['value_transport_verified']:
                    for symbol in wanted & set(rows):
                        key=(symbol,period)
                        item={'symbol':symbol,'revenue_period':period,'revenue_yoy':rows[symbol],
                              'value_source':{'provider':'MOPS','official_endpoint':url,'content_hash':e['content_hash'],
                                              'period_identity_evidence':info['period_identity_evidence']}}
                        if key in values and values[key]['revenue_yoy']!=item['revenue_yoy']: raise ValueError('ARCHIVE_VARIANT_CONFLICT')
                        values[key]=item
                if '3661' in rows:
                    ky_candidates.append({**e,'symbol_evidence':'3661','revenue_yoy':rows['3661']})
    # A single official announcement query per symbol covers the three requested periods.
    for r in universe:
        p={'step':'00','RADIO_CM':'2','TYPEK':'sii' if r['market']=='TWSE' else 'otc',
           'CO_MARKET':'','CO_ID':r['symbol'],'PRO_ITEM':'F22','SUBJECT':'',
           'SDATE':'1150601','EDATE':'1150920','lang':'TW','AN':''}
        text,e=fetch('https://mopsov.twse.com.tw/mops/web/ezsearch_query',p)
        try: obj=json.loads(text); records=announcement_records(obj,r['symbol'])
        except (ValueError,TypeError): obj={}; records=[]
        e.update(symbol=r['symbol'],response_schema=sorted(obj.keys()),matched_records=records,
                 period_identity_location='data[].SUBJECT AND HYPERLINK year/month',
                 disclosure_date_location='data[].CDATE; CTIME is official local announcement time')
        date_probes.append(e)
        for record in records:
            dates.append({**record,'date_source':{'provider':'MOPS','official_endpoint':e['official_endpoint'],
                                                 'content_hash':e['content_hash']}})
    # Independently inspect single-company foreign/KY IFRS representation.
    for period in PERIODS:
        p={**base_params('3661',2026),'month':period[-2:]}
        text,e=fetch('https://mopsov.twse.com.tw/mops/web/ajax_t05st10_ifrs',p)
        table_rows=[r for t in _tables(text) for r in t]
        evidence=[r for r in table_rows if r and r[0] in ('本月','增減百分比')]
        e.update(requested_period=period,response_schema=evidence,
                 symbol_evidence='世芯-KY' if '世芯-KY' in text else None,
                 period_evidence=re.findall(r'115\s*年\s*[678]\s*月',text),
                 official_disclosure_date_evidence=None,
                 acceptance='VALUE_CROSS_CHECK_ONLY; numeric symbol/filing date absent')
        ky_candidates.append(e)
    events=[]; missing=[]
    for r in universe:
        for period in PERIODS:
            value=values.get((r['symbol'],period))
            event=join_revenue(value,dates,as_of) if value else None
            if event: events.append(event)
            else: missing.append({'symbol':r['symbol'],'period':period,'reason':'VALUE_OR_UNIQUE_ASOF_DISCLOSURE_MISSING'})
    covered={r['symbol'] for r in universe if all((r['symbol'],p) in values for p in PERIODS)}
    lineage_covered={r['symbol'] for r in universe if all(any(e['symbol']==r['symbol'] and e['revenue_period']==p for e in events) for p in PERIODS)}
    nky=sum(e['symbol']=='3661' for e in events)
    verified=len(events)==len(universe)*3
    return {'artifact':'RATE_CER073_REVENUE_REPRESENTATION_DISCOVERY',
            'revenue_0_classification':'OFFICIAL_VALUE_ARCHIVE_REACHABLE / LINEAGE_INCOMPLETE',
            'historical_representation':'MOPS t21 _0/_1 + eZsearch F22' if verified else 'UNRESOLVED',
            'classification':'OFFICIAL_DUAL_SOURCE_LINEAGE' if verified else 'LINEAGE_INCOMPLETE',
            'period_identity_source':'OFFICIAL_DUAL_SOURCE_LINEAGE',
            'value_period_identity_source':'VERIFIED_OFFICIAL_HISTORICAL_RESPONSE_METADATA',
            'disclosure_date_source':'MOPS eZsearch F22 data[].CDATE, joined by COMPANY_ID and explicit revenue period',
            'archive_variant_contract':'VERIFIED' if len(covered)==30 else 'UNVERIFIED',
            'monthly_revenue_historical_transport_contract':'VERIFIED' if verified else 'FAIL',
            'twse_actual_coverage':f'{len(covered & {r["symbol"] for r in universe if r["market"]=="TWSE"})}/25',
            'tpex_actual_coverage':f'{len(covered & {r["symbol"] for r in universe if r["market"]=="TPEX"})}/5',
            'actual_symbol_coverage':f'{len(covered)}/30','lineage_symbol_coverage':f'{len(lineage_covered)}/30',
            '3661_historical_coverage':f'{nky}/3','accepted_event_count':len(events),
            'candidate_archive_variants':archives,'3661_candidate_sources':ky_candidates,
            'disclosure_probes':date_probes,'accepted_discovery_events':events,'remaining_blockers':missing}


def fin_values(obj, symbol):
    names=obj.get('showNameList',[])
    if len(names)!=1 or not names[0].startswith(symbol+' '): return {}
    graphs=obj.get('graphData',[]); axis=obj.get('xaxisList',[])
    if len(graphs)!=1 or graphs[0].get('label') not in names[0]: return {}
    result={}
    for point in graphs[0].get('data',[]):
        i,value=point[:2]
        if not isinstance(i,int) or not 0<=i<len(axis) or isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value): continue
        period=axis[i]
        if period in QUARTERS:
            if period in result: raise ValueError('DUPLICATE_EPS_PERIOD')
            result[period]=value
    return result


def report_records(text,symbol):
    result=[]
    for table in _tables(text):
        if not table or '上傳日期' not in table[0]: continue
        header=table[0]
        for row in table[1:]:
            if len(row)!=len(header): continue
            r=dict(zip(header,row)); m=re.fullmatch(r'(\d{3}) 年 第([一二三四])季',r.get('資料年度',''))
            if r.get('證券代號')!=symbol or not m or r.get('資料細節說明')!='IFRSs合併財報': continue
            period=f'{int(m[1])+1911}Q{"一二三四".index(m[2])+1}'
            if period not in QUARTERS: continue
            filename=r.get('電子檔案','')
            if filename!=f'{period[:4]}0{period[-1]}_{symbol}_AI1.pdf': continue
            result.append({'symbol':symbol,'period':period,'official_disclosure_date':official_date(r['上傳日期']),
                           'filing_identity':filename,'correction_status':r.get('財務報告更(補)正'),'evidence':r})
    return result


def correction_records(text,symbol,period):
    tables=_tables(text)
    metadata=[r for t in tables for r in t if r and (r[0].startswith('資料年度') or r[0].startswith('季'))]
    flat=' '.join(' '.join(r) for r in metadata)
    year=re.search(r'資料年度[：:]\s*(\d{3})',flat)
    quarter=re.search(r'季\s*別[：:]\s*0?([1-4])',flat)
    if not year or not quarter or f'{int(year[1])+1911}Q{quarter[1]}'!=period: return []
    result=[]
    for table in tables:
        if not table or '公告日期' not in table[0]: continue
        for row in table[1:]:
            if len(row)!=len(table[0]): continue
            r=dict(zip(table[0],row))
            if r.get('公司代號')!=symbol or r.get('資料說明')!='IFRSs合併財報': continue
            date=datetime.strptime(r['公告日期'],'%Y%m%d').date().isoformat()
            result.append({'symbol':symbol,'period':period,'official_correction_date':date,
                           'period_metadata':metadata,'evidence':r})
    return result


def probe_eps(as_of):
    diagnostics=[]
    for market,code in [('TWSE','sii'),('TPEX','otc')]:
        params={**base_params('',2026),'TYPEK':code,'season':'02'}; params.pop('co_id');params.pop('isnew')
        text,e=fetch('https://mopsov.twse.com.tw/mops/web/ajax_t163sb04',params)
        diagnostics.append({**e,'market':market,'requested_period':'2026Q2',**structure(text),
                            'period_identity':'UNPROVEN; structural diagnosis only',
                            'previous_table_count_0_explanation':'Previous diagnostic counted schema matches, not HTML table tags'})
    page,pe=fetch('https://mopsfin.twse.com.tw/')
    terms,te=fetch('https://mopsfin.twse.com.tw/terms')
    pe['transport_definition_evidence']={
        'post_compare_data_present':'url: "/compare/data"' in page,
        'eps_item_present':'name="EPS"' in page,
        'quarter_flag_definition':'$("#quarter").val($("#tab_quarter").hasClass("current"))' in page,
        'single_quarter_label':bool(re.search(r'id="tab_quarter".{0,100}單季',page))}
    te['semantics_evidence']={'q1_q3_company_reported':'各公司自行申報之單季金額' in terms,
                              'q4_annual_minus_q3':'第4季累計金額減除第3季累計金額' in terms}
    candidates=[]; reports=[]; samples=[]; arithmetic=[]; corrections=[]
    for symbol in SAMPLES:
        series={}
        for mode,q in [('single',''),('cumulative','3'),('cumulative','4')]:
            p={'compareItem':'EPS','companyId':symbol,'quarter':'true' if mode=='single' else 'false',
               'ylabel':'元','ys':'0','revenue':'false','bcodeAvg':'false','companyAvg':'false','qnumber':q}
            text,e=fetch('https://mopsfin.twse.com.tw/compare/data',p)
            try: obj=json.loads(text); data=fin_values(obj,symbol)
            except (ValueError,TypeError): obj={};data={}
            e.update(symbol=symbol,mode=mode,response_schema=sorted(obj.keys()),
                     response_owned_company=obj.get('showNameList'),selected_period_values=data,
                     period_identity_location='xaxisList[graphData[].data[][0]]',
                     symbol_identity_location='showNameList[0] + graphData[0].label',
                     semantics='SINGLE_QUARTER' if mode=='single' else 'CUMULATIVE',
                     official_disclosure_date_location=None)
            candidates.append(e);series[mode+q]=(data,e)
        single,se=series['single']; c3,e3=series['cumulative3'];c4,e4=series['cumulative4']
        q4=single.get('2025Q4');a=c4.get('2025Q4');b=c3.get('2025Q3')
        diff=Decimal(str(a))-Decimal(str(b)) if a is not None and b is not None else None
        arithmetic.append({'symbol':symbol,'single_q4':q4,'annual_cumulative':a,'q3_cumulative':b,
                           'difference':float(diff) if diff is not None else None,
                           'validation_status':'PASS' if diff is not None and q4 is not None and abs(diff-Decimal(str(q4)))<=Decimal('0.01') else 'FAIL',
                           'source_hashes':[se.get('content_hash'),e3.get('content_hash'),e4.get('content_hash')]})
        filings=[]
        for year in (2025,2026):
            url='https://doc.twse.com.tw/server-java/t57sb01?'+urlencode({'step':'1','colorchg':'1','co_id':symbol,'year':year-1911,'seamon':'','mtype':'A'})
            text,e=fetch(url); records=report_records(text,symbol)
            reports.append({**e,'symbol':symbol,'requested_year':year,'matched_records':records,
                            'disclosure_date_location':'上傳日期','period_identity_location':'資料年度 AND 電子檔案'})
            for record in records: filings.append({**record,'source':e})
        for period in QUARTERS:
            fs=[r for r in filings if r['period']==period]
            f=fs[0] if len(fs)==1 else None
            availability=f['official_disclosure_date'] if f else None
            correction_ok=bool(f and f['correction_status']=='無')
            correction_lineage=[]
            if f and not correction_ok:
                params={'step':'1','firstin':'1','off':'1','isQuery':'Y','TYPEK':'otc' if symbol=='6274' else 'sii',
                        'year':str(int(period[:4])-1911),'season':f'0{period[-1]}'}
                text,ce=fetch('https://mopsov.twse.com.tw/mops/web/ajax_t56sb31_q1',params)
                cr=correction_records(text,symbol,period)
                corrections.append({**ce,'symbol':symbol,'period':period,'correction_records':cr})
                correction_ok=bool(cr) and ce.get('http_status')==200
                correction_lineage=[{**r,'source':ce} for r in cr]
                if cr: availability=max([availability]+[r['official_correction_date'] for r in cr])
            date_ok=bool(f and availability<=as_of and correction_ok)
            samples.append({'symbol':symbol,'year':int(period[:4]),'quarter':int(period[-1]),'period':period,
                            'single_quarter_eps':single.get(period),'returned_period_identity':period in single,
                            'official_source':se['official_endpoint'],'content_hash':se.get('content_hash'),
                            'official_disclosure_date':availability,
                            'date_asof_check':'PASS' if date_ok else 'FAIL',
                            'disclosure_date_semantics':'Conservative availability: max(official consolidated-report upload, all matching official correction announcement dates); not the original earnings announcement date',
                            'filing_lineage':f,'correction_lineage':correction_lineage,
                            'provider_lineage':['MOPSFin EPS','MOPS official financial report filing list','MOPS correction announcements when present']})
    identities=sum(s['returned_period_identity'] for s in samples)
    semantics=all(te['semantics_evidence'].values()) and all(pe['transport_definition_evidence'].values()) and all(r['validation_status']=='PASS' for r in arithmetic)
    transport=identities==12 and semantics and all(e.get('http_status')==200 for e in candidates)
    verified=transport and all(s['date_asof_check']=='PASS' for s in samples)
    blockers=[]
    if not transport: blockers.append('MOPSFIN_SAMPLE_TRANSPORT_OR_SEMANTICS_UNVERIFIED')
    if not all(s['date_asof_check']=='PASS' for s in samples): blockers.append('EPS_SAMPLE_FILING_DATE_OR_REVISION_UNRESOLVED')
    fallback={'status':'NOT_RUN','reason':'MOPSFin stable sample transport verified'}
    if not transport:
        # Official single-company XBRL entry is probed only when preferred transport fails.
        text,e=fetch('https://mopsov.twse.com.tw/mops/web/t203sb01')
        fallback={**e,'status':'FAIL','structure':structure(text),
                  'reason':'Entry reachability alone does not prove company/period/concept/filing transport'}
    return {'artifact':'RATE_CER073_EPS_REPRESENTATION_DISCOVERY','current_t163_response_structure':diagnostics,
            't163_previous_classification':'OFFICIAL_RESPONSE_REACHABLE / REPRESENTATION_UNRESOLVED',
            't163_representation':'NORMAL_HTML_TABLE' if all(d['classification']=='NORMAL_HTML_TABLE' for d in diagnostics) else 'OTHER_OFFICIAL_REPRESENTATION',
            'mopsfin_page_transport_definition':pe,'mopsfin_methodology':te,'mopsfin_candidate_results':candidates,
            'mopsfin_technical_transport_contract':'VERIFIED' if transport else 'UNVERIFIED',
            'mopsfin_sample_period_identity':f'{identities}/12','mopsfin_sample_eps_semantics':'PASS' if semantics else 'FAIL',
            'q4_arithmetic_validation':arithmetic,'samples':samples,'filing_date_probes':reports,'correction_date_probes':corrections,
            'xbrl_fallback_probe':fallback,'period_identity_location':'MOPSFin response xaxisList with explicit graphData index',
            'eps_semantics':'Q1-Q3 company-reported single-quarter; Q4 full-year cumulative minus Q3 cumulative',
            'historical_representation':'MOPSFin /compare/data + MOPS financial report filing metadata' if verified else 'UNRESOLVED',
            'eps_returned_period_identity':'PASS' if identities==12 else 'FAIL',
            'disclosure_date_source':'t57sb01 mtype=A 上傳日期 + t56sb31_q1 公告日期 for corrected filings; exact symbol/fiscal-quarter/report type',
            'eps_accounting_category_authority':'NOT_REQUIRED' if transport else 'NOT_RUN',
            'accounting_category_rationale':'MOPSFin exposes normalized EPS and requires no industry/taxonomy parameter at consumer layer. Verified only for the three requested companies; raw statements/XBRL still require taxonomy authority.',
            'eps_historical_transport_contract':'VERIFIED' if verified else 'FAIL','remaining_blockers':blockers,
            'limits':['Discovery validates 3 companies x 4 quarters only; no 30-symbol 8Q bootstrap.',
                      'No claim of pre-correction vintage reconstruction. Corrected filings use latest matching official correction date and fail closed when date lineage is missing or after as_of.']}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--as-of-date',default='2026-09-18')
    parser.add_argument('--output-dir',default='artifacts/representation-discovery')
    args=parser.parse_args()
    universe=json.loads((ROOT/'config/staging/RATE_STAGING_LIVE_UNIVERSE_V1.json').read_text(encoding='utf-8'))
    rows=universe['symbols']; symbols=sorted(r['symbol'] for r in rows)
    if len(set(symbols))!=30 or Counter(r['market'] for r in rows)!={'TWSE':25,'TPEX':5}: raise ValueError('UNIVERSE_MISMATCH')
    if universe.get('universe_symbol_digest')!='30276287608b87f7d9b606891514247da523dce9214e4b82bb34ba118a35af4c': raise ValueError('UNIVERSE_DIGEST_MISMATCH')
    payload={'source_state_id':universe['source_state_id'],'symbols':[r['symbol'] for r in rows]}
    actual_digest=hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    if actual_digest!=universe['universe_symbol_digest']: raise ValueError('ACTUAL_UNIVERSE_DIGEST_MISMATCH')
    common={'discovery_performed':True,'as_of_date':args.as_of_date,'scope':'REPRESENTATION_DISCOVERY_ONLY',
            'actions_run_id':os.getenv('GITHUB_RUN_ID'),'actions_job_name':os.getenv('GITHUB_JOB'),
            'staging_head':os.getenv('GITHUB_SHA'),'previous_staging_head':'5ca982c7bffa86d38434fec2d08ac69cbd63e2f2',
            'RATE_LIVE_E2E_ENABLED':False,'input_snapshot_id':None,'production_decision_state_persist':0,
            'production_namespace_modified':False,'historical_layer_modified':False,'main_modified':False,
            'raw_html_persisted':False,'bootstrap_executed':False}
    output=Path(args.output_dir)
    print('Revenue representation discovery started',flush=True)
    revenue={**common,**probe_revenue(rows,args.as_of_date)}
    write(output/'RATE_CER073_REVENUE_REPRESENTATION_DISCOVERY.json',revenue)
    print('Revenue:',revenue['monthly_revenue_historical_transport_contract'],revenue['actual_symbol_coverage'],flush=True)
    print('EPS representation discovery started',flush=True)
    eps={**common,**probe_eps(args.as_of_date)}
    write(output/'RATE_CER073_EPS_REPRESENTATION_DISCOVERY.json',eps)
    print('EPS:',eps['eps_historical_transport_contract'],eps['mopsfin_sample_period_identity'],flush=True)
    print('Bootstrap NOT RUN; production writes = 0',flush=True)


if __name__ == '__main__':
    main()
