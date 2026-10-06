"""ENGINEERING-only history fixtures, never MAIN warmup acceptance evidence."""
import copy
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from src import full_market_history as h
from src.full_market_catalogue import build_catalogue, CLASSIFICATION_ENDPOINTS, LISTING_ENDPOINTS
from src.institutional_history import T86_OFFICIAL_SOURCE, TPEX_OFFICIAL_SOURCE
from src.cer080_multi_day_continuity import is_trading_day
from src.sources.tdcc_historical import TDCC_HISTORICAL_PAGE, holder_pct_400_from_tiers

BASE = "233d87333d4d1b8a1f0cb788635a0bb7662fd4c8"
RUN1_ALLOWED_CHANGES = {"scripts/bootstrap_full_market_history.py", "src/sources/fundamental_history.py",
                        "tests/test_full_market_history.py", "tests/test_full_market_history_storage.py",
                        ".github/workflows/rate_full_market_history_ci.yml"}
DAY = "2026-10-06"
AUTHORITY = {"ref": "refs/heads/main", "event": "workflow_dispatch", "run_id": "100", "commit_sha": "a" * 40}
AUTHORITY["github_execution_evidence"] = {"run_id": "100", "head_sha": "a" * 40, "head_branch": "main",
    "event": "workflow_dispatch", "workflow_path": ".github/workflows/rate_full_market_history_bootstrap.yml", "run_attempt": "1"}


def cfg():
    value = json.loads(h.CONTRACT.read_bytes())
    value["expected_market_counts"] = {"TWSE": 20, "TPEX": 20}
    value["symbols_per_shard"] = 10
    return value


def catalogue():
    header = ["Security Code & Security Name", "ISIN Code", "Date Listed", "Market", "Industrial Group", "CFICode", "Remarks"]
    def fetch(endpoint, html=False):
        market = next(m for m in ("TWSE", "TPEX") if endpoint in (CLASSIFICATION_ENDPOINTS[m], LISTING_ENDPOINTS[m]))
        symbols = [str(1000 + i) for i in range(40) if (i % 2 == 0) == (market == "TWSE")]
        if html:
            rows = [header, ["Stocks"]] + [[s + " Engineering", "ISIN" + s, "2000/01/01", "TWSE LISTED" if market == "TWSE" else "TPEx LISTED", "", "ESVUFR", ""] for s in symbols]
            body = ("Date Stock Updated:" + DAY.replace("-", "/") + "<table>" + "".join("<tr>" + "".join("<td>" + c.replace("&", "&amp;") + "</td>" for c in row) + "</tr>" for row in rows) + "</table>").encode("big5")
        else:
            key = "\u516c\u53f8\u4ee3\u865f" if market == "TWSE" else "SecuritiesCompanyCode"
            body = json.dumps([{key: s} for s in symbols]).encode()
        return body, {"endpoint": endpoint, "http_status": 200, "response_bytes": len(body), "body_sha256": hashlib.sha256(body).hexdigest(), "retrieved_at": "2026-10-06T01:00:00Z", "fallback_used": False}
    return build_catalogue(DAY, fetcher=fetch)


def plan():
    return h.build_plan(catalogue(), AUTHORITY)


def receipt(endpoint):
    return {"endpoint": endpoint, "content_hash": "c" * 64,
            "retrieved_at": datetime.now(timezone.utc).isoformat(), "parse_status": "PASS"}


def material(plan, symbol="1000", market="TWSE"):
    index = int(symbol) - 1000
    last = date.fromisoformat(plan["completed_through"])
    dates = []
    cursor = last
    while len(dates) < 180:
        if is_trading_day(cursor.isoformat()):
            dates.append(cursor.isoformat())
        cursor -= timedelta(days=1)
    dates.reverse()
    stamp = datetime.now(timezone.utc).isoformat()
    stocks = [{"symbol": symbol, "market": market, "trade_date": day, "open": 80 + .2 * i + .02 * index,
               "high": 81 + .2 * i + .02 * index, "low": 79 + .2 * i + .02 * index, "close": 80 + .2 * i + .02 * index,
               "volume": 100 + i * 2 + index, "turnover": (100 + i * 2 + index) * (80 + .2 * i + .02 * index),
               "source": market + "_STOCK_DAY", "source_timestamp": stamp, "ingested_at": stamp} for i, day in enumerate(dates)]
    bench = [{"market": market, "benchmark_symbol": "TAIEX" if market == "TWSE" else "TPEX", "trade_date": day,
              "close": 100 + .01 * i, "source": market + "_BENCHMARK_HISTORY", "source_timestamp": stamp, "ingested_at": stamp} for i, day in enumerate(dates)]
    institutional = [{"symbol": symbol, "trading_date": r["trade_date"], "close": r["close"], "turnover": r["turnover"],
                      "foreign_net_shares": index + 1, "investment_trust_net_shares": index + 2, "source_timestamp": stamp,
                      "official_source": T86_OFFICIAL_SOURCE if market == "TWSE" else TPEX_OFFICIAL_SOURCE} for r in stocks[-26:]]
    tdcc = []
    for offset in reversed(range(8)):
        period = (last - timedelta(days=3 + offset * 7)).isoformat()
        tiers = [{"symbol": symbol, "period_end": period, "holding_range": i, "holder_count": 10,
                  "shares": 100, "holder_percentage": 5.0, "source": TDCC_HISTORICAL_PAGE,
                  "response_sha256": "c" * 64, "retrieval_timestamp": stamp} for i in range(1, 16)]
        tdcc.append({"period_end": period, "holder_pct_400": holder_pct_400_from_tiers(tiers), "raw_lineage": tiers,
                     "source": "TDCC Official Historical Query", "source_timestamp": period, "retrieval_timestamp": stamp})
    meta = {"symbol": symbol, "market": market, "provider": "MOPS Official", "official_product": "ENGINEERING_FIXTURE_ONLY",
            "source_semantics": "OFFICIAL_SINGLE_QUARTER", "official_disclosure_date": "2026-09-01",
            "endpoint": "https://mopsov.twse.com.tw/mops/web/ajax_t163sb04", "content_hash": "c" * 64, "retrieval_timestamp": stamp}
    fundamental = {"revenue": [{**meta, "revenue_period": month, "revenue_yoy": index + 1} for month in ("2026-06", "2026-07", "2026-08")],
                   "eps": [{**meta, "fiscal_year": n // 4, "quarter": n % 4 + 1, "single_quarter_eps": 1.0} for n in range(2026 * 4 + 1 - 7, 2026 * 4 + 2)]}
    market_endpoint = "https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY" if market == "TWSE" else "https://www.tpex.org.tw/www/en-us/afterTrading/tradingStock"
    receipts = {d: [receipt(market_endpoint)] for d in ("stock", "benchmark", "institutional")}
    receipts.update(tdcc=[receipt(TDCC_HISTORICAL_PAGE)], fundamental=[receipt(meta["endpoint"])])
    return {"artifact": "RATE_FULL_MARKET_SYMBOL_HISTORY", "plan_id": plan["plan_id"], "symbol": symbol, "market": market,
            "acquisition_runtime_authority": AUTHORITY,
            "as_of": plan["as_of"], "stock": stocks, "benchmark": bench, "institutional": institutional,
            "tdcc": tdcc, "fundamental": fundamental, "source_receipts": receipts, "fallback_used": False}


class FullMarketHistoryTests(unittest.TestCase):
    def setUp(self):
        self.patch = patch("src.full_market_history.contract", side_effect=cfg)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.tmp = tempfile.TemporaryDirectory(prefix="rate-history-engineering-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.plan = plan()
        self.material = material(self.plan)

    def test_eligibility_and_shards_are_complete_deterministic_and_not_seed(self):
        self.assertEqual(h.build_plan(self.plan["catalogue"], AUTHORITY), self.plan)
        self.assertTrue(h.validate_plan(self.plan))
        assigned = [s for shard in self.plan["shards"] for s in shard["symbols"]]
        self.assertEqual(len(assigned), 40)
        self.assertEqual(len(assigned), len(set(assigned)))
        self.assertTrue(all(len(s["symbols"]) == 10 for s in self.plan["shards"]))

    def test_real_contract_requires_exact_1978_counts_no_shrink(self):
        self.patch.stop()
        self.assertEqual(h.contract()["expected_market_counts"], {"TWSE": 1085, "TPEX": 893})
        with self.assertRaisesRegex(RuntimeError, "CATALOGUE_COUNT_CHANGE_REQUEST_REQUIRED"):
            h.eligible(self.plan["catalogue"])

    def test_main_files_outside_run1_defect_scope_are_byte_identical(self):
        names = subprocess.check_output(["git", "-C", str(h.ROOT), "ls-tree", "-r", "--name-only", BASE]).decode().splitlines()
        for name in names:
            if name in RUN1_ALLOWED_CHANGES:
                continue
            self.assertEqual((h.ROOT / name).read_bytes(), subprocess.check_output(["git", "-C", str(h.ROOT), "show", BASE + ":" + name]), name)
        expected = os.getenv("RATE_WARMUP_CI_HEAD_SHA")
        if expected:
            self.assertEqual(subprocess.check_output(["git", "-C", str(h.ROOT), "rev-parse", "HEAD"]).decode().strip(), expected)

    def test_valid_all_domains(self):
        value = h.validate_symbol(self.material, self.plan, "1000", "TWSE")
        self.assertEqual(value["stock_sessions"], 180)
        self.assertEqual(value["institutional_sessions"], 26)

    def test_weekend_cannot_count_as_completed_official_session(self):
        value = copy.deepcopy(self.material)
        value["stock"][-2]["trade_date"] = "2026-10-04"
        with self.assertRaisesRegex(RuntimeError, "NON_TRADING_HISTORY_SESSION"):
            h.validate_symbol(value, self.plan, "1000", "TWSE")

    def test_missing_history_domains_and_minimums_fail_closed(self):
        for domain in h.DOMAINS:
            wrong = copy.deepcopy(self.material)
            del wrong[domain]
            with self.subTest(domain=domain), self.assertRaises((RuntimeError, KeyError)):
                h.validate_symbol(wrong, self.plan, "1000", "TWSE")
        for domain in ("stock", "benchmark", "institutional"):
            wrong = copy.deepcopy(self.material)
            wrong[domain] = wrong[domain][1:]
            with self.subTest(domain=domain), self.assertRaisesRegex(RuntimeError, "HISTORICAL_WARMUP_REQUIRED"):
                h.validate_symbol(wrong, self.plan, "1000", "TWSE")

    def test_stale_future_duplicate_market_and_fallback_rejected(self):
        for change in ("stale", "future", "duplicate", "market", "fallback", "provider", "nan", "tdcc", "eps"):
            wrong = copy.deepcopy(self.material)
            if change == "stale": wrong["stock"] = wrong["stock"][:-1] + [{**wrong["stock"][-1], "trade_date": "2026-10-04"}]
            if change == "future": wrong["stock"][-1]["trade_date"] = "2026-10-07"
            if change == "duplicate": wrong["stock"][1]["trade_date"] = wrong["stock"][0]["trade_date"]
            if change == "market": wrong["benchmark"][0]["benchmark_symbol"] = "TPEX"
            if change == "fallback": wrong["fallback_used"] = True
            if change == "provider": wrong["source_receipts"]["stock"][0]["endpoint"] = "https://example.com/history"
            if change == "nan": wrong["stock"][0]["close"] = float("nan")
            if change == "tdcc": wrong["tdcc"][0]["holder_pct_400"] += 1
            if change == "eps": wrong["fundamental"]["eps"] = wrong["fundamental"]["eps"][:7]
            with self.subTest(change=change), self.assertRaises((RuntimeError, ValueError)):
                h.validate_symbol(wrong, self.plan, "1000", "TWSE")

    def test_resume_idempotency_and_corrupt_saved_material_no_reacquire(self):
        first = h.persist_symbol(self.root, self.material, self.plan, "1000", "TWSE")
        before = {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        second = h.persist_symbol(self.root, self.material, self.plan, "1000", "TWSE")
        self.assertEqual(first, second)
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()})
        self.assertEqual(h.load_checkpoint(self.root, self.plan, "1000", "TWSE")[0], self.material)
        h.safe_path(self.root, first["material"]["path"]).write_bytes(b"corrupt")
        with self.assertRaisesRegex(RuntimeError, "HISTORY_MATERIAL_HASH_MISMATCH"):
            h.load_checkpoint(self.root, self.plan, "1000", "TWSE")

    def test_immutable_conflict_and_path_escape_fail_closed(self):
        h.persist_symbol(self.root, self.material, self.plan, "1000", "TWSE")
        wrong = copy.deepcopy(self.material)
        wrong["stock"][0]["open"] += .1
        with self.assertRaisesRegex(RuntimeError, "IMMUTABLE_HISTORY_CONFLICT"):
            h.persist_symbol(self.root, wrong, self.plan, "1000", "TWSE")
        for path in ("../state.json", "/tmp/state.json", "materials/../../LATEST.json"):
            with self.subTest(path=path), self.assertRaises(RuntimeError):
                h.put_json(self.root, path, {})

    def test_partial_coverage_never_creates_pass_snapshot(self):
        h.persist_symbol(self.root, self.material, self.plan, "1000", "TWSE")
        result = h.aggregate(self.root, self.plan)
        self.assertEqual(result["validation_status"], "FAIL_CLOSED")
        self.assertEqual(len(result["missing_symbols"]), 39)
        self.assertFalse((self.root / "snapshots").exists())

    def test_stale_completed_and_future_receipt_have_exact_blockers(self):
        stale = copy.deepcopy(self.material)
        for row in stale["stock"]:
            previous = date.fromisoformat(row["trade_date"]) - timedelta(days=1)
            while not is_trading_day(previous.isoformat()):
                previous -= timedelta(days=1)
            row["trade_date"] = previous.isoformat()
        with self.assertRaisesRegex(RuntimeError, "STALE_HISTORY"):
            h.validate_symbol(stale, self.plan, "1000", "TWSE")
        future = copy.deepcopy(self.material)
        future["source_receipts"]["stock"][0]["retrieved_at"] = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        with self.assertRaisesRegex(RuntimeError, "SOURCE_FUTURE_DATED"):
            h.validate_symbol(future, self.plan, "1000", "TWSE")

    def test_wrong_official_market_receipt_and_parse_fail_rejected(self):
        for change in ("market", "parse", "hash"):
            wrong = copy.deepcopy(self.material)
            r = wrong["source_receipts"]["stock"][0]
            if change == "market": r["endpoint"] = "https://www.tpex.org.tw/history"
            if change == "parse": r["parse_status"] = "FAIL"
            if change == "hash": r["content_hash"] = "missing"
            with self.subTest(change=change), self.assertRaises(RuntimeError):
                h.validate_symbol(wrong, self.plan, "1000", "TWSE")

    def test_symbol_acquisition_must_bind_its_own_main_runtime(self):
        wrong = copy.deepcopy(self.material)
        wrong["acquisition_runtime_authority"]["ref"] = "refs/pull/25/head"
        with self.assertRaisesRegex(RuntimeError, "WARMUP_MAIN_AUTHORITY_REQUIRED"):
            h.validate_symbol(wrong, self.plan, "1000", "TWSE")

    def test_stage_replay_failure_never_creates_snapshot(self):
        for row in h.eligible(self.plan["catalogue"]):
            h.persist_symbol(self.root, material(self.plan, row["symbol"], row["market"]), self.plan, row["symbol"], row["market"])
        with patch("src.stage_history.build_stage_feature_histories", side_effect=ValueError("STAGE_INPUTS_INCOMPLETE")) as owner:
            with self.assertRaisesRegex(ValueError, "STAGE_INPUTS_INCOMPLETE"):
                h.aggregate(self.root, self.plan)
            self.assertEqual(len(owner.call_args.args[0]), 40)
        self.assertFalse((self.root / "snapshots").exists())

    def test_full_cross_section_stage_replay_snapshot_and_reload(self):
        for row in h.eligible(self.plan["catalogue"]):
            h.persist_symbol(self.root, material(self.plan, row["symbol"], row["market"]), self.plan, row["symbol"], row["market"])
        result = h.aggregate(self.root, self.plan)
        self.assertEqual(result["validation_status"], "PASS")
        self.assertEqual(result["stage_replay_coverage"], "40/40")
        self.assertEqual(result["minimum_stock_sessions"], 180)
        before = {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(h.reload_snapshot(self.root, self.plan, result["snapshot_id"]), result)
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()})
        manifest = h.safe_path(self.root, result["manifest"]["path"])
        value = json.loads(manifest.read_bytes())
        value["shards"] = value["shards"][:-1]
        manifest.write_bytes(h.encoded(value))
        with self.assertRaisesRegex(RuntimeError, "HISTORY_MANIFEST_HASH_MISMATCH"):
            h.reload_snapshot(self.root, self.plan, result["snapshot_id"])
        self.assertFalse((h.ROOT / "data/production/full_market_history").exists())

    def test_catalogue_plan_owner_tamper_and_non_main_fail_closed(self):
        for key in ("policy_hash", "catalogue_sha256", "owner_hashes", "shards"):
            wrong = copy.deepcopy(self.plan)
            wrong[key] = "INVALID"
            with self.subTest(key=key), self.assertRaises(RuntimeError): h.validate_plan(wrong)
        for authority in ({**AUTHORITY, "ref": "refs/pull/25/head"}, {**AUTHORITY, "event": "pull_request"}):
            with self.assertRaisesRegex(RuntimeError, "WARMUP_MAIN_AUTHORITY_REQUIRED"):
                h.build_plan(self.plan["catalogue"], authority)


if __name__ == "__main__":
    unittest.main()
