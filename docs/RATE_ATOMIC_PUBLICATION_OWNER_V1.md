# Atomic Publication Owner V1

Independent Phase J-A repair, based on `66d52f73be78c6116420ac556668c7c158ca768d`.
This does not authorize First Refresh, provider acquisition, publication execution,
ranking activation, or a merge of PR #56.

## Transaction

Existing source/freshness/Phase2/authorized-feed validation remains in its owner.
Every normalized bundle, snapshot and validated Thin Work manifest is written
exclusively at a path containing its exact byte SHA256. Files are flushed/fsynced
and cold-read before commit. The complete refresh manifest is also preserved as
an immutable object. Staging failures may leave evidence, never a new Latest.

The sole authoritative pointer retains the existing source Latest filename.
Its exact previous bytes hash (or absence) is captured before assembly, then
compared under an OS writer lock immediately before one atomic replacement.
`--expected-previous-latest SHA256` pins a caller's prior identity; `NONE` requires
absence. Omitting it captures the current identity before staging, not at commit.
Conflicting writers fail closed. A lockfile's existence alone is not a live lock.
No automatic retry, unlock-by-deletion or CAS override exists.

An OS crash before replacement leaves the old transaction. A crash after
replacement leaves a complete, independently cold-readable new transaction.
Windows uses fsynced files and same-volume atomic replacement; no claim is made
about Windows directory power-loss durability or adversarial out-of-band writers.
All publication writers must use this owner and its lock.

## Consumer Migration Boundary

`read_committed()` and `scripts/read_production_refresh.py` read exactly one
authoritative pointer and verify every immutable reference before exposing the
bundle and Thin Work manifest together. Consumers must use this operation, not
join two independently read Latest views. Legacy source-pointer fields remain.

Thin Work Latest is a derived, explicitly nonauthoritative compatibility view.
It carries `derived_from_latest_identity`; failure/staleness of this view is a
post-commit warning, never a partial commit. Legacy readers joining that view
are not qualified for transaction-consistent First Refresh until migrated.
No scheduler, state, portfolio, ranking or intraday PARTIAL_VALID owner is changed.
The public-official report publication branch remains independent and unchanged.

## Evidence Scope

CI and native acceptance use synthetic temporary roots, real OS locks, real
file replacements and cold child processes. No real Production pointer is
published. Existing regression assertions, restored historical artifacts and
pins are not modified. Historical PIT remains UNPROVEN; fallback remains false.
