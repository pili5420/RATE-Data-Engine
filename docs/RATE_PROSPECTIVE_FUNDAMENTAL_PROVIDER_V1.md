# Prospective Fundamental Provider Acceptance V1

Change request: `RATE-PROSPECTIVE-FUNDAMENTAL-PROVIDER-ACTIVATION-ACCEPTANCE-V1`.
Scope: acceptance engineering and offline evidence only. Independent of PR #51 and #52.
No active owner, scheduler, warmup, calculation, strategy, ranking or publisher is changed.

## Seven Gates

| Gate | Rule | Meaning |
|---|---|---|
| A1 | Exact HTTPS endpoint, dataset, issuer/market, period, approved label, status, bytes/receipt hash and locator replay | Source identity PASS or FAIL, not 1978/1978 completeness |
| A2 | activation <= request <= received == observed <= validated <= first_seen <= now | Proposed prospective acquisition; absent request time is rejected, never inferred |
| A3 | Content-addressed raw/receipt plus immutable hash-linked events and trusted head | No overwrite or silent replacement; original observations remain readable |
| A4 | first_seen = validated system observation, original publication = null | Historical PIT stays UNPROVEN; no historical availability credit |
| A5 | EPS eight exact periods; revenue three finite YoY periods | Issuer readiness is distinct from provider suitability; partial data retained |
| A6 | Fresh external output; process network/write guards; existing Git blobs unchanged | Sandbox only; no Production, State, portfolio, ledger or ranking mutation |
| A7 | All engineering and source gates proven | Recommendation only: READY_FOR_PROSPECTIVE_PROVIDER_ACTIVATION_REVIEW |

`proposed_authorization=AUTHORIZED` is a review recommendation, not an effective authorization.
`provider_authorization=NOT_AUTHORIZED`, `activation_timestamp=null` and `production_eligible=false`
remain mandatory. Control Center must independently authorize activation and set its timestamp.
An approved activation would still not authorize first refresh, ranking or publication.

## Source and Period Semantics

FinMind: `https://api.finmindtrade.com/api/v4/data`, dataset `TaiwanStockFinancialStatements`,
type `EPS`, exact approved BASIC labels from the existing EPS mapping owner. Only the exact
eight calendar-quarter ends 2024Q3 through 2026Q2 are used. No fiscal-quarter inference,
official TTM promotion, annual subtraction or older-quarter substitution.

MOPS Official: existing market/month-specific HTTPS archive endpoint, normalization version
and revenue parser. Required months remain 2026-07, 2026-08 and 2026-09. Null and
UNDEFINED_ZERO_BASE stay non-ready; neither is zero. No numeric scale conversion.

Every acquisition stores provider/dataset, symbol/market issuer records, requested_at,
received_at, source_observed_at, endpoint/URL, raw/receipt SHA256, parser identity,
validation_timestamp, immutable snapshot ID and row locators. Original parser bytes and
validation parser bytes are separately identified. Original CRLF/LF parser representation
may be replayed only if its normalized code bytes exactly match; the original code pin is
never replaced by the validator hash. Raw and receipt bytes are never normalized.
Legacy FinMind receipts did not capture a source-parser hash; that field remains null.
The current validation parser hash must not masquerade as captured acquisition provenance.

## Observation Chain and Availability

The append-only chain records local observation ordering, not official revision ordering.
Neither original/latest public revision nor historical as-of selection is proven.
Latest **whole acquisition scope** is selected: a removed row cannot be silently restored
from an older observation. First_seen belongs to the validated immutable observation;
later changes append new evidence, not a rewritten availability date.

`candidate_activation_timestamp` is frozen in a synthetic sandbox configuration. It is not
an activation command. Legacy real acquisitions are inspected for A1 but deliberately
rejected from A2. No real prospective acquisitions are claimed before authorization.

## Execution and Non-Interference

`run_prospective_provider_acceptance.py --binding ... --binding-sha256 ... --output-dir ...`
validates externally pinned original feature/source evidence and exact Producer/Execution
bindings. It executes the original source consumer in a read-only, network-denied child,
then replays source rows with existing parsers. `--cold-package` plus its trusted SHA256
repeats that replay in a fresh process. Never repins old producer artifacts to new Head.

`--replay-sandbox` verifies persisted event chains against a separately supplied config hash
and trusted head. Existing OS writer locking is reused; `.scan.lock` is coordination only.
No acquisition method, provider credentials, HTTP call, automatic retry or fallback exists.

Public Windows/Linux CI is synthetic only: 836 unchanged relevant regressions plus 61 new
tests. Native real-source verification is separately retained in controlled local storage.
All preexisting tracked Git blobs must be identical to Base; no tests/gates are relaxed.

Historical PIT = UNPROVEN; original_eight_quarter_coverage_credit = 0;
external authorized intraday dependency = BLOCKED_EXTERNAL; fallback_allowed = false.
