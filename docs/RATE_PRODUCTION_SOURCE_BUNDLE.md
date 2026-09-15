# RATE Production Source Bundle V1

The runtime accepts an authorized, replayable directory containing `manifest.json` and one or more JSON arrays of daily candidate records. Each record must contain price/volume, MA20/MA60/MA120, momentum, relative strength, foreign flow, investment trust flow, large-holder structure, smart-money flow, fundamental score, liquidity, trading status, and source timestamps.

`src.source_bundle.create_input_snapshot_id` hashes the canonical manifest and exact file bytes. The resulting `rate-snapshot-<sha256-prefix>` is the immutable `input_snapshot_id` used for replay and duplicate keys. Missing files, missing fields, invalid ranges, stale/untyped metadata, and duplicate logical keys fail ingestion.

The repository intentionally does not contain a fabricated source bundle. Run `scripts/ingest_production_bundle.py <authorized-bundle>` after the Control Center provides the source files. Until then Production E2E remains BLOCKED.

The machine-readable metadata contract is `config/RATE_PRODUCTION_SOURCE_BUNDLE_SCHEMA_V1.json`. Every required domain must provide provider, source, source and retrieval timestamps, record count, schema version, SHA-256 content hash, slot-aware freshness, validation status, and attribution/license evidence before snapshot generation.
