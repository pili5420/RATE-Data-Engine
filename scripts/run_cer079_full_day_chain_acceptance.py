from __future__ import annotations

import argparse, json, os, shutil, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.cer074_acceptance import atomic_write_json, load_json
from src.cer079_full_day_chain import build_cer079_artifacts, write_fail_closed


def main() -> int:
    ap=argparse.ArgumentParser(description='RATE CER-079 full-day 4-cadence production chain acceptance')
    ap.add_argument('--source-bundle', required=True)
    ap.add_argument('--cer074-persisted-evidence', required=True)
    ap.add_argument('--cer075-persisted-evidence', required=True)
    ap.add_argument('--cer076-persisted-evidence', required=True)
    ap.add_argument('--cer077-persisted-evidence', required=True)
    ap.add_argument('--cer078-persisted-evidence', required=True)
    ap.add_argument('--scheduler-workflow-path', default='.github/workflows/rate_production_0730_scheduler.yml')
    ap.add_argument('--output-dir', default='artifacts/cer079')
    ap.add_argument('--state-root', default='data/production/cer079_full_day_chain_acceptance')
    ap.add_argument('--run-head-sha', default=os.getenv('GITHUB_SHA'))
    ap.add_argument('--actions-run-id', default=os.getenv('GITHUB_RUN_ID'))
    ap.add_argument('--actions-job-id', default=os.getenv('ACTIONS_JOB_ID') or os.getenv('GITHUB_JOB'))
    ap.add_argument('--event-name', default=os.getenv('GITHUB_EVENT_NAME'))
    ap.add_argument('--reset-state-root', action='store_true')
    args=ap.parse_args()
    out=Path(args.output_dir); out.mkdir(parents=True, exist_ok=True)
    write_fail_closed(out, run_head_sha=args.run_head_sha, actions_run_id=args.actions_run_id, actions_job_id=args.actions_job_id, event_name=args.event_name)
    try:
        root=Path(args.state_root)
        if args.reset_state_root and root.exists():
            allowed=(Path.cwd()/'data'/'production').resolve(); resolved=root.resolve()
            if allowed not in resolved.parents and resolved != allowed: raise RuntimeError('PRODUCTION_NAMESPACE_GUARD')
            shutil.rmtree(root)
        artifacts=build_cer079_artifacts(source_bundle=load_json(args.source_bundle), cer074_persisted=load_json(args.cer074_persisted_evidence), cer075_persisted=load_json(args.cer075_persisted_evidence), cer076_persisted=load_json(args.cer076_persisted_evidence), cer077_persisted=load_json(args.cer077_persisted_evidence), cer078_persisted=load_json(args.cer078_persisted_evidence), state_root=root, scheduler_workflow_path=args.scheduler_workflow_path, run_head_sha=args.run_head_sha, actions_run_id=args.actions_run_id, actions_job_id=args.actions_job_id, event_name=args.event_name)
        for filename,payload in artifacts.items(): atomic_write_json(out/filename,payload)
        lineage=artifacts['RATE_CER079_FULL_DAY_LINEAGE_EVIDENCE.json']; replay=artifacts['RATE_CER079_DETERMINISTIC_FULL_DAY_REPLAY.json']; idem=artifacts['RATE_CER079_FULL_DAY_IDEMPOTENCY_EVIDENCE.json']; failure=artifacts['RATE_CER079_FAILURE_GATE_EVIDENCE.json']
        terminal=all([lineage['full_day_state_chain']=='PASS', replay['deterministic_full_day_replay']=='PASS', idem['full_day_idempotency']=='PASS', failure['failure_closed_behavior']=='PASS'])
        print(json.dumps({'validation_status':'PASS' if terminal else 'FAIL','final_state_id':lineage.get('final_state_id'),'final_state_hash':lineage.get('final_state_hash'),'trading_date':'2026-09-18'}, sort_keys=True))
        return 0 if terminal else 1
    except Exception as exc:
        write_fail_closed(out, reason=str(exc), run_head_sha=args.run_head_sha, actions_run_id=args.actions_run_id, actions_job_id=args.actions_job_id, event_name=args.event_name)
        print(json.dumps({'validation_status':'BLOCKED','blocking_reason':str(exc)}), file=sys.stderr)
        return 1

if __name__=='__main__': raise SystemExit(main())
