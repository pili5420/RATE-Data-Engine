"""Synthetic engineering only; no real provider or qualification claim."""
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import unittest

from scripts.provider_warmup_readiness import (CONTRACT, FLAGS, cold_verify, decide,
    envelope, external_output, fingerprint, pinned, source_evidence, verify_inventory)
from src.eps_duration_facts.model import Rejected
from src.provider_eps_candidate import WINDOW, _canonical
from src.provider_financial_features import CONTRACT as FEATURES, EPS_NAMES, REVENUE_NAME, compute_core, seal
from tests.provider_financial_features_fixture import fixture_inputs

BASE = CONTRACT["base_sha"]
EXECUTION = {"base_sha": BASE, "head_sha": "1" * 40}


class ReadinessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="phase-i-synthetic-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.inputs = fixture_inputs(self.root)
        stocks = self.inputs["universe"]["stocks"]
        for market, count in (("TWSE", 1083), ("TPEX", 891)):
            for i in range(count):
                symbol = market + str(i).zfill(4)
                stocks.append({"symbol": symbol, "market": market})
                self.inputs["gaps"].extend({"symbol": symbol, "market": market, "analysis_quarter": q,
                    "classification": "NO_PROVIDER_ROWS_FOR_QUARTER"} for q in WINDOW)
        self.inputs["universe"]["verification_status"] = "PASS"
        for row in self.inputs["eps"]:
            receipt = json.loads(Path(row["receipt_reference"]).read_text(encoding="utf-8"))
            receipt.update(requested_url="https://api.finmindtrade.com/api/v4/data", http_status=200,
                query={"dataset": "TaiwanStockFinancialStatements", "data_id": row["symbol"]},
                received_at=row["acquired_observed_at"], response_body_sha256=row["raw_sha256"])
            Path(row["receipt_reference"]).write_bytes(_canonical(receipt))
            row["receipt_sha256"] = fingerprint(row["receipt_reference"])["sha256"]
        # Each synthetic revenue observation has explicit bytes/receipt identities.
        for i, row in enumerate(self.inputs["revenue"]):
            raw, receipt = self.root / f"rev-{i}.bin", self.root / f"receipt-{i}.json"
            raw.write_bytes(_canonical({"SYNTHETIC_ONLY": row["revenue_yoy"]}))
            row.update(raw_reference=str(raw), raw_sha256=fingerprint(raw)["sha256"], receipt_reference=str(receipt))
            receipt.write_bytes(_canonical({"source_owner": "MOPS Official", "market": row["market"],
                "requested_period": row["period"], "body_sha256": row["raw_sha256"], "http_status": 200,
                "fallback_used": False, "endpoint": "https://mopsov.twse.com.tw/nas/t21/SYNTHETIC_ONLY.html",
                "final_url": "https://mopsov.twse.com.tw/nas/t21/SYNTHETIC_ONLY.html",
                "retrieval_timestamp": row["observed_at"], "official_report_disclosure_date": "2026-10-06"}))
            row["receipt_sha256"] = fingerprint(receipt)["sha256"]
        self.now = datetime.now(timezone.utc).isoformat()

    def package(self, inputs=None):
        return seal(compute_core(inputs or self.inputs), code_binding={"base_sha": "0" * 40, "head_sha": "2" * 40})

    def evidence(self, inputs=None):
        return source_evidence(inputs or self.inputs, datetime.now(timezone.utc).isoformat())[0]

    def result(self, inputs=None):
        inputs = inputs or self.inputs
        return decide(self.package(inputs), inputs["universe"], self.evidence(inputs), EXECUTION,
                      datetime.now(timezone.utc).isoformat())

    def company(self, result, symbol="2330"):
        return next(c for c in result["gate_i_3_warmup_sandbox"]["companies"] if c["symbol"] == symbol)

    def missing(self, q="2024Q3"):
        self.inputs["eps"] = [r for r in self.inputs["eps"] if not (r["symbol"] == "2330" and r["analysis_quarter"] == q)]
        self.inputs["gaps"].append({"symbol": "2330", "market": "TWSE", "analysis_quarter": q,
            "classification": "NO_PROVIDER_ROWS_FOR_QUARTER"})

    def test_exact_1978_universe(self):
        r = self.result()
        self.assertEqual(len(r["gate_i_3_warmup_sandbox"]["companies"]), 1978)
        self.assertEqual(r["gate_i_3_warmup_sandbox"]["summary"]["by_market"]["TWSE"]["companies"], 1085)

    def test_complete_issuer_calculates_existing_features(self):
        row = self.company(self.result())
        self.assertTrue(row["sandbox_input_ready"])
        self.assertEqual(row["features"][EPS_NAMES[0]]["status"], "COMPUTABLE")

    def test_partial_valid_evidence_preserved(self):
        self.missing()
        row = self.company(self.result())
        self.assertEqual(row["valid_eps_positions_retained"], 7)
        self.assertFalse(row["sandbox_input_ready"])

    def test_missing_does_not_zero_fill(self):
        self.missing()
        row = self.company(self.result())
        self.assertIsNone(row["features"][EPS_NAMES[1]]["value"])
        self.assertIsNone(row["features"][EPS_NAMES[2]]["value"])

    def test_partial_latest_still_computes(self):
        self.missing()
        self.assertEqual(self.company(self.result())["features"][EPS_NAMES[0]]["status"], "COMPUTABLE")

    def test_missing_revenue_blocks_only_revenue(self):
        self.inputs["revenue"] = [r for r in self.inputs["revenue"] if not (r["symbol"] == "2330" and r["period"] == "2026-09")]
        row = self.company(self.result())
        self.assertTrue(row["eps_ready"])
        self.assertFalse(row["revenue_ready"])

    def test_zero_base_retains_null(self):
        self.inputs["revenue"][0].update(revenue_yoy=None, revenue_yoy_status="UNDEFINED_ZERO_BASE")
        row = self.company(self.result())
        self.assertIsNone(row["features"][REVENUE_NAME]["value"])
        self.assertIn({"period": "2026-07", "reason": "UNDEFINED_ZERO_BASE"}, row["missing_revenue_periods"])

    def test_no_issuer_silently_dropped(self):
        self.assertEqual(self.company(self.result(), "7777")["valid_eps_positions_retained"], 0)

    def test_no_older_quarter_substitution(self):
        self.inputs["eps"][0].update(provider_date="2024-06-30", analysis_quarter="2024Q2")
        with self.assertRaises(Rejected): self.result()

    def test_exact_quarter_end_only(self):
        self.inputs["eps"][0]["provider_date"] = "2024-09-29"
        with self.assertRaisesRegex(Rejected, "AMBIGUOUS_PROVIDER_PERIOD"): self.evidence()

    def test_duplicate_rejected(self):
        self.inputs["eps"].append(deepcopy(self.inputs["eps"][0]))
        with self.assertRaisesRegex(Rejected, "DUPLICATE"): self.package()

    def test_nonfinite_rejected(self):
        for value in ("NaN", "Infinity", True):
            data = deepcopy(self.inputs); data["eps"][0]["provider_value"] = value
            with self.assertRaises(Rejected): self.package(data)

    def test_negative_and_zero_not_filtered(self):
        r = self.result()
        self.assertEqual(r["gate_i_3_warmup_sandbox"]["summary"]["valid_eps_positions_retained"], 24)

    def test_no_official_ttm_promotion(self):
        self.assertTrue(all(f["not_official_ttm"] for f in self.company(self.result())["features"].values()))

    def test_raw_mutation_rejected(self):
        Path(self.inputs["eps"][0]["raw_reference"]).write_bytes(b"tamper")
        with self.assertRaisesRegex(Rejected, "TAMPER"): self.evidence()

    def test_receipt_mutation_rejected(self):
        Path(self.inputs["eps"][0]["receipt_reference"]).write_bytes(b"tamper")
        with self.assertRaisesRegex(Rejected, "TAMPER"): self.evidence()

    def test_provider_mismatch(self):
        self.inputs["eps"][0]["dataset"] = "OTHER"
        with self.assertRaisesRegex(Rejected, "PROVIDER_MISMATCH"): self.evidence()

    def test_revenue_source_mismatch(self):
        self.inputs["revenue"][0]["source"] = "OTHER"
        with self.assertRaisesRegex(Rejected, "PROVIDER_MISMATCH"): self.evidence()

    def test_future_observation(self):
        self.inputs["eps"][0]["verified_observed_at"] = "2099-01-01T00:00:00Z"
        with self.assertRaisesRegex(Rejected, "TIME"): self.evidence()

    def test_observation_not_publication(self):
        record = self.evidence()["FinMind"][0]
        self.assertIsNone(record["original_publication_timestamp"])
        self.assertIsNotNone(record["observation_timestamp"])

    def test_receipt_disclosure_label_not_original_publication(self):
        record = self.evidence()["MOPS Official"][0]
        self.assertIsNone(record["original_publication_timestamp"])
        self.assertEqual(record["receipt_disclosure_label_not_verified_publication"], "2026-10-06")

    def test_restatement_conflict_rejected(self):
        self.inputs["eps"][0]["revision_id"] = "fabricated"
        with self.assertRaisesRegex(Rejected, "UNSUPPORTED_PUBLICATION"): self.evidence()

    def test_retrieval_as_publication_rejected(self):
        self.inputs["eps"][0]["public_time"] = self.inputs["eps"][0]["acquired_observed_at"]
        with self.assertRaisesRegex(Rejected, "UNSUPPORTED_PUBLICATION"): self.evidence()

    def test_provider_date_as_publication_rejected(self):
        self.inputs["eps"][0]["public_time"] = self.inputs["eps"][0]["provider_date"]
        with self.assertRaisesRegex(Rejected, "UNSUPPORTED_PUBLICATION"): self.evidence()

    def test_historical_claim_rejected(self):
        self.inputs["eps"][0]["historical_pit_status"] = "PASS"
        with self.assertRaises(Rejected): self.evidence()

    def test_provider_outcomes_are_separate(self):
        matrix = self.result()["gate_i_1_provider_qualification"]
        self.assertEqual(len(matrix), 2)
        self.assertTrue(all(r["status"] == "NOT_QUALIFIED" and r["source_validation"] == "PASS" for r in matrix))

    def test_inventory_never_activates_ranking(self):
        row = self.company(self.result())
        self.assertTrue(row["sandbox_input_ready"])
        self.assertFalse(row["ranking_eligible"])
        self.assertIsNone(row["formal_score"])
        self.assertIsNone(row["rank"])

    def test_four_gates_separate(self):
        r = self.result()
        self.assertEqual(r["gate_i_2_historical_pit"]["status"], "UNPROVEN")
        self.assertEqual(r["gate_i_3_warmup_sandbox"]["status"], "PASS")
        self.assertFalse(r["gate_i_4_production_readiness"]["first_refresh_eligible"])

    def test_blockers_not_generic(self):
        self.assertEqual(self.result()["gate_i_4_production_readiness"]["blocking_conditions"],
            ["BLOCKED_PROVIDER_QUALIFICATION", "BLOCKED_HISTORICAL_PIT", "BLOCKED_DATA_GAP", "BLOCKED_GOVERNANCE"])

    def test_external_block_and_fallback_unchanged(self):
        self.assertEqual(FLAGS["external_authorized_intraday_feed_dependency"], "BLOCKED_EXTERNAL")
        self.assertFalse(FLAGS["fallback_allowed"])

    def test_exact_head_rejection(self):
        with self.assertRaisesRegex(Rejected, "EXECUTION_BINDING"):
            decide(self.package(), self.inputs["universe"], self.evidence(), dict(EXECUTION, base_sha="0" * 40),
                   datetime.now(timezone.utc).isoformat())

    def test_wrong_universe_rejected(self):
        universe = deepcopy(self.inputs["universe"]); universe["stocks"].pop()
        with self.assertRaisesRegex(Rejected, "UNIVERSE"):
            decide(self.package(), universe, self.evidence(), EXECUTION, datetime.now(timezone.utc).isoformat())

    def test_market_binding_rejected(self):
        self.inputs["eps"][0]["market"] = "TPEX"
        with self.assertRaisesRegex(Rejected, "IDENTITY_CONFLICT"): self.package()

    def test_deterministic_replay(self):
        first = self.result()
        random.Random(11).shuffle(self.inputs["eps"])
        # Evidence order is not part of the core identity.
        self.assertEqual(first, self.result())

    def test_cold_read(self):
        result = envelope(self.result(), self.now, datetime.now(timezone.utc).isoformat())
        path = self.root / "result.json"; path.write_bytes(_canonical(result))
        proof = cold_verify(path, fingerprint(path)["sha256"], self.package(), self.inputs["universe"],
            self.evidence(), EXECUTION, datetime.now(timezone.utc).isoformat())
        self.assertEqual(proof["status"], "PASS")

    def test_cold_source_pin_tamper(self):
        path = self.root / "pin.json"; path.write_bytes(b"{}")
        with self.assertRaisesRegex(Rejected, "SOURCE_PIN"): pinned(path, "0" * 64)

    def test_cold_core_tamper_even_with_new_file_pin(self):
        result = envelope(self.result(), self.now, datetime.now(timezone.utc).isoformat())
        result["core"]["boundaries"]["production_eligible"] = True
        path = self.root / "bad.json"; path.write_bytes(_canonical(result))
        with self.assertRaisesRegex(Rejected, "COLD_REPLAY"):
            cold_verify(path, fingerprint(path)["sha256"], self.package(), self.inputs["universe"],
                self.evidence(), EXECUTION, datetime.now(timezone.utc).isoformat())

    def test_future_cold_envelope_rejected(self):
        value = envelope(self.result(), self.now, "2099-01-01T00:00:00Z")
        path = self.root / "future.json"; path.write_bytes(_canonical(value))
        with self.assertRaisesRegex(Rejected, "FUTURE_ENVELOPE"):
            cold_verify(path, fingerprint(path)["sha256"], self.package(), self.inputs["universe"],
                self.evidence(), EXECUTION, datetime.now(timezone.utc).isoformat())

    def test_protected_mutation_detected(self):
        path = self.root / "protected.json"; path.write_bytes(b"original")
        inventory = {str(path): fingerprint(path)}
        verify_inventory(inventory)
        path.write_bytes(b"changed")
        with self.assertRaisesRegex(Rejected, "PROTECTED_SOURCE_CHANGED"): verify_inventory(inventory)

    def test_output_not_in_source(self):
        with self.assertRaisesRegex(Rejected, "OUTPUT_IN_SOURCE"): external_output(self.root / "output", [self.root])

    def test_output_not_production(self):
        with self.assertRaisesRegex(Rejected, "PROTECTED_OUTPUT"): external_output(self.root / "Production" / "new", [])

    def test_existing_output_rejected(self):
        with self.assertRaisesRegex(Rejected, "NEW_EXTERNAL"): external_output(self.root, [])

    def test_independent_process_disk_read(self):
        path = self.root / "package.json"; path.write_bytes(_canonical(self.package()))
        code = "from pathlib import Path; from src.provider_eps_metadata import read_metadata; from src.provider_financial_features import validate_package; import sys; print(validate_package(read_metadata(Path(sys.argv[1]).read_bytes()))['companies'])"
        run = subprocess.run([sys.executable, "-B", "-c", code, str(path)], cwd=Path(__file__).resolve().parents[1],
            capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(run.stdout.strip(), "1978")

    def test_phase_i_independent_process_cold_reconstruction(self):
        package = self.package()
        package_path = self.root / "feature.json"; package_path.write_bytes(_canonical(package))
        path = self.root / "readiness.json"
        path.write_bytes(_canonical(envelope(self.result(), self.now, datetime.now(timezone.utc).isoformat())))
        code = ("from pathlib import Path; from datetime import datetime,timezone; import sys; "
            "from scripts.provider_warmup_readiness import cold_verify,source_evidence; "
            "from src.provider_eps_metadata import read_metadata; "
            "p=read_metadata(Path(sys.argv[1]).read_bytes()); i=p['core']['inputs']; "
            "now=datetime.now(timezone.utc).isoformat(); "
            "e=source_evidence(i,now)[0]; print(cold_verify(sys.argv[2],sys.argv[3],p,i['universe'],e,"
            "{'base_sha':sys.argv[4],'head_sha':'1'*40},now)['status'])")
        run = subprocess.run([sys.executable, "-B", "-c", code, str(package_path), str(path),
            fingerprint(path)["sha256"], BASE], cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(run.stdout.strip(), "PASS")

    def test_same_count_wrong_identity_rejected(self):
        universe = deepcopy(self.inputs["universe"])
        universe["stocks"][0]["symbol"] = "OTHER"
        with self.assertRaisesRegex(Rejected, "UNIVERSE_BINDING"):
            decide(self.package(), universe, self.evidence(), EXECUTION, datetime.now(timezone.utc).isoformat())

    def test_audit_denies_state_portfolio_ledger_and_network(self):
        output = self.root / "allowed"; output.mkdir()
        code = "from scripts.provider_warmup_readiness import isolation_guard; import sys,pathlib,socket; sys.addaudithook(isolation_guard(sys.argv[1])); "
        for operation in ("pathlib.Path(sys.argv[2]).write_text('bad')", "socket.getaddrinfo('example.com',443)"):
            for name in ("DecisionState", "RoyPortfolio", "AIPaperPortfolio", "TransactionLedger", "RankingOutput", "ProductionLatest"):
                target = self.root / name; target.write_bytes(b"original")
                run = subprocess.run([sys.executable, "-B", "-c", code + operation, str(output), str(target)],
                    cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
                self.assertNotEqual(run.returncode, 0)
                self.assertEqual(target.read_bytes(), b"original")

    def test_no_live_owner_dependency(self):
        path = Path(__file__).resolve().parents[1] / "scripts/provider_warmup_readiness.py"
        text = path.read_text(encoding="utf-8")
        for forbidden in ("calculate_fundamental(", "build_current_state(", "publish(", "run_warmup(", "run_scheduler("):
            self.assertNotIn(forbidden, text)


if __name__ == "__main__":
    unittest.main()
