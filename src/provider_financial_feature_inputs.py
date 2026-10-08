"""Thin offline bridge to existing coverage and official revenue validators."""
from pathlib import Path

from .eps_duration_facts.model import require
from .eps_duration_facts.raw import sha256
from .full_market_history import digest
from .provider_eps_candidate import _canonical
from .provider_eps_coverage import load_universe, read_events, validate_plan
from .provider_eps_handoff import fingerprints, verify_parent_archive
from .provider_eps_metadata import read_metadata, validate_dispatches
from .sources.fundamental_history import _warmup_revenue_rows, _decode_response, validate_revenue_semantics
from .sources.mops_raw_evidence import load_response


def verify_file(path, expected):
    body = Path(path).read_bytes()
    require(len(body) == expected["bytes"] and sha256(body) == expected["sha256"], "FEATURE_SOURCE_FILE_TAMPERED:" + str(path))
    return body


def verify_snapshot(snapshot):
    for path, expected in snapshot.items():
        verify_file(path, expected)


def load_closeout(manifest_reference, expected_sha256):
    """Financial values are replayed from raw, not trusted from a readiness boolean."""
    path = Path(manifest_reference).resolve()
    body = path.read_bytes()
    require(sha256(body) == expected_sha256, "FEATURE_CLOSEOUT_MANIFEST_TAMPERED")
    manifest = read_metadata(body)
    require(manifest["excluded_self"] == path.name, "FEATURE_CLOSEOUT_MANIFEST_IDENTITY")
    verify_snapshot(manifest["files"])
    closeout = path.parent
    result_path = closeout / "CLOSEOUT_RESULT.json"
    require(str(result_path) in manifest["files"], "FEATURE_CLOSEOUT_RESULT_UNBOUND")
    result = read_metadata(result_path.read_bytes())
    before = read_metadata((closeout / "input-hashes-before.json").read_bytes())
    require(before == read_metadata((closeout / "input-hashes-after.json").read_bytes()), "FEATURE_CLOSEOUT_INVARIANCE_INVALID")
    verify_snapshot(before)
    root = Path(result["coverage_root"])
    plan = read_metadata((root / "plan.json").read_bytes())
    validate_plan(plan)
    require(plan["plan_id"] == result["plan_id"] and plan["code_binding"]["head_sha"] == result["execution_head"], "FEATURE_COVERAGE_IDENTITY_MISMATCH")
    universe = plan["universe"]
    require(load_universe(universe["source_path"], universe["source_file_sha256"], universe["source_commit"]) == universe, "FEATURE_CATALOGUE_MISMATCH")
    lineage = plan["recovery_lineage"]
    require(sha256(Path(lineage["archive_manifest_reference"]).read_bytes()) == lineage["archive_manifest_sha256"], "FEATURE_ARCHIVE_HASH_MISMATCH")
    archive, parent = verify_parent_archive(lineage["archive_manifest_reference"])
    require(archive["parent_plan_id"] == lineage["parent_plan_id"] and archive["parent_plan_sha256"] == lineage["parent_plan_sha256"], "FEATURE_PARENT_BINDING_MISMATCH")
    require(parent["universe"] == universe and parent["window"] == plan["window"] and parent["transport_binding"] == plan["transport_binding"], "FEATURE_PARENT_SOURCE_MISMATCH")
    for name in ("parser_identity", "dispatch_identity", "metadata_identity", "handoff_identity"):
        identity = lineage[name]
        require(sha256(Path(identity["path"]).read_bytes()) == identity["sha256"], "FEATURE_PINNED_SOURCE_CODE_TAMPERED")
    ready = read_metadata((root / "HANDOFF_READY.json").read_bytes())
    require(ready["plan_id"] == plan["plan_id"] and ready["status"] == "READY_FOR_REVIEW" and
        ready["sha256"] == sha256(_canonical({k: v for k, v in ready.items() if k != "sha256"})), "FEATURE_HANDOFF_TAMPERED")
    require(fingerprints(Path(p) for p in ready["inherited_event_inventory"]) == ready["inherited_event_inventory"], "FEATURE_INHERITED_EVENT_TAMPERED")
    require(not (root / "stop-gate.json").exists(), "FEATURE_COVERAGE_STOP_GATE")
    validate_dispatches(root, plan)
    events = read_events(root, plan)
    require(len(events) == len(universe["stocks"]) and all(e["status"] in {"COMPLETE", "HISTORICAL_INSUFFICIENT", "NO_EPS"} and not e["shared_host_stop"] for e in events.values()), "FEATURE_INCOMPLETE_OR_FAILED_LEDGER")
    eps = [r for event in events.values() for r in event["rows"]]
    saved = [read_metadata(line) for line in (closeout / "retained-eps-candidates.jsonl").read_bytes().splitlines()]
    require(saved == eps, "FEATURE_CLOSEOUT_EPS_REPLAY_MISMATCH")
    gap_artifact = read_metadata((closeout / "gap-evidence.json").read_bytes())
    require(gap_artifact["plan_id"] == plan["plan_id"], "FEATURE_GAP_PLAN_MISMATCH")
    gaps = [{"symbol": row["symbol"], "market": row["market"], "analysis_quarter": row["analysis_quarter"],
        "classification": row["classification"], "evidence_reference": str(closeout / "gap-evidence.json"),
        "json_locator": f"$.positions[{index}]", "receipt_evidence": row["receipt_evidence"]}
        for index, row in enumerate(gap_artifact["positions"])]
    inventory = read_metadata((Path(result["latest_scanner_report"]) / "revenue-availability.json").read_bytes())
    historical = read_metadata(Path(universe["source_path"]).read_bytes())
    markets = {r["symbol"]: r["market"] for r in universe["stocks"]}
    revenue = []
    for source in inventory["sources"]:
        receipt_path = Path(source["receipt_reference"])
        receipt = read_metadata(receipt_path.read_bytes())
        reference = {"path": receipt_path.relative_to(receipt_path.parents[2]).as_posix(), "sha256": digest(receipt)}
        receipt, raw = load_response(receipt_path.parents[2], reference, historical)
        require(receipt["market"] == source["market"] and receipt["requested_period"] == source["period"] and receipt["body_sha256"] == source["raw_sha256"] and receipt["retrieval_timestamp"] == source["observed_at"], "FEATURE_REVENUE_RECEIPT_BINDING")
        require(receipt["http_status"] == 200 and receipt["final_url"] == receipt["endpoint"], "FEATURE_REVENUE_TRANSPORT_INVALID")
        rows, failures = _warmup_revenue_rows(_decode_response(raw), receipt["market"], receipt["requested_period"], {**receipt, "raw_response_reference": reference})
        require(not failures and len(rows) == source["raw_valid_row_count"], "FEATURE_REVENUE_SOURCE_REPLAY_INVALID")
        for row in rows:
            validate_revenue_semantics(row)
            if markets.get(row["symbol"]) != row["market"]:
                continue
            revenue.append({"symbol": row["symbol"], "market": row["market"], "period": row["revenue_period"],
                "source": row["provider"], "revenue_yoy": str(row["revenue_yoy"]) if row["revenue_yoy"] is not None else None,
                "revenue_yoy_status": row["revenue_yoy_status"], "official_raw_yoy": row["official_raw_yoy"],
                "observed_at": row["retrieval_timestamp"], "source_validated_at": result["finished_at"],
                "receipt_reference": str(receipt_path), "receipt_sha256": sha256(receipt_path.read_bytes()),
                "raw_reference": str(receipt_path.parents[2] / receipt["raw_path"]), "raw_sha256": receipt["body_sha256"],
                "row_identity_locator": {"symbol": row["symbol"], "market": row["market"], "period": row["revenue_period"]}})
    saved_revenue = read_metadata((closeout / "revenue-evidence.json").read_bytes())["observations"]
    saved_map = {(r["symbol"], r["period"]): r for r in saved_revenue}
    require(len(saved_map) == len(saved_revenue) == len(revenue), "FEATURE_REVENUE_OBSERVATION_COUNT")
    for row in revenue:
        original = saved_map[(row["symbol"], row["period"])]
        require((str(original["revenue_yoy"]) if original["revenue_yoy"] is not None else None) == row["revenue_yoy"] and
            all(original[k] == row[k] for k in ("market", "revenue_yoy_status", "official_raw_yoy", "receipt_reference", "raw_sha256", "observed_at")), "FEATURE_CLOSEOUT_REVENUE_REPLAY_MISMATCH")
    verify_snapshot(before)
    verify_snapshot(manifest["files"])
    return {"material_class": "LOCAL_SAVED_FINMIND_AND_OFFICIAL_REVENUE_REPLAY", "universe": universe, "eps": eps, "revenue": revenue, "gaps": gaps,
        "source_binding": {"closeout_manifest_reference": str(path), "closeout_manifest_sha256": expected_sha256,
            "closeout_result_sha256": sha256(result_path.read_bytes()), "coverage_root": str(root), "plan_id": plan["plan_id"],
            "coverage_execution_head": result["execution_head"], "new_financial_requests": 0}}


def replay_binding(binding):
    result = load_closeout(binding["closeout_manifest_reference"], binding["closeout_manifest_sha256"])
    require(result["source_binding"] == binding, "FEATURE_SOURCE_BINDING_CHANGED")
    return result
