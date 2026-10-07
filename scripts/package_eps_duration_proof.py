"""Mechanical import of immutable local proof; no network or Production writes."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile


def package(old, new, output):
    output = Path(output)
    if output.exists():
        raise ValueError("PROOF_ARCHIVE_ALREADY_EXISTS")
    output.parent.mkdir(parents=True, exist_ok=True)
    inventory = []
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for prefix, root in (("prior", Path(old)), ("new", Path(new))):
            for relative in ("receipts", "raw"):
                for path in sorted((root / relative).glob("*")):
                    if not path.is_file():
                        continue
                    data = path.read_bytes()
                    target = prefix + "/" + relative + "/" + path.name
                    archive.writestr(target, data)
                    inventory.append({"path": target, "sha256": hashlib.sha256(data).hexdigest(),
                                      "bytes": len(data), "original_path": str(path)})
            for name in ("Reported_PIT_Source_Proof.ipynb", "filing-matrix.json",
                         "book-and-correction-evidence.json", "pdf-evidence.json"):
                path = root / name
                if path.exists():
                    data = path.read_bytes()
                    target = prefix + "/" + name
                    archive.writestr(target, data)
                    inventory.append({"path": target, "sha256": hashlib.sha256(data).hexdigest(),
                                      "bytes": len(data), "original_path": str(path)})
        archive.writestr("inventory.json", json.dumps(inventory, indent=2))
    return {"archive": str(output), "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
            "entries": len(inventory)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--prior", required=True)
    parser.add_argument("--new", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    print(json.dumps(package(args.prior, args.new, args.output), indent=2))
