"""Engineering fixtures only: precise calculations, cold reads and fail-closed gates."""
from copy import deepcopy
from decimal import Decimal, localcontext
from pathlib import Path
import json
import os
import random
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from src.eps_duration_facts.model import Rejected
from src.eps_duration_facts.raw import sha256
from src.provider_eps_candidate import _canonical
from src.provider_financial_feature_inputs import verify_file, load_closeout
from src.provider_financial_features import (CONTRACT, EPS_NAMES, REVENUE_NAME, compute_core, exact_sum,
    revenue_mean, hash_object, seal, export_package, consume, validate_package, ordered_inputs)
from tests.provider_financial_features_fixture import fixture_inputs


class FeaturesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="provider-features-engineering-")
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.raw = self.directory / "synthetic"
        self.raw.mkdir()
        self.inputs = fixture_inputs(self.raw)

    def row(self, core, symbol="2330", name=EPS_NAMES[0]):
        return next(c for c in core["companies"] if c["symbol"] == symbol)["features"][name]

    def missing(self, quarter):
        self.inputs["eps"] = [r for r in self.inputs["eps"] if not (r["symbol"] == "2330" and r["analysis_quarter"] == quarter)]
        self.inputs["gaps"].append({"symbol": "2330", "market": "TWSE", "analysis_quarter": quarter, "classification": "NO_PROVIDER_ROWS_FOR_QUARTER"})

    def export(self):
        package = seal(compute_core(self.inputs))
        out = self.directory / "features"
        export_package(package, out)
        return out, sha256((out / "FEATURE_MANIFEST.json").read_bytes()), package

    def replay(self, binding):
        return fixture_inputs(Path(binding["engineering_fixture_root"]), create=False)

    def test_four_named_features_and_independent_identity(self):
        core = compute_core(self.inputs)
        self.assertEqual(set(self.row_company(core)["features"]), set(CONTRACT["features"]))
        self.assertEqual(core["summary"]["companies"], 4)
        self.assertNotIn("quarterly_eps", core)
        self.assertNotIn("Fundamental", self.row_company(core))
        self.assertFalse(core["decision_eligible"])

    def row_company(self, core, symbol="2330"):
        return next(c for c in core["companies"] if c["symbol"] == symbol)

    def test_explicit_latest_and_previous_values_not_swapped(self):
        for row in self.inputs["eps"]:
            row["provider_value"] = "10" if row["analysis_quarter"] in CONTRACT["latest4"] else "1"
        core = compute_core(self.inputs)
        self.assertEqual(self.row(core)["value"], "40")
        self.assertEqual(self.row(core, name=EPS_NAMES[1])["value"], "4")
        self.assertEqual(self.row(core, name=EPS_NAMES[2])["value"], "36")

    def test_shuffled_inputs_have_same_values_and_content_identity(self):
        before = compute_core(self.inputs)
        random.Random(11).shuffle(self.inputs["eps"])
        self.inputs["revenue"].reverse()
        self.inputs["universe"]["stocks"].reverse()
        self.assertEqual(hash_object(before), hash_object(compute_core(self.inputs)))

    def test_previous_gap_does_not_block_latest_four(self):
        self.missing("2024Q3")
        core = compute_core(self.inputs)
        self.assertEqual(self.row(core)["status"], "COMPUTABLE")
        self.assertIsNone(self.row(core, name=EPS_NAMES[1])["value"])
        self.assertIsNone(self.row(core, name=EPS_NAMES[2])["value"])

    def test_latest_gap_does_not_block_previous_four(self):
        self.missing("2026Q2")
        core = compute_core(self.inputs)
        self.assertIsNone(self.row(core)["value"])
        self.assertEqual(self.row(core, name=EPS_NAMES[1])["status"], "COMPUTABLE")

    def test_three_quarters_never_called_four(self):
        self.missing("2026Q1")
        row = self.row(compute_core(self.inputs))
        self.assertIsNone(row["value"])
        self.assertEqual(len(row["necessary_inputs"]), 4)
        self.assertEqual(row["missing_reasons"], [{"period": "2026Q1", "reason": "MISSING_QUARTER"}])

    def test_duplicate_quarter_rejected(self):
        self.inputs["eps"].append(deepcopy(self.inputs["eps"][0]))
        with self.assertRaisesRegex(Rejected, "DUPLICATE_OR_CONFLICT"):
            compute_core(self.inputs)

    def test_conflicting_quarter_rejected(self):
        other = dict(self.inputs["eps"][0], provider_value="999")
        self.inputs["eps"].append(other)
        with self.assertRaisesRegex(Rejected, "DUPLICATE_OR_CONFLICT"):
            compute_core(self.inputs)

    def test_out_of_window_or_wrong_date_rejected(self):
        for period, date in (("2024Q2", "2024-06-30"), ("2024Q3", "2026-06-30")):
            data = deepcopy(self.inputs)
            data["eps"][0].update(analysis_quarter=period, provider_date=date)
            with self.assertRaisesRegex(Rejected, "OUT_OF_WINDOW"):
                compute_core(data)

    def test_identity_market_conflict_rejected(self):
        self.inputs["eps"][0]["market"] = "INVALID"
        with self.assertRaisesRegex(Rejected, "IDENTITY_CONFLICT"):
            compute_core(self.inputs)

    def test_zero_and_negative_values_retained(self):
        self.assertEqual(exact_sum(["0", "-4.25", "1.25", "0"]), Decimal("-3.00"))
        core = compute_core(self.inputs)
        self.assertEqual(len(core["inputs"]["eps"]), 24)
        self.assertTrue(any(Decimal(r["provider_value"]) < 0 for r in core["inputs"]["eps"]))

    def test_decimal_precision_not_default_context(self):
        with localcontext() as context:
            context.prec = 5
            self.assertEqual(str(exact_sum(["123456789.123456789123456789", "0.000000000000000001"])), "123456789.123456789123456790")

    def test_delta_negation_does_not_round_long_values(self):
        for row in self.inputs["eps"]:
            row["provider_value"] = "1.000000000000000000000000000001" if row["analysis_quarter"] in CONTRACT["previous4"] else "0"
        self.assertEqual(Decimal(self.row(compute_core(self.inputs), name=EPS_NAMES[2])["value"]), Decimal("-4.000000000000000000000000000004"))

    def test_nonfinite_and_boolean_values_rejected(self):
        for value in ("NaN", "Infinity", "-Infinity", True):
            data = deepcopy(self.inputs)
            data["eps"][0]["provider_value"] = value
            with self.assertRaises(Rejected):
                compute_core(data)

    def test_revenue_mean_scale_and_rounding_are_reproducible(self):
        self.assertEqual(revenue_mean(["100", "100", "100"]), "100.000000000000")
        self.assertEqual(revenue_mean(["0", "0", "1"]), "0.333333333333")
        self.assertEqual(revenue_mean(["-1", "0", "0"]), "-0.333333333333")
        self.assertEqual(revenue_mean(["0.0000000000005"] * 3), "0.000000000000")

    def test_revenue_zero_base_stays_null_not_zero(self):
        row = next(r for r in self.inputs["revenue"] if r["symbol"] == "2330")
        row.update(revenue_yoy=None, revenue_yoy_status="UNDEFINED_ZERO_BASE")
        result = self.row(compute_core(self.inputs), name=REVENUE_NAME)
        self.assertIsNone(result["value"])
        self.assertEqual(result["missing_reasons"][0]["reason"], "UNDEFINED_ZERO_BASE")

    def test_missing_revenue_month_does_not_shrink_divisor(self):
        self.inputs["revenue"] = [r for r in self.inputs["revenue"] if not (r["symbol"] == "2330" and r["period"] == "2026-09")]
        self.assertIsNone(self.row(compute_core(self.inputs), name=REVENUE_NAME)["value"])
        with self.assertRaisesRegex(Rejected, "THREE_REQUIRED"):
            revenue_mean(["1", "2"])

    def test_nonfinite_revenue_and_illegal_null_rejected(self):
        for value, status in (("NaN", "VALID_NUMERIC"), (None, "VALID_NUMERIC"), ("0", "UNDEFINED_ZERO_BASE")):
            data = deepcopy(self.inputs)
            data["revenue"][0].update(revenue_yoy=value, revenue_yoy_status=status)
            with self.assertRaises(Rejected):
                compute_core(data)

    def test_duplicate_or_other_revenue_period_rejected(self):
        self.inputs["revenue"].append(deepcopy(self.inputs["revenue"][0]))
        with self.assertRaisesRegex(Rejected, "DUPLICATE_OR_CONFLICT"):
            compute_core(self.inputs)
        self.inputs["revenue"].pop()
        self.inputs["revenue"][0]["period"] = "2026-06"
        with self.assertRaisesRegex(Rejected, "IDENTITY_CONFLICT"):
            compute_core(self.inputs)

    def test_partial_eligibility_and_company_retention(self):
        self.missing("2024Q3")
        core = compute_core(self.inputs)
        self.assertEqual(core["summary"]["companies"], 4)
        self.assertEqual(core["summary"]["all_three_eps_features"], 2)
        self.assertEqual(core["summary"]["all_four_features"], 2)
        self.assertEqual(core["summary"]["partial_features"], 2)
        self.assertEqual(len(core["inputs"]["eps"]), 23)

    def test_unknown_versions_and_q4_not_upgraded(self):
        core = compute_core(self.inputs)
        self.assertTrue(all(r["filing_id"] is None and r["public_time"] is None for r in core["inputs"]["eps"]))
        self.inputs["eps"][0]["revision_id"] = "LATEST"
        with self.assertRaisesRegex(Rejected, "FABRICATED"):
            compute_core(self.inputs)

    def test_effective_generated_validated_observed_times_separated(self):
        out, digest, package = self.export()
        time = package["execution"]["per_feature_time"]["2330"][EPS_NAMES[0]]
        self.assertEqual(time["contract_effective_at"], CONTRACT["contract_effective_at"])
        self.assertGreaterEqual(time["feature_available_at"], time["feature_validated_at"])
        self.assertEqual(consume(out, digest, source_replayer=self.replay)["status"], "PASS")

    def test_not_usable_at_historical_cutoff(self):
        _out, _digest, package = self.export()
        with self.assertRaisesRegex(Rejected, "TIME_NOT_REACHED"):
            validate_package(package, as_of="2026-10-05T23:59:59+00:00")

    def test_fake_generation_or_future_validation_rejected(self):
        core = compute_core(self.inputs)
        with self.assertRaisesRegex(Rejected, "NOT_EFFECTIVE"):
            seal(core, generated_at="2026-10-07T00:00:00+00:00")
        with self.assertRaisesRegex(Rejected, "FABRICATED"):
            seal(core, validated_at="2099-01-01T00:00:00+00:00")

    def test_input_time_after_generation_rejected(self):
        self.inputs["eps"][0]["verified_observed_at"] = "2099-01-01T00:00:00+00:00"
        with self.assertRaisesRegex(Rejected, "BEFORE_INPUT"):
            seal(compute_core(self.inputs))

    def test_repeat_core_identity_ignores_run_timestamps(self):
        core = compute_core(self.inputs)
        first, second = seal(core), seal(compute_core(self.inputs))
        self.assertEqual(first["content_sha256"], second["content_sha256"])
        self.assertNotEqual(first["execution"]["feature_generated_at"], second["execution"]["feature_generated_at"])

    def test_manifest_and_artifact_tamper_rejected(self):
        out, digest, _package = self.export()
        artifact = out / "PROVIDER_FINANCIAL_FEATURES_V1.json"
        original = artifact.read_bytes()
        artifact.write_bytes(original + b" ")
        with self.assertRaisesRegex(Rejected, "ARTIFACT_TAMPERED"):
            consume(out, digest, source_replayer=self.replay)
        artifact.write_bytes(original)
        manifest = out / "FEATURE_MANIFEST.json"
        manifest.write_bytes(manifest.read_bytes() + b" ")
        with self.assertRaisesRegex(Rejected, "MANIFEST_TAMPERED"):
            consume(out, digest, source_replayer=self.replay)

    def test_raw_and_receipt_tamper_rejected_by_reused_source_validator(self):
        out, digest, package = self.export()
        for field in ("raw_reference", "receipt_reference"):
            path = Path(package["core"]["inputs"]["eps"][0][field])
            original = path.read_bytes()
            path.write_bytes(original + b" ")
            with self.assertRaises(Rejected):
                consume(out, digest, source_replayer=self.replay)
            path.write_bytes(original)

    def test_generic_source_hash_and_closeout_manifest_tamper_rejected(self):
        path = self.directory / "source.json"
        path.write_bytes(b"{}")
        expected = {"bytes": 2, "sha256": sha256(b"{}")}
        path.write_bytes(b"[]")
        with self.assertRaisesRegex(Rejected, "SOURCE_FILE_TAMPERED"):
            verify_file(path, expected)
        with self.assertRaisesRegex(Rejected, "CLOSEOUT_MANIFEST_TAMPERED"):
            load_closeout(path, sha256(b"{}"))

    def test_output_escape_or_existing_directory_rejected(self):
        package = seal(compute_core(self.inputs))
        with self.assertRaisesRegex(Rejected, "NEW_EXTERNAL"):
            export_package(package, self.directory)
        with self.assertRaisesRegex(Rejected, "PROTECTED_OUTPUT"):
            export_package(package, self.directory / "Production" / "child")

    def test_source_replayer_required_and_false_replay_rejected(self):
        out, digest, _package = self.export()
        with self.assertRaisesRegex(Rejected, "SOURCE_REPLAY_REQUIRED"):
            consume(out, digest)
        wrong = deepcopy(self.inputs)
        wrong["eps"][0]["provider_value"] = "999"
        with self.assertRaisesRegex(Rejected, "INPUT_REPLAY_MISMATCH"):
            consume(out, digest, source_replayer=lambda _binding: wrong)

    def test_new_process_cold_consumer_keeps_digest_and_source_replay(self):
        out, digest, package = self.export()
        repo = Path(__file__).resolve().parents[1]
        command = "from pathlib import Path; from src.provider_financial_features import consume; from tests.provider_financial_features_fixture import fixture_inputs; import json,sys; print(json.dumps(consume(sys.argv[1],sys.argv[2],source_replayer=lambda b: fixture_inputs(Path(b['engineering_fixture_root']),create=False))))"
        run = subprocess.run([sys.executable, "-B", "-c", command, str(out), digest], cwd=repo, capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        result = json.loads(run.stdout)
        self.assertEqual(result["content_sha256"], package["content_sha256"])
        self.assertEqual(result["summary"]["all_four_features"], 3)

    def test_contract_window_cannot_slide_with_current_date(self):
        wrong = deepcopy(CONTRACT)
        wrong["latest4"][0] = "2026Q3"
        with self.assertRaisesRegex(Rejected, "CONTRACT_MISMATCH"):
            compute_core(self.inputs, wrong)

    def test_contract_key_order_does_not_change_feature_meaning(self):
        reordered = deepcopy(CONTRACT)
        reordered["features"] = dict(reversed(list(reordered["features"].items())))
        self.assertEqual(hash_object(compute_core(self.inputs)), hash_object(compute_core(self.inputs, reordered)))

    def test_gap_market_or_classification_cannot_change(self):
        self.inputs["gaps"][0]["market"] = "TWSE"
        with self.assertRaisesRegex(Rejected, "GAP_IDENTITY"):
            compute_core(self.inputs)

    def test_q4_cannot_be_upgraded_to_official_or_known_version(self):
        row = next(r for r in self.inputs["eps"] if r["analysis_quarter"].endswith("Q4"))
        row["q4_raw_or_derived_classification"] = "OFFICIALLY_REPORTED"
        with self.assertRaisesRegex(Rejected, "VERSION_CLAIM"):
            compute_core(self.inputs)

    def test_non_basic_label_and_false_locator_rejected(self):
        wrong = deepcopy(self.inputs)
        wrong["eps"][0]["provider_origin_name"] = "DILUTED"
        with self.assertRaises(Rejected):
            compute_core(wrong)
        self.inputs["eps"][0]["raw_row_index_zero_based"] = True
        with self.assertRaisesRegex(Rejected, "LOCATOR_INVALID"):
            compute_core(self.inputs)

    def test_time_metadata_tamper_rejected_even_when_core_unchanged(self):
        _out, _digest, package = self.export()
        package["execution"]["per_feature_time"]["2330"][EPS_NAMES[0]]["feature_available_at"] = "2026-10-05T00:00:00+00:00"
        with self.assertRaisesRegex(Rejected, "PACKAGE_TAMPERED"):
            validate_package(package)

    def test_manifest_cannot_escape_with_extra_file_path(self):
        out, _digest, _package = self.export()
        path = out / "FEATURE_MANIFEST.json"
        manifest = json.loads(path.read_bytes())
        manifest["files"]["../outside.json"] = manifest["files"]["PROVIDER_FINANCIAL_FEATURES_V1.json"]
        path.write_bytes(_canonical(manifest))
        with self.assertRaisesRegex(Rejected, "PATH_INVALID"):
            consume(out, sha256(path.read_bytes()), source_replayer=self.replay)

    def test_output_inside_another_repository_rejected(self):
        other = self.directory / "other-checkout"
        (other / ".git").mkdir(parents=True)
        (other / ".git/HEAD").write_text("ref: refs/heads/engineering\n", encoding="ascii")
        with self.assertRaisesRegex(Rejected, "IN_GIT_REPOSITORY"):
            export_package(seal(compute_core(self.inputs)), other / "features")


class FormalNonInterferenceTests(unittest.TestCase):
    def test_formal_entry_absent_present_updated_package_same_existing_input(self):
        from scripts import build_live_source_bundle as live
        formal = {"1000": {"Fundamental": "ENGINEERING_EXISTING_SENTINEL_NOT_CALCULATED"}}
        results = []
        with tempfile.TemporaryDirectory(prefix="features-formal-noninterference-") as temporary:
            package = Path(temporary) / "PROVIDER_FINANCIAL_FEATURES_V1.json"
            for state in ("ABSENT", "PRESENT", "UPDATED"):
                if state != "ABSENT":
                    package.write_bytes(_canonical({"engineering_fixture": True, "new_provider_feature": 1 if state == "PRESENT" else 999}))
                with patch.dict(os.environ, {"RATE_PROVIDER_FINANCIAL_FEATURES_ROOT": str(package.parent)}), \
                     patch.object(live, "_accepted_fundamental_history", return_value=deepcopy(formal)), \
                     patch.object(live, "calculate_fundamental", side_effect=AssertionError("FORMAL_SCORE_FORBIDDEN")) as scoring, \
                     patch.object(live, "_write", side_effect=AssertionError("PRODUCTION_WRITE_FORBIDDEN")):
                    results.append(live._fundamental_history(["1000"], as_of_date="2026-10-05"))
                    self.assertFalse(scoring.called)
        self.assertEqual(results, [formal] * 3)

    def test_candidate_presence_cannot_fill_missing_formal_eps(self):
        from scripts import build_live_source_bundle as live
        results = []
        with tempfile.TemporaryDirectory(prefix="features-missing-formal-") as temporary:
            package = Path(temporary) / "PROVIDER_FINANCIAL_FEATURES_V1.json"
            for state in ("ABSENT", "PRESENT", "UPDATED"):
                if state != "ABSENT":
                    package.write_bytes(_canonical({"engineering_fixture": True, "all_four_features": True, "state": state}))
                with patch.dict(os.environ, {"RATE_PROVIDER_FINANCIAL_FEATURES_ROOT": str(package.parent)}), \
                     patch.object(live, "_accepted_fundamental_history", return_value=None), \
                     patch.object(live, "FundamentalHistoryStoreV2") as store, \
                     patch.object(live, "MOPSHistoricalFundamentalAdapter") as adapter, \
                     patch.object(live, "calculate_fundamental", side_effect=AssertionError("FORMAL_SCORE_FORBIDDEN")) as scoring, \
                     patch.object(live, "_write", side_effect=AssertionError("PRODUCTION_WRITE_FORBIDDEN")):
                    store.return_value.select_asof.return_value = {"1000": {"revenue": {}, "eps": {}}}
                    adapter.return_value.fetch_eps_period.side_effect = RuntimeError("ENGINEERING_MISSING_FORMAL_EPS")
                    with self.assertRaisesRegex(RuntimeError, "MISSING_FORMAL_EPS") as outcome:
                        live._fundamental_history(["1000"], as_of_date="2026-10-05")
                    results.append(str(outcome.exception))
                    self.assertFalse(scoring.called)
                    self.assertFalse(store.return_value.upsert.called)
        self.assertEqual(len(set(results)), 1)
