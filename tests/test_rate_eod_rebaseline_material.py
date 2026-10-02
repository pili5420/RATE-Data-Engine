from __future__ import annotations

import json
import os
import shutil
import unittest
from pathlib import Path

from scripts.build_production_source_bundle_from_official import build_bundle
from scripts.build_production_rebaseline_material import build_rebaseline_material
from src.production_live_state import file_hash


class RateEODRebaselineMaterialTests(unittest.TestCase):
    def setUp(self):
        self.root = Path("artifacts/test-rate-eod-rebaseline-material")
        shutil.rmtree(self.root, ignore_errors=True)
        self.root.mkdir(parents=True, exist_ok=True)
        self.old_env = {k: os.environ.get(k) for k in ("RATE_SOURCE_TEST_CONTEXT", "RATE_SOURCE_TEST_FRESHNESS_CONTRACTS")}
        os.environ["RATE_SOURCE_TEST_CONTEXT"] = "1"
        os.environ["RATE_SOURCE_TEST_FRESHNESS_CONTRACTS"] = "1"

    def tearDown(self):
        for key, value in self.old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        shutil.rmtree(self.root, ignore_errors=True)

    def _records(self):
        keys = ("PT", "PV", "MO", "RS", "H5", "H20", "H60", "H120", "RelativeStrength", "Liquidity")
        rows = []
        for idx in range(30):
            rows.append({
                "symbol": str(1000 + idx),
                "trading_date": "2026-10-02",
                "technical_features": {key: float(idx + offset + 1) for offset, key in enumerate(keys)},
                "FI": {"net_buy": idx},
                "IT": {"trust_net_buy": idx},
                "SmartMoney_inputs": {"foreign_institutional": idx},
                "SMART_MONEY": float(idx),
                "LH": {"large_holder_ratio": 40 + idx},
                "Fundamental": {"eps": 1 + idx / 100},
                "Stage_inputs": {"listed_market": "TWSE"},
                "Stage_evidence": {"metadata_source": "official"},
                "Rotation_inputs": {"benchmark": "TAIEX"},
                "Rotation": float(idx),
            })
        return {"schema_version": "RATE-OFFICIAL-NORMALIZED-SOURCE-V2", "trading_date": "2026-10-02", "records": rows}

    def _write(self, name, payload):
        path = self.root / name
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return path

    def test_1930_source_bundle_builds_rebaseline_material_dry_run(self):
        source = self._write("official.json", self._records())
        universe = self._write("universe.json", {"artifact": "RATE_PRODUCTION_UNIVERSE_CONTRACT", "validation_status": "PASS", "approved_universe": [str(1000 + idx) for idx in range(30)]})
        bundle_path = self.root / "RATE_PRODUCTION_SOURCE_BUNDLE.json"
        evidence = build_bundle(
            rate_source_url=source.resolve().as_uri(),
            trading_date="2026-10-02",
            cadence="19:30",
            output=bundle_path,
            evidence_output=self.root / "evidence.json",
            requirement_matrix_output=self.root / "matrix.json",
            universe_contract=universe,
            universe_binding_output=self.root / "binding.json",
            freshness_matrix_output=self.root / "freshness.json",
            feature_input_contract_output=self.root / "feature.json",
        )
        bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
        self.assertEqual(evidence["validation_status"], "PASS")
        self.assertEqual(bundle["coverage"], "30/30")
        self.assertEqual(bundle["freshness"], "PASS")
        material = build_rebaseline_material(source_bundle_path=bundle_path, output_root=self.root / "rebaseline_material")
        self.assertEqual(material["validation_status"], "PASS")
        self.assertEqual(material["material_status"], "REBASELINE_MATERIAL_READY_FOR_CONTROL_CENTER_REVIEW")
        self.assertTrue(material["baseline_id"].startswith("rate-rebaseline-20261002-1930"))
        self.assertTrue(material["state_id"].startswith("rate-state-"))
        self.assertEqual(len(material["state_hash"]), 64)
        self.assertFalse(material["live_namespace_touched"])
        self.assertFalse(material["latest_touched"])
        self.assertFalse(material["authorization_created"])
        self.assertFalse(material["bootstrap_dispatched"])
        material_root = Path(material["material_root"])
        manifest = material_root / "RATE_PRODUCTION_REBASELINE_MANIFEST.json"
        roy = json.loads((material_root / "CONTROL_CENTER_REBASELINE_ROY_OPENING_STATE.json").read_text(encoding="utf-8"))
        state = json.loads((material_root / "RATE_PRODUCTION_REBASELINE_DECISION_STATE.json").read_text(encoding="utf-8"))
        self.assertEqual(file_hash(manifest), material["manifest_sha256"])
        self.assertEqual(roy["positions_count"], 10)
        self.assertEqual(roy["positions"], [])
        self.assertEqual(roy["position_detail_synthesis"], "PROHIBITED")
        self.assertEqual(roy["totals"], {"cash": 179523, "opening_nav": 1509636, "stock_market_value": 1330113, "stock_total_cost": 1972438})
        self.assertNotIn("previous_state_id", state["decision"])
        self.assertNotIn("runtime_previous_state_id", state["decision"])


if __name__ == "__main__":
    unittest.main()
