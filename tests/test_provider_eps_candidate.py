"""Engineering fixtures only: no API, official replay or Production scoring."""
from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path
import tempfile
import unittest

from src.eps_duration_facts.model import Rejected
from src.eps_duration_facts.raw import sha256
from src.provider_eps_candidate import (BOUNDARY, DESCENDING, ENGINEERING, KIND, SCHEMA, _canonical,
                                        build_candidate, consume_candidate)
from tests.provider_eps_engineering_fixture import make_fixture, write

BINDING = {"base_sha": "0" * 40, "head_sha": "1" * 40, "engineering_binding_only": True}


class ProviderCandidateEngineeringTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="provider-eps-engineering-")
        self.addCleanup(self.temporary.cleanup)
        self.root = make_fixture(Path(self.temporary.name))

    def inputs(self):
        return json.loads((self.root / "analysis_input.json").read_text())

    def modify_inputs(self, callback):
        data = self.inputs()
        callback(data)
        write(self.root / "analysis_input.json", data)

    def build(self):
        return build_candidate(self.root, BINDING)

    def assert_rejected(self, reason):
        with self.assertRaisesRegex(Rejected, reason):
            self.build()

    def test_24_rows_offline_and_unknowns_preserved(self):
        candidate = self.build()
        self.assertEqual(candidate["material_class"], ENGINEERING)
        self.assertEqual(candidate["artifact_kind"], KIND)
        self.assertEqual(candidate["schema_version"], SCHEMA)
        for key, value in BOUNDARY.items():
            self.assertEqual(candidate[key], value)
        rows = [r for c in candidate["companies"] for r in c["quarters"]]
        self.assertEqual(len(rows), 24)
        self.assertTrue(all(r["filing_id"] is r["revision_id"] is r["public_time"] is None for r in rows))
        self.assertEqual(sum(r["material_origin"] == "ORIGINAL_DIRECT_USE_17" for r in rows), 17)
        self.assertEqual(sum(r["material_origin"] == "NEW_FIXED_GAP_REQUEST" for r in rows), 7)
        self.assertEqual(len(consume_candidate(candidate)["companies"]), 3)

    def test_shuffle_and_reverse_cannot_swap_latest_and_earlier_quarters(self):
        baseline = self.build()
        self.modify_inputs(lambda d: d["records"].reverse())
        shuffled = self.build()
        self.assertEqual(baseline["artifact_id"], shuffled["artifact_id"])
        self.assertEqual(consume_candidate(baseline), consume_candidate(shuffled))
        for company in shuffled["companies"]:
            self.assertEqual([r["analysis_quarter"] for r in company["quarters"]], list(DESCENDING))
            self.assertEqual([r["analysis_quarter"] for r in company["quarters"][:4]], ["2026Q2", "2026Q1", "2025Q4", "2025Q3"])
            self.assertEqual([r["analysis_quarter"] for r in company["quarters"][4:]], ["2025Q2", "2025Q1", "2024Q4", "2024Q3"])

    def test_zero_negative_and_q4_provider_values_preserved(self):
        candidate = self.build()
        values = {(r["symbol"], r["analysis_quarter"]): r["provider_value"] for c in candidate["companies"] for r in c["quarters"]}
        self.assertEqual(values[("2330", "2024Q3")], "0")
        self.assertEqual(values[("6488", "2026Q2")], "-1")
        for r in [r for c in candidate["companies"] for r in c["quarters"] if r["analysis_quarter"].endswith("Q4")]:
            self.assertEqual(r["q4_raw_or_derived_classification"], "UNPROVEN")

    def test_missing_quarter_rejected_without_backfill(self):
        self.modify_inputs(lambda d: d["records"].pop())
        self.assert_rejected("MISSING_QUARTERS")

    def test_duplicate_key_rejected(self):
        self.modify_inputs(lambda d: d["records"].append(deepcopy(d["records"][0])))
        self.assert_rejected("DUPLICATE_KEY")

    def test_conflicting_value_rejected(self):
        def change(d):
            duplicate = deepcopy(d["records"][0])
            duplicate["provider_value"] = "999"
            d["records"].append(duplicate)
        self.modify_inputs(change)
        self.assert_rejected("CONFLICTING_VALUE")

    def test_nonfinite_values_rejected(self):
        for value in ("NaN", "Infinity", "-Infinity"):
            with self.subTest(value=value):
                self.modify_inputs(lambda d: d["records"][0].update(provider_value=value))
                self.assert_rejected("NONFINITE_EPS")

    def test_tampered_raw_rejected(self):
        raw = Path(self.inputs()["records"][0]["raw_path"])
        raw.write_bytes(raw.read_bytes() + b" ")
        self.assert_rejected("BODY_LENGTH_MISMATCH|CONTENT_LENGTH_MISMATCH|BODY_HASH_MISMATCH")

    def test_tampered_same_length_raw_rejected(self):
        raw = Path(self.inputs()["records"][0]["raw_path"])
        body = raw.read_bytes().replace(b'"msg": "ENGINEERING_FIXTURE"', b'"msg": "ENGINEERING_TAMPER!"')
        self.assertEqual(len(body), raw.stat().st_size)
        raw.write_bytes(body)
        self.assert_rejected("BODY_HASH_MISMATCH")

    def test_tampered_receipt_and_time_rejected(self):
        p = Path(self.inputs()["records"][0]["receipt_reference"])
        r = json.loads(p.read_text())
        r["received_at"] = "2026-10-07T12:28:00.1+00:00"
        write(p, r)
        self.assert_rejected("RECEIPT_HASH_BINDING_MISMATCH")

    def test_manifest_cannot_backdate_complete_dataset(self):
        p = self.root / "merged_manifest.json"
        manifest = json.loads(p.read_text())
        manifest["generated_at"] = "2026-10-07T12:00:00+00:00"
        write(p, manifest)
        self.modify_inputs(lambda d: d.update(metadata=manifest))
        self.assert_rejected("INPUT_COMPLETENESS_TIME_BACKDATED")

    def test_each_acquisition_time_matches_own_source(self):
        original = {(r["symbol"], r["analysis_quarter"]): r["observed_at"] for r in self.inputs()["records"]}
        candidate = self.build()
        times = [r["acquired_observed_at"] for c in candidate["companies"] for r in c["quarters"]]
        for company in candidate["companies"]:
            for r in company["quarters"]:
                self.assertEqual(r["acquired_observed_at"], original[(r["symbol"], r["analysis_quarter"])])
                self.assertNotEqual(r["verified_observed_at"], r["acquired_observed_at"])
        self.assertEqual(candidate["dataset_complete_observed_at"], max(times))

    def test_unknown_versions_cannot_be_fabricated(self):
        self.modify_inputs(lambda d: d["records"][0].update(revision_id="latest"))
        self.assert_rejected("UNSUPPORTED_VERSION_CLAIM")

    def test_row_value_locator_date_and_policy_tamper_rejected(self):
        for mutation, reason in (({"eps": "1000"}, "PROVIDER_VALUE_MISMATCH"),
                                 ({"json_locator": "$.data[999]"}, "JSON_LOCATOR_MISMATCH"),
                                 ({"analysis_quarter": "2025Q4"}, "DATE_QUARTER_MAPPING_MISMATCH"),
                                 ({"provider_reply_required": True}, "SOURCE_POLICY_MISMATCH")):
            with self.subTest(mutation=mutation):
                original = self.inputs()
                self.modify_inputs(lambda d: d["records"][0].update(mutation))
                self.assert_rejected(reason)
                write(self.root / "analysis_input.json", original)

    def test_matrix_mismatch_rejected(self):
        p = self.root / "quarter_matrix.json"
        matrix = json.loads(p.read_text())
        matrix["cells"][0]["eps"] = "1000"
        write(p, matrix)
        self.assert_rejected("MATRIX_VALUE_MISMATCH")

    def test_candidate_tamper_rejected_by_consumer(self):
        candidate = self.build()
        candidate["companies"][0]["quarters"][0]["provider_value"] = "999"
        with self.assertRaisesRegex(Rejected, "CANDIDATE_PAYLOAD_TAMPERED"):
            consume_candidate(candidate)

    def test_consumer_rejects_reordered_rows_even_with_new_digest(self):
        candidate = self.build()
        candidate["companies"][0]["quarters"].reverse()
        candidate["candidate_payload_sha256"] = sha256(_canonical({k: v for k, v in candidate.items() if k != "candidate_payload_sha256"}))
        with self.assertRaisesRegex(Rejected, "CANDIDATE_QUARTER_ORDER_INVALID"):
            consume_candidate(candidate)

    def test_candidate_cannot_alias_formal_eps(self):
        candidate = self.build()
        candidate["quarterly_eps"] = [1] * 8
        with self.assertRaisesRegex(Rejected, "FORMAL_EPS_ALIAS_FORBIDDEN"):
            consume_candidate(candidate)

    def test_q4_cannot_be_upgraded_to_official_or_derived_proof(self):
        self.modify_inputs(lambda d: d["records"][0].update(q4_raw_or_derived_classification="OFFICIALLY_REPORTED_SINGLE_QUARTER"))
        self.assert_rejected("UNSUPPORTED_Q4_CLAIM")

    def test_duplicate_or_conflicting_raw_target_cannot_be_ignored(self):
        inputs = self.inputs()
        row = inputs["records"][0]
        raw_path, receipt_path = Path(row["raw_path"]), Path(row["receipt_reference"])
        original_raw = raw_path.read_bytes()
        for conflicting in (False, True):
            with self.subTest(conflicting=conflicting):
                payload = json.loads(original_raw)
                extra = deepcopy(payload["data"][row["raw_row_index_zero_based"]])
                if conflicting:
                    extra["value"] = 999
                payload["data"].append(extra)
                body = json.dumps(payload).encode()
                raw_path.write_bytes(body)
                receipt = json.loads(receipt_path.read_bytes())
                receipt.update(bytes=len(body), content_length=str(len(body)), response_body_sha256=sha256(body))
                write(receipt_path, receipt)
                self.assert_rejected("RAW_CONFLICTING_VALUE" if conflicting else "RAW_DUPLICATE_KEY")

    def test_inputs_unchanged_and_repeat_replay_stable(self):
        before = {str(p): sha256(p.read_bytes()) for p in self.root.rglob("*") if p.is_file()}
        a, b = self.build(), self.build()
        self.assertEqual(a["artifact_id"], b["artifact_id"])
        self.assertEqual(consume_candidate(a), consume_candidate(b))
        self.assertEqual(before, {str(p): sha256(p.read_bytes()) for p in self.root.rglob("*") if p.is_file()})
        self.assertNotEqual(a["generated_at"], b["generated_at"])


if __name__ == "__main__":
    unittest.main()
