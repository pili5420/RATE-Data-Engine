# RATE V11 CURRENT_PRODUCTION Acceptance Session V1

This gate starts the real RATE V11 Production Acceptance window after Production
activation has been independently verified.

It deliberately replaces historical fixed soak dates with an activation-bound,
current-main session.

Only runs satisfying all of the following can receive session credit:

- official `event=schedule`;
- trading date on or after the session start date;
- exact activated merged-main SHA;
- one of 07:30 / 09:30 / 12:00 / 19:30;
- Production Data Gate PASS;
- Decision State, Portfolio, Transaction Ledger and Ranking continuity PASS;
- no fallback;
- no automatic retry.

Manual dispatch, pre-activation historical runs, cross-main runs and duplicate
date/cadence runs receive no credit.

Each admitted run persists normalized acceptance evidence for official schedule provenance,
Production Data Gate, Decision State continuity, Portfolio continuity, Transaction Ledger
continuity, Ranking continuity, fallback-free execution and no automatic retry. The session
summary recomputes these gates from the durable ledger; missing or tampered evidence fails
closed and cannot be hidden by the original admission result.

The session becomes `READY_FOR_FINAL_ACCEPTANCE` only after at least three complete
trading days and twelve unique official scheduled runs, independent state/cross-day lineage
PASS, and all durable acceptance evidence gates PASS. It still grants no CER-081 credit by
itself; the existing final acceptance gate remains authoritative.

## Independent lineage audit

The session does not trust a run's self-reported continuity flag by itself. Before final readiness, it independently orders admitted runs and verifies that every next `previous_state_id` equals the immediately preceding `current_state_id`.

Within-day links must follow `07:30 → 09:30 → 12:00 → 19:30`. Cross-day links must be exactly `19:30 → next trading-day 07:30`. Any reset, fork, broken state ID, or invalid cross-day boundary fails closed.
