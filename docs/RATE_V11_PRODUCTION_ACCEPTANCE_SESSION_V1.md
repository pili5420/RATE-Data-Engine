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

The session becomes `READY_FOR_FINAL_ACCEPTANCE` only after at least three complete
trading days and twelve unique official scheduled runs. It still grants no CER-081
credit by itself; the existing final acceptance gate remains authoritative.
