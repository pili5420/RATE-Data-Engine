import copy
import shutil
import unittest
from pathlib import Path

from src.historical_store import PersistentHistoricalStore
from src.ois_historical_revision import (
    REVISION_ID,
    apply_controlled_revision,
    build_default_revision_request,
    history_digest,
    materialize_fixture_history,
    normalize_fixture_history,
    run_acceptance,
)


class OISHistoricalRevisionRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.root = Path("artifacts/test_ois_hr001")
        shutil.rmtree(self.root, ignore_errors=True)
        self.stocks, self.benchmarks = normalize_fixture_history(
            "tests/fixtures/technical_replay_30x180.json",
            source_timestamp="2026-09-10T18:00:00Z",
            ingested_at="2026-09-11T00:00:00Z",
        )
        self.symbols = sorted(self.stocks)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _store(self, name="history"):
        store = PersistentHistoricalStore(self.root / name)
        materialize_fixture_history(store, self.stocks, self.benchmarks)
        return store

    def test_controlled_revision_rebuilds_history_deterministically(self):
        first = self._store("first")
        replay = self._store("replay")
        request = build_default_revision_request(self.stocks)
        before = history_digest(first, self.symbols)
        result = apply_controlled_revision(first, request)
        replay_result = apply_controlled_revision(replay, request)
        self.assertEqual(result["validation_status"], "PASS")
        self.assertEqual(replay_result["validation_status"], "PASS")
        self.assertNotEqual(before, history_digest(first, self.symbols))
        self.assertEqual(history_digest(first, self.symbols), history_digest(replay, self.symbols))

    def test_unapproved_revision_fails_closed_without_weakening_store_gate(self):
        store = self._store("fail")
        request = build_default_revision_request(self.stocks)
        request["revision_evidence_status"] = "FAIL"
        before = history_digest(store, self.symbols)
        result = apply_controlled_revision(store, request)
        self.assertEqual(result["validation_status"], "FAIL")
        self.assertTrue(result["publish_blocked"])
        self.assertEqual(before, history_digest(store, self.symbols))
        conflict = copy.deepcopy(self.stocks["1000"][-1])
        conflict["close"] += 100
        with self.assertRaises(ValueError):
            store.upsert_stock("1000", [conflict])

    def test_revision_id_and_before_hash_are_required(self):
        store = self._store("invalid")
        request = build_default_revision_request(self.stocks)
        request["revision_id"] = "HISTORICAL_SOURCE_REVISION:BAD"
        self.assertEqual(apply_controlled_revision(store, request)["validation_status"], "FAIL")
        request = build_default_revision_request(self.stocks)
        request["affected_rows"][0]["before_hash"] = "bad"
        self.assertEqual(apply_controlled_revision(store, request)["validation_status"], "FAIL")

    def test_acceptance_outputs_wfa_pass_and_four_published_production_jsons(self):
        summary = run_acceptance(output_dir=self.root / "acceptance", commit_sha="test-sha", run_id="test-run", job_id="test-job")
        self.assertEqual(summary["revision_id"], REVISION_ID)
        self.assertEqual(summary["wfa_001_ois_w1"], "PASS")
        self.assertTrue(summary["published"])
        self.assertEqual(summary["four_production_json_lineage"], "PASS")
        self.assertEqual(summary["production_json_count"], 4)
        for cadence in ("0730", "0930", "1200", "1930"):
            self.assertTrue((self.root / "acceptance" / f"RATE_OIS_HR001_PRODUCTION_{cadence}.json").exists())


if __name__ == "__main__":
    unittest.main()
