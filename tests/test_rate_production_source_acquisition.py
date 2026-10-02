from __future__ import annotations

import json
import shutil
import unittest
from pathlib import Path

from scripts.build_production_source_bundle_from_official import (
    TWSEAdapter,
    TPExAdapter,
    TDCCAdapter,
    MOPSAdapter,
    build_bundle,
    parse_source_urls,
    source_snapshot_id,
)
from scripts.resolve_production_runtime_context import resolve_context


class RateProductionSourceAcquisitionTests(unittest.TestCase):
    def setUp(self):
        self.root = Path("artifacts/test-rate-production-source-acquisition")
        shutil.rmtree(self.root, ignore_errors=True)
        self.root.mkdir(parents=True, exist_ok=True)
        self.trading_date = "2026-09-21"
        self.cadence = "19:30"

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _technical_source(self, seed: int = 1):
        return {"technical_features": {key: float(seed + index) for index, key in enumerate(("PT", "PV", "MO", "RS", "H5", "H20", "H60", "H120", "RelativeStrength", "Liquidity"))}}

    def _records(self, count: int = 30, *, trading_date: str | None = None, missing_symbol: bool = False, missing_feature: bool = False):
        records = []
        for idx in range(count):
            symbol = str(1000 + idx)
            row = {"symbol": symbol, "trading_date": trading_date or self.trading_date, **self._technical_source(idx + 1)}
            if missing_symbol and idx == 0:
                row.pop("symbol")
            if missing_feature and idx == 0:
                row["technical_features"].pop("Liquidity")
            records.append(row)
        return {"schema_version": "RATE-OFFICIAL-NORMALIZED-SOURCE-V1", "trading_date": trading_date or self.trading_date, "records": records}

    def _uri(self, name: str, payload: object) -> str:
        path = self.root / name
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return path.resolve().as_uri()

    def _build(self, url: str, name: str = "case"):
        out = self.root / name / "RATE_PRODUCTION_SOURCE_BUNDLE.json"
        ev = self.root / name / "RATE_PRODUCTION_OFFICIAL_SOURCE_ACQUISITION_EVIDENCE.json"
        mx = self.root / name / "RATE_PRODUCTION_SOURCE_REQUIREMENT_MATRIX.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        result = build_bundle(rate_source_url=url, trading_date=self.trading_date, cadence=self.cadence, output=out, evidence_output=ev, requirement_matrix_output=mx)
        return result, json.loads(out.read_text(encoding="utf-8")), json.loads(ev.read_text(encoding="utf-8")), json.loads(mx.read_text(encoding="utf-8"))

    def test_source_acquisition_does_not_require_previous_live_state(self):
        context = resolve_context(cadence="09:30", event_name="schedule", dispatch_trading_date=None, state_root=self.root / "no-live-state")
        if context["runtime_mode"] == "RUN":
            self.assertEqual(context["validation_status"], "BLOCKED")
            self.assertEqual(context["blocking_reason"], "LIVE_PREVIOUS_PRODUCTION_STATE_MISSING")
        url = self._uri("official.json", self._records())
        result, bundle, evidence, _ = self._build(url)
        self.assertEqual(result["validation_status"], "PASS")
        self.assertTrue(evidence["source_acquisition_independent_from_previous_state"])
        self.assertFalse(evidence["previous_state_required"])
        self.assertEqual(bundle["coverage"], "30/30")

    def test_source_only_workflow_boundary(self):
        text = Path(".github/workflows/rate_production_source_acquisition.yml").read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch:", text)
        self.assertNotIn("schedule:", text)
        self.assertNotIn("pull_request", text)
        self.assertNotIn("push:", text)
        self.assertNotIn("publish_production_state_latest.py", text)
        self.assertNotIn("RATE_PRODUCTION_STATE_LATEST", text)
        self.assertNotIn("production_state/live", text)
        self.assertNotIn("rebaseline_authorizations", text)
        self.assertNotIn("rate_production_rebaseline_bootstrap", text)
        self.assertIn('SCHEDULED_SOAK_CREDIT: "false"', text)
        self.assertIn('ACCEPTANCE_COUNTER_RESET: "false"', text)

    def test_source_specific_adapters_valid_payload_normalize_pass(self):
        url = self._uri("adapter.json", self._records())
        for cls in (TWSEAdapter, TPExAdapter, TDCCAdapter, MOPSAdapter):
            adapter = cls(url)
            normalized = adapter.normalize(adapter.fetch(), self.trading_date)
            self.assertEqual(normalized["normalization_status"], "PASS", cls.__name__)
            self.assertEqual(normalized["normalized_count"], 30, cls.__name__)

    def test_malformed_source_payloads_blocked(self):
        cases = [
            ("twse", TWSEAdapter, {"records": [{"trading_date": self.trading_date}]}),
            ("tpex", TPExAdapter, {"records": [{"symbol": "1000", "trading_date": "2026-09-20"}]}),
            ("tdcc", TDCCAdapter, {"records": "bad"}),
            ("mops", MOPSAdapter, {"records": [{"symbol": "1000", "trading_date": self.trading_date, "technical_features": {"PT": "bad"}}]}),
        ]
        for name, cls, payload in cases:
            url = self._uri(f"{name}.json", payload)
            normalized = cls(url).normalize(cls(url).fetch(), self.trading_date)
            self.assertNotEqual(normalized["normalization_status"], "PASS", name)

    def test_required_source_http_and_parse_failure_blocked(self):
        result, bundle, evidence, _ = self._build("TWSE=https://openapi.twse.com.tw/v1/not-a-real-rate-endpoint;TPEX=https://www.tpex.org.tw/openapi/v1/not-a-real-rate-endpoint", "http-fail")
        self.assertEqual(result["validation_status"], "BLOCKED")
        self.assertEqual(bundle["validation_status"], "BLOCKED")
        self.assertEqual(evidence["coverage"], "0/30")

    def test_symbol_mapping_required_dataset_stale_future_and_29_of_30_blocked(self):
        cases = {
            "symbol": self._records(missing_symbol=True),
            "required_dataset": self._records(missing_feature=True),
            "future": self._records(trading_date="2026-09-22"),
            "29": self._records(count=29),
        }
        for name, payload in cases.items():
            result, bundle, _, _ = self._build(self._uri(f"{name}.json", payload), name)
            self.assertEqual(result["validation_status"], "BLOCKED", name)
            self.assertEqual(bundle["validation_status"], "BLOCKED", name)
            self.assertNotEqual(bundle["decision_record_coverage"]["status"], "PASS", name)

    def test_30_of_30_pass_snapshot_ids_deterministic_and_no_fallback(self):
        url = self._uri("pass.json", self._records())
        first, bundle1, evidence1, matrix1 = self._build(url, "pass1")
        second, bundle2, evidence2, matrix2 = self._build(url, "pass2")
        self.assertEqual(first["validation_status"], "PASS")
        self.assertEqual(second["validation_status"], "PASS")
        self.assertEqual(bundle1["coverage"], "30/30")
        self.assertEqual(bundle1["source_snapshot_id"], bundle2["source_snapshot_id"])
        self.assertEqual(bundle1["input_snapshot_ids"], bundle2["input_snapshot_ids"])
        self.assertTrue(bundle1["source_snapshot_id"].startswith("rate-source-snapshot-"))
        self.assertTrue(all(x.startswith("rate-source-input-") for x in bundle1["input_snapshot_ids"]))
        for key in ("fixture_fallback", "synthetic_fallback", "historical_acceptance_bundle_fallback", "local_cache_fallback", "recovery_fallback", "manual_data_fallback", "third_party_fallback"):
            self.assertEqual(bundle1[key], "FORBIDDEN")
            self.assertEqual(evidence1["no_fallback_status"][key], "FORBIDDEN")
        self.assertEqual(matrix1["validation_status"], "PASS")
        self.assertEqual(matrix2["validation_status"], "PASS")

    def test_source_only_build_does_not_touch_latest_live_or_authorization(self):
        url = self._uri("official.json", self._records())
        before_latest = Path("artifacts/RATE_PRODUCTION_STATE_LATEST.json").exists()
        before_live = Path("artifacts/production_state/live").exists()
        before_auth = Path("control/rebaseline_authorizations").exists()
        result, _, evidence, _ = self._build(url, "no-touch")
        self.assertEqual(result["validation_status"], "PASS")
        self.assertEqual(Path("artifacts/RATE_PRODUCTION_STATE_LATEST.json").exists(), before_latest)
        self.assertEqual(Path("artifacts/production_state/live").exists(), before_live)
        self.assertEqual(Path("control/rebaseline_authorizations").exists(), before_auth)
        self.assertFalse(evidence["latest_touched"])
        self.assertFalse(evidence["live_state_touched"])
        self.assertFalse(evidence["authorization_created"])
        self.assertFalse(evidence["bootstrap_dispatched"])
        self.assertFalse(evidence["soak_credit"])

    def test_source_snapshot_id_helper_is_deterministic(self):
        one = source_snapshot_id("TWSE", "market", self.trading_date, "a" * 64)
        two = source_snapshot_id("TWSE", "market", self.trading_date, "a" * 64)
        three = source_snapshot_id("TWSE", "market", self.trading_date, "b" * 64)
        self.assertEqual(one, two)
        self.assertNotEqual(one, three)

    def test_parse_source_urls_supports_labeled_and_legacy_single_artifact(self):
        labeled = parse_source_urls("TWSE=file:///a;TPEX=file:///b;TDCC=file:///c;MOPS=file:///d")
        self.assertEqual(labeled["TWSE"], "file:///a")
        legacy = parse_source_urls("file:///only")
        self.assertEqual(legacy["TWSE"], "file:///only")
        self.assertEqual(legacy["TPEX"], "file:///only")


if __name__ == "__main__":
    unittest.main()
