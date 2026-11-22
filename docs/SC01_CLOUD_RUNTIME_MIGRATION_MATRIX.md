# RATE V11 SC-01 — Cloud Scheduler / Cloud Run Portability (OFFLINE ONLY)

Authority: `AUTHORIZE_RATE_V11_SC01_SCHEDULER_PORTABILITY_OFFLINE_ENGINEERING_ONLY`
Reference PR: #224, exact head `199a1f525c2afe2b3ada0453db28bf84f6150e0e`
Frozen base: `0334d18bde3bbc8ba0176ab2a51a5d07881e2bd7`
Disposition: **engineering candidate; not a deployed or trusted system**
NO_AUTO_NEXT: **TRUE**.

## Authorized boundary

This candidate is branched from the **frozen main base** rather than from PR #224 so PR #224 remains unchanged and the independent PR shows **only SC-01 changes**. It adds no executable production trigger, cloud SDK dependency, cloud credentials, Google Cloud resources, Scheduler jobs, IAM, Storage, Billing, source-date waiver or State mutation. Existing four Production workflows and Frozen Contracts are untouched.

### SC01-A: scheduler contract

- `src/sc01_scheduler_portability.py:make_slot` derives exactly 07:30, 09:30, 12:00, 19:30 Asia/Taipei nominal slots from the existing `src/cer081_scheduler_actual_timing.py:expected_slot_utc`.
- Each slot binds project, region, specific Scheduler Job, Cloud Run Job, target trading date and local cadence. Trading-date **calendar legality is not verified** by these modules: independent TWSE/TPEx calendar evidence remains mandatory for any real run.
- `assess_schedule_envelope` matches only **untrusted** envelope fields, retaining event ID, nonce and digest. It explicitly emits `identity_crypto_verified=false`, `calendar_verified=false`, and `production_permit=NOT_ISSUED`.
- A real proxy must validate Google's signed OIDC issuer/audience/service-account identity **cryptographically**, using trusted transport and an allowlisted project, service account and Scheduler resource. Header/body booleans never prove identity.
- `DeliveryAttempt` alone cannot establish uniqueness. The persistent slot transaction (SC01-B) and independent event receipt must bind actual scheduler delivery, retry and target.

### SC01-B: idempotency/atomicity

`src/sc01_slot_ledger.py` models a **single-process test double** and `TransactionalSlotStore` boundary:
1. Transactionally claim the unique `project/region/trading_date/cadence` slot, **canonical Event ID**, nonce, and event digest as separate uniqueness constraints.
2. Bind cloud Execution ID and issuance response; never blindly resubmit after a timeout (perform provider-side readback/reconciliation).
3. Fail closed on simultaneous claims, `delivery_attempt != 1`, replay (including same event ID with new nonce), missing or expired lease, non-matching execution, missing predecessor.
4. Use monotonically increasing **fencing tokens** on expired lease recovery; both binding and publication atomically check `lease_starts_utc <= now < lease_expires_utc`, even without a successor claim. `now` is a deterministic **offline fixture** only: a real implementation must use independently trusted, store-enforced transaction time.
5. Make the final State pointer/publication a second independent durable atomic compare-and-swap with prior-State lineage verification, and immutable readback.

**In-memory locks are not durable** or cross-instance, are not a cryptographic replay defense, cannot prevent duplicate Cloud Run starts on their own, and cannot authorize Production. The test-double `publish_candidate` writes no RATE state and emits no permit.

### SC01-C: timing evidence

`assess_task_start` validates Cloud Run v2-style `Execution.createTime`, `Execution.startTime`, and **Task.startTime**, resource identities and task attempt. Only Task.startTime is compared with the fixed Taiwan nominal cadence; never substitute Scheduler's HTTP send time, Execution created time or GitHub Run start time.

Mandatory edge cases: 899.9s PASS (offline contract), 900.0s PASS (offline contract), 900.1s BLOCK, missing/naive/early timestamps BLOCK, job/task/execution mismatch BLOCK, task retry/multi-task BLOCK. `provider_api_provenance_verified=false`, `production_permit=NOT_ISSUED`.

Real qualification still requires independently authenticated Google readback of Execution/Task records, guaranteed Task-start semantics, Clock/Timezone binding, latency proof, replay-safe receipt retention and real scheduled job execution. Offline fixtures never earn CER-081 credit.

### SC01-D: exact-file runtime migration matrix

| Existing file / responsibility | Proposed isolated Cloud boundary | Frozen/integration risk | Status |
|---|---|---|---|
| `.github/workflows/rate_production_0730_scheduler.yml` | Scheduler slot 07:30 + protected Job task | Predecessor must be previous valid 19:30 | UNCHANGED / future integration |
| `.github/workflows/rate_production_0930_scheduler.yml` | Scheduler slot 09:30 + protected Job task | Keep Route B PARTIAL_VALID and existing intraday Frozen scope | UNCHANGED / future integration |
| `.github/workflows/rate_production_1200_scheduler.yml` | Scheduler slot 12:00 + protected Job task | Keep Route B PARTIAL_VALID and existing intraday Frozen scope | UNCHANGED / future integration |
| `.github/workflows/rate_production_1930_scheduler.yml` | Scheduler slot 19:30 + protected Job task | Full-market EOD Source/State and 900s required | UNCHANGED / future integration |
| `scripts/resolve_production_runtime_context.py` | Runtime Context Adapter for actual scheduled identity | Currently depends on GitHub event context and predecessor paths; calendar and First Refresh are frozen | NOT MODIFIED |
| `src/cer081_scheduler_actual_timing.py` | Separate Execution/Task timing receipt adapter | GitHub Run API origin must not be silently relabeled Cloud PASS | REUSED, NOT MODIFIED |
| `scripts/build_scheduler_actual_timing_evidence.py` | Google authenticated API readback adapter | Existing GitHub Run evidence not equivalent | NOT MODIFIED |
| `scripts/build_production_source_bundle_from_official.py` | Containerized official-source acquisition | DC-01 source-date authority not established; maintain fail-closed | NOT MODIFIED |
| `scripts/run_phase2_production.py` | Container command entrypoint with attested execution identity | Requires `ACTIONS_JOB_ID` binding, existing Phase2 authority and previous state | NOT MODIFIED |
| `scripts/run_cer076_incremental_0930_acceptance.py` | Intraday job command | Frozen 09:30 route remains as-is | NOT MODIFIED |
| `scripts/run_cer077_incremental_1200_acceptance.py` | Intraday job command | Frozen 12:00 route remains as-is | NOT MODIFIED |
| `src/production_live_state.py` | Durable authority-guarded State Store + readback | Current local `artifacts/production_state/live/...` layout cannot be assumed durable inside Cloud Run Jobs | NOT MODIFIED |
| `scripts/publish_production_state_latest.py` | Durable atomic publication with fencing and immutable evidence | GitHub commit/rebase/push workflow cannot be substituted for custody proof | NOT MODIFIED |
| `scripts/publish_production_source_bundle_latest.py` | Immutable-source receipt and independent readback | Publication authority, hashing and artifact preservation | NOT MODIFIED |
| `scripts/validate_production_scheduler_safety.py` | Provider-agnostic gate and real-Google verifier adapter | Requires new specifically authorized compatibility engineering | NOT MODIFIED |
| `src/sc01_scheduler_portability.py` | Offline slots, envelope match, timing fixtures | **Only** OFFLINE candidate; no auth/clock proof | ADDED |
| `src/sc01_slot_ledger.py` | Offline transactional model/test double | **Not** a durable Store Authority | ADDED |
| `tests/test_sc01_scheduler_portability.py` | Targeted positive/negative tests | Cannot substitute real Runtime/Production tests | ADDED |
| `.github/workflows/rate_sc01_offline_ci.yml` | PR-only read-permission offline CI | No Production schedule or workflow dispatch | ADDED |

## Threat model and mandatory fail-closed controls

- **Scheduler at-least-once retries**: only the first durable slot claim may submit; duplicate deliveries rejected. A lost jobs.run response requires authenticated execution reconciliation, not a blind second job.
- **Replay**: validate token cryptography and nonce with an independent trusted proxy, bounded TTL and durable nonce index; never trust HTTP header claims alone.
- **Double publication**: immutable State/Source evidence, atomic pointer CAS, independently verified predecessor, durable fencing token and readback; in-memory model does not supply these.
- **Clock/timing**: nominal slot is not the HTTP request timestamp; Task.startTime from authenticated provider API must be within 0..900s inclusive. Test at edge.
- **GitHub and GCP identity**: Google service-account trust policy is separate from GitHub Actions identity; no implicit authority transfer.
- **Data freshness**: `Date Stock Updated` non-equal remains BLOCKED unless separately adopted DC-01 authority.
- **Frozen intraday**: 09:30/12:00 must not acquire 07:30/19:30 source/state capabilities by adapter expansion.
- **Trust/Store**: no named approved G2/Custody/Verifier authority exists for this candidate. Store class is explicitly unqualified.
- **Cost/availability**: project, billing, IAM, quota, region, proxy, persistent store, retention and independent verifier are NOT checked; no infrastructure created.
- **Publication**: do not publish during a stale job, wrong predecessor, conflicting lease or incomplete receipt.

## One-batch acceptance evidence

1. Exact reference PR #224 Head matched before first write.
2. Independent branch from frozen `main` base, no mutations to PR #224 or main.
3. Offline CI must pass with identity, 4 slots and full UTC ISO instants, time boundaries, attempt-2 refusal, canonical event-ID replay, expired lease without takeover, concurrency, fencing and previous-state rejection.
4. Report separate Draft PR, head SHA, changed files and CI result to Owner.
5. **Stop** after the single SC-01 engineering batch: no auto-next, merge, Cloud setup, Production runs, DC-01 relaxation or CER-081 credit.

Only a future Owner decision can authorize GCP account review, real Cloud Run Task-start qualification and Production architecture integration.

## SC01 R1-C01 targeted corrective candidate (2026-11-22)

Owner authority: `AUTHORIZE_RATE_V11_SC01_R1_C01_TARGETED_OFFLINE_CORRECTIVE_ONLY`; reference PR #225 pre-correction Head `196de0016a7281953985cd15e9596e05eb2618e6`; F-01/F-02/F-03 are the only authorized corrections.

- **F-01:** Bind and simulated publication now require an explicit `now` and atomically enforce lease validity while holding the in-memory lock. Lease expiry is exclusive at the exact instant. The test clock is caller-provided and **NOT trusted Production time**. A durable adapter must enforce transaction time itself; this is not implemented.
- **F-02:** Offline envelope refuses delivery attempt 2 or greater; a separate event-ID set rejects duplicate canonical events even when nonce and digest differ. This model does not cryptographically establish or derive the canonical ID from Google; signed OIDC and authoritative event identity remain unqualified.
- **F-03:** Regression tests compare all four complete ISO UTC date/time stamps, including :30 minutes and year/day rollover, on multiple nominal dates. Exchange trading-calendar truth remains unverified.
- No existing RATE Production source/State, Frozen Contract, Scheduler, Cloud credentials, Store Authority or trust bindings changed.
- Exact-head CI and independent review must follow the final targeted correction. A green offline CI cannot grant Production or CER-081 credit.
