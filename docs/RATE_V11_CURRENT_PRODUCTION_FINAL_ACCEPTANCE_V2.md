# RATE V11 CURRENT_PRODUCTION Final Acceptance V2

This is the final acceptance gate for the new activation-bound Production Acceptance
path.

Unlike the historical CER-081 soak implementation, this gate does not depend on the
fixed 2026-09-21 through 2026-09-25 window. It consumes the new
`RATE_V11_PRODUCTION_ACCEPTANCE_SESSION_SUMMARY_V1`, which only admits official
scheduled runs after verified Production activation and on the exact activated main.

Final acceptance requires all of the following simultaneously:

- post-merge Production activation verified;
- CURRENT_PRODUCTION session ready;
- at least 3 complete trading days;
- at least 12 unique official scheduled runs;
- full 07:30 / 09:30 / 12:00 / 19:30 coverage;
- independent state and cross-day continuity PASS;
- scheduler reliability PASS with no manual-dispatch substitution;
- deterministic replay PASS with no new record creation;
- model-freeze integrity PASS;
- exact merged-main binding across activation and session evidence.

Only a full PASS may emit
`RATE_V11_PRODUCTION_ACCEPTED / CER081_ACCEPTED_CLOSED / development_status=COMPLETE`.

The validator itself performs no Production mutation.
