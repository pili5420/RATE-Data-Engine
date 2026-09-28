from __future__ import annotations

import json
import shutil
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.resolve_production_runtime_context import resolve_context
from scripts.validate_production_scheduler_safety import validate
from scripts.publish_production_state_latest import publish_state
from scripts.seed_live_production_state import seed
from scripts.publish_production_source_bundle_latest import load_json, publish_latest, validate_production_source_bundle
from scripts.build_production_source_bundle_from_official import build_bundle

WORKFLOWS = [
    Path('.github/workflows/rate_production_0730_scheduler.yml'),
    Path('.github/workflows/rate_production_0930_scheduler.yml'),
    Path('.github/workflows/rate_production_1200_scheduler.yml'),
    Path('.github/workflows/rate_production_1930_scheduler.yml'),
]

class ProductionSchedulerChangeControlTests(unittest.TestCase):
    def _source_evidence(self, path: Path):
        path.write_text(json.dumps({
            "artifact": "RATE_CER079_END_OF_DAY_CLOSURE_EVIDENCE",
            "validation_status": "PASS",
            "trading_date": "2026-09-18",
            "final_cadence_for_trading_date": "19:30",
            "final_state_id": "rate-state-656e460995324fb4a3eb7b30",
            "final_state_hash": "656e460995324fb4a3eb7b3033b754752997c8cb761d414083a2148eb150b5c7",
            "state_ids": {"12:00": "rate-state-c227b116309d50b2967ed12b"},
        }), encoding="utf-8")

    def _technical_source(self, seed: int = 1):
        return {"technical_features": {key: float(seed + index) for index, key in enumerate(("PT", "PV", "MO", "RS", "H5", "H20", "H60", "H120", "RelativeStrength", "Liquidity"))}}

    def _official_dataset(self, trading_date: str = "2026-09-21", count: int = 30, malformed_join: bool = False):
        symbols = [str(1000 + idx) for idx in range(count)]
        production_sources = {symbol: self._technical_source(idx + 1) for idx, symbol in enumerate(symbols)}
        if malformed_join and symbols:
            production_sources.pop(symbols[-1])
        dataset_rows = [{"symbol": symbol, "validation_status": "PASS", "record_count": 1, "LH": 50.0, "fundamental_score": 60.0} for symbol in symbols]
        return {
            "schema_version": "RATE-OFFICIAL-NORMALIZED-SOURCE-V1",
            "trading_date": trading_date,
            "universe": symbols,
            "production_sources": production_sources,
            "datasets": {
                "market_daily": {"validation_status": "PASS", "record_count": count, "rows": [{"symbol": symbol} for symbol in symbols]},
                "market_intraday": {"validation_status": "PASS", "record_count": count, "rows": [{"symbol": symbol} for symbol in symbols]},
                "institutional": {"validation_status": "PASS", "record_count": count, "rows": [{"symbol": symbol} for symbol in symbols]},
                "large_holder": {"validation_status": "PASS", "record_count": count, "rows": dataset_rows},
                "fundamental": {"validation_status": "PASS", "record_count": count, "rows": dataset_rows},
                "benchmark": {"validation_status": "PASS", "record_count": 1, "rows": [{"symbol": "TAIEX"}]},
                "trading_metadata": {"validation_status": "PASS", "trading_date": trading_date, "record_count": 1},
            },
        }

    def _write_official_dataset(self, root: Path, dataset: dict) -> str:
        path = root / "official_source.json"
        path.write_text(json.dumps(dataset, ensure_ascii=False), encoding="utf-8")
        return path.resolve().as_uri()

    def _persist_evidence(self, root: Path, *, artifact: str, trading_date: str, cadence: str, current_state_id: str, current_state_hash: str, previous_state_id: str | None):
        path = root / f"{trading_date}-{cadence.replace(':', '')}.json"
        path.write_text(json.dumps({
            "artifact": artifact,
            "validation_status": "PASS",
            "current_state_id": current_state_id,
            "current_state_hash": current_state_hash,
            "previous_state_id": previous_state_id,
            "persist_result": {
                "status": "PERSISTED",
                "state_entry": {
                    "current_state_id": current_state_id,
                    "decision_payload_hash": current_state_hash,
                    "previous_state_id": previous_state_id,
                    "trading_date": trading_date,
                    "cadence": cadence,
                },
            },
        }), encoding="utf-8")
        return path

    def test_scheduler_safety_validation_passes(self):
        result = validate()
        self.assertEqual(result['validation_status'], 'PASS')
        self.assertEqual(result['dynamic_trading_date_resolution'], 'PASS')
        self.assertEqual(result['live_previous_state_resolver'], 'PASS')
        self.assertEqual(result['persistent_state_no_reset'], 'PASS')
        self.assertEqual(result['production_persistent_state_reset_count'], 0)
        self.assertEqual(result['cer081_read_only'], 'PASS')
        self.assertEqual(result['controlled_live_state_bootstrap_seed'], 'PASS')
        self.assertEqual(result['one_time_live_state_bootstrap_seed'], 'PASS')
        self.assertEqual(result['official_source_ingestion'], 'PASS')
        self.assertEqual(result['holiday_source_snapshot'], 'PASS')
        self.assertEqual(result['cer073_role'], 'AUDIT_ONLY_NOT_RECURRING_SOURCE')
        self.assertEqual(result['push_workflow_dispatch_not_soak_evidence'], 'PASS')

    def test_no_historical_acceptance_date_fallback_or_fixed_main_guard(self):
        for path in WORKFLOWS:
            text = path.read_text(encoding='utf-8')
            self.assertNotIn("inputs.trading_date || '2026-09-18'", text)
            self.assertNotIn('default: "2026-09-18"', text)
            self.assertNotIn('beae3ed542888cc647d64bbcecab7d907a7744aa', text)
            self.assertNotIn('--reset-state-root', text)
            self.assertNotRegex(text, r'RATE_CER07[45678].*ARTIFACT_ID')
            self.assertNotIn('artifacts/accepted/cer073/source_bundle', text)
            self.assertIn('build_production_source_bundle_from_official.py', text)

    def test_official_source_normalized_dataset_builds_complete_production_bundle(self):
        root = Path("artifacts/test-production-scheduler-change-control")
        try:
            shutil.rmtree(root, ignore_errors=True)
            root.mkdir(parents=True, exist_ok=True)
            source_url = self._write_official_dataset(root, self._official_dataset())
            output = root / "RATE_PRODUCTION_SOURCE_BUNDLE.json"
            evidence = root / "RATE_PRODUCTION_OFFICIAL_SOURCE_INGESTION_EVIDENCE.json"
            result = build_bundle(rate_source_url=source_url, trading_date="2026-09-21", cadence="09:30", output=output, evidence_output=evidence)
            bundle = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(result["validation_status"], "PASS")
            self.assertEqual(bundle["validation_status"], "PASS")
            self.assertEqual(bundle["source_bundle_validation"], "PASS")
            self.assertEqual(bundle["coverage"], "30/30")
            self.assertTrue(bundle["input_snapshot_id"])
            self.assertEqual(len(bundle["records"]), 30)
            self.assertEqual(len(bundle["decision_records"]), 30)
            self.assertEqual(bundle["trading_date"], "2026-09-21")
            self.assertEqual(bundle["cadence"], "09:30")
            self.assertEqual(bundle["source_provenance"]["source"], "RATE_OFFICIAL_TW_MARKET_DATA_SSOT")
            self.assertEqual(bundle["source_provenance"]["fixture_fallback"], "FORBIDDEN")
            self.assertEqual(bundle["source_provenance"]["historical_acceptance_bundle_fallback"], "FORBIDDEN")
            self.assertEqual(bundle["source_provenance"]["cer073_live_fallback"], "FORBIDDEN")
            self.assertEqual(bundle["source_provenance"]["stale_snapshot_fallback"], "FORBIDDEN")
            self.assertEqual(bundle["source_provenance"]["local_desktop_dependency"], "FORBIDDEN")
            transform = bundle["official_source_transformation"]
            self.assertEqual(transform["source_retrieval"], "PASS")
            self.assertEqual(transform["normalization"], "PASS")
            self.assertEqual(transform["symbol_mapping"], "PASS")
            self.assertEqual(transform["required_dataset_joins"], "PASS")
            self.assertEqual(bundle["required_dataset_gate"]["required_datasets"]["large_holder"], "PASS")
            self.assertEqual(bundle["required_dataset_gate"]["required_datasets"]["fundamental"], "PASS")
            self.assertEqual(bundle["required_dataset_gate"]["required_datasets"]["trading_metadata"], "PASS")
            self.assertEqual(transform["decision_record_construction"], "PASS")
            self.assertEqual(transform["decision_record_coverage"], "30/30")
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_official_source_missing_malformed_or_insufficient_coverage_fails_closed(self):
        root = Path("artifacts/test-production-scheduler-change-control")
        try:
            shutil.rmtree(root, ignore_errors=True)
            root.mkdir(parents=True, exist_ok=True)
            cases = {
                "missing": {},
                "malformed_join": self._official_dataset(malformed_join=True),
                "insufficient_coverage": self._official_dataset(count=29),
                "missing_large_holder": {**self._official_dataset(), "datasets": {k: v for k, v in self._official_dataset()["datasets"].items() if k != "large_holder"}},
            }
            for name, dataset in cases.items():
                case_root = root / name
                case_root.mkdir(parents=True, exist_ok=True)
                source_url = self._write_official_dataset(case_root, dataset)
                output = case_root / "bundle.json"
                evidence = case_root / "evidence.json"
                result = build_bundle(rate_source_url=source_url, trading_date="2026-09-21", cadence="12:00", output=output, evidence_output=evidence)
                bundle = json.loads(output.read_text(encoding="utf-8"))
                self.assertEqual(result["validation_status"], "BLOCKED", name)
                self.assertEqual(bundle["validation_status"], "BLOCKED", name)
                self.assertEqual(bundle["source_bundle_validation"], "BLOCKED", name)
                self.assertEqual(bundle["decision_record_coverage"]["status"], "FAIL", name)
                self.assertEqual(len(bundle["decision_records"]), 0, name)
                self.assertIsNone(bundle["input_snapshot_id"], name)
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_holiday_calendar_gate_builds_legal_snapshot_and_latest(self):
        root = Path("artifacts/test-production-scheduler-change-control")
        try:
            shutil.rmtree(root, ignore_errors=True)
            root.mkdir(parents=True, exist_ok=True)
            output = root / "holiday_bundle.json"
            evidence = root / "holiday_evidence.json"
            result = build_bundle(rate_source_url="", trading_date="2026-09-28", cadence="07:30", output=output, evidence_output=evidence)
            bundle = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(result["validation_status"], "PASS")
            self.assertEqual(bundle["snapshot_type"], "HOLIDAY")
            self.assertTrue(bundle["input_snapshot_id"])
            self.assertEqual(bundle["trading_calendar_gate"]["status"], "PASS")
            self.assertFalse(bundle["trading_calendar_gate"]["is_trading_day"])
            self.assertEqual(bundle["required_dataset_gate"]["required_datasets"]["trading_metadata"], "PASS")
            published = publish_latest(source_bundle_path=output, trading_date="2026-09-28", cadence="07:30", artifacts_root=root, workflow_run_id="run-holiday", workflow_job_id="job-holiday")
            self.assertEqual(published["publish_result"], "PASS")
            latest = load_json(root / "RATE_PRODUCTION_SOURCE_BUNDLE_LATEST.json")
            self.assertEqual(latest["snapshot_type"], "HOLIDAY")
            self.assertEqual(latest["input_snapshot_id"], bundle["input_snapshot_id"])
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_schedule_resolves_dynamic_taiwan_trading_date_and_blocks_missing_live_predecessor(self):
        root = Path("artifacts/test-production-scheduler-change-control")
        try:
            shutil.rmtree(root, ignore_errors=True)
            root.mkdir(parents=True, exist_ok=True)
            context = resolve_context(cadence='09:30', event_name='schedule', dispatch_trading_date=None, state_root=root)
            self.assertEqual(context['trading_date_resolution'], 'DYNAMIC_TAIWAN_TRADING_DATE')
            self.assertNotEqual(context['trading_date'], '2026-09-18')
            self.assertEqual(context['previous_state_resolution'], 'LIVE_PRODUCTION_STATE_STORE')
            if context['runtime_mode'] == 'RUN':
                self.assertEqual(context['validation_status'], 'BLOCKED')
                self.assertEqual(context['blocking_reason'], 'LIVE_PREVIOUS_PRODUCTION_STATE_MISSING')
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_seed_live_state_from_cer079_eod_is_idempotent_and_unblocks_next_0730_resolver(self):
        root = Path("artifacts/test-production-scheduler-change-control")
        try:
            shutil.rmtree(root, ignore_errors=True)
            root.mkdir(parents=True, exist_ok=True)
            src = root / "cer079_eod.json"
            self._source_evidence(src)
            first = seed(source_evidence_path=src, artifacts_root=root)
            second = seed(source_evidence_path=src, artifacts_root=root)
            self.assertEqual(first["validation_status"], "PASS")
            self.assertEqual(second["idempotency_result"], "BOOTSTRAP_NOT_REQUIRED_EXISTING_LIVE_STATE")
            context = resolve_context(cadence="07:30", event_name="workflow_dispatch", dispatch_trading_date="2026-09-21", state_root=root / "production_state")
            self.assertEqual(context["previous_state_resolution"], "LIVE_PRODUCTION_STATE_STORE")
            self.assertEqual(context["validation_status"], "PASS")
            self.assertNotEqual(context.get("blocking_reason"), "LIVE_PREVIOUS_PRODUCTION_STATE_MISSING")
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_cer079_seed_day1_full_chain_day2_0730_skips_bootstrap_and_uses_day1_1930(self):
        root = Path("artifacts/test-production-scheduler-change-control")
        try:
            shutil.rmtree(root, ignore_errors=True)
            root.mkdir(parents=True, exist_ok=True)
            src = root / "cer079_eod.json"
            self._source_evidence(src)
            first = seed(source_evidence_path=src, artifacts_root=root)
            self.assertEqual(first["idempotency_result"], "SEEDED_NEW_RECORD")
            chain = [
                ("RATE_CER075_PERSIST_RESULT_EVIDENCE", "07:30", "rate-state-day1-0730", "hash-day1-0730", "rate-state-656e460995324fb4a3eb7b30"),
                ("RATE_CER076_PERSIST_RESULT_EVIDENCE", "09:30", "rate-state-day1-0930", "hash-day1-0930", "rate-state-day1-0730"),
                ("RATE_CER077_PERSIST_RESULT_EVIDENCE", "12:00", "rate-state-day1-1200", "hash-day1-1200", "rate-state-day1-0930"),
                ("RATE_CER078_PERSIST_RESULT_EVIDENCE", "19:30", "rate-state-day1-1930", "hash-day1-1930", "rate-state-day1-1200"),
            ]
            for artifact, cadence, state_id, state_hash, previous in chain:
                evidence = self._persist_evidence(root, artifact=artifact, trading_date="2026-09-21", cadence=cadence, current_state_id=state_id, current_state_hash=state_hash, previous_state_id=previous)
                published = publish_state(persist_evidence_path=evidence, trading_date="2026-09-21", cadence=cadence, artifacts_root=root)
                self.assertEqual(published["validation_status"], "PASS")
            latest_before = json.loads((root / "RATE_PRODUCTION_STATE_LATEST.json").read_text(encoding="utf-8"))
            second_day_seed = seed(source_evidence_path=src, artifacts_root=root)
            latest_after = json.loads((root / "RATE_PRODUCTION_STATE_LATEST.json").read_text(encoding="utf-8"))
            self.assertEqual(second_day_seed["idempotency_result"], "BOOTSTRAP_NOT_REQUIRED_EXISTING_LIVE_STATE")
            self.assertEqual(latest_after, latest_before)
            self.assertEqual(latest_after["current_state_id"], "rate-state-day1-1930")
            context = resolve_context(cadence="07:30", event_name="workflow_dispatch", dispatch_trading_date="2026-09-22", state_root=root / "production_state")
            self.assertEqual(context["validation_status"], "PASS")
            self.assertEqual(context["previous_state_resolution"], "LIVE_PRODUCTION_STATE_STORE")
            self.assertEqual(context["previous_state_evidence_path"], "artifacts/test-production-scheduler-change-control/production_state/live/2026-09-21/1930/RATE_PRODUCTION_PERSIST_RESULT_EVIDENCE.json")
            self.assertEqual(context["production_persistent_state_reset_count"], 0)
            self.assertFalse(second_day_seed["persistent_state_reset"])
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_seed_incompatible_live_state_fails_closed(self):
        root = Path("artifacts/test-production-scheduler-change-control")
        try:
            shutil.rmtree(root, ignore_errors=True)
            dest = root / "production_state/live/2026-09-18/1930"
            dest.mkdir(parents=True, exist_ok=True)
            (dest / "RATE_PRODUCTION_PERSIST_RESULT_EVIDENCE.json").write_text(json.dumps({"current_state_id": "other", "current_state_hash": "other"}), encoding="utf-8")
            src = root / "cer079_eod.json"
            src.write_text(json.dumps({
                "artifact": "RATE_CER079_END_OF_DAY_CLOSURE_EVIDENCE",
                "validation_status": "PASS",
                "trading_date": "2026-09-18",
                "final_cadence_for_trading_date": "19:30",
                "final_state_id": "rate-state-656e460995324fb4a3eb7b30",
                "final_state_hash": "656e460995324fb4a3eb7b3033b754752997c8cb761d414083a2148eb150b5c7",
            }), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "INCOMPATIBLE_LIVE_SEED_ALREADY_EXISTS"):
                seed(source_evidence_path=src, artifacts_root=root)
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def _fresh_bundle(self, retrieval_timestamp: str, trading_date: str = "2026-09-21") -> dict:
        records = [{"symbol": str(1000 + idx)} for idx in range(30)]
        return {
            "validation_status": "PASS",
            "source_bundle_validation": "PASS",
            "schema_version": "RATE-PRODUCTION-SOURCE-BUNDLE-V1",
            "trading_date": trading_date,
            "source_provenance": {"source": "RATE_OFFICIAL_TW_MARKET_DATA_SSOT", "retrieval_timestamp": retrieval_timestamp},
            "coverage": "30/30",
            "decision_records": records,
            "records": records,
        }

    def test_stale_future_and_trading_date_mismatch_source_data_rejected(self):
        now = datetime.now(timezone.utc)
        stale = self._fresh_bundle((now - timedelta(days=1)).isoformat().replace("+00:00", "Z"))
        future = self._fresh_bundle((now + timedelta(minutes=5)).isoformat().replace("+00:00", "Z"))
        mismatch = self._fresh_bundle(now.isoformat().replace("+00:00", "Z"), trading_date="2026-09-20")
        self.assertEqual(validate_production_source_bundle(stale, trading_date="2026-09-21", cadence="09:30")["validation_status"], "FAIL")
        self.assertEqual(validate_production_source_bundle(future, trading_date="2026-09-21", cadence="09:30")["validation_status"], "FAIL")
        self.assertEqual(validate_production_source_bundle(mismatch, trading_date="2026-09-21", cadence="09:30")["validation_status"], "FAIL")

    def test_non_trading_day_noop_does_not_require_predecessor(self):
        root = Path("artifacts/test-production-scheduler-change-control")
        try:
            shutil.rmtree(root, ignore_errors=True)
            root.mkdir(parents=True, exist_ok=True)
            context = resolve_context(cadence='07:30', event_name='workflow_dispatch', dispatch_trading_date='2026-09-28', state_root=root)
            self.assertEqual(context['runtime_mode'], 'NOOP_NON_TRADING_DAY')
            self.assertEqual(context['validation_status'], 'PASS')
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_live_state_publish_requires_pass_and_writes_live_pointer(self):
        root = Path("artifacts/test-production-scheduler-change-control")
        try:
            shutil.rmtree(root, ignore_errors=True)
            root.mkdir(parents=True, exist_ok=True)
            evidence = root / 'persist.json'
            evidence.write_text(json.dumps({
                'artifact': 'RATE_CER076_PERSIST_RESULT_EVIDENCE',
                'validation_status': 'PASS',
                'current_state_id': 'rate-state-x',
                'current_state_hash': 'hash-x',
                'previous_state_id': 'rate-state-prev',
                'persist_result': {'status': 'PERSISTED', 'state_entry': {'current_state_id': 'rate-state-x', 'decision_payload_hash': 'hash-x', 'trading_date': '2026-09-29', 'cadence': '09:30'}}
            }), encoding='utf-8')
            result = publish_state(persist_evidence_path=evidence, trading_date='2026-09-29', cadence='09:30', artifacts_root=root)
            self.assertEqual(result['validation_status'], 'PASS')
            self.assertTrue((root / 'production_state/live/2026-09-29/0930/RATE_PRODUCTION_PERSIST_RESULT_EVIDENCE.json').exists())
            latest = json.loads((root / 'RATE_PRODUCTION_STATE_LATEST.json').read_text(encoding='utf-8'))
            self.assertEqual(latest['current_state_id'], 'rate-state-x')
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_live_state_publish_blocks_wrong_date_without_writing_latest(self):
        root = Path("artifacts/test-production-scheduler-change-control")
        try:
            shutil.rmtree(root, ignore_errors=True)
            root.mkdir(parents=True, exist_ok=True)
            evidence = root / 'persist.json'
            evidence.write_text(json.dumps({
                'artifact': 'RATE_CER077_PERSIST_RESULT_EVIDENCE',
                'validation_status': 'PASS',
                'persist_result': {'status': 'PERSISTED', 'state_entry': {'trading_date': '2026-09-29', 'cadence': '12:00'}}
            }), encoding='utf-8')
            result = publish_state(persist_evidence_path=evidence, trading_date='2026-09-30', cadence='12:00', artifacts_root=root)
            self.assertEqual(result['validation_status'], 'BLOCKED')
            self.assertFalse((root / 'RATE_PRODUCTION_STATE_LATEST.json').exists())
        finally:
            shutil.rmtree(root, ignore_errors=True)

if __name__ == '__main__':
    unittest.main()


