# RATE Fugle Free/Basic Intraday Feasibility V1

Purpose: test whether Fugle's free/basic trial can technically satisfy RATE's 30-symbol
09:30/12:00 dual-market payload without changing Production authority.

Official Fugle documentation exposes per-symbol intraday quote responses containing
exchange, last price, cumulative volume/value and lastUpdated. The documented ticker
surface supports TWSE and TPEx. The free/basic offering is treated only as a candidate:
403, 429, missing fields, stale timestamps, market mismatch or any missing symbol fail closed.

The diagnostic performs exactly one request per approved symbol (30 total), no retry.
The bound universe is sourced from the existing validation-PASS RATE Production source
bundle and contains 25 TWSE + 5 TPEx symbols.

A technical PASS is **not** a license PASS. Until Fugle explicitly confirms that the
account/plan permits RATE's non-display automated analytical use, the result remains:
- production_eligible=false
- registry_activation_allowed=false
- external_dependency_resolved=false

No live request is run by PR CI. A later Owner-authorized manual probe must supply
FUGLE_API_KEY and execute near 09:30 or 12:00.
