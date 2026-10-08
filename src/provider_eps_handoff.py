"""Verified, staged code-version handoff, including already-recovered parents."""
from copy import deepcopy
from pathlib import Path

from .eps_duration_facts.model import require
from .eps_duration_facts.raw import sha256
from .provider_eps_candidate import _canonical
from .provider_eps_coverage import (append_event, initialize, make_plan, now, read_events,
    save, summary, validate_plan)
from .provider_eps_dispatch import exclusive_scan
from .provider_eps_metadata import VERSION, read_metadata, read_intent, validate_dispatches
from .provider_eps_recovery import verify_archive

REASON = "DISPATCH_METADATA_JSON_ROUND_TRIP_CODE_HANDOFF"
SCHEMA = "RATE_PROVIDER_CODE_HANDOFF_ARCHIVE_V1"


def fingerprints(paths):
    return {str(Path(p).resolve()): {"bytes": len(b), "sha256": sha256(b)}
            for p in sorted(set(paths)) for b in [Path(p).read_bytes()]}


def identity():
    source = Path(__file__).resolve().parent
    return {name: {"path": str(source / filename), "sha256": sha256((source / filename).read_bytes())}
        for name, filename in (("parser_identity", "provider_eps_candidate.py"),
            ("dispatch_identity", "provider_eps_dispatch.py"), ("metadata_identity", "provider_eps_metadata.py"),
            ("handoff_identity", "provider_eps_handoff.py"))}


def verify_parent_archive(path):
    manifest = read_metadata(Path(path).read_bytes())
    require(manifest["schema"] == SCHEMA, "HANDOFF_ARCHIVE_SCHEMA_INVALID")
    require(fingerprints(Path(p) for p in manifest["files"]) == manifest["files"], "HANDOFF_PARENT_CHANGED")
    root = Path(manifest["parent_root"])
    require({str(p.resolve()) for p in root.rglob("*") if p.is_file()} ==
            {p for p in manifest["files"] if Path(p).is_relative_to(root)}, "HANDOFF_PARENT_FILES_CHANGED")
    parent = read_metadata((root / "plan.json").read_bytes())
    validate_plan(parent)
    require(parent["plan_id"] == manifest["parent_plan_id"] and
            sha256((root / "plan.json").read_bytes()) == manifest["parent_plan_sha256"], "HANDOFF_PARENT_PLAN_CHANGED")
    ancestor = parent.get("recovery_lineage")
    if ancestor:
        archive = Path(ancestor["archive_manifest_reference"])
        require(sha256(archive.read_bytes()) == ancestor["archive_manifest_sha256"], "ARCHIVE_MANIFEST_TAMPERED")
        if ancestor["recovery_reason"] == REASON:
            verify_parent_archive(archive)
        else:
            verify_archive(archive)
    return manifest, parent


def lineage(path, manifest, head):
    return {"parent_plan_id": manifest["parent_plan_id"], "parent_plan_sha256": manifest["parent_plan_sha256"],
        "old_head": manifest["old_head"], "new_head": head, "recovery_reason": REASON,
        "archive_manifest_reference": str(Path(path).resolve()), "archive_manifest_sha256": sha256(Path(path).read_bytes()),
        "metadata_codec_version": VERSION, **identity(), "old_dispatch_spacing_status": "UNPROVEN",
        "inherited_requests": manifest["counts"]["cumulative_data_requests"]}


def resolve_request(event_path):
    """Follow sealed event lineage to an actual ancestor intent, not a fake request."""
    seen, chain = set(), []
    while True:
        event_path = Path(event_path).resolve()
        require(str(event_path) not in seen, "HANDOFF_PROVENANCE_CYCLE")
        seen.add(str(event_path))
        entry = read_metadata(event_path.read_bytes())
        require(entry["event_sha256"] == sha256(_canonical({k: v for k, v in entry.items() if k != "event_sha256"})),
                "HANDOFF_ANCESTRAL_EVENT_TAMPERED")
        chain.append({"event_reference": str(event_path), "event_file_sha256": sha256(event_path.read_bytes()),
                      "plan_id": entry["plan_id"], "event_sha256": entry["event_sha256"]})
        intent_path = event_path.parent.parent / "intents" / (entry["symbol"] + ".json")
        if intent_path.exists():
            plan = read_metadata((intent_path.parent.parent / "plan.json").read_bytes())
            validate_plan(plan)
            intent = read_intent(intent_path, plan)
            require(intent["plan_id"] == entry["plan_id"] and intent.get("query") ==
                    {**plan["query"], "data_id": entry["symbol"]}, "HANDOFF_ANCESTRAL_REQUEST_INVALID")
            return str(intent_path), chain
        recovery = entry.get("recovery")
        if not recovery:
            require(entry["origin"] == "REUSED_ORIGINAL_24", "HANDOFF_REAL_REQUEST_NOT_FOUND")
            return None, chain
        next_path = Path(recovery["original_event_reference"])
        original = read_metadata(next_path.read_bytes())
        require(sha256(next_path.read_bytes()) == recovery["original_event_file_sha256"] and
                original["plan_id"] == recovery["parent_plan_id"] and original["symbol"] == entry["symbol"] and
                original["receipt_references"] == entry["receipt_references"], "HANDOFF_ANCESTRAL_BINDING_INVALID")
        event_path = next_path


def verify_handoff(root, plan, head):
    validate_plan(plan)
    value = plan["recovery_lineage"]
    manifest, parent = verify_parent_archive(value["archive_manifest_reference"])
    require(value == lineage(value["archive_manifest_reference"], manifest, head), "HANDOFF_CODE_IDENTITY_CHANGED")
    require(plan["universe"] == parent["universe"] and plan["window"] == parent["window"] and
            plan["transport_binding"] == parent["transport_binding"], "HANDOFF_SOURCE_IDENTITY_CHANGED")
    ready = read_metadata((Path(root) / "HANDOFF_READY.json").read_bytes())
    require(ready["status"] == "READY_FOR_REVIEW" and ready["plan_id"] == plan["plan_id"] and
            ready["sha256"] == sha256(_canonical({k: v for k, v in ready.items() if k != "sha256"})), "HANDOFF_NOT_VERIFIED")
    require(fingerprints(Path(p) for p in ready["inherited_event_inventory"]) == ready["inherited_event_inventory"],
            "HANDOFF_INHERITED_EVENT_CHANGED")
    return manifest, parent


def handoff(parent_root, output, code_binding):
    parent_root, output = Path(parent_root).resolve(), Path(output).resolve()
    require(not output.exists() and not output.is_relative_to(parent_root), "HANDOFF_REQUIRES_NEW_ROOT")
    staging = output.with_name(output.name + "-INCOMPLETE")
    require(not staging.exists(), "HANDOFF_STAGING_EXISTS")
    parent = read_metadata((parent_root / "plan.json").read_bytes())
    validate_plan(parent)
    with exclusive_scan(parent_root):
        require(not (parent_root / "stop-gate.json").exists(), "HANDOFF_UNRESOLVED_STOP_GATE")
        validate_dispatches(parent_root, parent)
        events = read_events(parent_root, parent)
        require(all(e["status"] != "VALIDATION_FAILED" and not e["shared_host_stop"] for e in events.values()),
                "HANDOFF_UNRESOLVED_STOP_GATE")
        before = summary(parent_root, parent, {"reason": "OFFLINE_HANDOFF", "new_requests": 0})
        require(before["counts"]["status_counts"].get("REQUEST_OUTCOME_UNKNOWN", 0) == 0,
                "HANDOFF_UNKNOWN_REQUEST_OUTCOME")
        lock_path = parent_root / ".scan.lock"
        paths = {p.resolve() for p in parent_root.rglob("*") if p.is_file() and p.resolve() != lock_path}
        # Only this exact OS-held runtime lock is unreadable on Windows.
        for e in events.values():
            paths.update(Path(p).resolve() for p in e["input_integrity"])
        requests = {}
        for symbol in events:
            ref, chain = resolve_request(parent_root / "events" / (symbol + ".json"))
            requests[symbol] = (ref, chain)
            paths.update(Path(c["event_reference"]) for c in chain)
            if ref:
                paths.add(Path(ref))
        parent_lineage = parent.get("recovery_lineage")
        if parent_lineage:
            paths.add(Path(parent_lineage["archive_manifest_reference"]))
        files = fingerprints(paths)
    # After releasing the parent's scanner lock, include its bytes as well.
    files.update(fingerprints([lock_path]))
    archive_path = output.with_name(output.name + "-parent-archive.json")
    manifest = {"schema": SCHEMA, "parent_root": str(parent_root), "parent_plan_id": parent["plan_id"],
        "parent_plan_sha256": sha256((parent_root / "plan.json").read_bytes()), "old_head": parent["code_binding"]["head_sha"],
        "counts": before["counts"], "files": files, "created_at": now(), "network_requests": 0}
    save(archive_path, manifest)
    verify_parent_archive(archive_path)
    plan = make_plan(parent["universe"], code_binding, parent["transport_binding"],
        recovery_lineage=lineage(archive_path, manifest, code_binding["head_sha"]))
    root = initialize(staging, plan)
    save(root / "INCOMPLETE.json", {"status": "INCOMPLETE_UNTIL_HANDOFF_READY", "plan_id": plan["plan_id"]})
    matrix = []
    for symbol, old in events.items():
        event_path = parent_root / "events" / (symbol + ".json")
        request, chain = requests[symbol]
        entry = deepcopy(old)
        entry.pop("event_sha256")
        instant = now()
        provenance = {"parent_plan_id": parent["plan_id"], "original_event_reference": str(event_path),
            "original_event_sha256": old["event_sha256"], "original_event_file_sha256": sha256(event_path.read_bytes()),
            "original_request_reference": request, "original_receipt_references": old["receipt_references"],
            "old_status": old["status"], "new_status": old["status"], "revalidated_at": instant,
            "original_request_identity": "coverage-" + symbol if request else "REUSED_ORIGINAL_24",
            "ancestral_event_chain": chain, "prior_recovery_provenance": old.get("recovery")}
        entry.update(plan_id=plan["plan_id"], recovery=provenance, recorded_at=instant)
        entry["input_integrity"][str(event_path)] = files[str(event_path)]
        for row in entry["rows"]:
            row.update(coverage_plan_id=plan["plan_id"], recovery_provenance=provenance, verified_observed_at=instant)
        append_event(root, entry)
        matrix.append({"symbol": symbol, "market": old["market"], "old_status": old["status"],
            "new_status": entry["status"], "old_valid_quarters": len(old["rows"]), "new_valid_quarters": len(entry["rows"]),
            "data_unchanged": True, "provenance": provenance})
    after = summary(root, plan, {"reason": "OFFLINE_CODE_HANDOFF_ONLY", "new_requests": 0})
    require(after["counts"]["accounted_for"] == before["counts"]["accounted_for"] and
            after["counts"]["valid_company_quarters"] == before["counts"]["valid_company_quarters"] and
            after["counts"]["status_counts"] == before["counts"]["status_counts"] and
            after["counts"]["inherited_data_requests"] == before["counts"]["cumulative_data_requests"] and
            after["counts"]["new_plan_data_request_intents"] == 0, "HANDOFF_ACCOUNTING_CHANGED")
    verify_parent_archive(archive_path)
    save(root / "reports" / "coverage-result.json", after)
    save(root / "reports" / "before-after-matrix.json", {"data_unchanged": True, "companies": matrix})
    save(root / "reports" / "invariance.json", {"parent_files": files, "unchanged": True,
        "same_values_sources_observation_times_and_decisions": True, "real_new_requests": 0})
    inherited = {str(output / "events" / p.name): v for p, v in
                 ((Path(p), v) for p, v in fingerprints((root / "events").glob("*.json")).items())}
    ready = {"status": "READY_FOR_REVIEW", "plan_id": plan["plan_id"], "verified_at": now(),
        "inherited_event_inventory": inherited, "counts": after["counts"], "real_new_requests": 0,
        "production_eligible": False, "original_eight_quarter_coverage_credit": 0}
    save(root / "HANDOFF_READY.json", {**ready, "sha256": sha256(_canonical(ready))})
    require(root.parent == output.parent and not output.exists(), "HANDOFF_PUBLISH_PATH_INVALID")
    root.rename(output)
    verify_handoff(output, plan, code_binding["head_sha"])
    return output, plan, after
