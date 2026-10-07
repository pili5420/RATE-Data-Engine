"""B1 safety and unchanged formal paths; retained bytes plus labelled fixtures."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from src.eps_b1_research import (BOUNDARY, ROOT, Rejected, build_view, canonical, digest,
                               export_view, markdown_view, validate_view, verify_export)
from scripts.eps_b1_formal_fixture import formal_fingerprint

ARCHIVE = ROOT / "tests/fixtures/eps_duration/official-proof.zip"
CUTOFF = "2026-10-07T23:59:59+08:00"
SHA = "a" * 40


class B1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.value = build_view(ARCHIVE, CUTOFF, SHA, generated_at="2026-10-08T00:00:00+08:00")

    def test_exact_replay_counts_not_full_market(self):
        s = self.value["core"]["summary"]
        self.assertEqual((s["receipt_count"], s["unique_body_count"], s["replayed_eps_document_count"],
                          s["replayed_fact_count"], s["displayed_fact_count"]), (75, 73, 18, 112, 112))
        self.assertEqual(s["not_evaluated_symbol_count"], 1976)
        self.assertEqual(s["not_evaluated_status"], "NOT_EVALUATED")
        self.assertEqual(s["source_evidence_only_symbols"], ["1340"])

    def test_all_outputs_and_facts_have_nondecision_boundary(self):
        for value in [self.value, self.value["core"], *self.value["core"]["facts"]]:
            for k, v in BOUNDARY.items():
                self.assertEqual(value[k], v)
        self.assertEqual(self.value["core"]["summary"]["original_eight_quarter_coverage"], "0/1978")

    def test_independent_raw_semantic_pit_statuses(self):
        for fact in self.value["core"]["facts"]:
            self.assertEqual(fact["raw_integrity_status"], "PASS")
            self.assertEqual(fact["fact_semantics_status"], "PASS")
            self.assertEqual(fact["historical_pit_status"], "UNPROVEN")
            self.assertEqual(fact["latest_version_status"], "UNPROVEN")
            self.assertIsNone(fact["source_publication_time"])
            self.assertIsNone(fact["revision_identity"])
            self.assertNotIn("single_quarter_eps", fact)

    def test_quarantine_no_verified_numeric_display(self):
        quarantined = self.value["core"]["quarantine"]
        self.assertEqual(len(quarantined), 2)
        self.assertEqual(sorted(q["reason"] for q in quarantined),
                         ["COMPLETED_RESPONSE_UNPROVEN", "UNAPPROVED_REDIRECT"])
        self.assertTrue(all(q["verified_numeric_value"] is None for q in quarantined))

    def test_time_requires_explicit_timezone(self):
        for cutoff in ("2026-10-07", "2026-10-07T12:00:00"):
            with self.assertRaisesRegex(Rejected, "TIMEZONE_UNPROVEN"):
                build_view(ARCHIVE, cutoff, SHA)

    def test_observed_forward_cannot_backfill_historical_cutoff(self):
        early = build_view(ARCHIVE, "2026-10-05T23:59:59+08:00", SHA)
        self.assertEqual(early["core"]["facts"], [])
        self.assertEqual(len(early["core"]["excluded_observations"]), 112)
        self.assertTrue(all(f["verified_numeric_value"] is None for f in early["core"]["excluded_observations"]))
        self.assertEqual(early["core"]["historical_cutoff"], "2026-10-05")

    def test_observation_timestamp_preserved_across_exports(self):
        later = build_view(ARCHIVE, CUTOFF, SHA, generated_at="2026-11-01T00:00:00+08:00")
        self.assertEqual(self.value["core"], later["core"])
        self.assertEqual(self.value["core_sha256"], later["core_sha256"])

    def test_duration_and_basis_are_not_merged(self):
        facts = self.value["core"]["facts"]
        groups = {(f["duration"], f["eps_basis"]) for f in facts}
        self.assertEqual(len(groups), 6)
        self.assertEqual(len({f["fact_id"] for f in facts}), 112)
        self.assertTrue(all(not (f["duration"] == "QUARTER" and f["period_start"].endswith("01-01")
                                and f["period_end"].endswith("12-31")) for f in facts))

    def test_no_new_ttm_or_score_fields(self):
        text = canonical(self.value).decode()
        for field in ("single_quarter_eps", "quarterly_eps", "eps_ttm", "rate_composite_score", "buy_signal"):
            self.assertNotIn('"' + field + '"', text)

    def test_raw_tamper_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "tampered.zip"
            path.write_bytes(ARCHIVE.read_bytes() + b"tamper")
            with self.assertRaisesRegex(ValueError, "ARCHIVE_HASH_MISMATCH"):
                build_view(path, CUTOFF, SHA)

    def test_serialized_fact_tamper_even_after_rehash_rejected(self):
        for key, value in (("normalized_value", "999"), ("duration", "QUARTER"),
                           ("eps_basis", "UNPROVEN"), ("first_verified_observed_at", "2000-01-01T00:00:00Z")):
            bad = copy.deepcopy(self.value)
            fact = next(f for f in bad["core"]["facts"] if f["duration"] == "ANNUAL")
            fact[key] = value
            bad["core_sha256"] = digest(canonical(bad["core"]))
            with self.assertRaisesRegex(Rejected, "B1_SERIALIZED_MATERIAL_TAMPERED"):
                validate_view(bad, ARCHIVE)

    def test_false_boundary_must_not_be_integer_zero(self):
        bad = copy.deepcopy(self.value)
        bad["production_eligible"] = 0
        with self.assertRaisesRegex(Rejected, "B1_SERIALIZED_MATERIAL_TAMPERED"):
            validate_view(bad, ARCHIVE)

    def test_chinese_view_exposes_limits_and_full_fact_metadata(self):
        text = markdown_view(self.value)
        for word in ("研究證據視圖", "Historical PIT：UNPROVEN", "BASIC", "DILUTED", "ANNUAL",
                     "YEAR_TO_DATE", "first_verified_observed_at", "公開時間：未知", "precision", "NOT_EVALUATED"):
            self.assertIn(word, text)

    def test_new_external_directory_and_manifest_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "rate-eps-b1-research"
            output = root / "run1"
            manifest = export_view(self.value, ARCHIVE, root, output)
            self.assertEqual(verify_export(output, ARCHIVE), "PASS_NONDECISION_ONLY")
            self.assertFalse(manifest["production_eligible"])
            with self.assertRaisesRegex(Rejected, "B1_OUTPUT_ALREADY_EXISTS"):
                export_view(self.value, ARCHIVE, root, output)
            previous = (output / "RATE_EPS_B1_RESEARCH_VIEW.json").read_bytes()
            export_view(self.value, ARCHIVE, root, root / "run2")
            self.assertEqual((output / "RATE_EPS_B1_RESEARCH_VIEW.json").read_bytes(), previous)

    def test_manifest_and_output_tamper_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "rate-eps-b1-research"
            output = root / "one"
            export_view(self.value, ARCHIVE, root, output)
            target = output / "RATE_EPS_B1_RESEARCH_VIEW.json"
            target.write_bytes(target.read_bytes() + b"tamper")
            with self.assertRaisesRegex(Rejected, "B1_OUTPUT_HASH_MISMATCH"):
                verify_export(output, ARCHIVE)

    def test_protected_output_and_path_escape_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "rate-eps-b1-research"
            for output in (Path(d) / "outside", root / ".." / "outside", ROOT / "artifacts" / "B1"):
                with self.assertRaises(Rejected):
                    export_view(self.value, ARCHIVE, root, output)
                self.assertFalse(output.exists())
            with self.assertRaisesRegex(Rejected, "B1_DEDICATED_ROOT_REQUIRED"):
                export_view(self.value, ARCHIVE, Path(d) / "wrong-root", Path(d) / "wrong-root" / "out")
            for namespace in ("data", "artifacts", "production", "portfolio", "ledger", "latest",
                              "state", "live_state", "STATE_LATEST", "RATE_STATE_LATEST",
                              "Roy_Portfolio", "AI_Paper_Portfolio", "Transaction_Ledger"):
                with self.assertRaisesRegex(Rejected, "B1_PROTECTED_NAMESPACE"):
                    export_view(self.value, ARCHIVE, root, root / namespace / "new")

    def test_b1_cannot_write_any_git_repository(self):
        with tempfile.TemporaryDirectory() as d:
            parent = Path(d) / "other-checkout"
            (parent / ".git").mkdir(parents=True)
            root = parent / "rate-eps-b1-research"
            with self.assertRaisesRegex(Rejected, "B1_OUTPUT_INSIDE_REPOSITORY"):
                export_view(self.value, ARCHIVE, root, root / "run")

    def test_absent_present_updated_corrupt_b1_does_not_change_formal_outputs(self):
        baseline = formal_fingerprint()
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "rate-eps-b1-research"
            output = root / "present"
            self.assertEqual(formal_fingerprint(), baseline)
            export_view(self.value, ARCHIVE, root, output)
            self.assertEqual(formal_fingerprint(), baseline)
            later = build_view(ARCHIVE, "2026-10-05T23:59:59+08:00", SHA, generated_at="2026-11-01T00:00:00Z")
            self.assertNotEqual(later["core"], self.value["core"])
            export_view(later, ARCHIVE, root, root / "updated")
            self.assertEqual(formal_fingerprint(), baseline)
            (output / "RATE_EPS_B1_RESEARCH_VIEW.json").write_text("corrupt", encoding="utf-8")
            self.assertEqual(formal_fingerprint(), baseline)
            self.assertIn("FUNDAMENTAL_EPS_PERIOD_NOT_AVAILABLE", baseline["missing_formal_eps_gate"])
            self.assertEqual(baseline["state_mutation"], 0)

    def test_rehashed_manifest_cannot_claim_production_or_different_artifact(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "rate-eps-b1-research"
            for i, (field, value) in enumerate((("artifact", "RATE_PRODUCTION_SOURCE_BUNDLE"),
                                               ("validation", {"historical_pit": "PASS"}))):
                output = root / str(i)
                manifest = export_view(self.value, ARCHIVE, root, output)
                manifest[field] = value
                manifest["manifest_sha256"] = digest(canonical({k: v for k, v in manifest.items() if k != "manifest_sha256"}))
                (output / "RATE_EPS_B1_RESEARCH_MANIFEST.json").write_bytes(canonical(manifest))
                with self.assertRaisesRegex(Rejected, "B1_MANIFEST_BINDING_INVALID"):
                    verify_export(output, ARCHIVE)

    def test_expected_head_binding(self):
        with self.assertRaisesRegex(Rejected, "B1_CODE_SHA_BINDING_INVALID"):
            validate_view(self.value, ARCHIVE, expected_code_sha="b" * 40)

    def test_linked_output_root_rejected(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "rate-eps-b1-research"
            with patch.object(Path, "is_symlink", return_value=True):
                with self.assertRaisesRegex(Rejected, "B1_OUTPUT_LINK_FORBIDDEN"):
                    export_view(self.value, ARCHIVE, root, root / "new")
            self.assertFalse(root.exists())
