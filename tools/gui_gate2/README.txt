RATE GUI Gate2 Target Identity Corrective — OFFLINE ENGINEERING ONLY

RATE-GUI-AUTH-TARGET-001 remains OPEN pending Control Center corrective review
and separately authorized real identity evidence. This component never declares
Gate2 final PASS. No native provider, live Permit loader, activation or deployment
entry point is implemented. live_entry() always rejects.

The contract separates three decisions:
1. An identity-only grant may authorize one bounded discovery on a fixed Host,
   Session, Desktop and observer Station scope with an exact executable path,
   SHA256, volume/file ID and Class predicate. It cannot read titles or diagnose.
2. Resolution must yield exactly one stable PID+Process Creation Time and
   HWND+TID+generation identity; any unknown, ambiguity, mismatch, loss, reuse,
   restart, disappearance or read race blocks. Title is not an identity selector.
3. A separate independent review ACK binds the resolution evidence SHA, exact
   target identity SHA and diagnostic Read Scope SHA. A separate diagnostic grant
   additionally pins that ACK SHA and the same target/evidence hashes. Diagnostics
   read only that exact target; EnumWindows is forbidden and there is no fallback.

identity_binding.py is a side-effect-free offline reference validator. Every model
is explicitly OFFLINE_SYNTHETIC_MODEL_NO_EXECUTION_AUTHORITY and restricted to
SYNTHETIC-HOST-ONLY. It does not accept or consume real Execution Permits. Synthetic
attempt state is for testing only. No original collector, OS enumeration, process
query, Pagefile, Production, Ledger, network or GUI control operation is performed.

TARGET_IDENTITY_BINDING_CONTRACT_V1.json defines the two-stage target model and
independent review boundary. AUTHORIZED_READ_BOUNDARY_CONTRACT_V1.json freezes
APIs, per-API fields, access masks, enumeration/read bounds, deadlines and evidence
destination constraints. TARGET_IDENTITY_BINDING_SCHEMA_V1.json describes offline
test models; semantic checks are mandatory in addition to structural validation.
The schema and documents are contracts, not instances of a formal Permit.

ReadGuard validates a role-bound scope and independent review evidence before
admitting calls, rejects arbitrary/unregistered discovery seeds, pins the exact
diagnostic identity before/after every read, detects authority mutation, enforces
deadline/count/field/API limits, and poisons failed synthetic attempts. A future
native adapter must honor call tickets and arguments and provide durable exclusive
intent, crash containment and physical output-root validation. None exists here.

Window generation is NOT inferred from equal before/after HWND/PID/TID and is not
claimed to be a Win32 creation timestamp. Tests use a synthetic lossless lifecycle
ledger. A future independently engineered witness must justify provenance and
complete coverage/event ordering/loss detection. If it cannot, the result stays
UNKNOWN. Sequential reads are not atomic; change-and-return and later changes can
never be universally excluded. Disk executable SHA is not loaded-memory integrity.

The accepted title V2 sources and142 tests are preserved byte-for-byte under
accepted_baseline/ for regression and pure title/token validation. Their native
backend is never constructed by the new component. They are not an approved live
entry point. The old broad V2 discovery cannot be substituted for the new contract.
The original exact title, Full/Admin/High, visibility, Session/Desktop and strict
title-reliability gates remain mandatory after identity binding.

Regression procedure (offline engineering only):
Copy this complete directory to a fresh disposable evidence directory; preserve
all generated fixtures, negative HALTED outputs and failure logs. Use the fixed
Python3.12 x64 interpreter with -I -B. Run run_synthetic.py for Gate2 models and
accepted_baseline/run_corrective_synthetic.py for the exact accepted142. All native
DLL binding is forbidden in these synthetic tests. Do not run either source from
the original accepted evidence directories. No tests are skipped or whitelisted.

Future identity-only authorization prerequisites:
- Independent Control Center approval of the exact Host/Session/Desktop scope,
  executable path/hash/file identity/Class predicate, APIs/fields/rights/bounds,
  fresh attempt/nonce, time window and absent physical evidence destination.
- Separately reviewed native transport, timeout/crash containment, persistent
  one-shot ledger and independent executable/window-generation witness provenance.
- Retained exact launch/interpreter and source/Schema pins, raw API errors and
  before/after identity/lifecycle evidence, with no retries or cleanup on unknown.
- Independent review of the resulting actual identity evidence; no promotion
  from historical PIDs or synthetic results to a diagnostic grant.
- A further exact-target diagnostic grant, separately issued only after review.

Original HALT Root Cause remains UNKNOWN. CORRECTIVE_ACCEPTED for title engineering
is unchanged. Pagefile changes, Set/Apply, reboot, UAC escalation, process control,
Production, Chunk3 and automatic next steps remain prohibited. No-Auto-Next holds.

Primary API references (contract context; not native qualification):
https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-getprocesstimes
https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-getwindowthreadprocessid
https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-getfileinformationbyhandleex
