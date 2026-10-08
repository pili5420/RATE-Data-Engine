"""Synthetic coverage-only fixtures, never real FinMind/catalogue replay."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from urllib.parse import urlencode

from src.cer074_acceptance import sha256 as catalogue_hash
from src.eps_duration_facts.model import Rejected
from src.eps_duration_facts.raw import sha256
from src.full_market_catalogue import CLASSIFICATION_ENDPOINTS, LISTING_ENDPOINTS, policy_hash, POLICY_ID
from src.full_market_history import digest
from src.provider_eps_candidate import API, BASIC_LABEL, WINDOW, _canonical
from src.provider_eps_coverage import (QUERY, append_event, evaluate_receipt, initialize, load_universe,
    make_plan, now, read_events, result_entry, reuse_original, save, scan, summary, validate_plan)
from tests.provider_eps_engineering_fixture import make_fixture

BINDING = {"base_sha": "0" * 40, "head_sha": "1" * 40}
ENDS = ("2024-09-30", "2024-12-31", "2025-03-31", "2025-06-30", "2025-09-30", "2025-12-31", "2026-03-31", "2026-06-30")


class FakeClock:
    def __init__(self):
        self.value = 0

    def clock(self):
        return self.value

    def sleep(self, seconds):
        self.value += seconds


def engineering_universe(path):
    catalogue = {"artifact": "RATE_FULL_MARKET_ELIGIBILITY_CATALOGUE", "as_of": "2026-10-06",
        "trading_date": "2026-10-06", "policy_id": POLICY_ID, "policy_hash": policy_hash(),
        "validation_status": "PASS", "source_status": "PASS", "freshness_status": "PASS",
        "fallback_used": False, "blocked_dependencies": [], "excluded_type_counts": {}, "markets": []}
    for market, symbols in (("TWSE", ["1340", "2330"]), ("TPEX", ["6488", "7777"])):
        records = [{"symbol": s, "market": market, "cfi_code": "ESVUFR", "eligible": True,
            "eligibility": True, "security_type": "COMMON_STOCK",
            "official_listing_market": "TWSE LISTED" if market == "TWSE" else "TPEx LISTED",
            "eligibility_reason": "OFFICIAL_COMMON_EQUITY_NORMAL_LISTING"} for s in symbols]
        receipts = {kind: {"endpoint": endpoint, "http_status": 200, "fallback_used": False,
            "response_bytes": 11, "body_sha256": sha256(b"ENGINEERING"), "as_of": "2026-10-06", "record_count": 2}
            for kind, endpoint in (("classification", CLASSIFICATION_ENDPOINTS[market]), ("listing", LISTING_ENDPOINTS[market]))}
        catalogue["markets"].append({"market": market, "complete": True, "record_count": 2,
            "records": records, "records_sha256": catalogue_hash(records), "source_receipt": receipts})
    catalogue.update(record_count=4, eligible_count=4)
    catalogue["content_hash"] = catalogue_hash(catalogue)
    catalogue["catalogue_id"] = "rate-full-market-catalogue-" + catalogue["content_hash"][:24]
    authority = {"ref": "refs/heads/main", "event": "workflow_dispatch", "run_id": "1", "commit_sha": "0" * 40,
        "github_execution_evidence": {"run_id": "1", "head_sha": "0" * 40, "head_branch": "main",
            "event": "workflow_dispatch", "workflow_path": ".github/workflows/rate_full_market_history_bootstrap.yml", "run_attempt": "1"}}
    historical = {"artifact": "RATE_FULL_MARKET_HISTORY_PLAN", "engineering_fixture": True, "as_of": "2026-10-06",
        "catalogue": catalogue, "catalogue_sha256": digest(catalogue), "runtime_authority": authority,
        "shards": [{"market": m["market"], "symbols": [r["symbol"] for r in m["records"]]} for m in catalogue["markets"]]}
    historical["plan_id"] = "rate-history-plan-" + digest(historical)[:24]
    save(path, historical)
    return load_universe(path, sha256(path.read_bytes()), "0" * 40, expected_counts={"TWSE": 2, "TPEX": 2})


def fake_capture(*, rows_mutator=None, blocked=False, service_blocked=False, wrong_identity=False):
    def capture(root, ident, api, symbol, *, start, end, token):
        query = {"dataset": QUERY["dataset"], "data_id": symbol, "start_date": start, "end_date": end}
        rows = [{"stock_id": "WRONG" if wrong_identity and symbol == "7777" else symbol,
            "date": d, "type": "EPS", "origin_name": BASIC_LABEL, "value": 0 if i == 0 else -i} for i, d in enumerate(ENDS)]
        if rows_mutator:
            rows_mutator(rows)
        payload = {"status": 402 if service_blocked else 200, "data": rows, "engineering_fixture": True}
        body = json.dumps(payload).encode()
        raw = root / "raw" / (sha256(body) + ".json")
        raw.write_bytes(body)
        observed = now()
        receipt = {"engineering_fixture": True, "query": query, "requested_url": api,
            "final_url": api + "?" + urlencode(query), "http_status": 402 if blocked else 200,
            "status": "HTTP_BLOCKED" if blocked else "SAMPLE_BODY_ACQUIRED", "raw_capture_status": "COMPLETE",
            "content_encoding": None, "content_length": str(len(body)), "bytes": len(body),
            "response_body_sha256": sha256(body), "raw_path": "raw/" + raw.name,
            "started_at": observed, "received_at": observed, "finished_at": observed}
        save(root / "receipts" / (ident + ".json"), receipt)
        return receipt
    return capture


class CoverageEngineeringTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="provider-coverage-engineering-")
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.original = self.directory / "original"
        self.original.mkdir()
        make_fixture(self.original)
        self.evidence = self.directory / "engineering-universe.json"
        self.universe = engineering_universe(self.evidence)
        self.plan = make_plan(self.universe, BINDING, {"path": "ENGINEERING_ONLY", "sha256": "1" * 64})
        self.root = initialize(self.directory / "coverage", self.plan)
        reuse_original(self.root, self.plan, self.original)

    def run_scan(self, capture, **kwargs):
        clock = FakeClock()
        return scan(self.root, self.plan, capture, sleep=clock.sleep, clock=clock.clock, **kwargs)

    def test_more_than_original_three_and_original_24_regression(self):
        before = read_events(self.root, self.plan)
        self.assertEqual(sum(len(e["rows"]) for e in before.values()), 24)
        stop = self.run_scan(fake_capture())
        report = summary(self.root, self.plan, stop)
        self.assertEqual(report["counts"]["valid_company_quarters"], 32)
        self.assertEqual(report["counts"]["eps_complete_companies"], 4)
        self.assertEqual(report["counts"]["accounted_for"], 4)
        self.assertEqual(report["counts"]["actual_data_request_intents"], 1)
        self.assertFalse(report["production_eligible"])

    def test_same_plan_continuation_never_repeats_counts_or_requests(self):
        self.run_scan(fake_capture())
        stop = self.run_scan(lambda *args, **kwargs: self.fail("NO_DUPLICATE_FETCH"))
        self.assertEqual(stop["new_requests"], 0)
        self.assertEqual(summary(self.root, self.plan, stop)["counts"]["valid_company_quarters"], 32)
        reuse_original(self.root, self.plan, self.original)
        self.assertEqual(len(read_events(self.root, self.plan)), 4)

    def test_changed_universe_market_or_window_cannot_mix_plans(self):
        other = deepcopy(self.universe)
        for r in other["stocks"]:
            if r["symbol"] == "2330": r["market"] = "TPEX"
            if r["symbol"] == "6488": r["market"] = "TWSE"
        new_plan = make_plan(other, BINDING, self.plan["transport_binding"])
        with self.assertRaisesRegex(Rejected, "DIFFERENT_COVERAGE_PLAN"):
            initialize(self.root, new_plan)
        wrong = deepcopy(self.plan)
        wrong["window"].pop()
        with self.assertRaisesRegex(Rejected, "COVERAGE_PLAN_BINDING"):
            validate_plan(wrong)

    def test_universe_hash_commit_counts_and_mapping_are_bound(self):
        for digest_value, commit, reason in (("f" * 64, "0" * 40, "HASH_MISMATCH"),
                                            (sha256(self.evidence.read_bytes()), "f" * 40, "COMMIT_MISMATCH")):
            with self.assertRaisesRegex(Rejected, reason):
                load_universe(self.evidence, digest_value, commit, expected_counts={"TWSE": 2, "TPEX": 2})
        with self.assertRaisesRegex(Rejected, "COUNTS_MISMATCH"):
            load_universe(self.evidence, sha256(self.evidence.read_bytes()), "0" * 40)

    def test_missing_quarter_is_not_zero_or_older_substitution(self):
        stop = self.run_scan(fake_capture(rows_mutator=lambda rows: rows.pop(5)))
        result = summary(self.root, self.plan, stop)
        company = next(c for c in result["companies"] if c["symbol"] == "7777")
        self.assertEqual(company["status"], "HISTORICAL_INSUFFICIENT")
        self.assertEqual(company["missing_quarters"], ["2025Q4"])
        self.assertEqual(result["counts"]["valid_company_quarters"], 31)

    def test_duplicate_conflict_nonfinite_are_separate_and_other_positions_survive(self):
        def modify(rows):
            rows.append(deepcopy(rows[0]))
            conflict = deepcopy(rows[1]); conflict["value"] = 999; rows.append(conflict)
            rows[6]["value"] = "NaN"
        stop = self.run_scan(fake_capture(rows_mutator=modify))
        entry = read_events(self.root, self.plan)["7777"]
        self.assertEqual(len(entry["rows"]), 5)
        self.assertEqual({i["reason"] for i in entry["issues"]}, {"RAW_DUPLICATE_KEY", "RAW_CONFLICTING_VALUE", "NONFINITE_EPS"})
        self.assertEqual(summary(self.root, self.plan, stop)["counts"]["eps_complete_companies"], 3)

    def test_no_eps_distinguished_from_unattempted(self):
        stop = self.run_scan(fake_capture(rows_mutator=lambda rows: rows.clear()))
        company = next(c for c in summary(self.root, self.plan, stop)["companies"] if c["symbol"] == "7777")
        self.assertEqual(company["status"], "NO_EPS")
        self.assertFalse(company["unattempted"])

    def test_shared_http_or_service_quota_stops_and_never_retries(self):
        self.run_scan(fake_capture(service_blocked=True))
        stop = self.run_scan(lambda *args, **kwargs: self.fail("NO_BLOCK_BYPASS"))
        self.assertEqual(stop["reason"], "PERSISTED_STOP_GATE")
        self.assertEqual(stop["persisted_reason"], "SHARED_HOST_ACCESS_STOP")
        self.assertEqual(read_events(self.root, self.plan)["7777"]["status"], "ACCESS_FAILED")

    def test_single_company_validation_failure_does_not_poison_other_companies(self):
        self.universe["stocks"].append({"symbol": "8888", "market": "TPEX"})
        self.universe["expected_market_counts"]["TPEX"] = 3
        self.plan = make_plan(self.universe, BINDING, self.plan["transport_binding"])
        self.root = initialize(self.directory / "coverage-five", self.plan)
        reuse_original(self.root, self.plan, self.original)
        self.run_scan(fake_capture(wrong_identity=True))
        entries = read_events(self.root, self.plan)
        self.assertEqual(entries["7777"]["status"], "VALIDATION_FAILED")
        self.assertNotIn("8888", entries)
        pending = next(c for c in summary(self.root, self.plan, {"reason": "VALIDATION_FAILED_STOP"})["companies"] if c["symbol"] == "8888")
        self.assertEqual(pending["status"], "NOT_ATTEMPTED")
        self.assertTrue(all(entries[s]["status"] == "COMPLETE" for s in ("2330", "6488", "1340")))

    def test_common_block_leaves_following_company_unattempted(self):
        self.universe["stocks"].append({"symbol": "8888", "market": "TPEX"})
        self.universe["expected_market_counts"]["TPEX"] = 3
        self.plan = make_plan(self.universe, BINDING, self.plan["transport_binding"])
        self.root = initialize(self.directory / "coverage-block-five", self.plan)
        reuse_original(self.root, self.plan, self.original)
        stop = self.run_scan(fake_capture(blocked=True))
        report = summary(self.root, self.plan, stop)
        pending = next(c for c in report["companies"] if c["symbol"] == "8888")
        self.assertEqual(pending["status"], "NOT_ATTEMPTED")
        self.assertEqual(report["counts"]["actual_data_request_intents"], 1)
        self.assertEqual(report["counts"]["accounted_for"], 4)

    def test_extra_provider_period_retained_but_not_counted(self):
        def modify(rows):
            extra = deepcopy(rows[0]); extra["date"] = "2026-09-30"; rows.append(extra)
        self.run_scan(fake_capture(rows_mutator=modify))
        entry = read_events(self.root, self.plan)["7777"]
        self.assertEqual(len(entry["rows"]), 8)
        self.assertEqual(entry["issues"][0]["reason"], "EXTRA_PROVIDER_PERIOD")
        self.assertFalse(entry["issues"][0]["target_position"])

    def test_resigned_ledger_wrong_market_rejected(self):
        path = self.root / "events/2330.json"
        event = json.loads(path.read_bytes())
        event["market"] = "TPEX"
        event["event_sha256"] = sha256(_canonical({k: v for k, v in event.items() if k != "event_sha256"}))
        path.write_text(json.dumps(event))
        with self.assertRaisesRegex(Rejected, "PLAN_OR_MARKET_MISMATCH"):
            read_events(self.root, self.plan)

    def test_bounded_budget_leaves_pending_not_no_data(self):
        stop = self.run_scan(lambda *args, **kwargs: self.fail("ZERO_BUDGET"), max_requests=0)
        result = summary(self.root, self.plan, stop)
        self.assertEqual(result["counts"]["accounted_for"], 3)
        self.assertEqual(result["counts"]["unattempted_companies"], 1)
        self.assertIsNone(result["full_universe_complete_observed_at"])

    def test_unknown_intent_is_not_retried_or_claimed_unattempted(self):
        save(self.root / "intents/7777.json", {"plan_id": self.plan["plan_id"], "symbol": "7777"})
        stop = self.run_scan(lambda *args, **kwargs: self.fail("INTENT_RETRY_FORBIDDEN"))
        self.assertEqual(stop["reason"], "REQUEST_OUTCOME_UNKNOWN_NO_AUTOMATIC_RETRY")
        company = summary(self.root, self.plan, stop)["companies"][-1]
        self.assertEqual(company["status"], "REQUEST_OUTCOME_UNKNOWN")
        self.assertFalse(company["unattempted"])

    def test_saved_receipt_recovers_intent_without_fetch(self):
        save(self.root / "intents/7777.json", {"plan_id": self.plan["plan_id"], "symbol": "7777"})
        fake_capture()(self.root, "coverage-7777", API, "7777", start=QUERY["start_date"], end=QUERY["end_date"], token=None)
        stop = self.run_scan(lambda *args, **kwargs: self.fail("SAVED_RESPONSE_FETCH_FORBIDDEN"))
        self.assertEqual(stop["new_requests"], 0)
        self.assertEqual(summary(self.root, self.plan, stop)["counts"]["valid_company_quarters"], 32)

    def test_observations_sort_hash_and_unknowns_preserved(self):
        before = read_events(self.root, self.plan)
        self.run_scan(fake_capture())
        after = read_events(self.root, self.plan)
        for s in before:
            self.assertEqual(before[s], after[s])
        for row in after["7777"]["rows"]:
            self.assertIsNone(row["revision_id"])
            self.assertIsNone(row["public_time"])
            self.assertEqual(row["market"], "TPEX")
        self.assertEqual([r["analysis_quarter"] for r in after["7777"]["rows"]], list(reversed(WINDOW)))
        self.assertEqual(after["7777"]["rows"][-1]["provider_value"], "0")

    def test_ledger_and_raw_tamper_rejected(self):
        self.run_scan(fake_capture())
        row = read_events(self.root, self.plan)["7777"]["rows"][0]
        Path(row["raw_reference"]).write_bytes(b"TAMPERED")
        with self.assertRaisesRegex(Rejected, "SOURCE_TAMPERED"):
            read_events(self.root, self.plan)


if __name__ == "__main__":
    unittest.main()
