"""Cold synthetic regression runner with a non-intervening CER078 observer."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.cer078_native_diagnostics import Observer, environment, test_ids
from src.prospective_acquisition_recovery import offline_network_guard


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("modules", nargs="+"); a = p.parse_args()
    if a.output.exists(): raise ValueError("DIAGNOSTIC_OUTPUT_MUST_BE_NEW")
    def guard(event, args):
        if event == "urllib.Request" and args and str(args[0]).startswith("file://"): return
        offline_network_guard(event, args)
    sys.addaudithook(guard)
    import src.cer078_evening_1930 as owner
    source_before = hashlib.sha256(Path(owner.__file__).read_bytes()).hexdigest()
    suite = unittest.defaultTestLoader.loadTestsFromNames(a.modules)
    order = test_ids(suite); env = environment()
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT).decode().strip()
    context = {"environment": env, "test_order": order, "execution_head": head,
               "cwd": str(ROOT), "artifact_output": str(a.output.resolve())}
    with Observer(owner, context=context, event_path=a.output.with_suffix(".events.jsonl")) as observer:
        class Result(unittest.TextTestResult):
            def startTest(self, test):
                observer.test_id = test.id()
                super().startTest(test)
        result = unittest.TextTestRunner(verbosity=2, resultclass=Result).run(suite)
    after = hashlib.sha256(Path(owner.__file__).read_bytes()).hexdigest()
    if source_before != after: raise ValueError("SUT_CHANGED_DURING_OBSERVATION")
    output = {"environment": env, "test_order": order, "tests_run": result.testsRun,
        "failures": [{"test_id": t.id(), "traceback": tb} for t,tb in result.failures],
        "errors": [{"test_id": t.id(), "traceback": tb} for t,tb in result.errors],
        "skipped": [{"test_id": t.id(), "reason": reason} for t,reason in result.skipped],
        "all_pass": result.wasSuccessful() and not result.skipped, "observations": observer.events,
        "owner_sha256": source_before, "owner_unchanged": True, "real_financial_requests": 0,
        "root_cause": "UNRESOLVED", "root_cause_resolved_by_green_rerun": False,
        "execution_head": head, "diagnostic_errors": observer.diagnostic_errors}
    a.output.parent.mkdir(parents=True, exist_ok=True)
    with a.output.open("x", encoding="utf-8") as stream: json.dump(output, stream, indent=2)
    return 0 if output["all_pass"] and not observer.diagnostic_errors else 1


if __name__ == "__main__": raise SystemExit(main())
