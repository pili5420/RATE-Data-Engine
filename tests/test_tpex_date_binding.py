import copy
import hashlib
import json
import os
import shutil
import unittest
from http.client import IncompleteRead
from pathlib import Path
from unittest.mock import patch

from scripts import build_production_source_bundle_from_official as builder
from scripts.bootstrap_tpex_history import TPEx_SYMBOLS
from scripts.materialize_production_history_store import materialize
from src.sources.tpex import CURRENT_DAILY_ENDPOINT, HISTORICAL_ENDPOINT
from src.sources import tpex_date_binding as binding
from tests.test_rate_production_history_materialization import APPROVED_UNIVERSE, FakeTWSEAdapter, FakeTPExAdapter


def official_history(symbol, trading_date="2026-10-02"):
    payload = {"code": symbol, "tables": [{"subtitle": symbol,
        "fields": ["Date", "Open", "High", "Low", "Close", "Trade unit", "Trade Amt.(NTD1000)"],
        "data": [["2026/10/01", "10", "12", "9", "11", "1000", "11000"],
                 [trading_date.replace("-", "/"), "11", "13", "10", "12", "1100", "13200"]]}]}
    return {"endpoint": HISTORICAL_ENDPOINT, "source_type": "OFFICIAL_PRIMARY",
        "provider": "TPEx Official OpenAPI", "raw_payload": payload,
        "content_hash": binding.digest(payload), "diagnostics": {"http_status": 200},
        "request_method": "POST", "request_params": {"code": symbol, "date": "2026/10/01", "response": "json"},
        "source_timestamp": "2026-10-05T13:25:00Z", "retrieval_timestamp": "2026-10-05T13:25:01Z"}


def current_result(raw_date="1151005"):
    return {"endpoint": CURRENT_DAILY_ENDPOINT, "content_hash": "a" * 64,
        "retrieval_timestamp": "2026-10-05T13:30:00Z",
        "raw_payload": [{"Date": raw_date, "SecuritiesCompanyCode": s, "Open": "11", "High": "13",
                         "Low": "10", "Close": "12", "TradingShares": "1100", "TransactionAmount": "13200"} for s in TPEx_SYMBOLS],
        "diagnostics": {"http_status": 200, "parse_status": "PASS", "attempt_count": 1, "fallback_used": False}}


class DateBoundTPExAdapter(FakeTPExAdapter):
    def fetch_historical_symbol(self, symbol, period):
        return official_history(symbol)


class TPExDateBindingTests(unittest.TestCase):
    def setUp(self):
        self.root = Path("artifacts/test_tpex_date_binding")
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = binding.material_path(self.root, "2026-10-02")
        self.entry = next(e for e in json.loads(Path("config/RATE_PRODUCTION_OFFICIAL_SOURCE_REGISTRY_V1.json").read_text())["datasets"] if e["dataset_id"] == "tpex_market_daily")

    def tearDown(self):
        shutil.rmtree(self.root)

    def save(self):
        material = binding.build_material("2026-10-02", {s: official_history(s) for s in TPEx_SYMBOLS}, TPEx_SYMBOLS)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(material), encoding="utf-8")
        return material

    def select(self, result):
        return binding.select_market_daily(result, trading_date="2026-10-02", history_root=self.root, symbols=TPEx_SYMBOLS)

    def test_current_exact_date_selects_current_without_history(self):
        current = current_result("1151002")
        with patch.object(binding, "load_material", side_effect=AssertionError("history must not be used")):
            result = self.select(current)
        self.assertEqual(result["market_daily_source_mode"], "CURRENT_OFFICIAL_DAILY")
        self.assertEqual(result["raw_payload"], current["raw_payload"])

    def test_historical_exact_date_selects_authoritative_material(self):
        material = self.save()
        result = self.select(current_result())
        self.assertEqual(result["market_daily_source_mode"], "DATE_BOUND_OFFICIAL_HISTORY")
        self.assertEqual(result["source_effective_date"], "2026-10-02")
        self.assertEqual(result["historical_material_hash"], material["historical_material_hash"])
        self.assertEqual(result["content_hash"], hashlib.sha256(self.path.read_bytes()).hexdigest())
        self.assertEqual(result["retrieval_timestamp"], "2026-10-05T13:25:01Z")
        self.assertFalse(result["diagnostics"]["fallback_used"])

    def test_missing_exact_date_material_fails_closed(self):
        with self.assertRaisesRegex(RuntimeError, "TPEX_DATE_BOUND_CANONICAL_MATERIAL_MISSING"):
            self.select(current_result())

    def test_exact_date_not_in_official_response_fails_closed(self):
        sources = {s: official_history(s) for s in TPEx_SYMBOLS}
        sources["6274"]["raw_payload"]["tables"][0]["data"].pop()
        with self.assertRaisesRegex(RuntimeError, "TPEX_DATE_BOUND_EXACT_DATE_MISSING"):
            binding.build_material("2026-10-02", sources, TPEx_SYMBOLS)

    def test_newer_current_row_never_relabelled_or_accepted(self):
        current = current_result()
        before = copy.deepcopy(current)
        with self.assertRaisesRegex(RuntimeError, "CANONICAL_MATERIAL_MISSING"):
            self.select(current)
        self.assertEqual(current, before)
        with self.assertRaisesRegex(RuntimeError, "TPEX_RAW_TRADING_DATE_MISMATCH"):
            builder._raw_market_row(current["raw_payload"][0], source="TPEX", trading_date="2026-10-02")

    def test_run_37316684164_structural_replay_normalizes_five_symbols(self):
        self.save()
        with patch.dict(os.environ, {"RATE_OFFICIAL_HISTORY_STORE_ROOT": str(self.root)}), patch.object(builder.LiveTPExAdapter, "fetch_daily", return_value=current_result()):
            fetched = builder.RegistryDatasetAdapter(self.entry, trading_date="2026-10-02").fetch()
            result = builder._normalize_dataset_entry(self.entry, fetched, "2026-10-02")
        self.assertEqual(result["normalization_status"], "PASS")
        self.assertCountEqual([r["symbol"] for r in result["normalized_records"]], ["3081", "3227", "6187", "6274", "6510"])
        self.assertEqual(result["endpoint"], HISTORICAL_ENDPOINT)
        self.assertTrue(all(r["trading_date"] == "2026-10-02" for r in result["normalized_records"]))
        self.assertNotIn("NO_NORMALIZED_RECORDS", str(result.get("blocking_reason")))
        self.assertEqual(result["current_official_date"], "2026-10-05")

    def test_rolling_technical_receives_all_30_market_identities(self):
        self.save()
        fetched = self.select(current_result())
        fetched["status"] = "PASS"
        tpex = builder._normalize_dataset_entry(self.entry, fetched, "2026-10-02")
        twse_symbols = [s for s in APPROVED_UNIVERSE if s not in TPEx_SYMBOLS]
        twse = {"domain": "market_daily", "source": "TWSE", "normalization_status": "PASS", "normalized_records": [
            {"symbol": s, "raw_market_latest": {"symbol": s, "source": "TWSE", "trade_date": "2026-10-02"}} for s in twse_symbols]}
        scores = [{"symbol": s, "technical_features": {key: 1 for key in builder.TECHNICAL_REQUIRED}} for s in APPROVED_UNIVERSE]
        with patch.object(builder, "_is_test_context", return_value=False), patch.object(builder, "_fetch_official_stock_history", return_value=[]) as history, patch.object(builder, "_fetch_official_benchmark_history", return_value=[]), patch.object(builder, "compute_scores", return_value=scores):
            result = builder._build_official_rolling_technical_source(universe_binding={"validation_status": "PASS", "expected_universe": APPROVED_UNIVERSE}, normalized_sources=[twse, tpex], trading_date="2026-10-02")
        self.assertEqual(history.call_count, 30)
        self.assertEqual(len(result["normalized_records"]), 30)
        self.assertCountEqual([call.args[0] for call in history.call_args_list], APPROVED_UNIVERSE)

    def test_invalid_material_hash_fails_closed(self):
        material = self.save()
        material["historical_material_hash"] = "0" * 64
        self.path.write_text(json.dumps(material), encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "MATERIAL_BINDING_INVALID"):
            self.select(current_result())

    def test_invalid_provenance_and_source_hash_fail_closed(self):
        for key, value in (("endpoint", "https://example.invalid"), ("content_hash", "invalid"), ("source_type", "MANUAL"), ("retrieval_timestamp", None)):
            with self.subTest(key=key):
                sources = {s: official_history(s) for s in TPEx_SYMBOLS}
                sources["6274"][key] = value
                with self.assertRaises((RuntimeError, ValueError)):
                    binding.build_material("2026-10-02", sources, TPEx_SYMBOLS)
        material = self.save()
        material["entries"][0]["source_payload_hash"] = "0" * 64
        self.rehash(material)
        with self.assertRaisesRegex(RuntimeError, "SOURCE_HASH_INVALID"):
            self.select(current_result())

    def rehash(self, material):
        core = {k: v for k, v in material.items() if k not in ("historical_material_hash", "historical_material_id")}
        material["historical_material_hash"] = binding.digest(core)
        material["historical_material_id"] = "rate-tpex-date-bound-" + binding.digest(core)[:24]
        self.path.write_text(json.dumps(material), encoding="utf-8")

    def test_modified_record_cannot_override_official_evidence(self):
        material = self.save()
        material["entries"][0]["record"]["close"] = 999
        self.rehash(material)
        with self.assertRaisesRegex(RuntimeError, "RECORD_BINDING_INVALID"):
            self.select(current_result())

    def test_materializer_preserves_prior_history_and_adds_exact_date_evidence(self):
        contract = self.root / "contract.json"
        contract.write_text(json.dumps({"artifact": "RATE_PRODUCTION_UNIVERSE_CONTRACT", "approved_universe": APPROVED_UNIVERSE, "required_count": 30, "validation_status": "PASS"}))
        result = materialize(trading_date="2026-10-02", universe_contract=contract, history_root=self.root, evidence_output=self.root / "evidence.json", max_months=1, minimum_sessions=1, max_runtime_seconds=30, twse_adapter=FakeTWSEAdapter(), tpex_adapter=DateBoundTPExAdapter())
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["symbols_materialized"], 30)
        self.assertEqual(result["date_bound_market_daily"]["validation_status"], "PASS")
        self.assertEqual(result["date_bound_market_daily"]["historical_material_hash"], self.select(current_result())["historical_material_hash"])
        for symbol in APPROVED_UNIVERSE:
            rows = json.loads((self.root / "market_daily" / (symbol + ".json")).read_text())
            self.assertTrue(all(r["trade_date"] < "2026-10-02" for r in rows))

    def test_blocked_path_never_writes_latest_or_live_state(self):
        files = [self.root / name for name in ("RATE_PRODUCTION_SOURCE_BUNDLE_LATEST.json", "RATE_PRODUCTION_STATE_LATEST.json", "portfolio.json", "ledger.json")]
        for file in files:
            file.write_bytes(b"unchanged")
        with patch.dict(os.environ, {"RATE_OFFICIAL_HISTORY_STORE_ROOT": str(self.root)}), patch.object(builder.LiveTPExAdapter, "fetch_daily", return_value=current_result()), patch.object(builder, "atomic_write_json") as writer:
            result = builder.RegistryDatasetAdapter(self.entry, trading_date="2026-10-02").fetch()
        self.assertEqual(result["status"], "BLOCKED")
        writer.assert_not_called()
        self.assertTrue(all(file.read_bytes() == b"unchanged" for file in files))

    def test_transport_failure_cannot_switch_to_history(self):
        self.save()
        with patch.object(builder.LiveTPExAdapter, "fetch_daily", side_effect=RuntimeError("transport failed")), patch.object(binding, "load_material") as loader:
            result = builder.RegistryDatasetAdapter(self.entry, trading_date="2026-10-02").fetch()
        self.assertEqual(result["status"], "BLOCKED")
        loader.assert_not_called()

    def test_run_37327588428_historical_eod_never_probes_current(self):
        self.save()
        failures = [IncompleteRead(b"partial"), IncompleteRead(b"partial"), TimeoutError()]
        with patch.dict(os.environ, {"RATE_OFFICIAL_HISTORY_STORE_ROOT": str(self.root)}), patch.object(builder.LiveTPExAdapter, "fetch_daily", side_effect=failures) as current:
            fetched = builder.RegistryDatasetAdapter(self.entry, trading_date="2026-10-02", cadence="19:30").fetch()
            normalized = builder._normalize_dataset_entry(self.entry, fetched, "2026-10-02")
        current.assert_not_called()
        self.assertEqual(fetched["status"], "PASS")
        self.assertEqual(fetched["market_daily_source_mode"], "DATE_BOUND_OFFICIAL_HISTORY")
        self.assertEqual(normalized["normalization_status"], "PASS")
        self.assertCountEqual([r["symbol"] for r in normalized["normalized_records"]], TPEx_SYMBOLS)
        self.assertNotIn("current_official_probe", fetched)
        self.assertFalse(fetched["fallback_used"])
        twse = {"domain": "market_daily", "source": "TWSE", "normalization_status": "PASS", "normalized_records": [
            {"symbol": s, "raw_market_latest": {"symbol": s, "source": "TWSE", "trade_date": "2026-10-02"}}
            for s in APPROVED_UNIVERSE if s not in TPEx_SYMBOLS]}
        scores = [{"symbol": s, "technical_features": {key: 1 for key in builder.TECHNICAL_REQUIRED}} for s in APPROVED_UNIVERSE]
        with patch.object(builder, "_is_test_context", return_value=False), patch.object(builder, "_fetch_official_stock_history", return_value=[]) as history, patch.object(builder, "_fetch_official_benchmark_history", return_value=[]), patch.object(builder, "compute_scores", return_value=scores):
            rolling = builder._build_official_rolling_technical_source(
                universe_binding={"validation_status": "PASS", "expected_universe": APPROVED_UNIVERSE},
                normalized_sources=[twse, normalized], trading_date="2026-10-02")
        self.assertEqual(rolling["status"], "PASS")
        self.assertEqual(history.call_count, 30)
        self.assertEqual(len(rolling["normalized_records"]), 30)
        self.assertCountEqual([r["symbol"] for r in rolling["normalized_records"]], APPROVED_UNIVERSE)

    def test_historical_eod_invalid_material_never_switches_to_current(self):
        for defect in ("missing", "corrupt", "validation", "identity", "hash", "provenance"):
            with self.subTest(defect=defect):
                material = self.save()
                if defect == "missing":
                    self.path.unlink()
                elif defect == "corrupt":
                    self.path.write_text('{"partial":')
                else:
                    if defect == "validation":
                        material["validation_status"] = "FAIL"
                    elif defect == "identity":
                        material["requested_trading_date"] = "2026-10-05"
                    elif defect == "hash":
                        material["entries"][0]["source_payload_hash"] = "0" * 64
                    else:
                        material["entries"][0]["source_evidence"]["endpoint"] = "https://example.invalid"
                    self.rehash(material)
                with patch.dict(os.environ, {"RATE_OFFICIAL_HISTORY_STORE_ROOT": str(self.root)}), patch.object(builder.LiveTPExAdapter, "fetch_daily") as current, patch.object(builder, "atomic_write_json") as writer:
                    fetched = builder.RegistryDatasetAdapter(self.entry, trading_date="2026-10-02", cadence="19:30").fetch()
                current.assert_not_called()
                writer.assert_not_called()
                self.assertEqual(fetched["status"], "BLOCKED")
                self.assertIn("TPEX_MARKET_DAILY_DATE_BINDING_FAILED", fetched["blocking_reason"])
                self.assertFalse(fetched["fallback_used"])

    def test_current_day_eod_without_historical_target_keeps_current_semantics(self):
        with patch.dict(os.environ, {"RATE_OFFICIAL_HISTORY_STORE_ROOT": str(self.root)}), patch.object(builder, "datetime") as clock, patch.object(builder.LiveTPExAdapter, "fetch_daily", return_value=current_result("1151002")) as current:
            from datetime import date
            clock.now.return_value.date.return_value = date(2026, 10, 2)
            fetched = builder.RegistryDatasetAdapter(self.entry, trading_date="2026-10-02", cadence="19:30").fetch()
        current.assert_called_once()
        self.assertEqual(fetched["status"], "PASS")
        self.assertEqual(fetched["market_daily_source_mode"], "CURRENT_OFFICIAL_DAILY")

    def test_trading_metadata_keeps_its_independent_official_acquisition(self):
        self.save()
        entry = next(e for e in json.loads(Path("config/RATE_PRODUCTION_OFFICIAL_SOURCE_REGISTRY_V1.json").read_text())["datasets"]
                     if e["parser"] == "TPEX_TRADING_METADATA_V1")
        with patch.dict(os.environ, {"RATE_OFFICIAL_HISTORY_STORE_ROOT": str(self.root)}), patch.object(builder.LiveTPExAdapter, "fetch_daily", return_value=current_result()) as current:
            fetched = builder.RegistryDatasetAdapter(entry, trading_date="2026-10-02", cadence="19:30").fetch()
        current.assert_called_once()
        self.assertEqual(fetched["status"], "PASS")
        self.assertNotIn("market_daily_source_mode", fetched)

    def test_corrupted_or_validation_fail_material_fails_closed(self):
        self.save()
        self.path.write_text('{"truncated":', encoding="utf-8")
        with self.assertRaises(binding.TPExDateBindingError):
            self.select(current_result())
        material = self.save()
        material["validation_status"] = "FAIL"
        self.rehash(material)
        with self.assertRaisesRegex(binding.TPExDateBindingError, "MATERIAL_BINDING_INVALID"):
            self.select(current_result())

    def test_failed_exact_date_materialization_cannot_reuse_old_pass_material(self):
        self.save()
        contract = self.root / "contract.json"
        contract.write_text(json.dumps({"artifact": "RATE_PRODUCTION_UNIVERSE_CONTRACT", "approved_universe": APPROVED_UNIVERSE, "required_count": 30, "validation_status": "PASS"}))
        result = materialize(trading_date="2026-10-02", universe_contract=contract, history_root=self.root, evidence_output=self.root / "evidence.json", max_months=1, minimum_sessions=1, max_runtime_seconds=30, twse_adapter=FakeTWSEAdapter(), tpex_adapter=FakeTPExAdapter())
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["date_bound_market_daily"]["validation_status"], "FAIL_CLOSED")
        with self.assertRaisesRegex(binding.TPExDateBindingError, "MATERIAL_BINDING_INVALID"):
            self.select(current_result())
