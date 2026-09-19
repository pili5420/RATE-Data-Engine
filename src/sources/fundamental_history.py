"""Official MOPS historical fundamental transports and revision-aware staging store."""
from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import date, datetime, timezone
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

SCHEMA_VERSION = "RATE-FUNDAMENTAL-HISTORY-V2"
MOPS_REVENUE_PAGE = "https://mops.twse.com.tw/mops/web/t21sc03"
MOPS_REVENUE_ARCHIVE = "https://mopsov.twse.com.tw/nas/t21/{market}/t21sc03_{roc_year}_{month}_0.html"
MOPS_EPS_PAGE = "https://mops.twse.com.tw/mops/web/t163sb04"
MOPS_EPS_ENDPOINT = "https://mopsov.twse.com.tw/mops/web/ajax_t163sb04"


def _now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _plain(value):
    return re.sub(r"\s+", " ", unescape(str(value))).strip()


def _number(value):
    text = _plain(value).replace(",", "").replace("％", "").replace("%", "")
    if text in ("", "-", "--", "N/A"):
        raise ValueError("FUNDAMENTAL_NUMERIC_MISSING")
    return float(text.replace("(", "-").replace(")", ""))


def normalize_official_date(value):
    text = _plain(value).replace("/", "-")
    digits = "".join(x for x in text if x.isdigit())
    if len(digits) == 8:
        year, month, day = int(digits[:4]), int(digits[4:6]), int(digits[6:])
    elif len(digits) == 7:
        year, month, day = int(digits[:3]) + 1911, int(digits[3:5]), int(digits[5:])
    else:
        m = re.search(r"(\d{2,3})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日", text)
        if not m:
            raise ValueError("DATA_INCOMPLETE:FUNDAMENTAL_DISCLOSURE_DATE")
        year, month, day = int(m.group(1)) + 1911, int(m.group(2)), int(m.group(3))
    if year < 1911:
        year += 1911
    return date(year, month, day).isoformat()


def normalize_revenue_period(value):
    text = _plain(value)
    digits = "".join(x for x in text if x.isdigit())
    if len(digits) == 6:
        year, month = int(digits[:4]), int(digits[4:6])
    elif len(digits) == 5:
        year, month = int(digits[:3]) + 1911, int(digits[3:5])
    else:
        m = re.search(r"(\d{2,4})\s*(?:年|/|-)?\s*(\d{1,2})\s*(?:月)?", text)
        if not m:
            raise ValueError("FUNDAMENTAL_REVENUE_PERIOD_IDENTITY_UNPROVEN")
        raw_year = int(m.group(1))
        year = raw_year + 1911 if raw_year < 1911 else raw_year
        month = int(m.group(2))
    if not 1 <= month <= 12:
        raise ValueError("FUNDAMENTAL_REVENUE_PERIOD_IDENTITY_UNPROVEN")
    return f"{year:04d}-{month:02d}"


def extract_disclosure_date(text):
    # Only an explicit official report/publication field is accepted. HTTP Date,
    # retrieval time and runtime source timestamps are intentionally excluded.
    patterns = (
        r"出表日期\s*[：:]?\s*([0-9]{2,4}[^\s<]{0,3}[0-9]{1,2}[^\s<]{0,3}[0-9]{1,2})",
        r"資料發布日期\s*[：:]?\s*([0-9]{2,4}[^\s<]{0,3}[0-9]{1,2}[^\s<]{0,3}[0-9]{1,2})",
        r"公告日期\s*[：:]?\s*([0-9]{2,4}[^\s<]{0,3}[0-9]{1,2}[^\s<]{0,3}[0-9]{1,2})",
    )
    plain = _plain(re.sub(r"<[^>]+>", " ", text))
    for pattern in patterns:
        found = re.search(pattern, plain)
        if found:
            return normalize_official_date(found.group(1))
    raise ValueError("DATA_INCOMPLETE:FUNDAMENTAL_DISCLOSURE_DATE")


class _TableParser(HTMLParser):
    def __init__(self):
        super().__init__(); self.tables=[]; self._stack=[]; self._cell=None
    def handle_starttag(self, tag, attrs):
        tag=tag.lower()
        if tag == "table":
            self._stack.append({"rows":[],"row":None})
        elif tag == "tr" and self._stack:
            self._stack[-1]["row"]=[]
        elif tag in ("th", "td") and self._stack and self._stack[-1]["row"] is not None:
            self._cell=[]
    def handle_data(self, data):
        if self._cell is not None: self._cell.append(data)
    def handle_endtag(self, tag):
        tag=tag.lower()
        if tag in ("th", "td") and self._cell is not None:
            if self._stack and self._stack[-1]["row"] is not None:
                self._stack[-1]["row"].append(_plain(" ".join(self._cell)))
            self._cell=None
        elif tag == "tr" and self._stack and self._stack[-1]["row"] is not None:
            row=self._stack[-1]["row"]
            if any(row): self._stack[-1]["rows"].append(row)
            self._stack[-1]["row"]=None
        elif tag == "table" and self._stack:
            table=self._stack.pop()["rows"]
            if table: self.tables.append(table)


def _tables(html):
    parser=_TableParser(); parser.feed(html); return parser.tables


def _header_index(header, candidates):
    normalized=[re.sub(r"\s+", "", x) for x in header]
    for i,value in enumerate(normalized):
        if any(candidate in value for candidate in candidates): return i
    return None


def _table_records(html, required):
    records=[]; schemas=[]
    for table in _tables(html):
        header_pos=None; indices=None
        for pos,row in enumerate(table[:8]):
            trial={key:_header_index(row,names) for key,names in required.items()}
            if all(value is not None for value in trial.values()):
                header_pos,indices=pos,trial; schemas.append(row); break
        if indices is None: continue
        width=max(indices.values())
        for row in table[header_pos+1:]:
            if len(row)<=width: continue
            item={key:row[index] for key,index in indices.items()}
            if re.fullmatch(r"[0-9A-Za-z]{4,6}", _plain(item.get("symbol"))): records.append(item)
    return records,schemas


def discover_eps_identity(html):
    plain=_plain(re.sub(r"<[^>]+>"," ",html))
    snippets=[]
    for pattern in (
        r"資料年度\s*[：:]?\s*(\d{2,4})\s*年?.{0,12}?第?\s*(\d{1,2})\s*季",
        r"(\d{2,4})\s*年.{0,12}?第?\s*(\d{1,2})\s*季",
        r"value=[\"']?(\d{2,3})[\"']?[^>]{0,120}selected[^>]{0,120}(?:年度|year)",
        r"(?:season|季別)[^>]{0,120}value=[\"']?(\d{1,2})[\"']?[^>]{0,120}selected",
    ):
        for found in re.finditer(pattern, html, flags=re.IGNORECASE):
            snippets.append(_plain(found.group(0))[:200])
    selected_years=[int(x)+1911 for x in re.findall(r"<option[^>]+value=[\"']?(\d{2,3})[\"']?[^>]*selected", html, flags=re.IGNORECASE)]
    selected_seasons=[int(x) for x in re.findall(r"<option[^>]+value=[\"']?0?([1-4])[\"']?[^>]*selected", html, flags=re.IGNORECASE)]
    title_match=re.search(r"資料年度\s*[：:]?\s*(\d{2,4})\s*年?.{0,12}?第?\s*(\d{1,2})\s*季",plain)
    if title_match:
        raw_year=int(title_match.group(1)); year=raw_year+1911 if raw_year < 1911 else raw_year
        return {"year":year,"quarter":int(title_match.group(2)),"identity_source":"OFFICIAL_RESPONSE_TITLE",
                "period_bearing_text_snippets":snippets[:8],"selected_years":selected_years,"selected_seasons":selected_seasons}
    if selected_years and selected_seasons:
        return {"year":selected_years[-1],"quarter":selected_seasons[-1],
                "identity_source":"OFFICIAL_RESPONSE_SELECTED_CONTROL",
                "period_bearing_text_snippets":snippets[:8],"selected_years":selected_years,"selected_seasons":selected_seasons}
    return {"year":None,"quarter":None,"identity_source":"UNPROVEN",
            "period_bearing_text_snippets":snippets[:8],"selected_years":selected_years,"selected_seasons":selected_seasons}


def _classify_body(body, content_type):
    sample=body[:4096].decode("utf-8",errors="ignore").lower()
    if "access denied" in sample or "captcha" in sample or "驗證碼" in sample or "系統忙碌" in sample:
        return "OFFICIAL_MOPS_TRANSPORT_BLOCKED_BY_EDGE_POLICY"
    if "html" in content_type.lower() or "<html" in sample or "<table" in sample: return "HTML"
    return "UNKNOWN"


class MOPSHistoricalFundamentalAdapter:
    provider="MOPS Official"
    revenue_request_granularity="MARKET_PERIOD"
    eps_request_granularity="MARKET_QUARTER"
    def __init__(self, opener=urlopen, min_interval_seconds=0.25):
        self.opener=opener; self.min_interval_seconds=min_interval_seconds; self._last=None
        self.request_count={"revenue":0,"eps":0}; self.diagnostics=[]
    def _open(self, request, domain, requested_period):
        if self._last is not None:
            time.sleep(max(0,self.min_interval_seconds-(time.monotonic()-self._last)))
        self._last=time.monotonic()
        try:
            response=self.opener(request,timeout=45)
            status=getattr(response,"status",response.getcode()); final_url=response.geturl()
            content_type=response.headers.get("Content-Type",""); body=response.read()
        except HTTPError as exc:
            raise RuntimeError(f"MOPS_{domain.upper()}_HTTP_{exc.code}") from exc
        except (URLError,TimeoutError,OSError) as exc:
            raise RuntimeError(f"MOPS_{domain.upper()}_TRANSPORT:{type(exc).__name__}") from exc
        classification=_classify_body(body,content_type)
        diag={"domain":domain,"requested_period":requested_period,"http_status":status,"final_url":final_url,
              "content_type":content_type,"response_bytes":len(body),"body_classification":classification,
              "body_sha256":hashlib.sha256(body).hexdigest(),"retrieval_timestamp":_now()}
        self.diagnostics.append(diag); self.request_count[domain]+=1
        if status != 200: raise RuntimeError(f"MOPS_{domain.upper()}_HTTP_{status}")
        if not body: raise RuntimeError(f"MOPS_{domain.upper()}_EMPTY_RESPONSE")
        if classification == "OFFICIAL_MOPS_TRANSPORT_BLOCKED_BY_EDGE_POLICY":
            raise RuntimeError(classification)
        if classification != "HTML": raise RuntimeError(f"MOPS_{domain.upper()}_NON_HTML_RESPONSE")
        encodings=("utf-8-sig","big5","cp950")
        head=body[:2048].decode("ascii",errors="ignore").lower()
        if "charset=big5" in head or "charset=ms950" in head:
            encodings=("big5","cp950","utf-8-sig")
        for encoding in encodings:
            try: return body.decode(encoding),diag
            except UnicodeDecodeError: pass
        raise RuntimeError(f"MOPS_{domain.upper()}_ENCODING_UNSUPPORTED")
    @staticmethod
    def _market(market): return "sii" if market == "TWSE" else "otc"
    def fetch_revenue_period(self, market, period):
        year,month=(int(x) for x in period.split("-")); roc=year-1911; mk=self._market(market)
        endpoint=MOPS_REVENUE_ARCHIVE.format(market=mk,roc_year=roc,month=month)
        html,diag=self._open(Request(endpoint,headers={"User-Agent":"RATE-Data-Engine/1.0"}),"revenue",period)
        rows,schemas=_table_records(html,{"symbol":("公司代號",),"period":("資料年月",),
                                          "yoy":("去年同月增減",),"disclosure":("出表日期",)})
        basic_rows,basic_schemas=_table_records(html,{"symbol":("公司代號",),"yoy":("去年同月增減",)})
        diag.update({"basic_schema_header":basic_schemas,"basic_row_count":len(basic_rows),
                     "parsed_symbols":sorted({_plain(row["symbol"]) for row in basic_rows})})
        normalized_rows=[]; returned_periods=set()
        for row in rows:
            try:
                row_period=normalize_revenue_period(row["period"])
            except ValueError:
                continue
            returned_periods.add(row_period)
            normalized_rows.append((row,row_period,normalize_official_date(row["disclosure"])))
        if not normalized_rows:
            raise RuntimeError("FUNDAMENTAL_REVENUE_PERIOD_IDENTITY_UNPROVEN")
        if returned_periods != {period}:
            returned=",".join(sorted(returned_periods)) or "NONE"
            raise RuntimeError(f"FUNDAMENTAL_REVENUE_PERIOD_IDENTITY_MISMATCH:{period}:{returned}")
        diag.update({"schema_header":schemas,"distinct_returned_periods":sorted(returned_periods),
                     "period_identity_source":"ROW_LEVEL_OFFICIAL_FIELD",
                     "official_disclosure_date_fields":"ROW_LEVEL 出表日期"})
        return [{"symbol":_plain(row["symbol"]),"market":market,"revenue_period":row_period,
                 "revenue_yoy":_number(row["yoy"]),"official_disclosure_date":disclosure,
                 "provider":self.provider,"official_product":"月營業收入資訊","endpoint":endpoint,
                 "content_hash":diag["body_sha256"],"retrieval_timestamp":diag["retrieval_timestamp"]}
                for row,row_period,disclosure in normalized_rows]
    def fetch_eps_period(self, market, fiscal_year, quarter):
        mk=self._market(market); period=f"{fiscal_year}Q{quarter}"
        params={"encodeURIComponent":"1","step":"1","firstin":"1","off":"1","isQuery":"Y",
                "TYPEK":mk,"year":str(fiscal_year-1911),"season":f"{quarter:02d}"}
        body=urlencode(params).encode("ascii")
        req=Request(MOPS_EPS_ENDPOINT,data=body,method="POST",headers={"User-Agent":"RATE-Data-Engine/1.0",
            "Content-Type":"application/x-www-form-urlencoded","Referer":MOPS_EPS_PAGE})
        html,diag=self._open(req,"eps",period)
        identity=discover_eps_identity(html)
        diag.update({"period_identity_candidates":identity})
        if identity["year"] is None or identity["quarter"] is None:
            raise RuntimeError("FUNDAMENTAL_EPS_PERIOD_IDENTITY_UNPROVEN")
        if identity["year"] != fiscal_year or identity["quarter"] != quarter:
            raise RuntimeError("FUNDAMENTAL_EPS_PERIOD_IDENTITY_MISMATCH")
        disclosure=extract_disclosure_date(html)
        rows,schemas=_table_records(html,{"symbol":("公司代號",),"eps":("基本每股盈餘",)})
        if not rows: raise RuntimeError("FUNDAMENTAL_EPS_SCHEMA_MISSING")
        diag.update({"schema_header":schemas,"returned_period":period,"official_disclosure_date":disclosure,
                     "period_identity_source":identity["identity_source"]})
        return [{"symbol":_plain(row["symbol"]),"market":market,"fiscal_year":fiscal_year,"quarter":quarter,
                 "single_quarter_eps":_number(row["eps"]),"official_disclosure_date":disclosure,
                 "source_semantics":"OFFICIAL_SINGLE_QUARTER","provider":self.provider,
                 "official_product":"綜合損益表","endpoint":MOPS_EPS_ENDPOINT,
                 "content_hash":diag["body_sha256"],"retrieval_timestamp":diag["retrieval_timestamp"]} for row in rows]


def _canonical(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"))


class FundamentalHistoryStoreV2:
    def __init__(self, root="data/staging/fundamental"):
        self.root=Path(root)
        if "production" in {part.lower() for part in self.root.parts}:
            raise RuntimeError("PRODUCTION_FUNDAMENTAL_NAMESPACE_FORBIDDEN")
        self.path=self.root/"RATE_FUNDAMENTAL_HISTORY_V2.json"
    def load(self):
        if not self.path.is_file():
            return {"schema_version":SCHEMA_VERSION,"revenue_events":[],"eps_events":[]}
        obj=json.loads(self.path.read_text(encoding="utf-8"))
        if obj.get("schema_version") != SCHEMA_VERSION: raise RuntimeError("FUNDAMENTAL_HISTORY_SCHEMA_MISMATCH")
        return obj
    def save(self,obj):
        obj={**obj,"schema_version":SCHEMA_VERSION,"updated_at":_now()}
        # Operational write time is not part of a historical snapshot's identity.
        payload=_canonical({k:v for k,v in obj.items() if k not in ("content_hash", "updated_at")})
        obj["content_hash"]=hashlib.sha256(payload.encode()).hexdigest()
        self.root.mkdir(parents=True,exist_ok=True)
        tmp=self.path.with_suffix(".tmp"); tmp.write_text(json.dumps(obj,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8"); tmp.replace(self.path)
    def upsert(self,revenue_events,eps_events):
        obj=self.load()
        for row in revenue_events:
            self._validate_revenue_event(row)
        for row in eps_events:
            self._validate_eps_event(row)
        for key,new_rows in (("revenue_events",revenue_events),("eps_events",eps_events)):
            seen={hashlib.sha256(_canonical(row).encode()).hexdigest() for row in obj[key]}
            for row in new_rows:
                digest=hashlib.sha256(_canonical(row).encode()).hexdigest()
                if digest not in seen: obj[key].append(row); seen.add(digest)
            obj[key].sort(key=lambda x:(str(x.get("symbol")),str(x.get("revenue_period",x.get("fiscal_year"))),str(x.get("quarter","")),str(x.get("official_disclosure_date"))))
        self.save(obj); return obj
    @staticmethod
    def _validate_revenue_event(row):
        required=("symbol","market","revenue_period","revenue_yoy","official_disclosure_date",
                  "provider","official_product","endpoint","content_hash","retrieval_timestamp")
        missing=[key for key in required if row.get(key) in (None,"")]
        if missing:
            raise RuntimeError("UNVERIFIED_REVENUE_EVENT:" + ",".join(missing))
        normalize_revenue_period(row["revenue_period"])
        normalize_official_date(row["official_disclosure_date"])
    @staticmethod
    def _validate_eps_event(row):
        required=("symbol","market","fiscal_year","quarter","single_quarter_eps","official_disclosure_date",
                  "source_semantics","provider","official_product","endpoint","content_hash","retrieval_timestamp")
        missing=[key for key in required if row.get(key) in (None,"")]
        if missing:
            raise RuntimeError("UNVERIFIED_EPS_EVENT:" + ",".join(missing))
        if row["source_semantics"] not in ("OFFICIAL_SINGLE_QUARTER","OFFICIAL_CUMULATIVE",
                                           "OFFICIAL_DOCUMENTED_Q4_DERIVATION"):
            raise RuntimeError("FUNDAMENTAL_EPS_SOURCE_SEMANTICS_INVALID")
        normalize_official_date(row["official_disclosure_date"])
    @staticmethod
    def select_asof(obj,universe,as_of_date):
        selected={str(s):{"revenue":{},"eps":{}} for s in universe}
        for row in obj.get("revenue_events",[]):
            symbol=str(row.get("symbol")); period=row.get("revenue_period"); disclosed=row.get("official_disclosure_date")
            if symbol not in selected or not period or not disclosed: continue
            if period <= as_of_date[:7] and disclosed <= as_of_date:
                old=selected[symbol]["revenue"].get(period)
                if old is None or old["official_disclosure_date"] < disclosed: selected[symbol]["revenue"][period]=row
        for row in obj.get("eps_events",[]):
            symbol=str(row.get("symbol")); disclosed=row.get("official_disclosure_date"); key=(row.get("fiscal_year"),row.get("quarter"))
            if symbol not in selected or None in key or not disclosed: continue
            if disclosed <= as_of_date:
                old=selected[symbol]["eps"].get(key)
                if old is None or old["official_disclosure_date"] < disclosed: selected[symbol]["eps"][key]=row
        return selected
