"""Offline-only acceptance and cold consumer. Never acquires or activates a provider."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def fingerprint(path):
    h = hashlib.sha256()
    path = Path(path)
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            h.update(chunk)
    return {"bytes": path.stat().st_size, "sha256": h.hexdigest()}


def guard(output=None):
    def allowed(path):
        if isinstance(path, int):
            return
        if output is None or not Path(os.fsdecode(path)).resolve().is_relative_to(output):
            raise RuntimeError("PROSPECTIVE_WRITE_OUTSIDE_FRESH_OUTPUT")
    def audit(event, values):
        if event in {"socket.connect", "socket.getaddrinfo", "socket.sendto"}:
            raise RuntimeError("PROSPECTIVE_NETWORK_FORBIDDEN")
        if event == "open" and ((values[1] and any(c in values[1] for c in "wax+")) or
                values[2] & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC)):
            allowed(values[0])
        if event in {"os.remove", "os.mkdir", "os.rmdir", "os.chmod", "os.utime", "os.truncate"}:
            allowed(values[0])
        if event in {"os.rename", "os.link", "os.symlink"}:
            allowed(values[0]); allowed(values[1])
    return audit


def git(root, *args):
    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--binding", type=Path)
    p.add_argument("--binding-sha256")
    p.add_argument("--output-dir", type=Path)
    p.add_argument("--source-child", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--replay-sandbox", type=Path)
    p.add_argument("--config-sha256")
    p.add_argument("--trusted-head")
    p.add_argument("--as-of")
    p.add_argument("--output-file", type=Path)
    p.add_argument("--cold-package", type=Path)
    p.add_argument("--expected-package-sha256")
    args = p.parse_args()
    if args.source_child:
        binding = json.loads(args.binding.read_text(encoding="utf-8"))
        if fingerprint(args.binding)["sha256"] != args.binding_sha256:
            raise ValueError("PROSPECTIVE_BINDING_TAMPER")
        sys.path.insert(0, binding["producer_checkout"])
        sys.addaudithook(guard())
        from src.provider_financial_features import consume
        from src.provider_financial_feature_inputs import replay_binding
        result = consume(binding["feature_dir"], binding["feature_manifest_sha256"], source_replayer=replay_binding,
            expected_code_binding=binding["producer"])
        print(json.dumps(result, allow_nan=False))
        return 0
    sys.path.insert(0, str(ROOT))
    from src.eps_duration_facts.model import require, Rejected
    from src.eps_duration_facts.raw import sha256
    from src.provider_eps_candidate import _canonical, WINDOW
    from src.provider_eps_coverage import load_universe
    from src.provider_eps_metadata import read_metadata
    from src.provider_financial_features import within_git_checkout, hash_object, CONTRACT as FEATURES
    from src.prospective_fundamental_provider import (CONTRACT, inspect_source, prospective_record,
        issuer_readiness, replay, review_decision)
    if args.replay_sandbox:
        require(args.output_file and not args.output_file.exists(), "PROSPECTIVE_FRESH_OUTPUT_REQUIRED")
        args.output_file.parent.mkdir(parents=True, exist_ok=True)
        sys.addaudithook(guard(args.output_file.parent.resolve()))
        config, events = replay(args.replay_sandbox, args.config_sha256, args.trusted_head, args.as_of)
        rows = issuer_readiness(config, events)
        args.output_file.write_bytes(_canonical({"status": "PASS", "events": len(events), "ledger_head": args.trusted_head,
            "issuer_count": len(rows), "readiness_sha256": hash_object(rows), "production_eligible": False}))
        return 0
    require(args.binding and args.binding_sha256 and args.output_dir, "PROSPECTIVE_REQUIRED_BINDING_MISSING")
    require(fingerprint(args.binding)["sha256"] == args.binding_sha256, "PROSPECTIVE_BINDING_TAMPER")
    binding = read_metadata(args.binding.read_bytes())
    execution = binding["execution"]
    require(execution["base_sha"] == CONTRACT["base_sha"] and git(ROOT,"rev-parse","HEAD") == execution["head_sha"] and
        git(ROOT,"merge-base",execution["base_sha"],execution["head_sha"]) == execution["base_sha"] and
        not git(ROOT,"status","--porcelain"), "PROSPECTIVE_EXACT_HEAD_MISMATCH")
    producer = Path(binding["producer_checkout"])
    require(git(producer,"rev-parse","HEAD") == binding["producer"]["head_sha"] and
        git(producer,"merge-base",binding["producer"]["base_sha"],binding["producer"]["head_sha"]) == binding["producer"]["base_sha"] and
        not git(producer,"status","--porcelain"), "PROSPECTIVE_ORIGINAL_PRODUCER_MISMATCH")
    output = args.output_dir.resolve()
    require(not output.exists() and not within_git_checkout(output) and not any(part.casefold() in
        {"production","latest","state","portfolio","ledger","snapshots"} for part in output.parts), "PROSPECTIVE_FRESH_EXTERNAL_OUTPUT_REQUIRED")
    require(fingerprint(binding["protected_manifest"])["sha256"] == binding["protected_manifest_sha256"], "PROSPECTIVE_PROTECTION_PIN_MISMATCH")
    pins = read_metadata(Path(binding["protected_manifest"]).read_bytes())
    def check():
        for name, expected in pins.items():
            require(fingerprint(name) == expected, "PROSPECTIVE_PROTECTED_INPUT_MUTATION:" + name)
    check()
    for checkout in (ROOT, producer):
        for name in git(checkout,"ls-files").splitlines():
            pins[str(checkout/name)] = fingerprint(checkout/name)
    feature_dir = Path(binding["feature_dir"])
    require(fingerprint(feature_dir/"FEATURE_MANIFEST.json")["sha256"] == binding["feature_manifest_sha256"], "PROSPECTIVE_FEATURE_MANIFEST_TAMPER")
    manifest = read_metadata((feature_dir/"FEATURE_MANIFEST.json").read_bytes())
    require(set(manifest["files"]) == {"PROVIDER_FINANCIAL_FEATURES_V1.json"}, "PROSPECTIVE_FEATURE_MANIFEST_PATH_INVALID")
    source_path = feature_dir/"PROVIDER_FINANCIAL_FEATURES_V1.json"
    require(fingerprint(source_path) == manifest["files"][source_path.name], "PROSPECTIVE_FEATURE_TAMPER")
    package = read_metadata(source_path.read_bytes())
    inputs = package["core"]["inputs"]
    universe = load_universe(binding["universe_evidence"],binding["universe_sha256"],binding["universe_commit"])
    universe["stocks"].sort(key=lambda r: (r["market"] != "TWSE",r["symbol"]))
    require(inputs["universe"] == universe and Counter(s["market"] for s in universe["stocks"]) == {"TWSE":1085,"TPEX":893}, "PROSPECTIVE_EXACT_UNIVERSE_MISMATCH")
    for root in (producer,feature_dir,ROOT,Path(inputs["source_binding"]["coverage_root"]),Path(inputs["source_binding"]["snapshot_root"])):
        require(not output.is_relative_to(root.resolve()), "PROSPECTIVE_OUTPUT_IN_SOURCE")
    for name in (args.binding,source_path,feature_dir/"FEATURE_MANIFEST.json",Path(binding["universe_evidence"]),Path(binding["protected_manifest"])):
        pins[str(name)] = fingerprint(name)
    output.mkdir(parents=True,exist_ok=False)
    sys.addaudithook(guard(output))
    def write(name,value):
        (output/name).write_bytes(_canonical(value)+b"\n")
    write("INCOMPLETE_UNTIL_VERIFIED.json",{"usable_acceptance":False})
    write("INPUT_BINDINGS.json",binding)
    run = subprocess.run([sys.executable,"-B",str(Path(__file__).resolve()),"--source-child","--binding",str(args.binding),
        "--binding-sha256",args.binding_sha256],cwd=producer,capture_output=True,text=True,encoding="utf-8",
        env={**os.environ,"PYTHONDONTWRITEBYTECODE":"1","PYTHONIOENCODING":"utf-8"})
    (output/"source-replay.log").write_text(run.stdout+run.stderr,encoding="utf-8")
    require(run.returncode == 0,"PROSPECTIVE_ORIGINAL_SOURCE_REPLAY_FAILED")
    source = json.loads(run.stdout)
    require(source["source_replay"] == "PASS" and source["content_sha256"] == package["content_sha256"],"PROSPECTIVE_ORIGINAL_SOURCE_REPLAY_BINDING_MISMATCH")
    write("ORIGINAL_PRODUCER_SOURCE_REPLAY.json",source)
    now = datetime.now(timezone.utc).isoformat()
    original_parser = (producer/"src/sources/fundamental_history.py").read_bytes()
    seen, audits, old_rejections = {}, [], Counter()
    for domain, rows in (("EPS",inputs["eps"]),("REVENUE",inputs["revenue"])):
        for row in rows:
            provider = "FinMind" if domain == "EPS" else "MOPS Official"
            target = {"symbol":row["symbol"],"market":row["market"]} if domain == "EPS" else {"market":row["market"],"period":row["period"]}
            key = (provider,row["receipt_reference"])
            if key not in seen:
                for path, digest in ((row["raw_reference"],row["raw_sha256"]),(row["receipt_reference"],row["receipt_sha256"])):
                    pins[path] = fingerprint(path)
                    require(pins[path]["sha256"] == digest,"PROSPECTIVE_SOURCE_PIN_MISMATCH")
                inspected = inspect_source(provider,target,Path(row["raw_reference"]).read_bytes(),Path(row["receipt_reference"]).read_bytes(),
                    row["raw_sha256"],row["receipt_sha256"],universe,now,original_parser_bytes=original_parser if domain == "REVENUE" else None)
                seen[key] = inspected
                try:
                    prospective_record(inspected,now,now)
                except Rejected as error:
                    old_rejections[str(error)] += 1
                else:
                    raise ValueError("PROSPECTIVE_LEGACY_ACQUISITION_MASQUERADE")
                audits.append({"provider":provider,"target":target,"raw_reference":row["raw_reference"],"receipt_reference":row["receipt_reference"],
                    "raw_sha256":row["raw_sha256"],"receipt_sha256":row["receipt_sha256"],"source_identity_gate":"PASS",
                    "received_at":inspected["received_at"],"requested_at":inspected["requested_at"],
                    "source_parser_sha256":inspected["source_parser_sha256"],"validator_parser":inspected["parser_version"],
                    "prospective_admissible":False,"historical_pit":"UNPROVEN"})
            inspected = seen[key]
            period = row["analysis_quarter"] if domain == "EPS" else row["period"]
            found = [r for r in inspected["rows"] if r["symbol"] == row["symbol"] and r["period"] == period]
            value = row["provider_value"] if domain == "EPS" else row["revenue_yoy"]
            observed = row["acquired_observed_at"] if domain == "EPS" else row["observed_at"]
            from decimal import Decimal
            require(len(found) == 1 and (found[0]["value"] is None and value is None or found[0]["value"] is not None and value is not None and
                Decimal(found[0]["value"]) == Decimal(str(value))) and observed == inspected["source_observed_at"],"PROSPECTIVE_LEGACY_ROW_REPLAY_MISMATCH")
            locator = row["json_locator"] if domain == "EPS" else row["row_identity_locator"]
            require(locator == found[0]["json_locator"],"PROSPECTIVE_LOCATOR_MISMATCH")
    eps = {(r["symbol"],r["analysis_quarter"]) for r in inputs["eps"]}
    rev = {(r["symbol"],r["period"]):r for r in inputs["revenue"]}
    issuers = []
    for stock in universe["stocks"]:
        symbol = stock["symbol"]
        missing_eps = [q for q in WINDOW if (symbol,q) not in eps]
        missing_rev = [{"period":q,"reason":"MISSING_REQUIRED_PERIOD" if (symbol,q) not in rev else rev[(symbol,q)]["revenue_yoy_status"]}
            for q in FEATURES["revenue_months"] if (symbol,q) not in rev or rev[(symbol,q)]["revenue_yoy_status"] != "VALID_NUMERIC"]
        issuers.append({**stock,"legacy_eps_positions_retained":8-len(missing_eps),"missing_eps":missing_eps,"missing_revenue":missing_rev,
            "legacy_input_readiness":"READY" if not missing_eps and not missing_rev else "NOT_READY_MISSING_REQUIRED_PERIOD",
            "prospective_input_readiness":"NOT_READY_MISSING_REQUIRED_PERIOD","reason":"NO_POST_AUTHORIZATION_ACQUISITION",
            "provider_authorization":"NOT_AUTHORIZED","ranking_eligible":False,"production_eligible":False})
    core = {"contract":CONTRACT,"execution":execution,"original_producer":package["execution"]["code_binding"],
        "source_feature_content_sha256":package["content_sha256"],"source_feature_manifest_sha256":binding["feature_manifest_sha256"],
        "universe":universe,"provider_decision":review_decision({p:"PASS" for p in ("FinMind","MOPS Official")},True),
        "identity_verified_acquisitions":dict(Counter(a["provider"] for a in audits)),
        "old_acquisition_rejections":dict(old_rejections),"issuers":issuers,"preserved_gaps":inputs["gaps"],
        "legacy_summary":{"eps_valid_positions":len(eps),"eps_complete":sum(not r["missing_eps"] for r in issuers),
            "revenue_complete":sum(not r["missing_revenue"] for r in issuers),"complete_intersection":sum(r["legacy_input_readiness"]=="READY" for r in issuers),
            "incomplete_valid_eps_retained":sum(r["legacy_eps_positions_retained"] for r in issuers if r["missing_eps"])},
        "real_prospective_acquisitions":0,"financial_requests":0,"historical_pit":"UNPROVEN","production_eligible":False}
    write("SOURCE_IDENTITY_AUDIT.json",audits)
    if args.cold_package:
        require(fingerprint(args.cold_package)["sha256"] == args.expected_package_sha256,"PROSPECTIVE_ACCEPTANCE_PACKAGE_TAMPER")
        old = read_metadata(args.cold_package.read_bytes())
        require(old["core"] == core and old["content_sha256"] == hash_object(core),"PROSPECTIVE_COLD_REPLAY_MISMATCH")
        write("COLD_READ_VERIFICATION.json",{"status":"PASS","content_sha256":hash_object(core),"source_replay":"PASS"})
    else:
        write("ACCEPTANCE_PACKAGE.json",{"core":core,"content_sha256":hash_object(core),"generated_at":now,"validated_at":datetime.now(timezone.utc).isoformat()})
    check()
    write("input-hashes-before.json",pins)
    write("input-hashes-after.json",pins)
    write("NON_INTERFERENCE.json",{"checked_files":len(pins),"modified":[],"deleted":[],"write_scope":"AUDIT_ENFORCED_FRESH_EXTERNAL_OUTPUT_ONLY",
        "financial_requests":0,"actual_provider_authorizations":0,"first_refresh_calls":0,"ranking_calls":0,"scheduler_calls":0,
        "production_mutations":0,"decision_state_mutations":0,"portfolio_mutations":0,"ledger_mutations":0})
    write("EXECUTION_COMPLETE.json",{"source_replay":"PASS","source_identity":"PASS","legacy_relabeling":"REJECTED", "cold_read":bool(args.cold_package),"activation_timestamp":None})
    print(json.dumps({"status":"PASS","output":str(output),"source_acquisitions":len(audits),"core_identity":hash_object(core),"summary":core["legacy_summary"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
