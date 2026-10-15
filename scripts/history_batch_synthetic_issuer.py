"""SYNTHETIC ONLY: temporary memory keys, independent original-evidence replay."""
import base64
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT))
from src.prospective_acquisition_recovery import offline_network_guard
sys.addaudithook(offline_network_guard)
from src import history_batch_authority as a


def receive():
    line = sys.stdin.readline()
    a.require(bool(line), "BATCH_ISSUER_INPUT_CLOSED")
    return a.read_metadata(line.encode())


def reply(value):
    sys.stdout.write(a.e.canonical({"status": "PASS", **value}).decode() + "\n"); sys.stdout.flush()


def main():
    boot = receive()
    a.require(boot["operation"] == "BOOT" and boot["material_scope"] == a.SCOPE, "BATCH_REAL_KEY_CREATION_FORBIDDEN")
    base = a.sandbox(boot["sandbox"])
    # These test keys are generated only inside this contained process, never serialized.
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    issuer_key, witness_key = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
    reply({"pid": os.getpid(), "parent_pid": os.getppid(), "issuer_public_key": base64.b64encode(issuer_key.public_key().public_bytes_raw()).decode(),
        "witness_public_key": base64.b64encode(witness_key.public_key().public_bytes_raw()).decode(),
        "private_key_serialized": False, "material_scope": a.SCOPE})
    init = receive()
    a.require(init["operation"] == "INITIALIZE" and a.e.safe(init["policy"]["roots"]["sandbox"]) == base,
              "BATCH_ISSUER_INITIALIZATION_REQUIRED")
    writer_roots = [a.child_root(init["policy"]["roots"][name], base) for name in ("issuer", "witness")]
    def guard(event, args):
        paths = []
        if event == "open" and not isinstance(args[0], int):
            mode, flags = args[1:3]
            if ((isinstance(mode, str) and any(x in mode for x in "wax+")) or
                (isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))):
                paths.append(args[0])
        elif event in {"os.mkdir", "os.remove", "os.rmdir", "os.chmod", "os.utime"}:
            paths.append(args[0])
        elif event in {"os.rename", "os.symlink", "os.link"}:
            paths.extend(args[:2])
        for path in paths:
            resolved = Path(path).resolve()
            a.require(any(resolved == root or resolved.is_relative_to(root) for root in writer_roots), "BATCH_ISSUER_WRITE_BOUNDARY")
    sys.addaudithook(guard)
    issuer = a.Issuer(init["policy"], init["ctx"], init["registry"], init["registry_pin"], init["policy_envelope"],
        issuer_key.sign, witness_key.sign, at=init["at"])
    reply({"initialized": True, "pid": os.getpid()})
    while True:
        request = receive()
        operation, at = request["operation"], request["at"]
        if operation == "AUTHORIZE":
            result = issuer.authorize(request["ordinal"], request["predecessor_head"], at=at)
        elif operation == "ACCEPT":
            result = issuer.accept(request["ordinal"], at=at)
        elif operation == "ACK":
            result = issuer.acknowledge(request["head"], genesis_path=request["genesis_path"],
                activation_path=request["activation_path"], record_paths=request["record_paths"], at=at)
        elif operation == "REVOKE":
            result = issuer.revoke(at=at)
        else:
            raise ValueError("BATCH_ISSUER_RPC_NOT_ALLOWED")
        reply({"result": result})


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        sys.stdout.write(a.e.canonical({"status": "HALTED", "error": type(exc).__name__ + ": " + str(exc)}).decode() + "\n")
        sys.stdout.flush()
        raise SystemExit(1)
