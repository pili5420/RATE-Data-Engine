"""Probe official fundamental historical transport contracts only.

This command intentionally does not run stock history, institutional replay,
TDCC replay, Stage replay, Phase A2, 07:30, or source-bundle assembly.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.sources.fundamental_history import MOPSHistoricalFundamentalAdapter  # noqa: E402


REVENUE_PROBES = (
    ("TWSE", "2026-08"),
    ("TWSE", "2026-07"),
    ("TWSE", "2026-06"),
    ("TPEX", "2026-08"),
    ("TPEX", "2026-07"),
    ("TPEX", "2026-06"),
)

EPS_PROBES = (
    ("TWSE", 2026, 2),
    ("TWSE", 2026, 1),
    ("TWSE", 2025, 4),
    ("TWSE", 2025, 3),
    ("TPEX", 2026, 2),
    ("TPEX", 2026, 1),
    ("TPEX", 2025, 4),
    ("TPEX", 2025, 3),
)


def _now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _write(path, value):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _load_universe(path):
    if not path:
        return []
    obj = json.loads(Path(path).read_text(encoding="utf-8"))
    entries = obj.get("symbols", obj) if isinstance(obj, dict) else obj
    result = []
    for entry in entries:
        if isinstance(entry, str):
            result.append({"symbol": entry, "market": None})
        elif isinstance(entry, dict) and entry.get("symbol"):
            result.append({"symbol": str(entry["symbol"]), "market": entry.get("market")})
    return result


def _hit_count(rows, universe, market):
    wanted = {row["symbol"] for row in universe if row.get("market") in (None, market)}
    if not wanted:
        return 0
    returned = {str(row.get("symbol")) for row in rows}
    return len(wanted & returned)


def _latest_diag(adapter, domain):
    for diag in reversed(adapter.diagnostics):
        if diag.get("domain") == domain:
            return diag
    return {}


def probe_revenue(adapter, universe):
    probes = []
    pass_count = 0
    for market, period in REVENUE_PROBES:
        item = {"market": market, "requested_period": period, "validation_status": "FAIL"}
        try:
            rows = adapter.fetch_revenue_period(market, period)
            diag = _latest_diag(adapter, "revenue")
            returned = sorted({row.get("revenue_period") for row in rows if row.get("revenue_period")})
            item.update({
                "validation_status": "PASS" if returned == [period] else "FAIL",
                "official_endpoint": rows[0]["endpoint"] if rows else diag.get("final_url"),
                "http_status": diag.get("http_status"),
                "content_type": diag.get("content_type"),
                "body_sha256": diag.get("body_sha256"),
                "encoding": "auto:utf-8-sig/big5/cp950",
                "table_count": len(diag.get("schema_header", [])),
                "schema": diag.get("schema_header"),
                "row_count": len(rows),
                "distinct_row_level_periods": returned,
                "universe_symbol_hits": _hit_count(rows, universe, market),
                "official_disclosure_date_field": "出表日期",
                "period_identity_source": diag.get("period_identity_source"),
                "archive_variant": "t21sc03_roc_month_0",
            })
            if item["validation_status"] == "PASS":
                pass_count += 1
        except Exception as exc:
            diag = _latest_diag(adapter, "revenue")
            item.update({
                "blocking_reason": str(exc),
                "official_endpoint": diag.get("final_url"),
                "http_status": diag.get("http_status"),
                "content_type": diag.get("content_type"),
                "body_sha256": diag.get("body_sha256"),
                "response_bytes": diag.get("response_bytes"),
            })
        probes.append(item)
    coverage = sum(1 for row in universe if row.get("symbol"))
    archive_contract = "VERIFIED" if pass_count == len(REVENUE_PROBES) and coverage == 30 else "UNVERIFIED"
    return {
        "artifact": "RATE_CER073_REVENUE_CONTRACT_EVIDENCE",
        "validation_status": "PASS" if pass_count == len(REVENUE_PROBES) else "FAIL",
        "probe_pass_count": pass_count,
        "probe_total": len(REVENUE_PROBES),
        "period_identity_source": "ROW_LEVEL_OFFICIAL_FIELD",
        "archive_variant_contract": archive_contract,
        "foreign_ky_revenue_coverage": f"{coverage}/30" if coverage else "0/30",
        "monthly_revenue_historical_transport_contract": "VERIFIED" if pass_count == len(REVENUE_PROBES) and archive_contract == "VERIFIED" else "FAIL",
        "probes": probes,
        "retrieval_timestamp": _now(),
    }


def probe_eps(adapter, universe):
    probes = []
    pass_count = 0
    for market, year, quarter in EPS_PROBES:
        item = {"market": market, "requested_year": year, "requested_quarter": quarter, "validation_status": "FAIL"}
        try:
            rows = adapter.fetch_eps_period(market, year, quarter)
            diag = _latest_diag(adapter, "eps")
            returned = sorted({(row.get("fiscal_year"), row.get("quarter")) for row in rows})
            item.update({
                "validation_status": "PASS" if returned == [(year, quarter)] else "FAIL",
                "official_endpoint": rows[0]["endpoint"] if rows else diag.get("final_url"),
                "http_status": diag.get("http_status"),
                "content_type": diag.get("content_type"),
                "body_sha256": diag.get("body_sha256"),
                "schema": diag.get("schema_header"),
                "row_count": len(rows),
                "company_symbol": rows[0]["symbol"] if rows else None,
                "eps_field": "基本每股盈餘",
                "source_semantics": rows[0]["source_semantics"] if rows else None,
                "accounting_category": "UNVERIFIED_CATEGORY_AUTHORITY",
                "official_disclosure_date": rows[0]["official_disclosure_date"] if rows else None,
                "returned_periods": [{"fiscal_year": y, "quarter": q} for y, q in returned],
                "universe_symbol_hits": _hit_count(rows, universe, market),
            })
            if item["validation_status"] == "PASS":
                pass_count += 1
        except Exception as exc:
            diag = _latest_diag(adapter, "eps")
            item.update({
                "blocking_reason": str(exc),
                "official_endpoint": diag.get("final_url"),
                "http_status": diag.get("http_status"),
                "content_type": diag.get("content_type"),
                "body_sha256": diag.get("body_sha256"),
                "response_bytes": diag.get("response_bytes"),
            })
        probes.append(item)
    category_status = "FAIL"
    return {
        "artifact": "RATE_CER073_EPS_CONTRACT_EVIDENCE",
        "validation_status": "PASS" if pass_count == len(EPS_PROBES) and category_status == "PASS" else "FAIL",
        "probe_pass_count": pass_count,
        "probe_total": len(EPS_PROBES),
        "eps_returned_period_identity": "PASS" if pass_count == len(EPS_PROBES) else "FAIL",
        "eps_accounting_category_authority": category_status,
        "eps_historical_transport_contract": "VERIFIED" if pass_count == len(EPS_PROBES) and category_status == "PASS" else "FAIL",
        "probes": probes,
        "retrieval_timestamp": _now(),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--universe-file", default=os.getenv("RATE_UNIVERSE_FILE"))
    parser.add_argument("--revenue-output", default="artifacts/RATE_CER073_REVENUE_CONTRACT_EVIDENCE.json")
    parser.add_argument("--eps-output", default="artifacts/RATE_CER073_EPS_CONTRACT_EVIDENCE.json")
    args = parser.parse_args()

    universe = _load_universe(args.universe_file)
    adapter = MOPSHistoricalFundamentalAdapter()
    revenue = probe_revenue(adapter, universe)
    eps = probe_eps(adapter, universe)
    _write(args.revenue_output, revenue)
    _write(args.eps_output, eps)

    summary = {
        "revenue": f"{revenue['probe_pass_count']}/{revenue['probe_total']}",
        "eps": f"{eps['probe_pass_count']}/{eps['probe_total']}",
        "validation_status": "PASS" if revenue["validation_status"] == "PASS" and eps["validation_status"] == "PASS" else "FAIL",
    }
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0 if summary["validation_status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
