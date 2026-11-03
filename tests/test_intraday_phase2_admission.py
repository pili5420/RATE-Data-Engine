"""Tests for authoritative intraday admission before Phase2 consumption."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.authorized_intraday_feed import IntradayQualificationError
from src.intraday_phase2_admission import (
    expected_universe_binding,
    qualify_phase2_intraday_feed,
    validate_phase2_intraday_admission,
)
from src.phase2_production import evaluate_material
from scripts.build_phase2_production_source import build_phase2_bundle

NOW = datetime(2026, 11, 4, 1, 35, 30, tzinfo=timezone.utc)
DAY = "2026-11-04"
CADENCE = "09:30"


def feed():
    trusted, _ = expected_universe_binding()
    rows = [{
        "symbol": symbol,
        "market": market,
        "timestamp": "2026-11-04T09:35:00+08:00",
        "price": 100.0,
        "volume": 1000,
        "turnover": 100000.0,
    } for symbol, market in trusted.items()]
    return {
        "artifact": "RATE_AUTHORIZED_TAIWAN_INTRADAY_FEED_V1",
        "authorization_status": "PASS",
        "validation_status": "PASS",
        "source_status": "PASS",
        "freshness_status": "PASS",
        "blocked_dependencies": [],
        "source_authority": "AUTHORIZED_TAIWAN_INTRADAY_FEED",
        "provider_authority": "CONTROL_CENTER_ACCEPTED_PROVIDER",
        "license_scope": {
            "automated_production_use": True,
            "markets": ["TWSE", "TPEX"],
        },
        "trading_date": DAY,
        "cadence": CADENCE,
        "fallback_used": False,
        "records": rows,
        "previous_state_id": "state-previous",
        "previous_state_hash": "hash-previous",
        "payload_references": [{"path": "unused.json", "sha256": "a" * 64}],
    }


class IntradayPhase2AdmissionTests(unittest.TestCase):
    def test_exact_repo_rooted_30_symbol_feed_qualifies(self):
        result = qualify_phase2_intraday_feed(feed(), trading_date=DAY, cadence=CADENCE, now_utc=NOW)
        self.assertEqual(result["validation_status"], "PASS")
        self.assertEqual(result["coverage"], "30/30")
        self.assertEqual(result["market_counts"], {"TWSE": 25, "TPEX": 5})
        self.assertEqual(len(result["feed_sha256"]), 64)
        self.assertEqual(len(result["qualification_sha256"]), 64)
        self.assertFalse(result["production_eligible"])
        self.assertEqual(result["network_requests"], 0)

    def test_substitute_same_25_plus_5_universe_fails(self):
        value = feed()
        original = value["records"][0]["symbol"]
        value["records"][0]["symbol"] = "9999"
        self.assertNotEqual(original, "9999")
        with self.assertRaises(IntradayQualificationError):
            qualify_phase2_intraday_feed(value, trading_date=DAY, cadence=CADENCE, now_utc=NOW)

    def test_stale_feed_fails_authoritative_freshness_gate(self):
        value = feed()
        value["records"][0]["timestamp"] = "2026-11-04T09:20:00+08:00"
        with self.assertRaisesRegex(IntradayQualificationError, "FRESHNESS_FAIL"):
            qualify_phase2_intraday_feed(value, trading_date=DAY, cadence=CADENCE, now_utc=NOW)

    def test_legacy_source_authority_and_status_are_still_required(self):
        cases = (
            ("source_status", "BLOCKED", "SOURCE_STATUS_NOT_PASS"),
            ("freshness_status", "BLOCKED", "FRESHNESS_STATUS_NOT_PASS"),
            ("source_authority", "OTHER", "SOURCE_AUTHORITY_INVALID"),
            ("blocked_dependencies", ["X"], "BLOCKED_DEPENDENCIES_PRESENT"),
            ("fallback_used", True, "FALLBACK_FORBIDDEN"),
        )
        for field, bad, reason in cases:
            value = feed()
            value[field] = bad
            with self.subTest(field=field), self.assertRaisesRegex(RuntimeError, reason):
                qualify_phase2_intraday_feed(value, trading_date=DAY, cadence=CADENCE, now_utc=NOW)

    def test_feed_mutation_after_admission_is_rejected(self):
        value = feed()
        admission = qualify_phase2_intraday_feed(value, trading_date=DAY, cadence=CADENCE, now_utc=NOW)
        value["records"][0]["price"] = 101.0
        with self.assertRaisesRegex(RuntimeError, "FEED_DIGEST_MISMATCH"):
            validate_phase2_intraday_admission(value, admission, trading_date=DAY, cadence=CADENCE, now_utc=NOW)

    def test_qualification_mutation_after_admission_is_rejected(self):
        value = feed()
        admission = qualify_phase2_intraday_feed(value, trading_date=DAY, cadence=CADENCE, now_utc=NOW)
        admission["qualified_payload"]["coverage"] = "29/30"
        with self.assertRaisesRegex(RuntimeError, "QUALIFICATION_DIGEST_MISMATCH"):
            validate_phase2_intraday_admission(value, admission, trading_date=DAY, cadence=CADENCE, now_utc=NOW)

    def test_admission_scope_cannot_be_reused_for_other_cadence(self):
        value = feed()
        admission = qualify_phase2_intraday_feed(value, trading_date=DAY, cadence=CADENCE, now_utc=NOW)
        with self.assertRaisesRegex(RuntimeError, "ADMISSION_SCOPE_MISMATCH"):
            validate_phase2_intraday_admission(value, admission, trading_date=DAY, cadence="12:00", now_utc=NOW)

    def test_self_resealed_forged_qualification_is_replayed_and_rejected(self):
        value = feed()
        admission = qualify_phase2_intraday_feed(value, trading_date=DAY, cadence=CADENCE, now_utc=NOW)
        forged = deepcopy(admission)
        forged["qualified_payload"]["coverage"] = "30/30"
        forged["qualified_payload"]["provider_authority"] = "FORGED_AUTHORITY"
        from src.cer074_acceptance import sha256
        forged["qualification_sha256"] = sha256(forged["qualified_payload"])
        with self.assertRaisesRegex(RuntimeError, "QUALIFICATION_REPLAY_MISMATCH"):
            validate_phase2_intraday_admission(
                value, forged, trading_date=DAY, cadence=CADENCE, now_utc=NOW
            )

    def test_admission_age_is_bounded(self):
        value = feed()
        admission = qualify_phase2_intraday_feed(value, trading_date=DAY, cadence=CADENCE, now_utc=NOW)
        later = datetime(2026, 11, 4, 1, 41, 0, tzinfo=timezone.utc)
        with self.assertRaisesRegex(RuntimeError, "ADMISSION_EXPIRED"):
            validate_phase2_intraday_admission(
                value, admission, trading_date=DAY, cadence=CADENCE, now_utc=later
            )

    def test_builder_admission_failure_happens_before_material_binding(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            feed_path = root / "feed.json"
            feed_path.write_text(json.dumps(feed()), encoding="utf-8")
            with patch.dict(os.environ, {"RATE_AUTHORIZED_INTRADAY_FEED_PATH": str(feed_path)}),                  patch("scripts.build_phase2_production_source.main_authority", return_value={"ok": True}),                  patch("scripts.build_phase2_production_source.require_intraday_authority"),                  patch("scripts.build_phase2_production_source.qualify_phase2_intraday_feed",
                       side_effect=RuntimeError("ADMISSION_FAIL")),                  patch("scripts.build_phase2_production_source.bind_input_material",
                       side_effect=AssertionError("MATERIAL_BOUND_TOO_EARLY")) as bind_mock:
                result = build_phase2_bundle(
                    trading_date=DAY,
                    cadence=CADENCE,
                    output=root / "bundle.json",
                    evidence_output=root / "evidence.json",
                    state_root=root / "state",
                    history_root=root / "history",
                )
            self.assertEqual(result["validation_status"], "FAIL_CLOSED")
            self.assertEqual(result["blocking_reason"], "ADMISSION_FAIL")
            bind_mock.assert_not_called()
            self.assertFalse((root / "bundle.json").exists())

    def test_evaluate_material_requires_admission_before_predecessor_lookup(self):
        material = {
            "cadence": CADENCE,
            "trading_date": DAY,
            "intraday_feed": feed(),
            "intraday_admission": None,
        }
        with patch("src.phase2_production.require_intraday_authority"),              patch("src.phase2_production.latest_predecessor",
                   side_effect=AssertionError("PREDECESSOR_READ_TOO_EARLY")) as predecessor:
            with self.assertRaisesRegex(RuntimeError, "ADMISSION_MISSING"):
                evaluate_material(material, {}, Path("unused"))
        predecessor.assert_not_called()

    def test_valid_admission_is_byte_bound_into_material_snapshot_inputs(self):
        value = feed()
        admission = qualify_phase2_intraday_feed(value, trading_date=DAY, cadence=CADENCE, now_utc=NOW)
        self.assertTrue(validate_phase2_intraday_admission(value, admission, trading_date=DAY, cadence=CADENCE, now_utc=NOW))
        self.assertEqual(admission["qualified_payload"]["expected_market_counts"], {"TWSE": 25, "TPEX": 5})
        self.assertEqual(admission["qualified_payload"]["selected_market_counts"], {"TWSE": 25, "TPEX": 5})


if __name__ == "__main__":
    unittest.main()
