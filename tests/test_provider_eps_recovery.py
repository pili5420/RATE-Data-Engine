"""Synthetic label, stop, timing and lineage checks; zero live network calls."""
from copy import deepcopy
import json
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock
from types import SimpleNamespace

from src.eps_duration_facts.model import Rejected
from src.eps_duration_facts.raw import sha256
from src.provider_eps_candidate import (API, BASIC_LABEL, LABEL_MAPPING_VERSION, _canonical, _json,
    map_basic_eps_label, read_provider_response, build_candidate, consume_candidate)
from src.provider_eps_coverage import (QUERY, append_event, initialize, make_plan, now, read_events,
    result_entry, reuse_original, save, scan, stop_exit_code, summary)
from src.provider_eps_dispatch import DispatchGate, exclusive_scan
from src.provider_eps_recovery import replay_archive
from tests.provider_eps_engineering_fixture import make_fixture, write
from tests.test_provider_eps_coverage import BINDING, FakeClock, engineering_universe, fake_capture

UNIT_LABEL = BASIC_LABEL + "\uff08\u5143\uff09"


class LabelCompatibilityTests(unittest.TestCase):
    def test_exact_two_labels_and_no_type_or_unit_alias(self):
        for label in (BASIC_LABEL, UNIT_LABEL):
            mapping = map_basic_eps_label("EPS", label)
            self.assertEqual(mapping["normalized_provider_label"], BASIC_LABEL)
            self.assertEqual(mapping["label_mapping_version"], LABEL_MAPPING_VERSION)
        for kind, label in (("DILUTED", BASIC_LABEL), ("eps", BASIC_LABEL), ("OTHER", UNIT_LABEL),
                            ("EPS", "DILUTED"), ("EPS", "unknown"), ("EPS", BASIC_LABEL + "(\u5143)"),
                            ("EPS", BASIC_LABEL + "\uff08\u7f8e\u5143\uff09"), ("EPS", " " + BASIC_LABEL),
                            ("EPS", BASIC_LABEL + " extra"), ("EPS", "\u7a00\u91cb\u6bcf\u80a1\u76c8\u9918")):
            with self.subTest(kind=kind, label=label), self.assertRaises(Rejected):
                map_basic_eps_label(kind, label)


class RecoveryEngineeringTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="pr33-synthetic-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.original = self.directory / "original"
        self.original.mkdir()
        make_fixture(self.original)
        self.universe = engineering_universe(self.directory / "universe.json")
        self.plan = make_plan(self.universe, BINDING, {"path": "MOCK_NOT_NETWORK", "sha256": "1" * 64})
        self.root = initialize(self.directory / "old", self.plan)
        reuse_original(self.root, self.plan, self.original)

    def run_scan(self, capture, **kwargs):
        clock = FakeClock()
        return scan(self.root, self.plan, capture, clock=clock.clock, sleep=clock.sleep, **kwargs)

    def five_companies(self):
        self.universe["stocks"].append({"symbol": "8888", "market": "TPEX"})
        self.universe["expected_market_counts"]["TPEX"] = 3
        self.plan = make_plan(self.universe, BINDING, self.plan["transport_binding"])
        self.root = initialize(self.directory / "five", self.plan)
        reuse_original(self.root, self.plan, self.original)

    def test_raw_unit_label_preserved_in_candidate_and_coverage(self):
        self.run_scan(fake_capture(rows_mutator=lambda rows: [r.update(origin_name=UNIT_LABEL) for r in rows]))
        rows = read_events(self.root, self.plan)["7777"]["rows"]
        self.assertEqual(len(rows), 8)
        for row in rows:
            self.assertEqual(row["provider_origin_name"], UNIT_LABEL)
            self.assertEqual(row["normalized_provider_label"], BASIC_LABEL)
            self.assertEqual(row["label_mapping_rule"], "EXACT_BASIC_NAME_TWD_UNIT")
        self.assertEqual(rows[-1]["provider_value"], "0")
        self.assertEqual(rows[0]["provider_value"], "-7")

    def test_strict_candidate_accepts_unit_label_and_preserves_raw_name(self):
        inputs = json.loads((self.original / "analysis_input.json").read_bytes())
        for receipt_path in (self.original / "receipts").glob("*.json"):
            receipt = json.loads(receipt_path.read_bytes())
            payload = json.loads((self.original / receipt["raw_path"]).read_bytes())
            for row in payload["data"]:
                if row["type"] == "EPS":
                    row["origin_name"] = UNIT_LABEL
            body = json.dumps(payload).encode()
            raw_path = self.original / "raw" / (sha256(body) + ".json")
            raw_path.write_bytes(body)
            receipt.update(raw_path="raw/" + raw_path.name, bytes=len(body), content_length=str(len(body)), response_body_sha256=sha256(body))
            write(receipt_path, receipt)
            for row in inputs["records"]:
                if row["receipt_reference"] == str(receipt_path):
                    row.update(provider_origin_name=UNIT_LABEL, raw_path=str(raw_path), response_sha256=sha256(body),
                               receipt_sha256=sha256(receipt_path.read_bytes()), response_bytes=len(body))
        write(self.original / "analysis_input.json", inputs)
        candidate = build_candidate(self.original, BINDING)
        consume_candidate(candidate)
        self.assertTrue(all(r["provider_origin_name"] == UNIT_LABEL for c in candidate["companies"] for r in c["quarters"]))

    def test_first_validation_failure_stops_before_next_capture_and_nonzero_exit(self):
        self.five_companies()
        calls = []
        capture = fake_capture(rows_mutator=lambda rows: [r.update(origin_name="UNKNOWN") for r in rows])
        def mock(*args, **kwargs):
            calls.append(args[3])
            return capture(*args, **kwargs)
        stop = self.run_scan(mock)
        self.assertEqual(calls, ["7777"])
        self.assertEqual(stop["reason"], "VALIDATION_FAILED_STOP")
        self.assertEqual(stop_exit_code(stop), 2)
        self.assertEqual(read_events(self.root, self.plan)["7777"]["status"], "VALIDATION_FAILED")
        restart = self.run_scan(lambda *a, **k: self.fail("PERSISTED_ERROR_DISPATCH"))
        self.assertEqual(restart["reason"], "PERSISTED_STOP_GATE")
        self.assertEqual(stop_exit_code(restart), 2)

    def test_cli_execute_returns_nonzero_and_persists_failure_report(self):
        with patch.object(sys, "path", [str(Path(__file__).resolve().parents[1] / "scripts"), *sys.path]):
            from scripts import scan_provider_eps_coverage as cli
        self.five_companies()
        capture = Mock(side_effect=fake_capture(wrong_identity=True))
        module = SimpleNamespace(capture=capture)
        spec = SimpleNamespace(loader=SimpleNamespace(exec_module=lambda value: None))
        args = SimpleNamespace(reuse_input=self.original, max_requests=280, max_seconds=3600,
            interval_seconds=13, expected_base=BINDING["base_sha"], expected_head=BINDING["head_sha"])
        with patch.object(cli.importlib.util, "spec_from_file_location", return_value=spec), \
             patch.object(cli.importlib.util, "module_from_spec", return_value=module), \
             patch.object(cli, "binding", return_value={}), patch("builtins.print"):
            code = cli.execute(args, self.root, self.plan, Path("MOCK"), [], {}, {}, {})
        self.assertEqual(code, 2)
        self.assertEqual(capture.call_count, 1)
        execution = _json(next((self.root / "reports").glob("*/execution.json")).read_bytes())
        self.assertEqual(execution["stop"]["reason"], "VALIDATION_FAILED_STOP")

    def test_saved_validation_event_without_gate_also_stops_on_restart(self):
        fake_capture(wrong_identity=True)(self.root, "coverage-7777", API, "7777", start=QUERY["start_date"], end=QUERY["end_date"], token=None)
        from src.provider_eps_coverage import evaluate_receipt
        append_event(self.root, evaluate_receipt(self.plan, "7777", self.root / "receipts/coverage-7777.json"))
        stop = self.run_scan(lambda *a, **k: self.fail("OLD_VALIDATION_DISPATCH"))
        self.assertEqual(stop["reason"], "PERSISTED_VALIDATION_FAILED")

    def test_missing_and_empty_are_classified_not_validation_and_can_continue(self):
        self.five_companies()
        calls = []
        partial = fake_capture(rows_mutator=lambda rows: rows.pop())
        empty = fake_capture(rows_mutator=lambda rows: rows.clear())
        def mock(*args, **kwargs):
            calls.append(args[3])
            return (partial if args[3] == "7777" else empty)(*args, **kwargs)
        stop = self.run_scan(mock)
        self.assertEqual(calls, ["7777", "8888"])
        self.assertEqual(stop["reason"], "ALL_COMPANIES_ACCOUNTED_FOR")
        self.assertEqual(stop_exit_code(stop), 0)
        events = read_events(self.root, self.plan)
        self.assertEqual(events["7777"]["status"], "HISTORICAL_INSUFFICIENT")
        self.assertEqual(events["8888"]["status"], "NO_EPS")

    def test_unknown_request_later_in_universe_blocks_earlier_dispatch(self):
        self.five_companies()
        save(self.root / "intents/8888.json", {"plan_id": self.plan["plan_id"], "symbol": "8888"})
        stop = self.run_scan(lambda *a, **k: self.fail("UNKNOWN_REQUEST_BYPASS"))
        self.assertEqual(stop["reason"], "REQUEST_OUTCOME_UNKNOWN_NO_AUTOMATIC_RETRY")
        self.assertEqual(self.run_scan(lambda *a, **k: self.fail("UNKNOWN_RESTART"))["reason"], "PERSISTED_STOP_GATE")

    def test_source_tamper_and_plan_damage_dispatch_nothing(self):
        event = read_events(self.root, self.plan)["2330"]
        Path(event["rows"][0]["raw_reference"]).write_bytes(b"tampered")
        with self.assertRaisesRegex(Rejected, "SOURCE_TAMPERED"):
            self.run_scan(lambda *a, **k: self.fail("TAMPER_DISPATCH"))
        broken = deepcopy(self.plan)
        broken["window"].pop()
        with self.assertRaisesRegex(Rejected, "PLAN_BINDING"):
            scan(self.root, broken, lambda *a, **k: self.fail("PLAN_DISPATCH"))

    def test_saved_receipt_validation_recovery_stops_without_new_calls(self):
        self.five_companies()
        save(self.root / "intents/7777.json", {"plan_id": self.plan["plan_id"], "symbol": "7777"})
        fake_capture(wrong_identity=True)(self.root, "coverage-7777", API, "7777", start=QUERY["start_date"], end=QUERY["end_date"], token=None)
        stop = self.run_scan(lambda *a, **k: self.fail("SAVED_FAILURE_FETCH"))
        self.assertEqual(stop["reason"], "VALIDATION_FAILED_STOP")
        self.assertEqual(stop["new_requests"], 0)

    def test_cross_batch_new_session_waits_conservatively_and_records_boundary(self):
        self.five_companies()
        first_clock = FakeClock()
        first = scan(self.root, self.plan, fake_capture(), max_requests=1, clock=first_clock.clock, sleep=first_clock.sleep)
        self.assertEqual(first["reason"], "BOUNDED_BATCH_BUDGET")
        second_clock = FakeClock()
        second = scan(self.root, self.plan, fake_capture(), clock=second_clock.clock, sleep=second_clock.sleep)
        self.assertEqual(second["reason"], "ALL_COMPANIES_ACCOUNTED_FOR")
        one = _json((self.root / "intents/7777.json").read_bytes())["dispatch_evidence"]
        two = _json((self.root / "intents/8888.json").read_bytes())["dispatch_evidence"]
        self.assertNotEqual(one["session_identity"], two["session_identity"])
        self.assertEqual(two["actual_wait_seconds"], 13)
        self.assertIsNone(two["previous_dispatch_interval_seconds"])
        self.assertEqual(two["prior_session_continuity"], "UNPROVEN_CONSERVATIVE_WAIT")

    def test_dispatch_evidence_tamper_is_rejected_before_restart_capture(self):
        self.run_scan(fake_capture())
        path = self.root / "intents/7777.json"
        intent = _json(path.read_bytes())
        intent["dispatch_evidence"]["monotonic_timestamp"] = 999
        path.write_bytes(_canonical(intent))
        with self.assertRaisesRegex(Rejected, "DISPATCH_EVIDENCE_TAMPERED"):
            self.run_scan(lambda *a, **k: self.fail("TIMING_TAMPER_DISPATCH"))

    def test_single_writer_lock_rejects_other_writer(self):
        with exclusive_scan(self.root):
            with self.assertRaisesRegex(RuntimeError, "WRITER_ALREADY_ACTIVE"):
                with exclusive_scan(self.root):
                    self.fail("PARALLEL_WRITER")

    def archive_synthetic_failure(self):
        save(self.root / "intents/7777.json", {"plan_id": self.plan["plan_id"], "symbol": "7777", "query": {**QUERY, "data_id": "7777"}})
        def modify(rows):
            del rows[6:]
            for row in rows:
                row["origin_name"] = UNIT_LABEL
        fake_capture(rows_mutator=modify)(self.root, "coverage-7777", API, "7777", start=QUERY["start_date"], end=QUERY["end_date"], token=None)
        ref = self.root / "receipts/coverage-7777.json"
        material = read_provider_response(ref, symbols=("7777",))
        old_issues = [{"reason": "PROVIDER_BASIC_LABEL_MISMATCH", "analysis_quarter": r["analysis_quarter"], "json_locator": r["json_locator"], "target_position": True} for r in material["rows"]]
        append_event(self.root, result_entry(self.plan, "7777", issues=old_issues, references=[str(ref)], integrity=material["input_integrity"]))
        paths = {p.resolve() for p in self.root.rglob("*") if p.is_file()}
        for path in (self.root / "events").glob("*.json"):
            paths.update(Path(p).resolve() for p in _json(path.read_bytes())["input_integrity"])
        inventory = {str(p): {"bytes": len(b), "sha256": sha256(b)} for p in paths for b in [p.read_bytes()]}
        manifest = self.directory / "synthetic-archive.json"
        save(manifest, {"schema": "RATE_PR33_OLD_HEAD_EVIDENCE_V1", "old_root": str(self.root), "old_plan_id": self.plan["plan_id"],
            "old_plan_sha256": sha256((self.root / "plan.json").read_bytes()), "old_head": BINDING["head_sha"], "files": inventory,
            "counts": {"accounted_for": 4}, "inherited_requests": 1})
        return manifest, inventory

    def test_versioned_offline_replay_counts_and_old_bytes_unchanged(self):
        manifest, inventory = self.archive_synthetic_failure()
        new_binding = {**BINDING, "head_sha": "2" * 40}
        root, plan, changes = replay_archive(manifest, self.directory / "successor", new_binding)
        self.assertNotEqual(plan["plan_id"], self.plan["plan_id"])
        self.assertEqual(plan["recovery_lineage"]["parent_plan_id"], self.plan["plan_id"])
        result = summary(root, plan, {"reason": "OFFLINE_ONLY"})
        self.assertEqual(result["counts"]["valid_company_quarters"], 30)
        self.assertEqual(result["counts"]["inherited_data_requests"], 1)
        self.assertEqual(result["counts"]["new_plan_data_request_intents"], 0)
        recovered = read_events(root, plan)["7777"]
        self.assertEqual(recovered["status"], "HISTORICAL_INSUFFICIENT")
        self.assertEqual(recovered["recovery"]["old_status"], "VALIDATION_FAILED")
        for row in recovered["rows"]:
            self.assertEqual(row["provider_origin_name"], UNIT_LABEL)
            self.assertIsNone(row["revision_id"])
            self.assertIsNone(row["public_time"])
            self.assertEqual(row["acquired_observed_at"], _json(Path(row["receipt_reference"]).read_bytes())["received_at"])
        self.assertEqual(len(changes), 4)
        self.assertEqual(inventory, {p: {"bytes": len(b), "sha256": sha256(b)} for p in inventory for b in [Path(p).read_bytes()]})
        with self.assertRaisesRegex(Rejected, "REQUIRES_NEW_ROOT"):
            replay_archive(manifest, root, new_binding)

    def test_changed_archive_rejected_no_cross_version_overwrite(self):
        manifest, _ = self.archive_synthetic_failure()
        (self.root / "events/7777.json").write_bytes(b"changed")
        with self.assertRaisesRegex(Rejected, "ARCHIVED_SOURCE_CHANGED"):
            replay_archive(manifest, self.directory / "bad-successor", {**BINDING, "head_sha": "2" * 40})
        self.assertFalse((self.directory / "bad-successor").exists())

    def test_recovered_decision_provenance_cannot_be_resigned_to_change_history(self):
        manifest, _ = self.archive_synthetic_failure()
        root, plan, _ = replay_archive(manifest, self.directory / "successor", {**BINDING, "head_sha": "2" * 40})
        path = root / "events/7777.json"
        entry = _json(path.read_bytes())
        entry["recovery"]["old_status"] = "COMPLETE"
        entry["event_sha256"] = sha256(_canonical({k: v for k, v in entry.items() if k != "event_sha256"}))
        path.write_bytes(_canonical(entry))
        with self.assertRaisesRegex(Rejected, "RECOVERY_DECISION_PROVENANCE"):
            read_events(root, plan)


class MonotonicDispatchTests(unittest.TestCase):
    def test_early_sleep_tops_up_and_utc_rollback_does_not_shorten_gap(self):
        clock = FakeClock()
        calls = []
        def early_sleep(seconds):
            calls.append(seconds)
            clock.value += seconds / 2 if len(calls) == 1 else seconds
        wall = iter(("2026-10-08T02:00:00+00:00", "2026-10-08T01:00:00+00:00"))
        gate = DispatchGate(13, clock=clock.clock, sleep=early_sleep, utc=lambda: next(wall))
        gate.boundary("one")
        second = gate.boundary("two")
        self.assertEqual(calls, [13, 6.5])
        self.assertEqual(second["previous_dispatch_interval_seconds"], 13)
        self.assertEqual(second["actual_wait_seconds"], 13)

    def test_no_progress_sleep_and_monotonic_regression_fail_closed(self):
        clock = FakeClock()
        gate = DispatchGate(13, prior_dispatch=True, clock=clock.clock, sleep=lambda seconds: None, utc=now)
        with self.assertRaisesRegex(Rejected, "WAIT_DID_NOT_ADVANCE"):
            gate.boundary("never")
        clock.value = -1
        with self.assertRaisesRegex(Rejected, "CLOCK_REGRESSED"):
            gate.delay()

    def test_wait_after_previous_capture_completion_is_conservative(self):
        clock = FakeClock()
        gate = DispatchGate(13, clock=clock.clock, sleep=clock.sleep, utc=now)
        gate.boundary("one")
        clock.value = 5
        gate.completed()
        second = gate.boundary("two")
        self.assertEqual(second["previous_dispatch_interval_seconds"], 18)


if __name__ == "__main__":
    unittest.main()
