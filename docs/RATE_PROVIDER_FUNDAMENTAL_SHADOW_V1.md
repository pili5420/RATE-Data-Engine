# Provider Fundamental Shadow V1

Scope: `PROVIDER_FUNDAMENTAL_SHADOW_ONLY`. Independent artifact and score field:
`provider_fundamental_shadow_score_v1`. No production consumer imports this layer.
No formal Fundamental/RATE score, trading signal, official TTM or PIT claim.

## Source and Eligibility

The build CLI accepts externally pinned prior delivery index and delivery inventory
hashes. The inventory supplies the trusted feature manifest hash; it is not derived
from the pending feature manifest. The existing feature consumer validates original
producer identity, package, Decimal values, times, coverage lineage, EPS raw/receipts
and official revenue sources. Producer Base/Head remain unchanged. Execution
Base/Head are separate. Socket connections are disabled in the offline CLI.

Keep every source company and all original feature objects, references and missing
reasons. Only companies with all four labelled features COMPUTABLE may be scored.
The minimum of 20 applies AFTER filtering. Missing inputs produce null score/rank;
no imputation, zero fill, median fill, narrower windows or weight redistribution.
The data universe and scoring population have different fields and identities.

## Formula and Numeric Semantics

Use one common complete-input population for all three components:

`0.50 * pctl(revenue_mean) + 0.30 * pctl(eps_delta4q) + 0.20 * pctl(eps_latest4q)`

The contract pins the unchanged `src/feature_math.py` Git-blob LF SHA256 (only
Windows checkout CRLF is normalized to LF for this comparison). Its `pctl` converts
to Python float, assigns average 1-based ranks to ties, and applies Python
`round(100*(average_rank-1)/(n-1), 2)`. Conversion must remain finite. Original
feature strings, including EPS Decimal precision, are retained unchanged. The
percentile/contribution/score stage is explicitly binary float, not all-Decimal.
Contributions are summed in revenue/delta/latest order with no extra score rounding.
Identical exact float scores receive competition rank (1 plus count strictly
greater); symbol is only the stable display tie breaker, never a score adjustment.

Fixed EPS periods are 2024Q3 through 2026Q2; latest four 2025Q3 through 2026Q2,
previous four 2024Q3 through 2025Q2. Revenue periods are 2026-07/08/09. EPS sums
remain unadjusted provider-basis features, NOT official/share-aligned TTM.

## Population Sensitivity

A = all four input features complete. B = all three EPS features complete (eight
quarters). C = revenue mean complete. Compute B-A for each EPS component and C-A
for revenue, for the SAME companies in A. Save original values, percentiles,
population identities, differences, median/max absolute differences and ALL
companies tied for the largest change. Never compose the B/C percentiles into a
score. This measures population sensitivity, NOT returns, Sharpe, hit rate or
investment effectiveness. No industry classification is inferred.

## Time, Identity and Consumer

Input feature observation/source/availability times remain in the core. The
shadow-spec effective time and actual generation/validation/as-of times are
separate. Shadow availability is no earlier than every necessary feature,
specification effectiveness, generation and validation. Historical 2026-10-05
PIT remains UNPROVEN. Core identity pins source content/package, source producer,
population membership, formula/pctl version, periods and calculation basis;
generation/validation and execution binding are in a separate envelope.

Outputs are new external-only directories. The manifest hashes each artifact.
The independent consumer verifies pinned manifest, every file, source replay,
recomputes core, ranks, populations, sensitivity and times, and verifies sidecars.
The original feature artifact is consumed, NOT regenerated/rebound to a new Head.

## Engineering and Boundaries

The additive isolation verifier checks every existing Base file/blob and searches
existing source imports for reverse dependencies. Existing provider, feature and
official-history regressions remain unchanged. Synthetic engineering tests cover
known answers (independent less/equal counts), shuffled inputs, ties/zero/negative,
precision/rounding, filtered minimum, missing inputs, finite conversion, source
and digest/time/population tamper, new-process cold consume and formal entry
ABSENT/PRESENT/UPDATED/CORRUPT non-interference. The formal missing-EPS gate remains.
The formal-entry tests use an accepted-input sentinel and block scoring/writes;
they do not claim to calculate real formal ranking equivalence.

Windows and Linux CI are synthetic only. Real local population scoring/source
replay and independent arithmetic audits are recorded separately, never uploaded.
Decision and production eligibility are false; original formal coverage credit
is zero. No Production/state/Portfolio/Ledger, schedule, Run-5 or rebaseline.
