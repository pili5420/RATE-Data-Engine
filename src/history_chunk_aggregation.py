"""Network-free aggregate replay. Original roots and acquisition times are never rewritten."""
from pathlib import Path
import subprocess

from . import history_acquisition_execution as h
from . import history_chunk_planning as planning
from .eps_duration_facts.model import require
from .provider_eps_metadata import read_metadata


def _file(root, relative):
    path = h.evidence.safe(Path(root) / relative)
    require(path.is_file(), "CHUNK_EVIDENCE_FILE_REQUIRED")
    raw = path.read_bytes()
    return {"path": str(path), "sha256": h.evidence.sha(raw), "bytes": len(raw)}


def _replay(binding, *, trusted_sha256):
    """Trust is an independently supplied pin, not a digest taken from the binding itself."""
    require(planning.digest(trusted_sha256) and h.evidence.sha(binding) == trusted_sha256, "CHUNK_REPLAY_BINDING_PIN_MISMATCH")
    require(isinstance(binding, dict) and set(binding) == {"execution_root", "consumption_root", "plan", "seal", "authorization"},
            "CHUNK_REPLAY_BINDING_FIELDS_INVALID")
    root, consumption = h.evidence.safe(binding["execution_root"]), h.evidence.safe(binding["consumption_root"])
    result = h.replay(root, binding["plan"], binding["seal"], binding["authorization"], consumption)
    refs = [_file(root, str(p.relative_to(root))) for p in sorted(root.rglob("*")) if p.is_file()]
    # Scanner's unlocked runtime coordination file is not acquisition content.
    require(not any(Path(r["path"]).name == ".scan.lock" for r in refs), "CHUNK_RUNTIME_LOCK_INSIDE_EXECUTION_ROOT")
    record = _file(consumption, binding["authorization"]["authorization_id"] + ".json")
    return result, refs + [record]


def aggregate(manifest, scope, approval, chunks, benchmark, *, trusted_approval_sha256, trusted_benchmark_sha256,
              main_sha, universe, synthetic=False):
    """INVALID returns no trusted coverage; PARTIAL_HALTED retains every replayed valid event."""
    try:
        planning.validate_manifest(manifest, scope, approval, trusted_approval_sha256=trusted_approval_sha256,
            main_sha=main_sha, universe=universe, synthetic=synthetic)
        require(isinstance(chunks, list), "CHUNK_AGGREGATE_INPUT_INVALID")
        benchmark_result, benchmark_refs = _replay(benchmark, trusted_sha256=trusted_benchmark_sha256)
        bp = benchmark["plan"]
        require(benchmark_result["status"] == "PASS" and all(e["product"] == "benchmark" for e in bp["entries"]), "CHUNK_ACCEPTED_BENCHMARK_REQUIRED")
        require(bp["universe_sha256"] == manifest["universe_sha256"] and bp["source_native_cutoffs"] == manifest["source_native_cutoffs"],
                "CHUNK_BENCHMARK_UNIVERSE_OR_CUTOFF_MISMATCH")
        require(bp["material_scope"] == manifest["material_scope"], "CHUNK_BENCHMARK_MATERIAL_SCOPE_MISMATCH")
        # Accepted ancestor benchmark data retains its producer pin; additive orchestration must not rebind it.
        require(all(bp["owner_sha256_lf"][k] == h.owners()[k] for k in bp["owner_sha256_lf"]), "CHUNK_BENCHMARK_OWNER_DRIFT")
        if not synthetic:
            require(subprocess.run(["git", "merge-base", "--is-ancestor", bp["main_sha"], main_sha],
                    cwd=h.ROOT, capture_output=True).returncode == 0, "CHUNK_BENCHMARK_PRODUCER_NOT_ANCESTOR")
        events = [read_metadata(p.read_bytes()) for p in sorted((Path(benchmark["execution_root"]) / "events").glob("*.json"))]
        chains = h.benchmark_chains(events)
        require(all(c["at_least_180"] and c["latest_session"] == manifest["source_native_cutoffs"][m] for m,c in chains.items()),
                "CHUNK_BENCHMARK_180_CHAIN_REQUIRED")
        seen, request_keys, roots, consumptions, auth_ids, reports = set(), set(), set(), set(), set(), []
        definitions = {c["chunk_id"]: c for c in manifest["chunks"]}
        for supplied in chunks:
            require(isinstance(supplied, dict) and set(supplied) == {"chunk_id", "binding", "trusted_binding_sha256"}, "CHUNK_AGGREGATE_FIELDS_INVALID")
            cid, binding = supplied["chunk_id"], supplied["binding"]
            require(cid in definitions and cid not in seen, "CHUNK_DUPLICATE_OR_UNMANIFESTED")
            require(binding["plan"] == planning.chunk_plan(manifest, cid), "CHUNK_AGGREGATE_PLAN_MISMATCH")
            root_id = h.evidence.root_identity(binding["execution_root"])
            con_id = h.evidence.root_identity(binding["consumption_root"])
            auth_id = binding["authorization"]["authorization_id"]
            require(root_id not in roots and con_id not in consumptions and auth_id not in auth_ids, "CHUNK_EXECUTION_OR_AUTHORIZATION_REUSED")
            result, refs = _replay(binding, trusted_sha256=supplied["trusted_binding_sha256"])
            seen.add(cid); roots.add(root_id); consumptions.add(con_id); auth_ids.add(auth_id)
            keys = {e["request_key"] for e in binding["plan"]["entries"]}
            require(not keys & request_keys, "CHUNK_DUPLICATE_STOCK_EVIDENCE")
            request_keys.update(keys)
            chunk_events = [read_metadata(p.read_bytes()) for p in sorted((Path(binding["execution_root"]) / "events").glob("*.json"))]
            require(all(e["product"] == "stock" and e["market"] == manifest["market"] for e in chunk_events), "CHUNK_AGGREGATE_MARKET_OR_PRODUCT_MISMATCH")
            events.extend(chunk_events)
            reports.append({"chunk_id": cid, "chunk_ordinal": definitions[cid]["chunk_ordinal"], "status": result["status"],
                "ledger_head": result["ledger_head"], "actual_requests": result["actual_requests"],
                "completed_checkpoints": result["completed_checkpoints"], "execution_root_identity": root_id,
                "consumption_root_identity": con_id, "authorization_id": auth_id, "original_evidence": refs,
                "binding_sha256": supplied["trusted_binding_sha256"]})
        reports.sort(key=lambda r:r["chunk_ordinal"])
        scope_keys = {h.request_entry({**e,"product":"stock"},1)["request_key"] for e in scope["entries"]}
        valid_keys = {e["request_key"] for e in events if e["product"] == "stock"}
        complete = len(seen) == manifest["chunk_count"] and all(r["status"] == "PASS" for r in reports) and valid_keys == scope_keys
        coverage = h.coverage_inventory(manifest["universe"], events, manifest["source_native_cutoffs"])
        return h.evidence.identified({"artifact_kind":"RATE_HISTORY_STOCK_CHUNK_AGGREGATE_V1", "contract":planning.CONTRACT,
            "status":"COMPLETE" if complete else "PARTIAL_HALTED", "main_sha":main_sha,
            "manifest_id":manifest["manifest_id"], "manifest_sha256":manifest["manifest_sha256"],
            "scope_sha256":scope["scope_sha256"], "universe_sha256":manifest["universe_sha256"],
            "market":manifest["market"], "source_native_cutoffs":manifest["source_native_cutoffs"],
            "benchmark_binding_sha256":trusted_benchmark_sha256, "benchmark_producer_main_sha":bp["main_sha"],
            "benchmark_original_evidence":benchmark_refs, "chunks":reports,
            "required_chunks_without_supplied_execution":[c["chunk_id"] for c in manifest["chunks"] if c["chunk_id"] not in seen],
            "unsupplied_claim_status":"UNPROVEN_NOT_INFERRED_FROM_ABSENCE_OF_INPUT",
            "scope_entries":len(scope_keys), "accepted_scope_entries":len(valid_keys), "coverage":coverage,
            "orchestration_status":"AWAITING_CONTROL_CENTER_REVIEW" if complete else "HALTED_FOR_CONTROL_CENTER_REVIEW",
            "network_requests":0,"ranking_executions":0,"production_publications":0,"production_eligible":False,
            "historical_pit":"UNPROVEN","fallback":False,"auto_resume":False,"tpex_unit_status":planning.TPEX_HOLD},
            "rate-history-stock-chunk-aggregate-","aggregate_id","aggregate_sha256")
    except (ValueError, KeyError, TypeError, OSError) as error:
        return {"artifact_kind":"RATE_HISTORY_STOCK_CHUNK_AGGREGATE_V1", "status":"INVALID",
            "reason":str(error),"coverage":None,"trusted_scope_complete":False,"network_requests":0,
            "production_eligible":False,"ranking_executions":0,"production_publications":0}
