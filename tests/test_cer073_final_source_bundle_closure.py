from __future__ import annotations

import json
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch

import scripts.close_cer073_final_source_bundle as closure
import scripts.build_live_source_bundle as builder


class Args:
    source_bundle = "artifacts/test-final/source_bundle.json"
    fundamental_cross_section = "artifacts/test-final/fundamental.json"
    run_head_sha = "e09d3b95abca5b5158c9acfe4ec24a751a17bdf7"
    actions_run_id = "1"
    actions_job_name = "final-source-bundle-closure"


def record(symbol: str) -> dict:
    row = {key: index + 1 for index, key in enumerate(builder.FULL_COMPONENTS)}
    row.update({
        "symbol": symbol,
        "M7_inputs": {"PT": 1, "PV": 2, "MO": 3, "FI": 4, "IT": 5, "LH": 6, "RS": 7},
        "MHE_inputs": {"H5": 8, "H20": 9, "H60": 10, "H120": 11},
        "Rotation_inputs": {"RS_CHANGE": 12, "VOL_CHANGE": 13, "SMART_MONEY": 14, "MOMENTUM_CHANGE": 15},
        "SmartMoney_inputs": {"FC": 16},
        "Fundamental": 17,
        "RelativeStrength": 18,
        "Liquidity": 19,
        "Stage_inputs": {"stage": "WATCH"},
        "Stage_evidence": {"calculation_status": "PASS", "source_state_id": "state", "stage_field_lineage": {"x": "y"}, "lineage_binding_status": "PENDING_SNAPSHOT_BINDING"},
    })
    return row


def source(symbol: str) -> dict:
    return {"source_lineage": {
        "stock_history": {"source": "TWSE_STOCK_DAY", "trade_dates": ["2026-09-18"], "source_timestamps": ["2026-09-18"]},
        "benchmark": {"source": "TAIEX", "trade_dates": ["2026-09-18"], "source_timestamps": ["2026-09-18"]},
        "institutional": {"source": "TWSE_T86", "trading_dates": ["2026-09-18"], "source_timestamps": ["2026-09-18"]},
        "tdcc": {"source": "TDCC", "periods": ["2026-09-12"], "source_timestamps": ["2026-09-12"]},
        "fundamental": {"source": "MOPS", "revenue_periods": ["2026-08"], "eps_quarters": [{"fiscal_year": 2026, "quarter": 2}], "content_hash": "fund"},
        "technical_features": {"source": "RATE technical feature engine", "trade_date": "2026-09-18"},
        "smart_money_rotation": {"source": "RATE institutional engine", "content_hash": "sm"},
        "stage": {"source_type": "RATE stage engine", "source_state_id": "state", "calculation_status": "PASS"},
    }}


class FinalSourceBundleClosureTests(unittest.TestCase):
    def setUp(self):
        self.root = Path("artifacts/test-final")
        shutil.rmtree(self.root, ignore_errors=True)
        self.root.mkdir(parents=True)
        self.symbols = [f"{1000+i}" for i in range(30)]
        bundle = {
            "validation_status": "PASS",
            "input_snapshot_id": None,
            "production_state_created": False,
            "production_decision_state_persisted": 0,
            "production_namespace_modified": False,
            "universe": self.symbols,
            "decision_records": [record(s) for s in self.symbols],
            "production_sources": {s: source(s) for s in self.symbols},
            "prior_stage_package_binding": {"status": "PASS", "digest": closure.PRIOR_STAGE_DIGEST, "symbols_bound": 30},
        }
        fundamental = {"validation_status": "PASS", "as_of_date": closure.AS_OF_DATE, "analytical_output_hash": closure.FUNDAMENTAL_HASH,
            "rows": [{"symbol": s, "fundamental_score": 17, "revenue_events": [1, 2, 3], "eps_events": list(range(8))} for s in self.symbols]}
        Path(Args.source_bundle).write_text(json.dumps(bundle), encoding="utf-8")
        Path(Args.fundamental_cross_section).write_text(json.dumps(fundamental), encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_final_closure_passes_and_is_deterministic(self):
        with patch.object(closure, "_verify_model_freeze", return_value={"status": "PASS"}):
            final_bundle, completeness, provenance, determinism = closure.build_closure(Args)
        self.assertEqual(final_bundle["validation_status"], "PASS")
        self.assertEqual(completeness["full_19_component_completeness"], "30/30")
        self.assertEqual(provenance["source_provenance_completeness"], "30/30")
        self.assertEqual(determinism["canonical_bundle_hash_run_1"], determinism["canonical_bundle_hash_run_2"])

    def test_fundamental_hash_mismatch_fails_closed(self):
        data = json.loads(Path(Args.fundamental_cross_section).read_text())
        data["analytical_output_hash"] = "bad"
        Path(Args.fundamental_cross_section).write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "ACCEPTED_FUNDAMENTAL_HASH_MISMATCH"):
            closure.build_closure(Args)

    def test_build_live_source_bundle_loads_accepted_fundamental_without_fetch(self):
        accepted = {"validation_status": "PASS", "as_of_date": closure.AS_OF_DATE, "analytical_output_hash": closure.FUNDAMENTAL_HASH,
            "rows": [{"symbol": s, "fundamental_score": 17, "revenue_periods": ["2026-08", "2026-07", "2026-06"],
                "eps_quarters": ["2026Q2", "2026Q1", "2025Q4", "2025Q3", "2025Q2", "2025Q1", "2024Q4", "2024Q3"],
                "revenue_events": [{"revenue_yoy": 1, "provider": "MOPS", "official_product": "revenue", "endpoint": "e", "official_disclosure_date": "2026-09-10", "content_hash": "r"} for _ in range(3)],
                "eps_events": [{"single_quarter_eps": 1, "fiscal_year": 2026, "quarter": 2, "provider": "MOPS", "official_product": "eps", "endpoint": "e", "official_disclosure_date": "2026-08-14", "content_hash": "q", "source_semantics": "OFFICIAL_SINGLE_QUARTER"} for _ in range(8)]} for s in self.symbols]}
        p = self.root / "accepted_fundamental.json"
        p.write_text(json.dumps(accepted), encoding="utf-8")
        with patch.dict("os.environ", {"RATE_CER073_ACCEPTED_FUNDAMENTAL_CROSS_SECTION": str(p)}):
            result = builder._fundamental_history(self.symbols, {}, closure.AS_OF_DATE)
        self.assertEqual(set(result), set(self.symbols))
        self.assertEqual(result[self.symbols[0]]["Fundamental"], 17)


if __name__ == "__main__":
    unittest.main()
