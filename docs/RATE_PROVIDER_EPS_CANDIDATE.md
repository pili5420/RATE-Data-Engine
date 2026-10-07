# FinMind Provider EPS Candidate

This additive, offline adapter accepts the already saved three-company,
2024Q3 through 2026Q2 local analysis package. It never performs network requests,
replaces official EPS, calls scoring/ranking, or writes active artifacts/state.

## Independent Schema And Consumer

`RATE_PROVIDER_EPS_CANDIDATE_V1` / `PROVIDER_EPS_CANDIDATE_ONLY` is not an alias
for `quarterly_eps` or `single_quarter_eps`. `consume_candidate()` accepts only
this schema, validates its digest, boundaries, labelled order and times, then
returns a labelled candidate-only preview. Existing consumers do not import it.

The source remains FinMind / TaiwanStockFinancialStatements /
PROVIDER_DEFINED_QUARTERLY_BASIC_EPS / ACCEPTED_AS_PROVIDER_DATA.
Provider replies are not required. Q4 values remain unchanged; their production
method remains UNPROVEN. Unknown filing_id, revision_id and public_time remain
explicit null. Provider dates are calendar-quarter mappings for local analysis,
not announcement dates or proven official filing periods. Six existing numerical
corroborations are retained, not substituted or upgraded into period/version proof.

Each company has eight labelled rows, explicitly LATEST_TO_OLDEST:
2026Q2, 2026Q1, 2025Q4, 2025Q3, 2025Q2, 2025Q1, 2024Q4, 2024Q3.
The first four and last four are never inferred from input JSON order.
Zero/negative values and exact decimal strings are retained; there is no TTM,
annual subtraction, ranking, percentage growth or Fundamental calculation.

## Offline Replay

Use a clean checkout at the reviewed PR head. Supply exact full commit SHAs:

```powershell
py -3 -B scripts/build_provider_eps_candidate.py `
  --input-dir "D:\RATE-Evidence\rate-eps-public-research\eight-quarter-local-20261007-234816" `
  --output-dir "D:\RATE-Evidence\rate-eps-public-research\provider-eps-candidate-NEW_TIMESTAMP" `
  --expected-base BASE_SHA --expected-head HEAD_SHA
```

The output must be new and outside the repository/input tree; protected output
path components are rejected. Outputs are candidate JSON, consumption preview,
before/after source SHA256 inventory and local verification evidence. No source
bytes/receipts are copied into the repository or uploaded. The CLI performs two
offline replays to check stable identity/labelled values. Generated and verified
timestamps are intentionally fresh; therefore full package bytes differ across
runs. The stable artifact identity binds ordered value/provenance/version fields;
the full payload digest additionally covers each individual generated package.
Hashes detect inconsistency, not authenticity or a maliciously re-signed package.

The adapter reuses existing receipt byte/hash/time verification, normalizing only
an in-memory receipt. Original receipts remain unchanged. All referenced response
bytes, receipt hashes, indexes, values and own acquisition times are checked.
Missing/duplicate/conflicting quarters, nonfinite values, hash/locator tamper and
unsupported version claims fail closed. No missing-quarter substitution is used.

`dataset_complete_observed_at` is the latest of all 24 acquisition observations,
never the original 17-row observation. Acquisition, row verification, validation
and generation times are distinct. Cutoff 2026-10-05 stays unchanged and UNPROVEN.

## Engineering CI Versus Real Local Replay

Public CI runs only `tests/fixtures/provider_eps_candidate/engineering_spec.json`
and generated synthetic temporary responses, explicitly marked
ENGINEERING_FIXTURE_NOT_REAL_FINMIND_REPLAY. It needs only Python stdlib and Git.
It never runs the local real-data CLI. Passing fixtures is not real-data replay.

`scripts/verify_provider_eps_candidate.py` binds the actual base/head, permits
only the eight new files for this delivery, checks every existing Git tree entry,
requires a clean worktree and no candidate imports in existing entry points, and
compares working-file hashes before/after engineering tests. No historical
PR #29/#30/#31 frozen-baseline evidence is changed or regenerated.

Real 24-row replay is a separate local operation with its own source hashes and
base/head binding. Real materials and generated local candidates remain local;
do not upload them as CI artifacts. The new workflow has no schedule or dispatch.

## Authorization Boundary

local_window_complete=true; local_window_coverage=24/24;
formal_eight_quarter_acceptance=NOT_PERFORMED; production_eligible=false;
original_eight_quarter_coverage_credit=0.

READY_FOR_REVIEW only. Production contract/registry changes, active EPS artifact
translation, full-universe/revenue inputs, scoring integration, Historical PIT
acceptance, Work/B1 integration and strategy activation are not authorized here.
No merge, Run-5, resume or rebaseline is performed by this adapter or workflow.
