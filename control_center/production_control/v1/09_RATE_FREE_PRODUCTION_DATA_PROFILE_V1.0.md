# RATE_FREE_PRODUCTION_DATA_PROFILE V1.0
Document ID: RATE-FPDP-V1.0
System: RATE V11
Owner: RATE / OIS AI Control Center
Status: FROZEN / APPROVED FOR ENGINEERING
Effective Date: 2026-09-15

## Objective
Define the zero-subscription production-data profile for RATE while preserving the frozen M7, MHE, Stage, Rotation, Smart Money, and Top50/Top30 model logic.

## Authorized Free Sources
### TPEx Open Data
Use dataset-level sources released under Open Government Data License v1.0 for:
- OTC daily market/close data
- OTC individual institutional trading
- OTC benchmark
- OTC market status

### TWSE Open Data
Use only TWSE datasets with explicit dataset-level authorization evidence for:
- listed daily OHLCV
- TAIEX benchmark
- symbol master
- daily trading status / suspension and applicable restriction mapping

### TDCC Open Data
Use the official shareholder distribution dataset / OpenAPI for Large Holder evidence.
Preserve actual reporting period and source timestamp.

### MOPS / FSC Open Data
Use explicitly licensed open datasets for:
- monthly revenue
- revenue YoY
- EPS / income-statement evidence
- other fundamental fields only when already defined by the RATE Data Contract

### FSC t19 Open Data
Role: market-level institutional regime / cross-check evidence only.
It MUST NOT substitute for stock-level TWSE institutional data in M7 or Smart Money.

## TWSE T86 Free CSV
Role: listed-stock individual institutional source candidate.
Source status: OFFICIAL_SOURCE_CONFIRMED.
Free access status: AVAILABLE.
Automated production authorization: PENDING_WRITTEN_CONFIRMATION.
Production authorization: BLOCKED_PENDING_WRITTEN_CONFIRMATION.

Until written authorization or other explicit authorization evidence is preserved:
- T86 must not be used to declare the full RATE Production Data Gate PASS.
- T86 must not generate a full production input_snapshot_id.
- No crawler or automated retrieval shall be enabled as authorized production behavior merely because CSV download is technically available.

## Model Freeze
This profile does NOT authorize any modification to:
- M7
- MHE
- Stage
- Rotation
- Smart Money
- Top50 / Top30 ranking or screening

FSC t19 is supplemental market-regime/cross-check evidence and does not replace individual institutional inputs.

## Phase A Gate
07:30 and 19:30 may become full PASS only when every required daily domain passes authorization, completeness, freshness, quality, lineage, and snapshot generation.
Until TWSE individual institutional authorization is resolved:
- Production Source Bundle = PARTIAL
- input_snapshot_id = null
- 07:30 E2E = PARTIAL
- 19:30 E2E = PARTIAL

## Phase B Gate
09:30 and 12:00 require an authorized intraday feed.
Until available:
- 09:30 E2E = BLOCKED:INTRADAY_SOURCE_UNAVAILABLE
- 12:00 E2E = BLOCKED:INTRADAY_SOURCE_UNAVAILABLE

## Authorization Evidence
For every PASS dataset, preserve provider, dataset name, endpoint/reference, license, attribution requirements, intended use, source timestamp, retrieval timestamp, and evidence reference.

## Engineering Acceptance
Codex shall implement adapters only for PASS-authorized datasets, preserve the T86 authorization hard stop, and report exact remaining blockers without modifying frozen strategy logic.
