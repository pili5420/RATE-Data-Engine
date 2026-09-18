from __future__ import annotations
from .base import fetch_json, provenance
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
import hashlib, json, csv, io
import os
import time
from http.client import IncompleteRead
from urllib.parse import urljoin, urlparse

BASE = "https://openapi.twse.com.tw/v1"
MAX_REDIRECTS = 3
APPROVED_REDIRECT_HOSTS = frozenset({"www.twse.com.tw"})
_LAST_HISTORY_REQUEST = 0.0
_TRANSPORT_METRICS = {
    'host': 'www.twse.com.tw', 'total_requests': 0, 'successful_requests': 0,
    'redirect_responses': 0, 'bare_307_count': 0, '429_count': 0,
    '5xx_count': 0, 'retry_count': 0, 'circuit_breaker_count': 0,
    'elapsed_seconds': 0.0,
}

def reset_transport_metrics():
    global _LAST_HISTORY_REQUEST
    _LAST_HISTORY_REQUEST = 0.0
    for key in _TRANSPORT_METRICS:
        if key not in ('host',): _TRANSPORT_METRICS[key] = 0 if key != 'elapsed_seconds' else 0.0

def get_transport_metrics():
    return dict(_TRANSPORT_METRICS)

def _is_host_transient(reason):
    return reason in ('TWSE_REDIRECT_MISSING_LOCATION', 'TWSE_HISTORY_HTTP_429',
                      'TWSE_HISTORY_HTTP_502', 'TWSE_HISTORY_HTTP_503',
                      'TWSE_HISTORY_HTTP_504', 'TWSE_HISTORY_TRANSPORT_IncompleteRead',
                      'TWSE_HISTORY_TRANSPORT_URLError', 'TWSE_HISTORY_TRANSPORT_TimeoutError')

def _sleep_backoff(seconds):
    # Keep deterministic/unit runs fast; staging Actions opts into the real
    # bounded delays with RATE_STAGING_REALTIME=1.
    if os.getenv('RATE_DETERMINISTIC_TEST') == '1':
        return
    time.sleep(seconds if os.getenv('RATE_STAGING_REALTIME') == '1' else min(seconds, 0.01))

def _pace_history_request():
    global _LAST_HISTORY_REQUEST
    interval = float(os.getenv('TWSE_HISTORY_MIN_INTERVAL_SECONDS', '1.5'))
    if os.getenv('RATE_DETERMINISTIC_TEST') == '1': interval = 0.0
    elapsed = time.monotonic() - _LAST_HISTORY_REQUEST
    if elapsed < interval: _sleep_backoff(interval - elapsed)
    _LAST_HISTORY_REQUEST = time.monotonic()

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
    if dates and not any(_date_matches_period(value, year_month) for value in dates):
        raise RuntimeError('TWSE_HISTORY_RESPONSE_IDENTITY_MISMATCH')

_CSV_HEADER_ALIASES = {
    'trade_date': ('日期', '交易日期', 'Date', 'date'),
    'volume': ('成交股數', '成交股數(股)', 'TradeVolume', 'volume'),
    'turnover': ('成交金額', 'TradeValue', 'turnover'),
    'open': ('開盤價', 'OpeningPrice', 'open'),
    'high': ('最高價', 'HighestPrice', 'high'),
    'low': ('最低價', 'LowestPrice', 'low'),
    'close': ('收盤價', 'ClosingPrice', 'close'),
    'change': ('漲跌價差', 'Change', 'change'),
    'transactions': ('成交筆數', 'Transactions', 'transactions'),
}

def _decode_csv(body):
    """Decode official TWSE CSV without replacement or silent corruption."""
    for encoding in ('utf-8-sig', 'cp950', 'big5'):
        try:
            return body.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    raise RuntimeError('TWSE_CSV_ENCODING_INVALID')

def _parse_history_csv(body, stock_no, year_month):
    text, encoding = _decode_csv(body)
    if '<html' in text[:512].lower() or '<!doctype' in text[:512].lower():
        raise RuntimeError('TWSE_CSV_NON_DATA_RESPONSE')
    rows = list(csv.reader(io.StringIO(text)))
    # Drop blank lines and TWSE title/preamble rows; the first row containing
    # the required date/price headers is the deterministic table header.
    rows = [[cell.strip() for cell in row] for row in rows if any(str(cell).strip() for cell in row)]
    header_index = next((i for i, row in enumerate(rows)
                         if any(alias in row for aliases in _CSV_HEADER_ALIASES.values() for alias in aliases)), None)
    if header_index is None:
        raise RuntimeError('TWSE_CSV_HEADER_INVALID')
    header = rows[header_index]
    selected = {}
    for key, aliases in _CSV_HEADER_ALIASES.items():
        for alias in aliases:
            if alias in header:
                selected[key] = header.index(alias)
                break
    required = ('trade_date', 'open', 'high', 'low', 'close', 'volume')
    if any(key not in selected for key in required):
        raise RuntimeError('TWSE_CSV_HEADER_INVALID')
    data = []
    for row in rows[header_index + 1:]:
        if len(row) <= max(selected.values()):
            continue
        date = row[selected['trade_date']]
        if not date or date.startswith('合計') or date.startswith('說明'):
            continue
        if not _date_matches_period(date, year_month):
            # Ignore footer rows, but reject a table with no matching dates.
            continue
        item = {key: row[index] for key, index in selected.items()}
        item['Date'] = item.pop('trade_date')
        aliases = {'open': 'OpeningPrice', 'high': 'HighestPrice', 'low': 'LowestPrice',
                   'close': 'ClosingPrice', 'volume': 'TradeVolume', 'turnover': 'TradeValue',
                   'change': 'Change', 'transactions': 'Transactions'}
        for key, out_key in aliases.items():
            if key in item:
                item[out_key] = item.pop(key)
        data.append(item)
    if not data:
        raise RuntimeError('TWSE_HISTORY_RESPONSE_IDENTITY_MISMATCH')
    payload = {'stat': 'OK', 'fields': list(data[0].keys()), 'data': data,
               'csv_encoding': encoding, 'csv_headers': header}
    return payload, encoding, header

def _fetch_history_candidate(url, stock_no, year_month, candidate_index, representation='JSON', max_redirects=MAX_REDIRECTS):
    diagnostics = []
    current = url
    redirects = 0
    # Three transient attempts plus a finite redirect budget. Redirects are
    # state transitions, not retries, and therefore must not consume the
    # transient retry allowance.
    for attempt in range(1, 4 + max_redirects):
        try:
            _pace_history_request()
            started = time.monotonic()
            _TRANSPORT_METRICS['total_requests'] += 1
            req = Request(current, headers={
                'User-Agent': 'RATE-Data-Engine/1.0',
                'Accept': 'application/json',
                'Accept-Language': 'zh-TW,zh;q=0.9',
                'Referer': 'https://www.twse.com.tw/zh/',
                'Connection': 'close',
            })
            with urlopen(req, timeout=float(os.getenv('TWSE_HISTORY_HTTP_TIMEOUT_SECONDS', '30'))) as response:
                body = response.read()
                status = response.status
                ctype = response.headers.get('Content-Type', '')
            item = {'symbol': stock_no, 'period': year_month, 'candidate_index': candidate_index,
                    'request_url': current, 'http_status': status, 'redirect_location': None,
                    'resolved_redirect_url': None, 'redirect_count': redirects,
                    'content_type': ctype, 'response_bytes': len(body), 'attempt': attempt,
                'transport_result': 'HTTP_200', 'representation': representation}
            diagnostics.append(item)
            _TRANSPORT_METRICS['elapsed_seconds'] += time.monotonic() - started
            if not body:
                item['transport_result'] = 'EMPTY_RESPONSE'
                raise RuntimeError('TWSE_HISTORY_EMPTY_RESPONSE')
            if representation == 'CSV':
                if 'json' in ctype.lower() or ('csv' not in ctype.lower() and 'text/plain' not in ctype.lower() and 'octet-stream' not in ctype.lower()):
                    # Some TWSE responses omit a useful content type. Parse
                    # only if the bytes are a valid official CSV table.
                    item['content_type_warning'] = 'CSV_CONTENT_TYPE_UNSPECIFIED'
                try:
                    payload, encoding, headers = _parse_history_csv(body, stock_no, year_month)
                except RuntimeError as exc:
                    item['transport_result'] = str(exc)
                    raise
                item['csv_encoding'] = encoding
                item['csv_headers'] = headers
            else:
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
            _TRANSPORT_METRICS['successful_requests'] += 1
            return payload, hashlib.sha256(body).hexdigest(), diagnostics, current
        except HTTPError as exc:
            _TRANSPORT_METRICS['elapsed_seconds'] += 0
            location = exc.headers.get('Location') if exc.headers else None
            item = {'symbol': stock_no, 'period': year_month, 'candidate_index': candidate_index,
                    'request_url': current, 'http_status': exc.code,
                    'redirect_location': location, 'resolved_redirect_url': None,
                    'redirect_count': redirects, 'content_type': exc.headers.get('Content-Type', '') if exc.headers else '',
                    'response_bytes': 0, 'attempt': attempt,
                    'transport_result': f'HTTP_{exc.code}'}
            retry_after = exc.headers.get('Retry-After') if exc.headers else None
            item['retry_after_present'] = retry_after is not None
            try: item['retry_after_seconds'] = float(retry_after) if retry_after is not None else None
            except (TypeError, ValueError): item['retry_after_seconds'] = None
            diagnostics.append(item)
            if exc.code == 429: _TRANSPORT_METRICS['429_count'] += 1
            if 500 <= exc.code <= 599: _TRANSPORT_METRICS['5xx_count'] += 1
            if exc.code in (307, 308):
                _TRANSPORT_METRICS['redirect_responses'] += 1
                if not location:
                    _TRANSPORT_METRICS['bare_307_count'] += 1
                    # A CDN edge may emit a bare 307 transiently. Retry the
                    # same official candidate a bounded number of times, then
                    # fail over without inventing a redirect target.
                    if attempt < 3:
                        item['transport_result'] = 'HTTP_307_MISSING_LOCATION_RETRY'
                        _TRANSPORT_METRICS['retry_count'] += 1
                        _sleep_backoff((5, 15, 30)[min(attempt - 1, 2)])
                        continue
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
            if exc.code in (429, 502, 503, 504) and attempt < 3:
                _TRANSPORT_METRICS['retry_count'] += 1
                delay = item.get('retry_after_seconds')
                _sleep_backoff(min(delay, 60.0) if delay is not None else (5, 15, 30)[min(attempt - 1, 2)])
                continue
            error = RuntimeError(f'TWSE_HISTORY_HTTP_{exc.code}'); error.diagnostics = diagnostics; raise error from exc
        except (IncompleteRead, URLError, TimeoutError, ConnectionError) as exc:
            _TRANSPORT_METRICS['retry_count'] += 1
            diagnostics.append({'symbol': stock_no, 'period': year_month, 'candidate_index': candidate_index,
                                'request_url': current, 'http_status': None, 'redirect_location': None,
                                'resolved_redirect_url': None, 'redirect_count': redirects,
                                'content_type': '', 'response_bytes': 0, 'attempt': attempt,
                                'transport_result': type(exc).__name__})
            if attempt < 3:
                _sleep_backoff((5, 15, 30)[min(attempt - 1, 2)])
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
    def fetch_historical_symbol(self, stock_no: str, year_month: str, force_representation: str | None = None):
        endpoint = f"https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?date={year_month}01&stockNo={stock_no}&response=json"
        # TWSE's official exchangeReport route is a transport fallback for
        # intermittent CDN 307/security responses from the RWD route.  Both
        # are official date-aware monthly products; no alternate data vendor
        # or synthetic value is introduced.
        endpoints = [
            (endpoint, 'JSON_PRIMARY'),
            (f"https://www.twse.com.tw/exchangeReport/STOCK_DAY?response=json&date={year_month}01&stockNo={stock_no}", 'JSON_FALLBACK'),
            # Official CSV action for the same two TWSE products.  The route
            # is derived only by changing the documented response format on
            # the official endpoint; no guessed host or redirect is used.
            (endpoint.replace('response=json', 'response=csv'), 'CSV_OFFICIAL'),
            (f"https://www.twse.com.tw/exchangeReport/STOCK_DAY?response=csv&date={year_month}01&stockNo={stock_no}", 'CSV_OFFICIAL'),
        ]
        if force_representation:
            endpoints = [item for item in endpoints if item[1] == force_representation]
        all_diagnostics = []
        last = None
        attempts = []
        error_reasons = []
        primary_retry_after_circuit = False
        for index, (candidate, representation) in enumerate(endpoints):
            try:
                payload, digest, diagnostics, final_endpoint = _fetch_history_candidate(candidate, stock_no, year_month, index, representation='CSV' if representation == 'CSV_OFFICIAL' else 'JSON')
                all_diagnostics.extend(diagnostics)
                out = provenance("market_daily_history", self.provider, final_endpoint, digest, payload)
                out['diagnostics'] = {'requests': all_diagnostics, 'final_endpoint': final_endpoint,
                                      'redirect_count': max((x.get('redirect_count', 0) for x in all_diagnostics), default=0),
                                      'representation': representation, 'candidate_index': index,
                                      'candidate_attempts': attempts + [{'candidate_index': index, 'representation': representation, 'status': 'PASS'}]}
                out['representation'] = representation
                out['csv_route_verification'] = ({'status': 'PASS', 'endpoint': final_endpoint,
                                                   'encoding': payload.get('csv_encoding'),
                                                   'headers': payload.get('csv_headers')}
                                                  if representation == 'CSV_OFFICIAL' else None)
                return out
            except Exception as exc:
                last = exc
                error_reasons.append(str(exc))
                diagnostics = getattr(exc, 'diagnostics', None)
                if diagnostics:
                    all_diagnostics.extend(diagnostics)
                attempts.append({'candidate_index': index, 'representation': representation, 'status': 'FAIL', 'reason': str(exc), 'requests': diagnostics or []})
                # In staging, a repeated host-level transient ends the bounded
                # chunk immediately.  This prevents a single unavailable host
                # from consuming the entire runner budget across fallback
                # representations; no data is accepted on this path.
                if (os.getenv('TWSE_STAGING_FAIL_FAST_HOST') == '1'
                        and _is_host_transient(str(exc))
                        and os.getenv('RATE_STAGING_REALTIME') == '1'):
                    _TRANSPORT_METRICS['circuit_breaker_count'] += 1
                    error = RuntimeError('TWSE_HOST_TEMPORARILY_UNAVAILABLE')
                    error.diagnostics = all_diagnostics; error.candidate_attempts = attempts
                    raise error from exc
                transient_reps = {a.get('representation') for a in attempts if _is_host_transient(a.get('reason'))}
                if len(transient_reps) >= 2 and not primary_retry_after_circuit and os.getenv('RATE_STAGING_REALTIME') == '1':
                    _TRANSPORT_METRICS['circuit_breaker_count'] += 1
                    primary_retry_after_circuit = True
                    _sleep_backoff(float(os.getenv('TWSE_HISTORY_CIRCUIT_COOLDOWN_SECONDS', '60')))
                    try:
                        payload, digest, retry_diag, final_endpoint = _fetch_history_candidate(endpoints[0][0], stock_no, year_month, 0, representation='JSON')
                        all_diagnostics.extend(retry_diag)
                        out = provenance('market_daily_history', self.provider, final_endpoint, digest, payload)
                        out['diagnostics'] = {'requests': all_diagnostics, 'final_endpoint': final_endpoint,
                                              'redirect_count': max((x.get('redirect_count', 0) for x in all_diagnostics), default=0),
                                              'representation': endpoints[0][1], 'candidate_index': 0,
                                              'candidate_attempts': attempts + [{'candidate_index': 0, 'representation': endpoints[0][1], 'status': 'PASS_AFTER_CIRCUIT'}]}
                        out['representation'] = endpoints[0][1]
                        out['csv_route_verification'] = None
                        return out
                    except Exception as retry_exc:
                        retry_diag = getattr(retry_exc, 'diagnostics', None)
                        if retry_diag: all_diagnostics.extend(retry_diag)
                        attempts.append({'candidate_index': 0, 'representation': endpoints[0][1], 'status': 'FAIL_AFTER_CIRCUIT', 'reason': str(retry_exc), 'requests': retry_diag or []})
                        error_reasons.append(str(retry_exc))
                        last = retry_exc
                        break
                # Unsafe redirects and identity failures are hard stops. A
                # normal transport failure permits the official fallback.
                if str(exc) in ('TWSE_UNSAFE_REDIRECT_TARGET', 'TWSE_HISTORY_RESPONSE_IDENTITY_MISMATCH') and representation != 'CSV_OFFICIAL':
                    break
        detail = '|'.join(dict.fromkeys(error_reasons)) if error_reasons else 'UNKNOWN'
        transient_reps = {a.get('representation') for a in attempts
                          if a.get('reason') in ('TWSE_REDIRECT_MISSING_LOCATION', 'TWSE_HISTORY_HTTP_429',
                                                 'TWSE_HISTORY_HTTP_502', 'TWSE_HISTORY_HTTP_503',
                                                 'TWSE_HISTORY_HTTP_504', 'TWSE_HISTORY_TRANSPORT_IncompleteRead',
                                                 'TWSE_HISTORY_TRANSPORT_URLError', 'TWSE_HISTORY_TRANSPORT_TimeoutError')}
        if len(transient_reps) >= 2 and any(a.get('reason') == 'TWSE_REDIRECT_MISSING_LOCATION' for a in attempts):
            _TRANSPORT_METRICS['circuit_breaker_count'] += 1
            detail = 'TWSE_HOST_TEMPORARILY_UNAVAILABLE|' + detail
        error = RuntimeError(f"TWSE_HISTORICAL_RETRIEVAL_FAILED:{stock_no}:{year_month}:{detail}")
        error.diagnostics = all_diagnostics
        error.candidate_attempts = attempts
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
