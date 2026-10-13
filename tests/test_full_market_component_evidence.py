"""Synthetic engineering fixtures only; never real Production acceptance."""
from copy import deepcopy
from datetime import date, timedelta
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from src import full_market_component_evidence as m


def fixture(root, complete=24):
    universe = {"verification_status": "PASS", "stocks": [
        {"symbol": f"SYN{i:04}", "market": "TWSE" if i < 1085 else "TPEX"} for i in range(1978)]}
    _, uid = m.exact_universe(universe)
    day = date(2026, 10, 12)
    dates = []
    while len(dates) < 180:
        if day.weekday() < 5:
            dates.append(day.isoformat())
        day -= timedelta(days=1)
    dates.reverse()
    periods = [(date(2026, 10, 9) - timedelta(days=7 * i)).isoformat() for i in range(10)][::-1]
    observed, validated = "2026-10-12T10:00:00Z", "2026-10-12T10:01:00Z"
    refs = []
    def put(name, obj):
        p = root / name
        p.write_bytes(m.canonical(obj))
        return {"path": str(p), "sha256": m.digest(p.read_bytes())}
    for market in ("TWSE", "TPEX"):
        for family in m.FAMILIES:
            ident = market + ":" + family
            raw = put(market + family + "-raw.json", {"scope": m.SYNTHETIC, "identity": ident})
            host = "www.tdcc.com.tw" if family == "tdcc" else "www.twse.com.tw" if market == "TWSE" else "www.tpex.org.tw"
            endpoint = "https://" + host + "/synthetic-only-not-a-live-endpoint"
            receipt = put(market + family + "-receipt.json", {"endpoint": endpoint, "final_url": endpoint,
                "http_status": 200, "market": market, "family": family, "raw_sha256": raw["sha256"],
                "bytes": Path(raw["path"]).stat().st_size, "requested_at": observed, "observed_at": observed,
                "validated_at": validated, "material_scope": m.SYNTHETIC})
            refs.append({"id": ident, "family": family, "market": market, "raw": raw, "receipt": receipt})
    issuers = {}
    for n, row in enumerate(universe["stocks"]):
        s, market = row["symbol"], row["market"]
        histories = {family: [] for family in m.FAMILIES}
        if n < complete:
            for i, d in enumerate(dates):
                close = 100 + n * .3 + i * .02 + (.1 if i % 2 else -.1)
                common = {"symbol": s, "market": market, "trade_date": d, "source_timestamp": observed,
                          "raw_locator": "$[" + str(i) + "]"}
                stock = {**common, "open": close, "high": close + 1, "low": close - 1,
                         "close": close, "volume": 10000 + n * 100, "turnover": close * (10000 + n * 100),
                         "evidence_ref": market + ":stock"}
                histories["stock"].append(stock)
                histories["benchmark"].append({**common, "benchmark_symbol": "TAIEX" if market == "TWSE" else "TPEX",
                    "close": 100 + i * .01, "evidence_ref": market + ":benchmark"})
                if i >= 154:
                    histories["institutional"].append({**common, "close": close, "turnover": stock["turnover"],
                        "foreign_net_shares": n + 1, "investment_trust_net_shares": 2 - n,
                        "evidence_ref": market + ":institutional"})
            histories["tdcc"] = [{"symbol": s, "market": market, "period_end": d, "holder_pct_400": 40 + n * .1,
                "raw_locator": "$[" + str(i) + "]", "source_timestamp": observed, "evidence_ref": market + ":tdcc"}
                for i, d in enumerate(periods)]
        issuers[s] = {"market": market, "histories": histories}
    history = {"artifact_kind": "RATE_OFFICIAL_COMPONENT_HISTORY_INPUT_V1", "material_scope": m.SYNTHETIC,
        "ranking_universe_identity": uid, "trading_date": dates[-1], "issuers": issuers, "prior_stage_state": None}
    history_ref = put("history.json", history)
    acceptance = {"status": "PASS", "material_scope": m.SYNTHETIC, "production_evidence_authoritative": False,
        "fallback_used": False, "normalized_history_sha256": history_ref["sha256"],
        "raw_receipt_references_sha256": m.digest(refs), "normalization_owner_sha256_lf": m.owners(),
        "ranking_universe_identity": uid, "validated_at": validated, "source_snapshot_id": "SYNTHETIC-SOURCE-ONLY",
        "verified_sessions": {market: dates for market in ("TWSE", "TPEX")}, "tdcc_available_periods": periods,
        "latest_official_session": {market: dates[-1] for market in ("TWSE", "TPEX")},
        "session_gate": {market: "MARKET_SESSION_CONFIRMED" for market in ("TWSE", "TPEX")},
        "current_daily_receipt_ids": {market: market + ":stock" for market in ("TWSE", "TPEX")},
        "current_benchmark_receipt_ids": {market: market + ":benchmark" for market in ("TWSE", "TPEX")},
        "stage_reconstruction_authority_id": "SYNTHETIC_RECONSTRUCTION_AUTHORITY_ONLY"}
    binding = {"acceptance": put("acceptance.json", acceptance), "history": history_ref, "raw_receipts": refs}
    return universe, uid, history, acceptance, binding


class ComponentEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.u, self.uid, self.h, self.a, self.b = fixture(self.root)

    def update(self):
        self.b["history"]["sha256"] = self.write(self.b["history"]["path"], self.h)
        self.a["normalized_history_sha256"] = self.b["history"]["sha256"]
        self.a["raw_receipt_references_sha256"] = m.digest(self.b["raw_receipts"])
        self.b["acceptance"]["sha256"] = self.write(self.b["acceptance"]["path"], self.a)

    def write(self, path, value):
        Path(path).write_bytes(m.canonical(value))
        return m.digest(Path(path).read_bytes())

    def build(self, **kwargs):
        self.update()
        return m.build(self.u, expected_universe_identity=self.uid, generated_at="2026-10-12T10:02:00Z",
            validated_at="2026-10-12T10:03:00Z", evidence_as_of="2026-10-12T10:04:00Z", binding=self.b,
            trusted_acceptance_sha256=self.b["acceptance"]["sha256"], synthetic=True, **kwargs)

    def test_full_1978_scan_retains_missing(self):
        result = self.build()
        self.assertEqual(len(result["core"]["issuers"]), 1978)
        for name in m.COMPONENTS:
            self.assertEqual(result["core"]["counts"][name], {"PASS": 24, "MISSING_REQUIRED_HISTORY": 1954})

    def test_no_30_stock_truncation(self):
        self.u, self.uid, self.h, self.a, self.b = fixture(self.root, 31)
        result = self.build()
        self.assertEqual(result["core"]["populations"]["M7"]["component_population_count"], 31)

    def test_component_subset_keeps_ranking_universe(self):
        result = self.build()
        self.assertEqual(result["core"]["ranking_universe_count"], 1978)
        self.assertEqual(result["core"]["populations"]["M7"]["component_population_count"], 24)
        self.assertNotEqual(result["core"]["populations"]["M7"]["component_population_id"], self.uid)

    def test_owner_generation_vectors_and_stage_lineage(self):
        row = self.build()["core"]["issuers"][0]["components"]
        self.assertEqual(row["M7"]["value"], m.calculate_m7(row["M7"]["owner_lineage"]["components"])["m7_score"])
        self.assertEqual(set(row["M7"]["owner_lineage"]["components"]), {"PT", "PV", "MO", "FI", "IT", "LH", "RS"})
        self.assertEqual(set(row["MHE"]["owner_lineage"]["components"]), {"H5", "H20", "H60", "H120"})
        stage = row["Stage"]["owner_lineage"]
        self.assertTrue(stage["stage_evidence_lineage"] and stage["source_state_id"] and stage["input_snapshot_id"])
        self.assertEqual(stage["prior_stage_source"], "RECONSTRUCTED_FROM_AUTHORIZED_HISTORICAL_EVIDENCE")

    def test_duplicate_issuer_rejected(self):
        self.u["stocks"][-1] = deepcopy(self.u["stocks"][0])
        with self.assertRaisesRegex(ValueError, "UNIVERSE_CARDINALITY"):
            self.build()

    def test_missing_issuer_rejected(self):
        del self.h["issuers"]["SYN1977"]
        with self.assertRaisesRegex(ValueError, "MISSING_OR_EXTRA_ISSUER"):
            self.build()

    def test_wrong_universe_hash(self):
        self.uid = "0" * 64
        with self.assertRaisesRegex(ValueError, "EXACT_UNIVERSE"):
            self.build()

    def test_stale_data(self):
        ref = self.b["raw_receipts"][0]["receipt"]
        obj = m.read_metadata(Path(ref["path"]).read_bytes())
        obj.update(requested_at="2026-10-12T06:00:00Z", observed_at="2026-10-12T06:00:00Z")
        ref["sha256"] = self.write(ref["path"], obj)
        with self.assertRaisesRegex(ValueError, "STALE"):
            self.build()

    def test_future_data(self):
        self.h["trading_date"] = "2099-01-01"
        with self.assertRaisesRegex(ValueError, "FUTURE_TRADING_DATE"):
            self.build()

    def test_wrong_benchmark_date(self):
        self.h["issuers"]["SYN0000"]["histories"]["benchmark"][-1]["trade_date"] = "2026-10-11"
        row = self.build()["core"]["issuers"][0]["components"]
        self.assertEqual(row["MHE"]["status"], "INVALID_EVIDENCE")
        self.assertIsNone(row["MHE"]["value"])

    def test_wrong_institutional_date(self):
        self.h["issuers"]["SYN0000"]["histories"]["institutional"][-1]["trade_date"] = "2026-10-11"
        row = self.build()["core"]["issuers"][0]["components"]
        self.assertEqual(row["M7"]["status"], "INVALID_EVIDENCE")
        self.assertEqual(row["MHE"]["status"], "PASS")

    def test_wrong_tdcc_period(self):
        self.h["issuers"]["SYN0000"]["histories"]["tdcc"][-1]["period_end"] = "2026-10-10"
        row = self.build()["core"]["issuers"][0]["components"]
        self.assertEqual(row["SmartMoney"]["status"], "INVALID_EVIDENCE")

    def test_insufficient_stock_history_retained(self):
        self.h["issuers"]["SYN0000"]["histories"]["stock"] = self.h["issuers"]["SYN0000"]["histories"]["stock"][-100:]
        row = self.build()["core"]["issuers"][0]["components"]
        self.assertEqual(row["MHE"]["status"], "MISSING_REQUIRED_HISTORY")
        self.assertIsNone(row["MHE"]["value"])

    def test_owner_sha_drift(self):
        with patch.dict(m.CONTRACT["owner_code_sha256_lf"], {"src/rate_logic.py": "0" * 64}):
            with self.assertRaisesRegex(ValueError, "OWNER_SHA_DRIFT"):
                self.build()

    def test_missing_validation_timestamp(self):
        del self.a["validated_at"]
        with self.assertRaises(KeyError):
            self.build()

    def test_population_tamper_cold_rejected(self):
        result = self.build()
        result["core"]["populations"]["M7"]["component_population_count"] += 1
        with self.assertRaisesRegex(ValueError, "IDENTITY_TAMPER"):
            m.verify(result, self.u, expected_universe_identity=self.uid, as_of=m.now(), synthetic=True)

    def test_no_ranking_execution(self):
        with patch("src.rate_logic.rank_composites", side_effect=AssertionError("ranking forbidden")), patch(
                "src.rate_logic.rank_candidates", side_effect=AssertionError("ranking forbidden")):
            result = self.build()
        self.assertFalse(result["core"]["governance"]["ranking_authorized"])

    def test_raw_tamper(self):
        self.update()
        Path(self.b["raw_receipts"][0]["raw"]["path"]).write_bytes(b"tampered")
        with self.assertRaisesRegex(ValueError, "SOURCE_HASH"):
            self.build()

    def test_receipt_tamper(self):
        Path(self.b["raw_receipts"][0]["receipt"]["path"]).write_bytes(b"tampered")
        with self.assertRaisesRegex(ValueError, "SOURCE_HASH"):
            self.build()

    def test_source_acceptance_external_pin(self):
        self.update()
        with self.assertRaisesRegex(ValueError, "TRUSTED_SOURCE_ACCEPTANCE"):
            m.load_sources(self.b, trusted_acceptance_sha256="0" * 64, as_of=m.now(), synthetic=True)

    def test_no_synthetic_promotion(self):
        self.update()
        with self.assertRaisesRegex(ValueError, "NOT_PRODUCTION_ACCEPTED"):
            m.load_sources(self.b, trusted_acceptance_sha256=self.b["acceptance"]["sha256"], as_of=m.now())

    def test_no_fallback(self):
        self.a["fallback_used"] = True
        with self.assertRaisesRegex(ValueError, "NOT_PRODUCTION_ACCEPTED"):
            self.build()

    def test_preclose_rejected(self):
        ref = self.b["raw_receipts"][0]["receipt"]
        obj = m.read_metadata(Path(ref["path"]).read_bytes())
        obj.update(requested_at="2026-10-12T05:00:00Z", observed_at="2026-10-12T05:00:00Z")
        ref["sha256"] = self.write(ref["path"], obj)
        with self.assertRaisesRegex(ValueError, "PRECLOSE"):
            self.build()

    def test_unknown_current_session_rejected(self):
        self.a["session_gate"]["TPEX"] = "UNPROVEN"
        with self.assertRaisesRegex(ValueError, "SESSION_GATE"):
            self.build()

    def test_prior_stage_authority_required(self):
        del self.a["stage_reconstruction_authority_id"]
        row = self.build()["core"]["issuers"][0]["components"]
        self.assertEqual(row["Stage"]["status"], "NOT_COMPUTED")
        self.assertEqual(row["M7"]["status"], "PASS")

    def test_missing_source_all_issuers_not_evaluated(self):
        result = m.build(self.u, expected_universe_identity=self.uid, generated_at="2026-10-12T10:02:00Z",
            validated_at="2026-10-12T10:03:00Z", evidence_as_of="2026-10-12T10:04:00Z", synthetic=True)
        self.assertTrue(all(v == {"NOT_EVALUATED": 1978} for v in result["core"]["counts"].values()))
        self.assertTrue(all(v["component_population_id"] is None for v in result["core"]["populations"].values()))

    def test_immutable_external_output_no_overwrite(self):
        result = self.build()
        m.save(self.root / "out", result)
        with self.assertRaisesRegex(ValueError, "OUTPUT_MUST_BE_NEW"):
            m.save(self.root / "out", result)

    def test_reproducible_values_and_identity(self):
        self.assertEqual(self.build(), self.build())

    def test_independent_process_cold_read(self):
        result = self.build()
        universe_path = self.root / "universe.json"
        universe_path.write_bytes(m.canonical(self.u))
        path = m.save(self.root / "out", result)
        code = ("import sys; from src import full_market_component_evidence as m; "
                "u=m.read_metadata(open(sys.argv[1],'rb').read()); b=m.read_metadata(open(sys.argv[2],'rb').read()); "
                "assert m.verify(b,u,expected_universe_identity=sys.argv[3],as_of='2026-10-12T10:04:00Z',"
                "trusted_acceptance_sha256=sys.argv[4],synthetic=True)")
        run = subprocess.run([sys.executable, "-B", "-c", code, str(universe_path), str(path), self.uid,
                              self.b["acceptance"]["sha256"]], capture_output=True)
        self.assertEqual(run.returncode, 0, run.stderr.decode())

    def test_protected_files_and_no_publication(self):
        paths = list(m.CONTRACT["owner_code_sha256_lf"]) + ["src/fundamental.py", "src/phase2_production.py",
            "src/production_refresh_commit.py", "src/production_live_state.py"]
        before = {p: (m.ROOT / p).read_bytes() for p in paths}
        self.build()
        self.assertEqual(before, {p: (m.ROOT / p).read_bytes() for p in paths})
        self.assertFalse(m.CONTRACT["governance"]["production_publication_allowed"])
        self.assertFalse(m.CONTRACT["governance"]["state_mutation_allowed"])

    def test_intraday_still_blocked(self):
        self.assertEqual(self.build()["core"]["governance"]["intraday"], "BLOCKED_EXTERNAL")

    def test_no_real_universe_from_matching_counts_only(self):
        self.update()
        with self.assertRaisesRegex(ValueError, "EXACT_UNIVERSE"):
            m.build(self.u, expected_universe_identity=self.uid, generated_at="2026-10-12T10:02:00Z",
                validated_at="2026-10-12T10:03:00Z", evidence_as_of="2026-10-12T10:04:00Z")

    def test_current_cold_read_rejects_now_stale_source(self):
        result = self.build()
        with self.assertRaisesRegex(ValueError, "STALE_EVIDENCE"):
            m.verify(result, self.u, expected_universe_identity=self.uid, as_of="2026-10-12T14:00:00Z",
                trusted_acceptance_sha256=self.b["acceptance"]["sha256"], synthetic=True)

    def test_zero_volume_remains_data_not_score_zero(self):
        for row in self.h["issuers"]["SYN0000"]["histories"]["stock"][-20:]:
            row["volume"] = 0
        result = self.build()["core"]["issuers"][0]["components"]["Liquidity"]
        self.assertEqual(result["status"], "NOT_COMPUTED")
        self.assertIsNone(result["value"])

    def test_fundamental_subset_does_not_prefilter_technical(self):
        bundle = self.build()
        original = [{**r, "status": "PASS" if i < 12 else "MISSING_REQUIRED_PERIOD",
                     "population_id": "SYNTHETIC_FUNDAMENTAL_DISTINCT_POPULATION"} for i, r in enumerate(self.u["stocks"])]
        core = {"universe_identity": self.uid, "population_id": "SYNTHETIC_FUNDAMENTAL_DISTINCT_POPULATION", "issuers": original}
        path = self.root / "fundamental.json"
        self.write(path, {"core": core, "content_sha256": m.digest(core)})
        preview = m.readiness_preview(bundle, path, trusted_file_sha256=m.digest(path.read_bytes()), synthetic=True)
        self.assertEqual(preview["counts"], {"top50": 12, "long": 12, "short": 24})
        self.assertFalse(preview["fundamental_recomputed"])
        self.assertEqual(bundle["core"]["populations"]["M7"]["component_population_count"], 24)
        self.assertTrue(all(g["score"] is None and g["rank"] is None for r in preview["issuers"] for g in r["kinds"].values()))

    def test_exact_discovery_plan_no_execution(self):
        plan = m.acquisition_plan(self.u, expected_universe_identity=self.uid, execution_head=m.CONTRACT["base_sha"])
        self.assertEqual(plan["core"]["expected_requests"], 4)
        self.assertEqual(len(plan["core"]["entries"]), 4)
        self.assertFalse(plan["core"]["execution_allowed"])
        self.assertFalse(plan["core"]["fallback_allowed"])
        self.assertEqual(plan["core"]["retry"], 0)
        self.assertIsNone(plan["core"]["history_acquisition"]["expected_requests"])


if __name__ == "__main__":
    unittest.main()
