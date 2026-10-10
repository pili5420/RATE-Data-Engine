"""SYNTHETIC ONLY. No official requests or Production mutations."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from src import public_official_partial_valid as p
from src.cer074_acceptance import atomic_write_json, sha256, strip_runtime
from src.production_live_state import CADENCE_DIR, PERSIST_NAME, STATE_NAME, load_live_state, read_object, validate_material
from scripts.publish_production_state_latest import publish_state
from scripts.resolve_production_runtime_context import resolve_context, _previous_legal_trading_day
from scripts.publish_production_source_bundle_latest import validate_production_source_bundle
from tests import test_rate_soak_005 as soak_support


class PublicOfficialPartialValidTests(unittest.TestCase):
    def setUp(self):
        self.support = soak_support.RateSoak005Tests()
        self.support.setUp()
        self.addCleanup(self.support.doCleanups)
        self.root, self.artifacts, self.runtime = self.support.root, self.support.artifacts, self.support.runtime
        self.day = "2026-10-09"
        self.previous, self.previous_dir = self.support.install_test_predecessor(self.day, "07:30")
        self.predecessor = self.previous_dir / PERSIST_NAME
        self.calls = []

    def fetch(self, endpoint):
        self.calls.append(endpoint)
        payload = [{"synthetic_only": True, "Date": _previous_legal_trading_day(self.day),
            "Code": "TEST", "SecuritiesCompanyCode": "TEST", "公司代號": "TEST", "IndexName": "TAIEX",
            "ClosingIndex": "1000", "ClosingPrice": "100", "Close": "100", "TradeVolume": "1000",
            "資料年月": "11509", "營業收入-當月營收": "100000", "出表日期": "1151009"}]
        return {"raw_bytes": json.dumps(payload, ensure_ascii=False).encode(), "http_status": 200,
            "final_url": endpoint, "retrieval_timestamp": p.now()}

    def bundle(self, cadence="09:30", fetcher=None):
        target = self.root / cadence.replace(":", "") / "public.json"
        p.acquire(trading_date=self.day, cadence=cadence, output=target, evidence_output=target.parent / "acquisition.json",
            fetcher=fetcher or self.fetch)
        return target, read_object(target)

    def execute(self, cadence="09:30", previous=None, source=None):
        source = source or self.bundle(cadence)[0]
        return p.run(source_bundle=source, previous_evidence=previous or self.predecessor,
            output_dir=self.root / ("out" + cadence.replace(":", "")), state_root=self.runtime, cadence=cadence)

    def publish(self, cadence, persist):
        evidence = self.root / ("out" + cadence.replace(":", "")) / (p.ARTIFACTS[cadence] + ".json")
        with patch.dict(os.environ, {"GITHUB_EVENT_NAME": "schedule", "GITHUB_REF": "refs/heads/main"}):
            p.publish_report(source_bundle_path=self.root / cadence.replace(":", "") / "public.json",
                trading_date=self.day, cadence=cadence, artifacts_root=self.artifacts,
                workflow_run_id="301", workflow_job_id="401", evidence_output=self.root / (cadence.replace(":", "") + "-report.json"))
        return publish_state(persist_evidence_path=evidence, trading_date=self.day, cadence=cadence,
            artifacts_root=self.artifacts, state_root=self.runtime, workflow_run_id="301", workflow_job_id="401",
            event_name="schedule", ref="refs/heads/main", commit_sha="c" * 40)

    def midnight_state(self, cadence, persist):
        return read_object(self.runtime / "decision_state" / CADENCE_DIR[cadence] / (persist["current_state_id"] + ".json"))["decision_state"]

    def mutate_source(self, mutation):
        def fetcher(endpoint):
            result = self.fetch(endpoint)
            payload = json.loads(result["raw_bytes"])
            mutation(payload)
            result["raw_bytes"] = json.dumps(payload, ensure_ascii=False).encode()
            return result
        return fetcher

    def test_public_pass_intraday_blocked_partial_valid(self):
        persist = self.execute()
        state = self.midnight_state("09:30", persist)
        self.assertEqual(state["decision"]["public_official_evidence_gate"], "PASS")
        self.assertEqual(state["decision"]["market_intraday_price_gate"], "BLOCKED_EXTERNAL")
        self.assertEqual(state["decision"]["report_runtime_status"], "PARTIAL_VALID")
        self.assertEqual(state["decision"]["full_production_acceptance"], "NOT_ALLOWED")

    def test_public_fail_no_partial_state(self):
        with self.assertRaisesRegex(RuntimeError, "SCHEMA"):
            self.bundle(fetcher=self.mutate_source(lambda rows: (rows[0].pop("Date"), rows[0].pop("出表日期"))))
        self.assertFalse(self.runtime.exists())

    def test_no_synthetic_current_prices(self):
        state = self.midnight_state("09:30", self.execute())
        self.assertTrue(all(r["current_price"] is None and r["current_volume"] is None for r in state["decision"]["records"]))
        self.assertTrue(all(v["value"] is None for v in state["decision"]["intraday_modules"].values()))

    def test_ai_paper_no_execution(self):
        decision = self.midnight_state("09:30", self.execute())["decision"]
        self.assertEqual(decision["ai_paper_execution_status"], p.BLOCKED)
        self.assertEqual(decision["ai_paper_portfolio"], self.previous["decision"]["ai_paper_portfolio"])

    def test_transaction_ledger_exact_preservation(self):
        decision = self.midnight_state("09:30", self.execute())["decision"]
        self.assertEqual(decision["transaction_ledger"], self.previous["decision"]["transaction_ledger"])

    def chain(self, changed=False):
        opening = self.execute()
        self.assertEqual(self.publish("09:30", opening)["validation_status"], "PASS")
        prior = self.artifacts / "production_state/live" / self.day / "0930" / PERSIST_NAME
        fetcher = self.mutate_source(lambda rows: rows[0].update(營業收入_額外公告="changed")) if changed else self.fetch
        source, _ = self.bundle("12:00", fetcher)
        midday = self.execute("12:00", previous=prior, source=source)
        self.assertEqual(self.publish("12:00", midday)["validation_status"], "PASS")
        return opening, midday

    def test_0930_to_1200_cold_continuity(self):
        opening, midday = self.chain()
        loaded = load_live_state(self.artifacts / "production_state", self.day, "12:00")
        self.assertEqual(loaded["state"]["previous_state_id"], opening["current_state_id"])
        self.assertNotEqual(opening["current_state_id"], midday["current_state_id"])
        self.assertEqual(loaded["state"]["decision"]["transaction_ledger"], self.previous["decision"]["transaction_ledger"])

    def test_1200_to_1930_resolver_continuity(self):
        _, midday = self.chain()
        context = resolve_context(cadence="19:30", event_name="workflow_dispatch", dispatch_trading_date=self.day,
            state_root=self.artifacts / "production_state")
        self.assertEqual(context["validation_status"], "PASS")
        self.assertEqual(context["previous_state_id"], midday["current_state_id"])

    def test_none_delta_is_valid_incremental_state(self):
        _, midday = self.chain()
        self.assertEqual(self.midnight_state("12:00", midday)["decision"]["public_official_delta"], "NONE")

    def test_detected_delta_updates_only_evidence(self):
        _, midday = self.chain(changed=True)
        decision = self.midnight_state("12:00", midday)["decision"]
        self.assertEqual(decision["public_official_delta"], "DETECTED")
        self.assertEqual(decision["transaction_ledger"], self.previous["decision"]["transaction_ledger"])

    def test_yahoo_or_mis_cannot_enter_bundle(self):
        for endpoint in ("https://tw.stock.yahoo.com/quote/2330", "https://mis.twse.com.tw/stock/api/getStockInfo.jsp"):
            def fetcher(url):
                return {**self.fetch(url), "final_url": endpoint}
            with self.subTest(endpoint=endpoint), self.assertRaisesRegex(RuntimeError, "HTTP_OR_REDIRECT"):
                target = self.root / str(len(self.calls)) / "bad.json"
                p.acquire(trading_date=self.day, cadence="09:30", output=target, evidence_output=target.parent / "error.json", fetcher=fetcher)

    def test_dependency_and_fallback_remain_blocked(self):
        contract = p.policy()
        dependencies = read_object(p.ROOT / "config/RATE_EXTERNAL_PRODUCTION_DEPENDENCIES.json")
        dependency = next(d for d in dependencies["dependencies"] if d["dependency_id"] == p.DEPENDENCY)
        self.assertEqual(dependency["status"], "BLOCKED_EXTERNAL")
        self.assertFalse(dependency["fallback_allowed"])
        self.assertFalse(dependency["production_acceptance_allowed_while_blocked"])
        self.assertFalse(contract["strategy_changes_allowed"])

    def test_missing_source_rejected(self):
        _, bundle = self.bundle()
        bundle["sources"].pop()
        bundle["content_sha256"] = sha256({k: v for k, v in bundle.items() if k != "content_sha256"})
        with self.assertRaisesRegex(RuntimeError, "SOURCE_MISSING"):
            p.validate_bundle(bundle, trading_date=self.day, cadence="09:30")

    def test_duplicate_invalid_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "DUPLICATE_INVALID"):
            self.bundle(fetcher=self.mutate_source(lambda rows: rows.append(copy.deepcopy(rows[0]))))

    def test_future_source_date_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "FUTURE_DATED"):
            self.bundle(fetcher=self.mutate_source(lambda rows: rows[0].update(Date="2099-01-01")))

    def test_stale_previous_eod_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "PREVIOUS_EOD"):
            self.bundle(fetcher=self.mutate_source(lambda rows: rows[0].update(Date="2026-09-01")))

    def test_stale_observation_rejected(self):
        def fetcher(url):
            return {**self.fetch(url), "retrieval_timestamp": "2026-01-01T00:00:00Z"}
        with self.assertRaisesRegex(RuntimeError, "OBSERVATION_STALE"):
            self.bundle(fetcher=fetcher)

    def test_future_observation_rejected(self):
        def fetcher(url):
            return {**self.fetch(url), "retrieval_timestamp": "2099-01-01T00:00:00Z"}
        with self.assertRaisesRegex(RuntimeError, "OBSERVATION_ORDER"):
            self.bundle(fetcher=fetcher)

    def test_invalid_numeric_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "INVALID_NUMERIC"):
            self.bundle(fetcher=self.mutate_source(lambda rows: rows[0].update(ClosingPrice="NaN")))

    def test_null_or_boolean_identity_rejected(self):
        for identity in (None, True, " "):
            with self.subTest(identity=identity), self.assertRaisesRegex(RuntimeError, "IDENTITY_INVALID"):
                p.validate_rows([{"Code": identity}], next(e for e in p.entries() if e["dataset_id"] == "twse_market_daily"), self.day)

    def test_negative_previous_volume_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "INVALID_NUMERIC"):
            self.bundle(fetcher=self.mutate_source(lambda rows: rows[0].update(TradeVolume="-1")))

    def test_builder_opt_in_delegates_without_intraday_transport(self):
        from scripts.build_production_source_bundle_from_official import build_bundle
        target = self.root / "builder" / "public.json"
        with patch("scripts.build_production_source_bundle_from_official.fetch_url", side_effect=lambda url, **kw: self.fetch(url)):
            result = build_bundle(rate_source_url="https://openapi.twse.com.tw/v1;https://www.tpex.org.tw/openapi/v1",
                trading_date=self.day, cadence="09:30", output=target, evidence_output=self.root / "builder-evidence.json", public_official_partial=True)
        self.assertEqual(result["report_runtime_status"], "PARTIAL_VALID")
        self.assertTrue(all(url in {e["endpoint"] for e in p.entries()} for url in self.calls))

    def test_archived_source_replay_without_acquisition_paths(self):
        source, bundle = self.bundle()
        with patch.dict(os.environ, {"GITHUB_EVENT_NAME": "schedule", "GITHUB_REF": "refs/heads/main"}):
            report = p.publish_report(source_bundle_path=source, trading_date=self.day, cadence="09:30",
                artifacts_root=self.artifacts, workflow_run_id="301", workflow_job_id="401", evidence_output=self.root / "report.json")
        for reference in bundle["sources"]:
            Path(reference["receipt_path"]).unlink()
        result = p.validate_bundle(bundle, trading_date=self.day, cadence="09:30", archive_directory=Path(report["published_report_path"]).parent)
        self.assertEqual(result["report_runtime_status"], "PARTIAL_VALID")

    def test_partial_state_cannot_publish_without_archived_source_bytes(self):
        persist = self.execute()
        evidence = self.root / "out0930" / (p.ARTIFACTS["09:30"] + ".json")
        result = publish_state(persist_evidence_path=evidence, trading_date=self.day, cadence="09:30",
            artifacts_root=self.artifacts, state_root=self.runtime, workflow_run_id="301", workflow_job_id="401",
            event_name="schedule", ref="refs/heads/main", commit_sha="c" * 40)
        self.assertEqual(result["validation_status"], "BLOCKED")
        self.assertFalse((self.artifacts / "production_state/live" / self.day / "0930" / PERSIST_NAME).exists())

    def test_raw_tamper_rejected(self):
        _, bundle = self.bundle()
        receipt = read_object(bundle["sources"][0]["receipt_path"])
        Path(receipt["raw_path"]).write_bytes(b"[]")
        with self.assertRaisesRegex(RuntimeError, "RAW_HASH"):
            p.validate_bundle(bundle, trading_date=self.day, cadence="09:30")

    def test_receipt_tamper_rejected(self):
        _, bundle = self.bundle()
        Path(bundle["sources"][0]["receipt_path"]).write_bytes(b"{}")
        with self.assertRaisesRegex(RuntimeError, "RECEIPT_HASH"):
            p.validate_bundle(bundle, trading_date=self.day, cadence="09:30")

    def test_bundle_tamper_rejected(self):
        _, bundle = self.bundle()
        bundle["report_runtime_status"] = "FULL_PRODUCTION_PASS"
        with self.assertRaisesRegex(RuntimeError, "BUNDLE_HASH"):
            p.validate_bundle(bundle, trading_date=self.day, cadence="09:30")

    def test_forged_fallback_even_with_new_content_hash_rejected(self):
        _, bundle = self.bundle()
        bundle["fallback_allowed"] = True
        bundle["content_sha256"] = sha256({k: v for k, v in bundle.items() if k != "content_sha256"})
        with self.assertRaisesRegex(RuntimeError, "GATE_INVALID"):
            p.validate_bundle(bundle, trading_date=self.day, cadence="09:30")

    def test_duplicate_json_key_rejected(self):
        with self.assertRaises(ValueError):
            p.read_rows(b'[{"Code":"TEST", "Code":"OTHER"}]')

    def test_watchlist_and_commentary_are_source_linked_not_prices(self):
        state = self.midnight_state("09:30", self.execute())
        row = state["decision"]["watchlist_evidence"][0]
        self.assertEqual(row["symbol"], "TEST")
        self.assertTrue(row["source_rows"])
        self.assertTrue(all(r["json_locator"] == "$[0]" for r in row["source_rows"]))
        self.assertEqual(state["decision"]["report_commentary_inputs"]["full_production_acceptance"], "NOT_ALLOWED")

    def test_publisher_rejects_rehashed_intraday_fill(self):
        persist = self.execute()
        old_path = self.runtime / "decision_state/0930" / (persist["current_state_id"] + ".json")
        material = read_object(old_path)
        state = material["decision_state"]
        state["decision"]["transaction_ledger"]["transactions"].append({"id": "forbidden-fill"})
        digest = sha256(strip_runtime(state["decision"]))
        state.update(current_state_id="rate-state-" + digest[:24], decision_payload_hash=digest)
        material["state_entry"].update(current_state_id=state["current_state_id"], decision_payload_hash=digest)
        persist.update(current_state_id=state["current_state_id"], current_state_hash=digest)
        persist["persist_result"]["state_entry"] = material["state_entry"]
        atomic_write_json(old_path.parent / (state["current_state_id"] + ".json"), material)
        atomic_write_json(self.root / "out0930" / (p.ARTIFACTS["09:30"] + ".json"), persist)
        result = self.publish("09:30", persist)
        self.assertEqual(result["validation_status"], "BLOCKED")
        self.assertIn("PUBLIC_PROTECTED_STATE_CHANGED", result["blocking_reason"])

    def test_partial_cannot_claim_full_status_to_bypass_validator(self):
        state = self.midnight_state("09:30", self.execute())
        state["decision"]["report_runtime_status"] = "FULL_PRODUCTION_PASS"
        with self.assertRaisesRegex(RuntimeError, "GATE_INVALID"):
            p.validate_partial_state(state["decision"])

    def test_legacy_named_price_cannot_be_inserted_as_current(self):
        state = self.midnight_state("09:30", self.execute())
        state["decision"]["records"][0]["close"] = 100
        with self.assertRaisesRegex(RuntimeError, "CURRENT_PRICE_FORBIDDEN"):
            p.validate_partial_state(state["decision"])

    def test_corrupted_previous_state_no_persist(self):
        atomic_write_json(self.previous_dir / STATE_NAME, {})
        with self.assertRaisesRegex(RuntimeError, "FILE_HASH"):
            self.execute()
        self.assertFalse(self.runtime.exists())

    def test_idempotent_same_runtime_state(self):
        source, _ = self.bundle()
        first = self.execute(source=source)
        second = self.execute(source=source)
        self.assertEqual(first, second)

    def test_full_formal_source_gate_rejects_partial_bundle(self):
        _, bundle = self.bundle()
        self.assertEqual(validate_production_source_bundle(bundle, trading_date=self.day, cadence="09:30")["validation_status"], "FAIL")

    def test_eod_cadences_cannot_use_partial_mode(self):
        for cadence in ("07:30", "19:30"):
            with self.assertRaisesRegex(RuntimeError, "CADENCE_FORBIDDEN"):
                self.bundle(cadence)

    def test_archive_immutable_no_refetch(self):
        self.bundle()
        count = len(self.calls)
        with self.assertRaisesRegex(RuntimeError, "IMMUTABLE_OUTPUT_EXISTS"):
            self.bundle()
        self.assertEqual(len(self.calls), count)

    def test_shared_official_endpoint_fetched_once(self):
        self.bundle()
        self.assertEqual(len(self.calls), len(set(e["endpoint"] for e in p.entries())))

    def test_unconfigured_risk_sources_not_asserted_clear(self):
        _, bundle = self.bundle()
        self.assertEqual(set(bundle["unconfigured_evidence"].values()), {"NOT_CONFIGURED_NOT_ASSERTED_CLEAR"})

    def test_published_state_exposes_partial_not_full_acceptance(self):
        persist = self.execute()
        self.assertEqual(self.publish("09:30", persist)["validation_status"], "PASS")
        latest = read_object(self.artifacts / "RATE_PRODUCTION_STATE_LATEST.json")
        self.assertEqual(latest["report_runtime_status"], "PARTIAL_VALID")
        self.assertEqual(latest["full_production_acceptance"], "NOT_ALLOWED")

    def test_report_consumption_never_updates_full_source_latest(self):
        source, _ = self.bundle()
        with patch.dict(os.environ, {"GITHUB_EVENT_NAME": "schedule", "GITHUB_REF": "refs/heads/main"}):
            result = p.publish_report(source_bundle_path=source, trading_date=self.day, cadence="09:30",
                artifacts_root=self.artifacts, workflow_run_id="301", workflow_job_id="401", evidence_output=self.root / "published.json")
        self.assertEqual(result["report_runtime_status"], "PARTIAL_VALID")
        self.assertFalse((self.artifacts / "RATE_PRODUCTION_SOURCE_BUNDLE_LATEST.json").exists())
        for reference in result["sources"]:
            directory = Path(result["published_report_path"]).parent
            self.assertEqual(p.digest_bytes((directory / reference["raw_reference"]).read_bytes()), reference["raw_sha256"])
            self.assertEqual(p.digest_bytes((directory / reference["receipt_reference"]).read_bytes()), reference["receipt_sha256"])

    def test_actual_cli_opt_in_0930_to_1200_cold_process(self):
        previous = self.predecessor
        first_id = None
        for cadence, number in (("09:30", "076"), ("12:00", "077")):
            source, _ = self.bundle(cadence)
            out = self.root / ("out" + cadence.replace(":", ""))
            command = [sys.executable, "-B", str(p.ROOT / "scripts" / ("run_cer" + number + "_incremental_" + cadence.replace(":", "") + "_acceptance.py")),
                "--public-official-partial", "--source-bundle", str(source), "--cer074-persisted-evidence", str(previous),
                "--cer075-persisted-evidence", str(previous), "--output-dir", str(out), "--state-root", str(self.runtime)]
            if cadence == "12:00":
                command.extend(["--cer076-persisted-evidence", str(previous)])
            result = subprocess.run(command, cwd=p.ROOT, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            persist = read_object(out / (p.ARTIFACTS[cadence] + ".json"))
            if first_id:
                self.assertEqual(persist["previous_state_id"], first_id)
            else:
                first_id = persist["current_state_id"]
            self.assertEqual(self.publish(cadence, persist)["validation_status"], "PASS")
            previous = self.artifacts / "production_state/live" / self.day / CADENCE_DIR[cadence] / PERSIST_NAME


if __name__ == "__main__":
    unittest.main()
