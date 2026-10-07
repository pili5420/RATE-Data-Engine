"""Real-byte replay and separately labelled engineering knowledge-time fixtures."""
from dataclasses import asdict, replace
import json
from pathlib import Path
import unittest
import zipfile

from scripts.replay_eps_duration_proof import ARCHIVE_SHA, replay
from src.eps_duration_facts.model import Expectation, Rejected, validate_semantics
from src.eps_duration_facts.parser import parse_inline, parse_book_calendar
from src.eps_duration_facts.pit import (Index, Version, observed_forward_only, select_eight,
                                      select_version, validate_index, validate_pit)
from src.eps_duration_facts.raw import audit_archive, sha256, verify_receipt
from src.eps_duration_facts.validator import evaluate, validate_fact_replay

ARCHIVE = Path(__file__).parent / "fixtures/eps_duration/official-proof.zip"
WINDOW = ("2026Q3", "2026Q2", "2026Q1", "2025Q4", "2025Q3", "2025Q2",
          "2025Q1", "2024Q4", "2024Q3", "2024Q2")
CUTOFF = "2026-10-05T00:00:00+08:00"


def archived(label, prefix="prior"):
    with zipfile.ZipFile(ARCHIVE) as archive:
        receipt = json.loads(archive.read(prefix + "/receipts/" + label + ".json"))
        data = archive.read(prefix + "/raw/" + receipt["body_sha256"] + ".bin")
    return receipt, data


def fixture_index(fact, versions=None):
    """Synthetic attestations exercise gates, not claimed official version evidence."""
    version = Version("ENGINEERING_FIXTURE_ORIGINAL", fact.symbol, fact.market, "2026Q2",
                      fact.raw_sha256, "2026-08-01T12:00:00+08:00", "SECOND",
                      "ENGINEERING_FIXTURE_PUBLIC_HASH_BINDING_NOT_OFFICIAL", "PASS")
    return Index(fact.symbol, fact.market, WINDOW, "2026-10-08T00:00:00+08:00",
                 ("page1", "page2"), ("page1", "page2"), ("a" * 64, "b" * 64),
                 tuple(versions or (version,)), "PASS", "ENGINEERING_FIXTURE_COMPLETE_INDEX", "PASS")


class ArchivedReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.receipt, cls.data = archived("2330-2026Q2-download")
        calendar_receipt, calendar_body = archived("book-index-2330-2026")
        cls.calendar = parse_book_calendar(calendar_receipt, calendar_body, "2330")
        cls.facts = parse_inline(cls.receipt, cls.data, "2330", "TWSE", cls.calendar)
        cls.fact = next(f for f in cls.facts if f.eps_basis == "BASIC"
                        and f.period_start == "2026-04-01" and f.period_end == "2026-06-30")
        cls.expected = Expectation("2330", "TWSE", "2026-04-01", "2026-06-30")

    def test_exact_archive_and_entry_hashes(self):
        self.assertEqual(sha256(ARCHIVE.read_bytes()), ARCHIVE_SHA)
        with zipfile.ZipFile(ARCHIVE) as archive:
            for entry in json.loads(archive.read("inventory.json")):
                self.assertEqual(sha256(archive.read(entry["path"])), entry["sha256"])

    def test_receipts_not_filings_and_same_body_acquisitions_preserved(self):
        with zipfile.ZipFile(ARCHIVE) as archive:
            prior, new = audit_archive(archive, "prior"), audit_archive(archive, "new")
        self.assertEqual((prior["receipt_count"], prior["unique_body_count"],
                          prior["filing_identity_count"], prior["filing_responses"]), (71, 70, 18, 22))
        self.assertEqual(prior["failed_attempts"], 2)
        self.assertEqual(len(prior["same_body_multiple_receipts"]), 1)
        self.assertEqual((new["completed_responses"], new["failed_responses"]), (3, 1))
        self.assertEqual(prior["source_binding_rejections"]["prior/receipts/mops-spa.json"],
                         "UNAPPROVED_REDIRECT")

    def test_all_eighteen_filings_exact_replay_no_production_credit(self):
        result = replay(ARCHIVE)
        self.assertEqual(len(result["filings"]), 18)
        count = 0
        for filing in result["filings"]:
            for fact in filing["facts"]:
                count += 1
                self.assertEqual(fact["raw_integrity_status"], "PASS")
                self.assertEqual(fact["historical_pit_status"], "UNPROVEN")
                self.assertFalse(fact["production_eligible"])
                self.assertEqual(fact["original_eight_quarter_coverage_credit"], 0)
                self.assertIsNone(fact["source_publication_time"])
                self.assertIsNone(fact["precision"])
                self.assertNotIn("single_quarter_eps", fact)
        self.assertEqual(count, 112)

    def test_tampered_bytes_rejected(self):
        with self.assertRaisesRegex(Rejected, "BODY_HASH_MISMATCH"):
            parse_inline(self.receipt, self.data[:-1] + b"!", "2330", "TWSE", self.calendar)

    def test_serialized_fact_tamper_rejected_by_exact_replay(self):
        self.assertEqual(validate_fact_replay(self.fact, self.receipt, self.data, self.calendar), "PASS")
        for field, value in (("normalized_value", "999"), ("duration", "ANNUAL"),
                             ("statement_scope", "SEPARATE"),
                             ("first_verified_observed_at", "2020-01-01T00:00:00+00:00")):
            with self.subTest(field=field), self.assertRaisesRegex(Rejected, "FACT_MATERIAL_TAMPERED"):
                validate_fact_replay(replace(self.fact, **{field: value}), self.receipt, self.data, self.calendar)

    def test_composite_gates_pass_only_diagnostic_engineering_version_fixture(self):
        result = evaluate(self.fact, self.expected, self.receipt, self.data, self.calendar,
                          fixture_index(self.fact), "2026Q2", CUTOFF)
        self.assertEqual(result["pit_selection_status"], "PASS")
        self.assertFalse(result["production_eligible"])

    def test_wrong_endpoint_redirect_http_length_fallback_rejected(self):
        for key, value, reason in (("final_url", "https://example.com", "UNAPPROVED_REDIRECT"),
                                  ("http_status", 403, "HTTP_NOT_200"),
                                  ("response_bytes", 2, "BODY_LENGTH_MISMATCH"),
                                  ("content_length", "2", "CONTENT_LENGTH_MISMATCH")):
            with self.subTest(key=key):
                receipt = json.loads(json.dumps(self.receipt))
                receipt["attempts"][-1][key] = value
                with self.assertRaisesRegex(Rejected, reason):
                    verify_receipt(receipt, self.data, self.receipt["endpoint"])
        receipt = dict(self.receipt, fallback_used=True)
        with self.assertRaisesRegex(Rejected, "FALLBACK_FORBIDDEN"):
            verify_receipt(receipt, self.data, self.receipt["endpoint"])

    def test_visible_book_calendar_not_request_assumption(self):
        self.assertEqual(self.calendar.start_month, 1)
        self.assertEqual(self.calendar.symbol, "2330")
        with self.assertRaisesRegex(Rejected, "FISCAL_CALENDAR_BINDING_INVALID"):
            parse_inline(self.receipt, self.data, "2330", "TWSE", True)

    def test_unknown_calendar_duration_stays_unproven(self):
        facts = parse_inline(self.receipt, self.data, "2330", "TWSE")
        self.assertTrue(all(f.duration == "UNPROVEN" for f in facts))

    def test_direct_basic_quarter_positive_semantics(self):
        self.assertEqual(self.fact.normalized_value, "27.25")
        self.assertEqual(validate_semantics(self.fact, self.expected), "PASS")

    def test_annual_not_q4_quarter(self):
        for symbol, market in (("2330", "TWSE"), ("6488", "TPEX")):
            for year in (2024, 2025):
                with self.subTest(symbol=symbol, year=year):
                    receipt, data = archived(f"{symbol}-{year}Q4-download")
                    cr, cb = archived(f"book-index-{symbol}-{year}")
                    facts = parse_inline(receipt, data, symbol, market, parse_book_calendar(cr, cb, symbol))
                    self.assertTrue(all(f.duration == "ANNUAL" for f in facts))
                    self.assertFalse(any(f.period_start.endswith("10-01") for f in facts))
                    basic = next(f for f in facts if f.eps_basis == "BASIC")
                    expected = Expectation(symbol, market, f"{year}-10-01", f"{year}-12-31")
                    with self.assertRaisesRegex(Rejected, "DURATION_MISMATCH"):
                        validate_semantics(basic, expected)

    def test_ytd_not_quarter(self):
        fact = next(f for f in self.facts if f.eps_basis == "BASIC" and f.duration == "YEAR_TO_DATE")
        with self.assertRaisesRegex(Rejected, "DURATION_MISMATCH"):
            validate_semantics(fact, self.expected)

    def test_diluted_not_basic(self):
        fact = next(f for f in self.facts if f.eps_basis == "DILUTED")
        with self.assertRaisesRegex(Rejected, "BASIC_DILUTED_MISMATCH"):
            validate_semantics(fact, self.expected)

    def test_wrong_issuer_market_scope_unit_concept_context(self):
        cases = (("symbol", "6488", "WRONG_ISSUER"), ("market", "TPEX", "WRONG_MARKET"),
                 ("issuer_identifier_scheme", "https://example.com", "ISSUER_SCHEME_UNPROVEN"),
                 ("statement_scope", "SEPARATE", "WRONG_SCOPE"), ("unit", "USD/shares", "WRONG_UNIT"),
                 ("concept", "{https://example.com}BasicEarningsLossPerShare", "WRONG_CONCEPT"),
                 ("period_start", "2026-01-01", "WRONG_CONTEXT"))
        for field, value, error in cases:
            with self.subTest(field=field), self.assertRaisesRegex(Rejected, error):
                validate_semantics(replace(self.fact, **{field: value}), self.expected)

    def test_request_period_does_not_replace_returned_period(self):
        receipt = json.loads(json.dumps(self.receipt))
        receipt["endpoint"] = receipt["endpoint"].replace("year=2026", "year=2025")
        receipt["attempts"][-1]["final_url"] = receipt["endpoint"]
        with self.assertRaisesRegex(Rejected, "RETURNED_PERIOD_MISMATCH"):
            parse_inline(receipt, self.data, "2330", "TWSE", self.calendar)

    def test_sec_403_is_retained_failure_not_exact_raw_replay(self):
        with zipfile.ZipFile(ARCHIVE) as archive:
            receipt = json.loads(archive.read("new/receipts/sec-accession-index.json"))
        self.assertEqual(receipt["attempts"][0]["http_status"], 403)
        self.assertFalse(receipt["attempts"][0]["retry"])
        self.assertNotIn("body_sha256", receipt)
        self.assertFalse(receipt["production_authority"])

    def test_tsmc_q4_diluted_attachment_binding_exact_bytes(self):
        receipt, data = archived("tsmc-ir-2025Q4", "new")
        pdf_receipt, pdf = archived("tsmc-ir-2025Q4-pdf", "new")
        from lxml import html
        from urllib.parse import urljoin
        root = html.fromstring(data)
        links = [urljoin(receipt["endpoint"], h) for h in root.xpath("//a/@href")]
        self.assertIn(pdf_receipt["endpoint"], links)
        visible = " ".join(root.text_content().split())
        self.assertIn("diluted earnings per share", visible)
        self.assertIn("19.50", visible)
        self.assertIn("December 31, 2025", visible)
        self.assertTrue(pdf.startswith(b"%PDF"))
        verify_receipt(pdf_receipt, pdf, pdf_receipt["endpoint"])


class KnowledgeTimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ArchivedReplayTests.setUpClass()
        cls.fact, cls.expected = ArchivedReplayTests.fact, ArchivedReplayTests.expected

    def test_engineering_fixture_pit_pass_still_zero_coverage(self):
        result = validate_pit(self.fact, self.expected, fixture_index(self.fact), "2026Q2", CUTOFF)
        self.assertEqual(result["historical_pit_status"], "PASS")
        self.assertFalse(result["production_eligible"])
        self.assertEqual(result["coverage_credit"], 0)

    def test_real_source_no_public_version_is_unproven(self):
        index = replace(fixture_index(self.fact), version_history_status="UNPROVEN")
        with self.assertRaisesRegex(Rejected, "INDEX_INCOMPLETE_ANCHOR_UNPROVEN"):
            validate_pit(self.fact, self.expected, index, "2026Q2", CUTOFF)

    def test_revision_cannot_contaminate_pre_revision_cutoff(self):
        index = fixture_index(self.fact)
        original = index.versions[0]
        revision = replace(original, version_id="FIXTURE_REVISION", body_sha256="c" * 64,
                           public_at="2026-09-01T12:00:00+08:00", supersedes=original.version_id)
        index = replace(index, versions=(original, revision))
        self.assertEqual(select_version(index, "2026Q2", "2026-08-15T00:00:00+08:00"), original)
        with self.assertRaisesRegex(Rejected, "REVISION_LOOKAHEAD"):
            validate_pit(replace(self.fact, raw_sha256=revision.body_sha256), self.expected, index,
                         "2026Q2", "2026-08-15T00:00:00+08:00")

    def test_missing_original_blocks_pre_and_post_revision(self):
        original = fixture_index(self.fact).versions[0]
        revision = replace(original, version_id="FIXTURE_REVISION", public_at="2026-09-01T12:00:00+08:00",
                           supersedes=original.version_id)
        for cutoff in ("2026-08-15T00:00:00+08:00", CUTOFF):
            with self.subTest(cutoff=cutoff), self.assertRaisesRegex(Rejected, "ORIGINAL_VERSION_MISSING"):
                select_version(fixture_index(self.fact, (revision,)), "2026Q2", cutoff)

    def test_post_revision_evaluates_selected_version_and_index_separately(self):
        original = fixture_index(self.fact).versions[0]
        revision = replace(original, version_id="FIXTURE_REVISION", body_sha256="c" * 64,
                           public_at="2026-09-01T12:00:00+08:00", supersedes=original.version_id)
        index = fixture_index(self.fact, (original, revision))
        current = replace(self.fact, raw_sha256=revision.body_sha256)
        self.assertEqual(validate_pit(current, self.expected, index, "2026Q2", CUTOFF)["selected_version"],
                         revision.version_id)
        with self.assertRaisesRegex(Rejected, "INDEX_INCOMPLETE"):
            validate_pit(current, self.expected, replace(index, completeness_status="UNPROVEN"), "2026Q2", CUTOFF)

    def test_latest_unproven_without_complete_version_record(self):
        with self.assertRaisesRegex(Rejected, "INDEX_INCOMPLETE"):
            select_version(replace(fixture_index(self.fact), version_history_status="UNPROVEN"), "2026Q2", CUTOFF)

    def test_pagination_missing_blocks_anchor(self):
        with self.assertRaisesRegex(Rejected, "INDEX_PAGINATION_INCOMPLETE"):
            select_eight(replace(fixture_index(self.fact), verified_pages=("page1",)), CUTOFF)

    def test_observed_only_cannot_backfill_historical_cutoff(self):
        with self.assertRaisesRegex(Rejected, "OBSERVED_ONLY_HISTORICAL_BACKFILL_FORBIDDEN"):
            observed_forward_only(self.fact, CUTOFF)

    def test_forward_observation_is_not_publication(self):
        result = observed_forward_only(self.fact, "2026-10-08T00:00:00+08:00")
        self.assertEqual(result["historical_pit_status"], "UNPROVEN")
        self.assertFalse(result["production_eligible"])
        self.assertIsNone(self.fact.source_publication_time)

    def test_date_only_naive_time_cannot_become_exact_public_clock(self):
        version = replace(fixture_index(self.fact).versions[0], public_at="2026-08-01", publication_precision="DAY")
        with self.assertRaisesRegex(Rejected, "ASOF_VERSION_UNPROVEN"):
            validate_index(fixture_index(self.fact, (version,)), CUTOFF)
        version = replace(version, publication_precision="SECOND")
        with self.assertRaisesRegex(Rejected, "TIMEZONE_UNPROVEN"):
            validate_index(fixture_index(self.fact, (version,)), CUTOFF)

    def test_missing_quarter_no_older_substitution(self):
        template = fixture_index(self.fact).versions[0]
        versions = tuple(replace(template, version_id="FIXTURE_" + p, period=p)
                         for p in WINDOW if p != "2025Q4")
        with self.assertRaisesRegex(Rejected, "REQUIRED_QUARTER_MISSING_NO_SUBSTITUTION"):
            select_eight(fixture_index(self.fact, versions), CUTOFF)

    def test_anchor_is_independent_of_parser_success(self):
        template = fixture_index(self.fact).versions[0]
        versions = tuple(replace(template, version_id="FIXTURE_" + p, period=p) for p in WINDOW)
        anchor, selected = select_eight(fixture_index(self.fact, versions), CUTOFF)
        self.assertEqual((anchor, selected), (WINDOW[0], WINDOW[:8]))

    def test_1340_actual_revision_does_not_prove_original_or_latest(self):
        receipt, data = archived("correction-1340-attachment-0")
        verify_receipt(receipt, data, receipt["endpoint"])
        self.assertEqual(sha256(data), "ae9f74e0377a716ed8445fb40c554bef0407ee7c3f080e0ab71390d692ecc999")
        with zipfile.ZipFile(ARCHIVE) as archive:
            evidence = json.loads(archive.read("prior/book-and-correction-evidence.json"))
        encoded = json.dumps(evidence, ensure_ascii=False)
        self.assertIn("1340", encoded)
        self.assertIn("20260724", encoded)
        # Actual source has neither original bytes nor a complete public-version index.
        index = replace(fixture_index(self.fact), symbol="1340", completeness_status="UNPROVEN")
        for cutoff in ("2026-07-23T00:00:00+08:00", "2026-07-25T00:00:00+08:00", CUTOFF):
            with self.subTest(cutoff=cutoff), self.assertRaisesRegex(Rejected, "INDEX_INCOMPLETE"):
                select_version(index, "2025Q4", cutoff)

    def test_version_scope_rejection(self):
        index = fixture_index(self.fact)
        index = replace(index, versions=(replace(index.versions[0], statement_scope="SEPARATE"),))
        with self.assertRaisesRegex(Rejected, "VERSION_SCOPE_MISMATCH"):
            validate_pit(self.fact, self.expected, index, "2026Q2", CUTOFF)

    def test_wrong_index_issuer_rejected(self):
        with self.assertRaisesRegex(Rejected, "INDEX_WRONG_ISSUER"):
            validate_pit(self.fact, self.expected, replace(fixture_index(self.fact), symbol="6488"), "2026Q2", CUTOFF)

    def test_duplicate_pages_and_versions_rejected_not_filtered(self):
        index = fixture_index(self.fact)
        with self.assertRaisesRegex(Rejected, "INDEX_PAGE_DUPLICATE"):
            validate_index(replace(index, required_pages=("page1", "page1"), verified_pages=("page1", "page1")), CUTOFF)
        with self.assertRaisesRegex(Rejected, "VERSION_ID_DUPLICATE"):
            validate_index(replace(index, versions=index.versions * 2), CUTOFF)

    def test_index_snapshot_not_covering_cutoff_rejected(self):
        with self.assertRaisesRegex(Rejected, "INDEX_CUTOFF_NOT_COVERED"):
            validate_index(replace(fixture_index(self.fact), assessed_through="2026-09-01T00:00:00+08:00"), CUTOFF)

    def test_public_version_binding_missing_rejected(self):
        index = fixture_index(self.fact)
        for field, value in (("publication_evidence", ""), ("exact_public_version_status", "UNPROVEN")):
            with self.subTest(field=field), self.assertRaisesRegex(Rejected, "ASOF_VERSION_UNPROVEN"):
                validate_index(replace(index, versions=(replace(index.versions[0], **{field: value}),)), CUTOFF)

    def test_no_data_does_not_supply_eight_quarters(self):
        with self.assertRaisesRegex(Rejected, "ANCHOR_UNPROVEN"):
            select_eight(replace(fixture_index(self.fact), versions=()), CUTOFF)

    def test_non_consecutive_window_rejected(self):
        window = WINDOW[:3] + WINDOW[4:] + ("2024Q1",)
        with self.assertRaisesRegex(Rejected, "WINDOW_NOT_CONSECUTIVE"):
            select_eight(replace(fixture_index(self.fact), window=window), CUTOFF)

    def test_unknown_fact_no_substitution_or_mutation(self):
        before = asdict(self.fact)
        with self.assertRaisesRegex(Rejected, "CONCEPT_OR_NUMERIC_UNPROVEN"):
            validate_semantics(replace(self.fact, normalized_value=None, fact_semantics_status="UNPROVEN"), self.expected)
        self.assertEqual(asdict(self.fact), before)
        self.assertFalse(self.fact.production_eligible)

    def test_publication_is_after_cutoff_rejected(self):
        index = fixture_index(self.fact)
        index = replace(index, versions=(replace(index.versions[0], public_at="2026-10-06T00:00:00+08:00"),))
        with self.assertRaisesRegex(Rejected, "ASOF_VERSION_UNPROVEN"):
            select_version(index, "2026Q2", CUTOFF)

    def test_period_name_cannot_alias_another_context(self):
        index = fixture_index(self.fact)
        index = replace(index, versions=(replace(index.versions[0], period="2025Q4"),))
        with self.assertRaisesRegex(Rejected, "FACT_PERIOD_BINDING_INVALID"):
            validate_pit(self.fact, self.expected, index, "2025Q4", CUTOFF)


if __name__ == "__main__":
    unittest.main()
