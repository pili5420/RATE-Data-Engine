"""Offline plan/preflight or explicitly authorized one-attempt discovery only."""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src import session_discovery_execution as m
from src.provider_eps_metadata import read_metadata


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--operation", choices=("plan", "preflight", "execute"), required=True)
    p.add_argument("--main-sha", required=True)
    p.add_argument("--artifacts-root", type=Path, required=True)
    p.add_argument("--consumption-root", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--plan", type=Path)
    p.add_argument("--seal", type=Path)
    p.add_argument("--authorization", type=Path)
    a = p.parse_args()
    roots = {"artifacts_root": a.artifacts_root, "consumption_root": a.consumption_root}
    m.external_roots(**{k.replace("_root", ""): v for k, v in roots.items()})
    plan = m.build_plan(a.main_sha)
    if a.operation == "plan":
        output = m.safe(a.output_dir)
        m.external_roots(output, a.consumption_root)
        if output.exists():
            raise ValueError("DISCOVERY_OUTPUT_MUST_BE_NEW")
        seal = m.build_seal(plan, **roots)
        output.mkdir(parents=True)
        m.put_json(output / "PLAN.json", plan)
        m.put_json(output / "SEAL.json", seal)
        m.put_json(output / "CANDIDATE_AUTHORIZATION.json", m.candidate_authorization(seal))
        print(m.canonical({"status": m.PENDING, "plan_id": plan["plan_id"], "network_requests": 0}).decode())
        return 0
    if not all((a.plan, a.seal, a.authorization)):
        raise ValueError("DISCOVERY_FORMAL_BINDING_FILES_REQUIRED")
    loaded = read_metadata(a.plan.read_bytes())
    if m.canonical(loaded) != m.canonical(plan):
        raise ValueError("DISCOVERY_PLAN_MISMATCH")
    seal = read_metadata(a.seal.read_bytes())
    authorization = read_metadata(a.authorization.read_bytes())
    if a.operation == "preflight":
        m.preflight(plan, seal, authorization, **roots, candidate=True)
        print(m.canonical({"status": "READY_FOR_CONTROL_CENTER_AUTHORIZATION_REVIEW", "network_requests": 0,
                           "authorization_status": m.PENDING}).decode())
        return 0
    result = m.execute(plan, seal, authorization, **roots, output_root=a.output_dir)
    print(m.canonical({"status": result["status"], "actual_requests": result["actual_requests"],
                       "ledger_head": result["ledger_head"]}).decode())
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
