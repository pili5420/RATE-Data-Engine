from __future__ import annotations
import argparse, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.source_bundle import SourceBundleError, ingest

parser = argparse.ArgumentParser(description="Ingest an authorized RATE Production Source Bundle")
parser.add_argument("bundle", help="Directory containing manifest.json and source JSON files")
parser.add_argument("--output", help="Write ingestion result JSON")
args = parser.parse_args()
try:
    result = ingest(args.bundle)
except (OSError, ValueError, json.JSONDecodeError) as exc:
    result = {"validation_status":"BLOCKED", "errors":[str(exc)]}
    print(json.dumps(result, indent=2), file=sys.stderr)
    raise SystemExit(2)
if args.output:
    Path(args.output).write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(json.dumps({k:v for k,v in result.items() if k != "records"}, indent=2, ensure_ascii=False))
raise SystemExit(0 if result["validation_status"] == "PASS" else 1)
