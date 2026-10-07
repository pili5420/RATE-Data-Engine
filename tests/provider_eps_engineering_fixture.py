"""Generate clearly synthetic local response fixtures; no real provider bytes."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from urllib.parse import urlencode

from src.provider_eps_candidate import API, BASIC_LABEL, BOUNDARY, ENGINEERING, POLICY, WINDOW
from src.eps_duration_facts.raw import sha256


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=True, indent=2), encoding="utf-8")


def make_fixture(root):
    root = Path(root)
    (root / "raw").mkdir()
    (root / "receipts").mkdir()
    spec = json.loads((Path(__file__).parent / "fixtures/provider_eps_candidate/engineering_spec.json").read_text())
    values = spec["symbols"]
    ends = dict(zip(WINDOW, ("2024-09-30", "2024-12-31", "2025-03-31", "2025-06-30",
                            "2025-09-30", "2025-12-31", "2026-03-31", "2026-06-30")))
    groups = [(s, "2024-10-01", "2026-10-05" if s == "1340" else "2025-12-31",
               WINDOW[1:] if s == "1340" else WINDOW[1:6], "ORIGINAL_DIRECT_USE_17") for s in values]
    groups += [(s, "2024-07-01", "2024-09-30", WINDOW[:1], "NEW_FIXED_GAP_REQUEST") for s in values]
    groups += [(s, "2026-01-01", "2026-06-30", WINDOW[6:], "NEW_FIXED_GAP_REQUEST") for s in ("2330", "6488")]
    rows = []
    for group_index, (symbol, start, end, periods, origin) in enumerate(groups):
        ident = f"engineering-{symbol}-{group_index}"
        query = {"dataset": POLICY["dataset"], "data_id": symbol, "start_date": start, "end_date": end}
        payload_rows = [{"date": ends[periods[0]], "stock_id": symbol, "type": "Revenue",
                         "origin_name": "ENGINEERING_OTHER_FIELD", "value": 1}]
        for period in periods:
            payload_rows.append({"date": ends[period], "stock_id": symbol, "type": "EPS",
                                 "origin_name": BASIC_LABEL, "value": json.loads(values[symbol][WINDOW.index(period)])})
        payload = {"status": 200, "msg": "ENGINEERING_FIXTURE", "engineering_fixture": True, "data": payload_rows}
        body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        digest = sha256(body)
        raw_path = root / "raw" / (digest + ".json")
        raw_path.write_bytes(body)
        observed = datetime(2026, 10, 7, 12 if group_index < 3 else 15, 28, 0, tzinfo=timezone.utc) + timedelta(seconds=group_index)
        receipt = {"engineering_fixture": True, "id": ident, "requested_url": API, "query": query,
                   "http_status": 200, "final_url": API + "?" + urlencode(query),
                   "status": "SAMPLE_BODY_ACQUIRED", "raw_capture_status": "COMPLETE",
                   "content_encoding": None, "content_length": str(len(body)), "bytes": len(body),
                   "raw_path": "raw/" + raw_path.name, "response_body_sha256": digest,
                   "started_at": (observed - timedelta(seconds=1)).isoformat(),
                   "received_at": observed.isoformat(), "finished_at": (observed + timedelta(seconds=1)).isoformat()}
        receipt_path = root / "receipts" / (ident + ".json")
        write(receipt_path, receipt)
        for index, period in enumerate(periods, 1):
            raw_value = json.loads(body.decode())["data"][index]["value"]
            row = {**POLICY, **BOUNDARY, "symbol": symbol, "analysis_quarter": period,
                   "provider_date": ends[period], "provider_type": "EPS", "provider_origin_name": BASIC_LABEL,
                   "provider_basis_label": "BASIC", "provider_value": str(raw_value), "eps": str(raw_value),
                   "raw_row_index_zero_based": index, "json_locator": f"$.data[{index}]",
                   "raw_path": str(raw_path.resolve()), "receipt_reference": str(receipt_path.resolve()),
                   "response_sha256": digest, "receipt_sha256": sha256(receipt_path.read_bytes()),
                   "response_bytes": len(body), "observed_at": observed.isoformat(),
                   "acquisition_executed_at": observed.isoformat(), "filing_id": None, "revision_id": None,
                   "public_time": None, "same_public_version_status": "UNPROVEN",
                   "q4_raw_or_derived_classification": "UNPROVEN" if period.endswith("Q4") else "NOT_Q4_DATE",
                   "material_origin": origin, "official_numeric_corroboration": None}
            rows.append(row)
    policy = {**POLICY, **BOUNDARY, "local_analysis_eligible": True}
    manifest = {"engineering_fixture": True, "material_class": ENGINEERING, "policy": policy,
                "window_role": "LOCAL_ANALYSIS_WINDOW", "local_analysis_window": list(WINDOW),
                "generated_at": "2026-10-07T16:00:00+00:00", "merged_analysis_record_count": 24,
                "local_available_company_quarters": 24, "conflicts": [], "duplicate_keys": [], "missing_company_quarters": []}
    write(root / "merged_manifest.json", manifest)
    write(root / "analysis_input.json", {"metadata": deepcopy(manifest), "records": rows})
    write(root / "quarter_matrix.json", {"window": list(WINDOW), "cells": [
        {"symbol": r["symbol"], "analysis_quarter": r["analysis_quarter"], "eps": r["eps"]} for r in rows]})
    return root
