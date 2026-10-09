"""SYNTHETIC ENGINEERING ONLY. Not real prices or realized forward evidence."""
from copy import deepcopy
from datetime import date, timedelta
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from src import provider_shadow_forward as f
from src.provider_shadow_forward_prices import load_prices
from src.provider_eps_candidate import _canonical
from src.eps_duration_facts.model import Rejected
from src.eps_duration_facts.raw import sha256
from src.provider_eps_dispatch import exclusive_scan


def synthetic_shadow():
    rows = [{"symbol": str(1000 + i), "market": "TWSE", f.SCORE: float(i), "shadow_rank": 20 - i,
        "unscored_reasons": [], "features": {"synthetic_feature": {"input_observed_at_max": "2026-08-30T00:00:00Z"}}} for i in range(20)]
    rows += [{"symbol": "9999", "market": "TPEX", f.SCORE: None, "shadow_rank": None,
        "unscored_reasons": ["SYNTHETIC_MISSING_INPUT"], "features": {}}]
    return {"content_sha256": "a" * 64, "package_sha256": "b" * 64,
        "execution": {"shadow_available_at": "2026-08-31T00:00:00Z", "execution_code_binding": {"head_sha": "1" * 40}},
        "core": {"feature_content_sha256": "c" * 64, "populations": {"A_COMPLETE_INPUT": {"population_id": "synthetic-only"}}, "companies": rows}}


class ForwardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="SYNTHETIC-forward-")
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.root = self.directory / "candidate-forward"
        self.now = "2026-09-01T00:00:00+00:00"
        self.clock = patch.object(f, "instant", side_effect=lambda: self.now)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.shadow = synthetic_shadow()
        self.snapshot = self.make_snapshot()
        self.empty = {k: None for k in f.KINDS}

    def tearDown(self):
        self.clock.stop()
        self.temp.cleanup()

    def make_snapshot(self):
        return f.baseline(self.shadow, sealed_at=self.now, effective_at=self.now,
            execution_binding={"base_sha": "2" * 40, "head_sha": "3" * 40}, source_pin={"synthetic_only": True})

    def start(self):
        return f.create_baseline(self.root, self.snapshot, self.empty)

    def archives(self, *, omit=None, end="2026-09-30", negative=False):
        path = self.directory / "synthetic-archives"
        path.mkdir(exist_ok=True)
        days = [date(2026, 9, 1) + timedelta(days=i) for i in range(30) if (date(2026, 9, 1) + timedelta(days=i)).weekday() < 5]
        sources = []
        def emit(market, domain, symbol=None):
            field_names = ["Date", "OpeningPrice", "HighestPrice", "LowestPrice", "ClosingPrice", "TradeVolume", "TradeValue"] if domain == "stock" else ["Date", "ClosingIndex"]
            if market == "TPEX" and domain == "stock":
                field_names = ["Date", "Open", "High", "Low", "Close", "Trade unit", "Trade Amt.(NTD1000)"]
            data = []
            for index, d in enumerate(days):
                if omit == (symbol, d.isoformat()):
                    continue
                price = -1 if negative and index == 0 else 100 + (int(symbol or "1000") - 999) * index
                data.append([d.isoformat(), price, price, price, price, 100, 1000] if domain == "stock" else [d.isoformat(), 1000 + index])
            raw = {"stat": "OK", "stockNo": symbol, "fields": field_names, "data": data} if market == "TWSE" else {"code": symbol, "tables": [{"subtitle": str(symbol), "fields": field_names, "data": data}]}
            name = market + "-" + domain + "-" + str(symbol)
            raw_path = path / (name + ".raw.json")
            raw_path.write_bytes(_canonical(raw))
            if market == "TWSE":
                endpoint = "https://www.twse.com.tw/rwd/zh/" + (f"afterTrading/STOCK_DAY?date=20260901&stockNo={symbol}&response=json" if domain == "stock" else "TAIEX/MI_5MINS_HIST?date=20260901&response=json")
            else:
                endpoint = "https://www.tpex.org.tw/www/" + ("en-us/afterTrading/tradingStock" if domain == "stock" else "zh-tw/indexInfo/inx")
            receipt = {"synthetic_only": True, "market": market, "domain": domain, "symbol": symbol, "period": "202609",
                "endpoint": endpoint, "final_url": endpoint, "http_status": 200, "request_method": "GET" if market == "TWSE" else "POST",
                "request_params": {"date": "2026/09/01", "code": symbol}, "observed_at": "2026-10-01T14:00:00+08:00",
                "raw_path": str(raw_path), "raw_sha256": sha256(raw_path.read_bytes()), "bytes": raw_path.stat().st_size}
            receipt_path = path / (name + ".receipt.json")
            receipt_path.write_bytes(_canonical(receipt))
            sources.append({"receipt_path": str(receipt_path), "receipt_sha256": sha256(receipt_path.read_bytes())})
        for market in ("TWSE", "TPEX"):
            emit(market, "benchmark")
        for c in self.snapshot["companies"]:
            emit(c["market"], "stock", c["symbol"])
        manifest_path = path / "manifest.json"
        manifest_path.write_bytes(_canonical({"artifact_kind": "RATE_OFFICIAL_FORWARD_PRICE_ARCHIVE_MANIFEST_V1", "synthetic_only": True, "sessions_complete_through": end, "sources": sources}))
        return {"manifest_path": str(manifest_path), "manifest_sha256": sha256(manifest_path.read_bytes())}

    def book(self, **kwargs):
        self.now = "2026-10-08T00:00:00+00:00"
        pin = self.archives(**kwargs)
        return load_prices(pin, as_of=self.now, available_at=self.snapshot["forward_available_at"])

    def resolved(self, horizon=5, **kwargs):
        book = self.book(**kwargs)
        return f.resolve_returns(self.snapshot, horizon, book, as_of=self.now, prior_rows=f.initial_returns(self.snapshot, horizon)["returns"])

    def test_append_only_three_ledgers_and_initial_pending(self):
        self.start()
        self.assertEqual([len(f.replay_chain(self.root, k)) for k in f.KINDS], [1, 3, 3])
        self.assertTrue(all(r["status"] == "PENDING" for e in f.replay_chain(self.root, f.KINDS[1]) for r in e["payload"]["returns"]))

    def test_repeat_baseline_idempotent(self):
        self.start()
        before = f.heads(self.root)
        f.create_baseline(self.root, self.snapshot, before)
        self.assertEqual(before, f.heads(self.root))

    def test_baseline_cannot_backfill(self):
        self.now = "2026-09-02T00:00:00+00:00"
        with self.assertRaisesRegex(Rejected, "BACKFILL"):
            f.baseline(self.shadow, sealed_at="2026-09-01T00:00:00Z", effective_at="2026-09-01T00:00:00Z", execution_binding={}, source_pin={})

    def test_not_available_shadow_rejected(self):
        self.shadow["execution"]["shadow_available_at"] = "2026-09-02T00:00:00Z"
        with self.assertRaisesRegex(Rejected, "NOT_AVAILABLE"):
            self.make_snapshot()

    def test_older_seal_cannot_be_registered(self):
        self.now = "2026-09-02T00:00:00Z"
        with self.assertRaisesRegex(Rejected, "BACKFILL"):
            self.start()

    def test_population_freeze(self):
        other = deepcopy(self.snapshot)
        other["companies"].pop()
        with self.assertRaisesRegex(Rejected, "IDENTITY"):
            f.validate_baseline(other)

    def test_snapshot_identity_tamper(self):
        self.snapshot["population_id"] = "tampered"
        with self.assertRaisesRegex(Rejected, "IDENTITY"):
            self.start()

    def test_boundary_ties_not_split_by_symbol(self):
        for c in self.shadow["core"]["companies"][:4]:
            c[f.SCORE] = 19
        scored = [c for c in self.shadow["core"]["companies"] if c[f.SCORE] is not None]
        for c in scored:
            c["shadow_rank"] = 1 + sum(x[f.SCORE] > c[f.SCORE] for x in scored)
        s = self.make_snapshot()
        self.assertGreater(len(s["groups"]["Top10"]), 2)
        self.assertTrue(all(str(1000 + i) in s["groups"]["Top10"] for i in range(4)))

    def test_missing_company_not_zero_score(self):
        self.assertIsNone(self.snapshot["companies"][-1]["score"])
        self.assertFalse(any("9999" in values for values in self.snapshot["groups"].values()))

    def test_trading_offset_five_not_calendar_days(self):
        result = self.resolved()
        r = result["returns"][0]
        self.assertEqual((r["entry_price_date"], r["exit_price_date"]), ("2026-09-01", "2026-09-08"))
        self.assertEqual(len(r["price_path"]), 6)

    def test_twenty_day_maturity(self):
        self.assertEqual(self.resolved(20)["returns"][0]["exit_price_date"], "2026-09-29")

    def test_sixty_day_pending_not_substituted(self):
        row = self.resolved(60)["returns"][0]
        self.assertEqual(row["status"], "PENDING")
        self.assertIsNone(row["exit_price"])
        self.assertIsNone(row["return_value"])

    def test_insufficient_sessions_pending(self):
        book = self.book()
        for market in book["sessions"]:
            book["sessions"][market] = book["sessions"][market][:5]
        r = f.resolve_returns(self.snapshot, 5, book, as_of=self.now, prior_rows=f.initial_returns(self.snapshot, 5)["returns"])
        self.assertTrue(all(x["status"] == "PENDING" for x in r["returns"]))

    def test_future_price_observation_rejected(self):
        pin = self.archives(end="2026-09-07")
        with self.assertRaisesRegex(Rejected, "OBSERVATION"):
            load_prices(pin, as_of="2026-09-08T00:00:00Z", available_at=self.snapshot["forward_available_at"])

    def test_no_pre_snapshot_entry(self):
        book = self.book()
        self.snapshot["forward_available_at"] = "2026-09-02T13:30:00+08:00"
        r = f.resolve_returns(self.snapshot, 5, book, as_of=self.now, prior_rows=f.initial_returns(self.snapshot, 5)["returns"])
        self.assertEqual(r["returns"][0]["entry_price_date"], "2026-09-03")

    def test_suspended_entry_fail_closed_no_late_entry(self):
        r = self.resolved(omit=("1000", "2026-09-01"))["returns"][0]
        self.assertEqual(r["status"], "FAIL_CLOSED")
        self.assertIsNone(r["return_value"])

    def test_delisted_or_missing_exit_not_zero(self):
        r = self.resolved(omit=("1000", "2026-09-08"))["returns"][0]
        self.assertEqual(r["status"], "FAIL_CLOSED")
        self.assertIsNone(r["return_value"])

    def test_path_gap_not_carried_forward(self):
        self.assertEqual(self.resolved(omit=("1000", "2026-09-04"))["returns"][0]["status"], "FAIL_CLOSED")

    def test_source_raw_tamper_rejection(self):
        pin = self.archives()
        manifest = json.loads(Path(pin["manifest_path"]).read_bytes())
        receipt = json.loads(Path(manifest["sources"][0]["receipt_path"]).read_bytes())
        Path(receipt["raw_path"]).write_bytes(b"tamper")
        self.now = "2026-10-08T00:00:00Z"
        with self.assertRaisesRegex(Rejected, "SOURCE_TAMPERED"):
            load_prices(pin, as_of=self.now, available_at=self.snapshot["forward_available_at"])

    def test_source_receipt_tamper(self):
        pin = self.archives()
        source = json.loads(Path(pin["manifest_path"]).read_bytes())["sources"][0]
        Path(source["receipt_path"]).write_bytes(b"tamper")
        self.now = "2026-10-08T00:00:00Z"
        with self.assertRaisesRegex(Rejected, "SOURCE_TAMPERED"):
            load_prices(pin, as_of=self.now, available_at=self.snapshot["forward_available_at"])

    def test_manifest_tamper(self):
        pin = self.archives()
        Path(pin["manifest_path"]).write_bytes(b"tamper")
        self.now = "2026-10-08T00:00:00Z"
        with self.assertRaisesRegex(Rejected, "SOURCE_TAMPERED"):
            load_prices(pin, as_of=self.now, available_at=self.snapshot["forward_available_at"])

    def test_ledger_tamper(self):
        self.start()
        expected = f.heads(self.root)
        next((self.root / f.KINDS[0]).glob("*.json")).write_bytes(b"{}")
        with self.assertRaises((Rejected, KeyError)):
            f.verify(self.root, expected)

    def test_truncation_trusted_head_rejected(self):
        self.start()
        expected = f.heads(self.root)
        sorted((self.root / f.KINDS[1]).glob("*.json"))[-1].unlink()
        with self.assertRaisesRegex(Rejected, "TRUNCATION"):
            f.verify(self.root, expected)

    def test_wrong_checkpoint_rejected(self):
        self.start()
        with self.assertRaisesRegex(Rejected, "HEAD_MISMATCH"):
            f.verify(self.root, self.empty)

    def test_duplicate_finalization_rejected(self):
        self.start()
        f.append_event(self.root, f.KINDS[1], f.replay_chain(self.root, f.KINDS[1])[-1]["payload"])
        with self.assertRaisesRegex(Rejected, "DUPLICATE_FINALIZATION"):
            f.verify(self.root, f.heads(self.root))

    def test_full_disk_update_replay_idempotency(self):
        self.start()
        expected = f.heads(self.root)
        self.now = "2026-10-08T00:00:00Z"
        pin = self.archives()
        result = f.update(self.root, expected, self.snapshot["shadow_snapshot_id"], pin, as_of=self.now)
        h = result["heads"]
        self.assertEqual(f.verify(self.root, h)["status"], "PASS")
        again = f.update(self.root, h, self.snapshot["shadow_snapshot_id"], pin, as_of=self.now)
        self.assertEqual(again["heads"], h)

    def test_independent_process_cold_read(self):
        self.start()
        pin = self.archives()
        self.now = "2026-10-08T00:00:00Z"
        h = f.update(self.root, f.heads(self.root), self.snapshot["shadow_snapshot_id"], pin, as_of=self.now)["heads"]
        command = "from src.provider_shadow_forward import verify; import json; print(json.dumps(verify(" + repr(str(self.root)) + "," + repr(h) + ")))"
        run = subprocess.run([sys.executable, "-B", "-c", command], cwd=f.ROOT, capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(json.loads(run.stdout)["status"], "PASS")

    def test_saved_source_stop_persists(self):
        self.start()
        self.now = "2026-10-08T00:00:00Z"
        pin = self.archives()
        pin["manifest_sha256"] = "0" * 64
        with self.assertRaises(Rejected):
            f.update(self.root, f.heads(self.root), self.snapshot["shadow_snapshot_id"], pin, as_of=self.now)
        with self.assertRaisesRegex(Rejected, "PERSISTED_SOURCE_STOP"):
            f.update(self.root, f.heads(self.root), self.snapshot["shadow_snapshot_id"], pin, as_of=self.now)
        self.assertEqual(f.checkpoint(self.root, f.heads(self.root))["gates"]["A"]["status"], "FAIL")

    def test_known_rank_ic_spread_and_metrics(self):
        assessment = f.evaluate(self.snapshot, self.resolved())
        self.assertEqual(assessment["rank_ic"], 1)
        self.assertGreater(assessment["spreads"]["Top10_minus_Bottom10"], 0)
        self.assertTrue(assessment["monotonicity_bottom_middle_top"])
        self.assertEqual(assessment["groups"]["Top10"]["sample_count"], 2)
        self.assertEqual(assessment["groups"]["Top10"]["max_drawdown"], 0)

    def test_spearman_ties_and_constant(self):
        self.assertEqual(f.spearman([1, 1, 3], [5, 5, 7]), 1)
        self.assertIsNone(f.spearman([1, 1], [2, 3]))
        self.assertEqual(f.spearman([1, 2, 3], [3, 2, 1]), -1)

    def test_gate_no_automatic_pass_after_twenty(self):
        evaluation = f.evaluate(self.snapshot, self.resolved())
        rows = [{**evaluation, "shadow_snapshot_id": "SYNTHETIC-" + str(i)} for i in range(20)]
        self.assertEqual(f.gates(rows)["A"]["status"], "INCONCLUSIVE")
        self.assertEqual(f.gates(rows)["A"]["completed_valid_snapshots"], 20)

    def test_pending_gates_inconclusive(self):
        self.start()
        self.assertTrue(all(g["status"] == "INCONCLUSIVE" and g["completed_valid_snapshots"] == 0 for g in f.checkpoint(self.root, f.heads(self.root))["gates"].values()))

    def test_stability_retention_and_turnover(self):
        r = f.stability(self.snapshot, deepcopy(self.snapshot))
        self.assertEqual(r["score_correlation"], 1)
        self.assertEqual(r["groups"]["Top10"]["retention"], 1)
        self.assertEqual(r["groups"]["Top20"]["one_way_turnover"], 0)

    def test_bias_unscored_not_dropped(self):
        r = f.evaluate(self.snapshot, self.resolved())
        self.assertEqual(r["unscored_population_returns"]["sample_count"], 1)
        self.assertIsNotNone(r["scored_minus_unscored_mean"])

    def test_single_writer_second_process_rejected(self):
        self.root.mkdir()
        with exclusive_scan(self.root):
            code = "from pathlib import Path; from src.provider_eps_dispatch import exclusive_scan;\nwith exclusive_scan(Path(" + repr(str(self.root)) + ")): print('BAD_SECOND_WRITER')"
            p = subprocess.run([sys.executable, "-B", "-c", code], cwd=f.ROOT, capture_output=True, text=True)
            self.assertNotEqual(p.returncode, 0)
            self.assertNotIn("BAD_SECOND_WRITER", p.stdout)

    def test_finite_zero_negative_input_math(self):
        self.assertEqual(f.number("0"), 0)
        self.assertEqual(f.number("-0.25"), -0.25)
        for x in (True, "NaN", "Infinity", "1e999"):
            with self.assertRaises((Rejected, ValueError)):
                f.number(x)

    def test_formal_entry_noninterference_any_forward_package_state(self):
        from scripts import build_live_source_bundle as live
        outcomes, formal = [], {"1000": {"Fundamental": "FORMAL_SYNTHETIC_SENTINEL"}}
        for content in (None, b'{"forward":1}', b'{"forward":2}', b"corrupt"):
            if content is not None:
                (self.directory / "FORWARD_CHECKPOINT.json").write_bytes(content)
            with patch.dict(os.environ, {"RATE_SHADOW_FORWARD_ROOT": str(self.directory)}), patch.object(live, "_accepted_fundamental_history", return_value=deepcopy(formal)), patch.object(live, "calculate_fundamental", side_effect=AssertionError("NO_FORMAL_SCORING")) as calculation:
                outcomes.append(live._fundamental_history(["1000"], as_of_date="2026-10-05"))
                self.assertFalse(calculation.called)
        self.assertEqual(outcomes, [formal] * 4)

    def test_negative_price_fail_closed(self):
        with self.assertRaisesRegex(Rejected, "NONPOSITIVE"):
            self.book(negative=True)

    def test_unsupported_source_endpoint_rejected(self):
        from src.provider_shadow_forward_prices import endpoint_ok
        with self.assertRaisesRegex(Rejected, "TWSE_PRODUCT"):
            endpoint_ok({"market": "TWSE", "domain": "stock", "period": "202609", "endpoint": "https://example.com/price", "request_method": "GET", "symbol": "1000"})

    def test_wrong_raw_symbol_identity(self):
        from src.provider_shadow_forward_prices import ArchivedAdapter
        with self.assertRaisesRegex(Rejected, "SYMBOL_IDENTITY"):
            ArchivedAdapter({"symbol": "1000", "period": "202609", "market": "TWSE"}, {"stat": "OK", "stockNo": "9999", "data": [{"Date": "2026-09-01"}]}).fetch_historical_symbol("1000", "202609")

    def test_rank_rule_tamper_rejected(self):
        self.shadow["core"]["companies"][0]["shadow_rank"] = 1
        with self.assertRaisesRegex(Rejected, "RANK_MISMATCH"):
            self.make_snapshot()

    def test_5d_complete_does_not_finalize_60d(self):
        self.start()
        self.now = "2026-10-08T00:00:00Z"
        f.update(self.root, f.heads(self.root), self.snapshot["shadow_snapshot_id"], self.archives(), as_of=self.now)
        by_h = {e["payload"]["horizon"]: e["payload"] for e in f.replay_chain(self.root, f.KINDS[1])}
        self.assertTrue(all(r["status"] == "FINALIZED" for r in by_h[5]["returns"]))
        self.assertTrue(all(r["status"] == "PENDING" for r in by_h[60]["returns"]))

    def test_return_stats_negative_zero_and_drawdown(self):
        paths = [[100, 90, 110], [100, 90, 100], [100, 90, 90]]
        rows = [{"status": "FINALIZED", "return_value": p[-1] / 100 - 1, "entry_price": "100", "price_path": [{"close": str(x)} for x in p]} for p in paths]
        result = f.metrics(rows, 3)
        self.assertAlmostEqual(result["mean_return"], 0)
        self.assertEqual(result["win_rate"], 1 / 3)
        self.assertAlmostEqual(result["max_drawdown"], -0.1)

    def test_all_tied_groups_flag_overlap_no_valid_gate(self):
        for c in self.shadow["core"]["companies"][:-1]:
            c[f.SCORE], c["shadow_rank"] = 50, 1
        self.snapshot = self.make_snapshot()
        result = f.evaluate(self.snapshot, self.resolved())
        self.assertFalse(result["valid_observed_forward_snapshot"])
        self.assertIsNone(result["rank_ic"])
        self.assertEqual(len(result["boundary_tie_overlap"]), 20)

    def test_outlier_diagnostic_keeps_primary_population(self):
        result = f.evaluate(self.snapshot, self.resolved())
        self.assertEqual(result["rank_ic_sample_count"], 20)
        self.assertEqual(len(result["outlier_diagnostics"]["leave_one_out"]), 20)
        self.assertEqual(result["outlier_diagnostics"]["excluded_from_primary_analysis"], [])

    def test_wrong_market_price_rejected(self):
        book = self.book()
        book["prices"][("1000", "2026-09-01")]["reference"]["market"] = "TPEX"
        with self.assertRaisesRegex(Rejected, "MARKET_IDENTITY"):
            f.resolve_returns(self.snapshot, 5, book, as_of=self.now, prior_rows=f.initial_returns(self.snapshot, 5)["returns"])

    def test_revised_entry_cannot_replace_saved_price(self):
        resolved = self.resolved()
        book = self.book()
        book["prices"][("1000", "2026-09-01")]["close"] = "999"
        rows = deepcopy(resolved["returns"])
        rows[0]["status"] = "PENDING"
        with self.assertRaisesRegex(Rejected, "ENTRY_REVISED"):
            f.resolve_returns(self.snapshot, 5, book, as_of=self.now, prior_rows=rows)

    def test_independent_nontrivial_spearman_reference(self):
        self.assertAlmostEqual(f.spearman([1, 2, 3, 4, 5], [5, 1, 3, 2, 4]), -0.1)
        self.assertAlmostEqual(f.spearman([1, 1, 2, 3], [4, 1, 2, 3]), 0.5 / (22.5 ** 0.5))

    def test_resigned_nonfinite_raw_price_still_rejected(self):
        pin = self.archives()
        manifest = json.loads(Path(pin["manifest_path"]).read_bytes())
        source = manifest["sources"][2]
        receipt = json.loads(Path(source["receipt_path"]).read_bytes())
        payload = json.loads(Path(receipt["raw_path"]).read_bytes())
        payload["data"][0][4] = "NaN"
        Path(receipt["raw_path"]).write_bytes(_canonical(payload))
        receipt.update(raw_sha256=sha256(Path(receipt["raw_path"]).read_bytes()), bytes=Path(receipt["raw_path"]).stat().st_size)
        Path(source["receipt_path"]).write_bytes(_canonical(receipt))
        source["receipt_sha256"] = sha256(Path(source["receipt_path"]).read_bytes())
        Path(pin["manifest_path"]).write_bytes(_canonical(manifest))
        pin["manifest_sha256"] = sha256(Path(pin["manifest_path"]).read_bytes())
        self.now = "2026-10-08T00:00:00Z"
        with self.assertRaises(Rejected):
            load_prices(pin, as_of=self.now, available_at=self.snapshot["forward_available_at"])

    def test_duplicate_price_archive_rejected(self):
        pin = self.archives()
        manifest = json.loads(Path(pin["manifest_path"]).read_bytes())
        manifest["sources"].append(manifest["sources"][0])
        Path(pin["manifest_path"]).write_bytes(_canonical(manifest))
        pin["manifest_sha256"] = sha256(Path(pin["manifest_path"]).read_bytes())
        self.now = "2026-10-08T00:00:00Z"
        with self.assertRaisesRegex(Rejected, "DUPLICATE_ARCHIVE"):
            load_prices(pin, as_of=self.now, available_at=self.snapshot["forward_available_at"])

    def test_wrong_endpoint_month_rejected(self):
        from src.provider_shadow_forward_prices import endpoint_ok
        with self.assertRaisesRegex(Rejected, "TWSE_PRODUCT"):
            endpoint_ok({"market": "TWSE", "domain": "stock", "period": "202610", "endpoint": "https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?date=20260901&stockNo=1000&response=json", "request_method": "GET", "symbol": "1000"})

    def test_changed_top_population_turnover(self):
        current = deepcopy(self.snapshot)
        current["companies"][0]["score"] = 30
        current["companies"][1]["score"] = 29
        for c in current["companies"]:
            if c["score"] is not None:
                c["rank"] = 1 + sum(x["score"] is not None and x["score"] > c["score"] for x in current["companies"])
        current["groups"] = f.members(current["companies"])
        result = f.stability(self.snapshot, current)
        self.assertEqual(result["groups"]["Top10"]["one_way_turnover"], 1)
        self.assertEqual(result["groups"]["Top20"]["retention"], 0.5)
