# Controlled Batch Automation Scoped Engineering

CR `RATE-MH-CONTROLLED-BATCH-AUTOMATION-001` is approved for engineering only.
The declared human-authorized CR SHA256 is recorded, not misrepresented as an
independently downloaded original document hash. Design package pin:
`1ffb7ae926a4d6ce88461f7d7dc839c71eefac36f7a107f5da54217429f97358`.

This is a dependent additive PR based on Sidecar Head
`e3ef25084f17f9073b25555b8c0cf911e1146ec8`, not a change to PR #70 or frozen main
`fbdfbfcf0a003cd6de49911bc0a784275a32031c`. Every inherited blob is protected.

## Implemented Boundaries

- The independent issuer runs in a contained fresh process. Only public keys,
  canonical authorization/acceptance copies and detached envelopes cross IPC.
  Test private keys are generated in that worker's memory, never serialized.
- A separate ephemeral synthetic Control Center key signs the policy. The
  external registry FILE/content pin, key epoch, purpose and revocation checks
  precede release validation. The issuer cannot approve its own policy.
- `cryptography==50.0.2` provides Ed25519. Its transitive and test dependencies
  are version/hash locked for Python 3.12 on Windows amd64 and Linux x86_64.
  The RFC 8032 public verification vector contains no private seed.
- Existing exact-format authorization and acceptance JSON are unchanged.
  Signatures, policy identity, purpose, nonce, sequence and predecessor head
  are authenticated in detached envelopes, not added to those core objects.
- Issuance is globally reserved in the externally registered issuer journal
  before release. A different policy cannot silently choose another journal.
  Existing journal contents prohibit restarting/reissuing over a previous run.
- Journal intents, events and checkpoints are exclusive-create, hash chained,
  OS locked and checkpoint-last. External heads detect truncation. Incomplete
  records remain errors, not automatic repair/retry opportunities.
- The original `execute_chunk()` owns the only consumption/claim and request
  loop. Its existing prior-success cold replay, dispatch, STOP and no-next
  semantics are retained. The orchestrator records the original claim evidence;
  it does not create a competing claim before invoking that owner.
- Independent issuer acceptance validates the original execution root using
  the existing Sidecar/source replay owners. A caller-provided PASS is not used.
- Sidecar append uses the original activation/Genesis/record checks and external
  expected head. A fresh network-denied process cold-replays its result. Only
  the independent issuer's signed external head ACK can release the next chunk.
- Windows Job Object containment is configured before the child's boot line.
  Native child PID/direct-parent checks reject Windows venv redirectors that
  insert unbound intermediary processes. POSIX uses a separate process group
  and parent-pipe EOF monitor. No process is automatically restarted.

## Not Activated

Every mutating entry requires an isolated `SYNTHETIC-batch-*` sandbox and
`SYNTHETIC_ONLY` contexts/policies. Formal campaign and governance paths fail
lexically before opening them. Existing owner validation additionally rejects
synthetic artifacts as real acquisitions. `real_launch()` always rejects.

No real Control Center key, Chunk #3-109 material, official HTTP request,
acceptance-ledger write, provider activation, Ranking or Production operation
is performed by this engineering delivery. Public CI is synthetic only.
No service, scheduler, production workflow or cloud resource is deployed.
No-Auto-Next remains effective for the real campaign.

## Verification

`scripts/verify_history_controlled_batch.py` protects all 616 parent blobs,
runs all 1,868 inherited tests (including PR #70) and the new exact inventory,
checks every one of the 61 approved requirements against passing test IDs,
and produces isolated 3-/10-chunk full-owner acceptance proofs. A separate
unchanged applicability verifier runs current-main replacement/continuity.
No skips, assertion relaxation or failure whitelist is permitted.

The 3-/10-chunk cases use original owners with fake transport, an accepted
synthetic bootstrap and independent key workers. They are not just state-model
tests. Real request latency and source availability are not estimated from
fake-clock spacing. Wall time and retained evidence size are measured locally.

Source and trust references:
- [PyCA Ed25519 API](https://cryptography.io/en/50.0.2/hazmat/primitives/asymmetric/ed25519/)
- [Maintained distribution and release](https://pypi.org/project/cryptography/50.0.2/)
- [RFC 8032 test vectors](https://www.rfc-editor.org/rfc/rfc8032#section-7.1)

## Deployment Candidate And Remaining Gates

The verifier emits a non-deploying candidate with separate producer, Sidecar
and new-engineering Heads, exact owner hashes and immutable contract/lock pins.
It cannot be consumed as a real activation permit.

Production issuer account ACLs, protected key storage, independent external
witness storage and revocation/time authorities must be separately qualified.
Process-memory separation in synthetic tests is not a claim of protection from
host-admin/debugger compromise. No real credential or key provider is implemented.

The current implementation intentionally rejects resuming or reopening an
existing issuance run. Cross-window archival/reconciliation and campaign-wide
delegation need their own approved integration gate; a second fresh directory
must not be used to evade global issuance uniqueness. Windows directory fsync
and cross-system exactly-once success are not claimed. Any uncertain claim,
append or witness acknowledgement halts and preserves evidence.

Before a real pilot: accept independent engineering/security review; complete
the separate Sidecar Bootstrap Acceptance; approve finite No-Auto-Next and
automated acceptance delegation; qualify independent issuer/witness deployment;
issue exact-head permits and a finite policy separately. None is authorized here.

## PR #71 Security Correction

The immutable defect baseline is `90c82ecf0882639f22c1b6c836631bd5bf1cd214`.
The three witness metadata attacks were accepted at that head. The cancelled
CI run `38782850567` remains cancelled and provides no final acceptance.

The runner now verifies the control-signed policy, including an empty witness
genesis (sequence zero, null head), and maintains separate issuer and witness
counters. Each packet must extend the independently verified prior state.
`RESERVE` adds an issuer event only; the counters intentionally diverge.

A new `WITNESS_EVENT` Ed25519 envelope authenticates the entire canonical
witness event, including sequence, predecessor, payload and next-head digest.
The original witness acknowledgement separately authenticates the issuer head
and issuer sequence. Exact schemas and native types apply throughout packets,
events, acknowledgement, signed envelope and release artifacts; canonical
byte comparisons replace permissive object comparisons. RPC framing rejects
noncanonical bytes, duplicate keys and incomplete messages. Distinct pinned
control, issuer and witness public identities and purposes are required.

Security regression tests rehash the original three mutations without forging
signatures, exercise replay, schema, type and head attacks, and inject each
original attack at authorization, acceptance, acknowledgement and the next
authorization. Every injection must halt without subsequent execution, claim,
transport, acceptance append or release. Synthetic evidence is retained by CI.
