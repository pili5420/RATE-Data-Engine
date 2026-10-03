# RATE Thin Work Shadow Manifest V1

`RATE-THIN-WORK-PRODUCTION-BUNDLE-MANIFEST-V1` is an additive shadow contract.
It does not modify `RATE_PRODUCTION_SOURCE_BUNDLE_SCHEMA_V1`, production
`LATEST`, persistent state, portfolio state, or ledgers.

Required fields:

- `system`, `version`, `cadence`, `run_id`, `event`
- `production_snapshot_id`, `commit_sha`, `generated_at`, `market_date`,
  `snapshot_type`
- `source_status`, `freshness_status`, `validation_status`
- `required_datasets`, `datasets_present`, `datasets_missing`
- `blocked_dependencies`
- `input_snapshot_id`, `previous_state_requirement`
- `payload_references`

For `09:30` and `12:00`, absence of an authorized intraday feed must bind
`EXTERNAL_AUTHORIZED_INTRADAY_FEED_DEPENDENCY` in `blocked_dependencies`.
There is no fallback source.

Validation is fail closed. Any missing artifact, binding mismatch, commit or
run mismatch, stale/future timestamp, validation failure, missing required
dataset, corrupted manifest hash, or invalid previous-state requirement returns
`FAIL_CLOSED` and explicitly disallows state, portfolio, and ledger mutation.
