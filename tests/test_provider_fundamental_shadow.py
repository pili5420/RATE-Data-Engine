"""Synthetic-only known-answer, lifecycle, boundary and non-interference tests."""
from copy import deepcopy
from decimal import Decimal
import json
import math
import os
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from src.eps_duration_facts.model import Rejected
from src.eps_duration_facts.raw import sha256
from src.provider_eps_candidate import _canonical
from src.provider_financial_features import EPS_NAMES, REVENUE_NAME, hash_object, seal as feature_seal, compute_core as feature_core, export_package
from src.provider_fundamental_shadow import SPEC, SCORE, NAMES, compute_core, seal, validate, export, consume, finite_float
from src.provider_fundamental_shadow_inputs import load_delivery, source_pin
from tests.provider_fundamental_shadow_fixture import feature_package, load_synthetic, synthetic_inputs


def reference_percentile(value, rows):
    # Independent less/equal counts, not the production sort-and-rank helper.
    target, values = float(value), [float(v) for v in rows]
    less = sum(v < target for v in values)
    equal = sum(v == target for v in values)
    return round(100 * (less + (equal + 1) / 2 - 1) / (len(values) - 1), 2)


class ShadowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="shadow-synthetic-")
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.root = self.directory / "synthetic"
        self.root.mkdir()
        self.features = feature_package(self.root)

    def feature_change(self, change):
        data = deepcopy(self.features["core"]["inputs"])
        change(data)
        self.features = feature_seal(feature_core(data), code_binding=self.features["execution"]["code_binding"])

    def emit(self):
        source = self.directory / "source-features"
        export_package(self.features, source)
        pin = {"synthetic_feature_directory": str(source), "feature_manifest_sha256": sha256((source / "FEATURE_MANIFEST.json").read_bytes())}
        package = seal(compute_core(self.features), pin)
        output = self.directory / "shadow"
        digest = export(package, output)
        return output, digest, package

    def test_known_answer_independent_components_contributions_scores_and_ranks(self):
        core = compute_core(self.features)
        scored = [c for c in core["companies"] if c[SCORE] is not None]
        self.assertEqual(len(scored), 22)
        for company in scored:
            expected = []
            for name, weight in zip(NAMES, (0.5, 0.3, 0.2)):
                p = reference_percentile(company["features"][name]["value"], [c["features"][name]["value"] for c in scored])
                self.assertEqual(company["components"][name]["percentile"], p)
                self.assertEqual(company["components"][name]["weighted_contribution"], weight * p)
                expected.append(weight * p)
            self.assertEqual(company[SCORE], sum(expected))
            self.assertEqual(company["shadow_rank"], 1 + sum(c[SCORE] > company[SCORE] for c in scored))

    def test_windows_latest_previous_and_delta_not_reversed(self):
        company = compute_core(self.features)["companies"][0]
        self.assertEqual(Decimal(company["features"][EPS_NAMES[0]]["value"]), Decimal(-48))
        self.assertEqual(Decimal(company["features"][EPS_NAMES[1]]["value"]), Decimal(0))
        self.assertEqual(Decimal(company["features"][EPS_NAMES[2]]["value"]), Decimal(-48))

    def test_shuffled_feature_input_has_same_core_and_population(self):
        expected = compute_core(self.features)
        data = deepcopy(self.features["core"]["inputs"])
        for key in ("eps", "revenue", "gaps"):
            random.Random(7).shuffle(data[key])
        data["universe"]["stocks"].reverse()
        other = feature_seal(feature_core(data), generated_at=self.features["execution"]["feature_generated_at"],
            validated_at=self.features["execution"]["feature_validated_at"], code_binding=self.features["execution"]["code_binding"])
        self.assertEqual(expected, compute_core(other))

    def test_same_score_competition_rank_symbol_only_display(self):
        def change(data):
            for row in data["eps"]:
                row["provider_value"] = "0"
            for row in data["revenue"]:
                if row["revenue_yoy_status"] == "VALID_NUMERIC":
                    row["revenue_yoy"] = "0"
        self.feature_change(change)
        core = compute_core(self.features)
        scored = [r for r in core["companies"] if r[SCORE] is not None]
        self.assertTrue(all(c["shadow_rank"] == 1 and c[SCORE] == 50 for c in scored))
        self.assertEqual(core["scored_display_order"], sorted(c["symbol"] for c in scored))

    def test_zero_negative_and_original_decimal_strings_preserved(self):
        core = compute_core(self.features)
        self.assertTrue(any(Decimal(c["features"][EPS_NAMES[0]]["value"]) < 0 for c in core["companies"]))
        self.assertTrue(any(Decimal(c["features"][EPS_NAMES[0]]["value"]) == 0 for c in core["companies"]))
        for c in core["companies"]:
            for n in NAMES:
                self.assertEqual(c["components"][n]["raw_feature_value"], c["features"][n]["value"])

    def test_rounding_matches_python_pctl_and_no_extra_score_rounding(self):
        core = compute_core(self.features)
        row = next(c for c in core["companies"] if c["symbol"] == "1001")
        self.assertEqual(row["components"][EPS_NAMES[0]]["percentile"], 4.76)
        self.assertEqual(row[SCORE], sum(row["components"][n]["weighted_contribution"] for n in NAMES))

    def test_same_population_for_all_three_components(self):
        core = compute_core(self.features)
        population = core["populations"]["A_COMPLETE_INPUT"]["population_id"]
        self.assertTrue(all(c["components"][n]["percentile_population_id"] == population
            for c in core["companies"] if c[SCORE] is not None for n in NAMES))

    def test_minimum_applies_after_eligibility_filter(self):
        self.features = feature_package(self.root, count=21)
        with self.assertRaisesRegex(Rejected, "FILTERED_POPULATION_TOO_SMALL"):
            compute_core(self.features)

    def test_twenty_eligible_is_allowed(self):
        self.features = feature_package(self.root, count=22)
        self.assertEqual(compute_core(self.features)["summary"]["shadow_scoring_population"], 20)

    def test_missing_feature_keeps_null_no_imputation_or_reweighting(self):
        core = compute_core(self.features)
        for company in core["companies"][-2:]:
            self.assertIsNone(company[SCORE])
            self.assertIsNone(company["shadow_rank"])
            self.assertTrue(company["unscored_reasons"])
            self.assertEqual([company["components"][n]["weight"] for n in NAMES], [0.5, 0.3, 0.2])
            self.assertTrue(all(company["components"][n]["percentile"] is None for n in NAMES))

    def test_eight_quarters_required_even_when_three_score_features_available(self):
        core = compute_core(self.features)
        company = core["companies"][-1]
        self.assertEqual(company["features"][EPS_NAMES[0]]["status"], "COMPUTABLE")
        self.assertIsNone(company[SCORE])

    def test_sensitivity_uses_separate_actual_sets_and_no_mixed_scores(self):
        core = compute_core(self.features)
        self.assertEqual([core["populations"][k]["count"] for k in ("A_COMPLETE_INPUT", "B_EIGHT_QUARTER_EPS", "C_REVENUE_3M")], [22, 23, 23])
        self.assertEqual(len(core["sensitivity_matrix"]), 66)
        self.assertTrue(all(SCORE not in row for row in core["sensitivity_matrix"]))
        for row in core["sensitivity_matrix"]:
            self.assertEqual(row["difference_alternative_minus_A"], row["alternative_percentile"] - row["A_percentile"])

    def test_float_conversion_nonfinite_and_bool_fail_closed(self):
        for value in ("1e1000", "NaN", "Infinity", True):
            with self.assertRaises((Rejected, OverflowError)):
                finite_float(value)

    def test_source_feature_tamper_rejected(self):
        self.features["core"]["companies"][0]["features"][EPS_NAMES[0]]["value"] = "999"
        with self.assertRaisesRegex(Rejected, "FEATURE_PACKAGE_TAMPERED"):
            compute_core(self.features)

    def test_spec_or_pctl_source_tamper_rejected(self):
        wrong = dict(SPEC, minimum_after_filter=1)
        with self.assertRaisesRegex(Rejected, "SPEC_MISMATCH"):
            compute_core(self.features, spec=wrong)
        with patch("src.provider_fundamental_shadow.sha256", return_value="0" * 64):
            with self.assertRaisesRegex(Rejected, "PCTL_CODE_TAMPERED"):
                compute_core(self.features)

    def test_repeat_identity_scores_and_ranks_ignore_execution_times(self):
        core = compute_core(self.features)
        first, second = seal(core, {}), seal(compute_core(self.features), {})
        self.assertEqual(first["content_sha256"], second["content_sha256"])
        self.assertNotEqual(first["execution"]["shadow_generated_at"], second["execution"]["shadow_generated_at"])

    def test_time_future_or_historical_use_rejected(self):
        package = seal(compute_core(self.features), {})
        with self.assertRaisesRegex(Rejected, "TIME_NOT_REACHED"):
            validate(package, self.features, as_of="2026-10-05T23:59:59+00:00")
        with self.assertRaisesRegex(Rejected, "TIME_INVALID"):
            seal(package["core"], {}, validated_at="2099-01-01T00:00:00+00:00")

    def test_time_before_feature_availability_rejected(self):
        core = compute_core(self.features)
        first = next(c for c in core["companies"] if c[SCORE] is not None)
        core["source_feature_times"][first["symbol"]][EPS_NAMES[0]]["feature_available_at"] = "2099-01-01T00:00:00+00:00"
        with self.assertRaisesRegex(Rejected, "BEFORE_FEATURE_AVAILABLE"):
            seal(core, {})

    def test_package_time_and_population_tamper_rejected(self):
        original = seal(compute_core(self.features), {})
        for key in ("time", "population"):
            package = deepcopy(original)
            if key == "time":
                package["execution"]["shadow_available_at"] = "2026-10-05T00:00:00+00:00"
            else:
                package["core"]["populations"]["A_COMPLETE_INPUT"]["members"].pop()
            with self.assertRaisesRegex(Rejected, "PACKAGE_TAMPERED"):
                validate(package, self.features)

    def test_resigned_population_or_score_tamper_still_recomputed(self):
        core = compute_core(self.features)
        core["companies"][0][SCORE] = 999
        with self.assertRaisesRegex(Rejected, "RECOMPUTATION_MISMATCH"):
            validate(seal(core, {}), self.features)

    def test_manifest_artifact_source_raw_tamper_rejected(self):
        output, digest, _package = self.emit()
        for path in (output / "SHADOW_MANIFEST.json", output / "PROVIDER_FUNDAMENTAL_SHADOW_V1.json", self.root / "raw/finmind-2330.json"):
            if not path.exists():
                path = Path(self.features["core"]["inputs"]["eps"][0]["raw_reference"])
            original = path.read_bytes()
            path.write_bytes(original + b" ")
            with self.assertRaises(Rejected):
                consume(output, digest, load_synthetic)
            path.write_bytes(original)

    def test_source_receipt_tamper_rejected(self):
        output, digest, _package = self.emit()
        path = Path(self.features["core"]["inputs"]["eps"][0]["receipt_reference"])
        path.write_bytes(path.read_bytes() + b" ")
        with self.assertRaises(Rejected):
            consume(output, digest, load_synthetic)

    def test_manifest_extra_path_rejected_even_with_new_hash(self):
        output, _digest, _package = self.emit()
        path = output / "SHADOW_MANIFEST.json"
        manifest = json.loads(path.read_bytes())
        manifest["files"]["../escape.json"] = {"bytes": 0, "sha256": "0" * 64}
        path.write_bytes(_canonical(manifest))
        with self.assertRaisesRegex(Rejected, "PATH_INVALID"):
            consume(output, sha256(path.read_bytes()), load_synthetic)

    def test_cold_consumer_separate_process_replays_original_sources(self):
        output, digest, package = self.emit()
        code = "import json,sys; from src.provider_fundamental_shadow import consume; from tests.provider_fundamental_shadow_fixture import load_synthetic; print(json.dumps(consume(sys.argv[1],sys.argv[2],load_synthetic)))"
        run = subprocess.run([sys.executable, "-B", "-c", code, str(output), digest], cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertEqual(json.loads(run.stdout)["content_sha256"], package["content_sha256"])

    def test_execution_binding_mismatch_rejected(self):
        output, digest, _package = self.emit()
        with self.assertRaisesRegex(Rejected, "EXECUTION_CODE_MISMATCH"):
            consume(output, digest, load_synthetic, expected_code_binding={"head_sha": "wrong"})

    def test_source_trust_anchor_required_not_self_hashing_pending_manifest(self):
        path = self.directory / "FINAL_DELIVERY_INDEX.json"
        path.write_bytes(b"{}")
        with self.assertRaisesRegex(Rejected, "INDEX_TAMPERED"):
            source_pin(path, "0" * 64, "1" * 64)
        with self.assertRaisesRegex(Rejected, "INDEX_TAMPERED"):
            load_delivery({"delivery_index": str(path), "delivery_index_sha256": "0" * 64})

    def delivery(self):
        source = self.directory / "delivered-features"
        export_package(self.features, source)
        index = {"base_sha": "0" * 40, "head_sha": "1" * 40,
            "feature_manifest": str(source / "FEATURE_MANIFEST.json"),
            "feature_package": str(source / "PROVIDER_FINANCIAL_FEATURES_V1.json")}
        path = self.directory / "FINAL_DELIVERY_INDEX.json"
        path.write_bytes(_canonical(index))
        inventory = {"files": {str(p): {"sha256": sha256(p.read_bytes()), "bytes": len(p.read_bytes())}
            for p in (path, source / "FEATURE_MANIFEST.json", source / "PROVIDER_FINANCIAL_FEATURES_V1.json")}}
        inv = self.directory / "delivery-artifact-hashes.json"
        inv.write_bytes(_canonical(inventory))
        return source_pin(path, sha256(path.read_bytes()), sha256(inv.read_bytes()))

    def test_trusted_delivery_preserves_old_producer_with_new_reader(self):
        pin = self.delivery()
        with patch("src.provider_fundamental_shadow_inputs.replay_binding", side_effect=lambda b: synthetic_inputs(Path(b["engineering_fixture_root"]), count=b["count"])):
            self.assertEqual(load_delivery(pin), self.features)
        self.assertEqual(pin["producer_code_binding"], self.features["execution"]["code_binding"])

    def test_delivery_inventory_tamper_rejected(self):
        pin = self.delivery()
        path = self.directory / "delivery-artifact-hashes.json"
        path.write_bytes(path.read_bytes() + b" ")
        with self.assertRaisesRegex(Rejected, "INVENTORY_TAMPERED"):
            load_delivery(pin)

    def test_trusted_manifest_hash_mismatch_not_replaced_with_observed_hash(self):
        pin = self.delivery()
        pin["feature_manifest_sha256"] = "0" * 64
        with self.assertRaisesRegex(Rejected, "TRUSTED_MANIFEST_HASH_MISMATCH"):
            load_delivery(pin)

    def test_old_producer_cannot_be_rebound_to_new_execution(self):
        pin = self.delivery()
        pin["producer_code_binding"] = {"base_sha": "2" * 40, "head_sha": "3" * 40}
        with self.assertRaisesRegex(Rejected, "PRODUCER_BINDING_MISMATCH"):
            load_delivery(pin)

    def test_float_collapsed_decimal_ties_follow_existing_pctl(self):
        def change(data):
            for row in data["revenue"]:
                if row["revenue_yoy_status"] == "VALID_NUMERIC":
                    row["revenue_yoy"] = "10000000000000000.001" if row["symbol"] == "1000" else "10000000000000000.002"
        self.feature_change(change)
        core = compute_core(self.features)
        self.assertEqual(core["companies"][0]["components"][REVENUE_NAME]["percentile"], 50)
        self.assertNotEqual(core["companies"][0]["features"][REVENUE_NAME]["value"], core["companies"][1]["features"][REVENUE_NAME]["value"])

    def test_resigned_time_tamper_rejected_by_rederived_envelope(self):
        package = seal(compute_core(self.features), {})
        package["execution"]["shadow_available_at"] = "2026-10-05T00:00:00+00:00"
        package["package_sha256"] = hash_object({k: v for k, v in package.items() if k != "package_sha256"})
        with self.assertRaisesRegex(Rejected, "TIME_ENVELOPE_MISMATCH"):
            validate(package, self.features)

    def test_sidecar_tamper_rejected_even_when_file_manifest_resigned(self):
        output, _digest, _package = self.emit()
        sidecar = output / "shadow-populations.json"
        other = json.loads(sidecar.read_bytes())
        other["populations"]["A_COMPLETE_INPUT"]["count"] = 999
        body = _canonical(other)
        sidecar.write_bytes(body)
        manifest_path = output / "SHADOW_MANIFEST.json"
        manifest = json.loads(manifest_path.read_bytes())
        manifest["files"][sidecar.name] = {"bytes": len(body), "sha256": sha256(body)}
        manifest_path.write_bytes(_canonical(manifest))
        with self.assertRaisesRegex(Rejected, "POPULATION_SIDECAR_MISMATCH"):
            consume(output, sha256(manifest_path.read_bytes()), load_synthetic)

    def test_new_output_cannot_overwrite_or_enter_protected_source(self):
        package = seal(compute_core(self.features), {})
        with self.assertRaisesRegex(Rejected, "NEW_EXTERNAL"):
            export(package, self.directory)
        with self.assertRaisesRegex(Rejected, "PROTECTED_OUTPUT"):
            export(package, self.directory / "Portfolio" / "shadow")


class NonInterferenceTests(unittest.TestCase):
    def test_formal_acceptance_absent_present_updated_corrupt_shadow_identical(self):
        from scripts import build_live_source_bundle as live
        formal = {"1000": {"Fundamental": "EXISTING_ENGINEERING_SENTINEL_NOT_NEW_SCORE"}}
        outcomes = []
        with tempfile.TemporaryDirectory(prefix="shadow-formal-") as root:
            path = Path(root) / "PROVIDER_FUNDAMENTAL_SHADOW_V1.json"
            for body in (None, b'{"shadow":1}', b'{"shadow":999}', b"corrupt-not-json"):
                if body is not None:
                    path.write_bytes(body)
                with patch.dict(os.environ, {"RATE_PROVIDER_FUNDAMENTAL_SHADOW_ROOT": root}), \
                     patch.object(live, "_accepted_fundamental_history", return_value=deepcopy(formal)), \
                     patch.object(live, "calculate_fundamental", side_effect=AssertionError("FORMAL_SCORE_FORBIDDEN")) as scoring, \
                     patch.object(live, "_write", side_effect=AssertionError("PRODUCTION_WRITE_FORBIDDEN")):
                    outcomes.append(live._fundamental_history(["1000"], as_of_date="2026-10-05"))
                    self.assertFalse(scoring.called)
        self.assertEqual(outcomes, [formal] * 4)

    def test_missing_formal_eps_gate_not_filled_by_shadow_any_state(self):
        from scripts import build_live_source_bundle as live
        outcomes = []
        with tempfile.TemporaryDirectory(prefix="shadow-missing-formal-") as root:
            path = Path(root) / "PROVIDER_FUNDAMENTAL_SHADOW_V1.json"
            for body in (None, b'{"shadow":1}', b'{"shadow":999}', b"corrupt-not-json"):
                if body is not None:
                    path.write_bytes(body)
                with patch.dict(os.environ, {"RATE_PROVIDER_FUNDAMENTAL_SHADOW_ROOT": root}), \
                     patch.object(live, "_accepted_fundamental_history", return_value=None), \
                     patch.object(live, "FundamentalHistoryStoreV2") as store, \
                     patch.object(live, "MOPSHistoricalFundamentalAdapter") as adapter, \
                     patch.object(live, "calculate_fundamental", side_effect=AssertionError("FORMAL_SCORE_FORBIDDEN")) as scoring:
                    store.return_value.select_asof.return_value = {"1000": {"revenue": {}, "eps": {}}}
                    adapter.return_value.fetch_eps_period.side_effect = RuntimeError("SYNTHETIC_MISSING_FORMAL_EPS")
                    with self.assertRaisesRegex(RuntimeError, "MISSING_FORMAL_EPS") as result:
                        live._fundamental_history(["1000"], as_of_date="2026-10-05")
                    outcomes.append(str(result.exception))
                    self.assertFalse(scoring.called)
                    self.assertFalse(store.return_value.upsert.called)
        self.assertEqual(len(set(outcomes)), 1)
