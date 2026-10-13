"""Explicit plan, pending/formal preflight, one-time execution, or offline replay."""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src import history_acquisition_execution as h
from src.provider_eps_metadata import read_metadata


def load(path):
    return read_metadata(path.read_bytes())


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--operation", choices=("plan", "preflight", "execute", "replay"), required=True)
    p.add_argument("--main-sha", required=True)
    p.add_argument("--artifacts-root", type=Path, required=True)
    p.add_argument("--consumption-root", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--spec", type=Path)
    p.add_argument("--spec-sha256")
    p.add_argument("--plan", type=Path)
    p.add_argument("--seal", type=Path)
    p.add_argument("--authorization", type=Path)
    p.add_argument("--trusted-authorization-sha256")
    p.add_argument("--candidate", action="store_true")
    a = p.parse_args()
    roots = {"artifacts_root": a.artifacts_root, "consumption_root": a.consumption_root}
    if a.operation == "plan":
        if not a.spec or h.evidence.sha(a.spec.read_bytes()) != a.spec_sha256:
            raise ValueError("HISTORY_TRUSTED_REQUEST_SPEC_REQUIRED")
        spec = load(a.spec)
        plan = h.build_plan(a.main_sha, spec["universe"], spec["requests"], spec["source_native_cutoffs"],
                            maximum_requests=spec["maximum_authorized_requests"])
        h.main_guard(plan)
        seal = h.build_seal(plan, **roots)
        output = h.evidence.safe(a.output_dir)
        h.evidence.external_roots(output, a.consumption_root, ROOT)
        if output.exists():
            raise ValueError("HISTORY_PLAN_OUTPUT_MUST_BE_NEW")
        output.mkdir(parents=True)
        for name, value in (("PLAN", plan), ("SEAL", seal), ("CANDIDATE_AUTHORIZATION", h.candidate_authorization(seal))):
            h.evidence.put_json(output / (name + ".json"), value)
        print(h.evidence.canonical({"status": h.PENDING, "plan_id": plan["plan_id"], "network_requests": 0}).decode())
        return 0
    if not all((a.plan, a.seal, a.authorization)):
        raise ValueError("HISTORY_BINDING_FILES_REQUIRED")
    plan, seal, auth = load(a.plan), load(a.seal), load(a.authorization)
    if plan["main_sha"] != a.main_sha:
        raise ValueError("HISTORY_MAIN_DRIFT")
    if a.operation == "replay":
        from scripts.verify_ci_applicability import network_guard
        sys.addaudithook(network_guard)
        result = h.replay(a.output_dir, plan, seal, auth, a.consumption_root)
    elif a.operation == "preflight":
        h.preflight(plan, seal, auth, **roots, trusted_authorization_sha256=a.trusted_authorization_sha256, candidate=a.candidate)
        result = {"status": "PASS", "authorization_status": auth["status"], "network_requests": 0}
    else:
        if a.candidate:
            raise ValueError("HISTORY_PENDING_CANDIDATE_NOT_EXECUTABLE")
        result = h.execute(plan, seal, auth, **roots, output_root=a.output_dir,
                           trusted_authorization_sha256=a.trusted_authorization_sha256)
    print(h.evidence.canonical({k: result[k] for k in ("status", "actual_requests", "ledger_head", "authorization_status", "network_requests") if k in result}).decode())
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
