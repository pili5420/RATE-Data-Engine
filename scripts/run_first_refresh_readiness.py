"""No-network Phase J source replay. Writes only a fresh external readiness package."""
import argparse
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.first_refresh_readiness import CONTRACT, ReadOnlyGuard, dry_run, identity, transaction_design, publication_readiness
from src.eps_duration_facts.model import require
from src.eps_duration_facts.raw import sha256
from src.full_market_history import put_bytes
from src.provider_eps_metadata import read_metadata
from src.provider_eps_candidate import _canonical
from src.provider_eps_coverage import load_universe
from src.prospective_acquisition_recovery import load_binding, object_at, read_pinned, replay_recovered, successful_prefix
from src.prospective_provider_activation import load
from scripts.run_prospective_provider_activation import external, issuer_readiness
from src.historical_replay_portability import clean_env, equivalence


def now():
    return datetime.now(timezone.utc).isoformat()


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT, env=clean_env()).decode().strip()


def portability_command(binding, output):
    ref = binding["historical_replay_portability"]
    portable = object_at(ref)
    require(portable["artifact_kind"] == CONTRACT["historical_replay_contract"]
            and portable["producer_sha"] == CONTRACT["historical_producer_sha"]
            and portable["current_main_sha"] == binding["execution"]["base_sha"]
            and portable["consumer_head_sha"] == binding["execution"]["head_sha"]
            and Path(portable["consumer_checkout"]).resolve() == ROOT
            and Path(portable["repository_checkout"]).resolve() == ROOT,
            "REFRESH_PORTABILITY_EXECUTION_BINDING")
    require(portable["accepted_reader"] == binding["accepted_continuation_reader"]
            and Path(portable["accepted_reader"]["path"]).resolve().parent == Path(binding["continuation_root"]).resolve()
            and portable["fallback_allowed"] is False, "REFRESH_PORTABILITY_READER_BINDING")
    for name in ("recovery_binding", "recovery_checkpoint", "continuation_checkpoint"):
        require(portable["evidence_pins"][name] == binding[name], "REFRESH_PORTABILITY_EVIDENCE_BINDING")
    config_ref = portable["evidence_pins"]["configuration"]
    require(Path(config_ref["path"]).resolve() == Path(binding["continuation_root"]).resolve() / "continuation-evidence/CONFIG.json",
            "REFRESH_PORTABILITY_CONFIGURATION_BINDING")
    object_at(config_ref)
    object_at(portable["accepted_output"])
    return [sys.executable, "-B", str(ROOT / "scripts/run_historical_replay_portability.py"),
            "--binding", str(ref["path"]), "--binding-sha256", ref["sha256"],
            "--output", str(output / "historical-replay")]


def replay_continuation(binding, output):
    # A fresh interpreter prevents current src imports from leaking into historical code.
    command = portability_command(binding, output)
    run = subprocess.run(command, executable=sys.executable, cwd=ROOT, env=clean_env(), capture_output=True)
    put_bytes(output, "portability-worker.stdout.json", run.stdout)
    put_bytes(output, "portability-worker.stderr.txt", run.stderr)
    require(run.returncode == 0, "REFRESH_PORTABILITY_WORKER_FAILED_SEE_STDERR")
    proof = read_metadata(run.stdout)
    portable = object_at(binding["historical_replay_portability"])
    actual = read_metadata((output / "historical-replay/REPLAY.json").read_bytes())
    match = equivalence(actual, object_at(portable["accepted_output"]))
    require(proof["status"] == "PASS" and proof["equivalence"] == match
            and proof["identities"] == {"producer_sha": portable["producer_sha"],
                "current_main_sha": portable["current_main_sha"], "consumer_head_sha": portable["consumer_head_sha"]}
            and proof["accepted_reader_unchanged"] is True and proof["historical_functions_patched"] is False
            and all(proof[key] == 0 for key in ("network_requests", "financial_requests", "production_mutations",
                                               "shared_ref_mutations", "first_refresh_execution")),
            "REFRESH_PORTABILITY_REPLAY_PROOF_INVALID")
    return proof


def inputs(binding, output):
    execution = binding["execution"]
    require(execution["base_sha"] == CONTRACT["base_sha"] and git("rev-parse", "HEAD") == execution["head_sha"]
            and git("merge-base", execution["base_sha"], "HEAD") == execution["base_sha"]
            and not git("status", "--porcelain"), "REFRESH_EXACT_HEAD_BINDING")
    auth = load(binding["authority"]["root"], binding["authority"]["sha256"])
    require(auth["authority_id"] == binding["authority"]["authority_id"]
            and auth["contract"]["providers"] == CONTRACT["providers"], "REFRESH_AUTHORITY_PIN")
    universe = load_universe(binding["universe"]["path"], binding["universe"]["sha256"], binding["universe"]["commit"])
    cp = object_at(binding["recovery_checkpoint"])
    require(cp["binding_sha256"] == binding["recovery_binding"]["sha256"], "REFRESH_RECOVERY_CHECKPOINT")
    recovery = replay_recovered(cp["resolution_root"], binding["recovery_binding"]["path"], cp["binding_sha256"], cp["resolutions"], now())
    old, cfg, old_auth, engine = load_binding(binding["recovery_binding"]["path"], cp["binding_sha256"])
    require(cfg["universe"] == universe and old_auth == auth, "REFRESH_PARENT_IDENTITY_MISMATCH")
    events = successful_prefix(old, cfg, auth, engine, now())
    # The original A4 prefix retains its physical producer identity; no old plan is edited.
    a4 = object_at(binding["bounded_checkpoint"])
    require(a4["config_sha256"] == old["config_sha256"] and a4["authority_id"] == auth["authority_id"], "REFRESH_BOUNDED_CHECKPOINT")
    bounded_root = Path(binding["bounded_root"])
    require(sha256((bounded_root / "CONFIG.json").read_bytes()) == a4["config_sha256"], "REFRESH_BOUNDED_CONFIG_TAMPER")
    bounded = successful_prefix({**old, "legacy_root": str(bounded_root), "trusted_head_before_failure": a4["ledger_head"]},
                               cfg, auth, engine, now())
    require({p.stem for p in (bounded_root / "intents").iterdir()} == {e["intent_id"] for e in bounded}
            and not (bounded_root / "STOP.json").exists(), "REFRESH_BOUNDED_UNKNOWN_OR_STOP")
    replay_continuation(binding, output)
    continuation_cp = object_at(binding["continuation_checkpoint"])
    require(continuation_cp["parent_head"] == recovery["trusted_ledger_head"]
            and continuation_cp["ledger_head"] == binding["trusted_continuation_head"], "REFRESH_CONTINUATION_HEAD")
    croot = Path(binding["continuation_root"]) / "continuation-evidence"
    cconfig = read_metadata((croot / "CONFIG.json").read_bytes())
    require(cconfig["universe"] == universe and cconfig["authority_id"] == auth["authority_id"]
            and sha256((croot / "CONFIG.json").read_bytes()) == continuation_cp["config_sha256"], "REFRESH_CONTINUATION_CONFIG")
    cpaths = list((croot / "events").iterdir())
    require(len(cpaths) == 1 and sha256(cpaths[0].read_bytes()) == continuation_cp["ledger_head"], "REFRESH_CONTINUATION_EVENT")
    continuation = read_metadata(cpaths[0].read_bytes())
    all_events = sorted(bounded + events + [continuation], key=lambda e: e["record"]["first_seen_at"])
    # Parsed timestamps, not strings with mixed UTC offsets, define observation order.
    from src.provider_eps_candidate import _time
    all_events.sort(key=lambda e: _time(e["record"]["first_seen_at"]))
    legacy = object_at(binding["legacy_summary"])
    require(legacy.get("historical_pit", "UNPROVEN") == "UNPROVEN" and legacy["production_eligible"] is False
            and legacy["original_eight_quarter_coverage_credit"] == 0, "REFRESH_LEGACY_BOUNDARY")
    legacy_boundary = {"classification": "LEGACY_HISTORICAL_PIT_UNPROVEN", "prospective_credit": 0,
        "historical_pit": "UNPROVEN", "reference": binding["legacy_summary"],
        "legacy_counts": {k: legacy["scan_counts_replayed"][k] for k in ("accounted_for", "eps_complete_companies", "valid_company_quarters")}}
    return universe, all_events, auth, recovery, legacy_boundary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binding", required=True, type=Path); parser.add_argument("--binding-sha256", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    output = external(args.output)
    require(not output.exists(), "REFRESH_FRESH_OUTPUT_REQUIRED")
    binding = object_at({"path": str(args.binding), "sha256": args.binding_sha256})
    command = portability_command(binding, output)
    sys.dont_write_bytecode = True
    sys.addaudithook(ReadOnlyGuard(output, command))
    output.mkdir(parents=True)
    universe, events, auth, recovery, legacy = inputs(binding, output)
    result = dry_run(universe, universe, events, auth, recovery, legacy, now(), issuer_readiness)
    before = binding["production_latest_identity"]
    actual = sha256(read_pinned(binding["production_latest_reference"]))
    transaction = transaction_design(before, actual, {s: "PASS" for s in CONTRACT["transaction_stages"][:-1]})
    core = result["core"]
    publication = publication_readiness()
    providers_ready = all(value["status"] == "READY" for value in core["providers"].values())
    ready = providers_ready and publication["status"] == "PASS" and publication["cer078_historical_disposition"] == "HISTORICAL_NONREPRODUCIBLE_DISPOSITION_ACCEPTED"
    final_status = "READY_FOR_FIRST_REFRESH_EXECUTION_REVIEW" if ready else "BLOCKED"
    blockers = [] if ready else (["PROVIDER_READINESS_BLOCKED"] if not providers_ready else ["FIRST_REFRESH_READINESS_REEVALUATION_FAILED"])
    summary = {"gate_j1": core["providers"], "gate_j2": "PASS", "gate_j3": "PASS", "gate_j4": "PASS",
        "gate_j5": "PASS", "gate_j6": "PASS", "gate_j7": "ATOMIC_PUBLICATION_QUALIFIED", "gate_j8": publication["cer078_historical_disposition"], "gate_j9": "UNPROVEN",
        "gate_j10": "RANKING_NOT_AUTHORIZED", "market_counts": core["market_counts"],
        "issuer_total": len(core["issuers"]), "issuer_ready": sum(r["issuer_status"] == "READY" for r in core["issuers"]),
        "valid_prospective_eps_positions": sum(len(r["feature_inputs"]["eps"]) for r in core["issuers"]),
        "revenue_observations": sum(len(r["feature_inputs"]["revenue"]) for r in core["issuers"]),
        "finite_revenue_positions": sum(v["numeric_status"] == "VALID_NUMERIC" for r in core["issuers"] for v in r["feature_inputs"]["revenue"].values()),
        "content_sha256": result["content_sha256"], "universe_identity": core["universe_identity"],
        "source_event_count": len(events), "legacy_boundary": legacy, "financial_requests": 0,
        "first_refresh_execution": 0, "production_eligible": False, "decision_eligible": False,
        "original_eight_quarter_coverage_credit": 0, "historical_pit": "UNPROVEN", "intraday_dependency": "BLOCKED_EXTERNAL",
        "first_refresh_execution_eligibility": final_status, "source_binding_sha256": args.binding_sha256,
        "execution": binding["execution"], "generated_at": now(), "validated_at": now(),
        "historical_replay_portability": binding["historical_replay_portability"],
        "final_status": final_status, "atomic_publication_gate": publication,
        "blocking_conditions": blockers}
    put_bytes(output, "DRY_RUN.json", _canonical(result))
    put_bytes(output, "READINESS_SUMMARY.json", _canonical(summary))
    put_bytes(output, "REFRESH_TRANSACTION_DESIGN.json", _canonical(transaction))
    put_bytes(output, "OUTPUT_HASHES.json", _canonical({p.name: sha256(p.read_bytes()) for p in output.iterdir() if p.is_file()}))
    print("No-network source replay and exact-universe dry run complete; First Refresh execution remains NOT_AUTHORIZED")
    return 0 if final_status == "READY_FOR_FIRST_REFRESH_EXECUTION_REVIEW" else 1


if __name__ == "__main__":
    raise SystemExit(main())
