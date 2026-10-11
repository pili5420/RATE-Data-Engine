"""I-A2 exact-head additive scope, all inherited tests, synthetic evidence only."""
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
from scripts.verify_prospective_provider_acceptance import GROUPS as PRIOR_GROUPS

BASE = "feff6a487ed96e7c2c3535c95f3bd62a06ad5cb7"
NEW_COUNT = 65
ALLOWED = {"src/prospective_provider_activation.py", "scripts/run_prospective_provider_activation.py",
    "scripts/verify_prospective_provider_activation.py", "tests/test_prospective_provider_activation.py",
    "docs/contracts/RATE_PROSPECTIVE_PROVIDER_ACTIVATION_V1.json", "docs/RATE_PROSPECTIVE_PROVIDER_ACTIVATION_V1.md",
    ".github/workflows/rate_prospective_provider_activation_ci.yml"}
GROUPS = {**PRIOR_GROUPS,"prospective_activation_new":(["test_prospective_provider_activation"],NEW_COUNT)}


def proof(output):
    from tests.test_prospective_provider_activation import (authority_patches,authority_fixture,FakeGate,MAIN,
        ACTIVATION,REQUESTED,RECEIVED,VALIDATED,LATER,EXECUTION,universe,eps,revenue)
    from src import prospective_provider_activation as a
    from scripts import run_prospective_provider_activation as pipeline
    from src.provider_eps_candidate import _canonical
    from src.eps_duration_facts.raw import sha256
    with authority_patches():
        root=output/"synthetic-evidence"; authority=output/"synthetic-authority"
        raw,r=authority_fixture()
        pin=a.seal(authority,raw,sha256(raw),r,sha256(r),MAIN,VALIDATED)
        config_pin=pipeline.create(root,authority,pin,universe(),EXECUTION)
        head=None
        targets=[("FinMind",{"symbol":"1000","market":"TWSE"},eps())]+[
            ("MOPS Official",{"market":"TWSE","period":period},revenue(period,request_started_at=LATER,retrieval_timestamp=LATER))
            for period in ("2026-07","2026-08","2026-09")]
        for provider,target,(body,receipt) in targets:
            clock=iter((REQUESTED,REQUESTED,REQUESTED,VALIDATED,LATER) if head is None else (LATER,)*5).__next__
            head=pipeline.acquire_once(root,config_pin,head,provider,target,
                lambda directory,intent,b=body,r=receipt:(b,_canonical(r)),gate=FakeGate(),clock=clock)
        config,auth,events=pipeline.replay(root,config_pin,head,LATER)
        before={str(p.relative_to(root)):sha256(p.read_bytes()) for p in root.rglob("*") if p.is_file() and p.name!=".scan.lock"}
        for n in range(2):
            run=subprocess.run([sys.executable,"-B",str(ROOT/"tests/test_prospective_provider_activation.py"),"--synthetic-cold",
                str(root),config_pin,head],capture_output=True,text=True,encoding="utf-8")
            (output/f"cold-{n}.log").write_text(run.stdout+run.stderr,encoding="utf-8")
            if run.returncode: raise ValueError("ACTIVATION_COLD_PROCESS_FAILED")
        after={str(p.relative_to(root)):sha256(p.read_bytes()) for p in root.rglob("*") if p.is_file() and p.name!=".scan.lock"}
        if before!=after: raise ValueError("ACTIVATION_EXISTING_EVIDENCE_CHANGED")
        readiness=pipeline.issuer_readiness(config,events)
        write(output/"SYNTHETIC_ACTIVATION_PROOF.json",{"evidence_scope":"SYNTHETIC_ONLY_NOT_REAL_MAIN_ACTIVATION",
            "config_sha256":config_pin,"authority_sha256":pin,"ledger_head":head,"events":len(events),
            "universe_count":len(readiness),"synthetic_complete_issuer":readiness[0]["fundamental_input_status"],
            "providers":list(a.CONTRACT["providers"]),"activation_timestamp":auth["activation_timestamp"],
            "cold_read_processes":2,"existing_hashes_unchanged":before==after,"raw_receipt_event_hashes":before,
            "real_financial_requests":0,"actual_activation":False,"first_refresh_execution":0,
            "production_mutations":0,"historical_pit":"UNPROVEN","original_eight_quarter_coverage_credit":0})


def main():
    if len(sys.argv)>1 and sys.argv[1] in {"--test-child","--proof-child"}:
        def deny(event,args):
            if event in {"socket.connect","socket.getaddrinfo","socket.sendto"}:
                raise RuntimeError("ACTIVATION_SYNTHETIC_NETWORK_FORBIDDEN")
        sys.addaudithook(deny)
        if sys.argv[1]=="--test-child": return child(Path(sys.argv[2]),sys.argv[3:])
        proof(Path(sys.argv[2])); return 0
    p=argparse.ArgumentParser()
    p.add_argument("--expected-base",required=True); p.add_argument("--expected-head",required=True)
    p.add_argument("--output-dir",required=True,type=Path)
    args=p.parse_args()
    if args.output_dir.exists(): raise ValueError("OUTPUT_MUST_BE_NEW")
    if args.expected_base!=BASE or git("rev-parse","HEAD")!=args.expected_head or git("merge-base",BASE,"HEAD")!=BASE:
        raise ValueError("EXACT_BASE_HEAD_MISMATCH")
    if set(git("diff","--name-status","--no-renames",BASE,args.expected_head).splitlines())!={"A\t"+f for f in ALLOWED} or git("status","--porcelain"):
        raise ValueError("ADDITIVE_SCOPE_OR_WORKTREE_CHANGED")
    def tree(ref):
        return {line.split("\t",1)[1]:line.split("\t",1)[0].split()[2] for line in git("ls-tree","-r",ref).splitlines()}
    old,new=tree(BASE),tree(args.expected_head)
    if any(new.get(path)!=blob for path,blob in old.items()): raise ValueError("PROTECTED_BLOB_CHANGED")
    args.output_dir.mkdir(parents=True)
    write(args.output_dir/"protected-existing-blobs.json",old)
    temp=args.output_dir.resolve()/"temporary"; temp.mkdir()
    results={}
    with tempfile.TemporaryDirectory(prefix="a2-",dir=ROOT.parent) as directory:
        mirror=Path(directory)/"head"; extract(args.expected_head,mirror)
        (mirror/".git").write_text("gitdir: "+git("rev-parse","--absolute-git-dir")+"\n",encoding="utf-8")
        command=[sys.executable,"-B",str(mirror/"scripts/verify_prospective_provider_activation.py")]
        env={**os.environ,"PYTHONDONTWRITEBYTECODE":"1","PYTHONIOENCODING":"utf-8","TEMP":str(temp),"TMP":str(temp)}
        for name,(modules,count) in GROUPS.items():
            output=args.output_dir.resolve()/(name+".json")
            run=subprocess.run([*command,"--test-child",str(output),*modules],cwd=mirror,capture_output=True,text=True,encoding="utf-8",env=env)
            (args.output_dir/(name+".log")).write_text(run.stdout+run.stderr,encoding="utf-8")
            result=json.loads(output.read_text(encoding="utf-8")); result.update(exit_code=run.returncode,exact_count_pass=result["tests_run"]==count)
            results[name]=result
            print(json.dumps({"group":name,"tests":result["tests_run"],"pass":result["all_pass"]}),flush=True)
        run=subprocess.run([*command,"--proof-child",str(args.output_dir.resolve())],cwd=mirror,capture_output=True,text=True,encoding="utf-8",env=env)
        (args.output_dir/"synthetic-proof.log").write_text(run.stdout+run.stderr,encoding="utf-8")
        if run.returncode: raise ValueError("SYNTHETIC_PROOF_FAILED")
    passed=all(r["all_pass"] and r["exact_count_pass"] and r["exit_code"]==0 for r in results.values())
    if git("rev-parse","HEAD")!=args.expected_head or git("status","--porcelain"): raise ValueError("HEAD_OR_WORKTREE_CHANGED")
    write(args.output_dir/"VERIFICATION_PACKAGE.json",{"base_sha":BASE,"head_sha":args.expected_head,"changed_files":sorted(ALLOWED),
        "results":results,"existing_tests":sum(c for _,c in PRIOR_GROUPS.values()),"new_tests":NEW_COUNT,
        "protected_existing_blobs_unchanged":len(old),"real_financial_requests":0,"actual_activation":False,
        "first_refresh_execution":0,"production_mutations":0,"production_eligible":False,
        "validation_status":"PASS" if passed else "FAIL"})
    return 0 if passed else 1


if __name__=="__main__": raise SystemExit(main())
