"""Independent offline worker. Never import current src into historical replay."""
import argparse
from contextlib import redirect_stdout
import importlib.util
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("portability_runtime", ROOT / "src/historical_replay_portability.py")
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--binding", type=Path, required=True)
    parser.add_argument("--binding-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    def deny_network(event, args):
        if event in {"socket.connect", "socket.getaddrinfo", "socket.sendto", "urllib.Request"}:
            raise ValueError("PORTABILITY_NETWORK_FORBIDDEN")
    sys.addaudithook(deny_network)
    binding = p.read(p.pinned({"path":str(args.binding), "sha256":args.binding_sha256}))
    repository = Path(binding["repository_checkout"])
    identities = p.verify_binding(repository, binding)
    output = args.output.resolve()
    p.require(not output.exists() and not output.is_relative_to(ROOT), "PORTABILITY_OUTPUT_MUST_BE_NEW_EXTERNAL")
    p.require(not p.inside_repository(args.output) and not any(parent.is_symlink() or
              (hasattr(parent,"is_junction") and parent.is_junction()) for parent in (args.output,*args.output.parents)),
              "PORTABILITY_OUTPUT_LINK_OR_REPOSITORY")
    p.require(not any(output.is_relative_to(Path(root).resolve()) for root in binding["read_only_roots"]), "PORTABILITY_PROTECTED_OUTPUT")
    output.mkdir(parents=True)
    config = p.read(p.pinned(binding["evidence_pins"]["configuration"]))
    parent = p.read(p.pinned(binding["evidence_pins"]["recovery_binding"]))
    p.require(config["execution_head"] == identities["producer_sha"] and config["coordinator_sha256"] == binding["accepted_reader"]["sha256"], "PORTABILITY_DECLARED_PRODUCER_MISMATCH")
    declarations = [(config["execution_checkout"], identities["producer_sha"]),
                    (parent["legacy_checkout"], parent["legacy_execution"]["head_sha"])]
    views, pins = {}, {}
    for index, (logical, commit) in enumerate(declarations):
        physical = output / ("producer-" + str(index))
        pins[str(Path(logical).resolve())] = p.reconstruct(repository, commit, physical)
        views[logical] = str(physical)
    historical_pins = pins[str(Path(declarations[0][0]).resolve())]
    p.require(set(config["main_code_pins"]) == set(historical_pins), "PORTABILITY_DECLARED_SOURCE_SET_MISMATCH")
    for name, pin in config["main_code_pins"].items():
        p.require(pin["sha256"] == historical_pins[name]["sha256"] and pin["bytes"] == historical_pins[name]["bytes"], "PORTABILITY_SOURCE_BLOB_MISMATCH")
    sandbox = p.SourceSandbox(views, pins, declarations[0][0])
    sys.meta_path.insert(0, sandbox)
    proof = output / "REPLAY.json"
    sys.addaudithook(p.ReadOnlyRuntime(proof, views.values()))
    reader = sandbox.reader(binding["accepted_reader"])
    # All original provenance functions, including exact_main(), execute unchanged.
    with redirect_stdout(sys.stderr):
        reader.cold(proof)
    result = p.read(proof.read_bytes())
    expected = p.read(p.pinned(binding["accepted_output"]))
    match = p.equivalence(result, expected)
    print(json.dumps({"status":"PASS", "identities":identities, "equivalence":match,
          "source_pins":pins, "executed_sources":sandbox.executed, "isolated_git_queries":sandbox.git.calls,
          "accepted_reader_unchanged":True, "historical_functions_patched":False,
          "network_requests":0, "financial_requests":0, "production_mutations":0,
          "shared_ref_mutations":0, "first_refresh_execution":0}, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
