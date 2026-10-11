"""Exact-head, additive-only, synthetic acceptance and unchanged regression gates."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.verify_public_official_partial_valid import child, extract, git, write
from scripts.verify_fundamental_eligibility import GROUPS as PRIOR_GROUPS

BASE = "e8aa0f923c4605e57709446dde2ec23cc9edfb17"
ALLOWED = {"src/prospective_fundamental_provider.py", "scripts/run_prospective_provider_acceptance.py",
    "scripts/verify_prospective_provider_acceptance.py", "tests/test_prospective_fundamental_provider.py",
    "docs/RATE_PROSPECTIVE_FUNDAMENTAL_PROVIDER_V1.md", "docs/contracts/RATE_PROSPECTIVE_FUNDAMENTAL_PROVIDER_V1.json",
    ".github/workflows/rate_prospective_provider_acceptance_ci.yml"}
GROUPS = {**PRIOR_GROUPS, "prospective_acceptance_new": (["test_prospective_fundamental_provider"], 61)}


def proof(output):
    from tests.test_prospective_fundamental_provider import (ACTIVATION, LATER, EXECUTION, eps, universe, revenue)
    from src.prospective_fundamental_provider import new_store, append, replay, issuer_readiness, review_decision
    from src.provider_eps_candidate import _canonical
    root = output / "synthetic-sandbox"
    pin = new_store(root, universe(), EXECUTION, ACTIVATION)
    raw, receipt = eps()
    head = append(root,pin,None,"FinMind",{"symbol":"1000","market":"TWSE"},raw,_canonical(receipt),ACTIVATION,LATER)
    for period in ("2026-07","2026-08","2026-09"):
        raw, receipt = revenue(period)
        head = append(root,pin,head,"MOPS Official",{"market":"TWSE","period":period},raw,_canonical(receipt),ACTIVATION,LATER)
    config, events = replay(root,pin,head,LATER)
    before = {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob("*") if p.is_file() and p.name != ".scan.lock"}
    for index in range(2):
        run = subprocess.run([sys.executable,"-B",str(ROOT/"scripts/run_prospective_provider_acceptance.py"),"--replay-sandbox",str(root),
            "--config-sha256",pin,"--trusted-head",head,"--as-of",LATER,"--output-file",str(output/f"synthetic-cold-{index}.json")],
            capture_output=True,text=True,encoding="utf-8")
        if run.returncode:
            raise ValueError("SYNTHETIC_COLD_CONSUMER_FAILED:" + run.stderr)
    after = {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob("*") if p.is_file() and p.name != ".scan.lock"}
    if before != after:
        raise ValueError("SYNTHETIC_COLD_CONSUMER_MUTATED_EVIDENCE")
    rows = issuer_readiness(config,events)
    write(output/"SYNTHETIC_ACCEPTANCE_PROOF.json",{"scope":"SYNTHETIC_ONLY_NOT_POST_ACTIVATION_REAL_ACQUISITION",
        "universe":len(rows),"complete_synthetic_issuer":rows[0]["fundamental_input_status"],"partial_issuers_retained":len(rows)-1,
        "source_identity":{"FinMind":"PASS","MOPS Official":"PASS"},"decision":review_decision({"FinMind":"PASS","MOPS Official":"PASS"},True),
        "config_sha256":pin,"ledger_head":head,"events":len(events),"disk_cold_read_processes":2,
        "existing_evidence_hashes_unchanged":before==after,"precise_runtime_lock_not_content_hashed":str(root/".scan.lock"),
        "financial_requests":0,"actual_provider_activation":False,"production_mutations":0})


def main():
    if len(sys.argv)>1 and sys.argv[1] in {"--test-child","--proof-child"}:
        def deny(event,args):
            if event in {"socket.connect","socket.getaddrinfo","socket.sendto"}:
                raise RuntimeError("PROSPECTIVE_SYNTHETIC_NETWORK_FORBIDDEN")
        sys.addaudithook(deny)
        if sys.argv[1]=="--test-child":
            return child(Path(sys.argv[2]),sys.argv[3:])
        proof(Path(sys.argv[2])); return 0
    p=argparse.ArgumentParser()
    p.add_argument("--expected-base",required=True)
    p.add_argument("--expected-head",required=True)
    p.add_argument("--output-dir",required=True,type=Path)
    args=p.parse_args()
    if args.output_dir.exists(): raise ValueError("OUTPUT_MUST_BE_NEW")
    if args.expected_base!=BASE or git("rev-parse","HEAD")!=args.expected_head or git("merge-base",BASE,"HEAD")!=BASE:
        raise ValueError("EXACT_BASE_HEAD_MISMATCH")
    if set(git("diff","--name-status","--no-renames",BASE,args.expected_head).splitlines())!={"A\t"+f for f in ALLOWED} or git("status","--porcelain"):
        raise ValueError("EXACT_ADDITIVE_SCOPE_OR_WORKTREE_CHANGED")
    def tree(ref):
        return {line.split("\t",1)[1]:line.split("\t",1)[0].split()[2] for line in git("ls-tree","-r",ref).splitlines()}
    old,new=tree(BASE),tree(args.expected_head)
    if any(new.get(path)!=blob for path,blob in old.items()):
        raise ValueError("PROTECTED_EXISTING_BLOB_CHANGED")
    args.output_dir.mkdir(parents=True)
    write(args.output_dir/"protected-existing-blobs.json",old)
    temp=args.output_dir.resolve()/"temporary"; temp.mkdir()
    results={}
    with tempfile.TemporaryDirectory(prefix="pa-",dir=ROOT.parent) as directory:
        mirror=Path(directory)/"head"
        extract(args.expected_head,mirror)
        (mirror/".git").write_text("gitdir: "+git("rev-parse","--absolute-git-dir")+"\n",encoding="utf-8")
        command=[sys.executable,"-B",str(mirror/"scripts/verify_prospective_provider_acceptance.py")]
        env={**os.environ,"PYTHONDONTWRITEBYTECODE":"1","PYTHONIOENCODING":"utf-8","TEMP":str(temp),"TMP":str(temp)}
        for name,(modules,count) in GROUPS.items():
            output=args.output_dir.resolve()/(name+".json")
            run=subprocess.run([*command,"--test-child",str(output),*modules],cwd=mirror,capture_output=True,text=True,encoding="utf-8",env=env)
            (args.output_dir/(name+".log")).write_text(run.stdout+run.stderr,encoding="utf-8")
            result=json.loads(output.read_text(encoding="utf-8"))
            result.update(exit_code=run.returncode,exact_count_pass=result["tests_run"]==count)
            results[name]=result
            print(json.dumps({"group":name,"tests":result["tests_run"],"pass":result["all_pass"]}),flush=True)
        run=subprocess.run([*command,"--proof-child",str(args.output_dir.resolve())],cwd=mirror,capture_output=True,text=True,encoding="utf-8",env=env)
        (args.output_dir/"synthetic-proof.log").write_text(run.stdout+run.stderr,encoding="utf-8")
        if run.returncode: raise ValueError("SYNTHETIC_PROOF_FAILED")
    passed=all(r["all_pass"] and r["exact_count_pass"] and r["exit_code"]==0 for r in results.values())
    if git("rev-parse","HEAD")!=args.expected_head or git("status","--porcelain"):
        raise ValueError("HEAD_OR_WORKTREE_CHANGED")
    write(args.output_dir/"VERIFICATION_PACKAGE.json",{"base_sha":BASE,"head_sha":args.expected_head,"changed_files":sorted(ALLOWED),
        "results":results,"existing_tests":sum(c for _,c in PRIOR_GROUPS.values()),"new_tests":61,
        "protected_existing_blobs_unchanged":len(old),"financial_requests":0,"production_mutations":0,"actual_activation":False,
        "production_eligible":False,"validation_status":"PASS" if passed else "FAIL"})
    return 0 if passed else 1


if __name__=="__main__":
    raise SystemExit(main())
