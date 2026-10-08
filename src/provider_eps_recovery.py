"""Successor-plan replay of archived local evidence; no transport import or call."""
from pathlib import Path

from .eps_duration_facts.model import require
from .eps_duration_facts.raw import sha256
from .provider_eps_candidate import _canonical, read_provider_response
from .provider_eps_metadata import read_metadata as _json
from .provider_eps_coverage import append_event, evaluate_receipt, initialize, make_plan, now, result_entry, validate_plan


def verify_archive(manifest_path):
    manifest_path = Path(manifest_path).resolve()
    manifest = _json(manifest_path.read_bytes())
    require(manifest["schema"] == "RATE_PR33_OLD_HEAD_EVIDENCE_V1", "OLD_HEAD_ARCHIVE_REQUIRED")
    for filename, expected in manifest["files"].items():
        body = Path(filename).read_bytes()
        require(len(body) == expected["bytes"] and sha256(body) == expected["sha256"], "ARCHIVED_SOURCE_CHANGED:" + filename)
    root = Path(manifest["old_root"])
    require({str(p.resolve()) for p in root.rglob("*") if p.is_file()} <= set(manifest["files"]), "OLD_LEDGER_FILES_ADDED_AFTER_ARCHIVE")
    parent = _json((root / "plan.json").read_bytes())
    validate_plan(parent)
    require(parent["plan_id"] == manifest["old_plan_id"] and sha256((root / "plan.json").read_bytes()) == manifest["old_plan_sha256"], "ARCHIVED_PLAN_MISMATCH")
    return manifest, parent


def recovery_lineage(manifest_path, manifest, head):
    source = Path(__file__).resolve().parent
    return {"parent_plan_id": manifest["old_plan_id"], "parent_plan_sha256": manifest["old_plan_sha256"],
        "old_head": manifest["old_head"], "new_head": head,
        "archive_manifest_reference": str(Path(manifest_path).resolve()),
        "archive_manifest_sha256": sha256(Path(manifest_path).read_bytes()),
        "recovery_reason": "EXACT_BASIC_LABEL_COMPATIBILITY_AND_STOP_GATE_FIX",
        "parser_identity": {"path": str(source / "provider_eps_candidate.py"), "sha256": sha256((source / "provider_eps_candidate.py").read_bytes())},
        "dispatch_identity": {"path": str(source / "provider_eps_dispatch.py"), "sha256": sha256((source / "provider_eps_dispatch.py").read_bytes())},
        "old_dispatch_spacing_status": "UNPROVEN", "inherited_requests": manifest["inherited_requests"]}


def replay_archive(manifest_path, output, code_binding):
    manifest, parent = verify_archive(manifest_path)
    require(parent["code_binding"]["head_sha"] == manifest["old_head"], "PARENT_HEAD_MISMATCH")
    plan = make_plan(parent["universe"], code_binding, parent["transport_binding"],
                     recovery_lineage=recovery_lineage(manifest_path, manifest, code_binding["head_sha"]))
    output = Path(output).resolve()
    require(not output.exists() and not output.is_relative_to(Path(manifest["old_root"])), "RECOVERY_REQUIRES_NEW_ROOT")
    root = initialize(output, plan)
    changes = []
    for event_path in sorted((Path(manifest["old_root"]) / "events").glob("*.json")):
        old = _json(event_path.read_bytes())
        require(old["event_sha256"] == sha256(_canonical({k: v for k, v in old.items() if k != "event_sha256"})), "OLD_EVENT_TAMPERED")
        symbol = old["symbol"]
        require(event_path.stem == symbol and old["plan_id"] == parent["plan_id"], "OLD_EVENT_IDENTITY_MISMATCH")
        if old["origin"] == "REUSED_ORIGINAL_24":
            rows, issues, inventory = [], [], {}
            for reference in old["receipt_references"]:
                material = read_provider_response(reference)
                rows.extend(material["rows"])
                issues.extend(material["issues"])
                inventory.update(material["input_integrity"])
            entry = result_entry(plan, symbol, rows, issues, origin="REUSED_ORIGINAL_24",
                references=old["receipt_references"], integrity={**old["input_integrity"], **inventory})
            original_request = None
        else:
            require(len(old["receipt_references"]) == 1, "OLD_REQUEST_RECEIPT_COUNT_INVALID")
            entry = evaluate_receipt(plan, symbol, old["receipt_references"][0])
            entry["origin"] = "OFFLINE_PARENT_REQUEST_REPLAY"
            original_request = str(event_path.parent.parent / "intents" / (symbol + ".json"))
            require(original_request in manifest["files"], "ORIGINAL_REQUEST_NOT_ARCHIVED")
            intent = _json(Path(original_request).read_bytes())
            require(intent["plan_id"] == parent["plan_id"] and intent["symbol"] == symbol and
                    intent["query"] == {**parent["query"], "data_id": symbol}, "ORIGINAL_REQUEST_IDENTITY_INVALID")
        require(entry["market"] == old["market"], "RECOVERY_MARKET_CHANGED")
        provenance = {"parent_plan_id": parent["plan_id"], "original_event_reference": str(event_path),
            "original_event_sha256": old["event_sha256"], "original_event_file_sha256": sha256(event_path.read_bytes()),
            "original_request_reference": original_request, "original_receipt_references": old["receipt_references"],
            "old_status": old["status"], "new_status": entry["status"], "revalidated_at": now(),
            "original_request_identity": "coverage-" + symbol if original_request else "REUSED_ORIGINAL_24"}
        entry["recovery"] = provenance
        entry["input_integrity"][str(event_path)] = manifest["files"][str(event_path)]
        if original_request:
            entry["input_integrity"][original_request] = manifest["files"][original_request]
        prior_rows = {(r["receipt_reference"], r["json_locator"]): r for r in old["rows"]}
        for row in entry["rows"]:
            prior = prior_rows.get((row["receipt_reference"], row["json_locator"]))
            if prior:
                require(all(row[k] == prior[k] for k in ("provider_value", "provider_date", "raw_sha256", "acquired_observed_at")), "RECOVERY_SOURCE_OR_VALUE_CHANGED")
                for key in ("acquisition_executed_at", "material_origin", "official_numeric_corroboration"):
                    if key in prior:
                        row[key] = prior[key]
            row["recovery_provenance"] = provenance
        entry = append_event(root, entry)
        changes.append({"symbol": symbol, "market": entry["market"], "old_status": old["status"], "new_status": entry["status"],
            "old_valid_quarters": len(old["rows"]), "new_valid_quarters": len(entry["rows"]),
            "old_issues": old["issues"], "new_issues": entry["issues"], "provenance": provenance})
    verify_archive(manifest_path)
    require(len(changes) == manifest["counts"]["accounted_for"] and
            sum(bool(c["provenance"]["original_request_reference"]) for c in changes) == manifest["inherited_requests"],
            "ARCHIVED_ACCOUNTING_MISMATCH")
    return root, plan, changes
