import hashlib
import json
import os
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import build_live_source_bundle as builder
from scripts.resolve_staging_universe import canonical_digest, resolve

STATE = "RATE-V11.1-PS-20260913-V1-r000009"
STATE_HASH = "f1cc9c5f005a07f081943e279cfab9624079d51ae7d3ef1f1e23ef74b638864b"
SYMBOLS = ["3231", "6274", "3443", "6669", "2313", "2449", "3413", "3081", "6187", "2368", "6442", "3017", "2345", "3661", "3037", "2383", "2317", "2330", "2376", "2356", "5388", "2344", "2337", "2408", "3035", "3034", "6510", "3036", "3014", "3227"]
DIGEST = "30276287608b87f7d9b606891514247da523dce9214e4b82bb34ba118a35af4c"


class CER056UniverseTests(unittest.TestCase):
    def _load_payload(self, obj):
        root = Path("artifacts/test_cer056_tmp")
        root.mkdir(parents=True, exist_ok=True)
        path = root / "u.json"
        try:
            path.write_text(json.dumps(obj), encoding="utf-8")
            with patch.dict(os.environ, {"RATE_TWSE_SYMBOLS": "", "RATE_UNIVERSE_FILE": str(path)}, clear=True):
                return builder._load_universe()
        finally:
            shutil.rmtree(root, ignore_errors=True)
    def test_list_str_parser(self):
        self.assertEqual([x["symbol"] for x in builder._parse_universe_payload(["2330", "2317"])], ["2330", "2317"])

    def test_list_dict_parser(self):
        self.assertEqual(builder._parse_universe_payload([{"symbol": "2330", "market": "TWSE"}])[0]["symbol"], "2330")

    def test_dict_symbols_parsers(self):
        self.assertEqual(len(builder._parse_universe_payload({"symbols": ["2330"]})), 1)
        self.assertEqual(builder._parse_universe_payload({"symbols": [{"symbol": "2330", "market": "TWSE"}]})[0]["market"], "TWSE")

    def test_exact_approved_symbols_and_digest(self):
        self.assertEqual(len(SYMBOLS), 30)
        self.assertEqual(canonical_digest(STATE, SYMBOLS), DIGEST)

    def test_duplicate_rejection(self):
        with self.assertRaisesRegex(RuntimeError, "INVALID_PRODUCTION_UNIVERSE_AUTHORITY"):
            self._load_payload({"symbols": [{"symbol": "2330", "market": "TWSE"}, {"symbol": "2330", "market": "TWSE"}]})

    def test_taiex_exclusion(self):
        with self.assertRaisesRegex(RuntimeError, "INVALID_PRODUCTION_UNIVERSE_AUTHORITY"):
            self._load_payload({"symbols": [{"symbol": "TAIEX", "market": "TWSE"}]})

    def test_wrong_market_rejection(self):
        with self.assertRaisesRegex(RuntimeError, "INVALID_PRODUCTION_UNIVERSE_AUTHORITY"):
            self._load_payload({"symbols": [{"symbol": "2330", "market": "UNKNOWN"}]})

    def test_fixture_authority_rejection(self):
        with self.assertRaisesRegex(RuntimeError, "INVALID_PRODUCTION_UNIVERSE_AUTHORITY"):
            self._load_payload({"artifact": "fixture-snapshot-a2", "symbols": SYMBOLS})

    def test_record_count_mismatch_rejection(self):
        with self.assertRaisesRegex(RuntimeError, "RECORD_COUNT"):
            self._load_payload({"artifact": "CONTROL_CENTER_APPROVED_STAGING_VALIDATION_UNIVERSE_V1", "schema_version": "RATE-UNIVERSE-V1.0", "validation_scope": "STAGING_LIVE_ONLY", "ranking_status": "NOT_A_VALIDATED_TOP30_RANKING", "source_state_id": STATE, "source_state_file_sha256": STATE_HASH, "validation_status": "PASS", "symbols": []})

    def test_empty_fail_closed(self):
        with patch.dict(os.environ, {"RATE_TWSE_SYMBOLS": "", "RATE_UNIVERSE_FILE": ""}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "RATE_TWSE_SYMBOLS_OR_RATE_UNIVERSE_FILE"):
                builder._load_universe()

    def test_resolver_market_classification(self):
        twse = [{"Code": s, "Name": s} for s in SYMBOLS[:25]]
        tpex = [{"SecuritiesCompanyCode": s, "CompanyName": s} for s in SYMBOLS[25:]]
        out = Path("artifacts/test_cer056_manifest.json")
        try:
            result = resolve(Path("config/staging/RATE_STAGING_UNIVERSE_APPROVAL_V1.json"), out, twse_payload=twse, tpex_payload=tpex)
            self.assertEqual(result["record_count"], 30)
            self.assertEqual(result["markets"], {"TWSE": 25, "TPEX": 5})
            self.assertTrue(all(x["market"] in ("TWSE", "TPEX") for x in result["symbols"]))
        finally:
            out.unlink(missing_ok=True)

    def test_committed_manifest_contract(self):
        with patch.dict(os.environ, {"RATE_TWSE_SYMBOLS": "", "RATE_UNIVERSE_FILE": "config/staging/RATE_STAGING_LIVE_UNIVERSE_V1.json"}, clear=True):
            result = builder._load_universe()
            self.assertEqual(len(result), 30)
            self.assertEqual(builder.UNIVERSE_CONTEXT["twse_count"] + builder.UNIVERSE_CONTEXT["tpex_count"], 30)


if __name__ == "__main__":
    unittest.main()
