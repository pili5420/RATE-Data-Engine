"""SYNTHETIC ONLY. Execute wiring is tested with an in-process fake transport."""
from copy import deepcopy
import io
import json
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import session_discovery_execution as m
from src import session_discovery_transport as t

MAIN = "6a2108c6ce326bf90806ab0cdd7ab84e7131a643"
UTC = "2026-10-12T10:00:00Z"


def response(entry):
    if entry["market"] == "TWSE":
        payload = [{"日期": "20261012", "指數": "SYNTHETIC_INDEX", "收盤指數": "20000"}] if entry["product"] == "benchmark" else [
            {"Date": "20261012", "Code": "SYNTHETIC", "ClosingPrice": "100"}]
    else:
        payload = [{"Date": "1151012", "收市": "300"}] if entry["product"] == "benchmark" else [
            {"Date": "1151012", "SecuritiesCompanyCode": "SYNTHETIC", "Close": " ---"}]
    return {"raw_bytes": m.canonical(payload), "http_status": 200, "final_url": entry["endpoint"],
            "content_type": "application/json; charset=utf-8", "location": None}


def synthetic_authorization(seal):
    proposal = m.candidate_authorization(seal)
    core = {k: v for k, v in proposal.items() if k not in ("authorization_id", "authorization_sha256")}
    core["status"] = m.AUTHORIZED
    return m.identified(core, "rate-session-discovery-authorization-", "authorization_id", "authorization_sha256")


class Clock:
    def __init__(self):
        self.value = 100.25
        self.waits = []

    def monotonic(self):
        return self.value

    def sleep(self, seconds):
        self.waits.append(seconds)
        self.value += seconds


class Fixture(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="discovery-synthetic-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.artifacts, self.consumption = self.root / "discovery", self.root / "claims"
        self.output = self.artifacts / "run-one"
        self.plan = m.build_plan(MAIN)
        self.seal = m.build_seal(self.plan, self.artifacts, self.consumption)
        self.auth = synthetic_authorization(self.seal)
        self.clock, self.calls = Clock(), []
        self.guard = patch.object(m, "main_guard")
        self.guard.start()
        self.addCleanup(self.guard.stop)

    def capture(self, entry):
        self.assertTrue((self.consumption / (self.auth["authorization_id"] + ".json")).exists())
        intent = m.read_metadata((self.output / "intents" / f"{entry['ordinal']:02}.json").read_bytes())
        self.assertEqual(intent["ordinal"], entry["ordinal"])
        self.calls.append(deepcopy(entry))
        return response(entry)

    def execute(self, transport=None, **kwargs):
        return m.execute(self.plan, self.seal, self.auth, artifacts_root=self.artifacts,
            consumption_root=self.consumption, output_root=kwargs.pop("output_root", self.output),
            transport=transport or self.capture, utc=lambda: UTC, monotonic=self.clock.monotonic,
            sleep=self.clock.sleep, **kwargs)

    def preflight(self, **changes):
        values = dict(plan=self.plan, seal=self.seal, authorization=self.auth,
                      artifacts_root=self.artifacts, consumption_root=self.consumption)
        values.update(changes)
        return m.preflight(**values)

    def replay(self):
        return m.replay(self.output, self.plan, self.seal, self.auth, self.consumption)

    def mutate_plan(self, mutation):
        plan = deepcopy(self.plan)
        mutation(plan)
        with self.assertRaises(Exception):
            self.preflight(plan=plan)
        self.assertFalse(self.consumption.exists())


class PlanTests(Fixture):
    def test_exact_four_deterministic(self):
        self.assertEqual(self.plan, m.build_plan(MAIN))
        self.assertEqual([e["ordinal"] for e in self.plan["entries"]], [1, 2, 3, 4])
        self.assertEqual(len({e["request_key"] for e in self.plan["entries"]}), 4)
        self.assertEqual(self.plan["ranking_universe_identity"], m.UNIVERSE)

    def test_exact_official_endpoints(self):
        self.assertEqual([e["endpoint"] for e in self.plan["entries"]], [
            m.TWSE_BASE + "/exchangeReport/MI_INDEX",
            m.TWSE_BASE + "/exchangeReport/STOCK_DAY_ALL",
            m.BENCHMARK_ENDPOINT, m.CURRENT_DAILY_ENDPOINT])

    def test_fifth_rejected(self):
        self.mutate_plan(lambda p: p["entries"].append(p["entries"][0]))

    def test_wrong_endpoint(self):
        self.mutate_plan(lambda p: p["entries"][0].update(endpoint="https://evil.invalid/"))

    def test_order_mutation(self):
        self.mutate_plan(lambda p: p["entries"].reverse())

    def test_timeout(self):
        self.mutate_plan(lambda p: p["entries"][0].update(timeout=29))

    def test_retry(self):
        self.mutate_plan(lambda p: p["entries"][0].update(retry=1))

    def test_fallback(self):
        self.mutate_plan(lambda p: p["entries"][0].update(fallback=True))

    def test_redirect(self):
        self.mutate_plan(lambda p: p["entries"][0].update(redirect=True))

    def test_credentials(self):
        self.mutate_plan(lambda p: p["entries"][0].update(credentials="TOKEN"))

    def test_bool_not_number(self):
        self.mutate_plan(lambda p: p["entries"][0].update(ordinal=True))

    def test_plan_digest(self):
        self.mutate_plan(lambda p: p.update(plan_sha256="0" * 64))

    def test_universe(self):
        self.mutate_plan(lambda p: p.update(ranking_universe_identity="0" * 64))

    def test_minimum_interval(self):
        self.mutate_plan(lambda p: p["entries"][1].update(minimum_interval_seconds=12.99))

    def test_maximum_requests(self):
        self.mutate_plan(lambda p: p.update(maximum_requests=5))


class AuthorizationTests(Fixture):
    def test_missing_before_claim(self):
        with self.assertRaises(Exception):
            self.preflight(authorization={})
        self.assertFalse(self.consumption.exists())

    def test_wrong_authorization(self):
        self.auth["plan_sha256"] = "0" * 64
        with self.assertRaises(Exception):
            self.execute()
        self.assertFalse(self.calls)
        self.assertFalse(self.consumption.exists())

    def test_candidate_never_executable(self):
        self.auth = m.candidate_authorization(self.seal)
        self.preflight(candidate=True)
        with self.assertRaises(Exception):
            self.execute()
        self.assertFalse(self.consumption.exists())

    def test_seal_tamper(self):
        self.seal["maximum_requests"] = 5
        with self.assertRaises(Exception):
            self.execute()
        self.assertFalse(self.calls)

    def test_owner_drift(self):
        with patch.object(m, "owner_hashes", return_value={"executor": "0" * 64, "transport": "0" * 64}):
            with self.assertRaises(Exception):
                self.execute()
        self.assertFalse(self.consumption.exists())

    def test_main_drift(self):
        self.guard.stop()
        with patch.object(m, "main_guard", side_effect=ValueError("DISCOVERY_MAIN_DRIFT")):
            with self.assertRaisesRegex(Exception, "MAIN_DRIFT"):
                self.execute()
        self.assertFalse(self.consumption.exists())

    def test_dirty_worktree(self):
        self.guard.stop()
        with patch.object(m, "main_guard", side_effect=ValueError("DISCOVERY_DIRTY_WORKTREE")):
            with self.assertRaisesRegex(Exception, "DIRTY_WORKTREE"):
                self.execute()
        self.assertFalse(self.consumption.exists())

    def test_claim_precedes_dispatch(self):
        result = self.execute()
        self.assertEqual(result["actual_requests"], 4)
        self.assertEqual(len(self.calls), 4)

    def test_duplicate_claim(self):
        self.execute()
        with self.assertRaisesRegex(Exception, "AUTHORIZATION_ALREADY_CONSUMED"):
            self.execute(output_root=self.artifacts / "another-output")
        self.assertEqual(len(self.calls), 4)

    def test_consumption_root_change(self):
        self.execute()
        with self.assertRaises(Exception):
            self.preflight(consumption_root=self.root / "different-claims")

    def test_artifacts_root_change(self):
        with self.assertRaises(Exception):
            self.preflight(artifacts_root=self.root / "different-root")

    def test_output_must_be_new(self):
        self.output.mkdir(parents=True)
        with self.assertRaisesRegex(Exception, "MUST_BE_NEW"):
            self.execute()
        self.assertFalse(list(self.consumption.glob("*.json")))

    def test_external_only(self):
        with self.assertRaisesRegex(Exception, "IN_REPOSITORY"):
            m.build_seal(self.plan, m.ROOT / "bad", self.consumption)

    def test_other_checkout_output_rejected(self):
        other = self.root / "other-checkout"
        other.mkdir()
        (other / ".git").mkdir()
        (other / ".git/HEAD").write_text("ref: refs/heads/main", encoding="utf-8")
        with self.assertRaisesRegex(Exception, "IN_REPOSITORY"):
            m.build_seal(self.plan, other / "discovery", self.consumption)

    def test_other_worktree_consumption_rejected(self):
        other = self.root / "other-worktree"
        other.mkdir()
        (other / ".git").write_text("gitdir: SYNTHETIC_ONLY", encoding="utf-8")
        with self.assertRaisesRegex(Exception, "IN_REPOSITORY"):
            m.build_seal(self.plan, self.artifacts, other / "claims")

    def test_empty_non_repository_marker_not_checkout(self):
        other = self.root / "non-repository-placeholder"
        other.mkdir()
        (other / ".git").mkdir()
        self.assertFalse(m.checkout_marker(other))
        m.build_seal(self.plan, other / "discovery", self.consumption)

    def test_protected_output_root(self):
        with self.assertRaisesRegex(Exception, "PROTECTED_OUTPUT"):
            m.build_seal(self.plan, self.root / "state" / "discovery", self.consumption)

    def test_no_auto_resume(self):
        with self.assertRaisesRegex(Exception, "RESUME_FORBIDDEN"):
            m.resume()

    def test_partial_consumption_blocks_restart(self):
        self.consumption.mkdir()
        (self.consumption / (self.auth["authorization_id"] + ".json")).write_bytes(b"{")
        with self.assertRaisesRegex(Exception, "AUTHORIZATION_ALREADY_CONSUMED"):
            self.execute()


class LifecycleTests(Fixture):
    def test_four_success_checkpoints_chain(self):
        result = self.execute()
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["completed_checkpoints"], 4)
        self.assertEqual(len(list((self.output / "checkpoints").glob("*.json"))), 4)
        self.assertEqual(len(result["sessions"]), 4)
        self.assertEqual(result, self.replay())
        self.assertFalse(result["calendar_180_ready"])

    def test_intent_before_network(self):
        self.execute()
        self.assertEqual([e["ordinal"] for e in self.calls], [1, 2, 3, 4])

    def test_immutable_raw(self):
        self.execute()
        for e in self.calls:
            raw = response(e)["raw_bytes"]
            path = self.output / "raw" / (m.sha(raw) + ".bin")
            self.assertEqual(path.read_bytes(), raw)
            with self.assertRaises(FileExistsError):
                m.put(path, b"overwrite")

    def test_immutable_receipt(self):
        self.execute()
        for path in (self.output / "receipts").glob("*.json"):
            receipt = m.read_metadata(path.read_bytes())
            self.assertEqual(m.sha(path.read_bytes()), path.stem)
            self.assertEqual(receipt["retry_count"], 0)
            self.assertIs(receipt["fallback_used"], False)
            with self.assertRaises(FileExistsError):
                m.put_json(path, {})

    def test_thirteen_second_pacing(self):
        self.execute()
        self.assertEqual(self.clock.waits, [13, 13, 13])
        self.replay()

    def test_early_sleep_return(self):
        def early(seconds):
            self.clock.value += min(seconds, 3.25)
        self.clock.sleep = early
        self.execute()
        self.replay()
        self.assertGreaterEqual(self.clock.value, 139.25)

    def failure(self, change=None, error=None):
        def capture(entry):
            self.calls.append(entry)
            if entry["ordinal"] == 2:
                if error:
                    raise error
                return {**response(entry), **change}
            return response(entry)
        result = self.execute(capture)
        self.assertEqual(result["status"], "STOPPED")
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(result["actual_requests"], 2)
        self.assertEqual(result["completed_checkpoints"], 1)
        self.assertTrue((self.output / "traceback.txt").exists())
        self.assertEqual(result, self.replay())
        with self.assertRaisesRegex(Exception, "AUTHORIZATION_ALREADY_CONSUMED"):
            self.execute(output_root=self.artifacts / "retry-forbidden")

    def test_http_fail_stops(self):
        self.failure(change={"http_status": 403})

    def test_timeout_stops(self):
        self.failure(error=TimeoutError("synthetic"))
        self.assertEqual(m.read_metadata((self.output / "STOP.json").read_bytes())["reason"], "STOP_TIMEOUT")

    def test_redirect_stops(self):
        self.failure(change={"http_status": 302, "location": "https://evil.invalid"})

    def test_wrong_final_host_stops(self):
        self.failure(change={"final_url": "https://evil.invalid"})

    def test_schema_fail_stops(self):
        self.failure(change={"raw_bytes": b'{"stat":"OK","date":"20261012"}'})

    def test_unknown_outcome_stops(self):
        self.failure(error=ConnectionResetError("synthetic unknown outcome"))

    def test_future_session_stops(self):
        bad = [{"Date": "20991012", "Code": "SYN", "ClosingPrice": "1"}]
        self.failure(change={"raw_bytes": m.canonical(bad)})

    def test_raw_tamper(self):
        self.execute()
        next((self.output / "raw").glob("*.bin")).write_bytes(b"tamper")
        with self.assertRaisesRegex(Exception, "EVIDENCE_TAMPER"):
            self.replay()

    def test_receipt_tamper(self):
        self.execute()
        next((self.output / "receipts").glob("*.json")).write_bytes(b"{}")
        with self.assertRaisesRegex(Exception, "EVIDENCE_TAMPER"):
            self.replay()

    def test_intent_tamper(self):
        self.execute()
        (self.output / "intents/01.json").write_bytes(b"{}")
        with self.assertRaises(Exception):
            self.replay()

    def test_event_tamper(self):
        self.execute()
        (self.output / "events/01.json").write_bytes(b"{}")
        with self.assertRaises(Exception):
            self.replay()

    def test_checkpoint_tamper(self):
        self.execute()
        (self.output / "checkpoints/02.json").write_bytes(b"{}")
        with self.assertRaises(Exception):
            self.replay()

    def test_ledger_truncation_rejected(self):
        self.execute()
        (self.output / "events/04.json").unlink()
        with self.assertRaises(Exception):
            self.replay()

    def test_result_mutation_rejected(self):
        self.execute()
        result = m.read_metadata((self.output / "RESULT.json").read_bytes())
        result["sessions"]["TWSE:benchmark"] = "2026-10-11"
        (self.output / "RESULT.json").write_bytes(m.canonical(result))
        with self.assertRaises(Exception):
            self.replay()

    def test_failed_response_remains_hash_pinned(self):
        self.failure(change={"http_status": 429})
        stop = m.read_metadata((self.output / "STOP.json").read_bytes())
        raw = self.output / stop["raw"]["path"]
        self.assertEqual(raw.read_bytes(), response(self.plan["entries"][1])["raw_bytes"])
        raw.write_bytes(b"tampered-failure-evidence")
        with self.assertRaisesRegex(Exception, "FAILED_EVIDENCE_TAMPER"):
            self.replay()

    def test_stop_mutation_rejected(self):
        self.failure(error=TimeoutError("synthetic"))
        stop = m.read_metadata((self.output / "STOP.json").read_bytes())
        stop["reason"] = "PASS"
        (self.output / "STOP.json").write_bytes(m.canonical(stop))
        with self.assertRaisesRegex(Exception, "STOP_TAMPER"):
            self.replay()

    def test_first_failure_has_no_later_dispatch(self):
        def fail(entry):
            self.calls.append(entry)
            raise TimeoutError("synthetic first failure")
        result = self.execute(fail)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(result["completed_checkpoints"], 0)
        self.assertEqual(result["actual_requests"], 1)
        self.assertEqual(result, self.replay())

    def test_no_protected_mutations_or_ranking(self):
        protected = self.root / "protected"
        protected.mkdir()
        for name in ("ProductionLatest", "FundamentalLatest", "DecisionState", "Roy", "AI", "Ledger", "Ranking", "Scheduler"):
            (protected / name).write_bytes(b"protected-synthetic-sentinel")
        before = {p.name: m.sha(p.read_bytes()) for p in protected.iterdir()}
        result = self.execute()
        self.assertEqual(before, {p.name: m.sha(p.read_bytes()) for p in protected.iterdir()})
        self.assertEqual(result["ranking_executions"], 0)
        self.assertEqual(result["publication_count"], 0)

    def test_independent_cold_replay(self):
        expected = self.execute()
        for _ in range(2):
            run = subprocess.run([sys.executable, "-B", str(Path(__file__).resolve()), "--cold-replay",
                                  str(self.output), str(self.consumption)], capture_output=True)
            self.assertEqual(run.returncode, 0, run.stderr.decode())
            self.assertEqual(m.read_metadata(run.stdout), expected)

    def test_restart_and_different_output_claim_rejected(self):
        self.execute()
        run = subprocess.run([sys.executable, "-B", str(Path(__file__).resolve()), "--claim",
                              str(self.output), str(self.consumption), "different"], capture_output=True)
        self.assertEqual(run.returncode, 3, run.stderr.decode())
        self.assertIn(b"AUTHORIZATION_ALREADY_CONSUMED", run.stdout)

    def test_concurrent_claim_one_winner(self):
        fixture = self.root / "fixture"
        fixture.mkdir()
        for name, value in (("plan", self.plan), ("seal", self.seal), ("authorization", self.auth)):
            (fixture / (name + ".json")).write_bytes(m.canonical(value))
        children = [subprocess.Popen([sys.executable, "-B", str(Path(__file__).resolve()), "--claim",
                    str(fixture), str(self.consumption), "concurrent" + str(i)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    for i in range(2)]
        outputs = [p.communicate(timeout=60) for p in children]
        self.assertEqual(sorted(p.returncode for p in children), [0, 3], outputs)
        self.assertEqual(len(list(self.consumption.glob("*.json"))), 1)


class ResponseTests(Fixture):
    def test_all_exact_schemas(self):
        for entry in m.targets():
            parsed = m.response_session(response(entry)["raw_bytes"], entry, UTC)
            self.assertEqual(parsed["latest_session"], "2026-10-12")

    def test_bad_date(self):
        for value in ("202610", "2026-10-40", "2026-1-01", "tomorrow", None):
            with self.subTest(value=value), self.assertRaises(Exception):
                m.session_date(value)

    def test_exact_dates_roc_and_gregorian(self):
        for value in ("20261012", "1151012", "115/10/12", "2026-10-12"):
            self.assertEqual(m.session_date(value), "2026-10-12")

    def test_preclose_rejected(self):
        for entry in m.targets():
            with self.assertRaisesRegex(Exception, "PRE_CLOSE"):
                m.response_session(response(entry)["raw_bytes"], entry, "2026-10-12T05:29:59Z")

    def test_prior_day_not_claimed_current(self):
        parsed = m.response_session(response(m.targets()[0])["raw_bytes"], m.targets()[0], "2026-10-13T01:00:00Z")
        self.assertEqual(parsed["latest_session"], "2026-10-12")

    def test_duplicate_json_key(self):
        with self.assertRaises(Exception):
            m.response_session(b'{"date":"20261012","date":"20261011"}', m.targets()[0], UTC)

    def test_nonfinite_json(self):
        for raw in (b'{"x":NaN}', b'{"x":Infinity}', b'{"x":1e999}'):
            with self.subTest(raw=raw), self.assertRaises(Exception):
                m.response_session(raw, m.targets()[0], UTC)

    def test_stock_and_benchmark_schema_not_interchangeable(self):
        with self.assertRaises(Exception):
            m.response_session(response(m.targets()[2])["raw_bytes"], m.targets()[3], UTC)

    def test_mixed_daily_dates_rejected(self):
        raw = m.canonical([{"Date": "1151012", "SecuritiesCompanyCode": "SYN1", "Close": "1"},
                           {"Date": "1151011", "SecuritiesCompanyCode": "SYN2", "Close": "2"}])
        with self.assertRaisesRegex(Exception, "SESSION_IDENTITY"):
            m.response_session(raw, m.targets()[3], UTC)


class TransportTests(Fixture):
    def test_one_attempt_no_redirect_or_proxy(self):
        fake = MagicMock()
        fake.__enter__.return_value = fake
        fake.read.return_value = b"{}"
        fake.code, fake.geturl.return_value = 200, m.targets()[0]["endpoint"]
        fake.headers = {"Content-Type": "application/json"}
        opener = MagicMock()
        opener.open.return_value = fake
        with patch.object(t, "build_opener", return_value=opener) as build:
            result = t.dispatch_once(m.targets()[0])
        self.assertEqual(opener.open.call_count, 1)
        self.assertEqual(opener.open.call_args.kwargs["timeout"], 30)
        self.assertEqual(build.call_args.args[0].proxies, {})
        self.assertIsInstance(build.call_args.args[1], t.NoRedirect)
        self.assertEqual(result["raw_bytes"], b"{}")

    def test_redirect_handler_never_follows(self):
        self.assertIsNone(t.NoRedirect().redirect_request(None, None, 302, "found", {}, "https://evil.invalid"))

    def test_http_error_preserves_bytes_no_retry(self):
        error = HTTPError(m.targets()[0]["endpoint"], 403, "forbidden", {"Content-Type": "application/json"}, io.BytesIO(b"denied"))
        opener = MagicMock()
        opener.open.side_effect = error
        with patch.object(t, "build_opener", return_value=opener):
            result = t.dispatch_once(m.targets()[0])
        self.assertEqual(opener.open.call_count, 1)
        self.assertEqual(result["http_status"], 403)
        self.assertEqual(result["raw_bytes"], b"denied")

    def test_transport_target_guard_before_open(self):
        entry = deepcopy(m.targets()[0])
        entry["endpoint"] += "/alternate"
        with patch.object(t, "build_opener") as opener:
            with self.assertRaises(Exception):
                t.dispatch_once(entry)
            opener.assert_not_called()

    def test_transport_timeout_never_retries(self):
        opener = MagicMock()
        opener.open.side_effect = TimeoutError("synthetic")
        with patch.object(t, "build_opener", return_value=opener):
            with self.assertRaises(TimeoutError):
                t.dispatch_once(m.targets()[0])
        self.assertEqual(opener.open.call_count, 1)

    def test_no_credentials_codepath(self):
        import inspect
        source = inspect.getsource(t) + inspect.getsource(m)
        self.assertNotIn("os.environ", source)
        self.assertNotIn("getenv", source)
        self.assertNotIn("FINMIND_TOKEN", source)

    def test_main_guard_checks_real_git_identity(self):
        self.guard.stop()
        def git(args, **kwargs):
            cmd = args[1:]
            if cmd == ["branch", "--show-current"]:
                return b"main"
            if cmd[:1] == ["rev-parse"]:
                return MAIN.encode()
            if cmd[:1] == ["status"]:
                return b""
            if cmd[:1] == ["show"]:
                return (m.ROOT / cmd[1].split(":", 1)[1]).read_bytes().replace(b"\r\n", b"\n")
            raise AssertionError(cmd)
        with patch.object(m.subprocess, "check_output", side_effect=git):
            m.main_guard(self.plan)

    def test_actual_main_guard_negative_bindings(self):
        self.guard.stop()
        for defect in ("branch", "head", "origin", "dirty", "owner"):
            def git(args, **kwargs):
                cmd = args[1:]
                if cmd == ["branch", "--show-current"]:
                    return b"feature" if defect == "branch" else b"main"
                if cmd[:1] == ["rev-parse"]:
                    bad = defect == "head" and cmd[1] == "HEAD" or defect == "origin" and cmd[1] == "origin/main"
                    return ("0" * 40 if bad else MAIN).encode()
                if cmd[:1] == ["status"]:
                    return b"?? dirty" if defect == "dirty" else b""
                if cmd[:1] == ["show"]:
                    return b"wrong-committed-owner" if defect == "owner" else (m.ROOT / cmd[1].split(":", 1)[1]).read_bytes().replace(b"\r\n", b"\n")
                raise AssertionError(cmd)
            with self.subTest(defect=defect), patch.object(m.subprocess, "check_output", side_effect=git), self.assertRaises(Exception):
                m.main_guard(self.plan)

    def test_network_denial_guard(self):
        from scripts.verify_ci_applicability import network_guard
        for event in ("socket.connect", "socket.getaddrinfo", "socket.sendto", "urllib.Request"):
            with self.subTest(event=event), self.assertRaisesRegex(Exception, "NETWORK_FORBIDDEN"):
                network_guard(event, ("https://synthetic.invalid",))

    def test_cli_plan_offline_candidate_only(self):
        output = self.root / "cli-plan"
        run = subprocess.run([sys.executable, "-B", str(m.ROOT / "scripts/run_session_discovery_execution.py"),
            "--operation", "plan", "--main-sha", MAIN, "--artifacts-root", str(self.artifacts),
            "--consumption-root", str(self.consumption), "--output-dir", str(output)], capture_output=True)
        self.assertEqual(run.returncode, 0, run.stderr.decode())
        candidate = m.read_metadata((output / "CANDIDATE_AUTHORIZATION.json").read_bytes())
        self.assertEqual(candidate["status"], m.PENDING)
        self.assertEqual(m.read_metadata(run.stdout)["network_requests"], 0)
        self.assertFalse(self.consumption.exists())

    def test_os_writer_lock(self):
        self.consumption.mkdir()
        with m.exclusive_scan(self.consumption):
            with self.assertRaisesRegex(Exception, "WRITER_ALREADY_ACTIVE"):
                with m.exclusive_scan(self.consumption):
                    self.fail("second writer")

    def test_cli_synthetic_full_lifecycle(self):
        fixture = self.root / "cli-binding"
        fixture.mkdir()
        for name, value in (("plan", self.plan), ("seal", self.seal), ("authorization", self.auth)):
            (fixture / (name + ".json")).write_bytes(m.canonical(value))
        run = subprocess.run([sys.executable, "-B", str(Path(__file__).resolve()), "--synthetic-cli",
                              str(fixture), str(self.consumption), str(self.output)], capture_output=True)
        self.assertEqual(run.returncode, 0, run.stderr.decode())
        self.assertEqual(m.read_metadata(run.stdout)["actual_requests"], 4)
        self.assertEqual(self.replay()["status"], "PASS")


def helper():
    fixture, consumption = Path(sys.argv[2]), Path(sys.argv[3])
    plan, seal, auth = [m.read_metadata((fixture / (name + ".json")).read_bytes()) for name in ("plan", "seal", "authorization")]
    if sys.argv[1] == "--cold-replay":
        print(m.canonical(m.replay(fixture, plan, seal, auth, consumption)).decode())
        return 0
    if sys.argv[1] == "--claim":
        with patch.object(m, "main_guard"):
            try:
                artifacts = fixture.parent if (fixture / "consumption.json").exists() else fixture.parent / "discovery"
                output = artifacts / sys.argv[4]
                m.claim(plan, seal, auth, artifacts_root=output.parent, consumption_root=consumption,
                        output_root=output, utc=lambda: UTC)
                return 0
            except Exception as error:
                print(str(error))
                return 3
    clock = Clock()
    real_execute = m.execute
    def execute(*args, **kwargs):
        return real_execute(*args, **kwargs, transport=response, utc=lambda: UTC,
                            monotonic=clock.monotonic, sleep=clock.sleep)
    output = Path(sys.argv[4])
    argv = ["run_session_discovery_execution.py", "--operation", "execute", "--main-sha", MAIN,
            "--artifacts-root", str(output.parent), "--consumption-root", str(consumption), "--output-dir", str(output),
            "--plan", str(fixture / "plan.json"), "--seal", str(fixture / "seal.json"),
            "--authorization", str(fixture / "authorization.json")]
    with patch.object(m, "main_guard"), patch.object(m, "execute", side_effect=execute), patch.object(sys, "argv", argv):
        runpy.run_path(str(m.ROOT / "scripts/run_session_discovery_execution.py"), run_name="__main__")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] in ("--cold-replay", "--claim", "--synthetic-cli"):
        from scripts.verify_ci_applicability import network_guard
        sys.addaudithook(network_guard)
        raise SystemExit(helper())
    unittest.main()
