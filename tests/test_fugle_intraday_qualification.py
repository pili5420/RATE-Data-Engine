"""Synthetic-only tests for Fugle free/basic intraday feasibility."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts import run_fugle_intraday_qualification as cli
from src.authorized_intraday_feed import load_authoritative_universe_binding
from src.provider_fugle_intraday_candidate import (
    API_HOST,
    FugleDiagnosticError,
    load_binding,
    qualify,
)

NOW = datetime(2026, 11, 3, 1, 30, 30, tzinfo=timezone.utc)
DATE = "2026-11-03"
ROOT = Path(__file__).resolve().parents[1]
BINDING_FILE = ROOT / "docs" / "contracts" / "RATE_FUGLE_FREE_INTRADAY_UNIVERSE_BINDING_V1.json"


def approved_universe():
    trusted, _ = load_authoritative_universe_binding()
    return trusted


def binding():
    return json.loads(BINDING_FILE.read_text(encoding="utf-8"))


def quote(symbol, market, stamp=1793669400000000):
    return {
        "symbol": symbol,
        "exchange": market,
        "date": DATE,
        "lastUpdated": stamp,
        "lastPrice": 100.0,
        "total": {"tradeVolume": 1000, "tradeValue": 100000.0},
        "lastTrade": {"price": 100.0},
    }


class FakeResponse:
    def __init__(self, status, value=None):
        self.status = status
        self.value = value

    def read(self):
        if self.value is None:
            return b""
        return json.dumps(self.value).encode("utf-8")


class Connection:
    def __init__(self, owner, host, timeout):
        self.owner = owner
        self.host = host
        self.timeout = timeout
        self.request_entry = None
        self.closed = False

    def request(self, method, path, headers):
        self.request_entry = {
            "host": self.host,
            "method": method,
            "path": path,
            "headers": dict(headers),
        }
        self.owner.requests.append(self.request_entry)

    def getresponse(self):
        entry = self.request_entry
        if self.owner.status != 200:
            return FakeResponse(self.owner.status)
        symbol = entry["path"].rsplit("/", 1)[-1]
        market = self.owner.markets[symbol]
        stamp = self.owner.stamp
        if self.owner.wrong_market_symbol == symbol:
            market = "TPEX" if market == "TWSE" else "TWSE"
        return FakeResponse(200, quote(symbol, market, stamp))

    def close(self):
        self.closed = True


class ConnectionFactory:
    def __init__(self, *, status=200, stamp=1793669400000000, wrong_market_symbol=None):
        self.status = status
        self.stamp = stamp
        self.wrong_market_symbol = wrong_market_symbol
        self.markets = approved_universe()
        self.connections = []
        self.requests = []

    def __call__(self, host, timeout=10):
        connection = Connection(self, host, timeout)
        self.connections.append(connection)
        return connection


class FugleFreeDiagnosticTests(unittest.TestCase):
    def test_fixed_binding_matches_authoritative_rate_universe(self):
        expected, lineage = load_binding(binding())
        trusted, trusted_lineage = load_authoritative_universe_binding()
        self.assertEqual(expected, trusted)
        self.assertEqual(lineage["production_snapshot_id"], trusted_lineage["production_snapshot_id"])
        self.assertEqual(lineage["source_bundle_sha256"], trusted_lineage["source_bundle_sha256"])
        self.assertEqual(lineage["universe_contract_sha256"], trusted_lineage["universe_contract_sha256"])
        self.assertEqual(lineage["universe_binding_hash"], trusted_lineage["universe_binding_hash"])
        self.assertEqual(list(expected.values()).count("TWSE"), 25)
        self.assertEqual(list(expected.values()).count("TPEX"), 5)

    def test_substitute_25_plus_5_binding_fails_before_network(self):
        bad = binding()
        row = deepcopy(bad["records"][0])
        original_symbol = row["symbol"]
        replacement = "9999"
        row["symbol"] = replacement
        bad["records"][0] = row
        self.assertNotEqual(original_symbol, replacement)
        factory = ConnectionFactory()
        with self.assertRaisesRegex(FugleDiagnosticError, "BINDING_NOT_APPROVED"):
            qualify(
                "SECRET",
                bad,
                trading_date=DATE,
                cadence="09:30",
                now_utc=NOW,
                connection_factory=factory,
            )
        self.assertEqual(factory.requests, [])
        self.assertEqual(factory.connections, [])

    def test_exact_30_dual_market_pass_uses_exactly_30_http_requests(self):
        factory = ConnectionFactory()
        result = qualify(
            "SECRET",
            binding(),
            trading_date=DATE,
            cadence="09:30",
            now_utc=NOW,
            connection_factory=factory,
        )
        self.assertEqual(result["technical_validation_status"], "PASS")
        self.assertEqual(result["market_coverage"], "30/30")
        self.assertEqual(result["market_counts"], {"TWSE": 25, "TPEX": 5})
        self.assertEqual(result["network_requests"], 30)
        self.assertEqual(result["http_redirects_followed"], 0)
        self.assertEqual(result["automatic_retries"], 0)
        self.assertEqual(len(factory.requests), 30)
        self.assertEqual(len(factory.connections), 30)
        self.assertTrue(all(item["host"] == API_HOST for item in factory.requests))
        self.assertTrue(all(item["method"] == "GET" for item in factory.requests))
        self.assertTrue(all(item["headers"]["X-API-KEY"] == "SECRET" for item in factory.requests))
        self.assertTrue(all(connection.closed for connection in factory.connections))
        self.assertFalse(result["production_eligible"])
        self.assertFalse(result["external_dependency_resolved"])
        self.assertNotIn("SECRET", json.dumps(result))

    def test_redirect_fails_closed_after_one_request_and_never_forwards_key(self):
        factory = ConnectionFactory(status=302)
        with self.assertRaisesRegex(FugleDiagnosticError, "REDIRECT_FORBIDDEN"):
            qualify(
                "SECRET",
                binding(),
                trading_date=DATE,
                cadence="09:30",
                now_utc=NOW,
                connection_factory=factory,
            )
        self.assertEqual(len(factory.requests), 1)
        self.assertEqual(len(factory.connections), 1)
        self.assertEqual(factory.requests[0]["host"], API_HOST)
        self.assertEqual(factory.requests[0]["headers"]["X-API-KEY"], "SECRET")
        self.assertTrue(factory.connections[0].closed)

    def test_free_plan_403_and_rate_limit_429_fail_closed_without_retry(self):
        for status, reason in ((403, "FREE_PLAN_NOT_AUTHORIZED"), (429, "FREE_PLAN_RATE_LIMIT")):
            factory = ConnectionFactory(status=status)
            with self.subTest(status=status), self.assertRaisesRegex(FugleDiagnosticError, reason):
                qualify(
                    "x",
                    binding(),
                    trading_date=DATE,
                    cadence="09:30",
                    now_utc=NOW,
                    connection_factory=factory,
                )
            self.assertEqual(len(factory.requests), 1)
            self.assertEqual(len(factory.connections), 1)

    def test_missing_token_fails_before_network(self):
        factory = ConnectionFactory()
        with self.assertRaisesRegex(FugleDiagnosticError, "API_KEY_MISSING"):
            qualify(
                "",
                binding(),
                trading_date=DATE,
                cadence="09:30",
                now_utc=NOW,
                connection_factory=factory,
            )
        self.assertEqual(factory.requests, [])
        self.assertEqual(factory.connections, [])

    def test_market_mismatch_and_freshness_fail_closed(self):
        expected = approved_universe()
        wrong_symbol = next(iter(expected))
        wrong = ConnectionFactory(wrong_market_symbol=wrong_symbol)
        with self.assertRaisesRegex(FugleDiagnosticError, "MARKET_MISMATCH"):
            qualify(
                "x",
                binding(),
                trading_date=DATE,
                cadence="09:30",
                now_utc=NOW,
                connection_factory=wrong,
            )
        stale = ConnectionFactory(stamp=1793668800000000)
        with self.assertRaisesRegex(FugleDiagnosticError, "FRESHNESS_FAIL"):
            qualify(
                "x",
                binding(),
                trading_date=DATE,
                cadence="09:30",
                now_utc=NOW,
                connection_factory=stale,
            )

    def test_cli_removed_runtime_binding_override(self):
        with patch.object(sys, "argv", [
            "run_fugle_intraday_qualification.py",
            "--binding", "other.json",
            "--trading-date", DATE,
            "--cadence", "09:30",
            "--output-name", "result.json",
        ]), patch.object(cli, "qualify") as qualify_mock:
            with self.assertRaises(SystemExit):
                cli.main()
            qualify_mock.assert_not_called()

    def test_output_path_traversal_is_rejected_before_binding_or_network(self):
        with patch.object(sys, "argv", [
            "run_fugle_intraday_qualification.py",
            "--trading-date", DATE,
            "--cadence", "09:30",
            "--output-name", "../artifacts/production.json",
        ]), patch.object(cli, "_load_fixed_binding") as binding_mock, patch.object(cli, "qualify") as qualify_mock:
            with self.assertRaisesRegex(RuntimeError, "OUTPUT_PATH_FORBIDDEN"):
                cli.main()
            binding_mock.assert_not_called()
            qualify_mock.assert_not_called()

    def test_existing_output_is_rejected_before_binding_or_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_root = Path(tmp) / "diagnostic"
            output_root.mkdir()
            (output_root / "result.json").write_text("{}\n", encoding="utf-8")
            with patch.object(cli, "OUTPUT_ROOT", output_root), patch.object(sys, "argv", [
                "run_fugle_intraday_qualification.py",
                "--trading-date", DATE,
                "--cadence", "09:30",
                "--output-name", "result.json",
            ]), patch.object(cli, "_load_fixed_binding") as binding_mock, patch.object(cli, "qualify") as qualify_mock:
                with self.assertRaisesRegex(RuntimeError, "OUTPUT_EXISTS"):
                    cli.main()
                binding_mock.assert_not_called()
                qualify_mock.assert_not_called()

    def test_result_writer_is_exclusive_create_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_root = Path(tmp) / "diagnostic"
            with patch.object(cli, "OUTPUT_ROOT", output_root):
                target = cli._safe_output_path("result.json")
                cli._write_new_result(target, {"artifact": "TEST"})
                self.assertTrue(target.is_file())
                with self.assertRaises(FileExistsError):
                    cli._write_new_result(target, {"artifact": "OVERWRITE"})
                self.assertEqual(json.loads(target.read_text(encoding="utf-8"))["artifact"], "TEST")


if __name__ == "__main__":
    unittest.main()
