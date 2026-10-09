"""Read-only official monthly archive bridge; existing RATE price normalizers."""
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import re
from urllib.parse import urlparse, parse_qs

from .eps_duration_facts.model import require
from .eps_duration_facts.raw import sha256
from .provider_eps_metadata import read_metadata
from .provider_eps_candidate import _time
from .provider_financial_features import instant
from .sources.tpex import HISTORICAL_ENDPOINT, INDEX_HISTORY_ENDPOINT
from .sources.twse import _validate_history_identity
from scripts.materialize_production_history_store import _twse_month_rows, _tpex_month_rows, _benchmark_month_rows
from scripts.build_production_source_bundle_from_official import _rows
from .benchmark_history import normalize_twse_date
from .sources.tpex import normalize_tpex_date


def verified_bytes(path, expected):
    data = Path(path).read_bytes()
    require(sha256(data) == expected, "FORWARD_PRICE_SOURCE_TAMPERED")
    return data


def verify_reference(reference):
    verified_bytes(reference["raw_path"], reference["raw_sha256"])
    verified_bytes(reference["receipt_path"], reference["receipt_sha256"])


def endpoint_ok(receipt):
    market, domain, period = receipt["market"], receipt["domain"], receipt["period"]
    require(market in ("TWSE", "TPEX") and domain in ("stock", "benchmark"), "FORWARD_PRICE_IDENTITY_INVALID")
    parsed = urlparse(receipt["endpoint"])
    query = parse_qs(parsed.query)
    require(parsed.scheme == "https" and not parsed.username and not parsed.password and not parsed.fragment and parsed.port is None, "FORWARD_PRICE_ENDPOINT_INVALID")
    if market == "TPEX":
        require(receipt["endpoint"] == (HISTORICAL_ENDPOINT if domain == "stock" else INDEX_HISTORY_ENDPOINT) and
            receipt["request_method"] == "POST" and receipt["request_params"]["date"] == f"{period[:4]}/{period[4:]}/01" and
            (domain != "stock" or receipt["request_params"]["code"] == receipt["symbol"]), "FORWARD_EXISTING_TPEX_PRODUCT_REQUIRED")
    else:
        paths = ("/rwd/zh/afterTrading/STOCK_DAY", "/exchangeReport/STOCK_DAY") if domain == "stock" else ("/rwd/zh/TAIEX/MI_5MINS_HIST", "/indicesReport/MI_5MINS_HIST")
        require(parsed.hostname == "www.twse.com.tw" and parsed.path in paths and query.get("date") == [period + "01"] and
            query.get("response") == ["json"] and (domain != "stock" or query.get("stockNo") == [receipt["symbol"]]) and receipt["request_method"] == "GET", "FORWARD_EXISTING_TWSE_PRODUCT_REQUIRED")


class ArchivedAdapter:
    def __init__(self, receipt, payload):
        self.receipt, self.payload = receipt, payload

    def fetch_historical_symbol(self, symbol, period):
        require((symbol, period) == (self.receipt["symbol"], self.receipt["period"]), "FORWARD_STOCK_BINDING")
        if self.receipt["market"] == "TWSE":
            _validate_history_identity(self.payload, symbol, period)
            require(str(self.payload.get("stockNo", "")) == symbol or re.search(r"(?<!\d)" + re.escape(symbol) + r"(?!\d)", str(self.payload.get("title", ""))), "FORWARD_TWSE_RAW_SYMBOL_IDENTITY")
        return self.result()

    def fetch_historical_benchmark(self, period):
        require(period == self.receipt["period"], "FORWARD_BENCHMARK_PERIOD")
        return self.result()

    def result(self):
        return {"raw_payload": self.payload, "retrieval_timestamp": self.receipt["observed_at"], "source_timestamp": self.receipt["observed_at"]}


def periods_between(start, end):
    cursor = date.fromisoformat(start).replace(day=1)
    result = []
    while cursor <= date.fromisoformat(end):
        result.append(cursor.strftime("%Y%m"))
        cursor = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
    return result


def load_prices(pin, *, as_of, available_at):
    manifest = read_metadata(verified_bytes(pin["manifest_path"], pin["manifest_sha256"]))
    if manifest.get("input_mode") == "OFFICIAL_MARKET_DAILY_FORWARD_INPUT_V1":
        from .provider_forward_daily_prices import load_daily_prices
        return load_daily_prices(pin, manifest, as_of=as_of, available_at=available_at)
    require(manifest["artifact_kind"] == "RATE_OFFICIAL_FORWARD_PRICE_ARCHIVE_MANIFEST_V1", "FORWARD_PRICE_MANIFEST_KIND")
    now = _time(as_of)
    require(_time(available_at) <= now <= _time(instant()), "FORWARD_FUTURE_PRICE_ASOF")
    through = manifest["sessions_complete_through"]
    taipei = timezone(timedelta(hours=8))
    start = _time(available_at).astimezone(taipei).date().isoformat()
    end = now.astimezone(taipei).date().isoformat()
    require(date.fromisoformat(through).isoformat() == through and start <= through <= end, "FORWARD_SESSION_COVERAGE_INVALID")
    expected_months = set(periods_between(start, through))
    benchmark_months, sessions, prices = {m: set() for m in ("TWSE", "TPEX")}, {m: {} for m in ("TWSE", "TPEX")}, {}
    seen = set()
    for source in manifest["sources"]:
        receipt = read_metadata(verified_bytes(source["receipt_path"], source["receipt_sha256"]))
        endpoint_ok(receipt)
        require(receipt["http_status"] == 200 and receipt["final_url"] == receipt["endpoint"] and
            _time(receipt["observed_at"]) <= now, "FORWARD_PRICE_HTTP_OR_OBSERVATION_INVALID")
        body = verified_bytes(receipt["raw_path"], receipt["raw_sha256"])
        require(len(body) == receipt["bytes"], "FORWARD_PRICE_BYTE_COUNT")
        key = (receipt["market"], receipt["domain"], receipt.get("symbol"), receipt["period"])
        require(key not in seen, "FORWARD_PRICE_DUPLICATE_ARCHIVE")
        seen.add(key)
        payload = read_metadata(body)
        adapter = ArchivedAdapter(receipt, payload)
        market, domain, period = receipt["market"], receipt["domain"], receipt["period"]
        require(period in expected_months, "FORWARD_PRICE_PERIOD_OUTSIDE_WINDOW")
        raw_rows = _rows(payload)
        require(raw_rows, "FORWARD_PRICE_EMPTY_RAW")
        for raw_row in raw_rows:
            raw_date = raw_row.get("trade_date") or raw_row.get("Date") or raw_row.get("日期")
            d = normalize_twse_date(raw_date) if market == "TWSE" else normalize_tpex_date(raw_date)
            require(date.fromisoformat(d).isoformat() == d and d.replace("-", "")[:6] == period and
                _time(d + "T13:30:00+08:00") <= _time(receipt["observed_at"]), "FORWARD_RAW_DATE_IDENTITY_OR_FUTURE")
            aliases = ("close", "ClosingPrice", "收盤價", "Close") if domain == "stock" else ("close", "ClosingIndex", "收盤指數", "收盤價")
            value = next((raw_row[k] for k in aliases if k in raw_row), None)
            if value not in (None, "", "-", "--"):
                from .provider_shadow_forward import number
                require(number(str(value).replace(",", "")) > 0, "FORWARD_PRICE_NONPOSITIVE")
        cutoff = (date.fromisoformat(through) + timedelta(days=1)).isoformat()
        if domain == "benchmark":
            rows = _benchmark_month_rows(adapter, market, period, cutoff)
            benchmark_months[market].add(period)
        else:
            rows = (_twse_month_rows if market == "TWSE" else _tpex_month_rows)(adapter, receipt["symbol"], period, cutoff)
        require(rows, "FORWARD_PRICE_EMPTY_OR_UNPARSABLE_ARCHIVE")
        for index, row in enumerate(rows):
            day = row["trade_date"]
            require(date.fromisoformat(day).isoformat() == day and day.replace("-", "")[:6] == period, "FORWARD_PRICE_DATE_IDENTITY")
            close_at = day + "T13:30:00+08:00"
            require(_time(close_at) <= _time(receipt["observed_at"]) <= now, "FORWARD_PRICE_BEFORE_CLOSE_OR_FUTURE")
            reference = {"raw_path": receipt["raw_path"], "raw_sha256": receipt["raw_sha256"],
                "receipt_path": source["receipt_path"], "receipt_sha256": source["receipt_sha256"],
                "normalized_row_index": index, "symbol": receipt.get("symbol"), "date": day, "market": market,
                "endpoint": receipt["endpoint"], "price_source": market + "_STOCK_DAY", "observed_at": receipt["observed_at"]}
            if domain == "benchmark":
                require(day not in sessions[market], "FORWARD_DUPLICATE_SESSION")
                sessions[market][day] = {"date": day, "close_at": close_at, "reference": reference}
            else:
                from .provider_shadow_forward import number
                require(number(row["close"]) > 0, "FORWARD_PRICE_NONPOSITIVE")
                key = (receipt["symbol"], day)
                require(key not in prices, "FORWARD_PRICE_DUPLICATE_OR_CONFLICT")
                prices[key] = {"close": str(row["close"]), "reference": reference}
    require(all(benchmark_months[m] == expected_months for m in benchmark_months), "FORWARD_BENCHMARK_MONTH_GAP")
    require(all(day in sessions[p["reference"]["market"]] for (_, day), p in prices.items()), "FORWARD_PRICE_NOT_MARKET_SESSION")
    return {"pin": pin, "manifest_sha256": pin["manifest_sha256"], "sessions": {m: [v for _, v in sorted(s.items())] for m, s in sessions.items()}, "prices": prices}
