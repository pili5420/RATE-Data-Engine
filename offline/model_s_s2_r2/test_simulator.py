"""Offline adversarial tests; every identity, byte and clock is synthetic."""

import copy
import os
import shutil
import tempfile
import threading
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from simulator import (Decision, ReceiptAuthority, ReplayLedger, RetentionMachine,
                       SyntheticTrust, FROZEN_C03_SHA256, at, canonical, digest, review_acceptance)


class ModelSOfflineTests(unittest.TestCase):
    def setUp(self):
        base = Path(os.environ.get("MODEL_S_S2_TEST_TMP", tempfile.gettempdir())).resolve()
        self.tmp = base / ("SYNTHETIC_model_s_" + uuid.uuid4().hex)
        self.tmp.mkdir()
        self.addCleanup(self._clean_tmp, base)
        self.now = datetime(2030, 1, 1, 12, tzinfo=timezone.utc)
        self.scope = "SYNTHETIC_CUSTODY_SCOPE"
        self.authority = "SYNTHETIC_RECEIPT_AUTHORITY"
        self.owner = "SYNTHETIC_OWNER_A"
        self.trust = SyntheticTrust()
        self.trust.register(self.authority, b"SYNTHETIC_TEST_AUTHORITY_KEY_32_BYTES_LONG", self.scope)
        self.trust.register(self.owner, b"SYNTHETIC_TEST_OWNER_KEY_32_BYTES_LONG_____", self.scope)
        self.ledger = ReplayLedger(self.tmp / "ledger.sqlite")
        self.receiver = ReceiptAuthority(self.trust, self.ledger, self.authority, self.scope)
        self.package_document = {
            "schema": "SYNTHETIC_EVIDENCE_V1", "frozen_c03_sha256": FROZEN_C03_SHA256,
            "complete": True, "redaction_pass": True,
            "commands": [{"id": "SYNTHETIC_W01", "sha256": digest(b"synthetic-command")}],
            "results": [{"id": "SYNTHETIC_W01", "sha256": digest(b"synthetic-result")}],
        }
        self.package = canonical(self.package_document)
        self.payload = {"kind": "RECEIPT_ACCEPTED", "token": "SYNTHETIC_RECEIPT_1",
                        "scope": self.scope, "run_id": "SYNTHETIC_RUN_1", "attempt": 1,
                        "package_sha256": digest(self.package), "package_length": len(self.package),
                        "issued_at": at(self.now - timedelta(minutes=1)),
                        "expires_at": at(self.now + timedelta(minutes=5))}
        self._deletion_fixture_sequence = 0

    def _clean_tmp(self, base):
        if self.tmp.resolve().parent != base or not self.tmp.name.startswith("SYNTHETIC_model_s_"):
            raise RuntimeError("UNSAFE_TEST_CLEANUP_TARGET")
        shutil.rmtree(self.tmp)

    def signed_receipt(self, **changes):
        return self.trust.sign(self.authority, {**self.payload, **changes})

    def receipt(self, **changes):
        return self.receiver.accept(self.signed_receipt(**changes), self.package, self.now)

    def manifest(self):
        return {"sha256": digest(self.package), "length": len(self.package),
                "complete": True, "redaction_pass": True,
                "frozen_c03_sha256": FROZEN_C03_SHA256,
                "commands": copy.deepcopy(self.package_document["commands"]),
                "results": copy.deepcopy(self.package_document["results"])}

    def review(self, receipt=None, manifest=None, owner_signed=None, **bindings):
        receipt = receipt or self.receipt()
        p = {"kind": "OWNER_ATTESTATION", "scope": self.scope,
             "run_id": "SYNTHETIC_RUN_1", "attempt": 1,
             "package_sha256": digest(self.package), "receipt_binding": (receipt.evidence or {}).get("binding", "0" * 64)}
        signed = owner_signed or self.trust.sign(self.owner, p)
        return review_acceptance(package=self.package, manifest=manifest or self.manifest(),
                                 receipt=receipt, owner_signed=signed, trust=self.trust,
                                 ledger=self.ledger, scope=self.scope,
                                 run_id=bindings.get("run_id", "SYNTHETIC_RUN_1"),
                                 attempt=bindings.get("attempt", 1), now=self.now)

    def ready_deletion(self):
        self._deletion_fixture_sequence += 1
        receipt = self.receiver.accept(self.signed_receipt(token=f"SYNTHETIC_DELETE_FIXTURE_{self._deletion_fixture_sequence}"), self.package, self.now)
        review = self.review(receipt=receipt)
        machine = RetentionMachine()
        machine.pending()
        self.start_retention(machine, receipt)
        machine.tick(self.now + timedelta(days=30))
        copies = [{"id": "SYNTHETIC_PRIMARY", "known": True, "encrypted": True,
                   "sha256": digest(self.package)},
                  {"id": "SYNTHETIC_BACKUP", "known": True, "encrypted": True,
                   "sha256": digest(self.package)}]
        signed = self.trust.sign(self.owner, {"kind": "DELETE_AUTHORIZE", "scope": self.scope,
                                              "receipt_sha256": digest(self.package),
                                              "copies_sha256": digest(canonical(copies)),
                                              "token": f"SYNTHETIC_DELETE_AUTH_{self._deletion_fixture_sequence}",
                                              "issued_at": at(self.now + timedelta(days=30)),
                                              "expires_at": at(self.now + timedelta(days=30, minutes=5))})
        return machine, review, copies, signed

    def start_retention(self, machine, receipt):
        return machine.accept(receipt, ledger=self.ledger, scope=self.scope,
                              run_id="SYNTHETIC_RUN_1", attempt=1,
                              package_sha256=digest(self.package))

    def delete(self, machine, review, copies, signed, **changes):
        args = dict(signed=signed, trust=self.trust, scope=self.scope,
                    now=self.now + timedelta(days=30), review=review,
                    legal_hold=False, incident_hold=False, review_hold=False,
                    copies=copies, receipt_sha256=digest(self.package), ledger=self.ledger)
        args.update(changes)
        return machine.authorize_deletion(**args)

    def test_01_valid_synthetic_receipt_and_anchor(self):
        result = self.receipt()
        self.assertEqual(result.status, "PASS")
        self.assertFalse(result.evidence["operational_authorization"])
        self.assertEqual(self.ledger.verify_chain().status, "PASS")

    def test_02_forged_signature(self):
        forged = self.signed_receipt()
        forged["signature"] = "0" * 64
        self.assertEqual(self.receiver.accept(forged, self.package, self.now).reason, "SIGNATURE_INVALID")

    def test_03_invalid_authority_identity(self):
        signed = self.signed_receipt()
        signed["identity"] = "SYNTHETIC_UNKNOWN"
        self.assertEqual(self.receiver.accept(signed, self.package, self.now).reason, "AUTHORITY_UNKNOWN")

    def test_04_expired_authority(self):
        self.assertEqual(self.receipt(expires_at=at(self.now)).reason, "AUTHORITY_EXPIRED_OR_FUTURE")

    def test_05_revoked_authority(self):
        self.trust.revoke(self.authority, self.now)
        self.assertEqual(self.receipt().reason, "AUTHORITY_REVOKED")

    def test_06_duplicate_receipt_and_reentry(self):
        self.assertEqual(self.receipt().status, "PASS")
        self.assertEqual(self.receipt().reason, "REPLAY_OR_REENTRY")

    def test_07_replay_after_restart(self):
        self.receipt()
        restarted = ReceiptAuthority(self.trust, ReplayLedger(self.ledger.path), self.authority, self.scope)
        self.assertEqual(restarted.accept(self.signed_receipt(), self.package, self.now).reason, "REPLAY_OR_REENTRY")

    def test_08_cross_run_attempt_scope(self):
        self.assertEqual(self.receipt(run_id="REAL_RUN").reason, "RUN_OR_SCOPE_INVALID")
        self.assertEqual(self.receipt(attempt=0).reason, "ATTEMPT_INVALID")
        self.assertEqual(self.receipt(scope="SYNTHETIC_WRONG").reason, "RUN_OR_SCOPE_INVALID")

    def test_09_lost_ack_is_unknown_and_reentry_blocked(self):
        result = self.receiver.accept(self.signed_receipt(), self.package, self.now, failure="lost_ack")
        self.assertEqual(result.status, "UNKNOWN")
        self.assertEqual(self.ledger.verify_chain().status, "PASS")
        self.assertEqual(self.receipt().reason, "REPLAY_OR_REENTRY")

    def test_10_concurrent_duplicate_one_ack(self):
        results = []
        lock = threading.Lock()
        barrier = threading.Barrier(6)
        def call():
            barrier.wait()
            result = self.receipt()
            with lock:
                results.append(result.status)
        threads = [threading.Thread(target=call) for _ in range(6)]
        for t in threads: t.start()
        for t in threads: t.join()
        self.assertEqual(results.count("PASS"), 1)
        self.assertEqual(results.count("BLOCKED"), 5)

    def test_11_partial_persistence_rolls_back(self):
        result = self.receiver.accept(self.signed_receipt(), self.package, self.now, failure="before_anchor")
        self.assertEqual(result.status, "UNKNOWN")
        self.assertEqual(self.ledger.verify_chain().evidence["count"], 0)
        self.assertEqual(self.receipt().reason, "REPLAY_OR_REENTRY")

    def test_12_rollback_failure_injection(self):
        result = self.receiver.accept(self.signed_receipt(), self.package, self.now, failure="before_commit")
        self.assertEqual(result.status, "UNKNOWN")
        self.assertEqual(self.ledger.verify_chain().evidence["count"], 0)
        self.assertEqual(self.receipt().reason, "REPLAY_OR_REENTRY")

    def test_13_tampered_anchor_rejected(self):
        self.receipt()
        with self.ledger._connect() as db:
            db.execute("UPDATE anchors SET hash=?", ("0" * 64,))
        self.assertEqual(self.ledger.verify_chain().reason, "ANCHOR_TAMPERED")

    def test_14_missing_or_wrong_package(self):
        self.assertEqual(self.receipt(package_sha256="0" * 64).reason, "PACKAGE_DIGEST_OR_LENGTH")
        self.assertEqual(self.receipt(package_length=0).reason, "PACKAGE_DIGEST_OR_LENGTH")

    def test_15_invalid_timestamp_and_clock(self):
        self.assertEqual(self.receipt(issued_at="2030-01-01T12:00:00+00:00").reason, "TIME_INVALID")
        self.assertEqual(self.receiver.accept(self.signed_receipt(), self.package, datetime(2030, 1, 1)).reason, "CLOCK_UNKNOWN")

    def test_16_valid_review_is_technical_only(self):
        result = self.review()
        self.assertEqual(result.reason, "TECHNICAL_VALIDATION_ONLY")
        self.assertFalse(result.evidence["independent_human_review"])

    def test_17_review_missing_evidence(self):
        manifest = self.manifest(); manifest["complete"] = False
        self.assertEqual(self.review(manifest=manifest).reason, "EVIDENCE_INCOMPLETE")

    def test_18_review_manifest_hash_mismatch(self):
        manifest = self.manifest(); manifest["sha256"] = "0" * 64
        self.assertEqual(self.review(manifest=manifest).reason, "MANIFEST_DIGEST_OR_LENGTH")

    def test_19_review_unauthorized_owner(self):
        receipt = self.receipt()
        forged = self.trust.sign(self.authority, {"kind": "OWNER_ATTESTATION"})
        self.assertEqual(self.review(receipt=receipt, owner_signed=forged).reason, "OWNER_IDENTITY_INVALID")

    def test_20_review_cross_run_and_attempt(self):
        receipt = self.receipt()
        self.assertEqual(self.review(receipt=receipt, run_id="SYNTHETIC_OTHER").reason, "RECEIPT_BINDING_MISMATCH")
        self.assertEqual(self.review(receipt=receipt, attempt=2).reason, "RECEIPT_BINDING_MISMATCH")

    def test_21_review_fabricated_receipt_rejected(self):
        fake = Decision("PASS", "SYNTHETIC_RECEIPT_ACCEPTED", {"binding": "0" * 64,
                "anchor": "0" * 64, "token": "SYNTHETIC_FAKE", "scope": self.scope,
                "run_id": "SYNTHETIC_RUN_1", "attempt": 1,
                "package_sha256": digest(self.package), "operational_authorization": False})
        self.assertEqual(self.review(receipt=fake).reason, "RECEIPT_ANCHOR_UNVERIFIED")

    def test_22_review_receipt_lost_ack_rejected(self):
        lost = self.receiver.accept(self.signed_receipt(), self.package, self.now, failure="lost_ack")
        self.assertEqual(self.review(receipt=lost).reason, "RECEIPT_NOT_ACCEPTED")

    def test_23_retention_valid_transitions(self):
        receipt = self.receipt(); m = RetentionMachine()
        self.assertEqual(m.pending().reason, "RECEIPT_PENDING")
        self.assertEqual(self.start_retention(m, receipt).reason, "RECEIPT_ACCEPTED")
        self.assertEqual(m.tick(self.now + timedelta(days=29)).reason, "RETENTION_ACTIVE")
        self.assertEqual(m.tick(self.now + timedelta(days=30)).reason, "RETENTION_EXPIRED")

    def test_24_retention_does_not_start_without_receipt(self):
        m = RetentionMachine(); m.pending()
        self.assertEqual(self.start_retention(m, Decision("UNKNOWN", "ACK_LOST_FAIL_CLOSED")).status, "BLOCKED")
        self.assertIsNone(m.accepted_at)

    def test_25_invalid_retention_timestamp(self):
        m = RetentionMachine(); m.pending()
        self.assertEqual(self.start_retention(m, Decision("PASS", "SYNTHETIC_RECEIPT_ACCEPTED", {"receipt_at": "not-utc"})).reason, "INVALID_RETENTION_TIMESTAMP")

    def test_26_premature_deletion(self):
        m, review, copies, signed = self.ready_deletion()
        m.state = "RETENTION_ACTIVE"
        self.assertEqual(self.delete(m, review, copies, signed).reason, "RETENTION_NOT_EXPIRED")

    def test_27_legal_and_incident_hold(self):
        for hold in ("legal_hold", "incident_hold", "review_hold"):
            m, review, copies, signed = self.ready_deletion()
            self.assertEqual(self.delete(m, review, copies, signed, **{hold: True}).reason, "HOLD_OR_COPY_UNKNOWN")

    def test_28_missing_backup_or_residual_copy_evidence(self):
        m, review, copies, signed = self.ready_deletion()
        self.assertEqual(self.delete(m, review, [], signed).reason, "HOLD_OR_COPY_UNKNOWN")
        m, review, copies, signed = self.ready_deletion()
        copies[1]["known"] = False
        self.assertEqual(self.delete(m, review, copies, signed).reason, "HOLD_OR_COPY_UNKNOWN")

    def test_29_cross_scope_deletion_authorization(self):
        m, review, copies, signed = self.ready_deletion()
        signed["payload"]["scope"] = "SYNTHETIC_WRONG"
        self.assertEqual(self.delete(m, review, copies, signed).reason, "OWNER_AUTHORIZATION_INVALID")

    def test_30_valid_deletion_is_simulation_only(self):
        m, review, copies, signed = self.ready_deletion()
        result = self.delete(m, review, copies, signed)
        self.assertFalse(result.evidence["real_deletion"])
        self.assertEqual(m.deletion_pending().reason, "DELETION_PENDING")
        confirmed = self.signed_confirmation(copies)
        self.assertEqual(m.verify_deletion(confirmed, copies=copies, trust=self.trust,
                                          ledger=self.ledger, scope=self.scope,
                                          now=self.now + timedelta(days=30)).reason, "DELETION_VERIFIED")

    def signed_confirmation(self, copies):
        return self.trust.sign(self.authority, {
            "kind": "SYNTHETIC_DELETION_CONFIRMATION", "scope": self.scope,
            "token": "SYNTHETIC_DELETE_CONFIRM_1", "receipt_sha256": digest(self.package),
            "copies_sha256": digest(canonical(copies)), "all_copies_accounted": True,
            "real_deletion": False, "issued_at": at(self.now + timedelta(days=30)),
            "expires_at": at(self.now + timedelta(days=30, minutes=5))})

    def test_31_invalid_deletion_receipt(self):
        m, review, copies, signed = self.ready_deletion()
        self.delete(m, review, copies, signed); m.deletion_pending()
        self.assertEqual(m.verify_deletion({"kind": "SYNTHETIC_DELETION_CONFIRMATION"}, copies=copies,
                                          trust=self.trust, ledger=self.ledger, scope=self.scope,
                                          now=self.now + timedelta(days=30)).reason, "DELETION_RECEIPT_INVALID")

    def test_32_revocation_during_processing(self):
        m, review, copies, signed = self.ready_deletion()
        self.trust.revoke(self.owner, self.now + timedelta(days=29))
        self.assertEqual(self.delete(m, review, copies, signed).reason, "OWNER_AUTHORIZATION_INVALID")

    def test_33_review_binding_mismatch_blocks_deletion(self):
        m, review, copies, signed = self.ready_deletion()
        self.assertEqual(self.delete(m, review, copies, signed, receipt_sha256="0" * 64).reason, "REVIEW_BINDING_MISMATCH")

    def test_34_unknown_copy_and_duplicate_inventory(self):
        m, review, copies, signed = self.ready_deletion()
        copies[1]["id"] = copies[0]["id"]
        self.assertEqual(self.delete(m, review, copies, signed).reason, "DUPLICATE_COPY")

    def test_35_no_operational_trust_root(self):
        with self.assertRaises(ValueError):
            self.trust.register("PRODUCTION_AUTHORITY", b"x" * 32, self.scope)

    def test_36_extra_receipt_field_rejected(self):
        self.assertEqual(self.receipt(unapproved=True).reason, "RECEIPT_SCHEMA")

    def test_37_fabricated_success_cannot_start_retention(self):
        m = RetentionMachine(); m.pending()
        fake = Decision("PASS", "SYNTHETIC_RECEIPT_ACCEPTED", {
            "receipt_at": at(self.now), "token": "SYNTHETIC_FAKE", "binding": "0" * 64,
            "anchor": "0" * 64, "scope": self.scope, "run_id": "SYNTHETIC_RUN_1",
            "attempt": 1, "package_sha256": digest(self.package),
            "operational_authorization": False})
        self.assertEqual(self.start_retention(m, fake).reason, "RECEIPT_ANCHOR_UNVERIFIED")
        self.assertIsNone(m.accepted_at)

    def test_38_unknown_claim_survives_restart(self):
        self.assertEqual(self.receiver.accept(self.signed_receipt(), self.package, self.now,
                                              failure="after_claim").status, "UNKNOWN")
        restarted = ReceiptAuthority(self.trust, ReplayLedger(self.ledger.path), self.authority, self.scope)
        self.assertEqual(restarted.accept(self.signed_receipt(), self.package, self.now).reason, "REPLAY_OR_REENTRY")

    def test_39_revocation_after_ack_fails_closed(self):
        result = self.receiver.accept(self.signed_receipt(), self.package, self.now,
                                      failure="revoke_after_ack")
        self.assertEqual(result.reason, "AUTHORITY_REVOKED_DURING_PROCESSING")
        self.assertEqual(self.ledger.verify_chain().status, "PASS")

    def test_40_deletion_authorization_lost_ack_burns_token(self):
        m, review, copies, signed = self.ready_deletion()
        self.assertEqual(self.delete(m, review, copies, signed, failure="lost_ack").reason,
                         "DELETION_OWNERSHIP_UNKNOWN")
        m2, _, _, _ = self.ready_deletion()
        self.assertEqual(self.delete(m2, review, copies, signed).reason, "DELETION_REPLAY")

    def test_41_forged_deletion_confirmation(self):
        m, review, copies, signed = self.ready_deletion()
        self.delete(m, review, copies, signed); m.deletion_pending()
        forged = self.signed_confirmation(copies)
        forged["signature"] = "0" * 64
        self.assertEqual(m.verify_deletion(forged, copies=copies, trust=self.trust,
                                          ledger=self.ledger, scope=self.scope,
                                          now=self.now + timedelta(days=30)).reason, "DELETION_RECEIPT_INVALID")

    def test_42_deletion_authorization_expired(self):
        m, review, copies, signed = self.ready_deletion()
        self.assertEqual(self.delete(m, review, copies, signed,
                                     now=self.now + timedelta(days=31)).reason, "DELETION_AUTH_EXPIRED")

    def test_43_receipt_timestamp_tamper_cannot_advance_retention(self):
        receipt = self.receipt()
        altered = copy.deepcopy(receipt)
        altered.evidence["receipt_at"] = at(self.now - timedelta(days=31))
        m = RetentionMachine(); m.pending()
        self.assertEqual(self.start_retention(m, altered).reason, "RECEIPT_ANCHOR_UNVERIFIED")
        self.assertEqual(self.review(receipt=altered).reason, "RECEIPT_ANCHOR_UNVERIFIED")

    def test_44_non_synthetic_ledger_path_rejected(self):
        with self.assertRaises(ValueError):
            ReplayLedger(self.tmp.parent / "production.sqlite")

    def test_45_receipt_rejects_bad_c03_and_redaction(self):
        for key, value in (("frozen_c03_sha256", "0" * 64), ("redaction_pass", False)):
            altered = {**self.package_document, key: value}
            bad_package = canonical(altered)
            signed = self.signed_receipt(package_sha256=digest(bad_package),
                                         package_length=len(bad_package))
            self.assertEqual(self.receiver.accept(signed, bad_package, self.now).reason,
                             "PACKAGE_SCHEMA_OR_REDACTION")

    def test_46_receipt_rejects_missing_result_mapping(self):
        altered = {**self.package_document, "results": []}
        bad_package = canonical(altered)
        signed = self.signed_receipt(package_sha256=digest(bad_package),
                                     package_length=len(bad_package))
        self.assertEqual(self.receiver.accept(signed, bad_package, self.now).reason,
                         "PACKAGE_SCHEMA_OR_REDACTION")

    def test_47_review_rejects_manifest_mapping_tamper(self):
        m = self.manifest()
        m["results"][0]["sha256"] = "0" * 64
        self.assertEqual(self.review(manifest=m).reason, "EVIDENCE_INCOMPLETE")


if __name__ == "__main__":
    unittest.main()
