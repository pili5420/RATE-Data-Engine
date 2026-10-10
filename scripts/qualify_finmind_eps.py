"""Offline local replay; trusted source pin is supplied separately from the manifest."""
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
from src.finmind_formal_qualification import replay_closeout
from src.provider_financial_features import within_git_checkout


def deny_network(event, args):
    if event in {"socket.connect", "socket.getaddrinfo", "socket.sendto"}:
        raise RuntimeError("PHASE_C_NETWORK_FORBIDDEN:" + event)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--closeout-manifest", required=True)
    p.add_argument("--expected-sha256", required=True)
    p.add_argument("--expected-head", required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    a = p.parse_args()
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()
    require(git("rev-parse", "HEAD") == a.expected_head and not git("status", "--porcelain"), "EXACT_CLEAN_HEAD_REQUIRED")
    require(not a.output_dir.exists() and not within_git_checkout(a.output_dir.resolve()), "NEW_EXTERNAL_OUTPUT_REQUIRED")
    a.output_dir.mkdir(parents=True)
    sys.addaudithook(deny_network)
    try:
        result = replay_closeout(a.closeout_manifest, a.expected_sha256, datetime.now(timezone.utc).isoformat())
        result["execution_head"] = a.expected_head
        result["execution_base"] = "6ea91f2328827d2233537292a55fe6acf15b8470"
        for name, value in (("QUALIFICATION_PACKAGE.json", result),
                            ("coverage-matrix.json", result["core"]["companies"]),
                            ("source-invariance.json", result["source_inventory"])):
            (a.output_dir / name).write_text(json.dumps(value, ensure_ascii=True, sort_keys=True, indent=2), encoding="utf-8")
        summary = {k: v for k, v in result["core"].items() if k not in {"companies", "universe"}}
        summary.update(content_sha256=result["content_sha256"], validated_at=result["validated_at"], execution_head=a.expected_head)
        (a.output_dir / "SUMMARY.json").write_text(json.dumps(summary, sort_keys=True, indent=2), encoding="utf-8")
        print(json.dumps(summary, sort_keys=True))
        return 0
    except Exception:
        (a.output_dir / "INCOMPLETE_TRACEBACK.txt").write_text(traceback.format_exc(), encoding="utf-8")
        raise


if __name__ == "__main__":
    raise SystemExit(main())
