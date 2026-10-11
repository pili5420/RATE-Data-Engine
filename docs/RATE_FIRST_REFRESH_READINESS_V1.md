# Phase J-R First Refresh Readiness Re-evaluation

Exact J-R Final base: `2e65ef3c0a5e08ba9a5b87ad248f79fca3882eed`.
Historical Producer remains `66d52f73be78c6116420ac556668c7c158ca768d`;
the Consumer Head is independently pinned after rebase, not equated to either.

This is an opt-in, no-network reader and a transaction **design**, not a refresh,
provider activation, warmup policy activation, publisher or ranking consumer.
Existing main consumers and contracts are unchanged. Only newly created external
readiness output may be written. No workflow schedule or financial endpoint exists
in this change. Synthetic CI and real local replay are reported separately.

## Evidence and Readiness

The CLI checks exact execution base/head, clean checkout, trusted binding hash,
the effective main authority, the original A4 store, the recovered A5 prefix and
its terminal HTTP failure/resolution, and the accepted, hash-pinned continuation
reader. Producer checkouts and physical parser identities stay pinned to their
original versions. The external continuation reader is code, so it is explicitly
hash-pinned, never discovered from an untrusted manifest or automatically executed
from an arbitrary directory. Financial networking is denied before replay.

The universe is independently rebuilt from the original catalogue/plan bytes,
commit and hash, then compared in full, not by counts. The existing issuer reader
selects the entire newest observation scope; missing rows are not silently restored
from older observations. Old coverage is classified separately as legacy, with zero
prospective credit. Legacy numbers cannot fill prospective missing periods.
The core has no candidate-provider import. Only the opt-in CLI supplies the existing
issuer readiness reader explicitly; normal production owners gain no dependency.

An issuer is READY only with eight finite EPS quarters and three finite monthly
revenue YoY values in the frozen contract windows. UNDEFINED_ZERO_BASE remains null.
All valid partial inputs, locators, source hashes and individual observation times
are retained. All 1978 issuers survive. Missing periods are normal NOT_READY results,
not zero values or parser failures. Input readiness grants no ranking eligibility.

Provider READY means verified authorization, real bounded acquisitions and multiple
observations with preserved recovery semantics. It does not mean all issuers have
complete current prospective inputs. A readiness-review verdict does not authorize
execution, acquisition, publication or activation; those need a new Control Center
decision. Historical PIT remains UNPROVEN and original eight-quarter credit is zero.

## Atomic Publication Qualification

PR #57 is now merged into the re-evaluation base. The production publisher uses
immutable content-addressed staging, an OS writer lock, compare-and-swap against the
previous authoritative Latest identity, and one authoritative atomic replacement of
`RATE_PRODUCTION_SOURCE_BUNDLE_LATEST.json`. The Thin Work Latest is a
non-authoritative compatibility view; a post-commit compatibility write failure is a
warning and cannot turn a committed transaction into a partial commit.

Phase J-R does not execute that publisher against real Production data. It verifies
the merged owner contract and relies on the inherited atomic-publication regression
suite, including pre-commit failures, stale CAS, concurrent writers, tamper, crash
boundaries and cold reconstruction. A successful re-evaluation may only produce
`READY_FOR_FIRST_REFRESH_EXECUTION_REVIEW`; execution/publication still requires a
separate Control Center authorization.

The historical CER078 incident remains
`UNRESOLVED_HISTORICAL_NONREPRODUCIBLE` with `root_cause=UNRESOLVED`. The merged
forward diagnostics preserve recurrence telemetry and do not rewrite the original
1043/1044 failure as PASS.

## Isolation

The CLI installs a Python audit guard before loading any evidence. It denies
network calls and writes outside its new external output, including Production
Latest, source snapshots, Decision State, portfolios, ledger, rankings and scheduler.
Existing production code has no dependency on this reader. The exact-head verifier
requires every existing tracked blob to be unchanged. Real source trees are hashed
before/after execution; independent CLI processes must reconstruct identical core
content and verify source bytes again. Generated/validation times are separate.

Public artifacts contain only synthetic fixtures. Real financial values, raw,
receipts and local bindings are never committed or uploaded.

## Merged Historical Replay Portability

The continuation is mandatory-replayed through the merged
`RATE_HISTORICAL_REPLAY_PORTABILITY_V1` worker in a fresh interpreter. Its immutable
binding pins Producer, current main, Consumer Head, accepted reader and full accepted
output, configuration and recovery evidence. Historical source bytes are rebuilt
from Git objects in private Git views. Shared refs never move, and the original
reader including `exact_main()` executes unchanged. No financial Decimal reader or
historical provenance assertion is patched. The parent independently compares the
full replay object with its trusted accepted output, not counts alone.

The audit guard permits only that exact worker argv/executable/cwd, not arbitrary
Python children. Worker traces and reconstructed source trees stay in the new
external output. Network remains forbidden in both processes. A worker failure is
preserved and blocks readiness, never falls back to the old shared-environment path.
The exact-head suite retains all 55 original readiness and 29 portability tests,
plus 10 integration tests: 1138 tests total. Replacement coverage remains 1030 with
the original continuity/report-soak/Phase2/CER081-blocked proof.
