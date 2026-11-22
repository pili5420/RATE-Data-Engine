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

    def test_four_cadences_correct_utc_slots(self):
        expected_hours = {"07:30": (22, 23), "09:30": (23, 1),
                          "12:00": (23, 4), "19:30": (23, 11)}
        for cadence in CADENCES:
            with self.subTest(cadence=cadence):
                item = make_slot(project="rate-v11-dev", region="asia-east1",
                                 cadence=cadence, trading_date="2026-11-23")
                dt = datetime.fromisoformat(item.expected_slot_utc.replace("Z", "+00:00"))
                day, hour = expected_hours[cadence]
                self.assertEqual((dt.day, dt.hour), (day, hour))
                self.assertIn(cadence, item.slot_key)
        self.assertEqual(BLOCKING_DELAY_SECONDS, 900)

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
        store.claim(self.slot, event_digest=digest, nonce="nonce-123456789012",
                    execution_id="exe-123456789012", now=now, lease_seconds=300)
        second = make_slot(project="rate-v11-dev", region="asia-east1",
                           cadence="09:30", trading_date="2026-11-23")
        self.assert_blocked("SC01_REPLAY_REJECTED", store.claim, second,
                            event_digest=hashlib.sha256(b"second").hexdigest(),
                            nonce="nonce-123456789012",
                            execution_id="exe-123456789013", now=now,
                            lease_seconds=300)
        self.assert_blocked("SC01_REPLAY_REJECTED", store.claim, second,
                            event_digest=digest, nonce="nonce-123456789013",
                            execution_id="exe-123456789013", now=now,
                            lease_seconds=300)

    def test_lease_ownership_fencing_and_publication(self):
        store = InMemorySC01Store()
        t1 = store.claim(self.slot, event_digest=hashlib.sha256(b"one").hexdigest(),
                         nonce="nonce-123456789012",
                         execution_id="exe-123456789012",
                         now=self.nominal, lease_seconds=10)
        self.assert_blocked("SC01_SLOT_ALREADY_CLAIMED", store.claim, self.slot,
                            event_digest=hashlib.sha256(b"two").hexdigest(),
                            nonce="nonce-123456789013", execution_id="exe-123456789013",
                            now=self.nominal + timedelta(seconds=9), lease_seconds=10)
        t2 = store.claim(self.slot, event_digest=hashlib.sha256(b"two").hexdigest(),
                         nonce="nonce-123456789013", execution_id="exe-123456789013",
                         now=self.nominal + timedelta(seconds=10), lease_seconds=10)
        self.assertEqual((t1.fencing_token, t2.fencing_token), (1, 2))
        self.assert_blocked("SC01_FENCING_TOKEN_STALE", store.bind_execution,
                            t1, self.execution_name)
        next_execution = self.slot.cloud_run_job + "/executions/exe-123456789013"
        store.bind_execution(t2, next_execution)
        self.assert_blocked("SC01_EXECUTION_ALREADY_BOUND",
                            store.bind_execution, t2, next_execution)
        store.publish_candidate(t2, execution_name=next_execution,
                                material_digest=hashlib.sha256(b"state").hexdigest(),
                                previous_state_id="previous-verified-id")
        self.assertEqual(store.snapshot(self.slot)["state"], "PUBLISHED")
        self.assertEqual(store.snapshot(self.slot)["production_state_mutation"], 0)
        self.assert_blocked("SC01_PUBLICATION_DUPLICATE_OR_UNBOUND",
                            store.publish_candidate, t2, execution_name=next_execution,
                            material_digest=hashlib.sha256(b"state").hexdigest(),
                            previous_state_id="previous-verified-id")
        self.assert_blocked("SC01_SLOT_ALREADY_PUBLISHED", store.claim, self.slot,
                            event_digest=hashlib.sha256(b"three").hexdigest(),
                            nonce="nonce-123456789014", execution_id="exe-123456789014",
                            now=self.nominal + timedelta(seconds=60), lease_seconds=10)

    def test_publication_requires_binding_material_and_predecessor(self):
        store = InMemorySC01Store()
        ticket = store.claim(self.slot, event_digest=hashlib.sha256(b"one").hexdigest(),
                             nonce="nonce-123456789012",
                             execution_id="exe-123456789012",
                             now=self.nominal, lease_seconds=300)
        self.assert_blocked("SC01_PUBLICATION_DUPLICATE_OR_UNBOUND",
                            store.publish_candidate, ticket,
                            execution_name=self.execution_name,
                            material_digest="0"*64, previous_state_id="previous")
        store.bind_execution(ticket, self.execution_name)
        self.assert_blocked("SC01_PUBLICATION_EXECUTION_MISMATCH",
                            store.publish_candidate, ticket,
                            execution_name="wrong",
                            material_digest="0"*64, previous_state_id="previous")
        self.assert_blocked("SC01_PUBLICATION_HASH_INVALID",
                            store.publish_candidate, ticket,
                            execution_name=self.execution_name,
                            material_digest="BAD", previous_state_id="previous")
        self.assert_blocked("SC01_PREDECESSOR_NOT_PROVEN",
                            store.publish_candidate, ticket,
                            execution_name=self.execution_name,
                            material_digest="0"*64, previous_state_id="")

    def test_threaded_claim_one_owner(self):
        store = InMemorySC01Store()
        successes, failures = [], []
        lock = threading.Lock()
        def contender(idx):
            try:
                ticket = store.claim(
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
