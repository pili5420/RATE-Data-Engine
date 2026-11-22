# RATE V11 P0 Runtime Recovery — Controlled Engineering Candidate

Authorities: OWNER_RATE_V11_P0_RUNTIME_RECOVERY_ENGINEERING_AUTHORIZATION + OWNER_RATE_V11_PR224_P0_FROZEN_COMPATIBILITY_CORRECTIVE_AUTHORIZATION
Disposition: CANDIDATE ONLY — NO PRODUCTION CREDIT, NO MERGE PERMIT.
Baseline: 0334d18bde3bbc8ba0176ab2a51a5d07881e2bd7
Reused observational sources: PR #223, head 92f9b31518b1f7ba5462c2a79ba801df2a125b8a

## FIX-01 — classification date semantics

- The source ISIN \`Date Stock Updated\` is a classification page update date, not an assured trading date.
- \`src/p0_catalogue_temporal.py\` separately diagnoses \`source_update_date\` versus \`trading_date\`. The frozen \`build_catalogue\` and \`validate_catalogue\` functions are restored to the exact PR #223 version and remain strictly same-date, until a separate Owner-approved effective-date contract exists.
- **BLOCKED SOURCE POLICY:** An official independent effective-as-of-target-date authority has not been approved. Earlier or later source update dates MUST remain \`STALE_OR_FUTURE_CATALOGUE\`. No user flag, test mock, environment override, or unverifiable \`true\` bypass is allowed.
- PR #223 source diagnostics are preserved. 2026-11-20 historical HTTP content cannot be re-created from a contemporary page.
- Only after Owner approves the authoritative temporal validity contract plus independent replayable evidence may a subsequent **separately authorized** engineering change support a different date.
- Full-market exact-date EOD quote gates, 180-session history, coverage, hashing and State gates are unchanged.

## FIX-02 — schedule admission

- Only **07:30 and 19:30** candidate schedule workflows call \`scripts/enforce_p0_scheduler_admission.py\` after timing capture and **before** source acquisition. The 09:30 and 12:00 workflows have been restored byte-for-byte to PR #223 to preserve frozen intraday compatibility; their equivalent pre-admission wiring is **NOT IMPLEMENTED** and requires a separate targeted Owner Frozen Contract decision.
- \`qualify_schedule_before_sources\` verifies GitHub run and job identity, job started timestamp from Job API, nominal Taipei slot, SHA, workflow path, first attempt and strict 900-second boundary. Missing, invalid, delayed or mismatched timing => exit 1.
- This is a **safety repair** preventing stale jobs from continuing; it cannot make GitHub native \`schedule\` punctual. Existing \`workflow_dispatch\` continues as originally controlled and is **not** a Production scheduled substitute.
- External trigger remains DESIGN ONLY: independent trusted timer; authenticated short-lived permit; allowed repository/cadence/slot; immutable slot proof and nonce; replay protection; GitHub run/job identity and exact head; tested trigger-to-job delay; no double publication; 899.9/900/900.1 second boundaries. No credentials, provider setup, event route or deployment authorized.

## FIX-03 — predecessor diagnostics

- \`src/p0_state_chain_diagnostics.py\` is a stand-alone offline/read-only diagnostic for missing exact predecessor slots and the approved single-use first refresh **candidate**, never generates or admits missing State.
- Frozen \`scripts/resolve_production_runtime_context.py\` is restored to main. Diagnostics are **NOT** injected into Production runtime context; a later separately approved integration would be required.
- Verify 2026-10-02 initial seed ID/Hash against approved policy and single-use permit on a future specifically authorized run. No resetting, synthetic slot, historical acceptance replay or ledger modification.
- 09:30/12:00 public-official \`PARTIAL_VALID\` report execution is not full intraday investment qualification.

## Evidence/acceptance boundary

ENGINEERING CI PASS is not Production PASS; new P0 admission rejects stale jobs, so future scheduled runs may fail earlier with a more accurate reason. Actual Production success requires independently adopted source contract, on-time trusted trigger, full EOD, legal predecessor, publication and readback, and one subsequent four-cadence chain. CER-081 Production Credit remains zero.

STOP: No auto-next, no main mutation, no merge, no runtime/prod activation, no Credentials/Rulesets changes.

