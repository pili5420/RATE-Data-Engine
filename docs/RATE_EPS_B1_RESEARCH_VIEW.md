# RATE EPS B1 Research View

Authority: `CR-RATE-EPS-B1-NONDECISION-V1`, `APPROVED_FOR_B1_IMPLEMENTATION_ONLY`.
Delivery: **NONDECISION_RESEARCH_ONLY**. Actual base:
`9c4c9d729c9d537173e227f139abcc06099ce45c` (reviewed MAIN unchanged).
PR #29 is DIAGNOSTIC_ONLY + CI_ONLY; PR #30 is ISOLATED_ONLY. Their historical
scripts, BASE constants, evidence and raw archive are unchanged. Unmerged PR #10
and #24 code is not imported. This implementation consists only of added files.

## Boundary

`src/eps_b1_research.py` is a thin offline presenter over existing
`scripts/replay_eps_duration_proof.py` and `src/eps_duration_facts`. It does not
replace either parser or PIT engine. Production has no B1 imports or routing.
No EPS alias, TTM, EPS derivation, score, ranking, trade signal, scheduler,
deployment, GitHub Pages or Work-report integration is added.

Every view/envelope/manifest/fact includes `usage_scope=NONDECISION_RESEARCH_ONLY`,
`decision_eligible=false`, `production_eligible=false` and original eight-quarter
coverage credit zero. `historical_cutoff=2026-10-05` is retained separately from
the required timezone-aware research `observation_cutoff`.

## Existing Materials And Counts

Only existing archive `tests/fixtures/eps_duration/official-proof.zip`, SHA256
`8a2a7b0e11b6f661ad96bdd86b22a71f592beb2642fd3c574896816f1fae135a`, is used.
No new source request or endpoint, no copied archive upload in this PR.

Archive total: 75 receipts, 74 completed responses, one failed response,
73 distinct bodies, three failed transport attempts. Completion is distinct
from source binding: the known navigation redirect is retained but quarantined.
Two quarantined receipts: unapproved redirect and incomplete SEC acquisition.
18 download documents yield 112 EPS facts including comparative contexts;
receipt/document counts are not proven public filing-version counts.

Fact-evaluated cases: 2330/TWSE, 6488/TPEX. 1340 source/PDF evidence is retained
but not automatically extracted into facts. The remaining 1976 expected universe
members (including 1340 facts) are **NOT_EVALUATED**, not excluded from eligibility.
The scope remains 1085 + 893 = 1978. No full-market or original eight-quarter
coverage is asserted. Counts in every output distinguish replayed, displayed,
cutoff-excluded, quarantined and Historical-PIT-unproven facts.

## Knowledge-Time And Semantics

Only raw-verified, semantically qualified facts observed on/before the supplied
cutoff enter the numeric view. Unknown public time/filing/revision stays null.
Publication precision, evidence, Historical PIT and latest-version status stay
explicitly UNPROVEN unless original evidence proves them; this tool does not
generate any historical index/public-version attestation.

The existing replay supplies retained first-verified observation timestamps.
Export/replay generation time never replaces them. A later export is a new output
directory; it cannot overwrite a previous observation record. An earlier research
cutoff hides later facts without numerical values in its excluded-observation list.
An accounting period is not knowledge time. Current downloaded corrected bytes
cannot be backdated to first publication. DAY-only policy remains an unapproved
proposal; the historical selector is byte-identical to MAIN.

Basic/diluted, annual/quarter/YTD, scope and units are kept per fact. The tool
does not aggregate or compare values. Annual facts are never labelled Q4 quarters.
Receipts/raw failures enter quarantine with `verified_numeric_value=null` and
their exact reason. Entire archive hash tamper fails closed before export;
serialized fact tamper is rejected by rebuilding from the pinned bytes.

## Usage And Output

Use a **new** child directory of an external dedicated `rate-eps-b1-research`
root, not a directory inside any Git checkout. Example:

```text
python -B scripts/build_eps_b1_research_view.py \
  --observation-cutoff 2026-10-07T23:59:59+08:00 \
  --research-root /tmp/rate-eps-b1-research \
  --output-dir /tmp/rate-eps-b1-research/review-1
```

The three outputs are `RATE_EPS_B1_RESEARCH_VIEW.json`,
`RATE_EPS_B1_RESEARCH_VIEW.zh-TW.md` and `RATE_EPS_B1_RESEARCH_MANIFEST.json`.
The manifest binds source archive/inventory, program commit, core SHA256,
generation time, cutoff, output-byte hashes and separate validation dimensions.
`verify_export` checks hashes, exact raw-backed serialization and head binding.

Resolved containment is checked before writes. Git ancestry directories,
Production/data/artifacts/control/state/account/ledger namespaces, links/junctions
and existing output directories are rejected. Files use exclusive create mode.
The writer only writes the three fixed B1 filenames. There is no generic output
path override. This protects ordinary local filesystem use; hostile concurrent
filesystem replacement by another process is outside the single-user threat model.

Identical source/cutoff/implementation bytes produce identical core and core hash.
Envelope generation time is intentionally variable, not a claim that full file
bytes are invariant between generation times. Historical timestamps remain unchanged.

## 繁體中文預覽（完整資料由 CI artifact 提供）

用途：**NONDECISION_RESEARCH_ONLY**。非正式 EPS，不能作為排名／買賣／coverage。

| 案例 | 期間／duration | basis／scope／unit | raw／normalized | Raw integrity | Fact semantics | Historical PIT／latest |
|---|---|---|---|---|---|---|
| 2330／TWSE | 2026-04-01 至 2026-06-30／QUARTER | BASIC／CONSOLIDATED／TWD/shares | 27.25／27.25 | PASS | PASS | UNPROVEN／UNPROVEN |
| 6488／TPEX | 2026-04-01 至 2026-06-30／QUARTER | BASIC／CONSOLIDATED／TWD/shares | 7.90／7.90 | PASS | PASS | UNPROVEN／UNPROVEN |
| 1340 | 原始 PDF 證據保留 | 自動 fact extraction：NOT_EVALUATED | 未展示為驗證數值 | 依來源證據 | NOT_EVALUATED | UNPROVEN |

Full JSON/Chinese Markdown retain every fact's issuer, period, basis/duration,
unit/scale/decimals/precision, raw/normalized value, source/document/revision,
raw hash/receipt/context/page locator, first observation and public-time evidence.
The table is a preview, not a separate coverage artifact or source qualification.

## Non-Interference Acceptance

`scripts/eps_b1_formal_fixture.py` is an **engineering-only harness**. It executes
the existing Fundamental calculation, fixture replay, production bundle/snapshot
and `run_rate_0730(..., persist_state=False)` primitives. All EPS inputs are fixed
engineering fixtures, not authoritative source data. A mocked official adapter
exercises the existing missing-EPS failure path; production writes are trapped.
Only the harness can choose baseline/candidate code roots; no Production entry
or source override is added.

`scripts/verify_eps_b1_noninterference.py` binds exact head and current recorded
base, enforces add-only changes and no reverse imports, then extracts exact
baseline/candidate Git trees to fresh temporary sandboxes. It records baseline
fingerprint and per-field comparisons for B1 **ABSENT/PRESENT/UPDATED/CORRUPT**:

- Formal EPS input hash and Fundamental output hash.
- RATE/LONG/SHORT scores and Top50/Short30/Long30 ordering.
- Complete engineering decision payload, state hash and state ID.
- Existing missing-formal-EPS failure; no B1 fallback/coverage.

UPDATED is a different cutoff research view, not fabricated new source data;
CORRUPT intentionally corrupts that isolated view. The old output remains intact.
Tracked base bytes and all candidate tracked bytes remain unchanged through tests;
state-engine writes are test-only paths in the temporary sandbox, not the canonical
live slot/LATEST/accounts. Both protected-before/after hash maps are retained.

## CI And Review Evidence

New workflow `rate_eps_b1_research_ci.yml` is **pull_request only**, contents read,
exact head checkout, no continue-on-error, no source fetch or production dispatch.

1. Current-base integration job executes actionlint, add-only/frozen-byte/import
   checks, B1 tests, existing isolated EPS tests, Fundamental/logic/state/production
   integration/fundamental-history/acquisition regressions, comparisons and preview.
2. Separate historical job checks out **PR30 head
   4c0f95e71281cf2dfc1e04d8c2bb128c6c2f1ad6** and runs its original
   `verify_eps_duration_isolation.py` unchanged against its own original BASE.
   The PR29/PR30 historical acceptance records are not rewritten to this new base.

Download `RATE_EPS_B1_CURRENT_<head>` for JSON/Chinese Markdown/manifest,
non-interference matrix, formal fingerprints, logs and frozen hash maps.
Download `RATE_EPS_B1_HISTORICAL_PR30_<head>` for the separate historical result/log.
No source archive or raw document bytes are reuploaded.

Not executed: whole-repository suite, official fetch, full-market warmup,
scheduler, live-state publication, Run-5, plan resume or rebaseline.
**B1 readiness** is judged only on these bounded offline engineering gates.
**Original Historical PIT readiness remains BLOCKED**: direct Q4 BASIC,
exact historical public versions/index and all 1978 eight-quarter qualification
are still unproved. This delivery does not replace that specification or accept
the small case set as full-market evidence.
