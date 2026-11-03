"""Synthetic tests for provider-neutral authorized intraday payload qualification."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import unittest

from src.authorized_intraday_feed import IntradayQualificationError, qualify_authorized_intraday_payload

NOW = datetime(2026, 11, 2, 1, 30, 30, tzinfo=timezone.utc)
TRADING_DATE = "2026-11-02"
CADENCE = "09:30"


def universe():
    values = {}
    for index in range(25):
        values[str(1000 + index)] = "TWSE"
    for index in range(5):
        values[str(2000 + index)] = "TPEX"
    return values


def payload():
    rows = []
    for symbol, market in universe().items():
        rows.append({
            "symbol": symbol,
            "market": market,
            "timestamp": "2026-11-02T09:30:00+08:00",
            "price": 100.0,
            "volume": 1000,
            "turnover": 100000.0,
        })
    return {
        "artifact": "RATE_AUTHORIZED_TAIWAN_INTRADAY_FEED_V1",
        "authorization_status": "PASS",
        "validation_status": "PASS",
        "provider_authority": "SYNTHETIC_AUTHORIZED_PROVIDER_FIXTURE",
        "license_scope": {"automated_production_use": True, "markets": ["TWSE", "TPEX"]},
        "trading_date": TRADING_DATE,
        "cadence": CADENCE,
        "fallback_used": False,
        "records": rows,
    }


class AuthorizedIntradayPayloadTests(unittest.TestCase):
    def qualify(self, value=None, expected=None, **kwargs):
        return qualify_authorized_intraday_payload(
            value or payload(),
            expected_universe=expected or universe(),
            trading_date=kwargs.pop("trading_date", TRADING_DATE),
            cadence=kwargs.pop("cadence", CADENCE),
            now_utc=kwargs.pop("now_utc", NOW),
            **kwargs,
        )

    def test_dual_market_30_of_30_passes_contract_only(self):
        result = self.qualify()
        self.assertEqual(result["validation_status"], "PASS")
        self.assertEqual(result["coverage"], "30/30")
        self.assertEqual(result["selected_market_counts"], {"TWSE": 25, "TPEX": 5})
        self.assertFalse(result["production_eligible"])
        self.assertFalse(result["registry_activated"])
        self.assertEqual(result["network_requests"], 0)

    def test_extra_raw_symbol_allowed_but_not_selected(self):
        value = payload()
        value["records"].append({
            "symbol": "9999", "market": "TWSE", "timestamp": "2026-11-02T09:30:00+08:00",
            "price": 1.0, "volume": 0, "turnover": 0,
        })
        result = self.qualify(value)
        self.assertEqual(result["coverage"], "30/30")
        self.assertEqual(result["extra_raw_symbols"], ["9999"])

    def test_missing_expected_symbol_fails_closed(self):
        value = payload()
        value["records"] = [r for r in value["records"] if r["symbol"] != "2004"]
        with self.assertRaisesRegex(IntradayQualificationError, "EXPECTED_SYMBOL_MISSING"):
            self.qualify(value)

    def test_market_mismatch_fails_closed(self):
        value = payload()
        next(r for r in value["records"] if r["symbol"] == "2000")["market"] = "TWSE"
        with self.assertRaisesRegex(IntradayQualificationError, "MARKET_BINDING_MISMATCH"):
            self.qualify(value)

    def test_duplicate_symbol_fails_closed(self):
        value = payload()
        value["records"].append(deepcopy(value["records"][0]))
        with self.assertRaisesRegex(IntradayQualificationError, "DUPLICATE_SYMBOL"):
            self.qualify(value)

    def test_explicit_timezone_is_required(self):
        value = payload()
        value["records"][0]["timestamp"] = "2026-11-02T09:30:00"
        with self.assertRaisesRegex(IntradayQualificationError, "TIMEZONE_REQUIRED"):
            self.qualify(value)

    def test_stale_and_future_quotes_fail_closed(self):
        stale = payload()
        stale["records"][0]["timestamp"] = "2026-11-02T09:20:00+08:00"
        with self.assertRaisesRegex(IntradayQualificationError, "FRESHNESS_FAIL"):
            self.qualify(stale)
        future = payload()
        future["records"][0]["timestamp"] = "2026-11-02T09:31:00+08:00"
        with self.assertRaisesRegex(IntradayQualificationError, "FRESHNESS_FAIL"):
            self.qualify(future)

    def test_trading_date_and_cadence_are_exactly_bound(self):
        value = payload()
        with self.assertRaisesRegex(IntradayQualificationError, "SCOPE_BINDING_MISMATCH"):
            self.qualify(value, trading_date="2026-11-03")
        with self.assertRaisesRegex(IntradayQualificationError, "CADENCE_INVALID"):
            self.qualify(value, cadence="19:30")

    def test_fallback_or_missing_authorization_fails_closed(self):
        value = payload(); value["fallback_used"] = True
        with self.assertRaisesRegex(IntradayQualificationError, "FALLBACK_FORBIDDEN"):
            self.qualify(value)
        value = payload(); value["authorization_status"] = "BLOCKED_EXTERNAL"
        with self.assertRaisesRegex(IntradayQualificationError, "AUTHORIZATION_NOT_PASS"):
            self.qualify(value)

    def test_license_must_cover_both_markets_for_automated_use(self):
        value = payload(); value["license_scope"]["markets"] = ["TWSE"]
        with self.assertRaisesRegex(IntradayQualificationError, "LICENSE_MARKET_COVERAGE_INCOMPLETE"):
            self.qualify(value)
        value = payload(); value["license_scope"]["automated_production_use"] = False
        with self.assertRaisesRegex(IntradayQualificationError, "AUTOMATED_USE_AUTHORITY_REQUIRED"):
            self.qualify(value)

    def test_expected_universe_must_be_exact_30_and_dual_market(self):
        one_market = {str(1000 + i): "TWSE" for i in range(30)}
        with self.assertRaisesRegex(IntradayQualificationError, "DUAL_MARKET_COVERAGE_REQUIRED"):
            self.qualify(expected=one_market)
        short = dict(list(universe().items())[:-1])
        with self.assertRaisesRegex(IntradayQualificationError, "COUNT_INVALID"):
            self.qualify(expected=short)

    def test_numeric_validation_is_fail_closed(self):
        for field, value in (("price", 0), ("volume", -1), ("turnover", float("nan"))):
            bad = payload()
            bad["records"][0][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(IntradayQualificationError, "NUMERIC_INVALID"):
                self.qualify(bad)


if __name__ == "__main__":
    unittest.main()
