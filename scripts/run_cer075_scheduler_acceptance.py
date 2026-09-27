from __future__ import annotations

import argparse, json, os, shutil, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.cer074_acceptance import atomic_write_json, load_json
from src.cer075_scheduler import build_cer075_artifacts, write_fail_closed


def main() -> int:
    ap=argparse.ArgumentParser(description='RATE CER-075 recurring 07:30 production scheduler acceptance')
    ap.add_argument('--source-bundle', required=True)
    ap.add_argument('--cer074-persisted-evidence', required=True)
    ap.add_argument('--workflow-path', default='.github/workflows/rate_production_0730_scheduler.yml')
    ap.add_argument('--output-dir', default='artifacts/cer075')
    ap.add_argument('--state-root', default='data/production/cer075_scheduler_acceptance')
    ap.add_argument('--run-head-sha', default=os.getenv('GITHUB_SHA'))
    ap.add_argument('--actions-run-id', default=os.getenv('GITHUB_RUN_ID'))
    ap.add_argument('--actions-job-id', default=os.getenv('ACTIONS_JOB_ID') or os.getenv('GITHUB_JOB'))
    ap.add_argument('--event-name', default=os.getenv('GITHUB_EVENT_NAME'))
    ap.add_argument('--event-schedule', default=os.getenv('GITHUB_EVENT_SCHEDULE'))
    ap.add_argument('--reset-state-root', action='store_true')
    args=ap.parse_args()
    out=Path(args.output_dir); out.mkdir(parents=True, exist_ok=True)
    write_fail_closed(out, run_head_sha=args.run_head_sha, actions_run_id=args.actions_run_id, actions_job_id=args.actions_job_id, event_name=args.event_name)
    try:
        root=Path(args.state_root)
        if args.reset_state_root and root.exists():
            allowed=(Path.cwd()/'data'/'production').resolve(); resolved=root.resolve()
            if allowed not in resolved.parents and resolved != allowed:
                raise RuntimeError('PRODUCTION_NAMESPACE_GUARD')
            shutil.rmtree(root)
        artifacts=build_cer075_artifacts(source_bundle=load_json(args.source_bundle), cer074_persisted=load_json(args.cer074_persisted_evidence), workflow_path=args.workflow_path, state_root=root, run_head_sha=args.run_head_sha, actions_run_id=args.actions_run_id, actions_job_id=args.actions_job_id, event_name=args.event_name, event_schedule=args.event_schedule)
        for filename,payload in artifacts.items(): atomic_write_json(out/filename,payload)
        lineage=artifacts['RATE_CER075_STATE_LINEAGE_EVIDENCE.json']; replay=artifacts['RATE_CER075_REPLAY_IDEMPOTENCY_EVIDENCE.json']; conc=artifacts['RATE_CER075_CONCURRENCY_EVIDENCE.json']; fail=artifacts['RATE_CER075_FAILURE_GATE_EVIDENCE.json']; sched=artifacts['RATE_CER075_SCHEDULER_DEFINITION_EVIDENCE.json']
        terminal=all([sched['recurring_scheduler_defined']=='PASS', sched['correct_timezone_mapping']=='PASS', lineage['decision_state_lineage']=='PASS', replay['production_state_idempotency']=='PASS', conc['concurrency_protection']=='PASS', fail['failure_closed_behavior']=='PASS', lineage['model_freeze_integrity']=='PASS'])
        print(json.dumps({'validation_status':'PASS' if terminal else 'FAIL','current_state_id':lineage.get('current_state_id'),'current_state_hash':lineage.get('current_state_hash'),'previous_state_id':lineage.get('previous_state_id')},sort_keys=True))
        return 0 if terminal else 1
    except Exception as exc:
        write_fail_closed(out, reason=str(exc), run_head_sha=args.run_head_sha, actions_run_id=args.actions_run_id, actions_job_id=args.actions_job_id, event_name=args.event_name)
        print(json.dumps({'validation_status':'BLOCKED','blocking_reason':str(exc)}), file=sys.stderr)
        return 1

if __name__=='__main__': raise SystemExit(main())
