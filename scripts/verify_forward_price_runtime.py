"""Exact-head narrow runtime scope, protected formal bytes and synthetic regression."""
import argparse
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.eps_duration_facts.model import require
from src.provider_financial_features import within_git_checkout, instant
from scripts.verify_eps_b1_noninterference import git, tracked_hashes, put
from scripts.verify_provider_financial_features import PROVIDER_REGRESSIONS, run_tests

ADDITIONS = {"src/provider_forward_daily_prices.py", "src/provider_forward_price_runtime.py", "scripts/run_forward_price_runtime.py",
    "scripts/verify_forward_price_runtime.py", "tests/test_forward_price_runtime.py", "docs/RATE_FORWARD_PRICE_EVIDENCE_RUNTIME_V1.md",
    "docs/contracts/RATE_FORWARD_PRICE_EVIDENCE_RUNTIME_V1.json", ".github/workflows/rate_forward_price_runtime.yml"}
MODIFIED = {"src/provider_shadow_forward_prices.py", "src/provider_shadow_forward.py", ".github/workflows/rate_provider_shadow_forward_ci.yml"}
OPT_IN = ('    if manifest.get("input_mode") == "OFFICIAL_MARKET_DAILY_FORWARD_INPUT_V1":\n'
    '        from .provider_forward_daily_prices import load_daily_prices\n'
    '        return load_daily_prices(pin, manifest, as_of=as_of, available_at=available_at)\n')


def isolation(base, head):
    require(git("rev-parse", "HEAD").decode().strip() == head and not git("status", "--porcelain", "--untracked-files=all"), "RUNTIME_EXACT_HEAD_CLEAN_REQUIRED")
    git("merge-base", "--is-ancestor", base, head)
    expected = {"A\t" + p for p in ADDITIONS} | {"M\t" + p for p in MODIFIED}
    require(set(git("diff", "--name-status", "--no-renames", base, head).decode().splitlines()) == expected, "RUNTIME_NARROW_SCOPE_DIFF_VIOLATION")
    reader = (ROOT / "src/provider_shadow_forward_prices.py").read_text(encoding="utf-8-sig")
    original = git("show", base + ":src/provider_shadow_forward_prices.py").decode("utf-8-sig").replace("\r\n", "\n")
    require(reader.count(OPT_IN) == 1 and reader.replace(OPT_IN, "", 1) == original, "RUNTIME_MONTHLY_READER_CHANGED")
    label = ('        if book.get("input_mode") == "OFFICIAL_MARKET_DAILY_FORWARD_INPUT_V1":\n'
        '            row["price_source"] = market + "_OFFICIAL_MARKET_DAILY"\n')
    forward = (ROOT / "src/provider_shadow_forward.py").read_text(encoding="utf-8-sig")
    old_forward = git("show", base + ":src/provider_shadow_forward.py").decode("utf-8-sig").replace("\r\n", "\n")
    require(forward.count(label) == 1 and forward.replace(label, "", 1) == old_forward, "RUNTIME_FORWARD_RULE_CHANGED")
    paths = [p for p in git("ls-tree", "-r", "--name-only", base).decode().splitlines() if p not in MODIFIED]
    for path in paths:
        require(git("rev-parse", base + ":" + path) == git("rev-parse", head + ":" + path), "RUNTIME_PROTECTED_BLOB_CHANGED:" + path)
        if path.endswith(".py") and path.startswith(("src/", "scripts/")):
            require(b"provider_forward_daily" not in (ROOT / path).read_bytes() and b"provider_forward_price_runtime" not in (ROOT / path).read_bytes(), "RUNTIME_FORMAL_REVERSE_IMPORT")
    return {"base_sha": base, "head_sha": head, "protected_file_count": len(paths), "protected_hashes": tracked_hashes(paths),
        "monthly_reader_unchanged_except_opt_in": True, "changed_files": sorted(ADDITIONS | MODIFIED)}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--expected-base", required=True)
    p.add_argument("--expected-head", required=True)
    p.add_argument("--output-dir", required=True)
    args = p.parse_args()
    out = Path(args.output_dir).resolve()
    require(not out.exists() and not within_git_checkout(out), "RUNTIME_NEW_EXTERNAL_TEST_ROOT_REQUIRED")
    out.mkdir(parents=True)
    before = isolation(args.expected_base, args.expected_head)
    put(out, "protected-before.json", before)
    tests = [run_tests(out,"prior-provider-93",PROVIDER_REGRESSIONS),
        run_tests(out,"prior-official-17",("tests.test_cer073_fundamental_history_v2",)),
        run_tests(out,"prior-features-42",("tests.test_provider_financial_features",)),
        run_tests(out,"prior-shadow-36",("tests.test_provider_fundamental_shadow",)),
        run_tests(out,"prior-revenue-23",("tests.test_provider_revenue_snapshot",)),
        run_tests(out,"prior-forward-52",("tests.test_provider_shadow_forward",)),
        run_tests(out,"new-daily-runtime",("tests.test_forward_price_runtime",))]
    after = isolation(args.expected_base,args.expected_head)
    require(before == after and sum(t["count"] for t in tests[:-1]) == 263, "RUNTIME_REGRESSIONS_OR_PROTECTED_BYTES_CHANGED")
    put(out,"protected-after.json",after)
    result = {"status":"PASS", "base_sha":args.expected_base,"head_sha":args.expected_head,"platform":sys.platform,
        "existing_tests":263,"new_tests":tests[-1]["count"],"total_tests":sum(t["count"] for t in tests),"tests":tests,
        "protected_file_count":before["protected_file_count"],"protected_bytes_and_blobs_unchanged":True,
        "changed_files":before["changed_files"],"monthly_reader_backward_compatibility":"PASS",
        "scope":"SYNTHETIC_ONLY_NOT_LIVE_PRICE_PROOF","real_price_requests":0,"new_shadow_snapshots":0,
        "production_eligible":False,"decision_eligible":False,"validated_at":instant()}
    put(out,"VERIFICATION_PACKAGE.json",result)
    print(json.dumps(result,sort_keys=True))


if __name__=="__main__": main()
