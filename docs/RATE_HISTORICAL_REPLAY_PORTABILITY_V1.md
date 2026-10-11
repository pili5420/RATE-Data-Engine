# Historical Replay Portability V1

This opt-in offline execution environment separates immutable acquisition
producer identity, current main baseline, and readiness consumer identity.
It neither changes PR #56 nor authorizes First Refresh.
Git lazy-fetch is disabled; a missing local object cannot trigger acquisition.

The accepted external reader and every original function execute unchanged.
Per-module import and subprocess interfaces resolve historical logical paths
to hash-pinned source reconstructed with local `git archive` and verified
against commit-tree blob identities. Saved physical paths remain the original
logical identity so record() cannot silently rewrite historical provenance.
No current worktree source is used as an execution substitute.

Git queries from historical source run real Git in private, clean repositories
whose objects come from the existing local object database. Their detached
HEAD and replay-only origin/main identify that producer. These views are not
current main, are never new authority, and never change shared refs. Current
main and the clean readiness consumer are independently verified before replay.
The original exact_main() gate is neither removed nor patched.

The import interface also addresses explicitly pinned legacy engine imports.
Network, non-Git subprocesses, Git writes, fallback, and all writes except the
single fresh replay result are rejected during replay. This is a constrained
trusted-code replay environment, not a general hostile-Python security sandbox.

Full accepted output equality includes intent, raw, receipt, snapshot, recovery,
ledger, dispatch, target, and observation identity; counts alone are insufficient.
Execution/source logs are external. Real financial payloads never enter CI.
Public CI uses synthetic fixtures only. Historical PIT remains UNPROVEN;
original eight-quarter credit is zero, and intraday remains BLOCKED_EXTERNAL.
