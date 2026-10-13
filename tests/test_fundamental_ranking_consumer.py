"""Synthetic engineering evidence only, never real Production acceptance."""
from contextlib import contextmanager
from collections import Counter
from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from src import fundamental_ranking_consumer as c
from src import fundamental_first_refresh_execution as e
from src.fundamental import calculate_fundamental
from src.provider_eps_candidate import _canonical
from tests.test_fundamental_first_refresh_execution import universe
from tests.test_fundamental_eligibility import row as component_fixture

AT = "2026-10-13T01:00:00+00:00"
LATER = "2026-10-13T01:01:00+00:00"
ROOT = Path(__file__).resolve().parents[1]


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    body = e.canonical(value)
    path.write_bytes(body)
    return c.digest(body)


def fixture(root):
    """Full synthetic universe, authentic writer formats, three missing issuers."""
    u = universe()
    plan = e.build_request_plan(u, "SYNTHETIC_ONLY_AUTHORITY", c.CONTRACT["base_sha"])
    lineage = root / "acquisitions"
    config = {"universe": u, "authority_id": plan["authority_id"]}
    config_sha = write(lineage / "CONFIG.json", config)
    observed, head = [], None
    for entry in plan["entries"]:
        ordinal, provider, target = entry["ordinal"], entry["provider"], entry["target"]
        rows = []
        if provider == "FinMind":
            for index, period in enumerate(e.EPS_PERIODS):
                if target["symbol"] == "P0001" and period == "2024Q3":
                    continue
                rows.append({**target, "period": period, "numeric_status": "VALID_NUMERIC",
                    "value": str(Decimal(ordinal) / 100 + index), "provider_date": c.exact_date(period),
                    "provider_type": "EPS", "provider_origin_name": "\u57fa\u672c\u6bcf\u80a1\u76c8\u9918",
                    "json_locator": f"$.data[{index}]", "raw_row_index_zero_based": index,
                    "filing_id": None, "revision_id": None, "public_time": None})
        else:
            for stock in u["stocks"]:
                if stock["market"] != target["market"] or (stock["symbol"] == "T0001" and target["period"] == "2026-07"):
                    continue
                missing = stock["symbol"] == "P0002" and target["period"] == "2026-09"
                rows.append({**stock, "period": target["period"], "value": None if missing else
                             str(Decimal(int(stock["symbol"][1:])) / 100),
                             "numeric_status": "UNDEFINED_ZERO_BASE" if missing else "VALID_NUMERIC",
                             "json_locator": {"parsed_row_index_zero_based": len(rows), **stock,
                                              "period": target["period"]}})
        raw = e.canonical({"SYNTHETIC_ONLY": ordinal})
        raw_sha = c.digest(raw)
        raw_path = lineage / "raw" / (raw_sha + ".bin")
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_bytes(raw)
        receipt = {"http_status": 200, "fallback_used": False, "SYNTHETIC_ONLY": ordinal}
        receipt_body = e.canonical(receipt)
        receipt_sha = c.digest(receipt_body)
        write(lineage / "receipts" / (receipt_sha + ".json"), receipt)
        record = {"provider": provider, "target": target, "rows": rows, "raw_sha256": raw_sha,
            "receipt_sha256": receipt_sha, "authority_id": plan["authority_id"],
            "activation_timestamp": AT, "requested_at": AT, "received_at": AT,
            "source_observed_at": AT, "validation_timestamp": AT, "first_seen_at": AT,
            "historical_pit": "UNPROVEN", "fallback_allowed": False, "original_publication_timestamp": None,
            "source_identity_gate": "PASS", "scope": {"provider": provider, **target}}
        record["immutable_snapshot_id"] = "authorized-prospective-acquisition-" + c.digest(_canonical(record))
        ident = f"synthetic-{ordinal:04d}"
        intent = {"intent_id": ident, "config_sha256": config_sha, "authority_id": plan["authority_id"],
                  "provider": provider, "target": target, "requested_at": AT,
                  "dispatch": {"plan_binding": e.PlanDispatchGate(plan, entry, None)._binding()}}
        intent_sha = write(lineage / "intents" / (ident + ".json"), intent)
        event = {"config_sha256": config_sha, "intent_id": ident, "intent_sha256": intent_sha,
                 "record": record, "previous_head": head, "previous_scope_observation": None}
        head = c.digest(e.canonical(event))
        write(lineage / "events" / (f"{ordinal-1:08d}-" + head + ".json"), event)
        observed.append({"ordinal": ordinal, "request_key": entry["request_key"], "intent_id": ident,
                         "intent": intent, "record": record, "event_sha256": head})
    snapshot = e.assemble_fundamental(plan, u, observed)
    artifacts = root / "synthetic-published"
    published = e.publish_fundamental_atomic(snapshot, artifacts_root=artifacts,
                                           expected_previous_latest=None, clock=lambda: AT)
    pointer = json.loads((artifacts / e.LATEST_NAME).read_bytes())
    pins = {"latest_identity": published["latest_identity"], "snapshot_id": snapshot["fundamental_snapshot_id"],
            "snapshot_content_sha256": snapshot["content_sha256"],
            "snapshot_file_sha256": pointer["fundamental_snapshot"]["sha256"],
            "universe_identity": snapshot["universe_identity"]}
    acceptance = {"01_Final_Status": "FUNDAMENTAL_FIRST_REFRESH_PRODUCTION_ACCEPTED", "evidence_scope": c.SYNTHETIC,
        "19_Fundamental_Latest_Identity": pins["latest_identity"], "23_Snapshot_ID": pins["snapshot_id"],
        "24_Snapshot_Content_SHA": pins["snapshot_content_sha256"],
        "25_Snapshot_Cold_Read": {"raw_bytes_sha256": pins["snapshot_file_sha256"]},
        "29_Exact_Universe_Match": {"universe_identity": pins["universe_identity"]}}
    path = root / "SYNTHETIC_ACCEPTANCE.json"
    pins["acceptance_sha256"] = write(path, acceptance)
    binding = {"material_scope": c.SYNTHETIC, "source": pins, "artifacts_root": str(artifacts),
               "acceptance": {"path": str(path), "sha256": pins["acceptance_sha256"]},
               "lineage_root": str(lineage), "config_sha256": config_sha,
               "producer_main_sha": c.CONTRACT["base_sha"]}
    return binding, snapshot


@contextmanager
def changed_file(path, body):
    path = Path(path)
    old = path.read_bytes()
    try:
        path.write_bytes(body)
        yield
    finally:
        path.write_bytes(old)


class ConsumerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="synthetic-consumer-")
        cls.root = Path(cls.temp.name)
        cls.binding, cls.snapshot = fixture(cls.root)
        cls.bundle = c.build(cls.binding, generated_at=AT, validated_at=LATER, synthetic=True)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def complete(self):
        return deepcopy(next(r for r in self.snapshot["issuer_readiness"] if r["fundamental_input_status"] == "READY"))

    def read(self, binding=None, **kwargs):
        return c.read_accepted(binding or self.binding, as_of=LATER, synthetic=True, **kwargs)

    def reject_adaptation(self, change):
        row = self.complete()
        change(row)
        with self.assertRaises((ValueError, KeyError, TypeError)):
            c.adapt([row])

    def test_01_exact_1978_universe(self):
        self.assertEqual(self.bundle["core"]["counts"]["input_universe"], 1978)
        self.assertEqual(Counter(r["market"] for r in self.bundle["core"]["issuers"]), {"TWSE": 1085, "TPEX": 893})

    def test_02_owner_receives_every_issuer(self):
        with patch.object(c, "calculate_fundamental", wraps=calculate_fundamental) as owner:
            rebuilt = c.build(self.binding, generated_at=AT, validated_at=LATER, synthetic=True)
        self.assertEqual(len(owner.call_args.args[0]), 1978)
        self.assertEqual(rebuilt["content_sha256"], self.bundle["content_sha256"])

    def test_03_owner_answer_matches(self):
        rows, _ = c.adapt(self.snapshot["issuer_readiness"])
        expected = {r["symbol"]: r["Fundamental"] for r in calculate_fundamental(rows)}
        actual = {r["symbol"]: r["value"] for r in self.bundle["core"]["issuers"] if r["status"] == "PASS"}
        self.assertEqual(actual, expected)
        self.assertEqual(len(actual), 1975)

    def test_04_missing_verdicts_retained(self):
        self.assertEqual(self.bundle["core"]["counts"]["score_missing"], 3)
        self.assertTrue(all(r["value"] is None and any(r["missing_reasons"].values())
                            for r in self.bundle["core"]["issuers"] if r["status"] != "PASS"))

    def test_05_no_rank(self):
        self.assertTrue(all("rank" not in r for r in self.bundle["core"]["issuers"]))

    def test_06_latest_previous_order(self):
        row = self.complete()
        out, _ = c.adapt([row])
        eps = row["feature_inputs"]["eps"]
        self.assertEqual(out[0]["quarterly_eps"], [Decimal(eps[p]["value"]) for p in c.EPS_ORDER])
        self.assertGreater(sum(out[0]["quarterly_eps"][:4]), sum(out[0]["quarterly_eps"][4:]))

    def test_07_revenue_order(self):
        row = self.complete()
        for i, p in enumerate(c.REVENUE_ORDER):
            row["feature_inputs"]["revenue"][p]["value"] = str(i)
        self.assertEqual(c.adapt([row])[0][0]["revenue_yoy"], [Decimal(0), Decimal(1), Decimal(2)])

    def test_08_shuffled_period_keys(self):
        row = self.complete()
        expected = c.adapt([row])
        for field in ("eps", "revenue"):
            row["feature_inputs"][field] = dict(reversed(list(row["feature_inputs"][field].items())))
        self.assertEqual(c.adapt([row]), expected)

    def test_09_shuffled_issuers(self):
        rows = deepcopy(self.snapshot["issuer_readiness"])
        random.Random(42).shuffle(rows)
        first = {r["symbol"]: r for r in c.adapt(rows)[0]}
        second = {r["symbol"]: r for r in c.adapt(self.snapshot["issuer_readiness"])[0]}
        self.assertEqual(first, second)

    def test_10_decimal_precision_negative_zero(self):
        row = self.complete()
        literals = ["-0.000000000000000000000000000012345", "0", "9.12345678901234567890123456789012345"]
        for p, value in zip(c.EPS_ORDER, literals):
            row["feature_inputs"]["eps"][p]["value"] = value
        adapted = c.adapt([row])[0][0]
        self.assertEqual(adapted["quarterly_eps"][:3], list(map(Decimal, literals)))
        self.assertEqual([row["feature_inputs"]["eps"][p]["value"] for p in c.EPS_ORDER[:3]], literals)

    def test_11_wrong_latest(self):
        binding = deepcopy(self.binding)
        binding["source"]["latest_identity"] = "a" * 64
        with self.assertRaises(ValueError): self.read(binding)

    def test_12_wrong_snapshot_id(self):
        binding = deepcopy(self.binding)
        binding["source"]["snapshot_id"] += "x"
        with self.assertRaises(ValueError): self.read(binding)

    def test_13_wrong_snapshot_sha(self):
        binding = deepcopy(self.binding)
        binding["source"]["snapshot_content_sha256"] = "a" * 64
        with self.assertRaises(ValueError): self.read(binding)

    def test_14_wrong_universe(self):
        binding = deepcopy(self.binding)
        binding["source"]["universe_identity"] = "a" * 64
        with self.assertRaises(ValueError): self.read(binding)

    def test_15_duplicate_issuer(self):
        rows = deepcopy(self.snapshot["issuer_readiness"])
        rows[-1] = rows[0]
        with self.assertRaises(ValueError): c.exact_universe({"verification_status": "PASS", "stocks": rows})

    def test_16_missing_issuer(self):
        with self.assertRaises(ValueError):
            c.exact_universe({"verification_status": "PASS", "stocks": self.snapshot["issuer_readiness"][:-1]})

    def test_17_missing_eps_preserves_partial(self):
        row = deepcopy(next(r for r in self.snapshot["issuer_readiness"] if r["symbol"] == "P0001"))
        adapted, missing = c.adapt([row])
        self.assertEqual(len(adapted[0]["quarterly_eps"]), 7)
        self.assertEqual(missing["P0001"]["FinMind"], ["2024Q3"])

    def test_18_missing_revenue_preserves_partial(self):
        row = deepcopy(next(r for r in self.snapshot["issuer_readiness"] if r["symbol"] == "T0001"))
        self.assertEqual(len(c.adapt([row])[0][0]["revenue_yoy"]), 2)

    def test_19_undefined_null_not_zero(self):
        row = deepcopy(next(r for r in self.snapshot["issuer_readiness"] if r["symbol"] == "P0002"))
        self.assertIsNone(row["feature_inputs"]["revenue"]["2026-09"]["value"])
        self.assertEqual(len(c.adapt([row])[0][0]["revenue_yoy"]), 2)

    def test_20_invalid_numeric_null(self):
        self.reject_adaptation(lambda r: r["feature_inputs"]["revenue"]["2026-09"].update(value=None))

    def test_21_nonfinite(self):
        for value in ("NaN", "Infinity", "-Infinity", True):
            with self.subTest(value=value):
                self.reject_adaptation(lambda r: r["feature_inputs"]["eps"]["2026Q2"].update(value=value))

    def test_22_period_substitution(self):
        self.reject_adaptation(lambda r: r["feature_inputs"]["eps"].update({"2024Q2": {"value": "1"}}))

    def test_23_missing_flag_cannot_be_zero_filled(self):
        row = deepcopy(next(r for r in self.snapshot["issuer_readiness"] if r["symbol"] == "P0002"))
        row["feature_inputs"]["revenue"]["2026-09"].update(value="0", numeric_status="VALID_NUMERIC")
        with self.assertRaises(ValueError): c.adapt([row])

    def test_24_owner_drift(self):
        with patch.dict(c.CONTRACT["owner_code_sha256_lf"], {"src/fundamental.py": "a" * 64}):
            with self.assertRaisesRegex(ValueError, "OWNER_DRIFT"): c.owner_identities()

    def test_25_snapshot_tamper(self):
        pointer = json.loads((Path(self.binding["artifacts_root"]) / e.LATEST_NAME).read_bytes())
        path = Path(self.binding["artifacts_root"]) / pointer["fundamental_snapshot"]["path"]
        with changed_file(path, path.read_bytes() + b" "):
            with self.assertRaises(ValueError): self.read()

    def test_26_evidence_reference_tamper(self):
        loaded, stocks = self.read()
        loaded["snapshot"]["evidence_index"][0]["raw_sha256"] = "a" * 64
        with self.assertRaises(ValueError): c.verify_lineage(self.binding, loaded, stocks, LATER)

    def test_27_raw_tamper(self):
        ref = self.bundle["core"]["issuers"][0]["evidence_references"][0]["raw_reference"]
        with changed_file(ref["path"], b"tampered"):
            loaded, stocks = self.read()
            with self.assertRaisesRegex(ValueError, "RAW_TAMPER"): c.verify_lineage(self.binding, loaded, stocks, LATER)

    def test_28_receipt_tamper(self):
        ref = self.bundle["core"]["issuers"][0]["evidence_references"][0]["receipt_reference"]
        with changed_file(ref["path"], b"tampered"):
            loaded, stocks = self.read()
            with self.assertRaises(ValueError): c.verify_lineage(self.binding, loaded, stocks, LATER)

    def test_29_intent_tamper(self):
        ref = self.bundle["core"]["issuers"][0]["evidence_references"][0]["intent_reference"]
        with changed_file(ref["path"], b"tampered"):
            loaded, stocks = self.read()
            with self.assertRaises(ValueError): c.verify_lineage(self.binding, loaded, stocks, LATER)

    def test_30_event_tamper(self):
        ref = self.bundle["core"]["issuers"][0]["evidence_references"][0]["event_reference"]
        with changed_file(ref["path"], b"tampered"):
            loaded, stocks = self.read()
            with self.assertRaises(ValueError): c.verify_lineage(self.binding, loaded, stocks, LATER)

    def test_31_owner_score_domain(self):
        for value in (-1, 101, float("nan"), float("inf"), True, None):
            with self.subTest(value=value), self.assertRaises(ValueError): c.score_value(value)

    def test_32_owner_bad_score_rejected(self):
        def wrong(rows):
            result = calculate_fundamental(rows)
            result[0]["Fundamental"] = 101
            return result
        with patch.object(c, "calculate_fundamental", side_effect=wrong):
            with self.assertRaisesRegex(ValueError, "OWNER_SCORE_INVALID"):
                c.build(self.binding, generated_at=AT, validated_at=LATER, synthetic=True)

    def test_33_owner_population_loss_rejected(self):
        with patch.object(c, "calculate_fundamental", return_value=[]):
            with self.assertRaisesRegex(ValueError, "POPULATION_MISMATCH"):
                c.build(self.binding, generated_at=AT, validated_at=LATER, synthetic=True)

    def test_34_pit_promotion_rejected(self):
        bundle = deepcopy(self.bundle)
        bundle["core"]["governance"]["historical_pit"] = "PASS"
        bundle["content_sha256"] = c.digest(bundle["core"])
        with self.assertRaises(ValueError): self.bridge(bundle=bundle)

    def test_35_fallback_rejected(self):
        bundle = deepcopy(self.bundle)
        bundle["core"]["governance"]["fallback_allowed"] = True
        bundle["content_sha256"] = c.digest(bundle["core"])
        with self.assertRaises(ValueError): self.bridge(bundle=bundle)

    def test_36_v1_owner_impersonation_rejected(self):
        with self.assertRaisesRegex(ValueError, "V1_IMPERSONATION"):
            self.bridge(components={"formal_eps_period_identity": {"status": "PASS"}})

    def test_37_ranking_execution_rejected(self):
        with self.assertRaisesRegex(ValueError, "NOT_AUTHORIZED"): c.execute_ranking(self.bundle)

    def bridge(self, symbol="P0001", components=None, bundle=None):
        bundle = bundle or self.bundle
        return c.eligibility_bridge(bundle, expected_content_sha256=bundle["content_sha256"],
            symbol=symbol, market="TPEX", components=components or {}, as_of=LATER,
            component_population_id="SYNTHETIC_INDEPENDENT_COMPONENT_POPULATION")

    def components(self):
        inputs = component_fixture()["inputs"]
        result = {k: v for k, v in inputs.items() if k in {n for names in c.RANK_INPUTS.values() for n in names}
                  and k != "Fundamental"}
        for value in result.values():
            value.update(observed_at=AT, validated_at=AT,
                         population_id="SYNTHETIC_INDEPENDENT_COMPONENT_POPULATION")
        return result

    def test_38_top50_missing_fundamental(self):
        result = self.bridge(components=self.components())
        self.assertFalse(result["gates"]["top50"]["input_ready"])
        self.assertIsNone(result["gates"]["top50"]["score"])

    def test_39_long_missing_fundamental(self):
        self.assertFalse(self.bridge(components=self.components())["gates"]["long"]["input_ready"])

    def test_40_short_independent(self):
        result = self.bridge(components=self.components())
        self.assertTrue(result["gates"]["short"]["input_ready"])
        self.assertFalse(result["ranking_authorized"])

    def test_41_short_requires_own_inputs(self):
        components = self.components()
        components.pop("M7")
        self.assertFalse(self.bridge(components=components)["gates"]["short"]["input_ready"])

    def test_42_complete_fundamental_other_components_unproven(self):
        result = self.bridge(symbol="P0003")
        self.assertTrue(result["fundamental_ready"])
        self.assertFalse(any(g["input_ready"] for g in result["gates"].values()))

    def test_43_bridge_does_not_promote_v1(self):
        self.assertEqual(self.bridge()["formal_eps_period_identity"], "NOT_ASSERTED_V1_UNCHANGED")
        self.assertEqual(c.CONTRACT["scope"], "PROSPECTIVE_PRODUCTION_ONLY")

    def test_44_component_population_mismatch(self):
        components = self.components()
        components["M7"]["population_id"] = "wrong"
        with self.assertRaises(ValueError): self.bridge(components=components)

    def test_45_future_time_rejected(self):
        with self.assertRaises(ValueError): c.read_accepted(self.binding, as_of="2099-01-01T00:00:00Z", synthetic=True)

    def test_46_before_commit_rejected(self):
        with self.assertRaises(ValueError): c.read_accepted(self.binding, as_of="2026-10-12T00:00:00Z", synthetic=True)

    def test_47_run_time_order(self):
        with self.assertRaises(ValueError): c.build(self.binding, generated_at=LATER, validated_at=AT, synthetic=True)

    def test_48_repeat_content_identity(self):
        other = c.build(self.binding, generated_at=LATER, validated_at=LATER, synthetic=True)
        self.assertEqual(other["content_sha256"], self.bundle["content_sha256"])
        self.assertNotEqual(other["consumer_generated_at"], self.bundle["consumer_generated_at"])

    def test_49_independent_cold_read(self):
        path = self.root / "binding.json"
        bundle_path = self.root / "verdicts.json"
        write(path, self.binding)
        write(bundle_path, self.bundle)
        code = ("import sys; from pathlib import Path; from src.fundamental_ranking_consumer import pinned,verify_bundle; "
                "from src.prospective_acquisition_recovery import offline_network_guard; sys.addaudithook(offline_network_guard); "
                "b=pinned({'path':sys.argv[1],'sha256':sys.argv[2]}); "
                "v=pinned({'path':sys.argv[3],'sha256':sys.argv[4]}); "
                "verify_bundle(v,b,as_of=sys.argv[5],synthetic=True); print(v['content_sha256'])")
        answers = []
        for _ in range(2):
            result = subprocess.run([sys.executable, "-B", "-c", code, str(path), c.digest(path.read_bytes()),
                str(bundle_path), c.digest(bundle_path.read_bytes()), LATER], cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            answers.append(result.stdout.strip())
        self.assertEqual(answers, [self.bundle["content_sha256"]] * 2)

    def test_50_verdict_tamper(self):
        bundle = deepcopy(self.bundle)
        bundle["core"]["issuers"][0]["value"] = 42
        with self.assertRaises(ValueError): c.verify_bundle(bundle, self.binding, as_of=LATER, synthetic=True)

    def test_51_unknown_request_blocks(self):
        path = Path(self.binding["lineage_root"]) / "intents" / "unknown.json"
        try:
            write(path, {})
            loaded, stocks = self.read()
            with self.assertRaisesRegex(ValueError, "UNKNOWN_OUTCOME"):
                c.verify_lineage(self.binding, loaded, stocks, LATER)
        finally:
            path.unlink(missing_ok=True)

    def test_52_persisted_stop_blocks(self):
        path = Path(self.binding["lineage_root"]) / "STOP.json"
        try:
            write(path, {})
            loaded, stocks = self.read()
            with self.assertRaisesRegex(ValueError, "STOP_PRESENT"): c.verify_lineage(self.binding, loaded, stocks, LATER)
        finally:
            path.unlink(missing_ok=True)

    def test_53_synthetic_cannot_be_real(self):
        with self.assertRaises(ValueError): c.read_accepted(self.binding, as_of=LATER)

    def test_54_wrong_producer(self):
        binding = deepcopy(self.binding)
        binding["producer_main_sha"] = "a" * 40
        with self.assertRaises(ValueError): self.read(binding)

    def test_55_source_immutability(self):
        before = {str(p): c.digest(p.read_bytes()) for p in self.root.rglob("*") if p.is_file()}
        c.build(self.binding, generated_at=AT, validated_at=LATER, synthetic=True)
        after = {str(p): c.digest(p.read_bytes()) for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(before, after)

    def test_56_owner_and_weights_byte_identity(self):
        identities = c.owner_identities()
        for path, expected in c.CONTRACT["owner_code_sha256_lf"].items():
            self.assertEqual(identities[path]["code_sha256_lf"], expected)
        self.assertFalse(any(c.FLAGS[k] for k in ("renormalization_allowed", "weight_redistribution_allowed", "imputation_allowed")))

    def test_57_bridge_future_component_rejected(self):
        components = self.components()
        components["M7"]["validated_at"] = "2099-01-01T00:00:00Z"
        with self.assertRaises(ValueError): self.bridge(components=components)

    def test_58_readiness_conflict_rejected(self):
        self.reject_adaptation(lambda row: row.update(fundamental_input_status="NOT_READY_MISSING_REQUIRED_PERIOD"))

    def test_59_exact_basic_label(self):
        self.reject_adaptation(lambda row: row["feature_inputs"]["eps"]["2026Q2"].update(provider_origin_name="similar BASIC EPS"))

    def test_60_locator_tamper(self):
        self.reject_adaptation(lambda row: row["feature_inputs"]["eps"]["2026Q2"].update(json_locator="$.data[9999]"))

    def test_61_network_guard(self):
        from scripts.run_fundamental_ranking_consumer import isolation_guard
        counts = {"network_attempts": 0, "protected_write_attempts": 0}
        guard = isolation_guard(self.root, counts)
        with self.assertRaisesRegex(RuntimeError, "NETWORK_FORBIDDEN"):
            guard("socket.connect", (None, ("example.invalid", 443)))
        self.assertEqual(counts["network_attempts"], 1)

    def test_62_protected_write_guard(self):
        from scripts.run_fundamental_ranking_consumer import isolation_guard
        counts = {"network_attempts": 0, "protected_write_attempts": 0}
        output = self.root / "new-output"
        guard = isolation_guard(output, counts)
        for path in (self.root / "DecisionState.json", self.root / "Portfolio.json", self.root / "Ledger.json",
                     self.root / "Ranking.json", self.root / e.LATEST_NAME, self.root / "scheduler.json"):
            with self.subTest(path=path), self.assertRaisesRegex(RuntimeError, "PROTECTED_WRITE"):
                guard("open", (str(path), "w", 0))
        guard("open", (str(output / "new.json"), "x", 0))
        self.assertEqual(counts["protected_write_attempts"], 6)

    def test_63_no_ranking_import_or_call(self):
        import ast
        body = ast.parse((ROOT / "src/fundamental_ranking_consumer.py").read_text(encoding="utf-8"))
        called = {n.func.id for n in ast.walk(body) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        self.assertNotIn("rank_composites", called)
        self.assertNotIn("rank_candidates", called)
        self.assertIn("calculate_fundamental", called)

    def test_64_wrong_eps_type(self):
        self.reject_adaptation(lambda row: row["feature_inputs"]["eps"]["2026Q2"].update(provider_type="DILUTED"))

    def test_65_wrong_issuer_market(self):
        self.reject_adaptation(lambda row: row["feature_inputs"]["eps"]["2026Q2"].update(market="WRONG"))

    def test_66_duplicate_json_key_rejected(self):
        from src.provider_eps_metadata import read_metadata
        with self.assertRaises(ValueError): read_metadata(b'{"value":0,"value":1}')

    def test_67_source_time_retained(self):
        row = self.bundle["core"]["issuers"][0]
        self.assertEqual(row["observed_at"], AT)
        self.assertEqual(row["validated_at"], AT)
        self.assertEqual(self.bundle["consumer_validated_at"], LATER)
        self.assertFalse(self.bundle["core"]["governance"]["ranking_authorized"])
        self.assertEqual(self.bundle["core"]["governance"]["original_eight_quarter_coverage_credit"], 0)

    def test_68_cli_two_cold_processes(self):
        binding_path = self.root / "cli-binding.json"
        binding_sha = write(binding_path, self.binding)
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT).decode().strip()
        command = [sys.executable, "-B", str(ROOT / "scripts/run_fundamental_ranking_consumer.py"),
                   "--binding", str(binding_path), "--binding-sha256", binding_sha,
                   "--expected-base", c.CONTRACT["base_sha"], "--expected-head", head, "--synthetic-only"]
        first = self.root.parent / (self.root.name + "-cli-first")
        second = self.root.parent / (self.root.name + "-cli-second")
        try:
            run = subprocess.run([*command, "--output-dir", str(first)], cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            bundle = json.loads((first / "FUNDAMENTAL_OWNER_VERDICTS.json").read_bytes())
            run = subprocess.run([*command, "--output-dir", str(second), "--verify-bundle",
                                  str(first / "FUNDAMENTAL_OWNER_VERDICTS.json"), "--verdict-content-sha256",
                                  bundle["content_sha256"]], cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            other = json.loads((second / "FUNDAMENTAL_OWNER_VERDICTS.json").read_bytes())
            self.assertEqual(other, bundle)
            self.assertEqual(json.loads((second / "RUN.json").read_bytes())["audit_counters"],
                             {"network_attempts": 0, "protected_write_attempts": 0})
        finally:
            import shutil
            for path in (first, second):
                if path.exists(): shutil.rmtree(path)

    def test_69_component_requirements_preserved_without_engineering_dependency(self):
        from src.fundamental_eligibility import RANK_INPUTS, OWNERS
        self.assertEqual(c.RANK_INPUTS, RANK_INPUTS)
        self.assertEqual(c.CONTRACT["component_owners"], {k: OWNERS[k] for k in c.CONTRACT["component_owners"]})
        import ast
        body = ast.parse((ROOT / "src/fundamental_ranking_consumer.py").read_text(encoding="utf-8"))
        modules = {node.module for node in ast.walk(body) if isinstance(node, ast.ImportFrom)}
        self.assertNotIn("fundamental_eligibility", modules)
        self.assertNotIn("prospective_fundamental_provider", modules)

    def test_70_returned_artifact_cannot_mutate_contract(self):
        expected = deepcopy(c.CONTRACT["owner_code_sha256_lf"])
        bundle = c.build(self.binding, generated_at=AT, validated_at=LATER, synthetic=True)
        bundle["core"]["owner_code_sha256_lf"]["src/fundamental.py"] = "a" * 64
        self.assertEqual(c.CONTRACT["owner_code_sha256_lf"], expected)

    def test_71_independent_component_population_requires_explicit_pin(self):
        components = self.components()
        with self.assertRaisesRegex(ValueError, "INDEPENDENT_COMPONENT_POPULATION_PIN_REQUIRED"):
            c.eligibility_bridge(self.bundle, expected_content_sha256=self.bundle["content_sha256"],
                                 symbol="P0001", market="TPEX", components=components, as_of=LATER)
        self.assertNotEqual(components["M7"]["population_id"], self.bundle["core"]["population_id"])
        result = self.bridge(components=components)
        self.assertFalse(result["fundamental_ready"])
        self.assertTrue(result["gates"]["short"]["input_ready"])
        self.assertFalse(result["ranking_authorized"])


if __name__ == "__main__":
    unittest.main()
