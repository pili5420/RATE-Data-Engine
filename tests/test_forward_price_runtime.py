"""SYNTHETIC ONLY: official-product-shaped bytes, never live market evidence."""
from copy import deepcopy
from datetime import date, timedelta
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from src import provider_shadow_forward as f
from src import provider_forward_daily_prices as d
from src import provider_forward_price_runtime as r
from src.provider_shadow_forward_prices import load_prices
from src.provider_eps_candidate import _canonical
from src.eps_duration_facts.raw import sha256
from src.provider_eps_dispatch import DispatchGate
from tests.test_provider_shadow_forward import synthetic_shadow


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="SYNTHETIC-daily-runtime-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.now = "2026-09-01T00:00:00+00:00"
        for module in (f, d, r):
            obj = patch.object(module, "instant", side_effect=lambda: self.now)
            obj.start()
            self.addCleanup(obj.stop)
        self.snapshot = f.baseline(synthetic_shadow(), sealed_at=self.now, effective_at=self.now,
            execution_binding={"base_sha": "a" * 40, "head_sha": "b" * 40}, source_pin={"synthetic_only": True})
        self.baseline = self.root / "baseline.json"
        self.baseline.write_bytes(_canonical(self.snapshot))
        self.baseline_pin = {"path": str(self.baseline), "sha256": sha256(self.baseline.read_bytes())}
        self.ledger = self.root / "forward-candidate"
        f.create_baseline(self.ledger, self.snapshot, {k: None for k in f.KINDS})
        self.heads = f.heads(self.ledger)
        self.now = "2026-12-01T06:00:00+00:00"
        self.counter = 0

    def emit(self, folder, market, domain, payload, observed, period="202609"):
        name = str(self.counter)
        self.counter += 1
        raw = folder / (name + ".raw")
        raw.write_bytes(_canonical(payload))
        target = next(t for t in r.targets("2026-09-01T00:00:00Z", "2026-09-30") if t["market"] == market and t["domain"] == domain)
        if domain == "benchmark":
            target = next(t for t in r.targets("2026-09-01T00:00:00Z", period[:4] + "-" + period[4:] + "-28") if t["market"] == market and t["domain"] == domain and t["period"] == period)
        receipt = {**target, "synthetic_only": True, "http_status": 200, "final_url": target["endpoint"],
            "raw_path": str(raw), "raw_sha256": sha256(raw.read_bytes()), "bytes": raw.stat().st_size,
            "observed_at": observed, "source_validated_at": observed}
        path = folder / (name + ".receipt.json")
        path.write_bytes(_canonical(receipt))
        return {"receipt_path": str(path), "receipt_sha256": sha256(path.read_bytes())}

    def prices(self, through="2026-09-08", *, omit=None, suspended=None, missing_day=None, no_session=False, tpex_omit=None):
        folder = self.root / ("archive-" + str(self.counter))
        folder.mkdir()
        days = [date(2026, 9, 1) + timedelta(days=i) for i in range((date.fromisoformat(through) - date(2026, 9, 1)).days + 1)
            if (date(2026, 9, 1) + timedelta(days=i)).weekday() < 5]
        observed = through + "T14:00:00+08:00"
        sources = []
        for market in d.DAILY:
            chosen = [] if no_session else [day for day in days if (market, day.isoformat()) != tpex_omit]
            for period in d.periods_between("2026-09-01", through):
                rows = [[day.isoformat(), 10000 + i] for i, day in enumerate(chosen) if day.strftime("%Y%m") == period]
                payload = {"fields": ["Date", "ClosingIndex"], "data": rows} if market == "TWSE" else {
                    "tables": [{"fields": ["Date", "ClosingIndex"], "data": rows}]} if rows else {"tables": []}
                sources.append(self.emit(folder, market, "benchmark", payload, observed, period))
            daily_days = [date(2026, 8, 31)] if no_session else ([date(2026, 8, 31)] + chosen if tpex_omit else chosen)
            for day in daily_days:
                if (market, day.isoformat()) == missing_day:
                    continue
                values = []
                for i, company in enumerate(self.snapshot["companies"]):
                    if company["market"] != market or (company["symbol"], day.isoformat()) == omit:
                        continue
                    value = "--" if (company["symbol"], day.isoformat()) == suspended else str(100 + i * 0.01 + (day - date(2026, 9, 1)).days)
                    values.append({"Date": day.isoformat(), "Code" if market == "TWSE" else "SecuritiesCompanyCode": company["symbol"],
                        "ClosingPrice" if market == "TWSE" else "Close": value})
                sources.append(self.emit(folder, market, "market_daily", values, day.isoformat() + "T14:00:00+08:00"))
        manifest = {"artifact_kind": d.KIND, "input_mode": d.MODE, "generated_at": observed, "sessions_complete_through": through,
            "synthetic_only": True, "baseline_pin": self.baseline_pin, "shadow_snapshot_id": self.snapshot["shadow_snapshot_id"],
            "universe_id": self.snapshot["universe_id"], "universe": [{"symbol": c["symbol"], "market": c["market"]} for c in self.snapshot["companies"]],
            "source_identities": [{"path": str(Path(d.__file__)), "sha256": sha256(Path(d.__file__).read_bytes())}], "sources": sources}
        path = folder / "manifest.json"
        path.write_bytes(_canonical(manifest))
        return {"manifest_path": str(path), "manifest_sha256": sha256(path.read_bytes())}

    def mutate_manifest(self, pin, mutate):
        path = Path(pin["manifest_path"])
        value = json.loads(path.read_bytes())
        mutate(value)
        path.write_bytes(_canonical(value))
        return {"manifest_path": str(path), "manifest_sha256": sha256(path.read_bytes())}

    def load(self, pin):
        return load_prices(pin, as_of=self.now, available_at=self.snapshot["forward_available_at"])

    def test_daily_market_wide_uses_existing_parser_and_raw_locator(self):
        book = self.load(self.prices())
        self.assertEqual(len(book["prices"]), 21 * 6)
        self.assertEqual(book["prices"][("1000", "2026-09-01")]["reference"]["json_locator"], "$[0]")
        self.assertEqual(len(book["session_coverage"]), 12)

    def test_no_session_joint_observation_never_creates_entry(self):
        book = self.load(self.prices("2026-09-01", no_session=True))
        self.assertEqual(book["sessions"], {"TWSE": [], "TPEX": []})
        self.assertTrue(all(r["status"] == "NO_SESSION_OBSERVED" for r in book["calendar_observations"]))
        self.assertFalse(book["calendar_reason_proven"])
        pending = f.resolve_returns(self.snapshot, 5, book, as_of=self.now, prior_rows=f.initial_returns(self.snapshot, 5)["returns"])
        self.assertTrue(all(r["entry_price"] is None and r["status"] == "PENDING" for r in pending["returns"]))

    def test_first_post_seal_session_frozen(self):
        f.update(self.ledger, self.heads, self.snapshot["shadow_snapshot_id"], self.prices("2026-09-01"), as_of=self.now)
        rows = f.replay_chain(self.ledger, f.KINDS[1])[-1]["payload"]["returns"]
        self.assertTrue(all(r["entry_price_date"] == "2026-09-01" for r in rows))
        self.assertTrue(all(r["status"] == "PENDING" for r in rows))
        self.assertTrue(all(r["price_source"] == r["market"]+"_OFFICIAL_MARKET_DAILY" for r in rows))

    def test_markets_have_distinct_session_chains(self):
        book = self.load(self.prices(tpex_omit=("TPEX", "2026-09-01")))
        self.assertEqual(book["sessions"]["TWSE"][0]["date"], "2026-09-01")
        self.assertEqual(book["sessions"]["TPEX"][0]["date"], "2026-09-02")

    def test_missing_symbol_entry_fail_closed_not_late_entry(self):
        pin = self.prices(omit=("1000", "2026-09-01"))
        book = self.load(pin)
        self.assertIn("1000", book["session_coverage"][0]["missing_symbols"])
        rows = f.resolve_returns(self.snapshot, 5, book, as_of=self.now, prior_rows=f.initial_returns(self.snapshot, 5)["returns"])["returns"]
        row = next(r for r in rows if r["symbol"] == "1000")
        self.assertEqual(row["status"], "FAIL_CLOSED")
        self.assertIsNone(row["entry_price"])

    def test_suspended_entry_is_preserved_invalid_not_zero(self):
        book = self.load(self.prices(suspended=("1000", "2026-09-01")))
        self.assertEqual(book["session_coverage"][0]["invalid_symbols"][0]["symbol"], "1000")
        self.assertNotIn(("1000", "2026-09-01"), book["prices"])

    def test_delisted_or_missing_required_path_fail_closed(self):
        book = self.load(self.prices(omit=("1000", "2026-09-08")))
        rows = f.resolve_returns(self.snapshot, 5, book, as_of=self.now, prior_rows=f.initial_returns(self.snapshot, 5)["returns"])["returns"]
        self.assertEqual(next(r for r in rows if r["symbol"] == "1000")["status"], "FAIL_CLOSED")

    def test_market_day_gap_cannot_be_skipped(self):
        with self.assertRaisesRegex(Exception, "SESSION_MARKET_EVIDENCE_GAP"):
            self.load(self.prices(missing_day=("TWSE", "2026-09-01")))

    def test_wrong_universe_rejected(self):
        pin = self.mutate_manifest(self.prices(), lambda m: m["universe"].pop())
        with self.assertRaisesRegex(Exception, "UNIVERSE_MISMATCH"):
            self.load(pin)

    def test_wrong_snapshot_identity_rejected(self):
        pin = self.mutate_manifest(self.prices(), lambda m: m.update(shadow_snapshot_id="forged"))
        with self.assertRaisesRegex(Exception, "BASELINE_BINDING_MISMATCH"):
            self.load(pin)

    def test_raw_tamper_rejected(self):
        pin = self.prices()
        manifest = json.loads(Path(pin["manifest_path"]).read_bytes())
        receipt = json.loads(Path(manifest["sources"][0]["receipt_path"]).read_bytes())
        Path(receipt["raw_path"]).write_bytes(b"{}")
        with self.assertRaisesRegex(Exception, "SOURCE_TAMPERED"):
            self.load(pin)

    def test_receipt_tamper_rejected(self):
        pin = self.prices()
        m = json.loads(Path(pin["manifest_path"]).read_bytes())
        Path(m["sources"][0]["receipt_path"]).write_bytes(b"{}")
        with self.assertRaisesRegex(Exception, "SOURCE_TAMPERED"):
            self.load(pin)

    def test_manifest_tamper_rejected(self):
        pin = self.prices()
        Path(pin["manifest_path"]).write_bytes(b"{}")
        with self.assertRaisesRegex(Exception, "SOURCE_TAMPERED"):
            self.load(pin)

    def test_future_generated_at_rejected(self):
        pin = self.mutate_manifest(self.prices(), lambda m: m.update(generated_at="2026-12-02T00:00:00Z"))
        with self.assertRaisesRegex(Exception, "TIME_INVALID"):
            self.load(pin)

    def test_pre_close_coverage_rejected(self):
        pin = self.prices("2026-09-01")
        self.now = "2026-09-01T05:29:59+00:00"
        with self.assertRaises(Exception):
            self.load(pin)

    def test_post_close_gate_exact_boundary(self):
        d.post_close("2026-09-01", "2026-09-01T05:30:00Z", self.now)
        with self.assertRaisesRegex(Exception, "PRE_CLOSE"):
            d.post_close("2026-09-01", "2026-09-01T05:29:59Z", self.now)

    def test_duplicate_symbol_rejected(self):
        row = {"Date": "2026-09-01", "Code": "1000", "ClosingPrice": "100"}
        with self.assertRaisesRegex(Exception, "DUPLICATE"):
            d.daily_rows([row, row], "TWSE")

    def test_conflicting_duplicate_rejected(self):
        row = {"Date": "2026-09-01", "Code": "1000", "ClosingPrice": "100"}
        with self.assertRaisesRegex(Exception, "DUPLICATE"):
            d.daily_rows([row, {**row, "ClosingPrice": "101"}], "TWSE")

    def test_invalid_nonfinite_nonpositive_close_rejected(self):
        for v in ("NaN", "Infinity", "1e9999", "0", "-1", True, "wrong"):
            with self.subTest(v=v), self.assertRaises(Exception):
                d.daily_rows([{"Date": "2026-09-01", "Code": "1000", "ClosingPrice": v}], "TWSE")

    def test_mixed_date_rejected(self):
        with self.assertRaisesRegex(Exception, "WRONG_DATE"):
            d.daily_rows([{"Date": "2026-09-01", "Code": "1000", "ClosingPrice": "1"},
                {"Date": "2026-09-02", "Code": "1001", "ClosingPrice": "1"}], "TWSE")

    def test_wrong_market_schema_rejected(self):
        with self.assertRaisesRegex(Exception, "SCHEMA_MISMATCH"):
            d.daily_rows([{"Date": "2026-09-01", "Code": "1000", "ClosingPrice": "1"}], "TPEX")

    def test_duplicate_json_key_and_nonfinite_payload_rejected(self):
        for v in (b'[{"Date":1,"Date":2}]', b'[{"close":NaN}]', b'[{"close":1e9999}]'):
            with self.assertRaises(Exception):
                d.read_payload(v)

    def test_5d_maturity_and_gate_only_one_of_twenty(self):
        f.update(self.ledger, self.heads, self.snapshot["shadow_snapshot_id"], self.prices(), as_of=self.now)
        cp = f.checkpoint(self.ledger, f.heads(self.ledger))
        self.assertEqual(cp["gates"]["A"]["completed_valid_snapshots"], 1)
        self.assertEqual(cp["gates"]["A"]["status"], "INCONCLUSIVE")
        self.assertEqual(cp["gates"]["B"]["completed_valid_snapshots"], 0)

    def test_20d_maturity_market_offsets(self):
        f.update(self.ledger, self.heads, self.snapshot["shadow_snapshot_id"], self.prices("2026-09-29"), as_of=self.now)
        event = next(e for e in reversed(f.replay_chain(self.ledger, f.KINDS[1])) if e["payload"]["horizon"] == 20)
        self.assertTrue(all(r["exit_price_date"] == "2026-09-29" and r["status"] == "FINALIZED" for r in event["payload"]["returns"]))

    def test_60d_maturity_market_offsets(self):
        f.update(self.ledger, self.heads, self.snapshot["shadow_snapshot_id"], self.prices("2026-11-24"), as_of=self.now)
        event = next(e for e in reversed(f.replay_chain(self.ledger, f.KINDS[1])) if e["payload"]["horizon"] == 60)
        self.assertTrue(all(r["exit_price_date"] == "2026-11-24" and r["status"] == "FINALIZED" for r in event["payload"]["returns"]))

    def test_duplicate_update_idempotent(self):
        pin = self.prices()
        f.update(self.ledger, self.heads, self.snapshot["shadow_snapshot_id"], pin, as_of=self.now)
        expected = f.heads(self.ledger)
        f.update(self.ledger, expected, self.snapshot["shadow_snapshot_id"], pin, as_of=self.now)
        self.assertEqual(expected, f.heads(self.ledger))

    def test_checkpoint_mismatch_rejected(self):
        with self.assertRaisesRegex(Exception, "HEAD_MISMATCH"):
            f.update(self.ledger, {k: "a" * 64 for k in f.KINDS}, self.snapshot["shadow_snapshot_id"], self.prices(), as_of=self.now)

    def test_ledger_truncation_rejected(self):
        next((self.ledger / f.KINDS[1]).glob("*.json")).unlink()
        with self.assertRaises(Exception):
            f.verify(self.ledger, self.heads)

    def test_original_snapshot_and_events_never_changed(self):
        before = {str(p): p.read_bytes() for p in self.ledger.rglob("*.json")}
        f.update(self.ledger, self.heads, self.snapshot["shadow_snapshot_id"], self.prices(), as_of=self.now)
        self.assertTrue(all(Path(p).read_bytes() == b for p, b in before.items()))
        self.assertEqual(len(f.replay_chain(self.ledger, f.KINDS[0])), 1)

    def test_unknown_daily_mode_does_not_enable_fallback(self):
        pin = self.mutate_manifest(self.prices(), lambda m: m.update(input_mode="UNKNOWN"))
        with self.assertRaises(Exception):
            self.load(pin)

    def test_source_identity_hash_tamper_rejected(self):
        pin = self.mutate_manifest(self.prices(), lambda m: m["source_identities"][0].update(sha256="0" * 64))
        with self.assertRaisesRegex(Exception, "SOURCE_TAMPERED"):
            self.load(pin)

    def test_duplicate_daily_snapshot_rejected(self):
        pin = self.mutate_manifest(self.prices(), lambda m: m["sources"].append(m["sources"][1]))
        with self.assertRaises(Exception):
            self.load(pin)

    def test_missing_monthly_benchmark_rejected(self):
        pin = self.mutate_manifest(self.prices(), lambda m: m["sources"].pop(0))
        with self.assertRaisesRegex(Exception, "MONTH_GAP"):
            self.load(pin)

    def test_cold_process_verifies_same_price_and_ledger_heads(self):
        pin = self.prices()
        f.update(self.ledger, self.heads, self.snapshot["shadow_snapshot_id"], pin, as_of=self.now)
        headfile = self.root / "heads.json"
        headfile.write_text(json.dumps(f.heads(self.ledger)))
        code = "import json,sys; from src.provider_shadow_forward import verify; print(verify(sys.argv[1],json.load(open(sys.argv[2]))))"
        # Future synthetic evidence uses an isolated fake clock, never a real record.
        code = "from src import provider_forward_daily_prices as d, provider_shadow_forward as f; d.instant=f.instant=lambda:'2026-12-01T06:00:00Z'; " + code
        result = subprocess.run([sys.executable, "-B", "-c", code, str(self.ledger), str(headfile)], cwd=Path(__file__).parents[1], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("PASS", result.stdout)

    def full_plan(self):
        self.now = "2026-09-01T00:00:00Z"
        shadow = synthetic_shadow()
        rows = []
        for market, count, first in (("TWSE", 1085, 1000), ("TPEX", 893, 6000)):
            for i in range(count):
                scored = market == "TWSE" and i < 20
                rows.append({"symbol": str(first + i), "market": market, f.SCORE: float(20-i) if scored else None,
                    "shadow_rank": i+1 if scored else None, "unscored_reasons": [] if scored else ["SYNTHETIC_ONLY"],
                    "features": {"synthetic_feature": {"input_observed_at_max": "2026-08-30T00:00:00Z"}} if scored else {}})
        shadow["core"]["companies"] = rows
        snapshot = f.baseline(shadow, sealed_at=self.now, effective_at=self.now,
            execution_binding={"base_sha": "a"*40, "head_sha": "b"*40}, source_pin={"synthetic_only": True})
        baseline = self.root / "full-baseline.json"
        baseline.write_bytes(_canonical(snapshot))
        ledger = self.root / "full-forward"
        f.create_baseline(ledger, snapshot, {k: None for k in f.KINDS})
        cp = self.root / "full-cp.json"
        cp.write_bytes(_canonical(f.checkpoint(ledger, f.heads(ledger))))
        directory = self.root / "runtime"
        pin = r.prepare(directory, {"path":str(baseline),"sha256":sha256(baseline.read_bytes())},
            {"path":str(cp),"sha256":sha256(cp.read_bytes())}, ledger, {"base_sha":"c"*40,"head_sha":"d"*40}, "2026-09-01")
        return directory, pin, r.pinned(pin["path"],pin["sha256"])

    def fake_capture(self, plan, *, bad_status=None, wrong_daily=False):
        calls = []
        class Response(io.BytesIO):
            def __init__(self, body, url):
                super().__init__(body)
                self.url = url
                self.headers = {"Content-Type":"application/json","Content-Length":str(len(body))}
            def geturl(self): return self.url
            def getcode(self): return bad_status or 200
        def opener(req, timeout):
            target = plan["targets"][len(calls)]
            calls.append(target)
            if target["domain"] == "benchmark":
                raw = {"fields":["Date","ClosingIndex"],"data":[["2026-09-01",1000]]} if target["market"]=="TWSE" else {
                    "tables":[{"fields":["Date","ClosingIndex"],"data":[["2026-09-01",1000]]}]}
            else:
                raw = [{"Date":"2026-09-02" if wrong_daily else "2026-09-01", "Code" if target["market"]=="TWSE" else "SecuritiesCompanyCode":
                    "1000" if target["market"]=="TWSE" else "6000", "ClosingPrice": "100"}]
            return Response(_canonical(raw),req.full_url)
        clock = [0.25]
        def sleep(seconds): clock[0] += seconds
        gate = DispatchGate(13, prior_dispatch=True, clock=lambda:clock[0], sleep=sleep, utc=lambda:self.now)
        return opener, gate, calls

    def test_builder_plan_exact_1978_and_four_requests(self):
        directory, pin, plan = self.full_plan()
        self.assertEqual(plan["max_requests"],4)
        self.assertFalse(plan["new_shadow_snapshot_allowed"])
        self.now="2026-09-01T06:00:00Z"
        opener,gate,calls=self.fake_capture(plan)
        result=r.acquire(directory,pin,opener=opener,gate=gate)
        self.assertEqual(len(calls),4)
        self.assertEqual(len(r.validate_runtime_dispatches(directory,plan)),4)
        book=load_prices(result,as_of=self.now,available_at=plan["forward_available_at"])
        self.assertEqual(len(book["session_coverage"][0]["expected_symbols"]),1085)
        self.assertEqual(len(book["session_coverage"][1]["expected_symbols"]),893)

    def test_builder_pre_close_zero_transport_calls(self):
        directory,pin,plan=self.full_plan()
        opener,gate,calls=self.fake_capture(plan)
        with self.assertRaisesRegex(Exception,"PRE_CLOSE_NO_REQUEST"):
            r.acquire(directory,pin,opener=opener,gate=gate)
        self.assertEqual(calls,[])

    def test_builder_http_failure_saved_and_no_following_requests(self):
        directory,pin,plan=self.full_plan()
        self.now="2026-09-01T06:00:00Z"
        opener,gate,calls=self.fake_capture(plan,bad_status=403)
        with self.assertRaisesRegex(Exception,"HTTP"):
            r.acquire(directory,pin,opener=opener,gate=gate)
        self.assertEqual(len(calls),1)
        self.assertEqual(len(list((directory/"receipts").glob("*.json"))),1)
        self.assertTrue((directory/"DEFECT_EVIDENCE.json").exists())
        with self.assertRaisesRegex(Exception,"NO_AUTOMATIC_RETRY"):
            r.acquire(directory,pin,opener=opener,gate=gate)
        self.assertEqual(len(calls),1)

    def test_builder_wrong_date_stops_before_third_call(self):
        directory,pin,plan=self.full_plan()
        self.now="2026-09-01T06:00:00Z"
        opener,gate,calls=self.fake_capture(plan,wrong_daily=True)
        with self.assertRaisesRegex(Exception,"FUTURE_DAILY_DATE"):
            r.acquire(directory,pin,opener=opener,gate=gate)
        self.assertEqual(len(calls),2)

    def test_builder_plan_tamper_rejected_before_request(self):
        directory,pin,plan=self.full_plan()
        Path(pin["path"]).write_bytes(b"{}")
        self.now="2026-09-01T06:00:00Z"
        opener,gate,calls=self.fake_capture(plan)
        with self.assertRaises(Exception):
            r.acquire(directory,pin,opener=opener,gate=gate)
        self.assertEqual(calls,[])

    def test_builder_unknown_intent_no_retry(self):
        directory,pin,plan=self.full_plan()
        (directory/"intents").mkdir()
        (directory/"intents"/"unknown.json").write_bytes(b"{}")
        self.now="2026-09-01T06:00:00Z"
        opener,gate,calls=self.fake_capture(plan)
        with self.assertRaisesRegex(Exception,"NO_AUTOMATIC_RETRY"):
            r.acquire(directory,pin,opener=opener,gate=gate)
        self.assertEqual(calls,[])

    def rewrite_receipt(self, pin, change):
        def update_manifest(m):
            item=m["sources"][0]
            path=Path(item["receipt_path"])
            receipt=json.loads(path.read_bytes())
            change(receipt)
            path.write_bytes(_canonical(receipt))
            item["receipt_sha256"]=sha256(path.read_bytes())
        return self.mutate_manifest(pin,update_manifest)

    def test_resigned_future_observation_rejected(self):
        pin=self.rewrite_receipt(self.prices(),lambda r:r.update(observed_at="2026-12-02T06:00:00Z",source_validated_at="2026-12-02T06:00:00Z"))
        with self.assertRaisesRegex(Exception,"TIME_MISMATCH"):
            self.load(pin)

    def test_resigned_wrong_market_receipt_rejected(self):
        pin=self.rewrite_receipt(self.prices(),lambda r:r.update(market="TPEX"))
        with self.assertRaisesRegex(Exception,"TPEX_PRODUCT"):
            self.load(pin)

    def test_receipt_http_redirect_rejected_even_if_hashes_valid(self):
        pin=self.rewrite_receipt(self.prices(),lambda r:r.update(final_url="https://example.invalid"))
        with self.assertRaisesRegex(Exception,"HTTP_RECEIPT"):
            self.load(pin)

    def test_builder_network_unknown_outcome_persisted_no_retry(self):
        directory,pin,plan=self.full_plan()
        self.now="2026-09-01T06:00:00Z"
        _,gate,calls=self.fake_capture(plan)
        def broken(req,timeout):
            calls.append(req.full_url)
            raise TimeoutError("SYNTHETIC_ONLY")
        with self.assertRaises(TimeoutError):
            r.acquire(directory,pin,opener=broken,gate=gate)
        result=json.loads((directory/"DEFECT_EVIDENCE.json").read_bytes())
        self.assertTrue(result["request_outcome_unknown"])
        self.assertEqual(result["stop_reason"],"REQUEST_OUTCOME_UNKNOWN_NO_AUTOMATIC_RETRY")
        self.assertEqual(len(calls),1)


class BenchmarkCompatibilityTests(unittest.TestCase):
    """SYNTHETIC ONLY: exact benchmark aliases, not stock-price aliases."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="SYNTHETIC-benchmark-schema-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.now = "2026-09-02T06:00:00+00:00"
        clock = patch.object(d, "instant", return_value=self.now)
        clock.start()
        self.addCleanup(clock.stop)

    def payload(self, aliases=None):
        aliases = {"收市": "1,234.50"} if aliases is None else aliases
        return {"synthetic_only": True, "tables": [{"fields": ["日期", *aliases],
            "data": [["115/09/01", *aliases.values()]]}]}

    def receipt(self, market="TPEX"):
        target = next(t for t in r.targets("2026-09-01T00:00:00Z", "2026-09-02")
            if t["market"] == market and t["domain"] == "benchmark")
        return {**target, "http_status": 200, "observed_at": self.now, "synthetic_only": True}

    def parse(self, payload, market="TPEX"):
        return d.benchmark_rows(self.receipt(market), payload, "2026-09-02", self.now)

    def test_tpex_exact_close_alias_reaches_existing_helper(self):
        rows = self.parse(self.payload())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["close"], 1234.5)
        self.assertEqual(rows[0]["trade_date"], "2026-09-01")

    def test_multiple_close_aliases_same_numeric_value_pass(self):
        rows = self.parse(self.payload({"收市": "1,234.50", "ClosingIndex": 1234.5, "close": "1234.500"}))
        self.assertEqual(rows[0]["close"], 1234.5)

    def test_multiple_close_aliases_conflicting_values_rejected(self):
        with self.assertRaisesRegex(Exception, "^DAILY_BENCHMARK_CLOSE_FIELD_CONFLICT$"):
            self.parse(self.payload({"收市": "1234.50", "ClosingIndex": "1234.51"}))

    def test_conflict_not_hidden_by_float_rounding(self):
        with self.assertRaisesRegex(Exception, "^DAILY_BENCHMARK_CLOSE_FIELD_CONFLICT$"):
            self.parse(self.payload({"收市": "1234.50000000000000001", "ClosingIndex": "1234.50000000000000002"}))

    def test_empty_non_numeric_zero_negative_close_rejected_in_domain(self):
        for value in (None, "", "--", "not-a-number", 0, -1, True, "NaN", "Infinity", "1e9999"):
            with self.subTest(value=value), self.assertRaisesRegex(Exception, "^DAILY_BENCHMARK_CLOSE_INVALID$"):
                self.parse(self.payload({"收市": value}))

    def test_invalid_secondary_alias_not_ignored(self):
        with self.assertRaisesRegex(Exception, "^DAILY_BENCHMARK_CLOSE_INVALID$"):
            self.parse(self.payload({"收市": "1234.5", "ClosingIndex": None}))

    def test_unknown_close_field_rejected(self):
        with self.assertRaisesRegex(Exception, "^DAILY_BENCHMARK_CLOSE_FIELD_MISSING$"):
            self.parse(self.payload({"未知欄位": "1234.5"}))

    def test_similar_names_not_fuzzy_matched(self):
        for name in ("收市價", "收市 ", "今日收市", "收", "市"):
            with self.subTest(name=name), self.assertRaisesRegex(Exception, "^DAILY_BENCHMARK_CLOSE_FIELD_MISSING$"):
                self.parse(self.payload({name: "1234.5"}))

    def test_stock_price_close_alias_not_accepted_as_benchmark(self):
        with self.assertRaisesRegex(Exception, "^DAILY_BENCHMARK_CLOSE_FIELD_MISSING$"):
            self.parse(self.payload({"ClosingPrice": "1234.5"}))

    def test_tpex_alias_not_accepted_for_twse(self):
        with self.assertRaisesRegex(Exception, "^DAILY_BENCHMARK_CLOSE_FIELD_MISSING$"):
            self.parse({"fields": ["日期", "收市"], "data": [["115/09/01", "1234.5"]]}, "TWSE")

    def test_twse_existing_aliases_unchanged(self):
        for name in ("ClosingIndex", "收盤指數", "close"):
            with self.subTest(name=name):
                rows = self.parse({"fields": ["日期", name], "data": [["115/09/01", "1234.5"]]}, "TWSE")
                self.assertEqual(rows[0]["close"], 1234.5)

    def test_mapping_preserves_raw_value_field_and_exact_locator(self):
        mapping = self.parse(self.payload())[0]["close_compatibility"]
        self.assertEqual(mapping["original_field"], "收市")
        self.assertEqual(mapping["canonical_field"], "close")
        self.assertEqual(mapping["raw_value"], "1,234.50")
        self.assertEqual(mapping["json_locator"], "$.tables[0].data[0][1]")
        self.assertEqual(mapping["raw_row_index"], 0)
        self.assertEqual(mapping["trade_date"], "2026-09-01")

    def test_dictionary_row_locator(self):
        mapping = self.parse({"data": [{"Date": "2026-09-01", "收市": "1234.5"}]})[0]["close_compatibility"]
        self.assertEqual(mapping["json_locator"], '$.data[0]["收市"]')

    def test_raw_receipt_and_payload_not_mutated(self):
        payload = self.payload()
        raw = self.root / "synthetic.raw"
        receipt = self.root / "synthetic.receipt.json"
        raw.write_bytes(_canonical(payload))
        receipt.write_bytes(_canonical({**self.receipt(), "raw_sha256": sha256(raw.read_bytes())}))
        before = (raw.read_bytes(), receipt.read_bytes(), deepcopy(payload))
        self.parse(payload)
        self.assertEqual(before, (raw.read_bytes(), receipt.read_bytes(), payload))

    def test_all_rows_reach_helper_without_parser_row_loss(self):
        payload = self.payload()
        payload["tables"][0]["data"].append(["115/09/02", "1235.5"])
        rows = self.parse(payload)
        self.assertEqual([row["trade_date"] for row in rows], ["2026-09-01", "2026-09-02"])
        self.assertEqual([row["close"] for row in rows], [1234.5, 1235.5])

    def test_normalized_payload_not_misrepresented_as_raw(self):
        original = self.payload()
        original_helper = d._benchmark_month_rows
        with patch.object(d, "_benchmark_month_rows", wraps=original_helper) as helper:
            self.parse(original)
        adapter = helper.call_args.args[0]
        self.assertIsNot(adapter.payload, original)
        self.assertEqual(adapter.payload["data"][0]["close"], "1234.50")
        self.assertNotIn("close", original["tables"][0]["fields"])


if __name__ == "__main__":
    unittest.main()
