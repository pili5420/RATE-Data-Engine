from __future__ import annotations

import json
import os
import shutil
import unittest
from pathlib import Path

from scripts.build_production_source_bundle_from_official import (
    TWSEAdapter,
    TPExAdapter,
    TDCCAdapter,
    MOPSAdapter,
    build_bundle,
    cadence_blocking_reason,
    cadence_domain_rule,
    load_external_dependencies,
    load_source_registry,
    parse_source_urls,
    source_snapshot_id,
    _normalize_source_date,
)
from scripts.resolve_production_runtime_context import resolve_context


class RateProductionSourceAcquisitionTests(unittest.TestCase):
    def setUp(self):
        self.root = Path("artifacts/test-rate-production-source-acquisition")
        shutil.rmtree(self.root, ignore_errors=True)
        self.root.mkdir(parents=True, exist_ok=True)
        self.trading_date = "2026-09-21"
        self.cadence = "19:30"
        self._old_env = {k: os.environ.get(k) for k in ("RATE_SOURCE_TEST_CONTEXT", "RATE_SOURCE_TEST_FRESHNESS_CONTRACTS")}
        os.environ["RATE_SOURCE_TEST_CONTEXT"] = "1"
        os.environ["RATE_SOURCE_TEST_FRESHNESS_CONTRACTS"] = "1"

    def tearDown(self):
        for key, value in self._old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        shutil.rmtree(self.root, ignore_errors=True)

    def _technical_source(self, seed: int = 1):
        return {"technical_features": {key: float(seed + index) for index, key in enumerate(("PT", "PV", "MO", "RS", "H5", "H20", "H60", "H120", "RelativeStrength", "Liquidity"))}}

    def _complete_fields(self, idx: int):
        return {
            **self._technical_source(idx + 1),
            "FI": {"net_buy": idx + 1},
            "IT": {"trust_net_buy": idx + 2},
            "SmartMoney_inputs": {"foreign_institutional": idx + 1},
            "SMART_MONEY": float(idx + 3),
            "LH": {"large_holder_ratio": 40 + idx},
            "Fundamental": {"eps": 1.0 + idx / 100},
            "Stage_inputs": {"listed_market": "TWSE"},
            "Stage_evidence": {"metadata_source": "official"},
            "Rotation_inputs": {"benchmark": "TAIEX"},
            "Rotation": float(idx),
        }

    def _records(self, count: int = 30, *, trading_date: str | None = None, missing_symbol: bool = False, missing_feature: bool = False, missing_dataset: str | None = None):
        records = []
        for idx in range(count):
            symbol = str(1000 + idx)
            row = {"symbol": symbol, "trading_date": trading_date or self.trading_date, **self._complete_fields(idx)}
            if missing_symbol and idx == 0:
                row.pop("symbol")
            if missing_feature and idx == 0:
                row["technical_features"].pop("Liquidity")
            if missing_dataset and idx == 0:
                for key in {
                    "large_holder": ["LH"],
                    "fundamental": ["Fundamental"],
                    "trading_metadata": ["Stage_inputs", "Stage_evidence"],
                    "benchmark_market_structure": ["Rotation_inputs", "Rotation"],
                    "institutional_smart_money": ["FI", "IT", "SmartMoney_inputs", "SMART_MONEY"],
                }[missing_dataset]:
                    row.pop(key, None)
            records.append(row)
        return {"schema_version": "RATE-OFFICIAL-NORMALIZED-SOURCE-V2", "trading_date": trading_date or self.trading_date, "records": records}

    def _uri(self, name: str, payload: object) -> str:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return path.resolve().as_uri()

    def _build(self, url: str, name: str = "case", *, universe_contract: str | None = None, source_registry: str | None = None):
        out = self.root / name / "RATE_PRODUCTION_SOURCE_BUNDLE.json"
        ev = self.root / name / "RATE_PRODUCTION_OFFICIAL_SOURCE_ACQUISITION_EVIDENCE.json"
        mx = self.root / name / "RATE_PRODUCTION_SOURCE_REQUIREMENT_MATRIX.json"
        ub = self.root / name / "RATE_PRODUCTION_UNIVERSE_BINDING.json"
        fm = self.root / name / "RATE_PRODUCTION_SOURCE_FRESHNESS_MATRIX.json"
        fc = self.root / name / "RATE_PRODUCTION_FEATURE_INPUT_CONTRACT.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        result = build_bundle(rate_source_url=url, trading_date=self.trading_date, cadence=self.cadence, output=out, evidence_output=ev, requirement_matrix_output=mx, universe_contract=universe_contract, universe_binding_output=ub, freshness_matrix_output=fm, feature_input_contract_output=fc, source_registry=source_registry)
        return result, json.loads(out.read_text(encoding="utf-8")), json.loads(ev.read_text(encoding="utf-8")), json.loads(mx.read_text(encoding="utf-8")), json.loads(ub.read_text(encoding="utf-8")), json.loads(fm.read_text(encoding="utf-8")), json.loads(fc.read_text(encoding="utf-8"))

    def _universe_contract(self, symbols: list[str] | None = None) -> str:
        symbols = symbols or [str(1000 + idx) for idx in range(30)]
        path = self.root / "universe_contract.json"
        path.write_text(json.dumps({"artifact": "RATE_PRODUCTION_UNIVERSE_CONTRACT", "validation_status": "PASS", "approved_universe": symbols}, ensure_ascii=False), encoding="utf-8")
        return str(path)

    def _raw_history(self, symbol: str, offset: int = 0):
        rows = []
        for idx in range(130):
            close = 50.0 + offset + idx * 0.1
            rows.append({
                "symbol": symbol,
                "trading_date": f"2026-05-{idx + 1:02d}" if idx < 31 else f"2026-06-{idx - 30:02d}" if idx < 61 else f"2026-07-{idx - 60:02d}" if idx < 92 else f"2026-08-{idx - 91:02d}" if idx < 122 else f"2026-09-{idx - 121:02d}",
                "open": close - 0.2,
                "high": close + 0.4,
                "low": close - 0.5,
                "close": close,
                "volume": 100000 + idx + offset,
                "turnover": (100000 + idx + offset) * close,
            })
        rows[-1]["trading_date"] = self.trading_date
        return rows

    def _registry_payloads(self, symbols: list[str] | None = None):
        symbols = symbols or [str(1000 + idx) for idx in range(30)]
        market = {"records": [{"symbol": symbol, "history": self._raw_history(symbol, idx)} for idx, symbol in enumerate(symbols)]}
        benchmark = {"records": [{"benchmark": "TAIEX", "history": self._raw_history("TAIEX", 100)}]}
        institutional = {"records": [{"symbol": symbol, "trading_date": self.trading_date, "FI": 10 + idx, "IT": 5 + idx, "SmartMoney_inputs": {"FI": 10 + idx, "IT": 5 + idx}, "SMART_MONEY": 20 + idx} for idx, symbol in enumerate(symbols)]}
        large_holder = {"records": [{"stock_code": symbol, "published_date": self.trading_date, "large_holder": 30 + idx} for idx, symbol in enumerate(symbols)]}
        fundamental = {"records": [{"company_code": symbol, "publication_date": self.trading_date, "fundamental": 40 + idx} for idx, symbol in enumerate(symbols)]}
        metadata = {"records": [{"symbol": symbol, "trading_date": self.trading_date, "Stage_inputs": {"listed_market": "TWSE", "trading_status": "NORMAL"}, "Stage_evidence": {"metadata_source": "official"}, "Rotation_inputs": {"benchmark": "TAIEX"}, "Rotation": 50 + idx} for idx, symbol in enumerate(symbols)]}
        return {
            "market": market,
            "benchmark": benchmark,
            "institutional": institutional,
            "large_holder": large_holder,
            "fundamental": fundamental,
            "metadata": metadata,
        }

    def _registry(self, payloads: dict[str, object], *, omit_domain: str | None = None) -> str:
        registry = load_source_registry("config/RATE_PRODUCTION_OFFICIAL_SOURCE_REGISTRY_V1.json")
        endpoint_by_dataset = {
            "twse_market_daily": self._uri("registry/market.json", payloads["market"]),
            "tpex_market_daily": self._uri("registry/tpex-market.json", {"records": []}),
            "twse_benchmark": self._uri("registry/benchmark.json", payloads["benchmark"]),
            "twse_institutional": self._uri("registry/institutional.json", payloads["institutional"]),
            "tpex_institutional": self._uri("registry/tpex-institutional.json", {"records": []}),
            "tdcc_large_holder": self._uri("registry/large-holder.json", payloads["large_holder"]),
            "twse_fundamental_revenue": self._uri("registry/fundamental.json", payloads["fundamental"]),
            "twse_trading_metadata": self._uri("registry/metadata.json", payloads["metadata"]),
        }
        datasets = []
        for item in registry["datasets"]:
            if item["domain"] == omit_domain:
                continue
            updated = dict(item)
            if item["dataset_id"] in endpoint_by_dataset:
                updated["endpoint"] = endpoint_by_dataset[item["dataset_id"]]
            datasets.append(updated)
        registry["datasets"] = datasets
        path = self.root / "registry" / "RATE_PRODUCTION_OFFICIAL_SOURCE_REGISTRY_V1.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(registry, ensure_ascii=False), encoding="utf-8")
        return str(path)

    def test_source_acquisition_does_not_require_previous_live_state(self):
        context = resolve_context(cadence="09:30", event_name="schedule", dispatch_trading_date=None, state_root=self.root / "no-live-state")
        if context["runtime_mode"] == "RUN":
            self.assertEqual(context["validation_status"], "BLOCKED")
            self.assertEqual(context["blocking_reason"], "LIVE_PREVIOUS_PRODUCTION_STATE_MISSING")
        url = self._uri("official.json", self._records())
        result, bundle, evidence, *_ = self._build(url, universe_contract=self._universe_contract())
        self.assertEqual(result["validation_status"], "PASS")
        self.assertTrue(evidence["source_acquisition_independent_from_previous_state"])
        self.assertFalse(evidence["previous_state_required"])
        self.assertEqual(bundle["coverage"], "30/30")

    def test_source_only_workflow_boundary(self):
        text = Path(".github/workflows/rate_production_source_acquisition.yml").read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch:", text)
        self.assertIn("github.ref == 'refs/heads/main'", text)
        self.assertIn("ref: ${{ github.sha }}", text)
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
        self.assertIn('EXECUTION_AUTHORITY: "MAIN_ONLY"', text)


    def test_cadence_applicability_rules_preserve_intraday_requirement(self):
        self.assertEqual(cadence_domain_rule("07:30", "market_intraday")["applicability"], "NOT_APPLICABLE")
        self.assertEqual(cadence_domain_rule("19:30", "market_intraday")["applicability"], "NOT_APPLICABLE")
        self.assertEqual(cadence_domain_rule("09:30", "market_intraday")["applicability"], "REQUIRED")
        self.assertEqual(cadence_domain_rule("12:00", "market_intraday")["applicability"], "REQUIRED")
        self.assertEqual(cadence_blocking_reason("09:30"), "EXTERNAL_AUTHORIZED_INTRADAY_FEED_DEPENDENCY")
        self.assertEqual(cadence_blocking_reason("12:00"), "EXTERNAL_AUTHORIZED_INTRADAY_FEED_DEPENDENCY")
        self.assertIsNone(cadence_blocking_reason("19:30"))
        registry = load_external_dependencies()
        dep = next(item for item in registry["dependencies"] if item["dependency_id"] == "EXTERNAL_AUTHORIZED_INTRADAY_FEED_DEPENDENCY")
        self.assertEqual(dep["affected_cadences"], ["09:30", "12:00"])
        self.assertFalse(dep["fallback_allowed"])
        self.assertFalse(dep["soak_credit_allowed_while_blocked"])
        self.assertFalse(dep["cer081_completion_allowed_while_blocked"])
        self.assertFalse(dep["production_acceptance_allowed_while_blocked"])

    def test_source_specific_adapters_valid_real_schema_payloads_normalize_pass(self):
        cases = [
            (TWSEAdapter, {"records": [{"Code": "1000", "Date": self.trading_date, **self._complete_fields(0)}]}),
            (TPExAdapter, {"records": [{"SecuritiesCompanyCode": "1000", "Date": self.trading_date, **self._complete_fields(0)}]}),
            (TDCCAdapter, {"records": [{"stock_code": "1000", "published_date": self.trading_date, "large_holder": {"ratio": 50}}]}),
            (MOPSAdapter, {"records": [{"company_code": "1000", "publication_date": self.trading_date, "fundamental": {"eps": 2.0}}]}),
        ]
        for cls, payload in cases:
            self.assertNotEqual(cls.parser_version, "RATE-SOURCE-PARSER-GENERIC-V2")
            url = self._uri(f"{cls.__name__}.json", payload)
            normalized = cls(url).normalize(cls(url).fetch(), self.trading_date)
            self.assertEqual(normalized["normalization_status"], "PASS", cls.__name__)
            self.assertEqual(normalized["normalized_count"], 1, cls.__name__)

    def test_registry_exists_and_maps_required_domains(self):
        registry = load_source_registry("config/RATE_PRODUCTION_OFFICIAL_SOURCE_REGISTRY_V1.json")
        domains = {item["domain"] for item in registry["datasets"]}
        self.assertTrue({"market_daily", "benchmark", "institutional", "large_holder", "fundamental", "trading_metadata", "market_intraday"} <= domains)
        self.assertTrue(all(item["fallback_allowed"] is False for item in registry["datasets"]))
        intraday = next(item for item in registry["datasets"] if item["domain"] == "market_intraday")
        self.assertEqual(intraday["cadence_applicability"]["07:30"], "NOT_APPLICABLE")
        self.assertEqual(intraday["cadence_applicability"]["19:30"], "NOT_APPLICABLE")
        self.assertEqual(intraday["cadence_applicability"]["09:30"], "BLOCKED_EXTERNAL")
        self.assertEqual(intraday["blocked_dependency"], "EXTERNAL_AUTHORIZED_INTRADAY_FEED_DEPENDENCY")

    def test_registry_eod_raw_market_rows_enter_existing_feature_pipeline(self):
        symbols = [str(1000 + idx) for idx in range(30)]
        registry = self._registry(self._registry_payloads(symbols))
        result, bundle, evidence, matrix, binding, freshness, feature = self._build("", "registry-1930", universe_contract=self._universe_contract(symbols), source_registry=registry)
        self.assertEqual(result["validation_status"], "PASS")
        self.assertEqual(bundle["coverage"], "30/30")
        self.assertEqual(bundle["validation_status"], "PASS")
        self.assertEqual(bundle["datasets_missing"], [])
        self.assertEqual(bundle["blocked_dependencies"], [])
        self.assertEqual(binding["validation_status"], "PASS")
        self.assertEqual(freshness["validation_status"], "PASS")
        self.assertNotIn("technical_features", json.dumps(self._registry_payloads(symbols)["market"], ensure_ascii=False))
        first = bundle["production_sources"][symbols[0]]
        self.assertIn("technical_features", first)
        self.assertEqual(first["feature_lineage"]["technical_features"]["source"], "src.technical_features.compute_scores")
        self.assertFalse(bundle["official_source_transformation"]["feature_pipeline"]["source_side_precomputed_feature_dependency"])
        domains = {row["dataset_name"]: row for row in matrix["requirements"]}
        self.assertEqual(domains["market_intraday"]["cadence_applicability"], "NOT_APPLICABLE")
        self.assertEqual(domains["market_price_volume"]["coverage_status"], "PASS")
        self.assertEqual(domains["benchmark_market_structure"]["coverage_status"], "PASS")

    def test_registry_0730_eod_pass_and_intraday_cadences_remain_external_blocked(self):
        symbols = [str(1000 + idx) for idx in range(30)]
        registry = self._registry(self._registry_payloads(symbols))
        self.cadence = "07:30"
        result, bundle, *_ = self._build("", "registry-0730", universe_contract=self._universe_contract(symbols), source_registry=registry)
        self.assertEqual(result["validation_status"], "PASS")
        self.assertEqual(bundle["authorized_intraday_feed"], "NOT_APPLICABLE")
        for cadence in ("09:30", "12:00"):
            self.cadence = cadence
            result2, bundle2, evidence2, *_ = self._build("", f"registry-{cadence.replace(':','')}", universe_contract=self._universe_contract(symbols), source_registry=registry)
            self.assertEqual(result2["validation_status"], "BLOCKED")
            self.assertEqual(bundle2["blocking_reason"], "EXTERNAL_AUTHORIZED_INTRADAY_FEED_DEPENDENCY")
            self.assertEqual(evidence2["cadence_applicability"]["external_dependency"], "EXTERNAL_AUTHORIZED_INTRADAY_FEED_DEPENDENCY")
        self.cadence = "19:30"

    def test_registry_missing_required_eod_domain_fails_closed(self):
        symbols = [str(1000 + idx) for idx in range(30)]
        registry = self._registry(self._registry_payloads(symbols), omit_domain="large_holder")
        result, bundle, *_ = self._build("", "registry-missing-large-holder", universe_contract=self._universe_contract(symbols), source_registry=registry)
        self.assertEqual(result["validation_status"], "BLOCKED")
        self.assertEqual(bundle["validation_status"], "BLOCKED")
        self.assertNotEqual(bundle["decision_record_coverage"]["status"], "PASS")

    def test_official_roc_dates_normalize_to_iso(self):
        self.assertEqual(_normalize_source_date("1151002"), "2026-10-02")
        self.assertEqual(_normalize_source_date("20261002"), "2026-10-02")
        self.assertEqual(_normalize_source_date("2026/10/02"), "2026-10-02")

    def test_malformed_source_payloads_blocked(self):
        cases = [("twse", TWSEAdapter, {"records": [{"trading_date": self.trading_date}]}), ("tpex", TPExAdapter, {"records": [{"symbol": "1000", "trading_date": "2026-09-20"}]}), ("tdcc", TDCCAdapter, {"records": "bad"}), ("mops", MOPSAdapter, {"records": [{"symbol": "1000", "trading_date": self.trading_date, "technical_features": {"PT": "bad"}}]})]
        for name, cls, payload in cases:
            url = self._uri(f"{name}.json", payload)
            normalized = cls(url).normalize(cls(url).fetch(), self.trading_date)
            self.assertNotEqual(normalized["normalization_status"], "PASS", name)

    def test_required_source_http_and_parse_failure_blocked(self):
        result, bundle, evidence, *_ = self._build("TWSE=https://openapi.twse.com.tw/v1/not-a-real-rate-endpoint;TPEX=https://www.tpex.org.tw/openapi/v1/not-a-real-rate-endpoint", "http-fail")
        self.assertEqual(result["validation_status"], "BLOCKED")
        self.assertEqual(bundle["validation_status"], "BLOCKED")
        self.assertEqual(evidence["coverage"], "0/30")

    def test_symbol_mapping_required_dataset_future_and_29_of_30_blocked(self):
        cases = {"symbol": self._records(missing_symbol=True), "required_dataset": self._records(missing_feature=True), "future": self._records(trading_date="2026-09-22"), "29": self._records(count=29), "large_holder": self._records(missing_dataset="large_holder"), "fundamental": self._records(missing_dataset="fundamental"), "trading_metadata": self._records(missing_dataset="trading_metadata"), "benchmark": self._records(missing_dataset="benchmark_market_structure")}
        for name, payload in cases.items():
            result, bundle, *_ = self._build(self._uri(f"{name}.json", payload), name)
            self.assertEqual(result["validation_status"], "BLOCKED", name)
            self.assertEqual(bundle["validation_status"], "BLOCKED", name)
            self.assertNotEqual(bundle["decision_record_coverage"]["status"], "PASS", name)

    def test_30_of_30_pass_snapshot_ids_deterministic_and_no_fallback(self):
        url = self._uri("pass.json", self._records())
        first, bundle1, evidence1, matrix1, binding1, freshness1, feature1 = self._build(url, "pass1", universe_contract=self._universe_contract())
        second, bundle2, _, matrix2, *_ = self._build(url, "pass2", universe_contract=self._universe_contract())
        self.assertEqual(first["validation_status"], "PASS")
        self.assertEqual(second["validation_status"], "PASS")
        self.assertEqual(bundle1["coverage"], "30/30")
        self.assertEqual(bundle1["source_snapshot_id"], bundle2["source_snapshot_id"])
        self.assertEqual(bundle1["input_snapshot_ids"], bundle2["input_snapshot_ids"])
        self.assertEqual(binding1["validation_status"], "PASS")
        self.assertEqual(freshness1["validation_status"], "PASS")
        self.assertEqual(feature1["calculation_changes"], "NONE")
        self.assertTrue(all(item["calculation_changed"] is False for item in feature1["feature_inputs"]))
        for key in ("fixture_fallback", "synthetic_fallback", "historical_acceptance_bundle_fallback", "local_cache_fallback", "recovery_fallback", "manual_data_fallback", "third_party_fallback"):
            self.assertEqual(bundle1[key], "FORBIDDEN")
            self.assertEqual(evidence1["no_fallback_status"][key], "FORBIDDEN")
        self.assertEqual(matrix1["validation_status"], "PASS")
        self.assertEqual(matrix2["validation_status"], "PASS")

    def test_production_file_scheme_blocked_and_intraday_external_dependency_sealed(self):
        url = self._uri("official.json", self._records())
        os.environ.pop("RATE_SOURCE_TEST_CONTEXT", None)
        os.environ.pop("RATE_SOURCE_TEST_FRESHNESS_CONTRACTS", None)
        result, bundle, evidence, *_ = self._build(url, "prod-file-blocked")
        self.assertEqual(result["validation_status"], "BLOCKED")
        self.assertIn("UNAPPROVED_PRODUCTION_SOURCE_SCHEME", json.dumps(bundle, ensure_ascii=False))
        os.environ["RATE_SOURCE_TEST_CONTEXT"] = "1"
        for cadence in ("09:30", "12:00"):
            self.cadence = cadence
            result2, bundle2, evidence2, *_ = self._build(url, f"external-{cadence.replace(':','')}", universe_contract=self._universe_contract())
            self.assertEqual(result2["validation_status"], "BLOCKED")
            self.assertEqual(bundle2["blocking_reason"], "EXTERNAL_AUTHORIZED_INTRADAY_FEED_DEPENDENCY")
            self.assertEqual(evidence2["cadence_applicability"]["external_dependency"], "EXTERNAL_AUTHORIZED_INTRADAY_FEED_DEPENDENCY")
            self.assertFalse(evidence2["scheduled_soak_credit"])
            intraday_rows = [row for row in bundle2["required_dataset_coverage"] if row["dataset_name"] == "market_intraday"]
            self.assertEqual(intraday_rows[0]["required_for_this_run"], True)
        self.cadence = "19:30"
        result3, bundle3, evidence3, matrix3, *_ = self._build(url, "eod-intraday-na", universe_contract=self._universe_contract())
        self.assertEqual(result3["validation_status"], "PASS")
        intraday_rows = [row for row in matrix3["requirements"] if row["dataset_name"] == "market_intraday"]
        self.assertEqual(intraday_rows[0]["cadence_applicability"], "NOT_APPLICABLE")
        self.assertEqual(intraday_rows[0]["required_for_this_run"], False)
        self.assertEqual(intraday_rows[0]["coverage_status"], "NOT_APPLICABLE")
        self.assertIsNone(evidence3["cadence_applicability"]["external_dependency"])

    def test_universe_contract_exact_30_and_no_first_30_shortcut(self):
        payload = self._records(31)
        contract_symbols = [str(1001 + idx) for idx in range(30)]
        result, bundle, _, _, binding, *_ = self._build(self._uri("31.json", payload), "contract-filter", universe_contract=self._universe_contract(contract_symbols))
        self.assertEqual(result["validation_status"], "PASS")
        self.assertEqual(binding["validation_status"], "PASS")
        self.assertEqual(binding["allowed_not_selected_symbols"], ["1000"])
        self.assertEqual(binding["extra_raw_symbols_status"], "ALLOWED_NOT_SELECTED")
        self.assertEqual(bundle["universe"], contract_symbols)
        result2, bundle2, *_ = self._build(self._uri("30.json", self._records()), "contract-pass", universe_contract=self._universe_contract())
        self.assertEqual(result2["validation_status"], "PASS")
        self.assertEqual(bundle2["universe"], [str(1000 + idx) for idx in range(30)])

    def test_formal_rebaseline_bootstrap_seed_contract_binds_exact_approved_30(self):
        contract = json.loads(Path("config/RATE_PRODUCTION_UNIVERSE_CONTRACT_V1.json").read_text(encoding="utf-8"))
        approved = contract["approved_universe"]
        records = []
        for idx, symbol in enumerate(["9999", *approved]):
            records.append({"symbol": symbol, "trading_date": self.trading_date, **self._complete_fields(idx)})
        payload = {"schema_version": "RATE-OFFICIAL-NORMALIZED-SOURCE-V2", "trading_date": self.trading_date, "records": records}
        result, bundle, _, _, binding, *_ = self._build(self._uri("formal-seed.json", payload), "formal-seed")
        self.assertEqual(result["validation_status"], "PASS")
        self.assertEqual(bundle["coverage"], "30/30")
        self.assertEqual(bundle["universe"], approved)
        self.assertEqual(binding["validation_status"], "PASS")
        self.assertEqual(binding["universe_mode"], "CONTROL_CENTER_REBASELINE_BOOTSTRAP_SEED")
        self.assertEqual(binding["ranking_status"], "BOOTSTRAP_SEED_NOT_RANKING_RESULT")
        self.assertEqual(binding["valid_scope"], "REBASELINE_BOOTSTRAP_ONLY")
        self.assertEqual(binding["allowed_not_selected_symbols"], ["9999"])
        self.assertEqual(binding["extra_raw_symbols_status"], "ALLOWED_NOT_SELECTED")

    def test_source_only_build_does_not_touch_latest_live_or_authorization(self):
        url = self._uri("official.json", self._records())
        before_latest = Path("artifacts/RATE_PRODUCTION_STATE_LATEST.json").exists()
        before_live = Path("artifacts/production_state/live").exists()
        before_auth = Path("control/rebaseline_authorizations").exists()
        result, _, evidence, *_ = self._build(url, "no-touch", universe_contract=self._universe_contract())
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
        one = source_snapshot_id("TWSE", "market", self.trading_date, "a" * 64, parser_version="v1", source_authority="TWSE")
        two = source_snapshot_id("TWSE", "market", self.trading_date, "a" * 64, parser_version="v1", source_authority="TWSE")
        three = source_snapshot_id("TWSE", "market", self.trading_date, "b" * 64, parser_version="v1", source_authority="TWSE")
        four = source_snapshot_id("TWSE", "market", self.trading_date, "a" * 64, parser_version="v2", source_authority="TWSE")
        self.assertEqual(one, two)
        self.assertNotEqual(one, three)
        self.assertNotEqual(one, four)

    def test_parse_source_urls_supports_labeled_and_legacy_single_artifact(self):
        labeled = parse_source_urls("TWSE=file:///a;TPEX=file:///b;TDCC=file:///c;MOPS=file:///d")
        self.assertEqual(labeled["TWSE"], "file:///a")
        legacy = parse_source_urls("file:///only")
        self.assertEqual(legacy["TWSE"], "file:///only")
        self.assertEqual(legacy["TPEX"], "file:///only")
        self.assertEqual(legacy["TDCC"], "file:///only")
        self.assertEqual(legacy["MOPS"], "file:///only")


if __name__ == "__main__":
    unittest.main()
