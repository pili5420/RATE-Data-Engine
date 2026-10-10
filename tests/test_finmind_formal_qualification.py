"""Synthetic only. No real provider response is published with these tests."""
from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path
import tempfile
import unittest

from src.eps_duration_facts.model import Rejected
from src.finmind_formal_qualification import (
    exact_period, future_observation_allowed, qualification_outcome, qualify_material, verify_gap_evidence,
)
from src.provider_eps_candidate import WINDOW, read_provider_response
from src.provider_financial_feature_inputs import load_closeout
from tests.provider_eps_engineering_fixture import make_fixture


class FinMindQualificationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = make_fixture(Path(self.tmp.name))
        self.material = {"material_class": "SYNTHETIC_ONLY", "universe": {"stocks": [
            {"symbol": "2330", "market": "TWSE"}, {"symbol": "1340", "market": "TWSE"},
            {"symbol": "6488", "market": "TPEX"}]}, "eps": [], "gaps": [],
            "source_binding": {"material_class": "SYNTHETIC_ONLY"}}
        for path in sorted((self.root / "receipts").glob("*.json")):
            replay = read_provider_response(path)
            self.assertEqual(replay["issues"], [])
            for row in replay["rows"]:
                row["market"] = "TPEX" if row["symbol"] == "6488" else "TWSE"
                self.material["eps"].append(row)
        self.now = "2099-01-01T00:00:00+00:00"

    def run_material(self, value=None):
        return qualify_material(self.material if value is None else value, self.now)

    def reject(self, reason):
        with self.assertRaisesRegex(Rejected, reason):
            self.run_material()

    def test_valid_eight_consecutive_calendar_quarters(self):
        s = self.run_material()["core"]["summary"]
        self.assertEqual((s["companies"], s["eps_complete_companies"], s["valid_company_quarters"]), (3, 3, 24))

    def test_date_shape_not_formal_fiscal_proof(self):
        c = self.run_material()["core"]
        self.assertEqual(c["provider_calendar_mapping"], "PASS")
        self.assertEqual(c["FORMAL_PERIOD_IDENTITY"], "NOT_PROVEN")
        self.assertEqual(c["FINMIND_FORMAL_EPS_PROVIDER"], "NOT_QUALIFIED")

    def test_duplicate_quarter(self):
        self.material["eps"].append(deepcopy(self.material["eps"][0]))
        self.reject("DUPLICATE_QUARTER")

    def test_conflicting_quarter(self):
        row = deepcopy(self.material["eps"][0]); row["provider_value"] = "123456"
        self.material["eps"].append(row)
        self.reject("CONFLICTING_QUARTER")

    def test_missing_quarter_without_gap_rejected(self):
        self.material["eps"].pop()
        self.reject("GAP_OR_UNIVERSE_MISMATCH")

    def test_incomplete_issuer_preserved(self):
        row = self.material["eps"].pop()
        self.material["gaps"].append({"symbol": row["symbol"], "market": row["market"],
            "analysis_quarter": row["analysis_quarter"], "classification": "NO_PROVIDER_ROWS_FOR_QUARTER"})
        s = self.run_material()["core"]["summary"]
        self.assertEqual((s["companies"], s["eps_complete_companies"], s["incomplete_issuer_valid_rows_retained"]), (3, 2, 7))

    def test_ambiguous_period(self):
        self.material["eps"][0]["provider_date"] = "2024-12-30"
        self.reject("AMBIGUOUS_PROVIDER_PERIOD")

    def test_wrong_symbol(self):
        self.material["eps"][0]["symbol"] = "OTHER"
        self.reject("WRONG_SYMBOL")

    def test_wrong_market(self):
        self.material["eps"][0]["market"] = "TPEX"
        self.reject("WRONG_MARKET")

    def test_wrong_basic_label(self):
        self.material["eps"][0]["provider_origin_name"] = "DILUTED"
        self.reject("PROVIDER_BASIC_LABEL_MISMATCH")

    def test_fuzzy_label_rejected(self):
        self.material["eps"][0]["provider_origin_name"] += " "
        self.reject("PROVIDER_BASIC_LABEL_MISMATCH")

    def test_non_eps_type_rejected(self):
        self.material["eps"][0]["provider_type"] = "EPS2"
        self.reject("PROVIDER_EPS_TYPE_MISMATCH")

    def test_nonfinite_eps(self):
        for value in ("NaN", "Infinity", "-Infinity"):
            with self.subTest(value=value):
                self.material["eps"][0]["provider_value"] = value
                self.reject("NONFINITE_EPS")

    def test_bool_not_numeric(self):
        self.material["eps"][0]["provider_value"] = True
        self.reject("INVALID_EPS_NUMERIC")

    def test_raw_tamper(self):
        path = Path(self.material["eps"][0]["raw_reference"])
        path.write_bytes(path.read_bytes() + b" ")
        self.reject("FEATURE_SOURCE_FILE_TAMPERED")

    def test_receipt_tamper(self):
        path = Path(self.material["eps"][0]["receipt_reference"])
        path.write_bytes(path.read_bytes() + b" ")
        self.reject("RECEIPT_TAMPERED")

    def test_value_not_copied_without_raw_verification(self):
        self.material["eps"][0]["provider_value"] = "999"
        self.reject("RAW_ROW_IDENTITY_MISMATCH")

    def test_locator_tamper(self):
        self.material["eps"][0]["json_locator"] = "$.data[999]"
        self.reject("RAW_LOCATOR_INVALID")

    def test_older_quarter_substitution(self):
        self.material["eps"][0]["analysis_quarter"] = "2024Q2"
        self.reject("OLDER_OR_OUTSIDE_QUARTER_SUBSTITUTION")

    def test_wrong_fiscal_period_cannot_be_inferred(self):
        with self.assertRaisesRegex(Rejected, "AMBIGUOUS_PROVIDER_PERIOD"):
            exact_period("2026-06-30", "2026Q1")

    def test_retrieval_time_not_publication(self):
        row = self.material["eps"][0]; row["public_time"] = row["acquired_observed_at"]
        self.reject("UNSUPPORTED_PUBLICATION_OR_REVISION_CLAIM")

    def test_provider_date_not_publication(self):
        row = self.material["eps"][0]; row["public_time"] = row["provider_date"] + "T00:00:00+00:00"
        self.reject("UNSUPPORTED_PUBLICATION_OR_REVISION_CLAIM")

    def test_revision_ambiguity(self):
        self.material["eps"][0]["revision_id"] = "latest"
        self.reject("UNSUPPORTED_PUBLICATION_OR_REVISION_CLAIM")

    def test_historical_claim_rejected(self):
        self.material["eps"][0]["historical_pit_status"] = "PASS"
        self.reject("UNSUPPORTED_HISTORICAL_CLAIM")

    def test_prospective_historical_separation_decision_table(self):
        self.assertEqual(qualification_outcome(True, False), "PROSPECTIVE_QUALIFIED")
        self.assertEqual(qualification_outcome(True, True), "FULLY_QUALIFIED")
        self.assertEqual(qualification_outcome(False, False), "NOT_QUALIFIED")
        self.assertEqual(qualification_outcome(False, True), "NOT_QUALIFIED")

    def test_no_automatic_activation(self):
        core = self.run_material()["core"]
        self.assertFalse(core["production_eligible"])
        self.assertEqual(core["formal_warmup_gate"], "FUNDAMENTAL_EPS_PERIOD_IDENTITY_UNPROVEN")
        self.assertFalse(core["fallback_allowed"])

    def test_future_observation_rejected(self):
        self.material["eps"][0]["acquired_observed_at"] = "2100-01-01T00:00:00+00:00"
        self.reject("FUTURE_OR_SUBSTITUTED_OBSERVATION")

    def test_pre_activation_observation_not_grandfathered(self):
        self.assertFalse(future_observation_allowed("2026-10-07T00:00:00+00:00", "2026-10-10T00:00:00+00:00", True))

    def test_observation_after_activation_necessary_not_sufficient(self):
        self.assertTrue(future_observation_allowed("2026-10-11T00:00:00+00:00", "2026-10-10T00:00:00+00:00", True))
        self.assertFalse(future_observation_allowed("2026-10-11T00:00:00+00:00", None, True))
        self.assertFalse(future_observation_allowed("2026-10-11T00:00:00+00:00", "2026-10-10T00:00:00+00:00", False))

    def test_reproducible_core_separate_verification_time(self):
        first = self.run_material()
        self.now = "2099-02-01T00:00:00+00:00"
        second = self.run_material()
        self.assertEqual(first["content_sha256"], second["content_sha256"])
        self.assertNotEqual(first["validated_at"], second["validated_at"])

    def test_unordered_inputs_same_quarter_sorting(self):
        first = self.run_material()
        self.material["eps"].reverse()
        self.assertEqual(first["content_sha256"], self.run_material()["content_sha256"])
        self.assertEqual([r["analysis_quarter"] for r in first["core"]["companies"][0]["quarters"]], list(reversed(WINDOW)))

    def test_decimal_zero_negative_preserved(self):
        first = self.run_material()
        original = {(r["symbol"], r["analysis_quarter"]): r["provider_value"] for r in self.material["eps"]}
        values = [r for c in first["core"]["companies"] for r in c["quarters"]]
        self.assertEqual(original, {(r["symbol"], r["analysis_quarter"]): r["provider_value"] for r in values})
        self.assertTrue(any(Decimal(r["provider_value"]) < 0 for r in values))
        self.assertTrue(any(Decimal(r["provider_value"]) == 0 for r in values))

    def test_inputs_and_bytes_unchanged(self):
        before = {str(p): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        material = deepcopy(self.material)
        self.run_material()
        self.assertEqual(material, self.material)
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.root.rglob("*") if p.is_file()})

    def test_missing_all_eight_remains_in_universe(self):
        symbol = "6488"
        self.material["eps"] = [r for r in self.material["eps"] if r["symbol"] != symbol]
        self.material["gaps"] = [{"symbol": symbol, "market": "TPEX", "analysis_quarter": q,
            "classification": "FINANCIAL_ROWS_PRESENT_NO_TYPE_EPS"} for q in WINDOW]
        core = self.run_material()["core"]
        company = next(c for c in core["companies"] if c["symbol"] == symbol)
        self.assertEqual((len(core["companies"]), company["status"], company["valid_quarters"]), (3, "NO_EPS", 0))

    def test_contract_and_official_owner_not_mutated(self):
        root = Path(__file__).resolve().parents[1]
        paths = [root / "src/sources/fundamental_history.py", root / "src/feature_math.py"]
        before = [p.read_bytes() for p in paths]
        self.run_material()
        self.assertEqual(before, [p.read_bytes() for p in paths])

    def test_unknown_fiscal_claim_not_manufactured(self):
        first = self.run_material()
        for company in first["core"]["companies"]:
            for row in company["quarters"]:
                self.assertIsNone(row["period_qualification"]["fiscal_year"])
                self.assertIsNone(row["period_qualification"]["fiscal_quarter"])
                self.assertIsNone(row["public_time"])
                self.assertIsNone(row["revision_id"])

    def gap_fixture(self):
        row = self.material["eps"][0]
        return {"symbol": row["symbol"], "market": row["market"], "analysis_quarter": "2024Q3",
            "classification": "NO_PROVIDER_ROWS_FOR_QUARTER", "receipt_evidence": [{
                "receipt_reference": row["receipt_reference"], "receipt_sha256": row["receipt_sha256"],
                "raw_reference": row["raw_reference"], "raw_sha256": row["raw_sha256"], "raw_bytes": row["raw_bytes"]}]}

    def test_gap_window_not_covered_rejected(self):
        with self.assertRaisesRegex(Rejected, "GAP_QUERY_DOES_NOT_COVER_POSITION"):
            verify_gap_evidence(self.gap_fixture())

    def test_gap_existing_eps_cannot_claim_no_rows(self):
        gap = self.gap_fixture(); gap["analysis_quarter"] = self.material["eps"][0]["analysis_quarter"]
        with self.assertRaisesRegex(Rejected, "GAP_CLASSIFICATION_REPLAY_MISMATCH"):
            verify_gap_evidence(gap)

    def test_gap_raw_tamper(self):
        gap = self.gap_fixture()
        Path(gap["receipt_evidence"][0]["raw_reference"]).write_bytes(b"{}")
        with self.assertRaisesRegex(Rejected, "FEATURE_SOURCE_FILE_TAMPERED"):
            verify_gap_evidence(gap)

    def test_gap_receipt_tamper(self):
        gap = self.gap_fixture()
        Path(gap["receipt_evidence"][0]["receipt_reference"]).write_bytes(b"{}")
        with self.assertRaisesRegex(Rejected, "GAP_RECEIPT_TAMPERED"):
            verify_gap_evidence(gap)

    def test_untrusted_manifest_self_hash_not_accepted(self):
        path = self.root / "untrusted-manifest.json"
        path.write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(Rejected, "FEATURE_CLOSEOUT_MANIFEST_TAMPERED"):
            load_closeout(path, "0" * 64)

    def test_decimal_precision_no_float_conversion(self):
        from src.eps_duration_facts.raw import sha256
        row = self.material["eps"][0]
        raw_path, receipt_path = Path(row["raw_reference"]), Path(row["receipt_reference"])
        precision = "-0.123456789012345678901234567890"
        payload = json.loads(raw_path.read_text(encoding="utf-8"))
        payload["data"][row["raw_row_index_zero_based"]]["value"] = precision
        raw = json.dumps(payload).encode("utf-8")
        raw_path.write_bytes(raw)
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        receipt.update(response_body_sha256=sha256(raw), bytes=len(raw), content_length=str(len(raw)))
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
        for record in self.material["eps"]:
            if record["raw_reference"] == str(raw_path):
                record.update(raw_sha256=sha256(raw), raw_bytes=len(raw), receipt_sha256=sha256(receipt_path.read_bytes()))
        row["provider_value"] = precision
        actual = [r["provider_value"] for c in self.run_material()["core"]["companies"] for r in c["quarters"]]
        self.assertIn(precision, actual)


if __name__ == "__main__":
    unittest.main()
