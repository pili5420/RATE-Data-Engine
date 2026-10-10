"""Offline opt-in semantic verification. Never changes source packages or active owners."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import traceback

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.eps_duration_facts.model import require
from src.provider_calendar_eps_contract import replay_closeout
from src.provider_financial_features import within_git_checkout
from scripts.verify_provider_calendar_eps import deny_network


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--closeout-manifest", required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    def git(*params):
        return subprocess.check_output(["git", *params], cwd=ROOT, text=True).strip()
    require(git("rev-parse", "HEAD") == args.expected_head and not git("status", "--porcelain"), "EXACT_CLEAN_HEAD_REQUIRED")
    require(not args.output_dir.exists() and not within_git_checkout(args.output_dir.resolve()), "NEW_EXTERNAL_OUTPUT_REQUIRED")
    args.output_dir.mkdir(parents=True)
    sys.addaudithook(deny_network)
    try:
        result = replay_closeout(args.closeout_manifest, args.expected_sha256, datetime.now(timezone.utc).isoformat())
        result["validation_execution_head"] = args.expected_head
        result["validation_completed_at"] = datetime.now(timezone.utc).isoformat()
        for name, value in (("CALENDAR_CONTRACT_VERIFICATION.json", result),
                            ("SUMMARY.json", result["core"]["summary"]),
                            ("source-inventory.json", result["source_inventory"])):
            (args.output_dir / name).write_text(json.dumps(value, ensure_ascii=True, sort_keys=True, indent=2), encoding="utf-8")
        print(json.dumps({"status": "PASS", "content_sha256": result["content_sha256"], "summary": result["core"]["summary"]}, sort_keys=True))
        return 0
    except Exception:
        (args.output_dir / "INCOMPLETE_TRACEBACK.txt").write_text(traceback.format_exc(), encoding="utf-8")
        raise


if __name__ == "__main__":
    raise SystemExit(main())
