# RATE FinMind Sponsor Snapshot Qualification V1

Scope: `FINMIND_INTRADAY_DIAGNOSTIC_ONLY`.

This layer evaluates whether FinMind Sponsor Snapshot APIs can technically satisfy RATE's blocked
09:30 / 12:00 intraday dependency. It does **not** change the Production source registry, external
dependency status, scheduler wiring, ranking rules, model weights, Decision State, Portfolio or Ledger.

## Provider endpoints

Official documented endpoints used by this diagnostic:

- `GET https://api.finmindtrade.com/api/v4/taiwan_stock_tick_snapshot`
- `GET https://api.finmindtrade.com/api/v4/taiwan_futures_snapshot`

FinMind documents the stock snapshot as Sponsor-only and approximately 10-second update frequency.
It supports `data_id=""` for all snapshots and index IDs including `001` TAIEX and `101` OTC
weighted index. The futures snapshot is Sponsor-only, approximately 30-second update frequency, and
supports `data_id="TXF"`.

Public documentation references:

- https://finmind.github.io/tutor/TaiwanMarket/RealTime/
- https://finmind.github.io/en/tutor/TaiwanMarket/IndexCodes/
- https://finmind.github.io/Pricing/

## Diagnostic gates

A live qualification is limited to three provider calls with zero automatic retry:

1. Full stock snapshot: `data_id=""`
2. Index snapshot: `data_id=["001","101"]`
3. Futures snapshot: `data_id="TXF"`

The token is read only from `FINMIND_API_TOKEN`; it is never printed, hashed into evidence, or
persisted. Raw response bytes are validated and hashed in memory but are not written by the diagnostic.

The evidence reports:

- authenticated Sponsor endpoint access
- HTTP/provider status and response-byte SHA256
- exact documented schema coverage
- duplicate identifiers
- index 001 / 101 presence
- TXF-family presence
- quote timestamps and diagnostic freshness
- optional intersection with an externally supplied RATE 1978-company universe
- request count and zero-retry invariant

If the exact RATE full-universe file is not supplied, full-market coverage is `INCONCLUSIVE`, never
silently inferred from provider row count.

FinMind snapshot timestamps are parsed for diagnostic freshness using Asia/Taipei only when the API
returns a timezone-naive value. This assumption is explicitly recorded and cannot by itself satisfy a
future Production timestamp contract.

## Outputs and boundaries

The output is a summary-only qualification artifact. It intentionally does not store price arrays or
raw provider responses. It may store identifiers needed for diagnostics, counts, content hashes and
small missing/duplicate samples.

Possible final classifications:

- `PASS_CANDIDATE`: technical gates pass, including exact external universe coverage when supplied.
- `PARTIAL_CANDIDATE`: provider access/schema works but a required proof such as exact universe
  coverage or timestamp semantics is unresolved.
- `FAIL_CLOSED`: access, schema, identity, duplicate, numeric, freshness or provider status fails.

None of these classifications authorizes Production. A separate Control Center change request is
required before replacing `EXTERNAL_AUTHORIZED_INTRADAY_FEED_DEPENDENCY`.
