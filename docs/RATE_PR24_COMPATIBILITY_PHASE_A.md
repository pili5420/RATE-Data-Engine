# PR24 Compatibility Integration - Phase A

Base: `b1d4376c1e774bf09b16bde619a352cc9d48dcc2`.
Selective source: PR24 Head `2c234218c7b8c22286540094ba4bc9c24a6e062f`.
Scope: CODE INTEGRATION ONLY. This is not warmup or Production acceptance.

## Per-file integration decisions

- Scheduler 09:30 and 12:00: retain MAIN bytes, public-official builder, runtime, report archive and publisher. Never switch to the former full-intraday path.
- Scheduler 07:30 and 19:30: retain cron, concurrency, default runtime and publication conditions. Add default-false manual opt-in preparation; it cannot satisfy scheduled publication conditions. No dispatch is performed in Phase A.
- Source builder: additive `--phase2` path for 07:30 / 19:30. For 09:30 / 12:00 the flag selects the existing public-official partial mode, not the old intraday materializer.
- Source publisher: recognize the distinct Phase2 schema; explicit CLI `--phase2` keeps MAIN/schedule/source authority validation. Do not impose PR24's obsolete blanket rejection of existing MAIN public reports.
- State publisher: additive `--phase2` replay and canonical binding. Preserve MAIN's public source replay, protected-account checks and immutable ready-manifest ordering.
- Resolver: opt-in Phase2 resolution at 07:30 / 19:30; retain the existing intraday resolver. An EOD partial predecessor must be the same-day 12:00 slot.
- Catalogue: retain MAIN byte-for-byte, including the later transport hardening. No old catalogue overwrite.
- Decision calculation: preserve the existing formula owners. Partial states retain the prior ranked records separately; use those records only for Stage continuity, never as current intraday price. Formal EOD input is still mandatory for the next full-market calculation.

## Governance

`REPORT_RUNTIME_STATUS=PARTIAL_VALID` at 09:30 / 12:00 remains report-only.
`MARKET_INTRADAY_PRICE_GATE=BLOCKED_EXTERNAL`,
`FULL_INTRADAY_DECISION_STATUS=BLOCKED_EXTERNAL`,
`FULL_PRODUCTION_ACCEPTANCE=NOT_ALLOWED`, `fallback_allowed=false`.
Report soak and CER081 remain separate, with unchanged governance owners.
The imported Phase2 contract explicitly does not authorize activation.

The official EPS provider contract, Source registry, original pins, historical
acceptance bytes, strategy/ranking/model owners, and production artifacts are
protected. `FUNDAMENTAL_EPS_PERIOD_IDENTITY_UNPROVEN` remains a valid blocker.
There is no candidate FinMind-to-formal EPS alias or coverage credit transfer.

## Verification

The strict Windows/Linux exact-head workflow uses the Phase A verifier when the
new contract is present; it retains every existing assertion and runs 131 legacy,
56 PR42, 48 report-soak, 8 scheduler-lock, 43 imported Phase2 and 9 new integration
tests separately. No existing verifier or test is edited. The verifier also
replays the legacy four-cadence proof, the separated three-day soak proof and a
new cold-CLI Phase2 07:30 -> public 09:30 -> public 12:00 -> Phase2 19:30 chain.
All publications and account/state writes in those proofs target synthetic
temporary copies, never the repository's Production material.

Phase B still requires separate source/warmup/publication authorization; Phase A
does not resolve formal EPS coverage, live intraday access or CER081 acceptance.
