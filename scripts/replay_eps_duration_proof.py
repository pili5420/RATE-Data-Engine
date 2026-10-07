"""Offline evidence audit and fact replay. Output is diagnostic, never persisted state."""
import argparse
from dataclasses import asdict, replace
import json
from pathlib import Path
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.eps_duration_facts.parser import parse_book_calendar, parse_inline
from src.eps_duration_facts.raw import audit_archive, sha256

ARCHIVE_SHA = "8a2a7b0e11b6f661ad96bdd86b22a71f592beb2642fd3c574896816f1fae135a"


def replay(path):
    if sha256(Path(path).read_bytes()) != ARCHIVE_SHA:
        raise ValueError("ARCHIVE_HASH_MISMATCH")
    with zipfile.ZipFile(path) as archive:
        inventory = json.loads(archive.read("inventory.json"))
        for entry in inventory:
            data = archive.read(entry["path"])
            if len(data) != entry["bytes"] or sha256(data) != entry["sha256"]:
                raise ValueError("ARCHIVE_ENTRY_HASH_MISMATCH")
        audit = {p: audit_archive(archive, p) for p in ("prior", "new")}
        rows = []
        for symbol, market in (("2330", "TWSE"), ("6488", "TPEX")):
            calendar_receipts = [n for n in audit["prior"]["receipt_sha256"]
                                 if n.startswith("prior/receipts/book-index-" + symbol)]
            # An explicit observed official book calendar label, not a default calendar.
            calendars = []
            for name in calendar_receipts:
                receipt = json.loads(archive.read(name))
                digest = receipt["body_sha256"]
                raw = archive.read("prior/raw/" + digest + ".bin")
                calendars.append(parse_book_calendar(receipt, raw, symbol))
            for name in sorted(audit["prior"]["receipt_sha256"]):
                if not name.startswith("prior/receipts/" + symbol) or not name.endswith("-download.json"):
                    continue
                receipt = json.loads(archive.read(name))
                data = archive.read("prior/raw/" + receipt["body_sha256"] + ".bin")
                facts = parse_inline(receipt, data, symbol, market, calendars[0] if calendars else None)
                facts = [replace(f, first_verified_observed_at=audit["prior"]["first_verified_observed_at"][f.raw_sha256])
                         for f in facts]
                rows.append({"receipt": name, "calendar_evidence": [asdict(c) for c in calendars],
                             "facts": [asdict(f) for f in facts]})
        return {"archive_sha256": ARCHIVE_SHA, "audit": audit, "filings": rows,
                "historical_cutoff": "2026-10-05", "source_proof_status": "BLOCKED",
                "production_eligible": False, "original_eight_quarter_coverage_credit": 0,
                "production_mutations": {"live_state": 0, "STATE_LATEST": 0, "Portfolio": 0, "Ledger": 0}}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", default="tests/fixtures/eps_duration/official-proof.zip")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = Path(args.output).resolve()
    if output.exists() or any(p.lower() in ("artifacts", "data", "control", "control_center") for p in output.parts):
        raise ValueError("OUTPUT_MUST_BE_NEW_DIAGNOSTIC_FILE")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(replay(args.archive), ensure_ascii=False, indent=2), encoding="utf-8")
