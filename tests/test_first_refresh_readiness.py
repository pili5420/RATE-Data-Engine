"""Synthetic only. A complete synthetic issuer is not real refresh evidence."""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from src import first_refresh_readiness as j
from src.eps_duration_facts.model import Rejected
from src.provider_eps_candidate import _canonical
from scripts import run_prospective_provider_activation as p
from tests.test_prospective_fundamental_provider import universe, eps, revenue, ACTIVATION, LATER, VALIDATED


def fixture():
    auth = {"authority_id": "synthetic-authority-not-real", "activation_timestamp": ACTIVATION}
    events = []
    for n in range(2):
        sources = [("FinMind", {"symbol": "1000", "market": "TWSE"}, eps())]
        sources += [("MOPS Official", {"market": "TWSE", "period": period}, revenue(period))
                    for period in j.CONTRACT["revenue_periods"]]
        for provider, target, (raw, receipt) in sources:
            receipt["synthetic_round"] = n
            rb = _canonical(receipt)
            inspection = p.inspect_source(provider, target, raw, rb, j.sha256(raw), j.sha256(rb), universe(), VALIDATED)
            record = p.record(inspection, auth, LATER)
            events.append({"record": record})
    recovery = {"runtime_status": "RECOVERED_FROM_KNOWN_TERMINAL_FAILURE", "authority_id": auth["authority_id"],
        "resolutions": [{"outcome": "TERMINAL_FAILED_KNOWN_OUTCOME"}]}
    legacy = {"classification": "LEGACY_HISTORICAL_PIT_UNPROVEN", "prospective_credit": 0, "historical_pit": "UNPROVEN"}
    return universe(), universe(), events, auth, recovery, legacy, LATER, p.issuer_readiness


class ReadinessTests(unittest.TestCase):
    def setUp(self):
        self.args = list(fixture())

    def run_dry(self):
        return j.dry_run(*self.args)

    def bad_record(self, field, value):
        self.args[2][0]["record"][field] = value
        with self.assertRaises((Rejected, ValueError)): self.run_dry()

    def test_exact_universe_and_complete_issuer(self):
        result = self.run_dry()["core"]
        self.assertEqual(len(result["issuers"]), 1978)
        self.assertEqual(result["issuers"][0]["issuer_status"], "READY")
        self.assertEqual(sum(r["issuer_status"] == "READY" for r in result["issuers"]), 1)

    def test_same_counts_wrong_identity(self):
        self.args[0]["stocks"][0]["symbol"] = "wrong"
        with self.assertRaisesRegex(Rejected, "EXACT_UNIVERSE"): self.run_dry()

    def test_missing_issuer_rejected(self):
        self.args[0]["stocks"].pop()
        with self.assertRaises(Rejected): self.run_dry()

    def test_market_transfer_rejected(self):
        self.args[0]["stocks"][0]["market"] = "TPEX"
        with self.assertRaises(Rejected): self.run_dry()

    def test_wrong_provider(self): self.bad_record("provider", "Other")
    def test_wrong_dataset(self): self.bad_record("dataset", "Other")
    def test_stale_authority(self): self.bad_record("authority_id", "old")
    def test_activation_mismatch(self): self.bad_record("activation_timestamp", "2026-10-09T00:00:00Z")
    def test_legacy_relabel_rejected(self): self.bad_record("requested_at", "2026-10-09T00:00:00Z")
    def test_future_data_rejected(self): self.bad_record("first_seen_at", "2099-01-01T00:00:00Z")
    def test_invalid_time_order(self): self.bad_record("validation_timestamp", ACTIVATION)
    def test_original_publication_claim_rejected(self): self.bad_record("original_publication_timestamp", ACTIVATION)
    def test_pit_promotion_rejected(self): self.bad_record("historical_pit", "PASS")
    def test_fallback_rejected(self): self.bad_record("fallback_allowed", True)
    def test_validation_failure_rejected(self): self.bad_record("source_identity_gate", "FAIL")

    def test_missing_period_not_zero_filled(self):
        r = self.args[2][-4]["record"]
        removed = r["rows"].pop()
        result = self.run_dry()["core"]["issuers"][0]
        self.assertEqual(result["issuer_status"], "NOT_READY_MISSING_REQUIRED_PERIOD")
        self.assertEqual(len(result["feature_inputs"]["eps"]), 7)
        self.assertNotIn(removed["period"], result["feature_inputs"]["eps"])

    def test_no_older_period_substitution(self):
        self.args[2][-4]["record"]["rows"][-1]["period"] = "2024Q2"
        with self.assertRaisesRegex(Rejected, "IDENTITY_OR_PERIOD"): self.run_dry()

    def test_duplicate_quarter(self):
        r = self.args[2][-4]["record"]
        r["rows"].append(deepcopy(r["rows"][0]))
        with self.assertRaisesRegex(Rejected, "DUPLICATE_PERIOD"): self.run_dry()

    def test_duplicate_observation(self):
        self.args[2].append(deepcopy(self.args[2][-1]))
        with self.assertRaisesRegex(Rejected, "DUPLICATE_OBSERVATION"): self.run_dry()

    def test_partial_valid_evidence_retained(self):
        result = self.run_dry()["core"]["issuers"]
        self.assertEqual(result[1]["issuer_status"], "NOT_READY_MISSING_REQUIRED_PERIOD")
        self.assertEqual(len(result[0]["feature_inputs"]["eps"]), 8)

    def test_no_imputation_for_other_company(self):
        r = self.run_dry()["core"]["issuers"][1]
        self.assertEqual(r["feature_inputs"], {"eps": {}, "revenue": {}})
        self.assertIsNone(r["score"]); self.assertIsNone(r["rank"])

    def test_null_zero_base_preserved(self):
        row = self.args[2][-1]["record"]["rows"][0]
        row["value"] = None; row["numeric_status"] = "UNDEFINED_ZERO_BASE"
        r = self.run_dry()["core"]["issuers"][0]
        self.assertEqual(r["revenue_status"], "NOT_READY_MISSING_REQUIRED_PERIOD")
        self.assertIsNone(r["feature_inputs"]["revenue"]["2026-09"]["value"])

    def test_nonfinite_value(self):
        self.args[2][-4]["record"]["rows"][0]["value"] = "NaN"
        with self.assertRaisesRegex(Rejected, "NONFINITE"): self.run_dry()

    def test_expected_symbols_cannot_silently_shrink(self):
        self.args[2][-1]["record"]["expected_symbols"].pop()
        with self.assertRaisesRegex(Rejected, "EXPECTED_ISSUER"): self.run_dry()

    def test_all_mandatory_periods_fixed(self):
        self.args[2][-4]["record"]["required_periods"].pop()
        with self.assertRaisesRegex(Rejected, "REQUIRED_PERIOD"): self.run_dry()

    def test_negative_zero_decimal_values_retained(self):
        rows = self.run_dry()["core"]["issuers"][0]["feature_inputs"]["eps"]
        self.assertEqual(rows["2024Q3"]["value"], "-0.123456789012345678901")
        self.assertEqual(rows["2024Q4"]["value"], "0")

    def test_recovery_mismatch(self):
        self.args[4]["authority_id"] = "other"
        with self.assertRaisesRegex(Rejected, "RECOVERY"): self.run_dry()

    def test_unknown_outcome_not_a_resolution(self):
        self.args[4]["resolutions"][0]["outcome"] = "UNKNOWN"
        with self.assertRaisesRegex(Rejected, "RECOVERY"): self.run_dry()

    def test_insufficient_soak_blocks_provider(self):
        self.args[2] = self.args[2][:4]
        result = self.run_dry()["core"]
        self.assertTrue(all(r["status"] == "BLOCKED" for r in result["providers"].values()))

    def test_legacy_no_credit(self):
        self.args[5]["prospective_credit"] = 1
        with self.assertRaisesRegex(Rejected, "LEGACY"): self.run_dry()

    def test_deterministic_no_input_mutation(self):
        before = deepcopy(self.args)
        self.assertEqual(self.run_dry(), self.run_dry())
        self.assertEqual(self.args, before)

    def test_input_order_within_scope_not_used_as_period(self):
        original = self.run_dry()
        for e in self.args[2]: e["record"]["rows"].reverse()
        result = self.run_dry()
        self.assertEqual(result["core"]["issuers"][0]["feature_inputs"], original["core"]["issuers"][0]["feature_inputs"])
        self.assertEqual(result["content_sha256"], original["content_sha256"])

    def test_ranking_stays_separate(self):
        r = self.run_dry()["core"]["issuers"][0]
        self.assertEqual(r["issuer_status"], "READY")
        self.assertFalse(r["ranking_eligible"]); self.assertIsNone(r["score"]); self.assertIsNone(r["rank"])

    def test_contract_no_activation(self):
        self.assertEqual(j.CONTRACT["providers"], p.CONTRACT["providers"])
        for key in ("first_refresh_execution_allowed", "production_publication_allowed", "ranking_activation_allowed", "score_execution_allowed", "production_eligible"):
            self.assertIs(j.CONTRACT[key], False)
        self.assertEqual(j.CONTRACT["historical_pit"], "UNPROVEN")
        self.assertEqual(j.CONTRACT["intraday_dependency"], "BLOCKED_EXTERNAL")


class TransactionTests(unittest.TestCase):
    def stages(self): return {s: "PASS" for s in j.CONTRACT["transaction_stages"][:-1]}

    def test_all_stages_still_cannot_publish(self):
        plan = j.transaction_design("old", "old", self.stages())
        self.assertFalse(plan["publish_allowed"])
        self.assertEqual(plan["production_latest_after"], "old")

    def test_each_prepublication_failure_preserves_latest(self):
        for stage in self.stages():
            with self.subTest(stage=stage):
                stages = self.stages(); stages[stage] = "FAIL"
                plan = j.transaction_design("old", "old", stages)
                self.assertEqual(plan["status"], "FAIL_CLOSED")
                self.assertEqual(plan["production_latest_after"], "old")

    def test_pending_prevents_partial_publication(self):
        stages = self.stages(); stages["Assemble"] = "PENDING"
        self.assertFalse(j.transaction_design("old", "old", stages)["publish_allowed"])

    def test_stale_latest_cas_rejected(self):
        with self.assertRaisesRegex(Rejected, "STALE_PRODUCTION_LATEST"): j.transaction_design("old", "changed", self.stages())

    def test_publication_failure_cannot_enter_phase_j(self):
        stages = {**self.stages(), "Publish": "FAIL"}
        with self.assertRaises(Rejected): j.transaction_design("old", "old", stages)

    def test_compatibility_pointer_failure_does_not_partial_commit(self):
        from unittest.mock import patch
        from scripts import publish_production_source_bundle_latest as publisher
        from src import production_refresh_commit as refresh
        from tests.test_production_source_latest_publisher import ProductionSourceLatestPublisherTests
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); bundle = ProductionSourceLatestPublisherTests().bundle()
            file = root / "synthetic-bundle.json"; file.write_text(json.dumps(bundle), encoding="utf-8")
            initial = publisher.publish_latest(source_bundle_path=file, trading_date="2026-09-21", cadence="07:30",
                artifacts_root=root, workflow_run_id="synthetic-old")
            self.assertEqual(initial["publish_result"], "PASS")
            latest = root / "RATE_PRODUCTION_SOURCE_BUNDLE_LATEST.json"; manifest = root / publisher.MANIFEST_LATEST_NAME
            before_latest, before_manifest = latest.read_bytes(), manifest.read_bytes()
            write = publisher.atomic_write_json
            def fail_compatibility(path, value):
                if Path(path) == manifest: raise OSError("SYNTHETIC_COMPATIBILITY_FAILURE")
                return write(path, value)
            with patch.object(publisher, "atomic_write_json", side_effect=fail_compatibility):
                result = publisher.publish_latest(source_bundle_path=file, trading_date="2026-09-21", cadence="07:30",
                    artifacts_root=root, workflow_run_id="synthetic-new")
            self.assertEqual(result["publish_result"], "PASS")
            self.assertEqual(result["transaction_status"], "COMMITTED")
            self.assertNotEqual(latest.read_bytes(), before_latest)
            self.assertEqual(manifest.read_bytes(), before_manifest)
            self.assertTrue(result["post_commit_warnings"])
            refresh.read_committed(latest)
            self.assertEqual(j.publication_readiness()["status"], "PASS")

    def test_publication_and_cer078_governance_are_qualified_without_execution_authorization(self):
        result = j.publication_readiness()
        self.assertEqual(result["reason"], "FIRST_REFRESH_ATOMIC_PUBLICATION_QUALIFIED")
        self.assertEqual(result["authoritative_commit_points"], 1)
        self.assertFalse(result["compatibility_authoritative"])
        self.assertEqual(result["cer078_root_cause"], "UNRESOLVED")
        self.assertEqual(result["cer078_historical_disposition"], "HISTORICAL_NONREPRODUCIBLE_DISPOSITION_ACCEPTED")
        self.assertFalse(result["first_refresh_authorized"])


class IsolationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.guard = j.ReadOnlyGuard(self.root / "new-evidence")

    def test_all_protected_writes_rejected(self):
        for name in ("Production/Latest", "Production/source-snapshot", "Decision State", "Roy Portfolio", "AI Paper Portfolio", "Transaction Ledger", "ranking", "scheduler"):
            with self.subTest(path=name), self.assertRaises(Rejected):
                self.guard("open", (str(self.root / name), "wb", os.O_WRONLY | os.O_CREAT))

    def test_path_escape_rejected(self):
        with self.assertRaises(Rejected): self.guard.write_path(self.root / "new-evidence/../Production")

    def test_allowed_new_external_output(self):
        self.guard.write_path(self.root / "new-evidence/result.json")

    def test_network_denied(self):
        for event in ("socket.connect", "socket.getaddrinfo", "urllib.Request"):
            with self.assertRaisesRegex(RuntimeError, "NETWORK_FORBIDDEN"): self.guard(event, ())

    def test_rename_to_production_rejected(self):
        with self.assertRaises(Rejected): self.guard("os.rename", (str(self.root / "new-evidence/x"), str(self.root / "Production/Latest")))

    def test_git_fetch_child_rejected(self):
        with self.assertRaises(Rejected): self.guard("subprocess.Popen", ("git", ["git", "fetch"], None, None))

    def test_readonly_git_windows_and_linux(self):
        for cmd in (["git", "show", "HEAD"], 'git show HEAD'):
            self.guard("subprocess.Popen", ("git", cmd, None, None))

    def test_arbitrary_child_rejected(self):
        with self.assertRaises(Rejected): self.guard("subprocess.Popen", ("python", ["python", "writer.py"], None, None))

    def test_real_audit_guard_protected_file_unchanged(self):
        protected = self.root / "Latest.json"; protected.write_bytes(b"old snapshot")
        code = "import sys; from pathlib import Path; from src.first_refresh_readiness import ReadOnlyGuard; sys.addaudithook(ReadOnlyGuard(sys.argv[1])); Path(sys.argv[2]).write_bytes(b'tampered')"
        run = subprocess.run([sys.executable, "-B", "-c", code, str(self.root / "new-evidence"), str(protected)], capture_output=True)
        self.assertNotEqual(run.returncode, 0)
        self.assertIn(b"READINESS_PROTECTED_WRITE_FORBIDDEN", run.stderr)
        self.assertEqual(protected.read_bytes(), b"old snapshot")

    def test_independent_cold_process_determinism(self):
        code = "from tests.test_first_refresh_readiness import fixture; from src.first_refresh_readiness import dry_run; print(dry_run(*fixture())['content_sha256'])"
        results = [subprocess.check_output([sys.executable, "-B", "-c", code]) for _ in range(2)]
        self.assertEqual(results[0], results[1])


class SourceGateTests(unittest.TestCase):
    def test_bound_source_mutation(self):
        from scripts.run_first_refresh_readiness import object_at
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "receipt.json"; path.write_bytes(b'{"http_status":200}')
            pin = j.sha256(path.read_bytes()); path.write_bytes(b'{"http_status":502}')
            with self.assertRaisesRegex(Rejected, "TAMPER"): object_at({"path": str(path), "sha256": pin})

    def test_exact_head_rejected_before_source_load(self):
        from unittest.mock import patch
        from scripts import run_first_refresh_readiness as runner
        with patch.object(runner, "git", return_value="wrong"):
            with self.assertRaisesRegex(Rejected, "EXACT_HEAD"):
                runner.inputs({"execution": {"base_sha": j.CONTRACT["base_sha"], "head_sha": "a" * 40}}, Path("unused"))

    def test_raw_and_receipt_tamper(self):
        raw, receipt = eps(); rb = _canonical(receipt)
        for body, rec in ((raw + b"x", rb), (raw, rb + b" ")):
            with self.subTest(raw=len(body)), self.assertRaisesRegex(Rejected, "TAMPER"):
                p.inspect_source("FinMind", {"symbol": "1000", "market": "TWSE"}, body, rec,
                                 j.sha256(raw), j.sha256(rb), universe(), VALIDATED)

    def test_http_failure_rejected(self):
        raw, receipt = eps(); receipt["http_status"] = 502; rb = _canonical(receipt)
        with self.assertRaises(Rejected):
            p.inspect_source("FinMind", {"symbol": "1000", "market": "TWSE"}, raw, rb,
                             j.sha256(raw), j.sha256(rb), universe(), VALIDATED)


class PortabilityIntegrationTests(unittest.TestCase):
    """Synthetic pins only; real historical replay is separately local."""
    def setUp(self):
        from scripts import run_first_refresh_readiness as runner
        self.runner = runner
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.output = self.root / "output"
        self.output.mkdir()
        def pin(name, value):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            body = _canonical(value); path.write_bytes(body)
            return {"path": str(path), "sha256": j.sha256(body)}
        self.pin = pin
        self.binding = {"execution": {"base_sha": j.CONTRACT["base_sha"], "head_sha": "a" * 40},
            "accepted_continuation_reader": pin("continuation.py", {"synthetic": True}),
            "continuation_root": str(self.root)}
        for name in ("recovery_binding", "recovery_checkpoint", "continuation_checkpoint"):
            self.binding[name] = pin(name + ".json", {"synthetic": name})
        self.portable = {"artifact_kind": j.CONTRACT["historical_replay_contract"],
            "producer_sha": j.CONTRACT["historical_producer_sha"],
            "current_main_sha": j.CONTRACT["base_sha"], "consumer_head_sha": "a" * 40,
            "consumer_checkout": str(runner.ROOT), "repository_checkout": str(runner.ROOT),
            "accepted_reader": self.binding["accepted_continuation_reader"],
            "accepted_output": pin("accepted.json", {"same_count": 1, "identity": "original"}),
            "fallback_allowed": False,
            "evidence_pins": {name: self.binding[name] for name in
                ("recovery_binding", "recovery_checkpoint", "continuation_checkpoint")}}
        self.portable["evidence_pins"]["configuration"] = pin("continuation-evidence/CONFIG.json", {"synthetic": True})
        self.bind()

    def bind(self):
        self.binding["historical_replay_portability"] = self.pin("PORTABILITY.json", self.portable)

    def command(self):
        return self.runner.portability_command(self.binding, self.output)

    def test_three_distinct_identities_and_exact_command(self):
        command = self.command()
        self.assertEqual(len({self.portable[k] for k in ("producer_sha", "current_main_sha", "consumer_head_sha")}), 3)
        self.assertEqual(command[:3], [sys.executable, "-B", str(self.runner.ROOT / "scripts/run_historical_replay_portability.py")])
        self.assertEqual(command[-1], str(self.output / "historical-replay"))

    def test_wrong_producer_rejected(self):
        self.portable["producer_sha"] = "b" * 40; self.bind()
        with self.assertRaisesRegex(Rejected, "EXECUTION_BINDING"): self.command()

    def test_stale_main_rejected(self):
        self.portable["current_main_sha"] = "b" * 40; self.bind()
        with self.assertRaisesRegex(Rejected, "EXECUTION_BINDING"): self.command()

    def test_stale_consumer_rejected(self):
        self.portable["consumer_head_sha"] = "b" * 40; self.bind()
        with self.assertRaisesRegex(Rejected, "EXECUTION_BINDING"): self.command()

    def test_reader_substitution_rejected(self):
        self.portable["accepted_reader"] = self.portable["accepted_output"]; self.bind()
        with self.assertRaisesRegex(Rejected, "READER_BINDING"): self.command()

    def test_recovery_substitution_rejected(self):
        self.portable["evidence_pins"]["recovery_binding"] = self.portable["accepted_output"]; self.bind()
        with self.assertRaisesRegex(Rejected, "EVIDENCE_BINDING"): self.command()

    def test_binding_tamper_rejected(self):
        Path(self.binding["historical_replay_portability"]["path"]).write_bytes(b"{}")
        with self.assertRaisesRegex(Rejected, "TAMPER"): self.command()

    def test_guard_only_allows_exact_worker_command_and_cwd(self):
        command = self.command(); guard = j.ReadOnlyGuard(self.output, command)
        guard("subprocess.Popen", (sys.executable, command, str(j.ROOT), {}))
        for altered in (command + ["--anything"], [sys.executable, "-c", "print('other')"]):
            with self.subTest(command=altered), self.assertRaisesRegex(Rejected, "CHILD_EXECUTION"):
                guard("subprocess.Popen", (sys.executable, altered, str(j.ROOT), {}))
        with self.assertRaisesRegex(Rejected, "PROCESS_BINDING"):
            guard("subprocess.Popen", (sys.executable, command, str(self.root), {}))
        with self.assertRaisesRegex(Rejected, "PROCESS_BINDING"):
            guard("subprocess.Popen", (None, command, str(j.ROOT), {}))

    def test_real_subprocess_audit_round_trip_with_explicit_executable(self):
        code = (
            "import sys, subprocess; from src.first_refresh_readiness import ReadOnlyGuard, ROOT; "
            "command=[sys.executable,'-B','-c',\"print('synthetic-worker')\"]; "
            "sys.addaudithook(ReadOnlyGuard(" + repr(str(self.output)) + ", command)); "
            "result=subprocess.run(command, executable=sys.executable, cwd=ROOT, capture_output=True, check=True); "
            "assert result.stdout.strip()==b'synthetic-worker'; print('PASS')")
        result = subprocess.check_output([sys.executable, "-B", "-c", code], cwd=j.ROOT)
        self.assertEqual(result.strip(), b"PASS")

    def test_worker_failure_preserved_without_fallback(self):
        from unittest.mock import patch
        with patch.object(self.runner.subprocess, "run", return_value=subprocess.CompletedProcess([], 1, b"", b"synthetic failure")) as run:
            with self.assertRaisesRegex(Rejected, "WORKER_FAILED"):
                self.runner.replay_continuation(self.binding, self.output)
            self.assertEqual(run.call_count, 1)
            self.assertEqual(run.call_args.kwargs["executable"], sys.executable)
        self.assertEqual((self.output / "portability-worker.stderr.txt").read_bytes(), b"synthetic failure")

    def test_same_counts_changed_full_object_rejected(self):
        from unittest.mock import patch
        path = self.output / "historical-replay/REPLAY.json"
        path.parent.mkdir(); path.write_bytes(_canonical({"same_count": 1, "identity": "changed"}))
        with patch.object(self.runner.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, b"{}", b"")):
            with self.assertRaisesRegex(ValueError, "^PORTABILITY_HISTORICAL_OUTPUT_MISMATCH$"):
                self.runner.replay_continuation(self.binding, self.output)


if __name__ == "__main__": unittest.main()
