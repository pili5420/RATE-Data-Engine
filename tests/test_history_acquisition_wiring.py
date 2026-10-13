"""SYNTHETIC ONLY. No fixture is accepted official history or live authorization."""
from copy import deepcopy
from datetime import date, timedelta
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch, Mock
from urllib.error import HTTPError

from scripts.verify_ci_applicability import network_guard
sys.addaudithook(network_guard)
from src import history_acquisition_execution as h
from src import history_acquisition_transport as transport
from src.history_acquisition_validation import parse_history, coverage_inventory, benchmark_chains

ROOT = Path(__file__).resolve().parents[1]


def universe():
    return {"verification_status": "PASS", "stocks": [{"symbol": "2330", "market": "TWSE"}]
        + [{"symbol": f"TW{i:04}", "market": "TWSE"} for i in range(1084)]
        + [{"symbol": "6488", "market": "TPEX"}]
        + [{"symbol": f"TP{i:04}", "market": "TPEX"} for i in range(892)]}


def payload(entry):
    if entry["product"] == "benchmark":
        return {"fields": ["Date", "收盤指數" if entry["market"] == "TWSE" else "收市"], "data": [["2026/09/01", "100"]]}
    fields = ["Date", "Open", "High", "Low", "Close", "Trade unit", "Trade Amt.(NTD1000)"] if entry["market"] == "TPEX" else ["Date", "OpeningPrice", "HighestPrice", "LowestPrice", "ClosingPrice", "TradeVolume", "TradeValue"]
    table = {"fields": fields, "data": [["2026/09/01", "10", "12", "9", "11", "0", "0"]]}
    return {"code": entry["symbol"], "tables": [table]} if entry["market"] == "TPEX" else {"stat": "OK", "stockNo": entry["symbol"], **table}


class Clock:
    def __init__(self):
        self.value = 100.25
        self.early = False

    def now(self):
        return self.value

    def sleep(self, seconds):
        self.value += seconds / 2 if self.early and seconds > .001 else seconds


class HistoryAcquisitionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="mh-synthetic-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.artifacts, self.consumption = self.root / "evidence-root", self.root / "consumption-root"
        self.run = self.artifacts / "run-001"
        self.cutoffs = {"TWSE": "2026-09-01", "TPEX": "2026-09-02"}
        self.specs = [{"market": market, "product": product, "symbol": ("2330" if market == "TWSE" else "6488") if product == "stock" else None,
                       "period": "202609"} for market in ("TWSE", "TPEX") for product in ("benchmark", "stock")]
        self.plan = h.build_plan("a" * 40, universe(), self.specs, self.cutoffs, synthetic=True)
        self.seal = h.build_seal(self.plan, self.artifacts, self.consumption)
        self.candidate = h.candidate_authorization(self.seal)
        core = {k: v for k, v in self.candidate.items() if k not in ("authorization_id", "authorization_sha256")}
        core["status"] = h.AUTHORIZED
        self.auth = h.evidence.identified(core, "rate-history-acquisition-authorization-", "authorization_id", "authorization_sha256")
        self.clock = Clock()
        self.calls = []

    def capture(self, entry):
        self.calls.append(entry["request_key"])
        return {"raw_bytes": h.evidence.canonical(payload(entry)), "http_status": 200, "final_url": entry["request_url"], "content_type": "application/json"}

    def execute(self, capture=None, **kwargs):
        return h.execute(self.plan, self.seal, self.auth, artifacts_root=self.artifacts, consumption_root=self.consumption,
            output_root=self.run, trusted_authorization_sha256=self.auth["authorization_sha256"], synthetic=True,
            transport=capture or self.capture, utc=lambda: "2026-09-03T12:00:00Z", monotonic=self.clock.now, sleep=self.clock.sleep, **kwargs)

    def replay(self):
        return h.replay(self.run, self.plan, self.seal, self.auth, self.consumption)

    def entry(self, market="TWSE", product="stock"):
        return next(e for e in self.plan["entries"] if e["market"] == market and e["product"] == product)

    def parse(self, entry=None, value=None):
        entry = entry or self.entry()
        return parse_history(h.evidence.canonical(payload(entry) if value is None else value), entry,
                             observed_at="2026-09-03T12:00:00Z", cutoff=self.cutoffs[entry["market"]])

    def test_four_families_complete_immutable_lifecycle(self):
        result = self.execute()
        self.assertEqual(result["status"], "PASS")
        self.assertEqual((result["actual_requests"], result["completed_checkpoints"]), (4, 4))
        self.assertEqual(self.replay(), result)
        for family in ("intents", "raw", "receipts", "events", "checkpoints"):
            self.assertEqual(len(list((self.run / family).iterdir())), 4)
        self.assertEqual(result["coverage"]["issuer_count"], 1978)
        self.assertFalse(result["coverage"]["calendar_180_ready"])

    def test_pending_authorization_rejected_before_claim(self):
        self.auth = self.candidate
        with self.assertRaisesRegex(ValueError, "HISTORY_AUTHORIZATION_MISMATCH"):
            self.execute()
        self.assertFalse(self.run.exists())
        self.assertFalse(self.calls)

    def test_trusted_authorization_pin_required(self):
        with self.assertRaisesRegex(ValueError, "HISTORY_TRUSTED_AUTHORIZATION_PIN_REQUIRED"):
            h.preflight(self.plan, self.seal, self.auth, artifacts_root=self.artifacts, consumption_root=self.consumption, synthetic=True)

    def test_single_use_claim_before_first_transport(self):
        def capture(entry):
            record = h.read_metadata((self.consumption / (self.auth["authorization_id"] + ".json")).read_bytes())
            self.assertEqual(record["status"], "CONSUMED")
            self.assertTrue((self.run / "intents" / f"{entry['ordinal']:05}.json").exists())
            return self.capture(entry)
        self.execute(capture)
        with self.assertRaisesRegex(ValueError, "ALREADY_CONSUMED"):
            self.execute()
        self.assertEqual(len(self.calls), 4)

    def test_execution_root_reuse_rejected(self):
        self.run.mkdir(parents=True)
        with self.assertRaisesRegex(ValueError, "MUST_BE_NEW_CHILD"):
            self.execute()
        self.assertFalse(self.calls)

    def test_unknown_interruption_consumed_and_not_resumable(self):
        def interrupt(entry):
            raise SystemExit("SYNTHETIC_PROCESS_EXIT")
        with self.assertRaises(SystemExit):
            self.execute(interrupt)
        with self.assertRaisesRegex(ValueError, "HISTORY_UNKNOWN_OUTCOME_NO_RESUME"):
            self.replay()
        with self.assertRaisesRegex(ValueError, "ALREADY_CONSUMED"):
            self.execute()
        with self.assertRaisesRegex(ValueError, "RESUME_FORBIDDEN"):
            h.resume()

    def test_timeout_stops_first_and_persists(self):
        mock = Mock(side_effect=TimeoutError("synthetic"))
        result = self.execute(mock)
        self.assertEqual(result["status"], "STOPPED")
        self.assertEqual(mock.call_count, 1)
        self.assertEqual(self.replay(), result)
        self.assertEqual(h.read_metadata((self.run / "STOP.json").read_bytes())["reason"], "HISTORY_TIMEOUT_UNKNOWN_OUTCOME")

    def test_first_validation_failure_zero_subsequent_calls(self):
        def wrong(entry):
            response = self.capture(entry)
            response["raw_bytes"] = b"not-json"
            return response
        result = self.execute(wrong)
        self.assertEqual((result["actual_requests"], len(self.calls)), (1, 1))
        self.assertEqual(result["completed_checkpoints"], 0)
        self.assertEqual(self.replay(), result)

    def test_hard_request_budget(self):
        with self.assertRaisesRegex(ValueError, "REQUEST_BUDGET_EXCEEDED"):
            h.build_plan("a" * 40, universe(), self.specs, self.cutoffs, maximum_requests=3, synthetic=True)

    def test_duplicate_request_rejected(self):
        with self.assertRaisesRegex(ValueError, "DUPLICATE_REQUEST"):
            h.build_plan("a" * 40, universe(), [self.specs[0]] * 2, self.cutoffs, synthetic=True)

    def test_twelve_month_cap(self):
        specs = deepcopy(self.specs)
        specs[0]["period"] = "202409"
        with self.assertRaisesRegex(ValueError, "TWELVE_MONTH_CAP"):
            h.build_plan("a" * 40, universe(), specs, self.cutoffs, synthetic=True)

    def test_request_order_is_deterministic(self):
        self.assertEqual(self.plan, h.build_plan("a" * 40, universe(), list(reversed(self.specs)), self.cutoffs, synthetic=True))

    def test_wrong_request_market_rejected(self):
        specs = deepcopy(self.specs)
        specs[1]["symbol"] = "6488"
        with self.assertRaisesRegex(ValueError, "UNIVERSE_MISMATCH"):
            h.build_plan("a" * 40, universe(), specs, self.cutoffs, synthetic=True)

    def test_missing_universe_issuer_rejected(self):
        u = universe()
        u["stocks"].pop()
        with self.assertRaises(ValueError):
            h.build_plan("a" * 40, u, self.specs, self.cutoffs, synthetic=True)

    def test_synthetic_scope_never_real(self):
        with self.assertRaisesRegex(ValueError, "SYNTHETIC_SCOPE_FORBIDDEN"):
            h.preflight(self.plan, self.seal, self.auth, artifacts_root=self.artifacts, consumption_root=self.consumption,
                        trusted_authorization_sha256=self.auth["authorization_sha256"])

    def test_owner_drift_rejected_before_claim(self):
        with patch.object(h, "owners", return_value={"tampered": "0" * 64}), self.assertRaises(ValueError):
            self.execute()
        self.assertFalse(self.calls)

    def test_owner_drift_stops_before_next_transport(self):
        actual = h.owners
        broken = [False]
        def owner_check():
            if broken[0]:
                broken[0] = False
                return {"DRIFT": "0" * 64}
            return actual()
        def capture(entry):
            response = self.capture(entry)
            broken[0] = True
            return response
        with patch.object(h, "owners", side_effect=owner_check):
            result = self.execute(capture)
        self.assertEqual((result["actual_requests"], result["completed_checkpoints"], len(self.calls)), (1, 1, 1))
        self.assertEqual(self.replay(), result)

    def test_row_market_identity_is_not_overridden_by_request(self):
        value = payload(self.entry())
        value["fields"].append("market")
        value["data"][0].append("TPEX")
        with self.assertRaisesRegex(ValueError, "ROW_MARKET_MISMATCH"):
            self.parse(value=value)

    def test_second_writer_rejected_while_first_holds_lock(self):
        def capture(entry):
            with self.assertRaisesRegex(RuntimeError, "WRITER_ALREADY_ACTIVE"):
                with h.exclusive_scan(self.artifacts):
                    self.fail("SECOND_WRITER_ACQUIRED_LOCK")
            return self.capture(entry)
        self.assertEqual(self.execute(capture)["status"], "PASS")

    def test_authorization_budget_drift_rejected(self):
        self.auth["maximum_authorized_requests"] = 5
        with self.assertRaises(ValueError):
            self.execute()
        self.assertFalse(self.calls)

    def test_early_sleep_returns_are_compensated(self):
        self.clock.early = True
        self.execute()
        intents = [h.read_metadata(p.read_bytes()) for p in sorted((self.run / "intents").iterdir())]
        for intent in intents:
            d = intent["dispatch"]
            self.assertGreaterEqual(d["monotonic_timestamp"] - d["previous_wait_anchor_monotonic"], 13)
        self.replay()

    def test_session_cutoffs_not_forced_equal(self):
        result = self.execute()
        self.assertEqual(result["coverage"]["source_native_cutoffs"], self.cutoffs)
        self.assertNotEqual(*self.cutoffs.values())

    def test_tp_ex_units_remain_unproven_no_rescale(self):
        parsed = self.parse(self.entry("TPEX"))
        self.assertEqual(parsed["unit_scale_status"], "TPEX_UNIT_SCALE_QUALIFICATION_REQUIRED")
        self.assertFalse(parsed["unit_scale_applied"])
        self.assertEqual(parsed["normalized_sessions"][0]["volume"], 0)
        self.assertEqual(parsed["normalized_sessions"][0]["turnover"], 0)

    def test_missing_close_retained_never_zero_filled(self):
        value = payload(self.entry())
        value["data"][0][4] = " ---"
        parsed = self.parse(value=value)
        self.assertEqual(parsed["missing_rows"], 1)
        self.assertEqual(parsed["normalized_sessions"], [])
        self.assertEqual(parsed["records"][0]["raw_fields"]["ClosingPrice"], " ---")
        self.assertIsNone(parsed["records"][0]["normalized"])

    def test_all1978_missing_issuers_preserved(self):
        result = self.execute()
        rows = result["coverage"]["issuers"]
        self.assertEqual(len(rows), 1978)
        self.assertEqual({r["symbol"] for r in rows}, {r["symbol"] for r in universe()["stocks"]})
        self.assertTrue(all(r["status"] == "NOT_READY" for r in rows))
        self.assertTrue(all(not r["ranking_eligible"] for r in rows))

    def test_benchmark_chain_capable_of180_without_cross_market_alignment(self):
        days = []
        cursor = date(2025, 12, 1)
        while len(days) < 181:
            if cursor.weekday() < 5:
                days.append(cursor.isoformat())
            cursor += timedelta(days=1)
        def event(market, count):
            return {"market": market, "product": "benchmark", "symbol": None, "validation": {
                "normalized_sessions": [{"trade_date": d, "close": 100} for d in days[:count]]}}
        chains = benchmark_chains([event("TWSE", 180), event("TPEX", 181)])
        self.assertTrue(chains["TWSE"]["at_least_180"])
        self.assertTrue(chains["TPEX"]["at_least_180"])
        self.assertNotEqual(chains["TWSE"]["latest_session"], chains["TPEX"]["latest_session"])

    def test_benchmark_180_alone_not_full_calendar_credit(self):
        days = [(date(2026, 1, 1) + timedelta(days=i)).isoformat() for i in range(180)]
        events = [{"market": m, "product": "benchmark", "symbol": None, "validation": {"normalized_sessions": [{"trade_date": d} for d in days]}} for m in ("TWSE", "TPEX")]
        result = coverage_inventory(universe()["stocks"], events, {m: days[-1] for m in ("TWSE", "TPEX")})
        self.assertEqual(result["ready"], 0)
        self.assertFalse(result["calendar_180_ready"])
        self.assertTrue(all("PERIOD_MISSING" in r["reasons"] for r in result["issuers"]))

    def test_complete_issuer_ready_without_dropping_incomplete(self):
        days = [(date(2026, 1, 1) + timedelta(days=i)).isoformat() for i in range(180)]
        events = [{"market": m, "product": "benchmark", "symbol": None, "validation": {"normalized_sessions": [{"trade_date": d} for d in days]}} for m in ("TWSE", "TPEX")]
        events.append({"market": "TWSE", "product": "stock", "symbol": "2330", "validation": {
            "unit_scale_status": "PASS", "records": [{"trade_date": d, "status": "VALID", "normalized": {"trade_date": d}} for d in days]}})
        result = coverage_inventory(universe()["stocks"], events, {m: days[-1] for m in ("TWSE", "TPEX")})
        self.assertEqual(result["ready"], 1)
        self.assertEqual(result["not_ready"], 1977)
        self.assertEqual(result["issuer_count"], 1978)

    def test_stock_off_chain_date_is_retained_but_not_ready(self):
        days = [(date(2026, 1, 1) + timedelta(days=i)).isoformat() for i in range(180)]
        events = [{"market": m, "product": "benchmark", "symbol": None, "validation": {"normalized_sessions": [{"trade_date": d} for d in days]}} for m in ("TWSE", "TPEX")]
        extra = "2025-12-31"
        events.append({"market": "TWSE", "product": "stock", "symbol": "2330", "validation": {
            "unit_scale_status": "PASS", "records": [{"trade_date": d, "status": "VALID", "normalized": {"trade_date": d}} for d in [extra, *days]]}})
        result = coverage_inventory(universe()["stocks"], events, {m: days[-1] for m in ("TWSE", "TPEX")})
        issuer = next(r for r in result["issuers"] if r["symbol"] == "2330")
        self.assertEqual(issuer["status"], "NOT_READY")
        self.assertIn("SESSION_NOT_IN_VERIFIED_BENCHMARK_CHAIN", issuer["reasons"])
        self.assertEqual(issuer["unconfirmed_sessions"], [extra])
        self.assertEqual(len(issuer["partial_records"]), 181)

    def test_conflicting_stock_session_does_not_grant_calendar_credit(self):
        days = [(date(2026, 1, 1) + timedelta(days=i)).isoformat() for i in range(180)]
        events = [{"market": m, "product": "benchmark", "symbol": None, "validation": {"normalized_sessions": [{"trade_date": d} for d in days]}} for m in ("TWSE", "TPEX")]
        for market, symbol in (("TWSE", "2330"), ("TPEX", "6488")):
            dates = ["2025-12-31", *days] if market == "TWSE" else days
            events.append({"market": market, "product": "stock", "symbol": symbol, "validation": {
                "unit_scale_status": "PASS", "records": [{"trade_date": d, "status": "VALID", "normalized": {"trade_date": d}} for d in dates]}})
        result = coverage_inventory(universe()["stocks"], events, {m: days[-1] for m in ("TWSE", "TPEX")})
        self.assertFalse(result["calendar_180_ready"])
        self.assertEqual(result["issuer_count"], 1978)

    def test_cold_process_replay_does_not_dispatch(self):
        expected = self.execute()
        command = "import sys;sys.path.insert(0,sys.argv[1]);from scripts.verify_ci_applicability import network_guard;sys.addaudithook(network_guard);from src import history_acquisition_execution as h;from pathlib import Path;r=Path(sys.argv[2]);p=h.read_metadata((r/'plan.json').read_bytes());s=h.read_metadata((r/'seal.json').read_bytes());a=h.read_metadata((r/'authorization.json').read_bytes());v=h.replay(r,p,s,a,Path(sys.argv[3]));print(v['ledger_head'])"
        run = subprocess.run([sys.executable, "-B", "-c", command, str(ROOT), str(self.run), str(self.consumption)], capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(run.stdout.strip(), expected["ledger_head"])
        self.assertEqual(len(self.calls), 4)

    def test_write_once_objects_reject_overwrite(self):
        self.execute()
        path = self.run / "RESULT.json"
        with self.assertRaises(FileExistsError):
            h.evidence.put(path, b"replacement")

    def test_no_state_or_portfolio_paths_written(self):
        self.execute()
        all_files = {p.name for p in self.root.rglob("*") if p.is_file()}
        self.assertNotIn("LATEST.json", all_files)
        self.assertNotIn("RATE_PRODUCTION_SOURCE_BUNDLE_LATEST.json", all_files)
        result = self.replay()
        self.assertEqual(result["production_publications"], 0)
        self.assertEqual(result["ranking_executions"], 0)
        self.assertEqual(result["historical_pit"], "UNPROVEN")

    def test_dedicated_transport_exact_get_and_post_single_call(self):
        for entry in self.plan["entries"]:
            response = Mock()
            response.code = 200
            response.headers = {"Content-Type": "application/json"}
            response.read.return_value = b"{}"
            response.geturl.return_value = entry["request_url"]
            response.__enter__ = Mock(return_value=response)
            response.__exit__ = Mock(return_value=False)
            opener = Mock()
            opener.open.return_value = response
            with patch.object(transport, "build_opener", return_value=opener) as factory:
                captured = transport.dispatch_once(entry)
            self.assertEqual(opener.open.call_count, 1)
            req = opener.open.call_args.args[0]
            self.assertEqual(req.get_method(), entry["method"])
            self.assertEqual(opener.open.call_args.kwargs["timeout"], 30)
            self.assertTrue(any(isinstance(x, transport.NoRedirect) for x in factory.call_args.args))
            self.assertEqual(captured["raw_bytes"], b"{}")

    def test_transport_timeout_no_implicit_retry(self):
        opener = Mock()
        opener.open.side_effect = TimeoutError("synthetic")
        with patch.object(transport, "build_opener", return_value=opener), self.assertRaises(TimeoutError):
            transport.dispatch_once(self.entry())
        self.assertEqual(opener.open.call_count, 1)

    def test_transport_url_tamper_rejected_before_opener(self):
        e = deepcopy(self.entry())
        e["endpoint"] = "https://example.invalid"
        with patch.object(transport, "build_opener") as opener, self.assertRaisesRegex(ValueError, "BINDING_MISMATCH"):
            transport.dispatch_once(e)
        opener.assert_not_called()


def schema_case(change, reason):
    def test(self):
        value = payload(self.entry())
        change(value)
        with self.assertRaisesRegex(ValueError, reason):
            self.parse(value=value)
    return test


SCHEMA_CASES = {
    "wrong_symbol": (lambda p: p.update(stockNo="WRONG"), "SYMBOL_MISMATCH"),
    "wrong_market": (lambda p: p.update(market="TPEX"), "MARKET_MISMATCH"),
    "wrong_product": (lambda p: p.update(product="benchmark"), "PRODUCT_MISMATCH"),
    "wrong_declared_period": (lambda p: p.update(period="202608"), "PERIOD_MISMATCH"),
    "wrong_row_period": (lambda p: p["data"][0].__setitem__(0, "2026/08/31"), "PERIOD_MISMATCH"),
    "impossible_date": (lambda p: p["data"][0].__setitem__(0, "2026/09/31"), "DATE_INVALID"),
    "future_session": (lambda p: p["data"][0].__setitem__(0, "2026/09/30"), "FUTURE_SESSION"),
    "duplicate_session": (lambda p: p["data"].append(deepcopy(p["data"][0])), "DUPLICATE_SESSION"),
    "wrong_width": (lambda p: p["data"].append(["2026/09/01"]), "ROW_WIDTH_INVALID"),
    "duplicate_fields": (lambda p: p["fields"].__setitem__(1, "Date"), "SCHEMA_INVALID"),
    "bool_value": (lambda p: p["data"][0].__setitem__(4, True), "NUMERIC_INVALID"),
    "nan_value": (lambda p: p["data"][0].__setitem__(4, "NaN"), "NUMERIC_INVALID"),
    "inf_value": (lambda p: p["data"][0].__setitem__(4, "Infinity"), "NUMERIC_INVALID"),
    "overflow_value": (lambda p: p["data"][0].__setitem__(4, "1e9999"), "NUMERIC_INVALID"),
    "nonnumeric_value": (lambda p: p["data"][0].__setitem__(4, "---x"), "NUMERIC_INVALID"),
    "negative_close": (lambda p: p["data"][0].__setitem__(4, "-1"), "RANGE_INVALID"),
    "zero_close": (lambda p: p["data"][0].__setitem__(4, "0"), "RANGE_INVALID"),
    "negative_volume": (lambda p: p["data"][0].__setitem__(5, "-1"), "RANGE_INVALID"),
    "empty_period": (lambda p: p.update(data=[]), "EMPTY_PERIOD_UNQUALIFIED"),
    "missing_identity": (lambda p: p.pop("stockNo"), "SYMBOL_IDENTITY_REQUIRED"),
}
for name, (change, reason) in SCHEMA_CASES.items():
    setattr(HistoryAcquisitionTests, "test_schema_" + name, schema_case(change, reason))


def source_case(market, product):
    def test(self):
        parsed = self.parse(self.entry(market, product))
        self.assertEqual(parsed["source_validation"], "PASS")
        self.assertEqual((parsed["total_rows"], parsed["valid_rows"], parsed["invalid_rows"]), (1, 1, 0))
        self.assertEqual(parsed["records"][0]["raw_row_index"], 0)
        self.assertTrue(parsed["records"][0]["json_locator"].startswith("$"))
    return test
for market in ("TWSE", "TPEX"):
    for product in ("stock", "benchmark"):
        setattr(HistoryAcquisitionTests, "test_positive_" + market + "_" + product, source_case(market, product))


def stopped_case(key, value, reason):
    def test(self):
        def capture(entry):
            response = self.capture(entry)
            response[key] = value
            return response
        result = self.execute(capture)
        self.assertEqual(result["status"], "STOPPED")
        self.assertEqual(len(self.calls), 1)
        self.assertIn(reason, h.read_metadata((self.run / "STOP.json").read_bytes())["reason"])
        self.assertEqual(self.replay(), result)
    return test
for name, key, value, reason in (("http", "http_status", 503, "HTTP_FAILURE"),
        ("redirect", "final_url", "https://example.invalid", "REDIRECT_MISMATCH"),
        ("malformed_json", "raw_bytes", b"{broken", "JSON_INVALID"),
        ("duplicate_json", "raw_bytes", b'{"a":1,"a":2}', "JSON_INVALID"),
        ("bad_type", "content_type", "text/html", "POLICY_INVALID")):
    setattr(HistoryAcquisitionTests, "test_stop_" + name, stopped_case(key, value, reason))


def tamper_case(family):
    def test(self):
        self.execute()
        path = self.run / ("RESULT.json" if family == "result" else "consumption.json") if family in ("result", "consumption") else next((self.run / family).iterdir())
        if family == "raw":
            path.write_bytes(path.read_bytes() + b" ")
        else:
            value = h.read_metadata(path.read_bytes())
            value["TAMPER"] = True
            path.write_bytes(h.evidence.canonical(value))
        with self.assertRaises((ValueError, KeyError, FileNotFoundError)):
            self.replay()
    return test
for family in ("raw", "receipts", "intents", "events", "checkpoints", "result", "consumption"):
    setattr(HistoryAcquisitionTests, "test_tamper_" + family, tamper_case(family))


if __name__ == "__main__":
    unittest.main()
