# Phase B: Formal EPS Period Identity Qualification

Base: `57b1d053d7374a100cdb97a24c6a8e01ad5061e9`.
Qualification/evidence engineering only. No active EPS contract or owner changes.

## MOPS feasibility

`MOPS_FORMAL_EPS_PERIOD_IDENTITY = NOT_PROVEN` for the available formal-owner
Run-4 material. The saved `ajax_t163sb04` EPS response is HTTP 200, 2529 bytes,
SHA256 `b1f0859d568793c299de67b762030bc5ff3192b31c2e9b4805a213e055976118`.
It visibly says no query data; it has no issuer, fiscal year/quarter, report
duration, publication timestamp or revision identifier. POST `year/season/TYPEK`
prove the request, not the returned EPS identity. This is not proof MOPS is
permanently incapable or that every issuer has no EPS. Original Run-4 failures
remain historical failures; current no-data handling does not qualify records.

The existing summary owner can recognize a response title/selected control and
extract an explicit report date. A title is not an XBRL duration. A report
generation date is not an exact public-version binding. A raw hash identifies
bytes, not the time those bytes first became public. Optional filing fields in
the history store and latest-disclosure selection do not prove complete revisions.
The original `OFFICIAL_SINGLE_QUARTER` output label is not independent evidence
for Q2/Q3/Q4 duration. No inference or annual-minus-three-quarters calculation is
introduced here. The original fail-closed owner is unchanged.

## Existing document evidence (different product)

Hash-pinned `tests/fixtures/eps_duration/official-proof.zip` contains actual MOPS
Inline XBRL and calendar evidence. The existing replay verifies receipts, issuer
CompanyID/Market, Year/Quarter, context identifier/startDate/endDate, BASIC vs
DILUTED QName, report category/scope, unit and exact value. These prove individual
duration-qualified facts, **not** that the current summary owner supplies them.
Later-document comparative contexts remain comparisons, not new filings or
original-public versions. Q4 annual contexts cannot satisfy a single quarter.
The existing parser leaves filing/revision/public time unknown; no real complete
8-quarter public-version chain is established. Historical PIT remains UNPROVEN.

The isolated `qualify_eight()` composes existing raw replay, semantic and PIT gates.
Its index attestations must be supplied as evidence; it never invents them.
Engineering fixtures demonstrate gate behavior only, not real source completion.
Even an engineering PASS has zero formal credit and cannot activate Production.

## FinMind formal-provider gap analysis

A **separate formal-provider Change Request is required** to replace the official
owner. Existing provider features/Shadow permissions do not authorize formal EPS.
No supplier reply is required. The following decisions/evidence are still distinct:

| Area | Existing evidence | Remaining formal gap / decision |
|---|---|---|
| Source | FinMind dataset, exact raw/receipt/locator, accepted provider BASIC labels | Explicit new formal artifact/consumer binding; never alias official single-quarter |
| Period | Provider date to local quarter mapping, 15597 valid positions | Formal fiscal-duration mapping and provider scope/unit authority; no official filing claim |
| Availability | 1978 retained; 1855 complete; 123 issuers/227 missing | Keep exact eight-quarter requirement and all issuers; no exclusion, zero fill or older replacement |
| Calculation | Unadjusted provider features allowed separately | Q4 construction and cross-quarter share basis unknown; source-only substitution into formal TTM not approved |
| Version | Exact saved payload and observation times | No complete original/revised public-version chain or historical cutoff binding |
| Time | Actual observed-forward availability | Explicit prospective formal-use decision; no 2026-10-05 historical backfill |

Existing 757 valid positions belonging to incomplete issuers remain preserved.
Candidate completeness is not formal coverage. Current provider acceptance is
not revoked; this PR neither promotes nor blocks already-authorized research use.

## Next necessary action

Choose an explicit source path: (a) qualify source-bound filing index/publication/
revision evidence plus exact quarterly contexts (including Q4) for the official
owner; or (b) separately approve Source/Availability/Calculation/Time differences
for provider-defined prospective formal use. Repeating the same no-data request
without new evidence will not establish those semantics. No warmup, refresh,
publication, historical pin changes, rebaseline or strategy changes are authorized.
