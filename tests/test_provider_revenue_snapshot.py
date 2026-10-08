"""Synthetic official archive fixtures only; never real financial acquisition."""
from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from src.eps_duration_facts.model import Rejected
from src.eps_duration_facts.raw import sha256
from src.provider_eps_dispatch import DispatchGate
from src.provider_eps_metadata import read_metadata
from src.provider_financial_features import compute_core, seal, export_package, consume, hash_object, instant
from src.provider_financial_feature_inputs import replay_binding
from src.provider_revenue_snapshot import (prepare, acquire, replay_snapshot, observations, differences,
    endpoint, strict_opener, NoRedirect, read_plan, MODE)
from tests.provider_fundamental_shadow_fixture import synthetic_inputs


class Clock:
    def __init__(self):
        self.time = 0.25
    def now(self):
        return self.time
    def sleep(self, seconds):
        self.time += seconds


class Response(BytesIO):
    def __init__(self, body, url, status=200):
        super().__init__(body)
        self.status, self.url = status, url
        self.headers = {"Content-Type": "text/html; charset=utf-8", "Content-Length": str(len(body))}
    def getcode(self):
        return self.status
    def geturl(self):
        return self.url


def html(market, period, rows):
    heading = "上市" if market == "TWSE" else "上櫃"
    month = int(period[-2:])
    cells = "".join(f"<tr><td>{s}</td><td>10</td><td>{'0' if v is None else '5'}</td><td>{'' if v is None else v}</td></tr>" for s, v in rows)
    return (f"<html><font size='5'>{heading}公司115年{month}月份(累計與當月)營業收入統計表</font>出表日期：115年10月09日"
        "<table><tr><th>公司代號</th><th>當月營收</th><th>去年當月營收</th><th>去年同月增減(%)</th></tr>" + cells + "</table></html>").encode("utf-8")


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="revenue-synthetic-")
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        source = self.directory / "old"
        source.mkdir()
        data = synthetic_inputs(source, create=True)
        data["source_binding"]["coverage_root"] = str(source)
        data["revenue"] = [r for r in data["revenue"] if r["symbol"] not in ("1000", "1001")]
        self.features = seal(compute_core(data), code_binding={"base_sha": "0" * 40, "head_sha": "1" * 40})
        self.root = self.directory / "snapshot"
        self.pin = {"synthetic_engineering_only": True}
        self.digest = prepare(self.features, self.pin, self.features["execution"]["code_binding"], self.root)
        self.plan = read_plan(self.root, self.digest, self.features)
        self.clock = Clock()
        self.gate = DispatchGate(13, prior_dispatch=True, clock=self.clock.now, sleep=self.clock.sleep,
            utc=instant)
        self.calls = []

    def opener(self, request, timeout):
        self.calls.append(request.full_url)
        target = next(t for t in self.plan["targets"] if t["endpoint"] == request.full_url)
        rows = [(c["symbol"], str(int(c["symbol"]) - 1000)) for c in self.features["core"]["inputs"]["universe"]["stocks"] if c["market"] == target["market"]]
        return Response(html(target["market"], target["period"], rows), request.full_url)

    def run_acquire(self, opener=None):
        return acquire(self.root, self.digest, self.features, opener=opener or self.opener, gate=self.gate)

    def replay(self, digest):
        return replay_snapshot(self.root, digest, old_loader=lambda _pin: self.features)

    def test_six_once_exact_old_eps_and_new_revenue_entire_selection(self):
        digest, result = self.run_acquire()
        inputs, diagnostics = self.replay(digest)
        self.assertEqual(len(self.calls), 6)
        self.assertEqual(result["new_eps_requests"], 0)
        self.assertEqual(inputs["eps"], self.features["core"]["inputs"]["eps"])
        self.assertEqual(inputs["gaps"], self.features["core"]["inputs"]["gaps"])
        self.assertTrue(all(r["raw_reference"].startswith(str(self.root)) for r in inputs["revenue"]))
        self.assertEqual(len(diagnostics["selection"]), 6)

    def test_existing_complete_market_period_reused_without_request(self):
        data = deepcopy(self.features["core"]["inputs"])
        for target in self.plan["targets"]:
            old = next(r for r in data["revenue"] if r["market"] == target["market"] and r["period"] == target["period"])
            data["revenue"].append(dict(old, symbol="1000" if target["market"] == "TPEX" else "1001"))
        features = seal(compute_core(data))
        root = self.directory / "sufficient"
        digest = prepare(features, {}, {}, root)
        _manifest, result = acquire(root, digest, features, opener=lambda *_a, **_k: self.fail("UNNECESSARY_REQUEST"), gate=self.gate)
        self.assertEqual(result["new_revenue_requests"], 0)

    def test_zero_base_is_preserved_not_refreshed_reason(self):
        self.assertTrue(all("1000" in t["missing_observation_symbols"] or "1001" in t["missing_observation_symbols"] for t in self.plan["targets"]))
        self.assertTrue(all("1022" not in t["missing_observation_symbols"] for t in self.plan["targets"]))
        def opener(request, timeout):
            target = next(t for t in self.plan["targets"] if t["endpoint"] == request.full_url)
            return Response(html(target["market"], target["period"], [(c["symbol"], None) for c in self.plan["universe"]["stocks"] if c["market"] == target["market"]]), request.full_url)
        digest, _ = self.run_acquire(opener)
        inputs, _ = self.replay(digest)
        self.assertTrue(all(r["revenue_yoy"] is None and r["revenue_yoy_status"] == "UNDEFINED_ZERO_BASE" for r in inputs["revenue"]))
        self.assertEqual(compute_core(inputs)["summary"]["feature_counts"]["official_revenue_yoy_mean_3m"], 0)

    def test_new_missing_row_not_backfilled_even_if_old_exists(self):
        def opener(request, timeout):
            target = next(t for t in self.plan["targets"] if t["endpoint"] == request.full_url)
            rows = [(c["symbol"], "10") for c in self.plan["universe"]["stocks"] if c["market"] == target["market"] and c["symbol"] != "1002"]
            return Response(html(target["market"], target["period"], rows), request.full_url)
        digest, _ = self.run_acquire(opener)
        inputs, diagnostics = self.replay(digest)
        self.assertFalse(any(r["symbol"] == "1002" for r in inputs["revenue"]))
        self.assertEqual(sum(r["symbol"] == "1002" and r["comparison"] == "no_longer_observed" for r in diagnostics["differences"]), 3)

    def test_diff_all_five_categories_not_only_improvements(self):
        row = self.features["core"]["inputs"]["revenue"][0]
        old = [dict(row, symbol=s) for s in ("1", "2", "3", "4")]
        new = [dict(row, symbol="1"), dict(row, symbol="2", revenue_yoy="999"),
            dict(row, symbol="3", revenue_yoy=None, revenue_yoy_status="UNDEFINED_ZERO_BASE"), dict(row, symbol="5")]
        self.assertEqual({r["comparison"] for r in differences(old, new, row["market"], row["period"])},
            {"unchanged", "added", "value_changed", "numeric_status_changed", "no_longer_observed"})

    def test_duplicate_and_conflicting_rows_stop_first_request(self):
        for value in ("1", "2"):
            root = self.directory / ("duplicate-" + value)
            digest = prepare(self.features, {}, {}, root)
            calls = []
            def opener(request, timeout):
                calls.append(request.full_url)
                t = next(t for t in self.plan["targets"] if t["endpoint"] == request.full_url)
                return Response(html(t["market"], t["period"], [("1001", "1"), ("1001", value)]), request.full_url)
            _hash, result = acquire(root, digest, self.features, opener=opener, gate=self.gate)
            self.assertEqual(len(calls), 1)
            self.assertEqual(result["snapshot_status"], "PARTIAL_SOURCE_FAILURE")

    def test_wrong_month_and_market_stop_without_followup(self):
        for kind in ("period", "market"):
            root = self.directory / kind
            digest = prepare(self.features, {}, {}, root)
            calls = []
            def opener(request, timeout):
                calls.append(request.full_url)
                t = self.plan["targets"][0]
                return Response(html("TPEX" if kind == "market" else t["market"], "2026-07" if kind == "period" else t["period"], [("1001", "1")]), request.full_url)
            _hash, result = acquire(root, digest, self.features, opener=opener, gate=self.gate)
            self.assertEqual(len(calls), 1)
            self.assertEqual(result["snapshot_status"], "PARTIAL_SOURCE_FAILURE")

    def test_http_redirect_and_401_403_429_stop_and_preserve_body(self):
        for status in (302, 401, 403, 429):
            root = self.directory / str(status)
            digest = prepare(self.features, {}, {}, root)
            calls = []
            def opener(request, timeout):
                calls.append(request.full_url)
                return Response(b"<html>BLOCKED</html>", request.full_url, status)
            manifest, result = acquire(root, digest, self.features, opener=opener, gate=self.gate)
            self.assertEqual(len(calls), 1)
            self.assertIsNotNone(result["events"][0]["receipt_reference"])
            inputs, _ = replay_snapshot(root, manifest, old_loader=lambda _pin: self.features)
            t = self.plan["targets"][0]
            self.assertFalse(any((r["market"], r["period"]) == (t["market"], t["period"]) for r in inputs["revenue"]))

    def test_network_failure_saved_no_retry_unknown_not_reissued(self):
        calls = []
        def opener(request, timeout):
            calls.append(request.full_url)
            raise OSError("SYNTHETIC_NETWORK_BLOCK")
        _digest, result = self.run_acquire(opener)
        self.assertEqual(len(calls), 1)
        self.assertEqual(result["new_revenue_requests"], 1)
        with self.assertRaisesRegex(Rejected, "NO_AUTOMATIC_RESTART"):
            self.run_acquire(opener)
        self.assertEqual(len(calls), 1)

    def test_strict_opener_converts_http_error_no_second_url(self):
        error = HTTPError("https://official.example.test", 302, "redirect", {"Location": "https://other.example.test"}, BytesIO(b"redirect"))
        with patch("src.provider_revenue_snapshot.build_opener") as factory:
            factory.return_value.open.side_effect = error
            self.assertIs(strict_opener()(object()), error)
            self.assertEqual(factory.return_value.open.call_count, 1)
        self.assertIsNone(NoRedirect().redirect_request(None, None, 302, "", {}, "https://other.example.test"))

    def test_monotonic_spacing_survives_early_sleep_returns_and_cold_read(self):
        self.gate.sleep = lambda seconds: self.clock.sleep(min(seconds, 0.5))
        digest, result = self.run_acquire()
        self.replay(digest)
        dispatches = [e["dispatch"] for e in result["events"]]
        self.assertTrue(all(d["monotonic_timestamp"] - d["previous_wait_anchor_monotonic"] >= 13 for d in dispatches))
        self.assertTrue(all(d["previous_dispatch_interval_seconds"] >= 13 for d in dispatches[1:]))

    def test_manifest_raw_receipt_and_plan_tamper_rejected(self):
        digest, _result = self.run_acquire()
        manifest = read_metadata((self.root / "SNAPSHOT_MANIFEST.json").read_bytes())
        for name in ("request-plan.json", next(n for n in manifest["files"] if n.startswith("materials/")), next(n for n in manifest["files"] if n.startswith("reports/mops/"))):
            path = self.root / name
            original = path.read_bytes()
            path.write_bytes(original + b" ")
            with self.assertRaisesRegex(Rejected, "SOURCE_TAMPERED"):
                self.replay(digest)
            path.write_bytes(original)
        path = self.root / "SNAPSHOT_MANIFEST.json"
        path.write_bytes(path.read_bytes() + b" ")
        with self.assertRaisesRegex(Rejected, "MANIFEST_TAMPERED"):
            self.replay(digest)

    def test_new_opt_in_binding_consumer_rebuilds_from_original_responses(self):
        digest, _ = self.run_acquire()
        inputs, _ = self.replay(digest)
        package = seal(compute_core(inputs))
        output = self.directory / "new-features"
        export_package(package, output)
        with patch("src.provider_revenue_snapshot.load_delivery", return_value=self.features):
            result = consume(output, sha256((output / "FEATURE_MANIFEST.json").read_bytes()), source_replayer=replay_binding)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(inputs["source_binding"]["input_mode"], MODE)

    def test_legacy_binding_still_calls_unchanged_legacy_loader(self):
        binding = {"closeout_manifest_reference": "ENGINEERING", "closeout_manifest_sha256": "0" * 64}
        result = {"source_binding": binding}
        with patch("src.provider_financial_feature_inputs.load_closeout", return_value=result) as loader:
            self.assertEqual(replay_binding(binding), result)
            loader.assert_called_once_with("ENGINEERING", "0" * 64)

    def test_mixed_observations_not_simultaneous_or_old_time_backfilled(self):
        digest, result = self.run_acquire()
        inputs, _ = self.replay(digest)
        self.assertTrue(result["not_simultaneous_market_snapshot"])
        self.assertFalse(result["official_latest_or_all_revisions_proven"])
        self.assertTrue(all(r["observed_at"] not in {o["observed_at"] for o in self.features["core"]["inputs"]["revenue"]} for r in inputs["revenue"]))

    def test_wrong_request_plan_hash_and_out_of_window_targets_rejected(self):
        with self.assertRaisesRegex(Rejected, "PLAN_TAMPERED"):
            read_plan(self.root, "0" * 64, self.features)
        for m, p in (("OTHER", "2026-07"), ("TWSE", "2026-10")):
            with self.assertRaisesRegex(Rejected, "OUT_OF_WINDOW"):
                endpoint(m, p)

    def test_conflicting_market_symbol_never_silently_filtered(self):
        def opener(request, timeout):
            t = self.plan["targets"][0]
            return Response(html(t["market"], t["period"], [("1000", "1")]), request.full_url)
        _digest, result = self.run_acquire(opener)
        self.assertEqual(result["new_revenue_requests"], 1)
        self.assertIn("MARKET_CONFLICT", result["stop"]["message"])

    def test_outside_universe_kept_raw_not_added_to_target_population(self):
        def opener(request, timeout):
            t = next(t for t in self.plan["targets"] if t["endpoint"] == request.full_url)
            rows = [(c["symbol"], "1") for c in self.plan["universe"]["stocks"] if c["market"] == t["market"]]
            return Response(html(t["market"], t["period"], rows + [("9999", "123")]), request.full_url)
        digest, result = self.run_acquire(opener)
        inputs, _ = self.replay(digest)
        self.assertFalse(any(r["symbol"] == "9999" for r in inputs["revenue"]))
        self.assertTrue(all("9999" in e["outside_universe_symbols"] for e in result["events"]))

    def test_per_target_once_budget_and_restart_gate(self):
        digest, result = self.run_acquire()
        self.assertEqual(len(set(self.calls)), result["new_revenue_requests"])
        self.assertLessEqual(result["new_revenue_requests"], 6)
        with self.assertRaisesRegex(Rejected, "NO_AUTOMATIC_RESTART"):
            self.run_acquire()

    def test_failed_snapshot_never_promoted_or_old_silent_fallback(self):
        digest, result = self.run_acquire(lambda request, timeout: Response(b"<html>no schema</html>", request.full_url))
        inputs, diagnostics = self.replay(digest)
        self.assertEqual(inputs["source_binding"]["snapshot_status"], "PARTIAL_SOURCE_FAILURE")
        self.assertIsNone(diagnostics["selection"][0]["selected_receipt"])
        self.assertTrue(all(s["status"] == "REUSED_OLD_VERIFIED" for s in diagnostics["selection"][1:]))

    def test_future_observation_not_promoted(self):
        with patch("src.sources.fundamental_history._now", return_value="2099-01-01T00:00:00+00:00"):
            _digest, result = self.run_acquire()
        self.assertEqual(result["new_revenue_requests"], 1)
        self.assertEqual(result["snapshot_status"], "PARTIAL_SOURCE_FAILURE")
        self.assertIn("TIME_INVALID", result["stop"]["message"])

    def test_separate_process_new_input_cold_replays_saved_receipts(self):
        import subprocess
        import sys
        from src.provider_eps_candidate import _canonical
        digest, _result = self.run_acquire()
        original_path = self.directory / "original-synthetic-features.json"
        original_path.write_bytes(_canonical(self.features))
        code = "import json,sys; from pathlib import Path; from src.provider_financial_features import validate_package; from src.provider_revenue_snapshot import replay_snapshot; from src.provider_eps_metadata import read_metadata; old=read_metadata(Path(sys.argv[3]).read_bytes()); validate_package(old); inputs,d=replay_snapshot(sys.argv[1],sys.argv[2],old_loader=lambda p: old); print(json.dumps({'rows':len(inputs['revenue']),'eps':len(inputs['eps']),'selection':len(d['selection'])}))"
        run = subprocess.run([sys.executable, "-B", "-c", code, str(self.root), digest, str(original_path)],
            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertEqual(json.loads(run.stdout)["rows"], 72)

    def test_negative_or_sub13_dispatch_rejected_even_if_manifests_resigned(self):
        from src.provider_eps_candidate import _canonical
        digest, _result = self.run_acquire()
        key = self.plan["targets"][0]["market"] + "-" + self.plan["targets"][0]["period"]
        event_path, intent_path = self.root / "events" / (key + ".json"), self.root / "intents" / (key + ".json")
        result_path, manifest_path = self.root / "ACQUISITION_RESULT.json", self.root / "SNAPSHOT_MANIFEST.json"
        originals = {p: p.read_bytes() for p in (event_path, intent_path, result_path, manifest_path)}
        for kind in ("negative", "sub13"):
            event = read_metadata(originals[event_path])
            if kind == "negative":
                event["dispatch"]["actual_wait_seconds"] = -1
            else:
                event["dispatch"]["previous_wait_anchor_monotonic"] = event["dispatch"]["monotonic_timestamp"] - 12.75
            event["event_sha256"] = hash_object({k: v for k, v in event.items() if k != "event_sha256"})
            event_path.write_bytes(_canonical(event))
            intent = read_metadata(originals[intent_path])
            intent.update(dispatch=event["dispatch"], dispatch_sha256=hash_object(event["dispatch"]))
            intent_path.write_bytes(_canonical(intent))
            result = read_metadata(originals[result_path])
            result["events"][0] = event
            result_path.write_bytes(_canonical(result))
            manifest = read_metadata(originals[manifest_path])
            for path in (event_path, intent_path, result_path):
                body = path.read_bytes()
                manifest["files"][path.relative_to(self.root).as_posix()] = {"bytes": len(body), "sha256": sha256(body)}
            manifest_path.write_bytes(_canonical(manifest))
            with self.assertRaisesRegex(Rejected, "(NUMERIC|INTERVAL)_INVALID"):
                self.replay(sha256(manifest_path.read_bytes()))


if __name__ == "__main__":
    unittest.main()
