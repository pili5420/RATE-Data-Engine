# RATE_PRODUCTION_DATA_SOURCE_SPEC V1.0
Document ID: RATE-PDSS-V1.0
System: RATE V11
Owner: RATE / OIS AI Control Center
Status: FROZEN / APPROVED FOR ENGINEERING
Effective Date: 2026-09-15
Related: RATE-PLS-V1.1 / RATE-DC-V1.0

## 1. Source Governance
Priority:
1. Official Primary Source
2. Authorized Production Feed
3. Deterministically Derived Data

Do not use third-party web scraping, search-result values, LLM estimates, silent source overwrite, or unauthorized real-time feeds as production evidence.

## 2. Required Data Domains
- Price / Volume
- Trading Metadata
- Institutional
- Large Holder
- Fundamental
- Market Benchmark

## 3. Price / Volume
Required daily raw fields:
symbol, trade_date, open, high, low, close, volume, turnover, source, source_timestamp.

Historical window:
- minimum 120 valid trading days
- target rolling store 180 valid trading days

MA20/60/120, Momentum and Relative Strength are calculated by RATE Engine from raw data.

For 09:30 and 12:00 intraday decisions require:
last_price, intraday_volume, intraday_turnover, quote_timestamp.

If no authorized intraday feed exists:
INTRADAY_SOURCE_UNAVAILABLE.
Previous close must not be presented as a live quote.

## 4. Institutional
Required:
symbol, trade_date, foreign_net, investment_trust_net, source_timestamp, source.

Units must be explicit and consistent.
If current-day official data is not yet published, preserve latest_available_trade_date.

## 5. Large Holder
Required:
symbol, period_end, holder_bucket, shares, percentage, source_timestamp, source.

This is low-frequency structural data. Latest officially published period may be used while preserving the true as_of_period.

## 6. Fundamental
Minimum:
symbol, reporting_period, revenue, revenue_yoy, eps, source_timestamp, source.

If RATE calculation requires an undefined fundamental input:
SPEC_REQUIRED.
Codex must not invent a new factor.

## 7. Relative Strength Benchmark
- listed stocks -> TAIEX
- OTC stocks -> TPEx benchmark/index

Benchmark and stock histories must be trading-date aligned.

## 8. Freshness SLA
Freshness is evaluated by source_domain x report_slot x publication_schedule, not one global minute threshold.

07:30:
- Daily OHLCV: latest completed session
- Institutional: latest officially available
- Large Holder/Fundamental: latest published period
- Trading status: current

09:30 / 12:00:
- Authorized intraday quote required
- Institutional: latest officially available
- Large Holder/Fundamental: latest published period
- Trading status: current

19:30:
- Daily OHLCV: current completed session
- Institutional: current day if officially published, otherwise latest officially available per publication schedule
- Large Holder/Fundamental: latest published period
- Trading status: current

Official source not yet published does not automatically mean stale.
Use freshness_status=LATEST_OFFICIAL_AVAILABLE where applicable.
Use STALE only when the expected publication schedule has been exceeded.

## 9. Source Conflict
Priority:
Official Primary -> Authorized Feed -> Derived/secondary evidence.

Material conflict beyond configured tolerance:
SOURCE_CONFLICT
validation_status=FAIL.
No silent overwrite.

## 10. Production Source Bundle
RATE_PRODUCTION_SOURCE_BUNDLE must contain:
- manifest
- market_daily
- market_intraday
- institutional
- large_holder
- fundamental
- benchmark
- trading_metadata

Each domain records:
provider, source_type, source_timestamp, retrieval_timestamp, market_date/reporting_period,
record_count, schema_version, content_hash, freshness_status, validation_status.

## 11. input_snapshot_id
Generate only after Source Bundle passes:
Schema + Type + Range + Duplicate + Source + Freshness.

Format:
RATE-{YYYYMMDD}-{SLOT}-{HASH}

HASH must be deterministic from actual Source Bundle content.
Same bundle => same snapshot ID.
Different content => different snapshot ID.

## 12. Blocking Matrix
Blocking:
- Price history missing
- Trading metadata missing
- Required benchmark missing
- Required M7 raw input missing
- Required MHE raw input missing
- Required Smart Money input missing
- Required ranking input missing

Result:
DATA_SOURCE_INCOMPLETE.

Conditional blocking:
09:30 / 12:00 without authorized intraday feed => INTRADAY_SOURCE_UNAVAILABLE for that slot.
This does not automatically block 07:30 or 19:30.

## 13. Data Lineage
Every final score must trace:
Score -> Component -> Raw Field -> Source Bundle -> Provider -> Source Timestamp.

## 14. No Guess / Silent Imputation
Forbidden:
NULL->0
NULL->average
NULL->previous day
missing source->LLM estimate
unavailable source->web search value

Carry-forward is allowed only where this contract explicitly permits latest officially published low-frequency data, while retaining its true period.

## 15. Production Data Gate
Production Data Source may be AVAILABLE only if:
Source Authorization=PASS
Schema=PASS
Type=PASS
Range=PASS
Duplicate=PASS
Source Lineage=PASS
Freshness=PASS
Required Domains=PASS
Snapshot Generation=PASS

Then:
input_snapshot_id != null

## 16. Codex Acceptance Criteria
Codex must demonstrate:
Production Source Bundle=PASS
Source Authorization=PASS
Freshness Validation=PASS
Data Quality=PASS
input_snapshot_id=generated
Snapshot Determinism=PASS

Then execute full RATE E2E:
Source Bundle -> Candidate Pipeline -> Smart Money -> M7 -> MHE -> Stage -> Rotation ->
Top50 -> Short Top30 -> Long Top30 -> Production JSON -> E2E Validation.

No strategy change is authorized by this specification.
