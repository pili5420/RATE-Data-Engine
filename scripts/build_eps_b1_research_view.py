"""Export retained, hash-pinned evidence to a new isolated B1 research directory."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.eps_b1_research import build_view, export_view


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--observation-cutoff", required=True)
    parser.add_argument("--research-root", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    archive = ROOT / "tests/fixtures/eps_duration/official-proof.zip"
    value = build_view(archive, args.observation_cutoff, sha)
    manifest = export_view(value, archive, args.research_root, args.output_dir)
    print(json.dumps({"usage_scope": manifest["usage_scope"], "core_sha256": manifest["core_sha256"],
                      "manifest_sha256": manifest["manifest_sha256"], "summary": value["core"]["summary"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
