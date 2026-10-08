"""SYNTHETIC ENGINEERING ONLY. No HTTP implementation or credentials."""
import json
from tests.test_provider_eps_coverage import fake_capture


def capture(root, ident, api, symbol, **kwargs):
    config = json.loads((root.parents[1] / "mock-config.json").read_bytes())
    with (root.parents[1] / "mock-calls.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"symbol": symbol, "material_class": "ENGINEERING_SYNTHETIC"}) + "\n")
    mode = config["mode"]
    if mode == "unknown":
        raise RuntimeError("SYNTHETIC_UNKNOWN_OUTCOME")
    mutation = (lambda rows: [r.update(origin_name="UNKNOWN") for r in rows]) if mode == "invalid" else None
    return fake_capture(rows_mutator=mutation, blocked=mode == "blocked")(root, ident, api, symbol, **kwargs)
