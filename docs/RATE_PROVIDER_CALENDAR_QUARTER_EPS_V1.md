# Provider Calendar Quarter BASIC EPS V1

CR: `RATE-PROVIDER-CALENDAR-QUARTER-EPS-V1`.
Scope: `PROSPECTIVE_SEMANTIC_CONTRACT`, not provider activation.
Normative definition: `contracts/RATE_PROVIDER_CALENDAR_QUARTER_EPS_V1.json`.

Only FinMind `TaiwanStockFinancialStatements`, exact `type=EPS`, and the
existing `FINMIND_BASIC_EPS_EXACT_LABELS_V1` two-label mapping are accepted.
Values remain finite Decimal representations; zero, negative values and
precision are preserved. Original raw/receipt hashes, locators, labels,
per-row observation times and unknown publication/revision fields remain.

| Exact provider date | Calendar label |
|---|---|
| 2024-09-30 | 2024Q3 |
| 2024-12-31 | 2024Q4 |
| 2025-03-31 | 2025Q1 |
| 2025-06-30 | 2025Q2 |
| 2025-09-30 | 2025Q3 |
| 2025-12-31 | 2025Q4 |
| 2026-03-31 | 2026Q1 |
| 2026-06-30 | 2026Q2 |

No non-quarter-end dates, fuzzy mapping, fiscal inference, older-quarter
substitution, annual subtraction or synthetic quarter construction.
This is provider-defined BASIC EPS with a calendar label, NOT official
fiscal-quarter EPS, official common-share-basis EPS or official TTM.
Any future sum must be independently named
`PROVIDER_DEFINED_UNADJUSTED_QUARTER_SUM`; this CR computes no sums and
does not change the calculation owner.

## Knowledge Time

Historical PIT remains `UNPROVEN`; cutoff remains `2026-10-05`.
Provider date, retrieval and first observation are not publication time.
Engineering replay of old observations does not grant prospective formal
use retroactively. Activation and its knowledge-time policy require a
separate `FORMAL_PROVIDER_ACTIVATION_CR`; no observation is grandfathered.

## Coverage and Isolation

The exact original catalogue binding is retained, including market mapping.
All 1978 issuers, 15597 valid positions and 227 explicit gaps remain.
1855 are calendar-window complete; 123 incomplete issuers keep their 757
valid rows. These counts are replay reconciliation expectations, not
hardcoded filtering or evidence of formal eight-quarter acceptance.

The new verifier composes the existing closeout replay, source/label/value
checks and independent fiscal qualification without rewriting any parser.
Calendar semantic PASS coexists with fiscal period `NOT_PROVEN` and
`FUNDAMENTAL_EPS_PERIOD_IDENTITY_UNPROVEN`. Existing qualification outputs
and producer/execution bindings are never rewritten. No active consumer
imports the new opt-in module. The new CLI only writes a fresh external
verification directory and denies financial network calls.

`production_eligible=false`, `fallback_allowed=false`,
`provider_reply_required=false`, original formal coverage credit=0.
Warmup completeness policy, formal EPS owner, first refresh, strategy,
ranking, model weights, Production state, Portfolio and Ledger are unchanged.
Public CI uses synthetic fixtures only; local real replay is reported separately.
