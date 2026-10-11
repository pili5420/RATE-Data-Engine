"""Exact-head additive scope and inherited synthetic regressions, zero skips."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.verify_public_official_partial_valid import child, extract, git, write
from scripts.verify_ci_applicability import CURRENT_MAIN_GROUPS, GOVERNANCE_TEST_COUNT
from src.prospective_acquisition_recovery import offline_network_guard

BASE = "dbd0983caf883fa9a39eb187fb3d01f192ecd61e"
NEW_COUNT = 29
ALLOWED = {"src/historical_replay_portability.py", "scripts/run_historical_replay_portability.py",
    "scripts/verify_historical_replay_portability.py", "tests/test_historical_replay_portability.py",
    "docs/contracts/RATE_HISTORICAL_REPLAY_PORTABILITY_V1.json", "docs/RATE_HISTORICAL_REPLAY_PORTABILITY_V1.md",
    ".github/workflows/rate_historical_replay_portability_ci.yml"}
GROUPS = {**CURRENT_MAIN_GROUPS, "ci_applicability_inherited":(["test_ci_applicability"], GOVERNANCE_TEST_COUNT),
          "diagnostics_inherited":(["test_cer078_native_diagnostics"],14),
          "portability_new":(["test_historical_replay_portability"],NEW_COUNT)}


def main():
    if len(sys.argv)>1 and sys.argv[1]=="--test-child":
        def guard(event,args):
            if event=="urllib.Request" and args and str(args[0]).startswith("file://"): return
            offline_network_guard(event,args)
        sys.addaudithook(guard)
        return child(Path(sys.argv[2]),sys.argv[3:])
    parser=argparse.ArgumentParser()
    parser.add_argument("--expected-base",required=True); parser.add_argument("--expected-head",required=True)
    parser.add_argument("--output-dir",type=Path,required=True); args=parser.parse_args()
    if args.expected_base!=BASE or git("rev-parse","HEAD")!=args.expected_head or git("merge-base",BASE,"HEAD")!=BASE:
        raise ValueError("EXACT_BASE_HEAD_MISMATCH")
    if git("status","--porcelain") or set(git("diff","--name-status","--no-renames",BASE,"HEAD").splitlines())!={"A\t"+p for p in ALLOWED}:
        raise ValueError("ADDITIVE_SCOPE_OR_WORKTREE_CHANGED")
    def tree(ref):
        return {line.split("\t",1)[1]:line.split("\t",1)[0].split()[2] for line in git("ls-tree","-r",ref).splitlines()}
    old,new=tree(BASE),tree("HEAD")
    if any(new.get(path)!=blob for path,blob in old.items()): raise ValueError("PROTECTED_BLOB_CHANGED")
    if args.output_dir.exists(): raise ValueError("OUTPUT_MUST_BE_NEW")
    args.output_dir.mkdir(parents=True); results={}
    # Canonical paths avoid Windows 8.3 TEMP aliases in exact provenance fixtures.
    with tempfile.TemporaryDirectory(prefix="rpci-",dir=ROOT.parent.resolve()) as directory:
        mirror=Path(directory)/"h"; extract(args.expected_head,mirror)
        (mirror/".git").write_text("gitdir: "+git("rev-parse","--absolute-git-dir")+"\n",encoding="utf-8")
        temp=Path(directory)/"t"; temp.mkdir()
        env={**os.environ,"PYTHONDONTWRITEBYTECODE":"1","PYTHONIOENCODING":"utf-8","TEMP":str(temp.resolve()),"TMP":str(temp.resolve())}
        for name,(modules,count) in GROUPS.items():
            path=args.output_dir.resolve()/(name+".json")
            run=subprocess.run([sys.executable,"-B",str(mirror/"scripts/verify_historical_replay_portability.py"),
                "--test-child",str(path),*modules],cwd=mirror,env=env,capture_output=True)
            (args.output_dir/(name+".log")).write_bytes(run.stdout+run.stderr)
            result=json.loads(path.read_text(encoding="utf-8")); result.update(exit_code=run.returncode,exact_count_pass=result["tests_run"]==count)
            results[name]=result
            print(json.dumps({"group":name,"tests":result["tests_run"],"pass":result["all_pass"]}),flush=True)
            if not result["all_pass"]:
                print(json.dumps({"group":name,"failures":result["failures"],"errors":result["errors"]}),flush=True)
    passed=all(r["all_pass"] and r["exact_count_pass"] and not r["exit_code"] and not r["skipped"] for r in results.values())
    if git("status","--porcelain") or git("rev-parse","HEAD")!=args.expected_head: raise ValueError("HEAD_OR_WORKTREE_CHANGED")
    write(args.output_dir/"VERIFICATION_PACKAGE.json",{"base_sha":BASE,"head_sha":args.expected_head,"changed_files":sorted(ALLOWED),
        "results":results,"existing_tests":sum(c for name,(_,c) in GROUPS.items() if name!="portability_new"),"new_tests":NEW_COUNT,
        "protected_existing_blobs_unchanged":len(old),"financial_requests":0,"network_requests_runtime":0,"first_refresh_execution":0,
        "production_mutations":0,"tests_skipped":0,"assertions_relaxed":0,"failure_whitelists":0,"status":"PASS" if passed else "BLOCKED"})
    return 0 if passed else 1


if __name__=="__main__": raise SystemExit(main())
