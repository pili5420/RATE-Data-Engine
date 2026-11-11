"""Offline artifact reader only. No collector import, activation or OS query."""
import argparse
import json
from pathlib import Path
from evidence import assess, strict_json, need, Refused


def evaluate(raw, expected_head, expected_run_id, expected_run_attempt):
    try:
        packet=strict_json(raw)
        need(packet['realm']=='RUNNER_ONLY_NOT_TARGET_HOST_EVIDENCE','RUNNER_ONLY_SCOPE_REQUIRED')
        context=packet['runner']
        need(context['head']==expected_head and context['run_id']==expected_run_id and context['run_attempt']==expected_run_attempt,'INDEPENDENT_CI_CONTEXT_MISMATCH')
    except (Refused,KeyError,TypeError):
        return {'status':'INDETERMINATE','reason':'INDEPENDENT_RUNNER_BINDING_FAILED','target_host_qualified':False,'execution_authorized':False,'GUI_Gate2':'BLOCKED','RT04':'BLOCKED','original_halt_root_cause':'UNKNOWN','no_auto_next':True}
    return assess(raw)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--input',required=True);p.add_argument('--expected-head',required=True);p.add_argument('--expected-run-id',required=True);p.add_argument('--expected-run-attempt',required=True);a=p.parse_args()
    print(json.dumps(evaluate(Path(a.input).read_bytes(),a.expected_head,a.expected_run_id,a.expected_run_attempt),indent=2))
