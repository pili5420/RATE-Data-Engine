"""SYNTHETIC ENGINEERING ONLY: no attestation here is official source proof."""
import calendar
from dataclasses import replace
from datetime import date
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from urllib.parse import urlencode

from src.eps_duration_facts.model import Expectation, Rejected
from src.eps_duration_facts.parser import parse_book_calendar, parse_inline
from src.eps_duration_facts.pit import Index, Version
from src.formal_eps_qualification import inspect_mops_response, qualify_eight
from src.full_market_history import encoded, digest
from src.sources.fundamental_history import MOPS_EPS_ENDPOINT
from src.sources.mops_raw_evidence import retain_response

WINDOW = ("2026Q2", "2026Q1", "2025Q4", "2025Q3", "2025Q2", "2025Q1",
          "2024Q4", "2024Q3", "2024Q2", "2024Q1")
CUTOFF = "2026-10-05T00:00:00+08:00"
OBSERVED = "2026-10-10T12:00:00+08:00"


def receipt_for(body, endpoint, label):
    return {"label": label, "endpoint": endpoint, "fallback_used": False,
            "attempts": [{"transport_integrity": "PASS", "http_status": 200,
                          "final_url": endpoint, "body_sha256": hashlib.sha256(body).hexdigest(),
                          "response_bytes": len(body), "retrieved_at": OBSERVED}]}


def material(period, value="1.23000000000000000001"):
    year, quarter = map(int, period.split("Q"))
    start = date(year, quarter * 3 - 2, 1).isoformat()
    end = date(year, quarter * 3, calendar.monthrange(year, quarter * 3)[1]).isoformat()
    negative = value.startswith("-")
    sign = 'sign="-"' if negative else ''
    body = f'''<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
      xmlns:i="http://www.xbrl.org/2003/instance"
      xmlns:n="http://www.xbrl.org/tifrs/notes/2026-03-31"
      xmlns:f="https://xbrl.ifrs.org/taxonomy/2025-03-27/ifrs-full"
      xmlns:c="http://www.xbrl.org/2003/iso4217"
      xmlns:t="http://www.xbrl.org/inlineXBRL/transformation/2015-02-26">
      <body><p>SYNTHETIC ENGINEERING FIXTURE NOT OFFICIAL</p>
      <ix:nonNumeric name="n:CompanyID">2330</ix:nonNumeric>
      <ix:nonNumeric name="n:Market">Listed company</ix:nonNumeric>
      <ix:nonNumeric name="n:Year">{year}</ix:nonNumeric>
      <ix:nonNumeric name="n:Quarter">{quarter}</ix:nonNumeric>
      <ix:nonNumeric name="n:ReportCategory">Consolidated report</ix:nonNumeric>
      <i:context id="current"><i:entity><i:identifier scheme="http://www.twse.com.tw">2330</i:identifier></i:entity>
      <i:period><i:startDate>{start}</i:startDate><i:endDate>{end}</i:endDate></i:period></i:context>
      <i:unit id="u"><i:divide><i:unitNumerator><i:measure>c:TWD</i:measure></i:unitNumerator>
      <i:unitDenominator><i:measure>i:shares</i:measure></i:unitDenominator></i:divide></i:unit>
      <ix:nonFraction name="f:BasicEarningsLossPerShare" contextRef="current" unitRef="u"
        format="t:numdotdecimal" {sign}>{value.lstrip('-')}</ix:nonFraction></body></html>'''.encode()
    endpoint = f"https://mopsov.twse.com.tw/server-java/FileDownLoad?functionName=t164sb01&step=9&co_id=2330&report_id=C&year={year}&season={quarter}"
    receipt = receipt_for(body, endpoint, "SYNTHETIC_" + period)
    book = '<html><head><meta charset="utf-8"/></head><body>會計期間：曆年制 SYNTHETIC ENGINEERING ONLY</body></html>'.encode()
    book_receipt = receipt_for(book, "https://doc.twse.com.tw/server-java/t57sb01?co_id=2330", "SYNTHETIC_CALENDAR")
    fiscal = parse_book_calendar(book_receipt, book, "2330")
    fact = parse_inline(receipt, body, "2330", "TWSE", fiscal)[0]
    return fact, Expectation("2330", "TWSE", start, end), receipt, body, fiscal


def engineering_case():
    materials = [material(q, "0" if n == 0 else "-2.5" if n == 1 else "1.23000000000000000001")
                 for n, q in enumerate(WINDOW[:8])]
    versions = tuple(Version("SYNTHETIC_" + q, "2330", "TWSE", q, m[0].raw_sha256,
                             "2026-08-01T12:00:00+08:00", "SECOND",
                             "SYNTHETIC_PUBLIC_VERSION_ATTESTATION_NOT_SOURCE_PROOF", "PASS")
                     for q, m in zip(WINDOW, materials))
    index = Index("2330", "TWSE", WINDOW, OBSERVED, ("SYNTHETIC_PAGE",), ("SYNTHETIC_PAGE",),
                  ("a" * 64,), versions, "PASS", "SYNTHETIC_INDEX_ATTESTATION_NOT_OFFICIAL", "PASS")
    return materials, index


class EightQuarterEngineeringTests(unittest.TestCase):
    def setUp(self):
        self.materials, self.index = engineering_case()

    def test_valid_exact_eight_still_no_production_credit(self):
        result = qualify_eight(self.materials, self.index, CUTOFF)
        self.assertEqual([r["quarter"] for r in result["records"]], list(WINDOW[:8]))
        self.assertEqual(result["candidate_evidence_gates"], "PASS")
        self.assertFalse(result["production_eligible"])
        self.assertEqual(result["original_eight_quarter_coverage_credit"], 0)
        self.assertEqual(result["formal_warmup_gate"], "FUNDAMENTAL_EPS_PERIOD_IDENTITY_UNPROVEN")

    def test_unordered_input_deterministic(self):
        self.assertEqual(qualify_eight(self.materials, self.index, CUTOFF),
                         qualify_eight(list(reversed(self.materials)), self.index, CUTOFF))

    def test_zero_negative_precision_preserved(self):
        values = [r["value"] for r in qualify_eight(self.materials, self.index, CUTOFF)["records"]]
        self.assertEqual(values[:3], ["0", "-2.5", "1.23000000000000000001"])

    def test_duplicate_quarter_rejected(self):
        self.materials[-1] = self.materials[0]
        with self.assertRaisesRegex(Rejected, "DUPLICATE_QUARTER"):
            qualify_eight(self.materials, self.index, CUTOFF)

    def test_missing_quarter_rejected(self):
        with self.assertRaisesRegex(Rejected, "EXACT_EIGHT_REQUIRED"):
            qualify_eight(self.materials[:-1], self.index, CUTOFF)

    def test_missing_index_quarter_not_older_substitution(self):
        with self.assertRaisesRegex(Rejected, "REQUIRED_QUARTER_MISSING"):
            qualify_eight(self.materials, replace(self.index, versions=self.index.versions[:-1]), CUTOFF)

    def test_ambiguous_public_version_rejected(self):
        other = replace(self.index.versions[0], version_id="SYNTHETIC_CONFLICT", body_sha256="b" * 64)
        with self.assertRaisesRegex(Rejected, "REVISION_CONFLICT|VERSION_SELECTION_AMBIGUOUS"):
            qualify_eight(self.materials, replace(self.index, versions=(*self.index.versions, other)), CUTOFF)

    def test_revision_branch_rejected_even_with_distinct_times(self):
        other = replace(self.index.versions[0], version_id="SYNTHETIC_BRANCH", public_at="2026-09-01T12:00:00+08:00")
        with self.assertRaisesRegex(Rejected, "REVISION_CONFLICT"):
            qualify_eight(self.materials, replace(self.index, versions=(*self.index.versions, other)), CUTOFF)

    def test_revision_missing_original_rejected(self):
        version = replace(self.index.versions[0], supersedes="MISSING_ORIGINAL")
        with self.assertRaisesRegex(Rejected, "ORIGINAL_VERSION_MISSING"):
            qualify_eight(self.materials, replace(self.index, versions=(version, *self.index.versions[1:])), CUTOFF)

    def test_future_disclosure_not_selected(self):
        versions = tuple(replace(v, public_at="2026-11-01T12:00:00+08:00") for v in self.index.versions)
        with self.assertRaisesRegex(Rejected, "ANCHOR_UNPROVEN"):
            qualify_eight(self.materials, replace(self.index, versions=versions), CUTOFF)

    def test_wrong_company_identity(self):
        with self.assertRaisesRegex(Rejected, "INDEX_WRONG_ISSUER"):
            qualify_eight(self.materials, replace(self.index, symbol="6488"), CUTOFF)

    def test_wrong_fiscal_period(self):
        fact, expected, *rest = self.materials[0]
        self.materials[0] = (fact, replace(expected, period_start="2026-01-01"), *rest)
        with self.assertRaisesRegex(Rejected, "WRONG_CONTEXT"):
            qualify_eight(self.materials, self.index, CUTOFF)

    def test_outside_window_rejected(self):
        self.materials[-1] = material("2024Q2")
        with self.assertRaisesRegex(Rejected, "QUARTER_OUTSIDE_REQUIRED_WINDOW"):
            qualify_eight(self.materials, self.index, CUTOFF)

    def test_raw_tamper_rejected(self):
        f, e, r, b, c = self.materials[0]
        self.materials[0] = (f, e, r, b[:-1] + b"!", c)
        with self.assertRaisesRegex(Rejected, "BODY_HASH_MISMATCH"):
            qualify_eight(self.materials, self.index, CUTOFF)

    def test_serialized_fact_tamper_rejected(self):
        f, *rest = self.materials[0]
        self.materials[0] = (replace(f, normalized_value="999"), *rest)
        with self.assertRaisesRegex(Rejected, "FACT_MATERIAL_TAMPERED"):
            qualify_eight(self.materials, self.index, CUTOFF)

    def test_receipt_tamper_rejected(self):
        f, e, r, b, c = self.materials[0]
        r = json.loads(json.dumps(r)); r["attempts"][0]["body_sha256"] = "c" * 64
        self.materials[0] = (f, e, r, b, c)
        with self.assertRaisesRegex(Rejected, "BODY_HASH_MISMATCH"):
            qualify_eight(self.materials, self.index, CUTOFF)

    def test_retrieval_time_not_publication_substitute(self):
        self.assertIsNone(self.materials[0][0].source_publication_time)
        versions = tuple(replace(v, publication_evidence="", public_at=OBSERVED) for v in self.index.versions)
        with self.assertRaisesRegex(Rejected, "ASOF_VERSION_UNPROVEN"):
            qualify_eight(self.materials, replace(self.index, versions=versions), CUTOFF)

    def test_no_version_index_no_pass(self):
        with self.assertRaisesRegex(Rejected, "INDEX_INCOMPLETE"):
            qualify_eight(self.materials, replace(self.index, version_history_status="UNPROVEN"), CUTOFF)

    def test_no_fuzzy_basic_label(self):
        f, e, r, b, c = self.materials[0]
        b = b.replace(b"BasicEarningsLossPerShare", b"BasicEarningsLossPerShareSimilar")
        r = receipt_for(b, r["endpoint"], r["label"])
        with self.assertRaisesRegex(Rejected, "EPS_FACTS_MISSING"):
            parse_inline(r, b, "2330", "TWSE", c)

    def test_caller_cannot_relax_basis_scope_unit_or_duration(self):
        for field, value in (("eps_basis", "DILUTED"), ("statement_scope", "SEPARATE"),
                             ("unit", "USD/shares"), ("duration", "ANNUAL")):
            f, e, *rest = self.materials[0]
            materials = [(f, replace(e, **{field: value}), *rest), *self.materials[1:]]
            with self.subTest(field=field), self.assertRaisesRegex(Rejected, "FORMAL_EPS_EXPECTATION_INVALID"):
                qualify_eight(materials, self.index, CUTOFF)

    def test_actual_diluted_fact_rejected(self):
        f, e, r, b, c = self.materials[0]
        b = b.replace(b"BasicEarningsLossPerShare", b"DilutedEarningsLossPerShare")
        r = receipt_for(b, r["endpoint"], r["label"])
        f = parse_inline(r, b, "2330", "TWSE", c)[0]
        materials = [(f, e, r, b, c), *self.materials[1:]]
        with self.assertRaisesRegex(Rejected, "BASIC_DILUTED_MISMATCH"):
            qualify_eight(materials, self.index, CUTOFF)

    def test_ytd_and_annual_contexts_not_single_quarter(self):
        for n in (0, 2):
            f, e, r, b, c = self.materials[n]
            b = b.replace(f.period_start.encode(), (f.period_start[:4] + "-01-01").encode())
            r = receipt_for(b, r["endpoint"], r["label"])
            f = parse_inline(r, b, "2330", "TWSE", c)[0]
            materials = list(self.materials); materials[n] = (f, e, r, b, c)
            with self.subTest(n=n), self.assertRaisesRegex(Rejected, "DURATION_MISMATCH"):
                qualify_eight(materials, self.index, CUTOFF)

    def test_nonfinite_raw_numeric_rejected(self):
        f, e, r, b, c = self.materials[0]
        for value in (b"NaN", b"Infinity", b"-Infinity", b"true"):
            raw = b.replace(b">0</ix:nonFraction>", b">" + value + b"</ix:nonFraction>")
            receipt = receipt_for(raw, r["endpoint"], r["label"])
            with self.subTest(value=value), self.assertRaisesRegex(Rejected, "NUMERIC_FORMAT_INVALID"):
                parse_inline(receipt, raw, "2330", "TWSE", c)

    def test_returned_fiscal_identity_not_request_substitution(self):
        f, e, r, b, c = self.materials[0]
        b = b.replace(b'name="n:Quarter">2<', b'name="n:Quarter">1<')
        r = receipt_for(b, r["endpoint"], r["label"])
        with self.assertRaisesRegex(Rejected, "RETURNED_PERIOD_MISMATCH"):
            parse_inline(r, b, "2330", "TWSE", c)


class SummaryEvidenceEngineeringTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        authority = {"ref": "refs/heads/main", "event": "workflow_dispatch", "run_id": "1",
                     "commit_sha": "a" * 40, "run_attempt": "1",
                     "github_execution_evidence": {"event": "workflow_dispatch", "head_branch": "main",
                        "head_sha": "a" * 40, "run_id": "1", "run_attempt": "1",
                        "workflow_path": ".github/workflows/rate_full_market_history_bootstrap.yml"}}
        metadata = {"plan_id": "SYNTHETIC_PLAN", "acquisition_runtime_authority": authority,
                    "domain": "eps", "market": "TWSE", "requested_period": "2026Q3",
                    "endpoint": MOPS_EPS_ENDPOINT, "final_url": MOPS_EPS_ENDPOINT,
                    "http_status": 200, "source_owner": "MOPS Official", "content_length": None,
                    "request_method": "POST", "request_body_hex": urlencode({"TYPEK": "sii", "year": "115", "season": "03"}).encode().hex(),
                    "retrieval_timestamp": OBSERVED}
        self.reference = retain_response(self.root, "<html>查詢無資料!</html>".encode(), metadata)
        self.receipt = json.loads((self.root / self.reference["path"]).read_bytes())
        self.plan = {"plan_id": "SYNTHETIC_PLAN", "owner_hashes": {
            "src/sources/fundamental_history.py": self.receipt["parser_sha256"]}}

    def test_request_only_cannot_establish_exact_period(self):
        result = inspect_mops_response(self.root, self.reference, self.plan)
        self.assertEqual(result["MOPS_FORMAL_EPS_PERIOD_IDENTITY"], "NOT_PROVEN")
        self.assertTrue(result["official_query_no_data"])
        self.assertIsNone(result["owner_identity"]["year"])
        self.assertIsNone(result["source_publication_time"])

    def test_receipt_hash_tamper_rejected(self):
        (self.root / self.reference["path"]).write_bytes(b"{}")
        with self.assertRaisesRegex(RuntimeError, "MOPS_RAW_RECEIPT_HASH_MISMATCH"):
            inspect_mops_response(self.root, self.reference, self.plan)

    def test_body_hash_tamper_rejected(self):
        (self.root / self.receipt["raw_path"]).write_bytes(b"corrupt")
        with self.assertRaisesRegex(RuntimeError, "MOPS_RAW_BODY_HASH_MISMATCH"):
            inspect_mops_response(self.root, self.reference, self.plan)

    def test_original_owner_binding_not_replaced(self):
        plan = {**self.plan, "owner_hashes": {"src/sources/fundamental_history.py": "b" * 64}}
        with self.assertRaisesRegex(RuntimeError, "MOPS_RAW_PLAN_BINDING_INVALID"):
            inspect_mops_response(self.root, self.reference, plan)

    def test_request_mismatch_rejected(self):
        r = {**self.receipt, "requested_period": "2026Q2"}
        ref = {"path": "reports/mops/" + digest(r) + ".json", "sha256": digest(r)}
        (self.root / ref["path"]).write_bytes(encoded(r))
        with self.assertRaisesRegex(Rejected, "QUALIFICATION_REQUEST_BINDING_INVALID"):
            inspect_mops_response(self.root, ref, self.plan)

    def test_audit_does_not_modify_material(self):
        before = {str(p): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        inspect_mops_response(self.root, self.reference, self.plan)
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.root.rglob("*") if p.is_file()})
