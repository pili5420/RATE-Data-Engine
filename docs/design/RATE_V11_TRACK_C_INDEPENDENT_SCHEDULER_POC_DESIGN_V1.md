# RATE V11 Track C — Independent Scheduler Authority and Runtime PoC (DESIGN ONLY)

Authority: AUTHORIZE_RATE_V11_TRACK_B_REBASELINE_DESIGN_AND_TRACK_C_SCHEDULER_POC_DESIGN_ONLY
Controlling main at design start: `0334d18bde3bbc8ba0176ab2a51a5d07881e2bd7`
Disposition: POC_DESIGN_CANDIDATE_ONLY / NOT_DEPLOYABLE / NO_CONTRACT_CHANGE

## Current immutable authority and observed failure

`docs/contracts/RATE_CER081_SCHEDULER_ACTUAL_TIMING_V1.json` requires `event_name=schedule`, direct `event_schedule`, correct workflow path/head SHA, GitHub Run API timestamps, attempt=1, and no inference/retry/fallback; threshold is `900` seconds. `src/cer081_scheduler_actual_timing.py` enforces this; the four official workflows are the current only admissible schedule sources. The 2026-11-05/06 native schedule runs observed significant delays beyond 900 seconds; optimization cannot guarantee GitHub service latency. PR #211's C02/C03 offline corrections address date reconstruction / Python CLI import, not timing guarantees.

## Options and recommendation

A. Keep GitHub native `schedule` and optimize workflows / telemetry: no authority change, cannot promise <=900 seconds; continue fail-closed.
B. External scheduler → GitHub dispatch: usually `workflow_dispatch` or `repository_dispatch`; may reduce scheduling delay but GitHub job queue still uncontrolled; forbidden for CURRENT_PRODUCTION credit under existing contract.
C. Independent scheduler + execution runtime: possible direct authoritative occurrence, clock and execution proof, but requires adopted event-authority, runtime-security, custody, cost, outage, and acceptance contracts. **Recommend only offline C PoC specification**, not deployment.

## Proposed offline architecture (NOT CURRENT PRODUCTION AUTHORITY)

- Scheduler Authority signs immutable occurrence envelope `{schedule_id, nominal_slot_utc, nominal_slot_taipei, trading_date, cadence, occurrence_id, authorization_id, issued_at_utc, nonce, policy_version, allowed_main_sha, binding_sha, expiry_utc}`.
- Integrity: approved public-key rotation, signature/algorithm allowlist, monotonic nonce and durable replay ledger, clock synchronization independent of process clock. An unsigned/ad-hoc wall-clock record is never trusted.
- Admission checks: accepted key/scope, legal calendar/slot, route=B, exact approved main/derived activation binding, `issued<=nominal+900s` only as a proposed design check, authentic actual start time, end-to-end `actual_start_utc - nominal_slot_utc <=900`, and no negative delay.
- Runtime: one admit per occurrence with durable atomic lock and idempotency key; zero automatic retry credit; spool failure evidence but never retime, re-label or promote failed runs. Data and State/Portfolio/Ledger pipelines remain unchanged.
- Custody: immutable time authority snapshot, signature, Scheduler dispatch receipt, runtime admission receipt, runtime actual-start receipt, source bundle, canonical commit & state hashes, corresponding workflow/job/process IDs, acceptance decision and independent attestation.
- Fail-closed: missing/mismatched time or key, stale permit, wrong cadence, ambiguous DST/holiday, clock drift, duplicate, queue-delay breach, unexpected sha, unreachable proof authority, wrong production source or ledger fork -> BLOCKED, no publishing and no credit.

## Contract change impact (separate Owner approval mandatory)

| Current contract | Needed proposed change | Until explicitly adopted |
|---|---|---|
| CER081 actual-timing: event=schedule, GitHub API created/start | New independently authenticated external occurrence and actual runtime start, no inference | All external PoC events are NOT_CREDITABLE |
| RATE Production Session: event=schedule, 3x4 ledger | Definition of authorized event class and native schedule vs external source exclusivity | Only native schedule qualifies |
| Scheduler workflows (07:30/09:30/12:00/19:30) | New deployment and rollback plan (if Owner chooses C) | Absolutely no workflow edits or dispatch |
| State, Portfolio, Transaction Ledger | Preserve chronological hash chain and exact 07:30→09:30→12:00→19:30→next trading day 07:30 | No reset/fork/replay |
| Route B Activation | Re-freeze after any merged functional change, preserve current code/binding source | No edits to activation baseline |

## Offline simulated PoC test vectors (no live credentials, no external calls)

C01 signed nominal slot at T=0, actual start at T+899: eligible timing only in proposed contract.
C02 T+900: boundary exactly passes if policy says >900 is blocking; C03 T+900.001: fail closed.
C04 wrong/missing event authority/signature/key or duplicate `occurrence_id`: fail.
C05 same occurrence different SHA/branch or changed Activation Binding: fail.
C06 start before scheduled occurrence, invalid timezone/trading day, invalid cadence: fail.
C07 clock drift/unsynchronized source, queue backpressure, evidence endpoint unavailable: fail.
C08 one runtime crash and re-dispatch: never second acceptance credit; first attempt custody maintained.
C09 manual dispatch relabeled as schedule: reject; external simulator must never generate official Credit.
C10 State/Portfolio/Ledger fork, source fallback or changed Frozen Contract: reject.
C11 3 trading-day/4 cadence simulated chain must not be promoted to official session.
C12 evaluate key rollover, cancellation/revocation, independent replay, tamper detection, cost/free-tier constraints.

## Measurement and exit gates

PoC may measure distribution of `dispatch_delay`, `queue_delay`, `execution_admission_delay`, `actual_start_delay`, clock drift and percent <=900 seconds with confidence bounds. **A simulated pass is never production reliability proof.** Evaluate real feasibility, cost, account/quota/security, failure recovery and auditability through separate non-production authority only.

### Owner decisions required
C-D1: retain native-only or adopt alternative signed external scheduling event authority; C-D2: define signed occurrence custody and key governance; C-D3: scope/fees/provider and security boundary; C-D4: explicit Contract Change Request for CER081, Session and Final Acceptance; C-D5: authorize controlled non-production experiment and later separate Production rollout, no direct migration.

### Independent review
Exact-head doc-only diff, all relevant CI terminal, no official workflow/contract modifications, no production event, no secret or network calls, realistic immutable-evidence model, clear forbidden substitutions and separate Owner Change Control.

`EVENT_SCHEDULE_CONTRACT_UNCHANGED=TRUE`, `DELAY_THRESHOLD_SECONDS=900`, `EXTERNAL_DISPATCH_CREDIT=0`, `PRODUCTION_CREDIT=0`, `CER081_CREDIT=0`, `NO_AUTO_NEXT=TRUE`.
