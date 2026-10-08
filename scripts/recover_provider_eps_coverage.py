"""Offline successor plan only: no transport import, credentials or requests."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.eps_duration_facts.model import require
from src.eps_duration_facts.raw import sha256
from src.provider_eps_candidate import _json, _quarter
from src.provider_eps_coverage import now, read_events, save, summary
from src.provider_eps_recovery import replay_archive, verify_archive
from verify_provider_eps_candidate import binding


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-manifest", required=True)
    parser.add_argument("--archive-sha256", required=True)
    parser.add_argument("--expected-base", required=True)
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    isolation = binding(args.expected_base, args.expected_head)
    manifest_path = Path(args.archive_manifest).resolve()
    require(sha256(manifest_path.read_bytes()) == args.archive_sha256, "ARCHIVE_MANIFEST_HASH_MISMATCH")
    output = Path(args.output_dir).resolve()
    manifest, parent = verify_archive(manifest_path)
    require(not output.is_relative_to(ROOT) and not output.is_relative_to(manifest_path.parent) and
            "rate-eps-public-research" in output.parts and
            not any(p.lower() in {"production", "latest", "state", "portfolio", "ledger"} for p in output.parts), "RECOVERY_OUTPUT_MUST_BE_EXTERNAL")
    require(not any(p.is_symlink() or (hasattr(p, "is_junction") and p.is_junction()) for p in (output, *output.parents)), "LINKED_OUTPUT_FORBIDDEN")
    started = now()
    root, plan, changes = replay_archive(manifest_path, output, {"base_sha": args.expected_base, "head_sha": args.expected_head})
    stop = {"reason": "OFFLINE_RECOVERY_COMPLETE_NO_MARKET_REQUESTS", "new_requests": 0}
    result = summary(root, plan, stop)
    events = read_events(root, plan)
    report = root / "reports" / ("report-" + now().replace(":", "").replace(".", ""))
    report.mkdir()
    save(report / "coverage-result.json", result)
    save(report / "request-ledger.json", {"plan_id": plan["plan_id"], "companies": list(events.values())})
    save(report / "before-after-matrix.json", {"parent_plan_id": parent["plan_id"], "plan_id": plan["plan_id"], "companies": changes})
    bank_replays = []
    for symbol in ("2801", "2812", "2816", "2820"):
        if symbol not in events:
            continue
        event = events[symbol]
        reference = event["receipt_references"][0]
        receipt = _json(Path(reference).read_bytes())
        body = _json((Path(reference).parent.parent / receipt["raw_path"]).read_bytes())
        bank_replays.append({"symbol": symbol, "old_status": event["recovery"]["old_status"], "new_status": event["status"],
            "receipt_reference": reference, "raw_sha256": receipt["response_body_sha256"], "raw_bytes": receipt["bytes"],
            "same_bytes_replay": True, "accepted_rows": event["rows"],
            "missing_quarters": [q for q in plan["window"] if q not in {r["analysis_quarter"] for r in event["rows"]}],
            "2026Q1_Q2_actual_raw_fields": [{"provider_date": r["date"], "provider_type": r["type"],
                "provider_origin_name": r["origin_name"], "json_locator": f"$.data[{i}]"}
                for i, r in enumerate(body["data"]) if _quarter(r["date"]) in {"2026Q1", "2026Q2"}]})
    save(report / "four-bank-same-bytes-replay.json", {"companies": bank_replays, "type_alias_added": False})
    old_execution = _json(Path(manifest["execution_reference"]).read_bytes())
    command = old_execution["command_without_credentials"].copy()
    command[command.index("--output-dir") + 1] = str(root)
    command[command.index("--expected-head") + 1] = args.expected_head
    save(report / "future-continuation.json", {"command_without_credentials": command, "executed": False,
        "prerequisites": ["Separate authorization after READY_FOR_REVIEW; no automatic scan",
            "Exact clean base/head, successor plan/parser/dispatch/transport/source hashes pass",
            "Single writer and no competing FinMind account/IP requests",
            "No persisted validation/shared-access/unknown-outcome gate",
            "280 requests / 3600 seconds / >=13 seconds, new session conservative wait"],
        "remaining_companies": result["counts"]["unattempted_companies"]})
    revenue_path = Path(manifest["execution_reference"]).parent / "revenue-availability.json"
    require(str(revenue_path) in manifest["files"], "REVENUE_REPORT_NOT_ARCHIVED")
    save(report / "revenue-availability.json", _json(revenue_path.read_bytes()))
    markets = {}
    for market in ("TWSE", "TPEX"):
        companies = [c for c in result["companies"] if c["market"] == market]
        markets[market] = {"accounted_for": sum(not c["unattempted"] for c in companies),
            "eps_complete_companies": sum(c["valid_quarters"] == 8 for c in companies),
            "valid_company_quarters": sum(c["valid_quarters"] for c in companies),
            "denominator": len(companies), "status_counts": dict(Counter(c["status"] for c in companies))}
    require(result["counts"]["new_plan_data_request_intents"] == 0, "RECOVERY_MUST_NOT_DISPATCH")
    verify_archive(manifest_path)
    require(isolation == binding(args.expected_base, args.expected_head), "PROTECTED_CODE_CHANGED")
    save(report / "invariance.json", {"old_sources_unchanged": True, "verified_file_count": len(manifest["files"]),
        "archive_manifest_reference": str(manifest_path), "archive_manifest_sha256": args.archive_sha256,
        "old_spacing_status": "UNPROVEN", "isolation": isolation})
    save(report / "execution.json", {"execution_type": "OFFLINE_VERSIONED_RECOVERY", "started_at": started,
        "finished_at": now(), "command_without_credentials": sys.argv, "code_binding": plan["code_binding"],
        "new_market_requests": 0, "inherited_requests": result["counts"]["inherited_data_requests"],
        "transport_imported": False, "stop": stop, "production_eligible": False})
    save(report / "RECOVERY_RESULT.json", {"status": "READY_FOR_REVIEW", "pr": 33, "counts": result["counts"],
        "market_counts": markets, "lineage": plan["recovery_lineage"], "plan_id": plan["plan_id"],
        "new_market_requests": 0, "reused_original_companies": sum(e["origin"] == "REUSED_ORIGINAL_24" for e in events.values()),
        "reused_original_quarters": sum(len(e["rows"]) for e in events.values() if e["origin"] == "REUSED_ORIGINAL_24"),
        "production_eligible": False, "provider_reply_required": False, "original_eight_quarter_coverage_credit": 0})
    print(json.dumps({"status": "READY_FOR_REVIEW", "report_dir": str(report), "plan_id": plan["plan_id"], "counts": result["counts"], "market_counts": markets}))


if __name__ == "__main__":
    main()
