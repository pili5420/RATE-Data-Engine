"""Deterministic GitHub Actions cache identity for historical bootstrap state."""
from __future__ import annotations

NORMALIZATION_SCHEMA_VERSION = 'RATE-STOCK-NORMALIZED-V1'
SOURCE_DATASET_VERSION = 'TWSE_STOCK_DAY_V1'
CHECKPOINT_SCHEMA_VERSION = 'RATE-TWSE-HISTORY-CHECKPOINT-V1'


def compatibility_prefix(universe_digest: str,
                         normalization_schema_version: str = NORMALIZATION_SCHEMA_VERSION,
                         source_dataset_version: str = SOURCE_DATASET_VERSION,
                         checkpoint_schema_version: str = CHECKPOINT_SCHEMA_VERSION) -> str:
    return (f'rate-twse-bootstrap-v1-{universe_digest}-'
            f'{normalization_schema_version}-{source_dataset_version}-{checkpoint_schema_version}-')


def versioned_cache_key(universe_digest: str, run_id: str, run_attempt: str,
                        normalization_schema_version: str = NORMALIZATION_SCHEMA_VERSION,
                        source_dataset_version: str = SOURCE_DATASET_VERSION,
                        checkpoint_schema_version: str = CHECKPOINT_SCHEMA_VERSION) -> str:
    return compatibility_prefix(universe_digest, normalization_schema_version, source_dataset_version, checkpoint_schema_version) + f'{run_id}-{run_attempt}'

