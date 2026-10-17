RATE Gate 2 Native Identity-Only Candidate -- OFFLINE ENGINEERING ONLY

Stacked source dependency: accepted PR #72
2e4e24c3a4f73d6fabe3881f4962c919d0a21c69
Base branch: codex/gui-gate2-target-identity-v1

This package implements the Windows API request orchestration, bounded read
guard, raw Win32 ABI decoders, identity comparisons and synthetic lifecycle /
intent model. It deliberately contains no Windows DLL binding, native callback,
live provider, execution Permit loader, or live command-line entry point.
Only the exact data-driven ScriptedWindowsProvider is accepted. Substitution of
a real provider is rejected. Engineering test drivers accept synthetic fixtures
only; they are not runtime deployment entry points.

Read ENGINEERING_CR_V1.json, THREAT_MODEL_AND_ARCHITECTURE_V1.json,
API_READ_BOUNDARY_V1.json, LIFECYCLE_WITNESS_CONTRACT_V1.json and
FUTURE_PERMIT_AND_NATIVE_GUARD_DESIGN_V1.json for the candidate and future gates.
NATIVE_IDENTITY_SCHEMA_V1.json describes synthetic models, not live Permits.
ACCEPTANCE_MATRIX_V1.json is the planned matrix. Final execution results and
exact-head evidence belong in the separately hashed final evidence package.

The runtime code identity is the SHA256 of the canonical map of the nine files
listed in contracts.RUNTIME_FILES. Schema identity is its separate file SHA256.
The accepted identity_binding.py and pure Title Validator are independently
pinned dependencies. No accepted PR #72 file is changed by this work.

All API calls here are data receipts through the provider. Zero native DLL
calls are allowed during testing. Titles are outside identity-only read scope.
An offline RESOLVED result is not identity execution authorization, final Gate 2
PASS, a Diagnostic Grant, or Production qualification. Review ACK is separate
and cannot promote authority. No automatic next phase is implemented.

Synthetic journal writes are exclusive, fsynced, immutable attempt/nonce/result
records under new dedicated private test roots. Partial or unknown outcomes
remain non-resumable. No production ledger is opened. Path/reparse/hardlink and
root replacement tests are not proof of Windows ACL security, directory-handle
race resistance or power-loss durability; those remain future native blockers.
The first durable attempt header also reserves its nonce even before the
secondary nonce index exists. Strict scanning rejects reuse after that crash.
Fixed initial/final bounded enumeration and all-window identity fences include
excluded candidates; these are scheduled observations, never failure retries.
ACK validation binds one exact model/result pair, including scope and provider.

Sequential pre/post reads are not an atomic Windows GUI snapshot. Synthetic
complete lifecycle provenance is never attributed to WinEvent/ETW. HWND has no
reliable creation timestamp in this design. Missing native lifetime coverage,
pre-hook window creation provenance or ambiguous identity remains UNKNOWN.
The original HALT root cause remains UNKNOWN and its evidence is preserved.

Native binding ABI / SID pointer-buffer validation, real cancellation,
host/boot trust, operator-parent provenance, real durable journal/ACL design,
independent executable-image trust and an independently reviewed real identity-
only Permit are prerequisites to a separately authorized future qualification.
Even that phase cannot authorize GUI diagnostics or Pagefile/Production changes.

Engineering test command (fresh output directory only):
  python -I -B -S tools/gui_native_identity/run_offline_tests.py --output <new-output>
The tests create fresh SYNTHETIC workspaces directly under D:\Codex and three
owned synthetic crash-test child processes. No original collector is executed.
Historical 304 tests are reconstructed only from verified external quarantine
archives; legacy executable baseline bytes are not added to this package.
