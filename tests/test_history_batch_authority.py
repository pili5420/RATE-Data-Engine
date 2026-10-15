"""SYNTHETIC ONLY: temporary keys and isolated journals, never real authorization."""
import base64
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from src.prospective_acquisition_recovery import offline_network_guard
import sys
sys.addaudithook(offline_network_guard)
from src import history_batch_authority as a
from tests.batch_synthetic_support import Fixture, AT


class SignatureTests(unittest.TestCase):
    def setUp(self):
        self.key = Ed25519PrivateKey.generate()
        self.registry = {"material_scope": a.SCOPE, "keys": {"issuer": {"epoch": 1,
            "public_key": base64.b64encode(self.key.public_key().public_bytes_raw()).decode(),
            "purposes": ["AUTHORIZATION"], "revoked": False}}}
        self.artifact = b'{"material_scope":"SYNTHETIC_ONLY"}'
        self.core = a.release_core(self.artifact, key_id="issuer", purpose="AUTHORIZATION", policy_sha256="b" * 64,
            sequence=1, previous_head=None, nonce="TEST_NONCE_123456789")
        self.signed = a.envelope(self.core, self.key.sign)

    def verify(self, **kwargs):
        return a.verify_envelope(kwargs.pop("signed", self.signed), kwargs.pop("artifact", self.artifact),
            registry=kwargs.pop("registry", self.registry), registry_pin=kwargs.pop("registry_pin", a.e.sha(self.registry)),
            purpose=kwargs.pop("purpose", "AUTHORIZATION"), policy_sha256="b" * 64,
            sequence=kwargs.pop("sequence", 1), previous_head=kwargs.pop("previous_head", None), nonce="TEST_NONCE_123456789", **kwargs)

    def test_temporary_key_roundtrip(self):
        self.assertEqual(self.verify(), self.core)

    def test_rfc8032_public_verification_vector_no_private_seed(self):
        public = bytes.fromhex("d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a")
        signature = bytes.fromhex("e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555f"
                                  "b8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b")
        self.assertIsNone(Ed25519PublicKey.from_public_bytes(public).verify(signature, b""))

    def test_payload_tamper(self):
        with self.assertRaisesRegex(ValueError, "ARTIFACT"):
            self.verify(artifact=self.artifact + b" ")

    def test_signature_tamper(self):
        self.signed["signature"] = base64.b64encode(b"x" * 64).decode()
        with self.assertRaisesRegex(ValueError, "SIGNATURE_INVALID"):
            self.verify()

    def test_external_registry_pin_required(self):
        with self.assertRaisesRegex(ValueError, "REGISTRY_PIN"):
            self.verify(registry_pin="0" * 64)

    def test_wrong_purpose_cannot_grant_acceptance(self):
        with self.assertRaisesRegex(ValueError, "PURPOSE"):
            self.verify(purpose="ACCEPTANCE")

    def test_stale_sequence(self):
        with self.assertRaisesRegex(ValueError, "SEQUENCE"):
            self.verify(sequence=2)

    def test_stale_previous_head(self):
        with self.assertRaisesRegex(ValueError, "SEQUENCE"):
            self.verify(previous_head="c" * 64)

    def test_revoked_key(self):
        self.registry["keys"]["issuer"]["revoked"] = True
        with self.assertRaisesRegex(ValueError, "REVOKED"):
            self.verify()

    def test_key_epoch_mismatch(self):
        self.registry["keys"]["issuer"]["epoch"] = 2
        with self.assertRaisesRegex(ValueError, "KEY"):
            self.verify()

    def test_unknown_key(self):
        self.registry["keys"] = {}
        with self.assertRaisesRegex(ValueError, "KEY"):
            self.verify()

    def test_unknown_algorithm(self):
        self.signed["core"]["algorithm"] = "none"
        with self.assertRaisesRegex(ValueError, "FIELDS"):
            self.verify()

    def test_extra_unsigned_field_rejected(self):
        self.signed["extra"] = True
        with self.assertRaisesRegex(ValueError, "FIELDS"):
            self.verify()

    def test_boolean_sequence_rejected(self):
        self.signed["core"]["sequence"] = True
        with self.assertRaisesRegex(ValueError, "SEQUENCE"):
            self.verify()

    def test_invalid_signature_encoding(self):
        self.signed["signature"] = "?!"
        with self.assertRaisesRegex(ValueError, "ENCODING"):
            self.verify()


class PolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = Fixture()
        cls.addClassCleanup(cls.fixture.close)

    def setUp(self):
        self.policy = deepcopy(self.fixture.policy)

    def check(self):
        a.validate_policy(self.policy, self.fixture.ctx, at=AT)

    def test_valid_exact_policy(self):
        self.check()

    def test_no_real_activation(self):
        self.policy["material_scope"] = "OFFICIAL_HISTORY_EVIDENCE_ONLY"
        with self.assertRaisesRegex(ValueError, "NOT_AUTHORIZED"):
            self.check()

    def test_missing_approval(self):
        self.policy["approved"] = False
        with self.assertRaisesRegex(ValueError, "NOT_APPROVED"):
            self.check()

    def test_nonce_required(self):
        self.policy["nonce"] = ""
        with self.assertRaisesRegex(ValueError, "NONCE"):
            self.check()

    def test_expired(self):
        self.policy["not_after"] = "2020-01-01T00:00:00Z"
        with self.assertRaisesRegex(ValueError, "EXPIRED"):
            self.check()

    def test_future_policy(self):
        self.policy["not_before"] = "2099-01-01T00:00:00Z"
        with self.assertRaisesRegex(ValueError, "FUTURE"):
            self.check()

    def test_acceptance_not_implicitly_delegated(self):
        self.policy["delegations"].remove("ACCEPTANCE")
        with self.assertRaisesRegex(ValueError, "DELEGATION"):
            self.check()

    def test_duplicate_keys_and_nonfinite_metadata(self):
        for raw in (b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":1e999}'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                a.read_metadata(raw)

    def test_bool_budget_is_not_integer(self):
        self.policy["maximum_requests"] = True
        with self.assertRaisesRegex(ValueError, "BUDGET"):
            self.check()

    def test_wrong_window_ordinal(self):
        self.policy["ordinals"] = [99]
        with self.assertRaisesRegex(ValueError, "WINDOW"):
            self.check()

    def test_request_budget_not_multiplied_by_cap(self):
        self.assertEqual(self.policy["maximum_requests"], 1)
        self.policy["maximum_requests"] = 100
        with self.assertRaisesRegex(ValueError, "BUDGET"):
            self.check()


def policy_bad(field, value, reason):
    def test(self):
        self.policy[field] = value
        with self.assertRaisesRegex(ValueError, reason):
            self.check()
    return test


for field, value, reason in [("main_sha", "0" * 40, "SOURCE"), ("sidecar_head", "0" * 40, "SOURCE"),
    ("execution_owner_sha256_lf", {}, "SOURCE"), ("sidecar_owner_sha256_lf", {}, "SOURCE"),
    ("binding", {}, "MANIFEST"), ("chunk_ids", ["wrong"], "IDENTITY"), ("per_chunk_requests", [100], "BUDGET"),
    ("engineering_cr_sha256", "0" * 64, "APPROVED")]:
    setattr(PolicyTests, "test_wrong_" + field, policy_bad(field, value, reason))


class JournalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="SYNTHETIC-batch-")
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.journal = a.Journal(self.base / "issuer", self.base)

    def test_append_and_cold_reconstruct(self):
        head = self.journal.append({"test": "SYNTHETIC_ONLY"}, None)
        fresh = a.Journal(self.base / "issuer", self.base)
        self.assertEqual(fresh.replay(head)[0]["event_sha256"], head)

    def test_stale_external_head(self):
        self.journal.append({"n": 1}, None)
        with self.assertRaisesRegex(ValueError, "HEAD"):
            self.journal.replay(None)

    def test_event_mutation(self):
        head = self.journal.append({"n": 1}, None)
        (self.journal.root / "events/000001.json").write_bytes(b"{}")
        with self.assertRaises(ValueError):
            self.journal.replay(head)

    def test_tail_truncation(self):
        head = self.journal.append({"n": 1}, None)
        head = self.journal.append({"n": 2}, head)
        for family in ("intents", "events", "checkpoints"):
            (self.journal.root / family / "000002.json").unlink()
        with self.assertRaisesRegex(ValueError, "HEAD"):
            self.journal.replay(head)

    def test_exclusive_create_no_overwrite(self):
        path = self.base / "object.json"
        a.put(path, {"n": 1})
        with self.assertRaises(FileExistsError):
            a.put(path, {"n": 2})
        self.assertEqual(a.load(path), {"n": 1})

    def test_second_writer_os_lock_rejected(self):
        with a.h.exclusive_scan(self.journal.root):
            with self.assertRaisesRegex(RuntimeError, "WRITER_ALREADY_ACTIVE"):
                self.journal.append({"n": 1}, None)

    def test_no_unexpected_directory(self):
        (self.journal.root / "unknown").mkdir()
        with self.assertRaisesRegex(ValueError, "DIRECTORY"):
            self.journal.replay(None)

    def test_formal_root_denied(self):
        with self.assertRaises(ValueError):
            a.child_root(a.sidecar.LEDGER, self.base)


def crash_at(folder):
    def test(self):
        def fail(stage):
            if stage == folder:
                raise RuntimeError("SYNTHETIC_CRASH")
        with self.assertRaisesRegex(RuntimeError, "SYNTHETIC_CRASH"):
            self.journal.append({"n": 1}, None, fault=fail)
        with self.assertRaises(ValueError):
            self.journal.replay(None)
        self.assertTrue((self.journal.root / "intents/000001.json").exists())
    return test


for family in ("intents", "events", "checkpoints"):
    setattr(JournalTests, "test_crash_after_" + family, crash_at(family))
