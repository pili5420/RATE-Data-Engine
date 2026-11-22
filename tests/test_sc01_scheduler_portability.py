"""SC-01 offline unit and negative tests. No cloud calls or production writes."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import threading
import unittest

from src.sc01_scheduler_portability import (
    BLOCKING_DELAY_SECONDS, CADENCES, SC01Blocked,
    assess_schedule_envelope, assess_task_start, make_slot,
)
from src.sc01_slot_ledger import InMemorySC01Store


class SC01OfflineTests(unittest.TestCase):
    def setUp(self):
        self.slot = make_slot(project="rate-v11-dev", region="asia-east1",
                              cadence="07:30", trading_date="2026-11-23")
        self.nominal = datetime.fromisoformat(
            self.slot.expected_slot_utc.replace("Z", "+00:00"))
        self.execution_name = self.slot.cloud_run_job + "/executions/exe-123456789012"
        self.task_name = self.execution_name + "/tasks/task-0"
        self.audience = "https://offline-proxy.example.invalid/receive"
        self.account = "scheduler@rate-v11-dev.iam.gserviceaccount.com"

    def ts(self, seconds):
        return (self.nominal + timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")

    def envelope(self):
        return {
            "scheduler_job": self.slot.scheduler_job,
            "cloud_run_job": self.slot.cloud_run_job,
            "cadence": self.slot.cadence,
            "trading_date": self.slot.trading_date,
            "audience": self.audience, "service_account": self.account,
            "issuer": "https://accounts.google.com",
            "event_id": "event-123456789012",
            "nonce": "nonce-123456789012",
            "delivery_attempt": 1,
            "nominal_slot_utc": self.slot.expected_slot_utc,
        }

    def task_api(self, seconds=100):
        execution = {
            "name": self.execution_name,
            "job": self.slot.cloud_run_job, "taskCount": 1,
            "createTime": self.ts(0), "startTime": self.ts(0),
        }
        task = {
            "name": self.task_name, "execution": self.execution_name,
            "taskIndex": 0, "retried": 0, "startTime": self.ts(seconds),
        }
        return execution, task

    def check_task(self, execution, task):
        return assess_task_start(execution, task, self.slot,
                                 expected_execution=self.execution_name,
                                 expected_task=self.task_name)

    def assert_blocked(self, reason, fn, *args, **kwargs):
        with self.assertRaisesRegex(SC01Blocked, reason):
            fn(*args, **kwargs)

    def claim(self, store, slot, *, event_id=None, **kwargs):
        # Explicit canonical event identity is separately unique in the store.
        # This test helper supplies distinct event IDs for existing fixtures.
        nonce = kwargs["nonce"]
        canonical = event_id if event_id is not None else "event-" + nonce
        return store.claim(slot, event_id=canonical, **kwargs)

    def bind(self, store, ticket, execution_name, *, now=None):
        at = now if now is not None else ticket.lease_starts_utc + timedelta(microseconds=1)
        return store.bind_execution(ticket, execution_name, now=at)

    def publish(self, store, ticket, *, now=None, **kwargs):
        at = now if now is not None else ticket.lease_starts_utc + timedelta(microseconds=1)
        return store.publish_candidate(ticket, now=at, **kwargs)

    def test_four_cadences_correct_utc_slots(self):
        # Full UTC instants (not only the hour) across a day and year rollover.
        # Nominal conversion is NOT proof of an actual exchange trading day.
        expected = {
            "2026-11-23": {
                "07:30": "2026-11-22T23:30:00Z",
                "09:30": "2026-11-23T01:30:00Z",
                "12:00": "2026-11-23T04:00:00Z",
                "19:30": "2026-11-23T11:30:00Z",
            },
            "2027-01-04": {
                "07:30": "2027-01-03T23:30:00Z",
                "09:30": "2027-01-04T01:30:00Z",
                "12:00": "2027-01-04T04:00:00Z",
                "19:30": "2027-01-04T11:30:00Z",
            },
        }
        for date_string, slots in expected.items():
            for cadence in CADENCES:
                with self.subTest(date=date_string, cadence=cadence):
                    item = make_slot(project="rate-v11-dev", region="asia-east1",
                                     cadence=cadence, trading_date=date_string)
                    self.assertEqual(item.expected_slot_utc, slots[cadence])
                    dt = datetime.fromisoformat(item.expected_slot_utc.replace("Z", "+00:00"))
                    self.assertEqual(dt.utcoffset(), timedelta(0))
                    self.assertEqual((dt + timedelta(hours=8)).strftime("%Y-%m-%dT%H:%M:%S"),
                                     f"{date_string}T{cadence}:00")
                    self.assertIn(cadence, item.slot_key)
        self.assertEqual(BLOCKING_DELAY_SECONDS, 900)

    def test_synthetic_utc_year_boundary_2027(self):
        # Synthetic calendar fixture ONLY: 2027-01-01 is not asserted to
        # be a valid TWSE/TPEx trading day; make_slot does not check holidays.
        # 07:30 Asia/Taipei crosses 2027 -> 2026 in the UTC conversion.
        expected_utc = {
            "07:30": "2026-12-31T23:30:00Z",
            "09:30": "2027-01-01T01:30:00Z",
            "12:00": "2027-01-01T04:00:00Z",
            "19:30": "2027-01-01T11:30:00Z",
        }
        taipei = timezone(timedelta(hours=8))
        self.assertEqual(set(expected_utc), set(CADENCES))
        for cadence in CADENCES:
            with self.subTest(synthetic_date="2027-01-01", cadence=cadence):
                slot = make_slot(project="rate-v11-dev", region="asia-east1",
                                 cadence=cadence, trading_date="2027-01-01")
                self.assertEqual(slot.expected_slot_utc, expected_utc[cadence])
                observed_utc = datetime.fromisoformat(
                    slot.expected_slot_utc.replace("Z", "+00:00"))
                self.assertEqual(observed_utc.utcoffset(), timedelta(0))
                self.assertEqual(
                    observed_utc.astimezone(taipei).isoformat(timespec="seconds"),
                    f"2027-01-01T{cadence}:00+08:00")
                self.assertEqual(observed_utc.second, 0)
                self.assertIn(cadence, slot.slot_key)
        crossing = datetime.fromisoformat(
            expected_utc["07:30"].replace("Z", "+00:00"))
        self.assertEqual(crossing.year, 2026)
        self.assertEqual(crossing.astimezone(taipei).year, 2027)

    def test_invalid_slot_rejected(self):
        for arg, val, reason in [
            ("project", "UPPERCASE", "SC01_PROJECT_INVALID"),
            ("region", "bad region", "SC01_REGION_INVALID"),
            ("cadence", "19:31", "SC01_CADENCE_INVALID"),
            ("trading_date", "2026-11-31", "SC01_TRADING_DATE_INVALID"),
        ]:
            kwargs = dict(project="rate-v11-dev", region="asia-east1",
                          cadence="07:30", trading_date="2026-11-23")
            kwargs[arg] = val
            self.assert_blocked(reason, make_slot, **kwargs)

    def test_untrusted_envelope_only_contract_match(self):
        got = assess_schedule_envelope(self.envelope(), self.slot,
                                       expected_audience=self.audience,
                                       expected_service_account=self.account)
        self.assertEqual(got["verdict"], "OFFLINE_CONTRACT_MATCH_ONLY")
        self.assertFalse(got["identity_crypto_verified"])
        self.assertFalse(got["calendar_verified"])
        self.assertEqual(got["production_permit"], "NOT_ISSUED")
        self.assertEqual(len(got["event_digest"]), 64)

    def test_envelope_invalid_identity_and_replay_fields(self):
        cases = [
            ("scheduler_job", "different", "SC01_SCHEDULER_JOB_MISMATCH"),
            ("cloud_run_job", "different", "SC01_CLOUD_RUN_JOB_MISMATCH"),
            ("cadence", "09:30", "SC01_SLOT_BINDING_MISMATCH"),
            ("trading_date", "2026-11-24", "SC01_SLOT_BINDING_MISMATCH"),
            ("audience", "https://attacker.invalid", "SC01_AUDIENCE_MISMATCH"),
            ("service_account", "untrusted@rate-v11-dev.iam.gserviceaccount.com", "SC01_SERVICE_ACCOUNT_MISMATCH"),
            ("issuer", "https://attacker.invalid", "SC01_ISSUER_MISMATCH"),
            ("event_id", "short", "SC01_EVENT_OR_NONCE_INVALID"),
            ("nonce", "short", "SC01_EVENT_OR_NONCE_INVALID"),
            ("delivery_attempt", 0, "SC01_DELIVERY_ATTEMPT_INVALID"),
            ("delivery_attempt", 2, "SC01_DELIVERY_ATTEMPT_INVALID"),
            ("delivery_attempt", True, "SC01_DELIVERY_ATTEMPT_INVALID"),
            ("nominal_slot_utc", self.ts(1), "SC01_NOMINAL_SLOT_MISMATCH"),
        ]
        for key, val, reason in cases:
            with self.subTest(key=key, value=str(val)):
                body = self.envelope()
                body[key] = val
                self.assert_blocked(reason, assess_schedule_envelope,
                                    body, self.slot, expected_audience=self.audience,
                                    expected_service_account=self.account)

    def test_cloud_task_boundary_899_9_and_900_pass(self):
        for seconds in (899.9, 900.0):
            with self.subTest(seconds=seconds):
                got = self.check_task(*self.task_api(seconds))
                self.assertAlmostEqual(got["actual_task_start_delay_seconds"], seconds)
                self.assertEqual(got["production_permit"], "NOT_ISSUED")

    def test_cloud_task_boundary_900_1_blocks(self):
        self.assert_blocked("SC01_TASK_START_DELAY_EXCEEDED_900S",
                            self.check_task, *self.task_api(900.1))

    def test_cloud_task_early_or_missing_time_blocks(self):
        self.assert_blocked("SC01_TASK_TIME_ORDER_INVALID",
                            self.check_task, *self.task_api(-0.1))
        execution, task = self.task_api(1)
        del task["startTime"]
        self.assert_blocked("SC01_TASK_STARTED_AT_MISSING",
                            self.check_task, execution, task)
        execution, task = self.task_api(1)
        task["startTime"] = "2026-11-23T01:00:00"
        self.assert_blocked("SC01_TASK_STARTED_AT_MISSING",
                            self.check_task, execution, task)

    def test_cloud_task_identity_and_retry_blocks(self):
        for field, value, reason in [
            ("name", "wrong", "SC01_EXECUTION_TASK_ID_MISMATCH"),
            ("execution", "wrong", "SC01_TASK_EXECUTION_MISMATCH"),
            ("taskIndex", 1, "SC01_TASK_ATTEMPT_UNQUALIFIED"),
            ("retried", 1, "SC01_TASK_ATTEMPT_UNQUALIFIED"),
            ("retried", True, "SC01_TASK_ATTEMPT_UNQUALIFIED"),
        ]:
            execution, task = self.task_api(1)
            task[field] = value
            self.assert_blocked(reason, self.check_task, execution, task)
        execution, task = self.task_api(1)
        execution["taskCount"] = 2
        self.assert_blocked("SC01_TASK_ATTEMPT_UNQUALIFIED",
                            self.check_task, execution, task)
        execution, task = self.task_api(1)
        execution["job"] = "other"
        self.assert_blocked("SC01_EXECUTION_JOB_MISMATCH",
                            self.check_task, execution, task)

    def test_cloud_task_execution_start_after_task_blocks(self):
        execution, task = self.task_api(10)
        execution["startTime"] = self.ts(11)
        self.assert_blocked("SC01_TASK_TIME_ORDER_INVALID",
                            self.check_task, execution, task)

    def test_slot_replay_nonce_across_slots(self):
        store = InMemorySC01Store()
        digest = hashlib.sha256(b"first").hexdigest()
        now = self.nominal
        self.claim(store, self.slot, event_digest=digest, nonce="nonce-123456789012",
                    execution_id="exe-123456789012", now=now, lease_seconds=300)
        second = make_slot(project="rate-v11-dev", region="asia-east1",
                           cadence="09:30", trading_date="2026-11-23")
        self.assert_blocked("SC01_REPLAY_REJECTED", self.claim, store, second,
                            event_digest=hashlib.sha256(b"second").hexdigest(),
                            nonce="nonce-123456789012",
                            execution_id="exe-123456789013", now=now,
                            lease_seconds=300)
        self.assert_blocked("SC01_REPLAY_REJECTED", self.claim, store, second,
                            event_digest=digest, nonce="nonce-123456789013",
                            execution_id="exe-123456789013", now=now,
                            lease_seconds=300)

    def test_lease_ownership_fencing_and_publication(self):
        store = InMemorySC01Store()
        t1 = self.claim(store, self.slot, event_digest=hashlib.sha256(b"one").hexdigest(),
                         nonce="nonce-123456789012",
                         execution_id="exe-123456789012",
                         now=self.nominal, lease_seconds=10)
        self.assert_blocked("SC01_SLOT_ALREADY_CLAIMED", self.claim, store, self.slot,
                            event_digest=hashlib.sha256(b"two").hexdigest(),
                            nonce="nonce-123456789013", execution_id="exe-123456789013",
                            now=self.nominal + timedelta(seconds=9), lease_seconds=10)
        t2 = self.claim(store, self.slot, event_digest=hashlib.sha256(b"two").hexdigest(),
                         nonce="nonce-123456789013", execution_id="exe-123456789013",
                         now=self.nominal + timedelta(seconds=10), lease_seconds=10)
        self.assertEqual((t1.fencing_token, t2.fencing_token), (1, 2))
        self.assert_blocked("SC01_FENCING_TOKEN_STALE", self.bind, store,
                            t1, self.execution_name)
        next_execution = self.slot.cloud_run_job + "/executions/exe-123456789013"
        self.bind(store, t2, next_execution)
        self.assert_blocked("SC01_EXECUTION_ALREADY_BOUND",
                            self.bind, store, t2, next_execution)
        self.publish(store, t2, execution_name=next_execution,
                                material_digest=hashlib.sha256(b"state").hexdigest(),
                                previous_state_id="previous-verified-id")
        self.assertEqual(store.snapshot(self.slot)["state"], "PUBLISHED")
        self.assertEqual(store.snapshot(self.slot)["production_state_mutation"], 0)
        self.assert_blocked("SC01_PUBLICATION_DUPLICATE_OR_UNBOUND",
                            self.publish, store, t2, execution_name=next_execution,
                            material_digest=hashlib.sha256(b"state").hexdigest(),
                            previous_state_id="previous-verified-id")
        self.assert_blocked("SC01_SLOT_ALREADY_PUBLISHED", self.claim, store, self.slot,
                            event_digest=hashlib.sha256(b"three").hexdigest(),
                            nonce="nonce-123456789014", execution_id="exe-123456789014",
                            now=self.nominal + timedelta(seconds=60), lease_seconds=10)

    def test_publication_requires_binding_material_and_predecessor(self):
        store = InMemorySC01Store()
        ticket = self.claim(store, self.slot, event_digest=hashlib.sha256(b"one").hexdigest(),
                             nonce="nonce-123456789012",
                             execution_id="exe-123456789012",
                             now=self.nominal, lease_seconds=300)
        self.assert_blocked("SC01_PUBLICATION_DUPLICATE_OR_UNBOUND",
                            self.publish, store, ticket,
                            execution_name=self.execution_name,
                            material_digest="0"*64, previous_state_id="previous")
        self.bind(store, ticket, self.execution_name)
        self.assert_blocked("SC01_PUBLICATION_EXECUTION_MISMATCH",
                            self.publish, store, ticket,
                            execution_name="wrong",
                            material_digest="0"*64, previous_state_id="previous")
        self.assert_blocked("SC01_PUBLICATION_HASH_INVALID",
                            self.publish, store, ticket,
                            execution_name=self.execution_name,
                            material_digest="BAD", previous_state_id="previous")
        self.assert_blocked("SC01_PREDECESSOR_NOT_PROVEN",
                            self.publish, store, ticket,
                            execution_name=self.execution_name,
                            material_digest="0"*64, previous_state_id="")

    def test_expired_lease_without_takeover_blocks_bind(self):
        store = InMemorySC01Store()
        ticket = self.claim(
            store, self.slot, event_digest=hashlib.sha256(b"lease-bind").hexdigest(),
            nonce="nonce-lease-bind-0001", execution_id="exe-lease-bind-0001",
            now=self.nominal, lease_seconds=10)
        self.assert_blocked("SC01_LEASE_EXPIRED_OR_CLOCK_INVALID",
                            self.bind, store, ticket, self.slot.cloud_run_job +
                            "/executions/exe-lease-bind-0001",
                            now=self.nominal + timedelta(seconds=10))
        self.assert_blocked("SC01_LEASE_EXPIRED_OR_CLOCK_INVALID",
                            self.bind, store, ticket, self.slot.cloud_run_job +
                            "/executions/exe-lease-bind-0001",
                            now=self.nominal + timedelta(seconds=10.001))
        self.assertEqual(store.snapshot(self.slot)["state"], "CLAIMED")

    def test_expired_lease_without_takeover_blocks_publication(self):
        store = InMemorySC01Store()
        ticket = self.claim(
            store, self.slot, event_digest=hashlib.sha256(b"lease-publish").hexdigest(),
            nonce="nonce-lease-publish-1", execution_id="exe-lease-publish-1",
            now=self.nominal, lease_seconds=10)
        name = self.slot.cloud_run_job + "/executions/exe-lease-publish-1"
        self.bind(store, ticket, name, now=self.nominal + timedelta(seconds=1))
        for seconds in (10, 10.000001, 11):
            with self.subTest(seconds=seconds):
                self.assert_blocked("SC01_LEASE_EXPIRED_OR_CLOCK_INVALID",
                                    self.publish, store, ticket, execution_name=name,
                                    material_digest="0"*64, previous_state_id="previous",
                                    now=self.nominal + timedelta(seconds=seconds))
        self.assertEqual(store.snapshot(self.slot)["state"], "EXECUTION_BOUND")

    def test_lease_positive_before_expiry_and_clock_rejects_backdating(self):
        store = InMemorySC01Store()
        ticket = self.claim(
            store, self.slot, event_digest=hashlib.sha256(b"lease-positive").hexdigest(),
            nonce="nonce-lease-positive-1", execution_id="exe-lease-positive-1",
            now=self.nominal, lease_seconds=10)
        name = self.slot.cloud_run_job + "/executions/exe-lease-positive-1"
        self.assert_blocked("SC01_LEASE_EXPIRED_OR_CLOCK_INVALID",
                            self.bind, store, ticket, name,
                            now=self.nominal - timedelta(microseconds=1))
        self.assert_blocked("SC01_CLOCK_UNTRUSTED",
                            self.bind, store, ticket, name,
                            now=datetime(2026, 11, 23, 1, 0))
        self.bind(store, ticket, name, now=self.nominal + timedelta(seconds=9.9))
        self.publish(store, ticket, execution_name=name,
                     material_digest=hashlib.sha256(b"material").hexdigest(),
                     previous_state_id="previous", now=self.nominal + timedelta(seconds=9.999999))
        self.assertEqual(store.snapshot(self.slot)["state"], "PUBLISHED")

    def test_event_id_independently_unique_from_nonce_and_digest(self):
        store = InMemorySC01Store()
        first_id = "event-canonical-1234567"
        first_nonce = "nonce-canonical-1234567"
        first_digest = hashlib.sha256(b"original-event").hexdigest()
        self.claim(store, self.slot, event_id=first_id,
                   event_digest=first_digest, nonce=first_nonce,
                   execution_id="exe-canonical-1234567", now=self.nominal,
                   lease_seconds=10)
        second = make_slot(project="rate-v11-dev", region="asia-east1",
                           cadence="09:30", trading_date="2026-11-23")
        # Same event with changed nonce AND digest: still a replay.
        self.assert_blocked("SC01_REPLAY_REJECTED", self.claim, store, second,
                            event_id=first_id, event_digest=hashlib.sha256(b"changed").hexdigest(),
                            nonce="nonce-different-12345", execution_id="exe-different-12345",
                            now=self.nominal, lease_seconds=10)
        # Exact duplicate delivery, even after expiry, must not claim again.
        self.assert_blocked("SC01_REPLAY_REJECTED", self.claim, store, self.slot,
                            event_id=first_id, event_digest=first_digest, nonce=first_nonce,
                            execution_id="exe-canonical-1234567",
                            now=self.nominal + timedelta(seconds=10), lease_seconds=10)
        # Changed event with reused nonce.
        self.assert_blocked("SC01_REPLAY_REJECTED", self.claim, store, second,
                            event_id="event-changed-1234567",
                            event_digest=hashlib.sha256(b"changed-2").hexdigest(),
                            nonce=first_nonce, execution_id="exe-different-12345",
                            now=self.nominal, lease_seconds=10)
        # Changed event/nonce with reused digest.
        self.assert_blocked("SC01_REPLAY_REJECTED", self.claim, store, second,
                            event_id="event-changed-1234567", event_digest=first_digest,
                            nonce="nonce-different-12345", execution_id="exe-different-12345",
                            now=self.nominal, lease_seconds=10)

    def test_concurrent_claims_same_event_id_across_distinct_slots(self):
        store = InMemorySC01Store()
        successes, failures = [], []
        lock = threading.Lock()

        def contender(idx, cadence):
            slot = make_slot(project="rate-v11-dev", region="asia-east1",
                             cadence=cadence, trading_date="2026-11-23")
            try:
                got = self.claim(store, slot, event_id="event-shared-123456789",
                                 event_digest=hashlib.sha256(str(idx).encode()).hexdigest(),
                                 nonce=f"nonce-event-{idx:012d}",
                                 execution_id=f"exe-event-{idx:012d}",
                                 now=self.nominal, lease_seconds=120)
                with lock:
                    successes.append(got)
            except SC01Blocked as exc:
                with lock:
                    failures.append(str(exc))
        threads = [threading.Thread(target=contender, args=(idx, cadence))
                   for idx, cadence in enumerate(CADENCES)]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        self.assertEqual(len(successes), 1)
        self.assertEqual(failures, ["SC01_REPLAY_REJECTED"] * 3)

    def test_canonical_event_id_missing_or_invalid_blocks(self):
        store = InMemorySC01Store()
        for event_id in (None, "", "too-short", True):
            with self.subTest(event_id=event_id):
                self.assert_blocked(
                    "SC01_EVENT_ID_INVALID", store.claim, self.slot,
                    event_id=event_id,
                    event_digest=hashlib.sha256(b"invalid").hexdigest(),
                    nonce="nonce-validate-123456",
                    execution_id="exe-validate-123456",
                    now=self.nominal, lease_seconds=10)

    def test_threaded_claim_one_owner(self):
        store = InMemorySC01Store()
        successes, failures = [], []
        lock = threading.Lock()
        def contender(idx):
            try:
                ticket = self.claim(store, 
                    self.slot, event_digest=hashlib.sha256(str(idx).encode()).hexdigest(),
                    nonce=f"nonce-{idx:012d}", execution_id=f"exe-{idx:012d}",
                    now=self.nominal, lease_seconds=120)
                with lock:
                    successes.append(ticket)
            except SC01Blocked as ex:
                with lock:
                    failures.append(str(ex))
        threads = [threading.Thread(target=contender, args=(idx,))
                   for idx in range(10)]
        for t in threads: t.start()
        for t in threads: t.join()
        self.assertEqual(len(successes), 1)
        self.assertEqual(len(failures), 9)
        self.assertTrue(all(reason == "SC01_SLOT_ALREADY_CLAIMED" for reason in failures))


if __name__ == "__main__":
    unittest.main()
