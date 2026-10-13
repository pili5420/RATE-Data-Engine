"""Synthetic-only regression for RATE-MD-DISCOVERY-TWSE-ENDPOINT-BINDING-001."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src import session_discovery_execution as m
from src.sources import twse, tpex
from src.public_official_partial_valid import validate_rows
from tests.test_session_discovery_execution import response, synthetic_authorization, MAIN, UTC

OLD_AUTH = "rate-session-discovery-authorization-33907c82d5ad7e117bd7440fdfe65061015432e68604b7f432d4f3ea1b270835"
OLD_URLS = ("https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX",
            "https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY_ALL")


def failed_shape():
    # Structure modeled from the local captured defect; NOT the captured raw bytes.
    tables = [{} for _ in range(10)]
    tables[6] = {"title": "SYNTHETIC_ONLY", "fields": ["成交統計", "成交金額(元)", "成交股數(股)", "成交筆數"],
                 "data": [["SYNTHETIC_CATEGORY", "0", "0", "0"]]}
    return {"stat": "OK", "date": "20261013", "type": "MS", "tables": tables}


class BindingFixTests(unittest.TestCase):
    def parse(self, payload, ordinal=1):
        return m.response_session(m.canonical(payload), m.targets()[ordinal - 1], UTC)

    def test_benchmark_matches_actual_formal_adapter(self):
        with patch.object(twse, "fetch_json", return_value=([], "synthetic-sha")) as fetch:
            owner = twse.TWSEAdapter().fetch_benchmark()
        self.assertEqual(m.targets()[0]["endpoint"], owner["endpoint"])
        self.assertEqual(fetch.call_args.args[0], m.targets()[0]["endpoint"])

    def test_market_matches_actual_formal_adapter(self):
        with patch.object(twse, "fetch_json", return_value=([], "synthetic-sha")) as fetch:
            owner = twse.TWSEAdapter().fetch_daily()
        self.assertEqual(m.targets()[1]["endpoint"], owner["endpoint"])
        self.assertEqual(fetch.call_args.args[0], m.targets()[1]["endpoint"])

    def test_all_four_owner_matches(self):
        expected = [twse.BASE + "/exchangeReport/MI_INDEX", twse.BASE + "/exchangeReport/STOCK_DAY_ALL",
                    tpex.BENCHMARK_ENDPOINT, tpex.CURRENT_DAILY_ENDPOINT]
        self.assertEqual([e["endpoint"] for e in m.targets()], expected)
        registry = json.loads((m.ROOT / "config/RATE_PRODUCTION_OFFICIAL_SOURCE_REGISTRY_V1.json").read_bytes())
        registry = {e["dataset_id"]: e["endpoint"] for e in registry["datasets"]}
        for index, name in ((0, "twse_benchmark"), (1, "twse_market_daily"), (3, "tpex_market_daily")):
            self.assertEqual(m.targets()[index]["endpoint"], registry[name])

    def test_old_routes_absent(self):
        self.assertFalse(set(OLD_URLS) & {e["endpoint"] for e in m.targets()})
        self.assertTrue(all("/rwd/zh/afterTrading/" not in e["endpoint"] for e in m.targets()))

    def test_twse_base_is_derived_not_duplicate_literal(self):
        with patch.object(m, "TWSE_BASE", "https://synthetic.invalid/formal-owner"):
            self.assertEqual(m.targets()[0]["endpoint"], "https://synthetic.invalid/formal-owner/exchangeReport/MI_INDEX")
            self.assertEqual(m.targets()[1]["endpoint"], "https://synthetic.invalid/formal-owner/exchangeReport/STOCK_DAY_ALL")

    def test_english_benchmark_matches_existing_owner_contract(self):
        payload = [{"Date": "20261012", "IndexName": "SYNTHETIC_INDEX", "ClosingIndex": "100"}]
        formal = validate_rows(payload, {"domain": "benchmark"}, "2026-10-13")
        parsed = self.parse(payload)
        self.assertEqual(parsed["latest_session"], formal[0]["publication_or_source_date"])
        self.assertEqual(parsed["json_locators"], [r["json_locator"] for r in formal])

    def test_chinese_benchmark_matches_existing_owner_contract(self):
        payload = [{"日期": "1151012", "指數": "SYNTHETIC_INDEX", "收盤指數": "100"}]
        formal = validate_rows(payload, {"domain": "benchmark"}, "2026-10-13")
        self.assertEqual(self.parse(payload)["latest_session"], formal[0]["publication_or_source_date"])

    def test_daily_matches_existing_owner_fields(self):
        payload = [{"Date": "1151012", "Code": "SYNTHETIC", "ClosingPrice": "10", "TradeVolume": "100"}]
        formal = validate_rows(payload, {"domain": "market_daily"}, "2026-10-13")
        normalized = twse.TWSEAdapter.normalize_daily(payload[0])
        self.assertEqual(normalized["symbol"], payload[0]["Code"])
        self.assertEqual(normalized["trade_date"], payload[0]["Date"])
        self.assertEqual(self.parse(payload, 2)["latest_session"], formal[0]["publication_or_source_date"])

    def test_captured_failure_structure_is_not_openapi_benchmark(self):
        payload = failed_shape()
        self.assertEqual(payload["type"], "MS")
        self.assertEqual(len(payload["tables"]), 10)
        with self.assertRaisesRegex(Exception, "DISCOVERY_SCHEMA_INVALID"):
            self.parse(payload)

    def test_rwd_market_table_is_also_rejected(self):
        with self.assertRaisesRegex(Exception, "DISCOVERY_SCHEMA_INVALID"):
            self.parse({"stat": "OK", "date": "20261012", "fields": ["證券代號", "收盤價"], "data": [["SYN", "1"]]}, 2)

    def test_daily_not_benchmark(self):
        with self.assertRaisesRegex(Exception, "DISCOVERY_SCHEMA_INVALID"):
            self.parse([{"Date": "20261012", "Code": "SYN", "ClosingPrice": "1"}])

    def test_benchmark_not_daily(self):
        with self.assertRaisesRegex(Exception, "DISCOVERY_SCHEMA_INVALID"):
            self.parse([{"日期": "20261012", "指數": "SYN", "收盤指數": "1"}], 2)

    def test_missing_date_rejected(self):
        with self.assertRaisesRegex(Exception, "DISCOVERY_SCHEMA_INVALID"):
            self.parse([{"指數": "SYN", "收盤指數": "1"}])

    def test_conflicting_date_aliases_rejected(self):
        with self.assertRaisesRegex(Exception, "DISCOVERY_SESSION_IDENTITY_INVALID"):
            self.parse([{"Date": "20261012", "日期": "20261009", "指數": "SYN", "收盤指數": "1"}])

    def test_equivalent_date_aliases_accepted(self):
        self.assertEqual(self.parse([{"Date": "20261012", "日期": "1151012", "指數": "SYN", "收盤指數": "1"}])["latest_session"], "2026-10-12")

    def test_mixed_sessions_fail_closed(self):
        with self.assertRaisesRegex(Exception, "DISCOVERY_SESSION_IDENTITY_INVALID"):
            self.parse([{"日期": "1151012", "指數": "SYN1", "收盤指數": "1"},
                        {"日期": "1151009", "指數": "SYN2", "收盤指數": "1"}])

    def test_duplicate_issuer_or_index_rejected_not_dropped(self):
        for ordinal in (1, 2):
            row = json.loads(response(m.targets()[ordinal - 1])["raw_bytes"])[0]
            with self.subTest(ordinal=ordinal), self.assertRaisesRegex(Exception, "DISCOVERY_SCHEMA_INVALID"):
                self.parse([row, row], ordinal)

    def test_invalid_close_uses_frozen_owner_numeric_gate(self):
        for value in (True, "NaN", "Infinity", "not-numeric", "-1"):
            with self.subTest(value=value), self.assertRaisesRegex(Exception, "DISCOVERY_SCHEMA_INVALID"):
                self.parse([{"日期": "1151012", "指數": "SYN", "收盤指數": value}])

    def test_official_missing_daily_close_retained_no_fill(self):
        payload = [{"Date": "20261012", "Code": "SYN1", "ClosingPrice": " ---"},
                   {"Date": "20261012", "Code": "SYN2", "ClosingPrice": None}]
        before = deepcopy(payload)
        parsed = self.parse(payload, 2)
        self.assertEqual(parsed["row_count"], 2)
        self.assertEqual(payload, before)

    def test_all_raw_indices_preserved_not_index_filtered(self):
        payload = [{"日期": "1151012", "指數": "SYN1", "收盤指數": "1"},
                   {"日期": "1151012", "指數": "SYN2", "收盤指數": "2"}]
        parsed = self.parse(payload)
        self.assertEqual(parsed["row_count"], len(payload))
        self.assertEqual(parsed["json_locators"], ["$[0]", "$[1]"])

    def test_input_bytes_unchanged(self):
        body = response(m.targets()[0])["raw_bytes"]
        original = m.sha(body)
        m.response_session(body, m.targets()[0], UTC)
        self.assertEqual(m.sha(body), original)

    def test_old_plan_rejected_before_claim_even_with_recomputed_digest(self):
        plan = m.build_plan(MAIN)
        core = {k: deepcopy(v) for k, v in plan.items() if k not in ("plan_id", "plan_sha256")}
        for n, endpoint in enumerate(OLD_URLS):
            core["entries"][n]["endpoint"] = endpoint
        stale = m.identified(core, "rate-session-discovery-plan-", "plan_id", "plan_sha256")
        with self.assertRaisesRegex(Exception, "DISCOVERY_PLAN_MISMATCH"):
            m.validate_plan(stale)

    def test_consumed_old_authorization_cannot_be_rebound_or_deleted(self):
        with tempfile.TemporaryDirectory(prefix="discovery-binding-synthetic-") as tmp:
            root = Path(tmp)
            artifacts, claims = root / "discovery", root / "claims"
            claims.mkdir()
            record = claims / (OLD_AUTH + ".json")
            record.write_bytes(m.canonical({"authorization_id": OLD_AUTH, "status": "CONSUMED", "scope": "SYNTHETIC_ONLY"}))
            before = record.read_bytes()
            plan = m.build_plan(MAIN)
            seal = m.build_seal(plan, artifacts, claims)
            invalid = synthetic_authorization(seal)
            invalid["authorization_id"] = OLD_AUTH
            with patch.object(m, "main_guard"), self.assertRaises(Exception):
                m.preflight(plan, seal, invalid, artifacts_root=artifacts, consumption_root=claims)
            self.assertEqual(record.read_bytes(), before)
            self.assertFalse(artifacts.exists())

    def test_governance_limits_unchanged(self):
        plan = m.build_plan(MAIN)
        self.assertEqual((plan["planned_requests"], plan["maximum_requests"]), (4, 4))
        self.assertTrue(plan["sequential"] and plan["single_writer"])
        self.assertFalse(plan["auto_resume"] or plan["token_required"])
        for entry in plan["entries"]:
            self.assertEqual((entry["retry"], entry["timeout"], entry["minimum_interval_seconds"]), (0, 30, 13))
            self.assertIs(entry["fallback"], False)
            self.assertIs(entry["redirect"], False)
            self.assertEqual(entry["credentials"], "NONE")


if __name__ == "__main__":
    unittest.main()
