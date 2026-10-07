# EPS Duration-Tagged Fact Layer

Authority: CR-RATE-EPS-DURATION-KNOWLEDGE-TIME-V1. Base MAIN:
`40c00f300d6ba64ca06850ba172fd1df222d1c86`. PR #29 remains OPEN at
`7d8d4ebd22f6b28218786546c3ce7a3f65d6cd4a`; its changes are not imported.
This is a separate diagnostic-only model, parser, validator and offline replay.
Nothing imports it from Production. No source registry, acquisition, ranking,
bootstrap, scheduler, consumer or state implementation is modified.

## Evidence Inventory And Replay

`tests/fixtures/eps_duration/official-proof.zip` retains all original receipt bytes,
body bytes, notebook and previous extracted evidence. Receipt absolute paths are
not rewritten; the reader resolves the corresponding archived body by SHA256.
Archive SHA256: `8a2a7b0e11b6f661ad96bdd86b22a71f592beb2642fd3c574896816f1fae135a`.
Every inventory entry includes its original path, byte length and SHA256.

Prior proof: 71 receipts, 71 completed responses, 2 failed attempts before success,
70 distinct bodies. 22 Inline XBRL download/preview responses group into 18 observed
issuer/quarter/consolidated-document groups, NOT 22 independent filings or versions.
The two market 2026Q3 correction queries returned the same body hash
`399ad6848ad791b743285bfa9d9bd6be0e789f52801b3ac146daef239adb9041`;
both acquisitions remain present. Publication-version filing IDs remain unknown.
One navigation receipt (`mops-spa`) has a trailing-slash redirect: its exact bytes
remain in the inventory, but the strict source-binding validator rejects it.
Neither the parser nor audit treats it as an accepted filing.

New proof: 4 receipts; 3 complete bodies and one retained SEC HTTP 403 failure.
No partial/403 body is represented as a successful receipt. New evidence is
`NEW_DIAGNOSTIC_FETCH`, not Run-4 or the previous round's exact material.
The existing twenty summary responses are reused as diagnostic qualification only;
they are not fetched again or upgraded to quarterly coverage.

18 download documents replay into 112 raw EPS facts, including comparative contexts,
basic/diluted and quarter/YTD/annual durations. The four preview bodies remain
byte-verified inventory; they are NOT extra filing credit. PDF/correction bodies and
the prior notebook are integrity-replayed; this narrow parser does not automatically
extract PDF accounting facts. Previous derived book summaries contain encoding
replacement characters; authoritative calendar evidence is re-extracted from the
original Big5 HTML using its declared encoding, without changing old summaries.

## Semantics And Knowledge Time

`Fact` is immutable. Missing filing/revision/public-time/precision identities stay
null or UNPROVEN. The issuer-period group is separate from official filing identity.
Document identity is the retained content hash, not an asserted publication version.
`decimals` (accuracy), `precision`, scale and raw value are distinct. Decimal arithmetic
normalizes only the observed `numdotdecimal` transformation, including explicit sign
and scale. It never differences two EPS facts.

The parser requires an explicit official book-index calendar witness; absent one,
duration remains UNPROVEN. It recognizes only observed IFRS concept and identity
namespace versions, exact issuer/market, the returned filing period, each absolute
context, undimensioned consolidated scope and TWD/shares. Annual facts cannot pass
a QUARTER expectation; diluted cannot pass BASIC; unknown semantics fail closed.

Raw integrity, fact semantics, historical version selection and index completeness
are separate gates. The composite `evaluate()` boundary first re-parses the exact
body and rejects changed serialized values, scope, duration or observed time before
calling the semantic and knowledge-time primitives. The latter primitives assume
their input raw gate has already been verified, not an arbitrary PASS string.
`production_eligible=false` and original coverage credit=0 are
non-init fields, including when an engineering PIT fixture passes. There is no alias
to `single_quarter_eps`, no fallback, no official eight-quarter completion claim.

The `Index`/`Version` input boundary requires qualified public-version and completeness
attestations, receipt hashes, explicit page coverage, version lineage and cutoff range.
This parser does NOT generate such attestations from a current successful fetch.
Only labelled engineering fixtures currently provide PASS attestations to exercise
selection mechanics. Production access to that boundary is absent. Future official
index adapters would need separate qualification and authorization.

SECOND-precision public time with a proven offset is required by this conservative
candidate selector. DAY-only/naive times remain evidence, not invented seconds.
Historical cutoff remains 2026-10-05 (date-only policy is not redefined by tests).
The tests' explicit timestamp cutoffs are engineering scenarios. Current observed
time allows only OBSERVED_FORWARD_ONLY after observation; it never dates publication.
Anchor comes from the complete filing index before fact parsing; no missing quarter
can be replaced by an older quarter within the bounded ten-quarter window.

## Source-Gap Matrix

| Case | Raw integrity | Fact semantics | Historical PIT / index |
|---|---|---|---|
| 2330 / 6488, Q1-Q3 observed contexts | PASS | Direct basic quarters and YTD tagged separately | UNPROVEN; current index is not complete historical version proof |
| Both issuers, 2024Q4 / 2025Q4 | PASS | ANNUAL basic/diluted, no direct Q4 basic context in the inspected filings | UNPROVEN; rejected for original QUARTER requirement |
| 2330 official 2025Q4 release | PASS | Q4 DILUTED NT$19.50, consolidated TIFRS | Public date DAY-only; exact cutoff version/index UNPROVEN |
| SEC accession 0001046179-26-000008 | Raw acquisition HTTP 403 | Official web index links 6-K / EX99.1; metadata only | UNPROVEN; no downloaded SEC bytes/replay or complete correction index |
| 6488 official IR 2025 category | PASS | No qualified new Q4 representation in the captured category page | UNPROVEN; no inferred absence of filings elsewhere |
| 1340 corrected PDF / 2025 annual and restated 2024 | PASS | PDF page 43 distinguishes annual BASIC and restatement; no automated PDF fact extraction | Original bytes and complete exact-public-version lineage missing |

The official [TSMC release](https://pr.tsmc.com/english/news/3281) links the retained
two-page PDF. Its first page identifies TWSE:2330 and Q4 ended 2025-12-31, diluted
NT$19.50 (distinct from US$3.14 per ADR); calendar witness gives 2025-10-01 start.
Page 2 says Q4 figures were not board-approved. Audit/unaudited status is UNPROVEN,
not inferred from that note. Release date is 2026-01-15, without an exact timezone
or a certificate that today's downloaded hash was publicly available then.
HTML SHA256: `61f993efb7ee26917cd471ef247b283e8b6fb0bdf9699531805f22dc6f5cbf1f`.
PDF SHA256: `186ef1cf053f720520b133c02531c7c5966e9335d1a9a5455091838dcb0e798a`.

The official [SEC index](https://www.sec.gov/Archives/edgar/data/1046179/000104617926000008/0001046179-26-000008-index.htm)
was inspectable as web-rendered metadata: filing date 2026-01-15, accepted clock
2026-01-15 06:58:24, report period 2025-12-31, 19 documents. Sequence 1 is
`tsm-20260115x6k.htm`; sequence 2 `a4q25e_withguidancexfinal.htm` is EX99.1.
That attachment link is distinct from a cryptographic byte-equivalence assertion
between the SEC representation and issuer PDF. Accepted-clock offset remains
UNPROVEN in the captured evidence. Filing date, acceptance, dissemination/publication,
document signature and current retrieval are not interchangeable. No restriction
bypass, mirror, re-attempt after 403 or all-Taiwan generalization was used.

## 1340 Version-Cutoff Case

The official correction row reports 2026-07-24, not an exact public time.
Detail SHA256: `078afeae918ed72f32655a396f50b960ed721e46a78ededdf0598674ec732732`.
Attachment SHA256: `ae9f74e0377a716ed8445fb40c554bef0407ee7c3f080e0ab71390d692ecc999`.
PDF page 43 reports 2025 annual total basic loss (2.61) and 2024 restated (5.28),
separate from continuing/discontinued-operation components; it does not provide a
qualifying Q4 single-quarter basic fact. Before 2026-07-24: corrected bytes cannot
stand in for unavailable original bytes; BLOCKED. After that date, including the
original 2026-10-05 cutoff: selected version, exact public hash and complete correction
index still require independent evidence; UNPROVEN, not automatically PASS/latest.
Post-revision selection can pass a synthetic complete index with the original version
record and selected revised bytes; original bytes are needed for earlier-cutoff facts,
not universally for every later query. Actual source evidence does not meet either gate.

## Remaining Decisions (Proposals Only)

Original eight-quarter readiness remains BLOCKED: direct Q4 BASIC representation,
complete cutoff-qualified filing index, exact public original/revision bytes, precise
publication time, and coverage for all 1085+893=1978 issuers remain unproved.
No production anchor or coverage is claimed for this small case study.

Minimal alternative proposal: authorize a separately named duration-tagged reported
EPS indicator with explicit BASIC/DILUTED and QUARTER/YTD/ANNUAL features, never alias
the old indicator. Knowledge-time mode must explicitly distinguish historical PIT
from observed-forward-only. A change to ranking consumption, Q4 derivation, source
authority, selection policy or rebaseline would require a new Control Center approval,
full-universe qualification and separate migration acceptance. This PR implements
none of those production changes, derivations or rebaselines.

## Reproduction

Install `lxml==6.1.1` and `PyYAML==6.0.3`. Run:

```text
python -B -m unittest tests.test_eps_duration_facts -v
python -B scripts/replay_eps_duration_proof.py --output <new external diagnostic JSON>
python -B scripts/verify_eps_duration_isolation.py
actionlint -shellcheck= -pyflakes= .github/workflows/rate_eps_duration_fact_layer_ci.yml
```

CI checks the exact PR head, real archived hashes, negative gates, existing Production
regressions, all base-tracked Git blobs unchanged and working bytes unchanged through
tests. Test-only state fixtures are not Production state. No network source fetch,
warmup dispatch, persist/publish/live-state call or coverage counter is added.
