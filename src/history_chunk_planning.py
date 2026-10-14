"""Opt-in stock-history chunks. No scope approval, empty inference or auto-continuation."""
from collections import defaultdict
from pathlib import Path
import re

from . import history_acquisition_execution as h
from .eps_duration_facts.model import require

CONTRACT = "RATE_HISTORY_STOCK_CHUNKED_ACQUISITION_V1"
CR = "RATE-MH-CHUNKED-FAIL-CLOSED-ACQUISITION-001"
POLICY = {"max_issuers_per_chunk": 10, "max_requests_per_chunk": 100,
          "issuer_order": "SYMBOL_ASCENDING", "period_order": "PERIOD_DESCENDING"}
OWNERS = ["src/history_chunk_planning.py", "src/history_chunk_aggregation.py",
          "docs/contracts/RATE_HISTORY_STOCK_CHUNKED_ACQUISITION_V1.json"]
TPEX_HOLD = "BLOCKED_EXTERNAL_DOCUMENTATION"


def owners():
    return {p: h.evidence.sha((h.ROOT / p).read_bytes().replace(b"\r\n", b"\n")) for p in OWNERS}


def digest(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def stock_scope(main_sha, universe, entries, cutoffs, market, scope_evidence_sha256, *, synthetic=False):
    """Create an UNAPPROVED canonical scope proposal, never an approval or authorization."""
    require(market in {"TWSE", "TPEX"} and type(synthetic) is bool, "CHUNK_SCOPE_MARKET_INVALID")
    require(digest(scope_evidence_sha256), "CHUNK_SCOPE_EVIDENCE_INVALID")
    require(isinstance(entries, list) and entries, "CHUNK_SCOPE_EMPTY")
    require(all(isinstance(e, dict) and set(e) == {"market", "symbol", "period"} for e in entries), "CHUNK_SCOPE_FIELDS_INVALID")
    require(all(e["market"] == market for e in entries), "CHUNK_MIXED_MARKET_SCOPE")
    plan = h.build_plan(main_sha, universe, [{**e, "product": "stock"} for e in entries], cutoffs, synthetic=synthetic)
    canonical = [{k: e[k] for k in ("market", "symbol", "period")} for e in plan["entries"]]
    return h.evidence.identified({"artifact_kind": "RATE_HISTORY_STOCK_SCOPE_V1", "contract": CONTRACT,
        "status": "UNAPPROVED_SCOPE_PROPOSAL", "main_sha": main_sha, "universe_sha256": plan["universe_sha256"],
        "source_native_cutoffs": cutoffs, "market": market, "scope_evidence_sha256": scope_evidence_sha256,
        "entries": canonical, "total_entries": len(canonical), "total_issuers": len({e["symbol"] for e in canonical}),
        "material_scope": plan["material_scope"]}, "rate-history-stock-scope-", "scope_id", "scope_sha256")


def validate_scope(scope, approval, trusted_approval_sha256, *, main_sha, universe, synthetic=False):
    h.evidence.verify_identity(scope, "rate-history-stock-scope-", "scope_id", "scope_sha256")
    expected = stock_scope(main_sha, universe, scope["entries"], scope["source_native_cutoffs"], scope["market"],
                           scope["scope_evidence_sha256"], synthetic=synthetic)
    require(scope == expected, "CHUNK_SCOPE_BINDING_MISMATCH")
    h.evidence.verify_identity(approval, "rate-history-stock-scope-approval-", "approval_id", "approval_sha256")
    require(digest(trusted_approval_sha256) and approval["approval_sha256"] == trusted_approval_sha256,
            "CHUNK_EXTERNAL_SCOPE_APPROVAL_PIN_REQUIRED")
    binding = {k: scope[k] for k in ("scope_id", "scope_sha256", "main_sha", "universe_sha256", "market",
                                   "scope_evidence_sha256", "material_scope")}
    expected_approval = h.evidence.identified({"artifact_kind": "RATE_HISTORY_STOCK_SCOPE_APPROVAL_V1",
        "contract": CONTRACT, "status": "CONTROL_CENTER_ACCEPTED_EXACT_SCOPE", **binding},
        "rate-history-stock-scope-approval-", "approval_id", "approval_sha256")
    require(approval == expected_approval, "CHUNK_SCOPE_NOT_EXTERNALLY_APPROVED")
    return expected


def build_manifest(scope, approval, *, trusted_approval_sha256, main_sha, universe, synthetic=False):
    validate_scope(scope, approval, trusted_approval_sha256, main_sha=main_sha, universe=universe, synthetic=synthetic)
    groups = defaultdict(list)
    for entry in scope["entries"]:
        groups[entry["symbol"]].append(entry)
    batches, current, count = [], [], 0
    for symbol in sorted(groups):
        entries = sorted(groups[symbol], key=lambda e: e["period"], reverse=True)
        require(len(entries) <= POLICY["max_requests_per_chunk"], "CHUNK_SINGLE_ISSUER_BUDGET_EXCEEDED")
        if current and (len(current) == POLICY["max_issuers_per_chunk"] or count + len(entries) > POLICY["max_requests_per_chunk"]):
            batches.append(current); current, count = [], 0
        current.append(symbol); count += len(entries)
    if current:
        batches.append(current)
    chunks = []
    for ordinal, symbols in enumerate(batches, 1):
        entries = [e for s in symbols for e in sorted(groups[s], key=lambda e: e["period"], reverse=True)]
        plan = h.build_plan(main_sha, universe, [{**e, "product": "stock"} for e in entries],
                            scope["source_native_cutoffs"], maximum_requests=len(entries), synthetic=synthetic)
        chunks.append(h.evidence.identified({"chunk_ordinal": ordinal, "market": scope["market"], "symbols": symbols,
            "entries": entries, "issuer_count": len(symbols), "request_count": len(entries),
            "first_request_key": plan["entries"][0]["request_key"], "last_request_key": plan["entries"][-1]["request_key"],
            "plan_id": plan["plan_id"], "plan_sha256": plan["plan_sha256"]}, "rate-history-stock-chunk-", "chunk_id", "chunk_sha256"))
    stocks, uid = h.exact_universe(universe)
    return h.evidence.identified({"artifact_kind": "RATE_HISTORY_STOCK_CHUNK_MANIFEST_V1", "contract": CONTRACT,
        "cr": CR, "main_sha": main_sha, "universe": stocks, "universe_sha256": uid, "market": scope["market"],
        "source_native_cutoffs": scope["source_native_cutoffs"], "source_native_cutoff": scope["source_native_cutoffs"][scope["market"]],
        "scope_id": scope["scope_id"], "scope_sha256": scope["scope_sha256"], "scope_evidence_sha256": scope["scope_evidence_sha256"],
        "scope_approval_id": approval["approval_id"], "scope_approval_sha256": trusted_approval_sha256,
        "scope_entry_count": scope["total_entries"], "issuer_count": scope["total_issuers"], "chunk_count": len(chunks),
        "chunk_policy": POLICY, "chunks": chunks, "orchestration_owner_sha256_lf": owners(),
        "material_scope": scope["material_scope"], "tpex_unit_status": TPEX_HOLD,
        "retry": 0, "fallback": False, "redirect": False, "auto_resume": False, "production_eligible": False,
        "ranking_authorized": False, "historical_pit": "UNPROVEN"},
        "rate-history-stock-chunk-manifest-", "manifest_id", "manifest_sha256")


def validate_manifest(manifest, scope, approval, *, trusted_approval_sha256, main_sha, universe, synthetic=False):
    h.evidence.verify_identity(manifest, "rate-history-stock-chunk-manifest-", "manifest_id", "manifest_sha256")
    expected = build_manifest(scope, approval, trusted_approval_sha256=trusted_approval_sha256,
                              main_sha=main_sha, universe=universe, synthetic=synthetic)
    require(manifest == expected, "CHUNK_MANIFEST_BINDING_OR_PARTITION_MISMATCH")


def chunk_plan(manifest, chunk_id):
    matches = [c for c in manifest["chunks"] if c["chunk_id"] == chunk_id]
    require(len(matches) == 1, "CHUNK_NOT_IN_MANIFEST")
    chunk = matches[0]
    plan = h.build_plan(manifest["main_sha"], {"verification_status": "PASS", "stocks": manifest["universe"]},
        [{**e, "product": "stock"} for e in chunk["entries"]], manifest["source_native_cutoffs"],
        maximum_requests=chunk["request_count"], synthetic=manifest["material_scope"] == "SYNTHETIC_ONLY")
    require(plan["plan_id"] == chunk["plan_id"] and plan["plan_sha256"] == chunk["plan_sha256"], "CHUNK_PLAN_MISMATCH")
    return plan


def materials(manifest, scope, approval, *, trusted_approval_sha256, main_sha, universe, chunk_id, campaign_root, synthetic=False):
    validate_manifest(manifest, scope, approval, trusted_approval_sha256=trusted_approval_sha256,
                      main_sha=main_sha, universe=universe, synthetic=synthetic)
    campaign = h.evidence.safe(campaign_root)
    artifacts, consumption = h.evidence.external_roots(campaign / chunk_id / "evidence", campaign / chunk_id / "consumption", h.ROOT)
    plan = chunk_plan(manifest, chunk_id)
    held = manifest["market"] == "TPEX" and not synthetic
    seal = None if held else h.build_seal(plan, artifacts, consumption)
    candidate = None if held else h.candidate_authorization(seal)
    return {"manifest_id": manifest["manifest_id"], "manifest_sha256": manifest["manifest_sha256"], "chunk_id": chunk_id,
        "plan": plan, "seal": seal, "candidate": candidate, "campaign_root": str(campaign),
        "artifacts_root": str(artifacts), "consumption_root": str(consumption), "execution_root": str(artifacts / "run-001"),
        "execution_status": "HOLD_EXTERNAL_UNIT_DOCUMENTATION" if held else "PENDING_CONTROL_CENTER_AUTHORIZATION",
        "formal_authorization_created": False}


def execute_chunk(manifest, scope, approval, bundle, authorization, *, trusted_approval_sha256, main_sha, universe,
                  trusted_authorization_sha256, synthetic=False, **synthetic_transport):
    """One explicit chunk only. Existing executor owns claim, pacing, capture and STOP."""
    expected = materials(manifest, scope, approval, trusted_approval_sha256=trusted_approval_sha256, main_sha=main_sha,
        universe=universe, chunk_id=bundle["chunk_id"], campaign_root=bundle["campaign_root"], synthetic=synthetic)
    require(bundle == expected, "CHUNK_MATERIAL_BINDING_MISMATCH")
    require(bundle["execution_status"] != "HOLD_EXTERNAL_UNIT_DOCUMENTATION", "CHUNK_TPEX_UNIT_HOLD")
    require(synthetic or not synthetic_transport, "CHUNK_REAL_TRANSPORT_OVERRIDE_FORBIDDEN")
    campaign = h.evidence.safe(bundle["campaign_root"])
    campaign.mkdir(parents=True, exist_ok=True)
    with h.exclusive_scan(campaign):
        require(not (campaign / "HALTED.json").exists(), "HALTED_FOR_CONTROL_CENTER_REVIEW")
        try:
            result = h.execute(bundle["plan"], bundle["seal"], authorization,
                artifacts_root=bundle["artifacts_root"], consumption_root=bundle["consumption_root"],
                output_root=bundle["execution_root"], trusted_authorization_sha256=trusted_authorization_sha256,
                synthetic=synthetic, **synthetic_transport)
        except Exception:
            consumed = Path(bundle["consumption_root"]) / (authorization["authorization_id"] + ".json")
            if consumed.exists():
                h.evidence.put_json(campaign / "HALTED.json", {"status": "HALTED_FOR_CONTROL_CENTER_REVIEW",
                    "manifest_sha256": manifest["manifest_sha256"], "chunk_id": bundle["chunk_id"], "reason": "CLAIMED_EXECUTION_OR_REPLAY_ERROR_NO_RESUME"})
            raise
        status = "HALTED_FOR_CONTROL_CENTER_REVIEW" if result["status"] == "STOPPED" else "AWAITING_SEPARATE_CHUNK_AUTHORIZATION"
        if result["status"] == "STOPPED":
            h.evidence.put_json(campaign / "HALTED.json", {"status": status, "manifest_sha256": manifest["manifest_sha256"],
                "chunk_id": bundle["chunk_id"], "result_sha256": h.evidence.sha(result), "reason": "PERSISTENT_CHUNK_STOP"})
        return {"orchestration_status": status, "next_chunk_started": False, "result": result}
