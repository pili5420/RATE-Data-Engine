"""Opt-in governance sidecar; never acquires data or changes a campaign."""
from pathlib import Path
import os
import subprocess

from . import history_acquisition_execution as h
from . import history_chunk_planning as chunks
from .eps_duration_facts.model import require
from .provider_eps_metadata import read_metadata

CONTRACT = "RATE_HISTORY_ACCEPTANCE_SIDECAR_V1"
FROZEN_MAIN = "fbdfbfcf0a003cd6de49911bc0a784275a32031c"
REPOSITORY = "pili5420/RATE-Data-Engine"
CAMPAIGN = r"D:\R1-20261015-01"
LEDGER = r"D:\RATE-MH-Governance\R1-20261015-01"
OWNER_PATHS = ["src/history_acceptance_sidecar.py", "scripts/run_history_acceptance_sidecar.py",
               "docs/contracts/RATE_HISTORY_ACCEPTANCE_SIDECAR_V1.json"]


def owners():
    return {p: h.evidence.sha((h.ROOT / p).read_bytes().replace(b"\r\n", b"\n")) for p in OWNER_PATHS}


def load(path):
    return read_metadata(h.evidence.safe(path).read_bytes())


def trusted_file(path, trusted_sha256):
    path = h.evidence.safe(path)
    body = path.read_bytes()
    require(chunks.digest(trusted_sha256) and h.evidence.sha(body) == trusted_sha256,
            "ACCEPTANCE_EXTERNAL_TRUST_PIN_MISMATCH")
    value = read_metadata(body)
    require(body == h.evidence.canonical(value), "ACCEPTANCE_CANONICAL_BYTES_REQUIRED")
    return value


def snapshot(root, *, exclude=()):
    root = h.evidence.safe(root)
    result = {}
    for path in sorted(root.rglob("*")):
        if path in exclude:
            continue
        checked = h.evidence.safe(path)
        if path.is_file():
            result[str(path.relative_to(root))] = h.evidence.sha(checked.read_bytes())
    return result


def context(manifest, scope, approval, universe, *, trusted_approval_sha256,
            trusted_manifest_sha256, campaign_root, ledger_root, synthetic=False):
    require(type(synthetic) is bool, "ACCEPTANCE_SCOPE_INVALID")
    campaign, ledger = h.evidence.safe(campaign_root), h.evidence.safe(ledger_root)
    require(not (campaign == ledger or campaign in ledger.parents or ledger in campaign.parents),
            "ACCEPTANCE_ROOT_OVERLAP")
    # The repository's accepted external-root validator also rejects checkout/state roots.
    h.evidence.external_roots(campaign, ledger, h.ROOT)
    require(manifest["manifest_sha256"] == trusted_manifest_sha256 and chunks.digest(trusted_manifest_sha256),
            "ACCEPTANCE_MANIFEST_TRUST_PIN_REQUIRED")
    if not synthetic:
        require(os.name == "nt" and campaign == h.evidence.safe(CAMPAIGN)
                and ledger == h.evidence.safe(LEDGER) and manifest["main_sha"] == FROZEN_MAIN,
                "ACCEPTANCE_FROZEN_CAMPAIGN_ROOT_REQUIRED")
    chunks.validate_manifest(manifest, scope, approval, trusted_approval_sha256=trusted_approval_sha256,
                             main_sha=manifest["main_sha"], universe=universe, synthetic=synthetic)
    return {"manifest": manifest, "campaign_root": str(campaign), "ledger_root": str(ledger),
            "synthetic": synthetic, "binding": {"repository": REPOSITORY,
                "frozen_main_sha": manifest["main_sha"], "manifest_sha256": manifest["manifest_sha256"],
                "scope_sha256": manifest["scope_sha256"], "universe_sha256": manifest["universe_sha256"],
                "campaign_root_identity": h.evidence.root_identity(campaign),
                "acceptance_root_identity": h.evidence.root_identity(ledger),
                "material_scope": "SYNTHETIC_ONLY" if synthetic else "CONTROL_CENTER_GOVERNANCE_ONLY"}}


def verify_chunk(ctx, ordinal):
    require(type(ordinal) is int and 1 <= ordinal <= ctx["manifest"]["chunk_count"], "ACCEPTANCE_CHUNK_INVALID")
    chunk = ctx["manifest"]["chunks"][ordinal - 1]
    base = Path(ctx["campaign_root"]) / chunk["chunk_id"]
    run, consumption = base / "evidence/run-001", base / "consumption"
    require(not (Path(ctx["campaign_root"]) / "HALTED.json").exists()
            and not (run / "STOP.json").exists(), "ACCEPTANCE_STOP_OR_HALTED")
    before = snapshot(base)
    for path in base.rglob("*.json"):
        require(path.read_bytes() == h.evidence.canonical(load(path)), "ACCEPTANCE_ORIGINAL_BYTES_INVALID")
    plan, seal, auth, result = [load(run / (name + ".json")) for name in ("plan", "seal", "authorization", "RESULT")]
    require(plan == chunks.chunk_plan(ctx["manifest"], chunk["chunk_id"]), "ACCEPTANCE_ORIGINAL_PLAN_MISMATCH")
    require(seal == h.build_seal(plan, base / "evidence", consumption), "ACCEPTANCE_ORIGINAL_SEAL_MISMATCH")
    h.validate_authorization(auth, seal)
    claims = list(consumption.glob("*.json"))
    require(len(claims) == 1 and claims[0].name == auth["authorization_id"] + ".json", "ACCEPTANCE_CONSUMPTION_INVALID")
    claim = load(claims[0])
    require(claim["status"] == "CONSUMED" and claim["authorization_sha256"] == auth["authorization_sha256"],
            "ACCEPTANCE_CONSUMPTION_INVALID")
    require(result["status"] == "PASS" and result["actual_requests"] == result["completed_checkpoints"]
            == chunk["request_count"], "ACCEPTANCE_RESULT_INCOMPLETE")
    for name, value in (("plan", plan), ("seal", seal), ("authorization", auth), ("RESULT", result)):
        require((run / (name + ".json")).read_bytes() == h.evidence.canonical(value), "ACCEPTANCE_ORIGINAL_BYTES_INVALID")
    proof = chunks._cold_replay_success(run, consumption, plan, seal, result)
    require(snapshot(base) == before, "ACCEPTANCE_ORIGINAL_EVIDENCE_CHANGED")
    latest_validation = max(h.evidence.stamp(load(p)["validated_at"]) for p in (run / "receipts").iterdir())
    binding = {**ctx["binding"], "chunk_ordinal": ordinal, "chunk_id": chunk["chunk_id"],
        "plan_sha256": plan["plan_sha256"], "seal_sha256": seal["seal_sha256"],
        "authorization_id": auth["authorization_id"], "authorization_sha256": auth["authorization_sha256"],
        "result_sha256": h.evidence.sha((run / "RESULT.json").read_bytes()), "ledger_head": result["ledger_head"],
        "consumption_sha256": h.evidence.sha(claims[0].read_bytes()), "request_count": chunk["request_count"],
        "execution_evidence_inventory_sha256": h.evidence.sha(before)}
    return {"status": "PASS", "binding": binding, "cold_replay": proof,
            "source_files": before, "latest_validation": latest_validation.isoformat()}


def acceptance_record(ctx, path, trusted_sha256):
    require(not h.evidence.safe(path).is_relative_to(h.evidence.safe(ctx["ledger_root"])),
            "ACCEPTANCE_TRUST_CANNOT_ORIGINATE_INSIDE_LEDGER")
    value = trusted_file(path, trusted_sha256)
    core = h.evidence.verify_identity(value, "rate-history-acceptance-record-", "acceptance_id", "acceptance_sha256")
    proof = verify_chunk(ctx, value.get("chunk_ordinal"))
    expected = {"artifact_kind": "RATE_HISTORY_CHUNK_CONTROL_CENTER_ACCEPTANCE_V1", "contract": CONTRACT,
                "issuer": "CONTROL_CENTER", "decision": "CHUNK_ACCEPTED", **proof["binding"],
                "accepted_at": value.get("accepted_at")}
    require(core == expected, "ACCEPTANCE_RECORD_BINDING_OR_FIELDS_INVALID")
    accepted = h.evidence.stamp(value["accepted_at"])
    require(h.evidence.stamp(proof["latest_validation"]) <= accepted <= h.evidence.stamp(h.evidence.now()),
            "ACCEPTANCE_DECISION_TIME_INVALID")
    return value, proof


def genesis_anchor(ctx, path, trusted_sha256):
    require(not h.evidence.safe(path).is_relative_to(h.evidence.safe(ctx["ledger_root"])), "ACCEPTANCE_EXTERNAL_GENESIS_REQUIRED")
    value = trusted_file(path, trusted_sha256)
    core = h.evidence.verify_identity(value, "rate-history-acceptance-genesis-", "genesis_id", "genesis_sha256")
    expected = {"artifact_kind": "RATE_HISTORY_ACCEPTANCE_GENESIS_V1", "contract": CONTRACT,
        "issuer": "CONTROL_CENTER", **ctx["binding"], "first_chunk_ordinal": 1,
        "first_acceptance_file_sha256": value.get("first_acceptance_file_sha256"),
        "prior_accepted_chunks": 0, "prior_accepted_requests": 0}
    require(core == expected and chunks.digest(core["first_acceptance_file_sha256"]), "ACCEPTANCE_GENESIS_INVALID")
    return value


def _progress(ctx, events):
    return {"accepted_chunks": len(events), "accepted_requests": sum(e["request_count"] for e in events),
            "total_chunks": ctx["manifest"]["chunk_count"], "total_requests": ctx["manifest"]["scope_entry_count"]}


def _event(record, record_sha, genesis_sha, ordinal, previous):
    return h.evidence.identified({"artifact_kind": "RATE_HISTORY_ACCEPTANCE_EVENT_V1", "contract": CONTRACT,
        "ordinal": ordinal, "previous_event_sha256": previous, "genesis_file_sha256": genesis_sha,
        "acceptance_file_sha256": record_sha, "acceptance_id": record["acceptance_id"],
        "chunk_id": record["chunk_id"], "chunk_ordinal": record["chunk_ordinal"],
        "request_count": record["request_count"], "binding": {k: record[k] for k in (
            "result_sha256", "ledger_head", "manifest_sha256", "plan_sha256", "seal_sha256",
            "authorization_id", "authorization_sha256", "consumption_sha256")}},
        "rate-history-acceptance-event-", "event_id", "event_sha256")


def _intent(event):
    return {"artifact_kind": "RATE_HISTORY_ACCEPTANCE_APPEND_INTENT_V1", "event": event}


def _checkpoint(ctx, events):
    return h.evidence.identified({"artifact_kind": "RATE_HISTORY_ACCEPTANCE_CHECKPOINT_V1", "contract": CONTRACT,
        **ctx["binding"], **_progress(ctx, events), "head": events[-1]["event_sha256"]},
        "rate-history-acceptance-checkpoint-", "checkpoint_id", "checkpoint_sha256")


def replay(ctx, *, genesis_path, trusted_genesis_sha256, trusted_records, expected_head):
    """Trust pins and last known head must come from outside this ledger."""
    genesis = genesis_anchor(ctx, genesis_path, trusted_genesis_sha256)
    root = h.evidence.safe(ctx["ledger_root"])
    # Decide by exact path before any read: Windows denies reads of our held lock.
    files = snapshot(root, exclude={root / ".scan.lock"}) if root.exists() else {}
    if root.exists():
        require(all(p.is_file() or str(p.relative_to(root)) in {"events", "intents", "records", "checkpoints"}
                    for p in root.rglob("*")), "ACCEPTANCE_UNEXPECTED_DIRECTORY")
    if not files:
        require(expected_head is None, "ACCEPTANCE_LEDGER_TRUNCATED_OR_STALE_HEAD")
        return {"status": "EMPTY", "head": None, "events": [], "proofs": [], **_progress(ctx, [])}
    require((root / "genesis.json").is_file() and load(root / "genesis.json") == genesis
            and h.evidence.sha((root / "genesis.json").read_bytes()) == trusted_genesis_sha256,
            "ACCEPTANCE_STORED_GENESIS_MISMATCH")
    paths = sorted((root / "events").glob("*.json"))
    require(paths, "ACCEPTANCE_INCOMPLETE_APPEND_HALT")
    expected_files, events, proofs, previous_time = {"genesis.json"}, [], [], None
    for ordinal, path in enumerate(paths, 1):
        require(path.name == f"{ordinal:06}.json", "ACCEPTANCE_EVENT_SEQUENCE_INVALID")
        event = load(path)
        sha = event.get("acceptance_file_sha256")
        require(sha in trusted_records, "ACCEPTANCE_PRIOR_RECORD_EXTERNAL_PIN_REQUIRED")
        record, proof = acceptance_record(ctx, trusted_records[sha], sha)
        require((root / "records" / (sha + ".json")).read_bytes() == h.evidence.canonical(record),
                "ACCEPTANCE_STORED_RECORD_CHANGED")
        require(record["chunk_ordinal"] == ordinal, "ACCEPTANCE_DUPLICATE_OR_OUT_OF_ORDER_CHUNK")
        require(ordinal != 1 or sha == genesis["first_acceptance_file_sha256"], "ACCEPTANCE_FIRST_RECORD_UNANCHORED")
        require(previous_time is None or previous_time <= h.evidence.stamp(record["accepted_at"]), "ACCEPTANCE_TIME_REGRESSED")
        previous_time = h.evidence.stamp(record["accepted_at"])
        expected = _event(record, sha, trusted_genesis_sha256, ordinal, events[-1]["event_sha256"] if events else None)
        require(event == expected and path.read_bytes() == h.evidence.canonical(expected), "ACCEPTANCE_EVENT_HASH_CHAIN_INVALID")
        events.append(event); proofs.append(proof)
        for directory, value in (("intents", _intent(event)), ("checkpoints", _checkpoint(ctx, events))):
            item = root / directory / path.name
            require(item.read_bytes() == h.evidence.canonical(value), "ACCEPTANCE_INCOMPLETE_OR_CHANGED_APPEND_HALT")
            expected_files.add(str(item.relative_to(root)))
        expected_files.update((str(path.relative_to(root)), str(Path("records") / (sha + ".json"))))
    require(set(files) == expected_files, "ACCEPTANCE_ORPHAN_OR_INCOMPLETE_APPEND_HALT")
    require(expected_head == events[-1]["event_sha256"], "ACCEPTANCE_LEDGER_TRUNCATED_OR_STALE_HEAD")
    return {"status": "PASS", "head": expected_head, "events": events, "proofs": proofs, **_progress(ctx, events)}


def _activation(ctx, path, trusted_sha256, genesis_sha):
    permit = trusted_file(path, trusted_sha256)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=h.ROOT).decode().strip()
    require(not subprocess.check_output(["git", "status", "--porcelain"], cwd=h.ROOT).strip(), "ACCEPTANCE_DEPLOYMENT_DIRTY")
    for relative, sha in owners().items():
        require(h.evidence.sha(subprocess.check_output(["git", "show", head + ":" + relative], cwd=h.ROOT)) == sha,
                "ACCEPTANCE_DEPLOYMENT_OWNER_DRIFT")
    require(permit == {"artifact_kind": "RATE_HISTORY_ACCEPTANCE_SIDECAR_ACTIVATION_V1", "contract": CONTRACT,
        "issuer": "CONTROL_CENTER", "status": "SIDECAR_LEDGER_BOOTSTRAP_AUTHORIZED", **ctx["binding"],
        "sidecar_head": head, "sidecar_owner_sha256_lf": owners(), "genesis_file_sha256": genesis_sha,
        "maximum_chunk_ordinal": permit.get("maximum_chunk_ordinal")}, "ACCEPTANCE_SEPARATE_ACTIVATION_REQUIRED")
    require(type(permit["maximum_chunk_ordinal"]) is int and 1 <= permit["maximum_chunk_ordinal"] <= ctx["manifest"]["chunk_count"],
            "ACCEPTANCE_ACTIVATION_SCOPE_INVALID")
    return permit


def _put(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(body); stream.flush(); os.fsync(stream.fileno())
    if os.name != "nt":
        fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    require(path.read_bytes() == body, "ACCEPTANCE_EXCLUSIVE_CREATE_READBACK_FAILED")


def append_acceptance(ctx, *, record_path, trusted_record_sha256, genesis_path, trusted_genesis_sha256,
                      trusted_records, expected_head, activation_path, trusted_activation_sha256):
    """Reserved for separately approved bootstrap. No activation builder is provided."""
    permit = _activation(ctx, activation_path, trusted_activation_sha256, trusted_genesis_sha256)
    genesis = genesis_anchor(ctx, genesis_path, trusted_genesis_sha256)
    record, proof = acceptance_record(ctx, record_path, trusted_record_sha256)
    require(record["chunk_ordinal"] <= permit["maximum_chunk_ordinal"], "ACCEPTANCE_ACTIVATION_SCOPE_EXCEEDED")
    pins = {**trusted_records, trusted_record_sha256: record_path}
    root = h.evidence.safe(ctx["ledger_root"])
    root.mkdir(parents=True, exist_ok=True)
    # Separate root: never acquire the campaign/scanner locks or write their evidence.
    with h.exclusive_scan(root):
        prior = replay(ctx, genesis_path=genesis_path, trusted_genesis_sha256=trusted_genesis_sha256,
                       trusted_records=pins, expected_head=expected_head)
        for event in prior["events"]:
            if event["chunk_id"] == record["chunk_id"]:
                require(event["acceptance_file_sha256"] == trusted_record_sha256, "ACCEPTANCE_CONFLICT_HALT")
                return {**prior, "idempotent_noop": True}
        require(record["chunk_ordinal"] == prior["accepted_chunks"] + 1, "ACCEPTANCE_NEXT_CHUNK_REQUIRED")
        require(prior["events"] or trusted_record_sha256 == load(genesis_path)["first_acceptance_file_sha256"],
                "ACCEPTANCE_GENESIS_TRUST_REQUIRED")
        if prior["events"]:
            previous = load(pins[prior["events"][-1]["acceptance_file_sha256"]])
            require(h.evidence.stamp(previous["accepted_at"]) <= h.evidence.stamp(record["accepted_at"]),
                    "ACCEPTANCE_TIME_REGRESSED")
        event = _event(record, trusted_record_sha256, trusted_genesis_sha256, record["chunk_ordinal"], prior["head"])
        name = f"{record['chunk_ordinal']:06}.json"
        _put(root / "intents" / name, h.evidence.canonical(_intent(event)))
        if not prior["events"]:
            _put(root / "genesis.json", h.evidence.canonical(genesis))
        _put(root / "records" / (trusted_record_sha256 + ".json"), h.evidence.canonical(record))
        _put(root / "events" / name, h.evidence.canonical(event))
        # Checkpoint is the final exclusive-create commit point, never a mutable pointer.
        _put(root / "checkpoints" / name, h.evidence.canonical(_checkpoint(ctx, [*prior["events"], event])))
        result = replay(ctx, genesis_path=genesis_path, trusted_genesis_sha256=trusted_genesis_sha256,
                        trusted_records=pins, expected_head=event["event_sha256"])
        return {**result, "idempotent_noop": False, "new_chunk_cold_replay": proof["cold_replay"]}
