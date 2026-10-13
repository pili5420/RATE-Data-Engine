"""SYNTHETIC ONLY: captured TPEx keys, not captured prices or HTTP bytes."""
from copy import deepcopy
import unittest

from src import session_discovery_execution as m
from src.benchmark_history import normalize_benchmark
from tests.test_session_discovery_execution import Fixture, response, UTC


def captured_style():
    # Eight arbitrary synthetic dates; not a trading-calendar qualification.
    dates = ("20261001", "20261002", "20261005", "20261006", "20261007", "20261008", "20261009", "20261012")
    return [{"Date": day, "Open": "100", "High": "102", "Low": "99", "Close": "101", "Change": "1"}
            for day in dates]


class TPEXSchemaTests(unittest.TestCase):
    def parse(self, rows, observed=UTC):
        return m.response_session(m.canonical(rows), m.targets()[2], observed)

    def test_close_captured_style_eight_rows(self):
        rows = captured_style()
        self.assertEqual(set(rows[0]), {"Date", "Open", "High", "Low", "Close", "Change"})
        parsed = self.parse(rows)
        self.assertEqual(parsed["validation"], "PASS")
        self.assertEqual(parsed["row_count"], 8)
        self.assertEqual(parsed["json_locators"], [f"$[{i}]" for i in range(8)])
        self.assertEqual(parsed["latest_session"], "2026-10-12")

    def test_unchanged_formal_owner_accepts_all_eight_close_fields(self):
        rows = captured_style()
        normalized = [normalize_benchmark(row, benchmark_symbol="SYNTHETIC_TPEX", market="TPEX",
                      source="SYNTHETIC_ONLY", source_timestamp=UTC, ingested_at=UTC) for row in rows]
        self.assertEqual(len(normalized), 8)
        self.assertEqual([r["close"] for r in normalized], [float(r["Close"]) for r in rows])
        self.assertEqual(self.parse(rows)["recognized_dates"], sorted(r["trade_date"] for r in normalized))

    def test_all_existing_aliases_unchanged(self):
        for alias in ("ClosingIndex", "收市", "收盤指數", "收盤價", "close"):
            with self.subTest(alias=alias):
                self.assertEqual(self.parse([{"Date": "20261012", alias: "100"}])["row_count"], 1)

    def test_unsupported_close_aliases_fail_closed(self):
        for alias in ("CLOSE", "Close ", " Close", "CloseChange", "ClosingPrice", "closingIndex"):
            with self.subTest(alias=alias), self.assertRaisesRegex(Exception, "DISCOVERY_SCHEMA_INVALID"):
                self.parse([{"Date": "20261012", alias: "100"}])

    def test_missing_close_schema_rejected(self):
        row = captured_style()[0]
        del row["Close"]
        with self.assertRaisesRegex(Exception, "DISCOVERY_SCHEMA_INVALID"):
            self.parse([row])

    def test_missing_date_schema_rejected(self):
        row = captured_style()[0]
        del row["Date"]
        with self.assertRaisesRegex(Exception, "DISCOVERY_SCHEMA_INVALID"):
            self.parse([row])

    def test_empty_payload_rejected(self):
        with self.assertRaisesRegex(Exception, "DISCOVERY_SCHEMA_INVALID"):
            self.parse([])

    def test_nonlist_payload_rejected(self):
        for payload in ({"data": captured_style()}, captured_style()[0], None):
            with self.subTest(payload=payload), self.assertRaisesRegex(Exception, "DISCOVERY_SCHEMA_INVALID"):
                self.parse(payload)

    def test_nonobject_row_rejected(self):
        with self.assertRaisesRegex(Exception, "DISCOVERY_SCHEMA_INVALID"):
            self.parse([captured_style()[0], ["20261012", "101"]])

    def test_invalid_date_rejected(self):
        for value in (None, 20261012, "not-a-date", "20261301"):
            with self.subTest(value=value), self.assertRaises(Exception):
                self.parse([{"Date": value, "Close": "101"}])

    def test_future_date_rejected(self):
        with self.assertRaisesRegex(Exception, "DISCOVERY_FUTURE_SESSION"):
            self.parse([{"Date": "20991012", "Close": "101"}])

    def test_preclose_session_rejected(self):
        with self.assertRaisesRegex(Exception, "DISCOVERY_PRE_CLOSE_SESSION"):
            self.parse(captured_style(), "2026-10-12T05:00:00Z")

    def test_malformed_json_rejected(self):
        with self.assertRaises(Exception):
            m.response_session(b'[{"Date":', m.targets()[2], UTC)

    def test_duplicate_json_keys_rejected(self):
        with self.assertRaises(Exception):
            m.response_session(b'[{"Date":"20261012","Close":"1","Close":"2"}]', m.targets()[2], UTC)

    def test_nonfinite_json_rejected(self):
        for value in ("NaN", "Infinity", "-Infinity", "1e999"):
            with self.subTest(value=value), self.assertRaises(Exception):
                m.response_session(('[{"Date":"20261012","Close":' + value + '}]').encode(), m.targets()[2], UTC)

    def test_input_values_and_bytes_unchanged(self):
        rows = captured_style()
        before = deepcopy(rows)
        body = m.canonical(rows)
        digest = m.sha(body)
        self.parse(rows)
        self.assertEqual(rows, before)
        self.assertEqual(m.sha(body), digest)

    def test_all_row_positions_retained_in_original_order(self):
        rows = list(reversed(captured_style()))
        parsed = self.parse(rows)
        self.assertEqual(parsed["row_count"], 8)
        self.assertEqual(parsed["json_locators"], [f"$[{i}]" for i in range(8)])
        self.assertEqual(parsed["recognized_dates"], self.parse(captured_style())["recognized_dates"])

    def test_tpex_daily_both_existing_aliases_unchanged(self):
        entry = m.targets()[3]
        for alias in ("Close", "ClosingPrice"):
            row = {"Date": "20261012", "SecuritiesCompanyCode": "SYNTHETIC_ONLY", alias: " ---"}
            parsed = m.response_session(m.canonical([row]), entry, UTC)
            self.assertEqual(parsed, {"latest_session": "2026-10-12", "recognized_dates": ["2026-10-12"],
                "row_count": 1, "json_locators": ["$[0]"], "validation": "PASS",
                "scope": "SESSION_DISCOVERY_ONLY_NOT_180_SESSION_CALENDAR"})

    def test_tpex_daily_issuer_identity_still_required(self):
        with self.assertRaisesRegex(Exception, "DISCOVERY_SCHEMA_INVALID"):
            m.response_session(m.canonical(captured_style()), m.targets()[3], UTC)

    def test_twse_benchmark_unchanged(self):
        entry = m.targets()[0]
        parsed = m.response_session(response(entry)["raw_bytes"], entry, UTC)
        self.assertEqual(parsed["latest_session"], "2026-10-12")
        self.assertEqual(parsed["row_count"], 1)
        self.assertEqual(parsed["json_locators"], ["$[0]"])

    def test_twse_daily_unchanged_no_close_alias_expansion(self):
        entry = m.targets()[1]
        self.assertEqual(m.response_session(response(entry)["raw_bytes"], entry, UTC)["row_count"], 1)
        with self.assertRaisesRegex(Exception, "DISCOVERY_SCHEMA_INVALID"):
            m.response_session(m.canonical([{"Date": "20261012", "Code": "SYN", "Close": "101"}]), entry, UTC)

    def test_routes_and_frozen_policies_unchanged(self):
        self.assertEqual([e["endpoint"] for e in m.targets()], [m.TWSE_BASE + "/exchangeReport/MI_INDEX",
            m.TWSE_BASE + "/exchangeReport/STOCK_DAY_ALL", m.BENCHMARK_ENDPOINT, m.CURRENT_DAILY_ENDPOINT])
        for entry in m.targets():
            self.assertEqual((entry["retry"], entry["timeout"], entry["minimum_interval_seconds"]), (0, 30, 13))
            self.assertFalse(entry["fallback"] or entry["redirect"])


class TPEXLifecycleTests(Fixture):
    def test_mock_execution_accepts_eight_rows_and_replays_disk(self):
        def capture(entry):
            result = self.capture(entry)
            if entry["ordinal"] == 3:
                result["raw_bytes"] = m.canonical(captured_style())
            return result
        result = self.execute(capture)
        self.assertEqual((result["status"], result["actual_requests"], result["completed_checkpoints"]), ("PASS", 4, 4))
        self.assertEqual(self.replay(), result)
        event = m.read_metadata((self.output / "events/03.json").read_bytes())
        self.assertEqual(event["source_validation"]["row_count"], 8)
        self.assertEqual(event["source_validation"]["json_locators"], [f"$[{i}]" for i in range(8)])
        self.assertEqual([e["ordinal"] for e in self.calls], [1, 2, 3, 4])

    def test_unsupported_third_schema_stops_without_fourth_dispatch(self):
        def capture(entry):
            result = self.capture(entry)
            if entry["ordinal"] == 3:
                result["raw_bytes"] = m.canonical([{"Date": "20261012", "CLOSE": "101"}])
            return result
        result = self.execute(capture)
        self.assertEqual((result["status"], result["actual_requests"], result["completed_checkpoints"]), ("STOPPED", 3, 2))
        self.assertEqual([e["ordinal"] for e in self.calls], [1, 2, 3])
        stop = m.read_metadata((self.output / "STOP.json").read_bytes())
        self.assertEqual(stop["reason"], "DISCOVERY_SCHEMA_INVALID")
        self.assertEqual(stop["authorization_status"], "CONSUMED")
        self.assertIs(stop["auto_resume"], False)
        self.assertEqual(result, self.replay())
        with self.assertRaisesRegex(Exception, "AUTHORIZATION_ALREADY_CONSUMED"):
            self.execute(output_root=self.artifacts / "forbidden-reuse")


if __name__ == "__main__":
    unittest.main()
