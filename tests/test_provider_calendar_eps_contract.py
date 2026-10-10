"""Synthetic engineering only; real 1978-issuer evidence is never committed."""
from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path
from unittest.mock import patch
import unittest

from src.eps_duration_facts.model import Rejected
from src.eps_duration_facts.raw import sha256
from src.provider_calendar_eps_contract import definition, validate_material
from src.provider_eps_candidate import WINDOW, map_basic_eps_label
from tests import test_finmind_formal_qualification as fixture


class CalendarEPSContractTests(unittest.TestCase):
    def setUp(self):
        fixture.FinMindQualificationTests.setUp(self)

    def run_contract(self):
        return validate_material(self.material, self.now)

    def reject(self, reason):
        with self.assertRaisesRegex(Rejected, reason):
            self.run_contract()

    def rewrite_first_raw(self, key, value):
        row = self.material["eps"][0]
        raw_path = Path(row["raw_reference"])
        receipt_path = Path(row["receipt_reference"])
        payload = json.loads(raw_path.read_bytes())
        payload["data"][row["raw_row_index_zero_based"]][key] = value
        raw = json.dumps(payload).encode()
        raw_path.write_bytes(raw)
        receipt = json.loads(receipt_path.read_bytes())
        receipt.update(response_body_sha256=sha256(raw), bytes=len(raw), content_length=str(len(raw)))
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
        for record in self.material["eps"]:
            if record["raw_reference"] == str(raw_path):
                record.update(raw_sha256=sha256(raw), raw_bytes=len(raw), receipt_sha256=sha256(receipt_path.read_bytes()))
        return row

    def test_contract_identity_and_scope(self):
        contract = definition()
        self.assertEqual(contract["contract_id"], "RATE-PROVIDER-CALENDAR-QUARTER-EPS-V1")
        self.assertEqual(contract["metric"], "PROVIDER_CALENDAR_QUARTER_BASIC_EPS")
        self.assertEqual(contract["scope"], "PROSPECTIVE_SEMANTIC_CONTRACT")

    def test_exact_mapping_all_eight(self):
        actual = {r["provider_date"]: r["analysis_quarter"] for c in self.run_contract()["core"]["companies"] for r in c["quarters"]}
        expected = {"2024-09-30": "2024Q3", "2024-12-31": "2024Q4", "2025-03-31": "2025Q1",
                    "2025-06-30": "2025Q2", "2025-09-30": "2025Q3", "2025-12-31": "2025Q4",
                    "2026-03-31": "2026Q1", "2026-06-30": "2026Q2"}
        self.assertEqual(actual, expected)
        self.assertEqual(definition()["period_mapping"], expected)

    def test_non_quarter_end_rejected(self):
        for date in ("2025-12-30", "2025-12-31T00:00:00", "2025/12/31"):
            with self.subTest(date=date):
                self.material["eps"][0]["provider_date"] = date
                self.reject("AMBIGUOUS_PROVIDER_PERIOD")

    def test_older_quarter_not_substituted(self):
        self.material["eps"][0]["analysis_quarter"] = "2024Q2"
        self.reject("OLDER_OR_OUTSIDE_QUARTER_SUBSTITUTION")

    def test_wrong_symbol(self):
        self.material["eps"][0]["symbol"] = "OTHER"
        self.reject("WRONG_SYMBOL")

    def test_wrong_market(self):
        self.material["eps"][0]["market"] = "TPEX"
        self.reject("WRONG_MARKET")

    def test_wrong_eps_type(self):
        self.material["eps"][0]["provider_type"] = "EPS_OTHER"
        self.reject("PROVIDER_EPS_TYPE_MISMATCH")

    def test_fuzzy_and_diluted_label_rejected(self):
        for label in ("基本每股盈餘 ", "基本每股盈餘(元)", "稀釋每股盈餘", "基本每股盈餘（美元）"):
            with self.subTest(label=label):
                self.material["eps"][0]["provider_origin_name"] = label
                self.reject("PROVIDER_BASIC_LABEL_MISMATCH")

    def test_second_exact_label_raw_retained(self):
        label = "基本每股盈餘（元）"
        row = self.rewrite_first_raw("origin_name", label)
        row.update(provider_origin_name=label, **map_basic_eps_label("EPS", label))
        result = self.run_contract()["core"]
        record = next(r for c in result["companies"] for r in c["quarters"] if r["json_locator"] == row["json_locator"] and r["receipt_reference"] == row["receipt_reference"])
        self.assertEqual(record["provider_origin_name"], label)

    def test_nonfinite_rejected(self):
        for value in ("NaN", "Infinity", "-Infinity"):
            with self.subTest(value=value):
                self.material["eps"][0]["provider_value"] = value
                self.reject("NONFINITE_EPS")

    def test_bool_rejected(self):
        self.material["eps"][0]["provider_value"] = True
        self.reject("INVALID_EPS_NUMERIC")

    def test_duplicate_quarter(self):
        self.material["eps"].append(deepcopy(self.material["eps"][0]))
        self.reject("DUPLICATE_QUARTER")

    def test_conflicting_quarter(self):
        row = deepcopy(self.material["eps"][0])
        row["provider_value"] = "9876"
        self.material["eps"].append(row)
        self.reject("CONFLICTING_QUARTER")

    def test_raw_tamper(self):
        Path(self.material["eps"][0]["raw_reference"]).write_bytes(b"{}")
        self.reject("FEATURE_SOURCE_FILE_TAMPERED")

    def test_receipt_tamper(self):
        Path(self.material["eps"][0]["receipt_reference"]).write_bytes(b"{}")
        self.reject("RECEIPT_TAMPERED")

    def test_locator_tamper(self):
        self.material["eps"][0]["json_locator"] = "$.data[999]"
        self.reject("RAW_LOCATOR_INVALID")

    def test_pit_and_unknown_version_fields_unchanged(self):
        result = self.run_contract()["core"]
        self.assertEqual(result["historical_pit_status"], "UNPROVEN")
        self.assertEqual(result["formal_period_identity"], "NOT_PROVEN")
        for c in result["companies"]:
            for row in c["quarters"]:
                self.assertIsNone(row["public_time"])
                self.assertIsNone(row["revision_id"])
                self.assertIsNone(row["period_qualification"]["fiscal_quarter"])

    def test_retrieval_time_not_publication(self):
        row = self.material["eps"][0]
        row["public_time"] = row["acquired_observed_at"]
        self.reject("UNSUPPORTED_PUBLICATION_OR_REVISION_CLAIM")

    def test_provider_date_not_publication(self):
        row = self.material["eps"][0]
        row["public_time"] = row["provider_date"] + "T00:00:00+00:00"
        self.reject("UNSUPPORTED_PUBLICATION_OR_REVISION_CLAIM")

    def test_official_ttm_not_promoted(self):
        self.assertEqual(definition()["future_sum_name_only"], "PROVIDER_DEFINED_UNADJUSTED_QUARTER_SUM")
        self.assertFalse(definition()["annual_subtraction_allowed"])
        self.material["eps"][0]["official_ttm"] = True
        self.reject("CALENDAR_OFFICIAL_PROMOTION_FORBIDDEN")

    def test_no_fiscal_inference(self):
        self.material["eps"][0]["fiscal_year"] = 2025
        self.reject("CALENDAR_FISCAL_INFERENCE_FORBIDDEN")

    def test_incomplete_issuer_keeps_valid_rows(self):
        row = self.material["eps"].pop()
        self.material["gaps"] = [{"symbol": row["symbol"], "market": row["market"],
            "analysis_quarter": row["analysis_quarter"], "classification": "NO_PROVIDER_ROWS_FOR_QUARTER"}]
        result = self.run_contract()["core"]["summary"]
        self.assertEqual((result["companies"], result["eps_complete_companies"], result["incomplete_issuer_valid_rows_retained"]), (3, 2, 7))

    def test_zero_eight_issuer_not_removed(self):
        self.material["eps"] = [r for r in self.material["eps"] if r["symbol"] != "6488"]
        self.material["gaps"] = [{"symbol": "6488", "market": "TPEX", "analysis_quarter": q,
            "classification": "FINANCIAL_ROWS_PRESENT_NO_TYPE_EPS"} for q in WINDOW]
        result = self.run_contract()["core"]
        company = next(c for c in result["companies"] if c["symbol"] == "6488")
        self.assertEqual((len(result["companies"]), company["valid_quarters"], len(company["gaps"])), (3, 0, 8))

    def test_missing_without_gap_rejected(self):
        self.material["eps"].pop()
        self.reject("GAP_OR_UNIVERSE_MISMATCH")

    def test_unordered_inputs_same_result(self):
        first = self.run_contract()
        self.material["eps"].reverse()
        self.assertEqual(first["content_sha256"], self.run_contract()["content_sha256"])
        self.assertEqual([r["analysis_quarter"] for r in first["core"]["companies"][0]["quarters"]], list(reversed(WINDOW)))

    def test_repeat_identity_validation_time_separate(self):
        first = self.run_contract()
        self.now = "2099-02-01T00:00:00+00:00"
        second = self.run_contract()
        self.assertEqual(first["content_sha256"], second["content_sha256"])
        self.assertNotEqual(first["validated_at"], second["validated_at"])

    def test_decimal_precision_negative_and_zero(self):
        values = [r["provider_value"] for r in self.material["eps"]]
        self.assertTrue(any(Decimal(v) == 0 for v in values))
        self.assertTrue(any(Decimal(v) < 0 for v in values))
        precision = "-0.123456789012345678901234567890"
        row = self.rewrite_first_raw("value", precision)
        row["provider_value"] = precision
        actual = [r["provider_value"] for c in self.run_contract()["core"]["companies"] for r in c["quarters"]]
        self.assertIn(precision, actual)

    def test_contract_document_tamper(self):
        path = self.root / "contract-tampered.json"
        value = definition()
        value["production_eligible"] = True
        path.write_text(json.dumps(value), encoding="utf-8")
        with patch("src.provider_calendar_eps_contract.CONTRACT_PATH", path):
            self.reject("CALENDAR_CONTRACT_TAMPERED")

    def test_no_activation_or_warmup_policy_change(self):
        before = deepcopy(self.material)
        bytes_before = {str(p): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        core = self.run_contract()["core"]
        self.assertFalse(core["production_eligible"])
        self.assertFalse(core["fallback_allowed"])
        self.assertEqual(core["warmup_completeness_policy"], "UNCHANGED")
        self.assertEqual(core["formal_warmup_gate"], "FUNDAMENTAL_EPS_PERIOD_IDENTITY_UNPROVEN")
        self.assertEqual(core["formal_provider_activation"], "NOT_AUTHORIZED")
        self.assertEqual(self.material, before)
        self.assertEqual(bytes_before, {str(p): p.read_bytes() for p in self.root.rglob("*") if p.is_file()})

    def test_provider_dataset_and_universe_binding(self):
        for field, bad in (("source", "OtherProvider"), ("dataset", "OtherDataset")):
            with self.subTest(field=field):
                original = self.material["eps"][0][field]
                self.material["eps"][0][field] = bad
                self.reject("SOURCE_POLICY_MISMATCH")
                self.material["eps"][0][field] = original
        self.material["material_class"] = "LOCAL_SAVED_FINMIND_AND_OFFICIAL_REVENUE_REPLAY"
        self.reject("CALENDAR_UNIVERSE_BINDING_INVALID")


if __name__ == "__main__":
    unittest.main()
