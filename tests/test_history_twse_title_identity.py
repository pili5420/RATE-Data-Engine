"""SYNTHETIC ONLY. No saved market response or prices belong in public CI."""
from copy import deepcopy
import hashlib
import json
import unittest

from scripts.verify_ci_applicability import network_guard
import sys
sys.addaudithook(network_guard)
from src import history_acquisition_execution as h
from src.history_acquisition_validation import parse_history

TITLE = "115\u5e7409\u6708 1101 \u53f0\u6ce5             \u5404\u65e5\u6210\u4ea4\u8cc7\u8a0a"
MISSING = object()


def stock_payload():
    return {"stat": "OK", "date": "20260901", "title": TITLE,
        "fields": ["Date", "OpeningPrice", "HighestPrice", "LowestPrice", "ClosingPrice", "TradeVolume", "TradeValue"],
        "data": [["115/09/01", "10", "12", "9", "11", "100", "1000"]]}


class TWSETitleIdentityTests(unittest.TestCase):
    def setUp(self):
        self.entry = h.request_entry({"market": "TWSE", "product": "stock", "symbol": "1101", "period": "202609"}, 3)

    def parse(self, payload=None, *, entry=None, observed_at="2026-10-14T01:39:29.775868Z", cutoff="2026-10-12"):
        return parse_history(h.evidence.canonical(stock_payload() if payload is None else payload), entry or self.entry,
                             observed_at=observed_at, cutoff=cutoff)

    def test_exact_title_identity_and_period_pass(self):
        result = self.parse()
        self.assertEqual(result["source_validation"], "PASS")
        self.assertEqual(result["total_rows"], 1)
        self.assertEqual(result["normalized_sessions"][0]["symbol"], "1101")
        self.assertEqual(result["dates"], ["2026-09-01"])

    def test_company_name_is_not_identity_proof(self):
        value = stock_payload()
        value["title"] = TITLE.replace("\u53f0\u6ce5", "\u6e2c\u8a66\u516c\u53f8")
        self.assertEqual(self.parse(value)["source_validation"], "PASS")
        value["title"] = value["title"].replace("1101", "1102")
        with self.assertRaisesRegex(ValueError, "HISTORY_SYMBOL_MISMATCH"):
            self.parse(value)

    def test_ascii_name_padding_not_normalized(self):
        for padding in (" ", " " * 13):
            with self.subTest(padding=len(padding)):
                value = stock_payload()
                value["title"] = TITLE.replace(" " * 13, padding)
                self.assertEqual(self.parse(value)["records"][0]["raw_fields"]["Date"], "115/09/01")
                self.assertEqual(value["title"], TITLE.replace(" " * 13, padding))

    def test_explicit_correct_identity_remains_highest_priority(self):
        for key in ("code", "stockNo", "symbol"):
            with self.subTest(field=key):
                value = stock_payload()
                value[key] = "1101"
                value["title"] = "not an accepted title"
                self.assertEqual(self.parse(value)["source_validation"], "PASS")

    def test_explicit_wrong_stockno_not_overridden_by_title(self):
        value = stock_payload()
        value["stockNo"] = "1102"
        with self.assertRaisesRegex(ValueError, "HISTORY_SYMBOL_MISMATCH"):
            self.parse(value)

    def test_explicit_wrong_code_or_symbol_not_overridden(self):
        for key in ("code", "symbol"):
            with self.subTest(field=key):
                value = stock_payload()
                value[key] = "1102"
                with self.assertRaisesRegex(ValueError, "HISTORY_SYMBOL_MISMATCH"):
                    self.parse(value)

    def test_conflicting_explicit_identities_still_rejected(self):
        value = stock_payload()
        value.update(code="1102", stockNo="1101", symbol="1101")
        with self.assertRaisesRegex(ValueError, "HISTORY_SYMBOL_MISMATCH"):
            self.parse(value)

    def test_correct_title_does_not_replace_row_period_validation(self):
        value = stock_payload()
        value["data"][0][0] = "115/08/31"
        with self.assertRaisesRegex(ValueError, "HISTORY_PERIOD_MISMATCH"):
            self.parse(value)

    def test_duplicate_session_gate_unchanged(self):
        value = stock_payload()
        value["data"].append(deepcopy(value["data"][0]))
        with self.assertRaisesRegex(ValueError, "HISTORY_DUPLICATE_SESSION"):
            self.parse(value)

    def test_future_session_gate_unchanged(self):
        value = stock_payload()
        value["title"] = TITLE.replace("09", "10", 1)
        value["data"][0][0] = "115/10/15"
        entry = h.request_entry({"market": "TWSE", "product": "stock", "symbol": "1101", "period": "202610"}, 3)
        with self.assertRaisesRegex(ValueError, "HISTORY_FUTURE_SESSION"):
            self.parse(value, entry=entry, cutoff="2026-10-14")

    def test_schema_gate_unchanged(self):
        value = stock_payload()
        value["data"][0].pop()
        with self.assertRaisesRegex(ValueError, "HISTORY_ROW_WIDTH_INVALID"):
            self.parse(value)

    def test_numeric_and_ohlc_gates_unchanged(self):
        for close, reason in (("-1", "HISTORY_NUMERIC_RANGE_INVALID"), ("NaN", "HISTORY_NUMERIC_INVALID"),
                              (True, "HISTORY_NUMERIC_INVALID"), ("20", "HISTORY_OHLC_INVALID")):
            with self.subTest(close=close):
                value = stock_payload()
                value["data"][0][4] = close
                with self.assertRaisesRegex(ValueError, reason):
                    self.parse(value)

    def test_twenty_rows_no_loss_order_and_locators_preserved(self):
        value = stock_payload()
        value["data"] = [[f"115/09/{day:02}", "10", "12", "9", "11", "100", "1000"] for day in range(1, 21)]
        result = self.parse(value)
        self.assertEqual((result["total_rows"], result["valid_rows"], len(result["normalized_sessions"])), (20, 20, 20))
        self.assertEqual([row["json_locator"] for row in result["records"]], [f"$.data[{n}]" for n in range(20)])
        self.assertEqual([row["raw_fields"]["Date"] for row in result["records"]], [row[0] for row in value["data"]])

    def test_raw_and_receipt_bytes_unchanged(self):
        value = stock_payload()
        before = deepcopy(value)
        raw = h.evidence.canonical(value)
        receipt = b'{"material_scope":"SYNTHETIC_ONLY","http_status":200}'
        hashes = hashlib.sha256(raw).hexdigest(), hashlib.sha256(receipt).hexdigest()
        parse_history(raw, self.entry, observed_at="2026-10-14T01:39:29Z", cutoff="2026-10-12")
        self.assertEqual(value, before)
        self.assertEqual((hashlib.sha256(raw).hexdigest(), hashlib.sha256(receipt).hexdigest()), hashes)

    def test_zero_volume_and_turnover_preserved(self):
        value = stock_payload()
        value["data"][0][-2:] = ["0", "0"]
        row = self.parse(value)["normalized_sessions"][0]
        self.assertEqual((row["volume"], row["turnover"]), (0, 0))

    def test_tpex_subtitle_fallback_unchanged(self):
        entry = h.request_entry({"market": "TPEX", "product": "stock", "symbol": "1240", "period": "202609"}, 4)
        value = {"tables": [{"subtitle": "1240 synthetic", "fields": ["Date", "Open", "High", "Low", "Close", "Trade unit", "Trade Amt.(NTD1000)"],
            "data": [["115/09/01", "10", "12", "9", "11", "100", "1000"]]}]}
        self.assertEqual(self.parse(value, entry=entry)["source_validation"], "PASS")
        self.assertEqual(self.parse(value, entry=entry)["unit_scale_status"], "TPEX_UNIT_SCALE_QUALIFICATION_REQUIRED")
        value["tables"][0]["subtitle"] = "12400 synthetic"
        with self.assertRaisesRegex(ValueError, "HISTORY_SYMBOL_IDENTITY_REQUIRED"):
            self.parse(value, entry=entry)

    def test_tpex_does_not_gain_twse_title_fallback(self):
        entry = h.request_entry({"market": "TPEX", "product": "stock", "symbol": "1240", "period": "202609"}, 4)
        value = {"title": TITLE.replace("1101", "1240"), "tables": [{"fields": ["Date", "Close"], "data": [["115/09/01", "11"]]}]}
        with self.assertRaisesRegex(ValueError, "HISTORY_SYMBOL_IDENTITY_REQUIRED"):
            self.parse(value, entry=entry)

    def test_twse_does_not_gain_tpex_subtitle_fallback(self):
        value = stock_payload()
        del value["title"]
        value["subtitle"] = "1101 synthetic"
        with self.assertRaisesRegex(ValueError, "HISTORY_SYMBOL_IDENTITY_REQUIRED"):
            self.parse(value)

    def test_benchmark_behavior_unchanged_for_both_markets(self):
        for market in ("TWSE", "TPEX"):
            with self.subTest(market=market):
                entry = h.request_entry({"market": market, "product": "benchmark", "symbol": None, "period": "202609"}, 1)
                value = {"title": "not a stock title", "fields": ["Date", "Close"], "data": [["115/09/01", "100"]]}
                self.assertEqual(self.parse(value, entry=entry)["source_validation"], "PASS")
                value["stockNo"] = "1101"
                with self.assertRaisesRegex(ValueError, "HISTORY_PRODUCT_MISMATCH"):
                    self.parse(value, entry=entry)


BAD_TITLES = {
    "wrong_symbol": (TITLE.replace("1101", "1102"), "HISTORY_SYMBOL_MISMATCH"),
    "missing": (MISSING, "HISTORY_SYMBOL_IDENTITY_REQUIRED"),
    "null": (None, "HISTORY_SYMBOL_IDENTITY_REQUIRED"),
    "number": (1101, "HISTORY_SYMBOL_IDENTITY_REQUIRED"),
    "bool": (True, "HISTORY_SYMBOL_IDENTITY_REQUIRED"),
    "empty": ("", "HISTORY_SYMBOL_IDENTITY_REQUIRED"),
    "whitespace": ("   ", "HISTORY_SYMBOL_IDENTITY_REQUIRED"),
    "superset": (TITLE.replace("1101", "11010"), "HISTORY_SYMBOL_IDENTITY_REQUIRED"),
    "prefixed": (TITLE.replace("1101", "A1101"), "HISTORY_SYMBOL_IDENTITY_REQUIRED"),
    "suffixed": (TITLE.replace("1101", "1101A"), "HISTORY_SYMBOL_IDENTITY_REQUIRED"),
    "arbitrary_contains": ("source 1101 synthetic", "HISTORY_SYMBOL_IDENTITY_REQUIRED"),
    "leading_space": (" " + TITLE, "HISTORY_SYMBOL_IDENTITY_REQUIRED"),
    "trailing_space": (TITLE + " ", "HISTORY_SYMBOL_IDENTITY_REQUIRED"),
    "newline": (TITLE + "\n", "HISTORY_SYMBOL_IDENTITY_REQUIRED"),
    "tab_separator": (TITLE.replace(" 1101 ", "\t1101 "), "HISTORY_SYMBOL_IDENTITY_REQUIRED"),
    "fullwidth_symbol": (TITLE.replace("1101", "\uff11\uff11\uff10\uff11"), "HISTORY_SYMBOL_IDENTITY_REQUIRED"),
    "repeated_codes": (TITLE.replace("1101 ", "1101 1102 "), "HISTORY_SYMBOL_IDENTITY_REQUIRED"),
    "missing_company": (TITLE.replace("\u53f0\u6ce5", ""), "HISTORY_SYMBOL_IDENTITY_REQUIRED"),
    "unsupported_company_form": (TITLE.replace("\u53f0\u6ce5", "SYNTHETIC"), "HISTORY_SYMBOL_IDENTITY_REQUIRED"),
    "missing_suffix": (TITLE[:-1], "HISTORY_SYMBOL_IDENTITY_REQUIRED"),
    "malformed_month": (TITLE.replace("09", "9", 1), "HISTORY_SYMBOL_IDENTITY_REQUIRED"),
    "wrong_title_month": (TITLE.replace("09", "08", 1), "HISTORY_PERIOD_MISMATCH"),
    "wrong_title_year": (TITLE.replace("115", "114", 1), "HISTORY_PERIOD_MISMATCH"),
    "issuer_at_start_wrong_form": ("1101 " + TITLE, "HISTORY_SYMBOL_IDENTITY_REQUIRED"),
}


def negative_title(title, reason):
    def test(self):
        value = stock_payload()
        if title is MISSING:
            del value["title"]
        else:
            value["title"] = title
        with self.assertRaisesRegex(ValueError, reason):
            self.parse(value)
    return test


for name, (title, reason) in BAD_TITLES.items():
    setattr(TWSETitleIdentityTests, "test_bad_title_" + name, negative_title(title, reason))


if __name__ == "__main__":
    unittest.main()
