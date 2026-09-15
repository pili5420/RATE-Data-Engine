from __future__ import annotations
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.production_layer import load_source_registry, production_gate_status, SLOTS

ROOT = Path(__file__).resolve().parents[1]
registry = load_source_registry(ROOT / "config" / "SOURCE_REGISTRY.json")
result = {"artifact":"RATE_PRODUCTION_DATA_LAYER_RUN_V1", "registry":"config/SOURCE_REGISTRY.json",
          "connected_data_sources":[], "slots":{slot:production_gate_status(registry, slot=slot) for slot in SLOTS}}
(ROOT / "artifacts" / "RATE_PRODUCTION_DATA_LAYER_RUN_V1.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
print(json.dumps(result, indent=2))
