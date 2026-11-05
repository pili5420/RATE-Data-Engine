"""Offline package pins and trusted 09:35 preflight, without credentials or I/O."""
from datetime import datetime, timedelta, timezone
import hashlib
from http.client import HTTPSConnection
import unittest
from unittest.mock import patch

from src.intraday_fugle_live_consumption_fence import canonical_digest
from src.intraday_fugle_r2_package import (
    FugleR2PackageError,
    validate_r2_package,
    validate_r2_time,
)

SOURCE = "a" * 40
WORKFLOW = ".github/workflows/rate_fugle_r2_offline_ci.yml"
FILES = {WORKFLOW: b"synthetic workflow", "src/offline.py": b"synthetic source"}
NOW = datetime(2026, 11, 5, 1, 35, 20, tzinfo=timezone.utc)


def package():
    return {
        "artifact": "RATE_FUGLE_R2_OFFLINE_PACKAGE_V1",
        "scope": "OFFLINE_CORRECTIVE_ONLY",
        "source_sha": SOURCE,
        "workflow_path": WORKFLOW,
        "workflow_sha256": hashlib.sha256(FILES[WORKFLOW]).hexdigest(),
        "permit_id": "R2-SYNTHETIC-PERMIT",
        "trigger_id": "R2-SYNTHETIC-TRIGGER",
        "trigger_created": False,
        "workflow_dispatch_allowed": False,
        "live_execution_allowed": False,
        "exchange_authority_gate": "REQUIRED_UNCHANGED",
        "admission_proposal_status": "PENDING_CONTROL_CENTER",
        "trading_date": "2026-11-05",
        "window_start_taipei": "09:35:00",
        "window_end_taipei_exclusive": "09:36:00",
        "source_files_sha256": {name: hashlib.sha256(body).hexdigest() for name, body in FILES.items()},
    }


def calendar():
    return {"status": "VERIFIED", "markets": ["TWSE", "TPEX"], "trading_dates": ["2026-11-05"]}


def clock():
    return {
        "authority_id": "SYNTHETIC-INDEPENDENT-CLOCK",
        "synchronization_status": "VERIFIED",
        "source_sha": SOURCE,
        "permit_id": "R2-SYNTHETIC-PERMIT",
        "trigger_id": "R2-SYNTHETIC-TRIGGER",
        "sampled_at_utc": NOW.isoformat(),
        "uncertainty_ms": 50,
    }


class R2PackageTests(unittest.TestCase):
    def check_package(self, value, files=None, **overrides):
        pins = {
            "expected_package_sha256": canonical_digest(value),
            "expected_source_sha": SOURCE,
            "expected_workflow_sha256": hashlib.sha256(FILES[WORKFLOW]).hexdigest(),
            "expected_permit_id": "R2-SYNTHETIC-PERMIT",
            "expected_trigger_id": "R2-SYNTHETIC-TRIGGER",
            "retired_trigger_ids": frozenset({"R2-OLD-CONSUMED-TRIGGER"}),
        }
        pins.update(overrides)
        return validate_r2_package(value, FILES if files is None else files, **pins)

    def check_time(self, value=None, cal=None, attestation=None, now=NOW, **overrides):
        value = package() if value is None else value
        cal = calendar() if cal is None else cal
        attestation = clock() if attestation is None else attestation
        pins = {
            "expected_package_sha256": canonical_digest(value),
            "expected_calendar_sha256": canonical_digest(cal),
            "expected_clock_sha256": canonical_digest(attestation),
            "trusted_clock_id": "SYNTHETIC-INDEPENDENT-CLOCK",
            "now_utc": now,
        }
        pins.update(overrides)
        return validate_r2_time(value, cal, attestation, **pins)

    def test_exact_r2_package_and_time_preflight_are_offline_only(self):
        with patch("os.getenv", side_effect=AssertionError("Credential access forbidden")) as credentials, patch.object(
            HTTPSConnection, "__init__", side_effect=AssertionError("Network forbidden")
        ) as connection:
            result = self.check_package(package())
            timing = self.check_time()
        self.assertEqual(result["validation_status"], "PASS")
        self.assertEqual(timing["validation_status"], "PASS")
        self.assertFalse(result["live_execution_allowed"])
        credentials.assert_not_called()
        connection.assert_not_called()

    def test_source_workflow_permit_trigger_pins_and_retired_trigger_fail_closed(self):
        for field, replacement in (
            ("source_sha", "b" * 40), ("workflow_sha256", "c" * 64),
            ("permit_id", "R2-OTHER"), ("trigger_id", "R2-OLD-CONSUMED-TRIGGER"),
        ):
            value = package()
            value[field] = replacement
            with self.subTest(field=field), self.assertRaises(FugleR2PackageError):
                self.check_package(value)
        with self.assertRaisesRegex(FugleR2PackageError, "TRIGGER_REUSE"):
            self.check_package(package(), retired_trigger_ids=frozenset({"R2-SYNTHETIC-TRIGGER"}))

    def test_immutable_package_pin_inventory_and_source_integrity(self):
        with self.assertRaisesRegex(FugleR2PackageError, "PACKAGE_PIN"):
            self.check_package(package(), expected_package_sha256="0" * 64)
        for files in ({WORKFLOW: FILES[WORKFLOW]}, {**FILES, "extra": b"extra"}):
            with self.subTest(files=list(files)), self.assertRaisesRegex(FugleR2PackageError, "INVENTORY"):
                self.check_package(package(), files)
        with self.assertRaisesRegex(FugleR2PackageError, "SOURCE_BYTES"):
            self.check_package(package(), {**FILES, WORKFLOW: b"tampered"})

    def test_execution_and_gate_bypass_are_forbidden(self):
        for field, replacement in (
            ("live_execution_allowed", True), ("workflow_dispatch_allowed", True),
            ("trigger_created", True), ("exchange_authority_gate", "WAIVED"),
            ("admission_proposal_status", "APPROVED"),
        ):
            value = package()
            value[field] = replacement
            with self.subTest(field=field), self.assertRaises(FugleR2PackageError):
                self.check_package(value)

    def test_wrong_date_closed_market_and_calendar_pin_fail(self):
        value = package()
        value["trading_date"] = "2026-11-06"
        with self.assertRaisesRegex(FugleR2PackageError, "NOT_TRADING_DAY"):
            self.check_time(value)
        cal = calendar()
        cal["trading_dates"] = []
        with self.assertRaisesRegex(FugleR2PackageError, "NOT_TRADING_DAY"):
            self.check_time(cal=cal)
        with self.assertRaisesRegex(FugleR2PackageError, "CALENDAR_PIN"):
            self.check_time(expected_calendar_sha256="0" * 64)
        with self.assertRaisesRegex(FugleR2PackageError, "TRADING_DATE_MISMATCH"):
            self.check_time(now=NOW + timedelta(days=1), attestation={**clock(), "sampled_at_utc": (NOW + timedelta(days=1)).isoformat()})

    def test_clock_failure_unknown_source_and_replay_block(self):
        for field, replacement in (
            ("synchronization_status", "UNKNOWN"), ("authority_id", "UNTRUSTED"),
            ("source_sha", "b" * 40), ("permit_id", "R2-OTHER"),
            ("trigger_id", "R2-OTHER"), ("uncertainty_ms", 1001),
            ("sampled_at_utc", "bad timestamp"), ("sampled_at_utc", "2026-11-05T09:35:20"),
        ):
            value = clock()
            value[field] = replacement
            with self.subTest(field=field, replacement=replacement), self.assertRaises(FugleR2PackageError):
                self.check_time(attestation=value)
        with self.assertRaisesRegex(FugleR2PackageError, "CLOCK_PIN"):
            self.check_time(expected_clock_sha256="0" * 64)

    def test_stale_future_and_naive_clock_fail(self):
        for now in (NOW + timedelta(seconds=6), NOW - timedelta(seconds=1), NOW.replace(tzinfo=None)):
            with self.subTest(now=now), self.assertRaises(FugleR2PackageError):
                self.check_time(now=now)

    def test_clock_cannot_admit_an_unpinned_or_incomplete_package(self):
        with self.assertRaisesRegex(FugleR2PackageError, "PACKAGE_PIN"):
            self.check_time(expected_package_sha256="0" * 64)
        value = package()
        attestation = clock()
        for key in ("source_sha", "permit_id", "trigger_id"):
            value.pop(key)
            attestation.pop(key)
        with self.assertRaisesRegex(FugleR2PackageError, "PACKAGE_BINDING"):
            self.check_time(value=value, attestation=attestation)

    def test_window_boundaries_and_clock_uncertainty_fail_closed(self):
        for stamp in ("2026-11-05T01:34:59+00:00", "2026-11-05T01:35:00+00:00", "2026-11-05T01:36:00+00:00"):
            attestation = {**clock(), "sampled_at_utc": stamp}
            with self.subTest(stamp=stamp), self.assertRaisesRegex(FugleR2PackageError, "OUTSIDE_0935"):
                self.check_time(now=datetime.fromisoformat(stamp), attestation=attestation)
        for field in ("window_start_taipei", "window_end_taipei_exclusive"):
            value = package()
            value[field] = "10:00:00"
            with self.subTest(field=field), self.assertRaisesRegex(FugleR2PackageError, "WINDOW_POLICY"):
                self.check_time(value=value)


if __name__ == "__main__":
    unittest.main()
