"""Offline sidecar entrypoint. Append requires a separately pinned activation permit."""
import argparse
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT))
from src.prospective_acquisition_recovery import offline_network_guard

network_attempts = 0


def network_guard(event, args):
    global network_attempts
    if event in {"socket.connect", "socket.getaddrinfo", "socket.sendto", "urllib.Request"}:
        network_attempts += 1
    offline_network_guard(event, args)


sys.addaudithook(network_guard)
from src import history_acceptance_sidecar as sidecar


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--operation", required=True, choices=("verify-chunks", "replay", "append"))
    p.add_argument("--binding", type=Path, required=True)
    p.add_argument("--trusted-binding-sha256", required=True)
    p.add_argument("--trust-file", type=Path)
    p.add_argument("--trusted-trust-file-sha256")
    p.add_argument("--ordinals", type=int, nargs="+", default=[1, 2])
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    output = sidecar.h.evidence.safe(a.output)
    sidecar.require(not output.exists(), "ACCEPTANCE_OUTPUT_MUST_BE_NEW")
    binding = sidecar.trusted_file(a.binding, a.trusted_binding_sha256)
    materials = {name: sidecar.trusted_file(binding[name]["path"], binding[name]["sha256"])
                 for name in ("manifest", "scope", "approval", "universe")}
    ctx = sidecar.context(materials["manifest"], materials["scope"], materials["approval"],
        {"verification_status": "PASS", "stocks": materials["universe"]["stocks"]},
        trusted_approval_sha256=binding["trusted_approval_sha256"],
        trusted_manifest_sha256=binding["trusted_manifest_sha256"],
        campaign_root=binding["campaign_root"], ledger_root=binding["ledger_root"])
    ledger_root = Path(ctx["ledger_root"])
    sidecar.require(not output.is_relative_to(Path(ctx["campaign_root"])) and not output.is_relative_to(ledger_root)
                    and not output.is_relative_to(ROOT), "ACCEPTANCE_OUTPUT_ISOLATION_REQUIRED")

    def write_guard(event, args):
        paths = []
        if event == "open" and not isinstance(args[0], int):
            mode, flags = args[1:3]
            if ((isinstance(mode, str) and any(c in mode for c in "wax+")) or
                    (isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))):
                paths.append(args[0])
        elif event in {"os.mkdir", "os.remove", "os.rmdir", "os.chmod", "os.utime"}:
            paths.append(args[0])
        elif event in {"os.rename", "os.link", "os.symlink"}:
            paths.extend(args[:2])
        for path in paths:
            resolved = Path(path).resolve()
            sidecar.require(resolved == output or (a.operation == "append" and
                            (resolved == ledger_root or resolved.is_relative_to(ledger_root))), "ACCEPTANCE_WRITE_BOUNDARY")

    sys.addaudithook(write_guard)
    if a.operation == "verify-chunks":
        result = {"status": "PASS", "chunks": [sidecar.verify_chunk(ctx, n) for n in a.ordinals],
                  "acceptance_decision": "NOT_RECORDED", "acceptance_ledger_created": False}
    else:
        sidecar.require(a.trust_file is not None, "ACCEPTANCE_EXTERNAL_TRUST_MATERIALS_REQUIRED")
        trust = sidecar.trusted_file(a.trust_file, a.trusted_trust_file_sha256)
        common = {k: trust[k] for k in ("genesis_path", "trusted_genesis_sha256", "trusted_records", "expected_head")}
        if a.operation == "replay":
            result = sidecar.replay(ctx, **common)
        else:
            result = sidecar.append_acceptance(ctx, **common, **{k: trust[k] for k in (
                "record_path", "trusted_record_sha256", "activation_path", "trusted_activation_sha256")})
    sidecar.require(network_attempts == 0, "ACCEPTANCE_NETWORK_ATTEMPTED")
    # No mkdir: the operator must supply an already-existing isolated output parent.
    with output.open("xb") as stream:
        stream.write(sidecar.h.evidence.canonical({"operation": a.operation, "network_attempts": network_attempts,
            "sidecar_owner_sha256_lf": sidecar.owners(), "result": result}))
        stream.flush(); os.fsync(stream.fileno())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
