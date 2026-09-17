from __future__ import annotations
from .base import fetch_json, provenance
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
import hashlib, json
import os
import time
from http.client import IncompleteRead
from urllib.parse import urljoin, urlparse

BASE = "https://openapi.twse.com.tw/v1"
MAX_REDIRECTS = 3
APPROVED_REDIRECT_HOSTS = frozenset({"www.twse.com.tw"})

def _history_rows(payload):
    if not isinstance(payload, dict):
        return []
    data = payload.get('data') or payload.get('records') or []
    fields = payload.get('fields') or []
    if fields and isinstance(data, list):
        return [dict(zip(fields, row)) if isinstance(row, list) else row for row in data if isinstance(row, (list, dict))]
    return [row for row in data if isinstance(row, dict)] if isinstance(data, list) else []

def _date_matches_period(value, year_month):
    text = str(value or '').strip().replace('-', '/').replace('.', '/')
    if not text:
        return False
    # TWSE returns either Gregorian YYYY/MM/DD or ROC YYY/MM/DD.
    return text.startswith(year_month[:4] + '/' + year_month[4:6] + '/') or text.startswith(str(int(year_month[:4]) - 1911).zfill(3) + '/' + year_month[4:6] + '/')

def _validate_history_identity(payload, stock_no, year_month):
    if not isinstance(payload, dict) or payload.get('stat') not in (None, 'OK'):
        raise RuntimeError('TWSE_HISTORY_RESPONSE_IDENTITY_MISMATCH')
    rows = _history_rows(payload)
    if not rows:
        raise RuntimeError('TWSE_HISTORY_RESPONSE_IDENTITY_MISMATCH')
    dates = []
    for row in rows:
        if isinstance(row, dict):
            dates.append(row.get('Date') or row.get('date') or row.get('日期') or row.get('交易日期'))
    # The endpoint is symbol-scoped; when no symbol field exists the URL is
    # the authoritative symbol identity.  A recognizable date must still
    # belong to the requested calendar month.
    if dates and not any(_date_matches_period(value, year_month) for value in dates):
        raise RuntimeError('TWSE_HISTORY_RESPONSE_IDENTITY_MISMATCH')

def _fetch_history_candidate(url, stock_no, year_month, candidate_index, max_redirects=MAX_REDIRECTS):
    diagnostics = []
    current = url
    redirects = 0
    # Three transient attempts plus a finite redirect budget. Redirects are
    # state transitions, not retries, and therefore must not consume the
    # transient retry allowance.
    for attempt in range(1, 4 + max_redirects):
        try:
            req = Request(current, headers={
                'User-Agent': 'RATE-Data-Engine/1.0',
                'Accept': 'application/json',
                'Accept-Language': 'zh-TW,zh;q=0.9',
                'Referer': 'https://www.twse.com.tw/zh/',
                'Connection': 'close',
            })
            with urlopen(req, timeout=30) as response:
                body = response.read()
                status = response.status
                ctype = response.headers.get('Content-Type', '')
            item = {'symbol': stock_no, 'period': year_month, 'candidate_index': candidate_index,
                    'request_url': current, 'http_status': status, 'redirect_location': None,
                    'resolved_redirect_url': None, 'redirect_count': redirects,
                    'content_type': ctype, 'response_bytes': len(body), 'attempt': attempt,
                    'transport_result': 'HTTP_200'}
            diagnostics.append(item)
            if not body:
                item['transport_result'] = 'EMPTY_RESPONSE'
                raise RuntimeError('TWSE_HISTORY_EMPTY_RESPONSE')
            if 'json' not in ctype.lower():
                item['transport_result'] = 'NON_JSON_RESPONSE'
                raise RuntimeError('TWSE_HISTORY_NON_JSON_RESPONSE')
            try:
                payload = json.loads(body.decode('utf-8-sig'))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                item['transport_result'] = 'JSON_PARSE_FAILURE'
                raise RuntimeError('TWSE_HISTORY_NON_JSON_RESPONSE') from exc
            if not isinstance(payload, dict) or (payload.get('stat') is not None and payload.get('stat') != 'OK') or not payload.get('data'):
                item['transport_result'] = 'EMPTY_OR_NON_OK_DATA'
                raise RuntimeError('TWSE_HISTORY_EMPTY_DATA')
            _validate_history_identity(payload, stock_no, year_month)
            item['transport_result'] = 'PASS'
            return payload, hashlib.sha256(body).hexdigest(), diagnostics, current
        except HTTPError as exc:
            location = exc.headers.get('Location') if exc.headers else None
            item = {'symbol': stock_no, 'period': year_month, 'candidate_index': candidate_index,
                    'request_url': current, 'http_status': exc.code,
                    'redirect_location': location, 'resolved_redirect_url': None,
                    'redirect_count': redirects, 'content_type': exc.headers.get('Content-Type', '') if exc.headers else '',
                    'response_bytes': 0, 'attempt': attempt,
                    'transport_result': f'HTTP_{exc.code}'}
            diagnostics.append(item)
            if exc.code in (307, 308):
                if not location:
                    error = RuntimeError('TWSE_REDIRECT_MISSING_LOCATION'); error.diagnostics = diagnostics; raise error
                if redirects >= max_redirects:
                    error = RuntimeError('TWSE_REDIRECT_LOOP_OR_LIMIT'); error.diagnostics = diagnostics; raise error
                resolved = urljoin(current, location)
                parsed = urlparse(resolved)
                item['resolved_redirect_url'] = resolved
                if parsed.scheme.lower() != 'https' or (parsed.hostname or '').lower() not in APPROVED_REDIRECT_HOSTS:
                    item['transport_result'] = 'UNSAFE_REDIRECT_TARGET'
                    error = RuntimeError('TWSE_UNSAFE_REDIRECT_TARGET'); error.diagnostics = diagnostics; raise error
                redirects += 1
                current = resolved
                continue
            # Non-redirect HTTP failures are not retried as redirects; the
            # outer candidate loop may proceed to the official fallback.
            error = RuntimeError(f'TWSE_HISTORY_HTTP_{exc.code}'); error.diagnostics = diagnostics; raise error from exc
        except (IncompleteRead, URLError, TimeoutError, ConnectionError) as exc:
            diagnostics.append({'symbol': stock_no, 'period': year_month, 'candidate_index': candidate_index,
                                'request_url': current, 'http_status': None, 'redirect_location': None,
                                'resolved_redirect_url': None, 'redirect_count': redirects,
                                'content_type': '', 'response_bytes': 0, 'attempt': attempt,
                                'transport_result': type(exc).__name__})
            if attempt < 3:
                time.sleep(2 ** (attempt - 1))
                continue
            error = RuntimeError(f'TWSE_HISTORY_TRANSPORT_{type(exc).__name__}'); error.diagnostics = diagnostics; raise error from exc
        except RuntimeError as exc:
            exc.diagnostics = diagnostics
            raise
    raise RuntimeError('TWSE_HISTORY_RETRY_EXHAUSTED')
class TWSEAdapter:
    provider = "TWSE Official OpenAPI"
    def fetch_daily(self):
        endpoint = BASE + "/exchangeReport/STOCK_DAY_ALL"
        payload, digest = fetch_json(endpoint)
        return provenance("market_daily", self.provider, endpoint, digest, payload)
    def fetch_benchmark(self):
        endpoint = BASE + "/exchangeReport/MI_INDEX"
        payload, digest = fetch_json(endpoint)
        return provenance("benchmark", self.provider, endpoint, digest, payload)
    def fetch_t86(self, trading_date: str):
        date = trading_date.replace('-', '')
        endpoint = f"https://www.twse.com.tw/rwd/zh/fund/T86?date={date}&selectType=ALLBUT0999&response=json"
        req = Request(endpoint, headers={"Accept":"application/json"})
        try:
            with urlopen(req, timeout=30) as resp:
                body = resp.read(); status = resp.status; ctype = resp.headers.get('Content-Type','')
        except Exception as exc:
            raise RuntimeError(f"FAIL:T86_HTTP_ERROR:{type(exc).__name__}") from exc
        diag = {'http_status':status,'content_type':ctype,'response_received':bool(body),'body_sha256':hashlib.sha256(body).hexdigest(),'response_bytes':len(body)}
        if not body: raise RuntimeError('FAIL:T86_EMPTY_RESPONSE')
        if 'json' not in ctype.lower(): raise RuntimeError('FAIL:T86_NON_JSON_RESPONSE')
        try: payload=json.loads(body.decode('utf-8'))
        except (UnicodeDecodeError,json.JSONDecodeError) as exc: raise RuntimeError('FAIL:T86_NON_JSON_RESPONSE') from exc
        out = provenance('institutional_listed', self.provider, endpoint, diag['body_sha256'], payload); out['diagnostics']=diag; out['trading_date']=trading_date; return out
    def fetch_symbol_master(self):
        endpoint = BASE + "/opendata/t187ap03_L"
        payload, digest = fetch_json(endpoint)
        return provenance("trading_symbol_master", self.provider, endpoint, digest, payload)
    def fetch_monthly_revenue(self):
        endpoint = BASE + "/opendata/t187ap05_L"
        payload, digest = fetch_json(endpoint)
        return provenance("fundamental_revenue", self.provider, endpoint, digest, payload)
    def fetch_historical_symbol(self, stock_no: str, year_month: str):
        endpoint = f"https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?date={year_month}01&stockNo={stock_no}&response=json"
        # TWSE's official exchangeReport route is a transport fallback for
        # intermittent CDN 307/security responses from the RWD route.  Both
        # are official date-aware monthly products; no alternate data vendor
        # or synthetic value is introduced.
        endpoints = [
            endpoint,
            f"https://www.twse.com.tw/exchangeReport/STOCK_DAY?response=json&date={year_month}01&stockNo={stock_no}",
        ]
        all_diagnostics = []
        last = None
        for index, candidate in enumerate(endpoints):
            try:
                payload, digest, diagnostics, final_endpoint = _fetch_history_candidate(candidate, stock_no, year_month, index)
                all_diagnostics.extend(diagnostics)
                out = provenance("market_daily_history", self.provider, final_endpoint, digest, payload)
                out['diagnostics'] = {'requests': all_diagnostics, 'final_endpoint': final_endpoint,
                                      'redirect_count': max((x.get('redirect_count', 0) for x in all_diagnostics), default=0)}
                return out
            except Exception as exc:
                last = exc
                diagnostics = getattr(exc, 'diagnostics', None)
                if diagnostics:
                    all_diagnostics.extend(diagnostics)
                # Unsafe redirects and identity failures are hard stops. A
                # normal transport failure permits the official fallback.
                if str(exc) in ('TWSE_UNSAFE_REDIRECT_TARGET', 'TWSE_HISTORY_RESPONSE_IDENTITY_MISMATCH'):
                    break
        detail = str(last) if last else 'UNKNOWN'
        error = RuntimeError(f"TWSE_HISTORICAL_RETRIEVAL_FAILED:{stock_no}:{year_month}:{detail}")
        error.diagnostics = all_diagnostics
        raise error from last
    def fetch_historical_benchmark(self, year_month: str):
        endpoints = [os.getenv('TWSE_BENCHMARK_HISTORY_ENDPOINT', 'https://www.twse.com.tw/rwd/zh/TAIEX/MI_5MINS_HIST'), 'https://www.twse.com.tw/indicesReport/MI_5MINS_HIST']
        diagnostics=[]
        for base in endpoints:
            endpoint = base + ('&' if '?' in base else '?') + f'date={year_month}01&response=json'
            req=Request(endpoint,headers={'User-Agent':'RATE-Data-Engine/1.0','Accept':'application/json','Accept-Language':'zh-TW,zh;q=0.9'})
            try:
                with urlopen(req,timeout=30) as resp: body=resp.read(); status=resp.status; ctype=resp.headers.get('Content-Type','')
            except HTTPError as exc:
                diagnostics.append({'endpoint':endpoint,'transport_result':f'HTTP_{exc.code}','http_status':exc.code}); continue
            except URLError as exc:
                diagnostics.append({'endpoint':endpoint,'transport_result':'CONNECT_FAILURE','detail':type(exc.reason).__name__}); continue
            if not body: diagnostics.append({'endpoint':endpoint,'transport_result':'EMPTY_DATA','http_status':status}); continue
            try: payload=json.loads(body.decode('utf-8'))
            except (UnicodeDecodeError,json.JSONDecodeError): diagnostics.append({'endpoint':endpoint,'transport_result':'INVALID_JSON','http_status':status,'content_type':ctype,'response_bytes':len(body)}); continue
            if payload.get('stat') != 'OK' or not payload.get('data'): diagnostics.append({'endpoint':endpoint,'transport_result':'TWSE_STAT_NOT_OK','http_status':status,'stat':payload.get('stat'),'row_count':len(payload.get('data',[]))}); continue
            digest=hashlib.sha256(body).hexdigest(); out=provenance('benchmark_history',self.provider,endpoint,digest,payload); out['diagnostics']={'endpoint_attempts':diagnostics+[{'endpoint':endpoint,'transport_result':'PASS','http_status':status,'content_type':ctype,'response_bytes':len(body),'stat':payload.get('stat'),'row_count':len(payload.get('data',[]))}]}; return out
        raise RuntimeError('LIVE_TAIEX_SOURCE_UNAVAILABLE:'+json.dumps(diagnostics,ensure_ascii=False,separators=(',',':')))
    @staticmethod
    def normalize_daily(record: dict) -> dict:
        return {"symbol":record.get("Code"), "trade_date":record.get("Date"),
                "open":record.get("OpeningPrice"), "high":record.get("HighestPrice"),
                "low":record.get("LowestPrice"), "close":record.get("ClosingPrice"),
                "volume":record.get("TradeVolume"), "turnover":record.get("TradeValue"),
                "source":"TWSE Official OpenAPI"}
