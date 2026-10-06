"""Official security classification, independent from price/history availability."""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timezone
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from urllib.request import Request, urlopen

from .cer074_acceptance import sha256
from .production_live_state import require

POLICY_PATH = Path(__file__).resolve().parents[1] / "config/RATE_PHASE2_CHANGE_REQUEST_V1.json"
POLICY_ID = "CR-RATE-PHASE2-ELIGIBILITY-AND-FIRST-REFRESH-V1"
CLASSIFICATION_ENDPOINTS = {m: f"https://isin.twse.com.tw/isin/e_C_public.jsp?strMode={mode}"
                            for m, mode in (("TWSE", 2), ("TPEX", 4))}
LISTING_ENDPOINTS = {"TWSE": "https://openapi.twse.com.tw/v1/opendata/t187ap03_L",
                     "TPEX": "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O"}
NORMAL_LISTING_MARKETS = {"TWSE": {"TWSE LISTED", "TAIWAN INNOVATION BOARD"}, "TPEX": {"TPEx LISTED"}}


def approved_policy():
    policy = json.loads(POLICY_PATH.read_bytes())
    require(policy.get("policy_id") == POLICY_ID and policy.get("status") == "APPROVED"
            and policy.get("approved_by") == "CONTROL_CENTER"
            and policy.get("fallback_allowed") is False, "PHASE2_POLICY_NOT_APPROVED")
    return policy


def policy_hash():
    return sha256(approved_policy())


class SecurityTable(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows, self.text, self.row, self.cell = [], [], None, None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.row = []
        if tag in {"td", "th"}:
            self.cell = []

    def handle_data(self, value):
        self.text.append(value)
        if self.cell is not None:
            self.cell.append(value)

    def handle_endtag(self, tag):
        if tag in {"td", "th"} and self.cell is not None:
            if self.row is not None:
                self.row.append("".join(self.cell).strip())
            self.cell = None
        if tag == "tr" and self.row is not None:
            self.rows.append(self.row)
            self.row = None


def parse_classification(body, market):
    parser = SecurityTable()
    parser.feed(body.decode("big5"))
    updated = re.search(r"Date Stock Updated:\s*(\d{4}/\d{2}/\d{2})", "".join(parser.text))
    require(updated is not None, "CATALOGUE_ASOF_MISSING")
    as_of = date.fromisoformat(updated[1].replace("/", "-")).isoformat()
    header = ["Security Code & Security Name", "ISIN Code", "Date Listed", "Market", "Industrial Group", "CFICode", "Remarks"]
    require(header in parser.rows, "CATALOGUE_SCHEMA_INVALID")
    records, seen, section = [], set(), None
    started = False
    for row in parser.rows:
        if row == header:
            started = True
            continue
        if not started:
            continue
        if len(row) == 1:
            section = row[0]
            continue
        require(len(row) == 7, "CATALOGUE_RECORD_INVALID")
        symbol = row[0].split()[0]
        require(symbol not in seen and row[1] and section and row[5], "CATALOGUE_RECORD_INVALID")
        seen.add(symbol)
        normal = row[3] in NORMAL_LISTING_MARKETS[market]
        cfi = row[5]
        # ES is the official CFI ordinary/common-share group, not a symbol heuristic.
        common = cfi.startswith("ES")
        security_type = ("COMMON_STOCK" if common else "PREFERRED_SHARE" if cfi.startswith("EP")
                         else "WARRANT" if cfi.startswith("RW") else "BOND" if cfi.startswith("D")
                         else "ETF" if "ETF" in section.upper() else "ETN" if "ETN" in section.upper()
                         else "FUND_UNIT" if cfi.startswith("C") else "OTHER_NON_COMMON_EQUITY")
        eligible = common and normal
        records.append({"symbol": symbol, "market": market, "security_type": security_type,
                        "cfi_code": cfi, "official_section": section, "official_listing_market": row[3],
                        "isin": row[1], "eligibility": eligible, "eligible": eligible,
                        "eligibility_reason": "OFFICIAL_COMMON_EQUITY_NORMAL_LISTING" if eligible
                        else "DELISTED_OR_NON_NORMAL_LISTING" if not normal else "OFFICIAL_NON_COMMON_EQUITY"})
    require(records and any(row["eligible"] for row in records), "CATALOGUE_EMPTY")
    return as_of, records


def fetch_receipt(endpoint, *, html=False):
    request = Request(endpoint, headers={"User-Agent": "RATE-Phase2/1.0", "Accept": "text/html" if html else "application/json"})
    with urlopen(request, timeout=30) as response:
        require(response.geturl() == endpoint, "CATALOGUE_UNAPPROVED_REDIRECT")
        body = response.read()
        status, content_type = response.getcode(), response.headers.get("Content-Type", "")
    require(status == 200 and body, "CATALOGUE_TRANSPORT_FAILED")
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return body, {"endpoint": endpoint, "http_status": status, "content_type": content_type,
                  "response_bytes": len(body), "body_sha256": hashlib.sha256(body).hexdigest(),
                  "retrieved_at": now, "fallback_used": False}


def build_catalogue(trading_date, *, fetcher=fetch_receipt):
    date.fromisoformat(trading_date)
    policy = approved_policy()
    catalogue = {"artifact": "RATE_FULL_MARKET_ELIGIBILITY_CATALOGUE", "schema_version": "RATE-FULL-MARKET-CATALOGUE-V1",
                 "policy_id": POLICY_ID, "policy_hash": sha256(policy), "eligibility_policy_id": POLICY_ID,
                 "eligibility_policy_sha256": sha256(policy), "approved_by": "CONTROL_CENTER",
                 "universe_mode": "FULL_TAIWAN_ELIGIBLE_MARKET_UNIVERSE", "valid_scope": "NORMAL_PRODUCTION",
                 "trading_date": trading_date, "as_of": trading_date, "validation_status": "PASS",
                 "source_status": "PASS", "freshness_status": "PASS", "fallback_used": False,
                 "blocked_dependencies": [], "markets": []}
    for market in ("TWSE", "TPEX"):
        body, receipt = fetcher(CLASSIFICATION_ENDPOINTS[market], html=True)
        as_of, records = parse_classification(body, market)
        require(as_of == trading_date, "STALE_OR_FUTURE_CATALOGUE")
        listing_body, listing_receipt = fetcher(LISTING_ENDPOINTS[market])
        listed = json.loads(listing_body.decode("utf-8-sig"))
        require(isinstance(listed, list) and listed, "OFFICIAL_LISTING_CATALOGUE_EMPTY")
        key = "\u516c\u53f8\u4ee3\u865f" if market == "TWSE" else "SecuritiesCompanyCode"
        listed_symbols = [str(row[key]).strip() for row in listed]
        require(len(listed_symbols) == len(set(listed_symbols)), "OFFICIAL_LISTING_DUPLICATE")
        common_symbols = {row["symbol"] for row in records if row["eligible"]}
        require(set(listed_symbols).issubset({row["symbol"] for row in records}),
                "OFFICIAL_CLASSIFICATION_LISTING_COVERAGE_MISMATCH")
        catalogue["markets"].append({"market": market, "authority": market, "complete": True,
            "validation_status": "PASS", "record_count": len(records), "records": records, "records_sha256": sha256(records),
            "source_receipt": {"classification": {**receipt, "as_of": as_of, "record_count": len(records)},
                               "listing": {**listing_receipt, "record_count": len(listed)}},
            "listing_reconciliation": {"classification_is_eligibility_authority": True,
                "eligible_not_in_company_metadata": sorted(common_symbols - set(listed_symbols)),
                "listed_non_common_equity": sorted(set(listed_symbols) - common_symbols)}})
    all_rows = [row for market in catalogue["markets"] for row in market["records"]]
    catalogue.update(record_count=len(all_rows), eligible_count=sum(row["eligible"] for row in all_rows),
                     excluded_type_counts=dict(Counter(row["security_type"] for row in all_rows if not row["eligible"])))
    require(catalogue["eligible_count"] > 30, "PREVIOUS_TOP30_ONLY_UNIVERSE_FORBIDDEN")
    catalogue["content_hash"] = sha256(catalogue)
    catalogue["catalogue_id"] = "rate-full-market-catalogue-" + catalogue["content_hash"][:24]
    return catalogue


def validate_catalogue(catalogue, trading_date):
    require(catalogue.get("artifact") == "RATE_FULL_MARKET_ELIGIBILITY_CATALOGUE"
            and catalogue.get("policy_id") == POLICY_ID and catalogue.get("policy_hash") == policy_hash(),
            "ELIGIBILITY_POLICY_BINDING_INVALID")
    require(catalogue.get("trading_date") == catalogue.get("as_of") == trading_date, "STALE_OR_FUTURE_CATALOGUE")
    require(all(catalogue.get(key) == "PASS" for key in ("validation_status", "source_status", "freshness_status"))
            and catalogue.get("fallback_used") is False and catalogue.get("blocked_dependencies") == [],
            "FULL_MARKET_CATALOGUE_NOT_PASS")
    digest = sha256({key: value for key, value in catalogue.items() if key not in {"content_hash", "catalogue_id"}})
    require(catalogue.get("content_hash") == digest
            and catalogue.get("catalogue_id") == "rate-full-market-catalogue-" + digest[:24], "CATALOGUE_HASH_MISMATCH")
    require(sorted(m.get("market", "") for m in catalogue.get("markets", [])) == ["TPEX", "TWSE"],
            "FULL_MARKET_CATALOGUE_INCOMPLETE")
    all_rows = []
    for market in catalogue["markets"]:
        require(market.get("complete") is True and market.get("record_count") == len(market["records"])
                and market.get("records_sha256") == sha256(market["records"])
                and any(row.get("eligible") is True for row in market["records"]), "FULL_MARKET_CATALOGUE_INCOMPLETE")
        all_rows.extend(market["records"])
        receipt = market.get("source_receipt", {})
        require(receipt.get("classification", {}).get("endpoint") == CLASSIFICATION_ENDPOINTS[market["market"]]
                and receipt.get("listing", {}).get("endpoint") == LISTING_ENDPOINTS[market["market"]], "OFFICIAL_CATALOGUE_RECEIPT_REQUIRED")
        require(receipt["classification"].get("as_of") == trading_date
                and receipt["classification"].get("record_count") == len(market["records"]),
                "OFFICIAL_CATALOGUE_RECEIPT_REQUIRED")
        for item in receipt.values():
            require(item.get("http_status") == 200 and item.get("fallback_used") is False
                    and item.get("response_bytes", 0) > 0 and re.fullmatch(r"[0-9a-f]{64}", item.get("body_sha256", "")),
                    "OFFICIAL_CATALOGUE_RECEIPT_REQUIRED")
        for row in market["records"]:
            expected = row.get("cfi_code", "").startswith("ES") and row.get("official_listing_market") in NORMAL_LISTING_MARKETS[market["market"]]
            require(row.get("eligible") is expected and row.get("eligibility") is expected
                    and row.get("market") == market["market"], "ELIGIBILITY_DECISION_INVALID")
            if expected:
                require(row.get("security_type") == "COMMON_STOCK"
                        and row.get("eligibility_reason") == "OFFICIAL_COMMON_EQUITY_NORMAL_LISTING",
                        "ELIGIBILITY_DECISION_INVALID")
    require(catalogue.get("record_count") == len(all_rows)
            and catalogue.get("eligible_count") == sum(row["eligible"] for row in all_rows)
            and catalogue.get("excluded_type_counts") == dict(Counter(row["security_type"] for row in all_rows if not row["eligible"])),
            "CATALOGUE_COUNT_MISMATCH")
    return True
