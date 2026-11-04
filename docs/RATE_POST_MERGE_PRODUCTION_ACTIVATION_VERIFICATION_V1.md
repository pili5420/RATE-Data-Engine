# RATE V11 Post-Merge Production Activation Verification V1

A merge alone grants no Production credit.

PASS requires the merged activation configuration to match the approved intraday
candidate and two successful official scheduled runs: 09:30 then 12:00. Both runs
must prove 30/30 TWSE/TPEx coverage, PASS intraday decision gates, Production Data
Gate PASS, Decision State/Portfolio/Transaction Ledger continuity, zero fallback and
zero automatic retry.

Only event=schedule runs count. A PASS yields PRODUCTION_ACTIVATION_VERIFIED and
advances to CER-081 Production Acceptance.