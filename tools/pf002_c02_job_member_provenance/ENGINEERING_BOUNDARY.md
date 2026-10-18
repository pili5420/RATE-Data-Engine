# PF002-C02: owned Job member provenance, not containment qualification

Base PR82 exact 5eb345159adc74b1be90a62965a99a6d112ccc57. All 669 original
files remain unchanged. New sources and one new workflow only. Original C01
unknown PIDs 5716 and 5340 are historical, never reopened on any machine.
Historical artifacts prove their reported membership numbers, not their identity.

## Experiment and stopping

Two fresh Windows-2022 roles maximum; one normal launch per role. No rerun,
workflow_dispatch, crash/hang/descendant mode, CIM/Registry, original host,
Owner Consent, Pagefile, Production, deployment or next stage. A signed GitHub
runner proof binds exact branch/head/workflow/audience/run/attempt1 and pinned
public keys. It is provenance only and cannot authorize an original host.

The copied reviewed Job creator retains suspended-create / assign-before-resume,
kill-on-close, active limit four, no breakaway, original 10-second normal and
10-second cleanup bounds, sanitized environment and explicit inherited handles.
These are checks between synchronous APIs and final acceptance bounds. Kernel
API and disk I/O cannot be hard-preempted here; the six-minute workflow timeout
is an outer platform bound, not a proven per-call cancellation mechanism.
Only fixed normal_worker.py can launch. Its private anonymous pipe carries a
unique launch nonce and signed proof. The CPython 3.12.10-only worker writes one
canonical self PID / self parent PID / executable / source receipt then exits0.
It creates no children. CPython's own getppid uses current-process PSS_CAPTURE_NONE;
no global process snapshot or enumeration is used. A private .part file is renamed
once without replacement so a reader sees a complete immutable receipt.

Pre-wait and post-root-wait are two fixed observation phases, not failure retries.
Only PIDs returned by this newly created Job's bounded complete PID query may be
opened. Four concurrent / three additional handles maximum, each PID opened once,
0x101000 = SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION, inheritance false.
IsProcessInJob must confirm this same Job before other identity reads. Reuse or
failed membership closes only that read handle and HALTs. No parent PID is opened.
No process ID is individually terminated. Failure cleanup uses only the reviewed
new owned Job mechanism; its zero/empty observation is never containment PASS.

Each same retained handle records GetProcessId, GetProcessTimes, zero-time Wait,
GetExitCodeProcess, QueryFullProcessImageNameW (fixed 32768 UTF16 units, no resize),
and fixed NtQueryInformationProcess class0. NTSTATUS must be zero and returned
length must match PBI. Class0 parent/PID fields are documented by Microsoft but
the API may change; absent/API error/insufficient access means UNKNOWN without
fallback or higher rights. Only PID/parent raw slices leave PBI; PEB and unrequested
metadata are not exported. Query path and creation are confirmed before/after;
this is not an atomic snapshot. UTF16 errors/truncation/conflicts HALT.

Image hashes first require GetDriveTypeW on only that image's exact volume anchor
to return DRIVE_FIXED=3 (no drive enumeration), before resolve/stat/open. They read
only that confirmed member's physical local executable path,
at most32MiB, checking open-file device/file ID, size, write/birth times before
and after plus current path identity. UNC/reparse/race/deadline failures HALT.
This is a disk snapshot, not a loaded-image attestation. No process memory reads,
Token privileges, Debug privilege, Toolhelp, WMI, ETW or completion port are used.

Raw accounting/PID query bytes, input buffer sizes, return lengths, API statuses,
error codes and ctypes offsets are preserved. Independent little-endian decoders
must agree with native fields. ACCT size48 / Active offset40; ID header8 and
pointer-sized array; PBI x86 size24 PID16/parent20, x64 size48 PID32/parent40.
These establish decoding in the NEW experiment only, never retroactive C01 ABI.

## Decision boundary

A diagnostic identity is not an accepted member. Root-cause PROVEN requires the
post-root-exit unknown-PID pattern plus stable same-handle identities, explicit
parent PID linkage within the original retained root's recorded creation/exit
interval and a matching controlled worker receipt. Unlinked identities, a parent
outside the known root, disappeared processes or absent reproduction remain
UNPROVEN. A filename, hash, signature, cleanup or exit alone cannot satisfy this.
No image/name whitelist exists. A proven specific launch-topology mechanism is
not proof of the exact historical PID identity, lossless lineage, original GUI
HALT root cause, RS-02 PASS or permission to expand the approved process domain.
The decision explicitly separates FRESH_EXPERIMENT_KNOWN_SET_MISMATCH_ONLY from
historical_C01_root_cause=UNPROVEN and from the unobserved Job assignment event.
Any domain expansion or real correction requires separate change authorization.

Independent source and negative-test review must PASS before the single fresh
native run is pushed. All original offline assertions remain intact; no skip,
failure whitelist, fallback, assertion relaxation or synthetic native PASS.

## Primary references

- https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_basic_process_id_list
- https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_basic_accounting_information
- https://learn.microsoft.com/en-us/windows/win32/api/jobapi/nf-jobapi-isprocessinjob
- https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-queryfullprocessimagenamew
- https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-getprocesstimes
- https://learn.microsoft.com/en-us/windows/win32/api/winternl/nf-winternl-ntqueryinformationprocess
- https://learn.microsoft.com/en-us/windows/win32/api/processsnapshot/ns-processsnapshot-pss_process_information
- https://raw.githubusercontent.com/python/cpython/v3.12.10/Modules/posixmodule.c (win32_getppid)
