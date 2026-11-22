"""P0 V2 Track A offline-only negative tests; no live official-source calls."""
import unittest

from src.p0_v2_date_semantics import V2Blocked, build_source_receipt, assess_calendar_fixture
from src.p0_v2_pit_universe import assess_pit_model, assess_forward_snapshot

H = "a" * 64
T = "2026-11-23"


def receipt(**changes):
    vals = dict(market="TWSE", dataset_role="classification",
                endpoint="https://isin.twse.com.tw/isin/e_C_public.jsp?strMode=2",
                trading_date=T, source_update_date_raw="2026/11/20",
                observed_at_utc="2026-11-23T01:20:00Z",
                body=b"offline-fixture", http_status=200,
                final_url="https://isin.twse.com.tw/isin/e_C_public.jsp?strMode=2",
                content_length=len(b"offline-fixture"))
    vals.update(changes)
    return build_source_receipt(**vals)


def calendar():
    return {m: {"trading_date": T, "status": "OPEN", "receipt_sha256": H}
            for m in ("TWSE", "TPEX")}


def rows():
    return [
        {"market": "TWSE", "symbol": "2330", "isin": "TW0002330008",
         "cfi_code": "ESVUFR", "listing_market": "TWSE LISTED",
         "lifecycle": "ACTIVE", "effective_from": "2020-01-01",
         "effective_to_exclusive": None, "eligible": True,
         "source_event_id": "synthetic-1", "receipt_sha256": H},
        {"market": "TPEX", "symbol": "6488", "isin": "TW0006488000",
         "cfi_code": "ESVUFR", "listing_market": "TPEx LISTED",
         "lifecycle": "ACTIVE", "effective_from": "2020-01-01",
         "effective_to_exclusive": None, "eligible": True,
         "source_event_id": "synthetic-2", "receipt_sha256": H},
    ]


def coverage():
    return {m: {"model_history_complete": True, "covered_from": "2020-01-01",
                "covered_through": T, "expected_symbols": [s],
                "history_receipt_sha256": H}
            for m, s in (("TWSE", "2330"), ("TPEX", "6488"))}


def assess(rs=None, cs=None, cal=None):
    return assess_pit_model(trading_date=T, rows=rows() if rs is None else rs,
                            coverage=coverage() if cs is None else cs,
                            calendars=calendar() if cal is None else cal)


class P0V2OfflineTests(unittest.TestCase):
    def blocked(self, reason, fn, *args, **kwargs):
        with self.assertRaises(V2Blocked) as error:
            fn(*args, **kwargs)
        self.assertEqual(str(error.exception), reason)

    def test_date_mismatch_preserved_without_authority(self):
        result = receipt()
        self.assertEqual(result["source_update_date_raw"], "2026/11/20")
        self.assertEqual(result["source_update_date_parsed"], "2026-11-20")
        self.assertEqual(result["date_relation"], "DIFFERENT_NOMINAL_DATE")
        self.assertEqual(result["source_valid_for_trading_date"], "NOT_ESTABLISHED")
        self.assertEqual(result["production_credit"], 0)

    def test_date_equal_still_not_authoritative(self):
        result = receipt(source_update_date_raw="2026/11/23")
        self.assertEqual(result["date_relation"], "EQUAL_NOMINAL_DATE")
        self.assertEqual(result["date_semantics_authority"], "UNQUALIFIED")

    def test_raw_bytes_content_digest(self):
        result = receipt()
        self.assertEqual(result["response_bytes"], len(b"offline-fixture"))
        self.assertEqual(len(result["raw_body_sha256"]), 64)
        self.assertNotEqual(result["raw_body_sha256"], result["candidate_receipt_sha256"])

    def test_http_partial_rejected(self):
        self.blocked("V2_SOURCE_BYTES_INCOMPLETE", receipt, content_length=200)

    def test_unapproved_redirect_rejected(self):
        self.blocked("V2_SOURCE_TRANSPORT_UNQUALIFIED", receipt,
                     final_url="https://example.com")

    def test_invalid_endpoint_rejected(self):
        self.blocked("V2_SOURCE_ENDPOINT_NOT_ALLOWLISTED", receipt,
                     endpoint="https://example.com")

    def test_failed_http_rejected(self):
        self.blocked("V2_SOURCE_TRANSPORT_UNQUALIFIED", receipt, http_status=503)

    def test_fallback_rejected(self):
        self.blocked("V2_SOURCE_TRANSPORT_UNQUALIFIED", receipt, fallback_used=True)

    def test_naive_observation_rejected(self):
        self.blocked("V2_OBSERVATION_UTC_REQUIRED", receipt,
                     observed_at_utc="2026-11-23T01:20:00")

    def test_future_source_update_date_rejected(self):
        self.blocked("V2_SOURCE_UPDATE_DATE_FUTURE_TO_OBSERVATION", receipt,
                     source_update_date_raw="2026/12/01")

    def test_missing_classification_date_rejected(self):
        self.blocked("V2_CLASSIFICATION_UPDATE_DATE_MISSING", receipt,
                     source_update_date_raw=None)

    def test_closed_exchange_holiday_fixture_rejected(self):
        cal = calendar()
        cal["TWSE"]["status"] = "CLOSED"
        self.blocked("V2_TRADING_DAY_CLOSED", assess_calendar_fixture, T, cal)

    def test_unknown_calendar_rejected(self):
        cal = calendar()
        cal["TPEX"]["status"] = "UNKNOWN"
        self.blocked("V2_CALENDAR_UNKNOWN", assess_calendar_fixture, T, cal)

    def test_calendar_market_coverage_rejected(self):
        cal = calendar()
        del cal["TPEX"]
        self.blocked("V2_CALENDAR_COVERAGE_MISSING", assess_calendar_fixture, T, cal)

    def test_synthetic_pit_model_never_qualifies_official_history(self):
        result = assess()
        self.assertEqual(result["structural_model_status"], "PASS_OFFLINE_FIXTURE")
        self.assertEqual(result["pit_coverage_status"], "BLOCKED_PIT_HISTORY_GAP")
        self.assertFalse(result["full_market_coverage_qualified"])
        self.assertEqual(result["production_permit"], "NOT_ISSUED")
        self.assertEqual(result["cer081_credit"], 0)

    def test_missing_history_rejected(self):
        c = coverage()
        c["TPEX"]["model_history_complete"] = False
        self.blocked("BLOCKED_PIT_HISTORY_GAP", assess, cs=c)

    def test_missing_exchange_coverage_rejected(self):
        c = coverage()
        del c["TPEX"]
        self.blocked("BLOCKED_PIT_HISTORY_GAP", assess, cs=c)

    def test_missing_effective_date_rejected(self):
        r = rows()
        r[0]["effective_from"] = None
        self.blocked("BLOCKED_PIT_HISTORY_GAP", assess, rs=r)

    def test_delisted_before_target_rejected(self):
        r = rows()
        r[0]["effective_to_exclusive"] = "2026-10-01"
        self.blocked("PIT_EFFECTIVE_INTERVAL_MISMATCH", assess, rs=r)

    def test_cross_market_duplicate_symbol_rejected(self):
        r = rows()
        r[1]["symbol"] = r[0]["symbol"]
        self.blocked("PIT_CROSS_MARKET_DUPLICATE", assess, rs=r)

    def test_wrong_market_transfer_mapping_rejected(self):
        r = rows()
        r[1]["market"] = "TWSE"
        self.blocked("PIT_LISTING_MARKET_MISMATCH", assess, rs=r)

    def test_unknown_cfi_rejected(self):
        r = rows()
        r[0]["cfi_code"] = ""
        self.blocked("PIT_CFI_UNKNOWN", assess, rs=r)

    def test_noncommon_cfi_cannot_claim_eligible(self):
        r = rows()
        r[0]["cfi_code"] = "CEOIES"
        self.blocked("PIT_ELIGIBILITY_CONFLICT", assess, rs=r)

    def test_noncommon_cfi_excluded_with_marker(self):
        r = rows()
        r[0]["cfi_code"] = "CEOIES"
        r[0]["eligible"] = False
        result = assess(rs=r)
        self.assertEqual(result["eligible_fixture_symbols"], [("TPEX", "6488")])
        self.assertEqual(result["pit_coverage_status"], "BLOCKED_PIT_HISTORY_GAP")

    def test_suspension_not_automatically_delisting(self):
        r = rows()
        r[0]["lifecycle"] = "SUSPENDED"
        result = assess(rs=r)
        self.assertIn(("TWSE", "2330"), result["suspended_not_automatically_delisted"])

    def test_terminated_symbol_cannot_claim_eligible(self):
        r = rows()
        r[0]["lifecycle"] = "TERMINATED"
        self.blocked("PIT_ELIGIBILITY_CONFLICT", assess, rs=r)

    def test_missing_event_id_rejected(self):
        r = rows()
        r[0]["source_event_id"] = ""
        self.blocked("BLOCKED_PIT_HISTORY_GAP", assess, rs=r)

    def test_incomplete_universe_rejected(self):
        c = coverage()
        c["TWSE"]["expected_symbols"].append("2317")
        self.blocked("BLOCKED_PIT_HISTORY_GAP", assess, cs=c)

    def test_snapshot_never_backfills_history(self):
        self.blocked("BLOCKED_PIT_HISTORY_GAP", assess_forward_snapshot,
                     snapshot_date=T, observed_at_utc="2026-11-23T01:20:00Z",
                     claimed_trading_date="2026-11-20", sha256=H)

    def test_same_day_snapshot_only_observed(self):
        result = assess_forward_snapshot(snapshot_date=T,
                                         observed_at_utc="2026-11-23T01:20:00Z",
                                         claimed_trading_date=T, sha256=H)
        self.assertEqual(result["pit_coverage_status"], "BLOCKED_PIT_HISTORY_GAP")
        self.assertEqual(result["production_permit"], "NOT_ISSUED")

    def test_snapshot_date_forgery_rejected(self):
        self.blocked("PIT_SNAPSHOT_DATE_UNATTESTED", assess_forward_snapshot,
                     snapshot_date="2026-11-22", observed_at_utc="2026-11-23T01:20:00Z",
                     claimed_trading_date=T, sha256=H)


    def test_incomplete_es_cfi_rejected(self):
        for code in ("ES", "ESV", "ESVU", "ESVUF"):
            with self.subTest(code=code):
                r = rows()
                r[0]["cfi_code"] = code
                self.blocked("PIT_CFI_UNKNOWN", assess, rs=r)

    def test_overlength_es_cfi_rejected(self):
        r = rows()
        r[0]["cfi_code"] = "ESVUFRX"
        self.blocked("PIT_CFI_UNKNOWN", assess, rs=r)

    def test_lowercase_cfi_rejected(self):
        for code in ("esvufr", "EsVUFR"):
            with self.subTest(code=code):
                r = rows()
                r[0]["cfi_code"] = code
                self.blocked("PIT_CFI_UNKNOWN", assess, rs=r)

    def test_numeric_cfi_rejected(self):
        r = rows()
        r[0]["cfi_code"] = "ESVU1R"
        self.blocked("PIT_CFI_UNKNOWN", assess, rs=r)

    def test_whitespace_cfi_rejected(self):
        for code in ("ESVUF ", " ESVUF", "ESVUFR "):
            with self.subTest(code=code):
                r = rows()
                r[0]["cfi_code"] = code
                self.blocked("PIT_CFI_UNKNOWN", assess, rs=r)

    def test_unicode_cfi_lookalike_rejected(self):
        r = rows()
        r[0]["cfi_code"] = "ESＶUFR"
        self.blocked("PIT_CFI_UNKNOWN", assess, rs=r)

    def test_unknown_cfi_group_rejected(self):
        for code in ("QQQQQQ", "EXVUFR", "EPVUFR"):
            with self.subTest(code=code):
                r = rows()
                r[0]["cfi_code"] = code
                self.blocked("PIT_CFI_GROUP_UNQUALIFIED", assess, rs=r)

    def test_unknown_es_attribute_positions_rejected(self):
        for code in ("ESQUFR", "ESVQFR", "ESVUQR", "ESVUFQ", "ESXUFR", "ESZZZZ"):
            with self.subTest(code=code):
                r = rows()
                r[0]["cfi_code"] = code
                self.blocked("PIT_CFI_ATTRIBUTE_UNQUALIFIED", assess, rs=r)

    def test_invalid_etf_cfi_attributes_rejected(self):
        r = rows()
        r[1]["cfi_code"] = "CEVUFR"
        self.blocked("PIT_CFI_ATTRIBUTE_UNQUALIFIED", assess, rs=r)

    def test_valid_noncommon_fixture_cannot_claim_common(self):
        r = rows()
        r[1]["cfi_code"] = "CEOIES"
        r[1]["eligible"] = True
        self.blocked("PIT_ELIGIBILITY_CONFLICT", assess, rs=r)

    def test_valid_full_es_variants_still_not_authority(self):
        for code in ("ESVUFR", "ESVUFB", "ESNUFR", "ESRTOR"):
            with self.subTest(code=code):
                r = rows()
                r[0]["cfi_code"] = code
                result = assess(rs=r)
                self.assertIn(("TWSE", "2330"), result["eligible_fixture_symbols"])
                self.assertEqual(result["historical_source_authority"], "UNVERIFIED")
                self.assertEqual(result["pit_coverage_status"], "BLOCKED_PIT_HISTORY_GAP")
                self.assertEqual(result["production_permit"], "NOT_ISSUED")

    def test_valid_noncommon_fixture_excluded_not_qualified(self):
        r = rows()
        r[1]["cfi_code"] = "CEOIES"
        r[1]["eligible"] = False
        result = assess(rs=r)
        self.assertEqual(result["eligible_fixture_symbols"], [("TWSE", "2330")])
        self.assertFalse(result["full_market_coverage_qualified"])
        self.assertEqual(result["pit_coverage_status"], "BLOCKED_PIT_HISTORY_GAP")
        self.assertEqual(result["production_credit"], 0)


if __name__ == "__main__":
    unittest.main()
