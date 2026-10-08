# Provider Financial Features V1

Authority: the current user-approved `PROVIDER_FINANCIAL_FEATURES_ONLY` engineering
decision, not the historical closeout CR's proposed Production adoption. The CR
remains `PROPOSED_NOT_APPROVED` in its original location.

## Narrow Approval Mapping

| Difference | Approved implementation | Still not authorized |
|---|---|---|
| Source | Independent FinMind provider-defined quarterly BASIC EPS features; separately bound existing MOPS revenue; no provider reply requirement | Active Source/Data registry or formal EPS artifact substitution |
| Availability | Retain every bound catalogue company and all valid EPS; feature-local dependencies, nulls and reasons | Reducing the ranking population, lowering the original eight-quarter gate, imputation |
| Calculation | Four explicitly named unadjusted/provider or official-revenue features | Official TTM, share adjustment, Fundamental scoring, percentiles, weights, ranks |
| Time | Actual input observations, generation, verification and contract effective time; independent forward feature availability | Historical PIT backfill, changing the 2026-10-05 cutoff or old artifact timestamps |

The independent contract is `docs/contracts/RATE_PROVIDER_FINANCIAL_FEATURES_V1.json`.
Its effective time establishes this engineering contract only, not Production
activation. The prior proposed generic four-quarter feature name is superseded
**only within this engineering product** by the four expressly approved names:

- `finmind_eps_sum_latest4q_unadjusted`: 2025Q3, 2025Q4, 2026Q1, 2026Q2.
- `finmind_eps_sum_previous4q_unadjusted`: 2024Q3, 2024Q4, 2025Q1, 2025Q2.
- `finmind_eps_delta4q_unadjusted`: latest four minus previous four; all eight required.
- `official_revenue_yoy_mean_3m`: 2026-07, 2026-08, 2026-09; three finite values required.

## Arithmetic and Missingness

Quarter labels, not JSON order, select dependencies. Each feature is evaluated
independently. A previous-window gap does not block a complete latest window.
All companies, every valid EPS row and the original gap classifications remain
in the product. Missing, duplicate and conflicting data are distinct: legitimate
absence gives null plus `NOT_COMPUTABLE`; duplicate/conflict/nonfinite/identity
or source-integrity errors reject the entire attempted package.

EPS uses exact Decimal addition with a precision derived from input coefficients
and exponents, including context-independent negation for the delta. Inputs retain
zero and negative values. EPS values serialize as exact Decimal strings, without
quantization. Revenue uses Decimal of the existing official parser's serialized
normalized number, retaining the official YoY percent-number scale (100 is not
silently converted to 1). The fixed denominator is three; output is a Decimal
string with 12 fractional places, ROUND_HALF_EVEN. Original official YoY text is
also preserved. `UNDEFINED_ZERO_BASE` stays null; no replacement month or smaller
denominator is permitted.

Every feature retains its name/version/value/window, necessary inputs, source
references, status/missing reasons and maximum input observation/validation time.
`share_basis_alignment=NOT_ADJUSTED`, `not_official_ttm=true`.

## Identity and Time

`core` contains the contract, ordered labelled inputs, original observations,
values and source bindings. Its SHA256 is stable for the same inputs and contract,
including reordered input lists. The execution envelope separately contains
actual generation/validation times, Base/Head and per-feature availability.
Availability is no earlier than contract effect, required observations/source
validation, generation and feature validation. Future or inconsistent times are
rejected. A pinned file manifest protects the envelope as well as core content.
Missing features have no available-at claim. Unknown public/revision/filing and
Q4 production-method fields remain unknown; provider date is not announcement time.

## Local Build and Independent Consumer

Use `scripts/build_provider_financial_features.py` with `--expected-base` and
`--expected-head`. The builder requires `--closeout-manifest`, its exact
`--closeout-manifest-sha256` and a new external `--output-dir`. Discover the manifest
from the delivered closeout, not guessed provider paths. No transport is invoked.

The thin input bridge verifies the pinned closeout manifests, all prior input
hashes, catalogue/plan/ancestor/ready evidence and saved intents, then uses existing
`read_events`, provider response validation, MOPS `load_response`, existing
revenue parser and semantic validator. It does not create or recover a plan.

Start a **new process** with `--consume DIRECTORY` and
`--expected-manifest-sha256 HASH` (and the same Base/Head). The consumer verifies
file and content hashes, recomputes each feature, validates time/contract and
replays the original source inputs. `--as-of` earlier than feature availability
rejects use. EPS inputs remain precise; metadata keeps its separate shared codec.

Outputs use a separate `RATE_PROVIDER_FINANCIAL_FEATURE_PACKAGE_V1` identity.
They cannot write within a Git checkout, the source coverage/closeout roots or
Production/LATEST/state/Portfolio/Ledger namespaces. No alias to formal EPS,
Fundamental or formal artifacts is added.

## Verification and Boundaries

`scripts/verify_provider_financial_features.py` checks a narrow additive allowlist
at actual Base/Head, every existing tracked file's bytes and no reverse import
from formal entries. It preserves and runs the 93 existing provider regressions
plus official history/parser regressions, separately from new feature tests.
Windows/Linux CI is synthetic engineering evidence only; no local raw, receipts,
company values or inventories are uploaded.

Non-interference tests exercise the unchanged formal live-history entry with an
existing synthetic accepted-input sentinel under ABSENT/PRESENT/UPDATED sidecars,
and separately its missing-formal-EPS gate. Actual formal scoring and Production
writes are blocked in these tests. They do not certify real rankings; full existing
blob protection and absence of a reverse dependency establish the scoped isolation.

Real 1978-company replay, reproducibility and before/after source invariance are
local-only evidence, separate from public CI. Stop at READY_FOR_REVIEW:
`feature_calculation_allowed=true`, `decision_eligible=false`,
`production_eligible=false`, `original_eight_quarter_coverage_credit=0`.
