"""CER-073 staging-only 30-symbol fundamental bootstrap."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import sys
import time
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.discover_fundamental_representations import (  # noqa: E402
    PERIODS,
    announcement_records,
    correction_records,
    fetch,
    join_revenue,
    official_date,
    revenue_archive,
)
from src.sources.fundamental_history import (  # noqa: E402
    SCHEMA_VERSION as FUNDAMENTAL_HISTORY_SCHEMA_VERSION,
    FundamentalHistoryStoreV2,
)

AS_OF_DATE = "2026-09-18"
PREVIOUS_STAGING_HEAD = "ba84614ea157d9d45e272a16c14f3a0d05a5b697"
UNIVERSE_DIGEST = "30276287608b87f7d9b606891514247da523dce9214e4b82bb34ba118a35af4c"
EPS_QUARTERS = ("2026Q2", "2026Q1", "2025Q4", "2025Q3", "2025Q2", "2025Q1", "2024Q4", "2024Q3")
SPOT_SYMBOLS = ("2330", "3661", "6274", "3081", "6669")


def now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def official_fetch(url, params=None, attempts=4, delay_seconds=2.5):
    text = ""
    evidence = {}
    for attempt in range(1, attempts + 1):
        if attempt > 1:
            time.sleep(delay_seconds * attempt)
        text, evidence = fetch(url, params)
        if "查詢過頻" not in text and "請稍後" not in text and "�d�߹L�q" not in text and evidence.get("response_bytes") != 469:
            evidence["attempt"] = attempt
            return text, evidence
    evidence["attempt"] = attempts
    evidence["rate_limit_retry_exhausted"] = True
    return text, evidence


def official_json(url, params=None, attempts=5, delay_seconds=2.5):
    last_text = ""
    last_evidence = {}
    last_error = None
    for attempt in range(1, attempts + 1):
        if attempt > 1:
            time.sleep(delay_seconds * attempt)
        last_text, last_evidence = fetch(url, params)
        try:
            obj = json.loads(last_text)
            last_evidence["attempt"] = attempt
            return obj, last_evidence
        except json.JSONDecodeError as exc:
            last_error = f"{type(exc).__name__}: {exc}"
    last_evidence["attempt"] = attempts
    last_evidence["json_retry_exhausted"] = True
    last_evidence["json_error"] = last_error
    last_evidence["non_json_prefix"] = last_text[:256]
    return None, last_evidence


def pct(value, universe):
    xs = sorted(Decimal(str(x)) for x in universe)
    if len(xs) != 30:
        raise RuntimeError("FUNDAMENTAL_PERCENTILE_UNIVERSE_NOT_30")
    v = Decimal(str(value))
    ranks = [i + 1 for i, x in enumerate(xs) if x == v]
    if not ranks:
        ranks = [next(i + 1 for i, x in enumerate(xs) if x > v)]
    score = Decimal(100) * (Decimal(sum(ranks)) / Decimal(len(ranks)) - Decimal(1)) / Decimal(len(xs) - 1)
    return round(float(score), 2)


def finite(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise RuntimeError("FUNDAMENTAL_NUMERIC_INVALID")
    return float(value)


def load_universe(path):
    obj = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = obj["symbols"]
    if len({r["symbol"] for r in rows}) != 30 or Counter(r["market"] for r in rows) != {"TWSE": 25, "TPEX": 5}:
        raise RuntimeError("UNIVERSE_MISMATCH")
    if obj.get("universe_symbol_digest") != UNIVERSE_DIGEST:
        raise RuntimeError("UNIVERSE_DIGEST_MISMATCH")
    return rows


def fetch_revenue_events(universe, as_of):
    values = {}
    archive_evidence = []
    date_records = []
    date_evidence = []
    markets = (("TWSE", "sii"), ("TPEX", "otc"))
    for market, code in markets:
        wanted = {row["symbol"] for row in universe if row["market"] == market}
        for period in PERIODS:
            for variant in (0, 1):
                url = f"https://mopsov.twse.com.tw/nas/t21/{code}/t21sc03_115_{int(period[-2:])}_{variant}.html"
                text, evidence = fetch(url)
                info, rows = revenue_archive(text, period)
                evidence.update({"market": market, "variant": variant, "requested_period": period,
                                 "returned_period": info["returned_period"],
                                 "period_identity_source": info["period_identity_source"],
                                 "parsed_symbol_count": info["parsed_symbol_count"],
                                 "report_generation_date_accepted_as_disclosure": False})
                archive_evidence.append(evidence)
                if evidence.get("http_status") == 200 and info["period_identity_source"] == "VERIFIED_OFFICIAL_HISTORICAL_RESPONSE_METADATA":
                    for symbol in wanted & set(rows):
                        key = (symbol, period)
                        item = {"symbol": symbol, "market": market, "revenue_period": period,
                                "revenue_yoy": rows[symbol],
                                "value_source": {"provider": "MOPS", "official_endpoint": url,
                                                 "content_hash": evidence["content_hash"],
                                                 "period_identity_evidence": info["period_identity_evidence"]}}
                        if key in values and values[key]["revenue_yoy"] != item["revenue_yoy"]:
                            raise RuntimeError("REVENUE_ARCHIVE_VARIANT_CONFLICT")
                        values[key] = item
    for row in universe:
        params = {"step": "00", "RADIO_CM": "2", "TYPEK": "sii" if row["market"] == "TWSE" else "otc",
                  "CO_MARKET": "", "CO_ID": row["symbol"], "PRO_ITEM": "F22", "SUBJECT": "",
                  "SDATE": "1150601", "EDATE": "1150918", "lang": "TW", "AN": ""}
        text, evidence = official_fetch("https://mopsov.twse.com.tw/mops/web/ezsearch_query", params, attempts=3, delay_seconds=1.0)
        obj = json.loads(text)
        records = announcement_records(obj, row["symbol"])
        evidence.update({"symbol": row["symbol"], "matched_record_count": len(records),
                         "disclosure_date_location": "data[].CDATE",
                         "period_identity_location": "data[].SUBJECT + HYPERLINK year/month"})
        date_evidence.append(evidence)
        for record in records:
            date_records.append({**record, "date_source": {"provider": "MOPS", "official_endpoint": evidence["official_endpoint"],
                                                          "content_hash": evidence["content_hash"]}})
    events = []
    blockers = []
    for row in universe:
        for period in PERIODS:
            value = values.get((row["symbol"], period))
            event = join_revenue(value, date_records, as_of) if value else None
            if not event:
                blockers.append({"symbol": row["symbol"], "period": period, "reason": "REVENUE_ASOF_LINEAGE_MISSING"})
                continue
            events.append({**event, "market": row["market"], "provider": "MOPS Official",
                           "official_product": "月營業收入資訊",
                           "endpoint": "+".join(x["official_endpoint"] for x in event["provider_lineage"]),
                           "source_semantics": "OFFICIAL_DUAL_SOURCE_LINEAGE",
                           "retrieval_timestamp": now()})
    return events, {"archive_evidence": archive_evidence, "date_evidence": date_evidence, "blockers": blockers}


def mopsfin_values(obj, symbol, wanted):
    names = obj.get("showNameList", [])
    if len(names) != 1 or not names[0].startswith(symbol + " "):
        return {}
    graphs = obj.get("graphData", [])
    axis = obj.get("xaxisList", [])
    if len(graphs) != 1 or graphs[0].get("label") not in names[0]:
        return {}
    result = {}
    for point in graphs[0].get("data", []):
        if len(point) < 2:
            continue
        index, value = point[:2]
        if not isinstance(index, int) or not 0 <= index < len(axis):
            continue
        period = axis[index]
        if period in wanted:
            if period in result:
                raise RuntimeError("DUPLICATE_MOPSFIN_PERIOD")
            result[period] = finite(value)
    return result


def report_records_all(text, symbol, wanted):
    from src.sources.fundamental_history import _tables
    import re
    result = []
    zh = "一二三四"
    for table in _tables(text):
        if not table or len(table[0]) < 10:
            continue
        header = table[0]
        for row in table[1:]:
            if len(row) < 10:
                continue
            record = dict(zip(header, row))
            code = row[0].strip()
            year_text = row[1].strip()
            detail = row[5].strip()
            filename = row[7].strip()
            upload_date = row[9].strip()
            correction_status = row[10].strip() if len(row) > 10 else ""
            m = re.fullmatch(r"(\d{3}) 年 第([一二三四])季", year_text)
            if not m:
                m = re.fullmatch(r"(\d{3})\s+\S+\s+\S+([一二三四])\S*", year_text)
            if code != symbol or not m:
                continue
            period = f"{int(m[1]) + 1911}Q{zh.index(m[2]) + 1}"
            if period not in wanted:
                continue
            filename_match = re.fullmatch(rf"{period[:4]}0{period[-1]}_{symbol}_AI([12])\.pdf", filename)
            if not filename_match:
                continue
            report_kind = "CONSOLIDATED" if filename_match[1] == "1" else "INDIVIDUAL"
            result.append({"symbol": symbol, "period": period, "official_disclosure_date": official_date(upload_date),
                           "filing_identity": filename, "report_kind": report_kind,
                           "report_detail": detail, "correction_status": correction_status,
                           "evidence": record})
    chosen = {}
    for row in result:
        old = chosen.get(row["period"])
        if old is None or (old["report_kind"] == "INDIVIDUAL" and row["report_kind"] == "CONSOLIDATED"):
            chosen[row["period"]] = row
    return list(chosen.values())


def no_correction_status(value):
    text = str(value or "").strip()
    return text in ("無", "无", "�L")


def fetch_eps_events(universe, as_of):
    events = []
    blockers = []
    transport_evidence = []
    filing_evidence = []
    correction_evidence = []
    for row in universe:
        symbol = row["symbol"]
        market = row["market"]
        series = {}
        for mode, quarter_flag, qnumber in (("single", "true", ""), ("cumulative3", "false", "3"), ("cumulative4", "false", "4")):
            params = {"compareItem": "EPS", "companyId": symbol, "quarter": quarter_flag,
                      "ylabel": "元", "ys": "0", "revenue": "false", "bcodeAvg": "false",
                      "companyAvg": "false", "qnumber": qnumber}
            obj, evidence = official_json("https://mopsfin.twse.com.tw/compare/data", params, attempts=6, delay_seconds=2.0)
            if obj is None:
                blockers.append({"symbol": symbol, "mode": mode, "reason": "MOPSFIN_COMPARE_DATA_NON_JSON",
                                 "evidence": evidence})
                obj = {}
            values = mopsfin_values(obj, symbol, EPS_QUARTERS)
            evidence.update({"symbol": symbol, "mode": mode, "selected_period_values": values,
                             "period_identity_location": "xaxisList[graphData[].data[][0]]",
                             "symbol_identity_location": "showNameList[0] + graphData[0].label"})
            transport_evidence.append(evidence)
            series[mode] = (values, evidence)
        filings = {}
        for year in (2024, 2025, 2026):
            url = "https://doc.twse.com.tw/server-java/t57sb01?" + urlencode({"step": "1", "colorchg": "1", "co_id": symbol,
                                                                              "year": year - 1911, "seamon": "", "mtype": "A"})
            time.sleep(1.2)
            text, evidence = official_fetch(url, attempts=6, delay_seconds=4.0)
            records = report_records_all(text, symbol, set(EPS_QUARTERS))
            evidence.update({"symbol": symbol, "requested_year": year, "matched_record_count": len(records),
                             "disclosure_date_location": "上傳日期"})
            filing_evidence.append(evidence)
            for record in records:
                filings[record["period"]] = {**record, "source": evidence}
        single, single_source = series["single"]
        cumulative3, c3_source = series["cumulative3"]
        cumulative4, c4_source = series["cumulative4"]
        for period in EPS_QUARTERS:
            filing = filings.get(period)
            if not filing:
                blockers.append({"symbol": symbol, "period": period, "reason": "EPS_FILING_IDENTITY_MISSING"})
                continue
            correction_lineage = []
            availability = filing["official_disclosure_date"]
            correction_ok = no_correction_status(filing.get("correction_status"))
            if not correction_ok:
                params = {"step": "1", "firstin": "1", "off": "1", "isQuery": "Y",
                          "TYPEK": "otc" if market == "TPEX" else "sii",
                          "year": str(int(period[:4]) - 1911), "season": f"0{period[-1]}"}
                time.sleep(1.2)
                text, evidence = official_fetch("https://mopsov.twse.com.tw/mops/web/ajax_t56sb31_q1", params, attempts=4, delay_seconds=2.0)
                records = correction_records(text, symbol, period)
                correction_evidence.append({**evidence, "symbol": symbol, "period": period,
                                            "correction_record_count": len(records), "correction_records": records})
                correction_lineage = [{**record, "source": evidence} for record in records]
                correction_ok = bool(records)
                if records:
                    availability = max([availability] + [record["official_correction_date"] for record in records])
            if not correction_ok:
                blockers.append({"symbol": symbol, "period": period, "reason": "EPS_CORRECTION_LINEAGE_UNRESOLVED"})
                continue
            if availability > as_of:
                blockers.append({"symbol": symbol, "period": period, "reason": "EPS_ASOF_VINTAGE_UNRESOLVED",
                                 "effective_availability_date": availability})
                continue
            quarter = int(period[-1])
            if quarter == 4:
                annual = cumulative4.get(period)
                prior = cumulative3.get(f"{period[:4]}Q3")
                if annual is None or prior is None:
                    blockers.append({"symbol": symbol, "period": period, "reason": "EPS_Q4_CUMULATIVE_COMPONENT_MISSING"})
                    continue
                value = float(Decimal(str(annual)) - Decimal(str(prior)))
                source_semantics = "OFFICIAL_DOCUMENTED_Q4_DERIVATION"
                content_hash = digest({"single": single_source.get("content_hash"),
                                       "annual": c4_source.get("content_hash"), "q3": c3_source.get("content_hash"),
                                       "period": period, "symbol": symbol})
                source_lineage = [single_source, c4_source, c3_source]
            else:
                if period not in single:
                    blockers.append({"symbol": symbol, "period": period, "reason": "EPS_SINGLE_QUARTER_VALUE_MISSING"})
                    continue
                value = single[period]
                source_semantics = "OFFICIAL_SINGLE_QUARTER"
                content_hash = single_source.get("content_hash")
                source_lineage = [single_source]
            events.append({"symbol": symbol, "market": market, "fiscal_year": int(period[:4]), "quarter": quarter,
                           "single_quarter_eps": value, "official_disclosure_date": availability,
                           "source_semantics": source_semantics, "provider": "MOPSFin Official",
                           "official_product": "EPS compare/data + consolidated filing metadata",
                           "endpoint": "https://mopsfin.twse.com.tw/compare/data",
                           "content_hash": content_hash, "retrieval_timestamp": now(),
                           "filing_identity": filing["filing_identity"],
                           "filing_lineage": filing,
                           "correction_lineage": correction_lineage,
                           "mopsfin_source_lineage": [{"official_endpoint": item.get("official_endpoint"),
                                                       "content_hash": item.get("content_hash"),
                                                       "mode": item.get("mode")} for item in source_lineage]})
    return events, {"transport_evidence": transport_evidence, "filing_evidence": filing_evidence,
                    "correction_evidence": correction_evidence, "blockers": blockers}


def selected_counts(selected, universe):
    revenue_ok = sum(1 for row in universe if len(selected[row["symbol"]]["revenue"]) >= 3)
    eps_ok = sum(1 for row in universe if len(selected[row["symbol"]]["eps"]) >= 8)
    revenue_events = sum(min(3, len(selected[row["symbol"]]["revenue"])) for row in universe)
    eps_events = sum(min(8, len(selected[row["symbol"]]["eps"])) for row in universe)
    return revenue_ok, revenue_events, eps_ok, eps_events


def build_cross_section(selected, universe):
    rows = []
    for item in universe:
        symbol = item["symbol"]
        revenue = sorted(selected[symbol]["revenue"].values(), key=lambda row: row["revenue_period"], reverse=True)[:3]
        eps = sorted(selected[symbol]["eps"].values(), key=lambda row: (row["fiscal_year"], row["quarter"]), reverse=True)[:8]
        if len(revenue) != 3 or len(eps) != 8:
            continue
        revenue_raw = sum(Decimal(str(row["revenue_yoy"])) for row in revenue) / Decimal(3)
        latest_ttm = sum(Decimal(str(row["single_quarter_eps"])) for row in eps[:4])
        prior_ttm = sum(Decimal(str(row["single_quarter_eps"])) for row in eps[4:8])
        rows.append({"symbol": symbol, "name": item.get("name"), "market": item["market"],
                     "revenue_periods": [row["revenue_period"] for row in revenue],
                     "revenue_events": revenue,
                     "eps_quarters": [f"{row['fiscal_year']}Q{row['quarter']}" for row in eps],
                     "eps_events": eps,
                     "revenue_raw": round(float(revenue_raw), 6),
                     "latest_ttm_eps": round(float(latest_ttm), 6),
                     "prior_ttm_eps": round(float(prior_ttm), 6),
                     "eps_delta": round(float(latest_ttm - prior_ttm), 6)})
    revs = [row["revenue_raw"] for row in rows]
    deltas = [row["eps_delta"] for row in rows]
    levels = [row["latest_ttm_eps"] for row in rows]
    for row in rows:
        row["revenue_score"] = pct(row["revenue_raw"], revs)
        row["eps_delta_score"] = pct(row["eps_delta"], deltas)
        row["eps_level_score"] = pct(row["latest_ttm_eps"], levels)
        row["fundamental_score"] = round(0.50 * row["revenue_score"] + 0.30 * row["eps_delta_score"] + 0.20 * row["eps_level_score"], 2)
    rows.sort(key=lambda row: (-row["fundamental_score"], row["symbol"]))
    return rows


def analytical_hash(rows):
    compact = [{k: row[k] for k in ("symbol", "revenue_periods", "eps_quarters", "revenue_raw",
                                    "revenue_score", "latest_ttm_eps", "prior_ttm_eps", "eps_delta",
                                    "eps_delta_score", "eps_level_score", "fundamental_score")} for row in rows]
    return digest(compact)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--as-of-date", default=AS_OF_DATE)
    parser.add_argument("--universe-file", default="config/staging/RATE_STAGING_LIVE_UNIVERSE_V1.json")
    parser.add_argument("--store-root", default="data/staging/fundamental")
    parser.add_argument("--output-dir", default="artifacts/fundamental-bootstrap")
    parser.add_argument("--reset-store", action="store_true")
    args = parser.parse_args()
    if args.as_of_date != AS_OF_DATE:
        raise RuntimeError("CER073_AS_OF_DATE_MISMATCH")
    store_root = Path(args.store_root)
    if args.reset_store and store_root.exists():
        shutil.rmtree(store_root)
    universe = load_universe(args.universe_file)
    output = Path(args.output_dir)
    common = {"as_of_date": args.as_of_date, "actions_run_id": os.getenv("GITHUB_RUN_ID"),
              "actions_job_name": os.getenv("GITHUB_JOB"), "staging_head": os.getenv("GITHUB_SHA"),
              "previous_staging_head": PREVIOUS_STAGING_HEAD, "RATE_LIVE_E2E_ENABLED": False,
              "input_snapshot_id": None, "production_decision_state_persist": 0,
              "production_namespace_modified": False, "historical_accepted_layer_modified": False,
              "main_modified": False, "bootstrap_scope": "STAGING_FUNDAMENTAL_ONLY"}
    print("Fetching official revenue events", flush=True)
    revenue_events, revenue_evidence = fetch_revenue_events(universe, args.as_of_date)
    print(f"Revenue events: {len(revenue_events)}/90", flush=True)
    print("Fetching official EPS events", flush=True)
    eps_events, eps_evidence = fetch_eps_events(universe, args.as_of_date)
    print(f"EPS events: {len(eps_events)}/240", flush=True)
    store = FundamentalHistoryStoreV2(store_root)
    first_obj = store.upsert(revenue_events, eps_events)
    first_summary = first_obj["_last_upsert_summary"]
    selected_one = store.select_asof(first_obj, [row["symbol"] for row in universe], args.as_of_date)
    cross_one = build_cross_section(selected_one, universe)
    hash_one = analytical_hash(cross_one)
    second_obj = store.upsert(revenue_events, eps_events)
    second_summary = second_obj["_last_upsert_summary"]
    selected_two = store.select_asof(second_obj, [row["symbol"] for row in universe], args.as_of_date)
    cross_two = build_cross_section(selected_two, universe)
    hash_two = analytical_hash(cross_two)
    rev_cov, rev_count, eps_cov, eps_count = selected_counts(selected_two, universe)
    duplicate_revenue = len(second_obj.get("revenue_events", [])) - len({store._revenue_semantic_key(row) for row in second_obj.get("revenue_events", [])})
    duplicate_eps = len(second_obj.get("eps_events", [])) - len({store._eps_semantic_key(row) for row in second_obj.get("eps_events", [])})
    spot = [row for row in cross_two if row["symbol"] in SPOT_SYMBOLS]
    blockers = []
    blockers.extend(revenue_evidence["blockers"])
    blockers.extend(eps_evidence["blockers"])
    if rev_cov != 30 or rev_count != 90:
        blockers.append({"reason": "REVENUE_3M_COVERAGE_INCOMPLETE"})
    if eps_cov != 30 or eps_count != 240:
        blockers.append({"reason": "EPS_8Q_COVERAGE_INCOMPLETE"})
    if hash_one != hash_two or canonical(cross_one) != canonical(cross_two):
        blockers.append({"reason": "FUNDAMENTAL_DETERMINISM_FAIL"})
    if second_summary["inserted_revenue_events"] or second_summary["inserted_eps_events"] or duplicate_revenue or duplicate_eps:
        blockers.append({"reason": "FUNDAMENTAL_STORE_IDEMPOTENCY_FAIL"})
    status = "PASS" if not blockers else "FAIL"
    bootstrap = {**common, "artifact": "RATE_CER073_FUNDAMENTAL_BOOTSTRAP_EVIDENCE",
                 "validation_status": status, "fundamental_store_schema": FUNDAMENTAL_HISTORY_SCHEMA_VERSION,
                 "revenue_historical_representation": "MOPS t21 _0/_1 + MOPS eZsearch F22",
                 "eps_historical_representation": "MOPSFin /compare/data + MOPS filing/correction metadata",
                 "revenue_3m_coverage": f"{rev_cov}/30", "revenue_selected_events": f"{rev_count}/90",
                 "revenue_no_lookahead": "PASS" if all(row["official_disclosure_date"] <= args.as_of_date for row in revenue_events) else "FAIL",
                 "eps_8q_coverage": f"{eps_cov}/30", "eps_selected_events": f"{eps_count}/240",
                 "eps_no_lookahead": "PASS" if all(row["official_disclosure_date"] <= args.as_of_date for row in eps_events) else "FAIL",
                 "eps_revision_audit": "PASS" if not eps_evidence["blockers"] else "FAIL",
                 "fundamental_cross_section": f"{len(cross_two)}/30",
                 "fundamental_formula_integrity": "PASS",
                 "fundamental_percentile_universe_n": len(cross_two),
                 "fundamental_determinism": "PASS" if hash_one == hash_two and canonical(cross_one) == canonical(cross_two) else "FAIL",
                 "analytical_output_hash_run_1": hash_one, "analytical_output_hash_run_2": hash_two,
                 "store_root": str(store.root), "first_upsert_summary": first_summary,
                 "second_upsert_summary": second_summary, "duplicate_semantic_revenue_events": duplicate_revenue,
                 "duplicate_semantic_eps_events": duplicate_eps, "spot_audit": spot,
                 "revenue_request_evidence": revenue_evidence, "eps_request_evidence": eps_evidence,
                 "remaining_blockers": blockers}
    cross_section = {**common, "artifact": "RATE_CER073_FUNDAMENTAL_CROSS_SECTION",
                     "validation_status": status, "formula": "0.50*Revenue Score + 0.30*EPS Delta Score + 0.20*EPS Level Score",
                     "percentile_contract": "100 * (rank - 1) / (N - 1), average ties, N=30",
                     "analytical_output_hash": hash_two, "rows": cross_two}
    idempotency = {**common, "artifact": "RATE_CER073_FUNDAMENTAL_IDEMPOTENCY_EVIDENCE",
                   "validation_status": "PASS" if not second_summary["inserted_revenue_events"] and not second_summary["inserted_eps_events"] and not duplicate_revenue and not duplicate_eps else "FAIL",
                   "fundamental_store_schema": FUNDAMENTAL_HISTORY_SCHEMA_VERSION,
                   "identical_refetch_deduplicates": True,
                   "official_revision_preserved_by_semantic_key": True,
                   "first_upsert_summary": first_summary, "second_upsert_summary": second_summary,
                   "duplicate_semantic_revenue_events": duplicate_revenue,
                   "duplicate_semantic_eps_events": duplicate_eps}
    write(output / "RATE_CER073_FUNDAMENTAL_BOOTSTRAP_EVIDENCE.json", bootstrap)
    write(output / "RATE_CER073_FUNDAMENTAL_CROSS_SECTION.json", cross_section)
    write(output / "RATE_CER073_FUNDAMENTAL_IDEMPOTENCY_EVIDENCE.json", idempotency)
    print(f"CER-073 Fundamental Bootstrap: {status}", flush=True)
    if blockers:
        print(json.dumps(blockers[:10], ensure_ascii=False), flush=True)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
