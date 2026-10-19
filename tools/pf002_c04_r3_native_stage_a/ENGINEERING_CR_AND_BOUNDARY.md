# PF002-C04-R3 Authenticated Native Stage-A Integration

Authority: original work order SHA256
`ccd6fd3dfa277f5880df4e21a810d4bbce6b1dd14efe016f971d67a73b9a3c5d`.
Stacked accepted PR87 base: `1d32415ed1c3747b2ed7cba4ac19ccdeaaf78848`.
This namespace is additive. All748 base files remain byte-identical. Nothing here
modifies or activates the accepted R2 tool, original Host, Pagefile, GUI or Production.

## Exact scope and trust

Five ordered HTTPS GETs reuse the reviewed R2 transport algorithm with only R3
audience/ref/workflow/base namespaces and discarded unused R2 credential alias.
HTTP diagnostic reflection rules remain unchanged. A separate child-environment
projection excludes only the fixed public Audience introduced by the tool itself;
all actual API credentials, OIDC request credentials, JWTs and private query values
remain forbidden. This avoids rejecting the public R3 evidence-path namespace.
The automatic per-job GitHub token authorizes four fixed REST reads. The distinct
OIDC request credential requests a fresh JWT; original pinned RSA signature,
algorithm, exact immutable claims and time gates remain. Both new roles must
independently authenticate their own Run/Head/Attempt1. Old receipts are evidence,
not authorization. No PAT, long-lived secret, formal Permit or Owner Consent exists.

Preauth receipt reports the pre-Native boundary, with zero Native effects at that
point. The separate Native intent binds this work order and exact source. Final
result reports actual Job/child creation and attempted CreateProcess separately.
An authenticated receipt is never itself a Native execution permit.

One owned Job, one fixed CPython Normal Root, explicit inherited handles, no shell.
The new Job independently verifies the fresh R3 JWT before any kernel32 dispatch.
The Worker independently verifies that same JWT, scope and nonce via anonymous
proof pipe. REST/OIDC request credentials never enter Worker env, argv, pipe or
artifacts. Only the fresh signed JWT is delivered through the private proof pipe.
Child env is a fixed key set with a minimal interpreter/System32 PATH, owned temp,
no case-colliding aliases or known secret values. No full environment is exported.

Worker sends READY after proof validation and remains held on an independent
release pipe. Parent validates the retained known Root PID/handle, creation time,
membership, fixed CreateProcess executable and liveness around both canonical
observations. It then releases once, requires canonical COMPLETE receipt and exit0.
No parent PID, NtQueryInformationProcess, OpenProcess, unknown-image inspection,
global enumeration, descendants, CIM/Registry/Pagefile, elevation or StageB exists
in the executable namespace. Unexpected Job accounting/member IDs HALT without
opening or whitelisting them. Job limit4 is the unchanged resource cap, never an
authorized expansion beyond the single intentionally created Root.

## Canonical identity and Native boundary

canonical_file.py and file_evidence.py are byte-identical original C04 modules.
model.py retains only exact AST-equivalent Unknown/need/acct/ids; no parent or
StageB classification. FileBasicInfo0, FileStandardInfo1 and FileIdInfo18 retain
40/24/24 byte layouts, full128-bit FileID, volume, size, creation/change/write,
attributes/link count, five handle-bound phases,32MiB bound and rb same-path reopen.
No legacy fstat/path.stat ctime comparison is used. Two Root observations occur
while the Worker is held, before release; they do not attest loaded image memory.

Native calls are fixed reviewed kernel32 APIs and existing CPython process/pipe
primitives. GetLastError is required by CPython ctypes initialization and original
error capture. The same-process audit guard restricts DLL/symbol lookup and one
exact _winapi.CreateProcess; it is not a general sandbox against arbitrary Python,
a compromised runner or process-memory inspection. It denies network after preauth,
other processes/shell, registry and unapproved DLL/symbols. There is no Native bypass
flag or Synthetic Consent path. Offline test providers cannot satisfy the Job's
real signature check or produce official Native qualification evidence.

## Deadline, cleanup and completeness

The60s preauth self-exit timer must cancel and join before Native begins. Native
Job creation/configuration precedes any child; kill-on-close is configured first.
A separate20s timer then covers the unchanged10s Normal bound plus10s cleanup.
Its only action is controller self-exit124. OS closure of the already-configured
owned Job is a final safety mechanism, not observed containment proof. Abrupt exit,
missing cleanup, nonzero result, partial files or watchdog uncertainty is HALT and
forbids Reproduction. Python/OS/GIL scheduling has no hard real-time guarantee.
Ordinary finally cleanup uses only the reviewed owned Job, retained known handles,
bounded wait, one terminal accounting/PID-list read and explicit resource close.
Any termination/wait/accounting/unknown member/close error prevents PASS. No sleep
or extended deadline manufactures success. Cleanup is never RS02 or ownership PASS.
Every returned Root/thread handle is owned before evidence publishing. If ordinary
exceptions occur before successful Job assignment, the existing CPython wrapper
terminates only that known suspended Root handle, waits once, then closes its thread.
Wrapper success returns None; it is not interpreted as a failed BOOL. Unexpected
exceptions during cleanup evidence cannot skip resource closing. Explicit async
FD/thread ownership is retained, and unfinished IO or any failed close stays UNKNOWN.
The CreateProcess-to-Assign interval is not an atomic crash-safe transaction. Abrupt
controller death in that interval is unqualified and could leave a suspended Root;
no proof is delivered and no Root is resumed before verified assignment. This work
does not claim to close the original general containment/RS02 defect.

PASS requires official process/job exit0 AND complete mutually consistent
fresh preauth/source/intent, ready/release/complete, Root before/after, raw Native
returns/errors/buffers, canonical comparisons, cleanup/close, final result hash
and strict sequence/hash/context chain. Formatter booleans alone are insufficient.
Strict integer nonnegative nondecreasing monotonic observations permit ties;
ordering is the strict journal sequence/hash, not unique clock readings.

## Acceptance and residual blockers

All493 inherited cases plus new integration negatives must pass in Local Windows,
independent clean Windows, Hosted Windows and Linux before independent exact-head
Native safety release. Push runs offline only. Each Native role gets one fresh
Normal case; Qualification HALT/unknown forbids Reproduction. No retries, resume,
credential fallback, Native successor or automatic next stage. A repository admin
could separately request a future workflow; this package grants no such authority.

Sequential reads are not atomic. Disk identity/hash is not loaded-image attestation.
Raw JWT is deliberately not public, so independent evidence review is not raw-JWT
signature replay. Runner trust, key rotation, bounded secret scans and scheduling
limits remain. Native Stage-A success applies only to this Hosted experiment.
Unknown Member Origin=UNPROVEN; PF002-C01-OWNERSHIP-001 and PF002-CONTAINMENT-001
OPEN; RS02 and full Runtime BLOCKED; Owner Consent NOT ISSUED; Original Host NOT
AUTHORIZED; original GUI HALT UNKNOWN. No Merge/Deploy/Production/Auto-Next.

PF01 recovery authority preserves original R3 scope (original work order SHA256 ce0a02f97070d485805e2bb86642199b6de870812d26daf89135a659e8ab0e6d). New branch codex/pf002-c04-r3-pf01-byte-exact-stage-a-v1 isolates this recovery from the preserved failed Worktree. Fresh raw base Gate must pass748/748 before candidate restoration; source normalization is never an accepted comparison.
