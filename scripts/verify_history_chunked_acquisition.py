"""Exact-head additive blob protection and all inherited synthetic history regressions."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.verify_public_official_partial_valid import child, extract, git, write
from scripts.verify_history_twse_title_identity import GROUPS as INHERITED
from scripts.verify_fundamental_ranking_consumer import clean_consumer_checkout, tree
from scripts.verify_ci_applicability import network_guard

BASE = "eb9f66c55245d9ace0417f3ef6f76ed4899dda01"
ADDED = {"src/history_chunk_planning.py", "src/history_chunk_aggregation.py",
    "scripts/verify_history_chunked_acquisition.py", "tests/test_history_chunked_acquisition.py",
    "docs/contracts/RATE_HISTORY_STOCK_CHUNKED_ACQUISITION_V1.json",
    "docs/RATE_HISTORY_STOCK_CHUNKED_ACQUISITION_V1.md",
    ".github/workflows/rate_history_chunked_acquisition_ci.yml"}
NEW_COUNT = 69
GROUPS = {**INHERITED,"history_chunked_new":(["test_history_chunked_acquisition"],NEW_COUNT)}


def main():
    if len(sys.argv)>1 and sys.argv[1]=="--test-child":
        sys.addaudithook(network_guard)
        return child(Path(sys.argv[2]),sys.argv[3:])
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-base",required=True)
    parser.add_argument("--expected-head",required=True)
    parser.add_argument("--output-dir",type=Path,required=True)
    args = parser.parse_args()
    if (args.expected_base != BASE or git("rev-parse","HEAD") != args.expected_head
        or git("merge-base",BASE,args.expected_head) != BASE or git("status","--porcelain")):
        raise ValueError("CHUNK_EXACT_BASE_HEAD_OR_WORKTREE_MISMATCH")
    changed = set(git("diff","--name-status","--no-renames",BASE,args.expected_head).splitlines())
    if changed != {"A\t"+p for p in ADDED}:
        raise ValueError("CHUNK_SEVEN_ADDITIVE_FILES_REQUIRED")
    old,new = tree(BASE),tree(args.expected_head)
    if any(new.get(p)!=blob for p,blob in old.items()):
        raise ValueError("CHUNK_PROTECTED_EXISTING_BLOB_CHANGED")
    if args.output_dir.exists(): raise ValueError("OUTPUT_MUST_BE_NEW")
    args.output_dir.mkdir(parents=True)
    write(args.output_dir/"PROTECTED_MAIN_BLOBS.json",old)
    results = {}
    with tempfile.TemporaryDirectory(prefix="chunk-ci-",dir=ROOT.parent) as directory:
        mirror = Path(directory)/"head"
        extract(args.expected_head,mirror)
        (mirror/".git").write_text("gitdir: "+git("rev-parse","--absolute-git-dir")+"\n",encoding="utf-8")
        temp = Path(directory)/"tmp"; temp.mkdir()
        env = {**os.environ,"PYTHONDONTWRITEBYTECODE":"1","PYTHONIOENCODING":"utf-8","TEMP":str(temp),"TMP":str(temp)}
        for name,(modules,count) in GROUPS.items():
            repo = mirror
            if name=="consumer_new":
                repo = Path(directory)/"consumer"
                clean_consumer_checkout(args.expected_head,repo)
            report = args.output_dir.resolve()/(name+".json")
            run = subprocess.run([sys.executable,"-B",str(repo/"scripts/verify_history_chunked_acquisition.py"),
                "--test-child",str(report),*modules],cwd=repo,env=env,capture_output=True)
            (args.output_dir/(name+".log")).write_bytes(run.stdout+run.stderr)
            row = json.loads(report.read_text(encoding="utf-8"))
            row.update(exit_code=run.returncode,exact_count_pass=row["tests_run"]==count)
            results[name] = row
            print(json.dumps({"group":name,"tests":row["tests_run"],"pass":row["all_pass"]}),flush=True)
    passed = all(r["all_pass"] and r["exact_count_pass"] and not r["exit_code"] and not r["skipped"] for r in results.values())
    if git("status","--porcelain") or git("rev-parse","HEAD")!=args.expected_head:
        raise ValueError("CHUNK_EXECUTION_BINDING_CHANGED")
    write(args.output_dir/"VERIFICATION_PACKAGE.json",{"status":"PASS" if passed else "BLOCKED",
        "base_sha":BASE,"head_sha":args.expected_head,"changed_files":sorted(ADDED),
        "existing_tests":sum(n for _,n in INHERITED.values()),"new_tests":NEW_COUNT,
        "total_tests":sum(n for _,n in GROUPS.values()),"results":results,
        "protected_existing_blobs_preserved":len(old),"existing_runtime_files_changed":[],
        "additive_runtime_files":["src/history_chunk_planning.py","src/history_chunk_aggregation.py"],
        "tests_skipped":sum(len(r["skipped"]) for r in results.values()),"assertions_relaxed":0,"failure_whitelists":0,
        "official_market_data_requests":0,"real_authorizations_created":0,"real_authorization_claims":0,
        "live_executions":0,"ranking_executions":0,"production_publications":0,"strategy_ranking_files_modified":0,
        "material_scope":"SYNTHETIC_ONLY","historical_pit":"UNPROVEN","calendar_180_ready":False,
        "tpex_unit":"BLOCKED_EXTERNAL_DOCUMENTATION","intraday":"BLOCKED_EXTERNAL","production_eligible":False,"fallback":False})
    return 0 if passed else 1


if __name__=="__main__": raise SystemExit(main())
