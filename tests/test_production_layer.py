import json, unittest
from pathlib import Path
from src.production_layer import load_source_registry, production_gate_status

class ProductionLayerTests(unittest.TestCase):
    def test_registry_covers_required_domains(self):
        registry = load_source_registry(Path(__file__).parents[1] / "config" / "SOURCE_REGISTRY.json")
        self.assertEqual(len(registry["domains"]), 7)
    def test_intraday_without_authorized_feed_is_blocked(self):
        registry = load_source_registry(Path(__file__).parents[1] / "config" / "SOURCE_REGISTRY.json")
        result = production_gate_status(registry, slot="0930")
        self.assertEqual(result["e2e"], "BLOCKED:INTRADAY_SOURCE_UNAVAILABLE")
