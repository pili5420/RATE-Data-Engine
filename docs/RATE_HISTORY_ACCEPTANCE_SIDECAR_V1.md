# History Acceptance Ledger Sidecar

CR `RATE-MH-ACCEPTANCE-LEDGER-SIDECAR-001`: engineering only. This does not authorize
bootstrap, acquisition, later chunk preparation, Ranking or Production publication.
The frozen campaign Producer main and original manifest remain
`fbdfbfcf0a003cd6de49911bc0a784275a32031c`. The independently deployed sidecar Head
is recorded separately; it never replaces the original Producer binding.

## Trust And Genesis

There is deliberately no acceptance, Genesis or activation issuer in production
code. Control Center must deliver canonical, independently SHA256-pinned records.
`RATE_HISTORY_CHUNK_CONTROL_CENTER_ACCEPTANCE_V1` binds every field listed in the
JSON contract, including the exact RESULT and consumption **file** digests,
original authorization identity, ledger head, scope, universe, roots and main.
Its content identity uses `acceptance_id` / `acceptance_sha256`; the external pin
is the full canonical **file SHA256**, not that semantic digest.

The separately pinned `RATE_HISTORY_ACCEPTANCE_GENESIS_V1` binds Chunk #1's exact
acceptance file SHA. Prior progress is zero: Chunk #1 itself is replayed and
credited as the first event. A live PASS, chat summary or self-derived digest is
not a substitute for a missing independent acceptance record or Genesis anchor.
Records in the ledger cannot serve as their own external trust source.

The next Control Center decision must additionally issue a pinned
`RATE_HISTORY_ACCEPTANCE_SIDECAR_ACTIVATION_V1` permitting the exact sidecar Head,
committed owner hashes, roots, manifest, Genesis and maximum chunk ordinal.
No such real permit, acceptance record or Genesis is created by this PR.
Missing authority fails before ledger creation.

## Independent Source Replay

`verify-chunks` is read-only and does not require a real ledger. Context validation
rebuilds the already-approved manifest with existing owners, not a replacement
manifest. Every original Plan, Seal, Authorization, RESULT and consumption is
bound to its original execution namespace. The existing `_cold_replay_success`
adapter starts `sys.executable -I -B scripts/replay_history_chunk_success.py`.
That accepted child installs `offline_network_guard` before owner import and
uses the existing history replay validator. Fresh PID, committed source hashes,
exit zero, PASS, original RESULT digest and ledger head are mandatory.
Raw, receipt, intent, event and checkpoint validation stays with that owner.
The sidecar checks original file-set/hash invariance before and after replay.

## Commit Protocol

Only `D:\RATE-MH-Governance\R1-20261015-01` is allowed for a real ledger, disjoint
from `D:\R1-20261015-01` and repository/state roots. Path aliases are rejected.
No real directory is created during this engineering review. Synthetic tests use
explicitly marked, isolated temporary contexts and Control Center fixtures.

The existing OS writer lock is used only on the separate ledger root, never on
the campaign or acquisition roots. Its exact `.scan.lock` is runtime coordination,
not evidence. All evidence is exclusive-create with file fsync, POSIX parent
directory fsync, and readback. Windows directory fsync/power-loss durability is
not claimed; incomplete files are detected and halt rather than repaired.

Append: intent -> first Genesis -> record -> chained event -> checkpoint.
The checkpoint is the final immutable commit point. Events link the prior event
SHA and external Genesis/record pins. Progress is recomputed from contiguous,
independently authenticated events; checkpoint counts are checked against that
derivation. There is no mutable Latest/progress pointer. A caller supplies the
externally retained expected head, required to detect stale views and tail
truncation. Store that returned head in controlled review evidence, not solely
inside this ledger.

Repeating the same acceptance with the current expected head is a no-op. A
different record for an already accepted chunk halts, even if both look valid.
The conflicting externally authenticated pin is preserved in exclusive-created
`HALTED.json`; all future replay/append attempts remain blocked for review.
Malformed files, orphan records, missing checkpoints, broken chains or a stale
head halt. Never delete intents, rebuild a truncated tail or retry a failed append
automatically. Control Center must review incomplete append evidence separately.

## Deferred Bootstrap Plan

1. Review and accept this exact engineering Head and CI. Do not merge into frozen
   campaign main or modify any old source pin.
2. Obtain independently pinned Chunk #1 and #2 acceptance records and a Genesis
   anchor with original RESULT/ledger/authorization bindings. Missing proof blocks.
3. Separately authorize deployment/Genesis bootstrap at the designated sidecar
   root. Bind the exact deployed Head/owner hashes and limit to Chunk #2.
4. Verify root isolation, both original chunks via fresh processes, all original
   evidence hashes and frozen main. Append Chunk #1 then Chunk #2 under the lock.
5. Independently replay the sidecar using external record/Genesis pins and expected
   final head; derive 2/109 chunks and 200/10760 requests from events, not constants.
6. Control Center accepts bootstrap/progress. Only then may a separate authorized
   task prepare Chunk #3. This PR creates no Chunk #3 material or authorization.

All public CI uses synthetic fixtures. Local real-evidence verification is separate.
Historical PIT, calendar180, Intraday, TPEx units, Ranking and Production boundaries
remain unchanged. No collector, parser, normalizer, scheduler or publisher is changed.
