# PF-PERSONAL-002-C01

Authority is containment corrective engineering only, stacked on PR81 exact
90b27e3dd5f328883e1c9c809173df6ec61c9373. The accepted 652 files are unchanged.
This isolated candidate does not integrate into or activate the original collector.

## Forensics and limits

Run 39111918936 failed with DESCENDANTS_LEFT_AFTER_ROOT_EXIT. Its aggregate-only
selftest omitted the failing Case/PID/count. Both earlier source subprocesses in
that run had active_after=0 while their original process handles were retained.
A retained handle does not deterministically imply nonzero Job accounting.
The historical failing Case, PID and exact root cause cannot be reconstructed
from those artifacts. Process accounting race is a hypothesis, not a finding.

Microsoft documents ActiveProcesses as associated-process accounting, decremented
after exit and release of references. A signaled retained process handle can prove
termination while accounting cleanup is still being observed. Job handles are not
general all-process-exit wait signals. Job-only PID queries are bounded to four.

Sources:
- https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_basic_accounting_information
- https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_basic_process_id_list
- https://learn.microsoft.com/en-us/windows/win32/procthread/process-handles-and-identifiers
- https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects
- https://devblogs.microsoft.com/oldnewthing/20130405-00/?p=4743

## Candidate and same-case experiment

One unique Job per case, kill-on-close, active limit four, no breakaway. Only fixed
Python normal / crash(exit 7) / hang / descendant_hang workers can launch. The last
case retains a handle to the receipt's PID only after IsProcessInJob confirms it
belongs to this newly owned Job. No system-wide process enumeration exists.

Create suspended, assign before resume, capture initial membership, close thread
handle, send signed provenance via anonymous pipe. Preserve original wait -> root
exit code -> ActiveProcesses ordering before any extra evidence writes. Capture
known original handles and expected exits, two retained observations, then close
only those confirmed signaled handles. Poll accounting and Job-only membership
within original bounds; require zero/empty twice. Unknown results never pass.

Normal/crash retain the original ten-second completion budget. Hang uses two
seconds and descendant hang three; cancellation/drain has the original ten-second
absolute budget, including termination call and journal I/O. Startup/proof delivery
bounds remain ten seconds, descendant receipt five. No deadline extension.

Actual nonzero first accounting in normal/crash plus signaled known handles and
final zero/empty is same-case RED/GREEN for the instantaneous accounting gate.
Timeout paths already polled accounting in the frozen implementation; their
instantaneous counts cannot serve as equivalent original RED proof. Elapsed time is not
isolated from handle release: no claim that release alone caused the change.
No observed native RED means BLOCKED_RED_NOT_REPRODUCED; no repeated experiment
to manufacture a RED. Fake-provider tests prove logic only, never native behavior.

## Evidence and containment boundaries

Per-case CreateNew canonical hash-chained records bind head/run/role, unique named
Job and handle, root PID/TID/handle, optional descendant PID/handle, exit and wait
states, before/retained/after accounting, bounded observations and terminal result.
The final resource-close event is included in the full chain; it is not termination
proof. Failed case journals survive independently of aggregate qualification.
The verifier checks all records, exact event protocol, summary bindings and raw
RED/GREEN consistency. Failure cleanup can terminate only the same owned Job;
this is containment cleanup, not rerunning the fault case. Cleanup failure remains
UNKNOWN. No PID re-open occurs after completion proof or release.

## Threat model / residual blockers

Source injection, stale bytecode, unsigned provenance, old audience/workflow,
re-run attempt, altered base, unknown members, contradictory exits, timeout,
unconfirmed cancellation and evidence overwrite fail closed. Source-byte manifests
and official exact-head Git blobs bind the new closure; pinned GitHub OIDC keys
have no refresh fallback. Workflow uses least permissions; id-token:write is only
runner provenance, never owner consent. Fixed public evidence excludes tokens,
environment dumps, original-host data and private worker streams.

Local same-user malicious kernel/API replacement, ACL/durability, parent death,
provider work outside the Job, full PF002 Runtime, source qualification and target
trust remain unqualified. Sequential API reads are not atomic snapshots. Original
GUI HALT root cause remains UNKNOWN. Owner Consent is NOT ISSUED. No retry,
resume, fallback, original-host query, twelve-source read, automatic next stage,
Pagefile operation, Production, merge or deployment is authorized.

## Acceptance

Preserve all inherited 108 Python and five pure descriptor tests; run new protocol,
authorization and evidence negatives on Windows/Linux with zero skips/waivers.
Separate sealed 170 (includes 69) and 111 reference regressions are not additive.
Two fresh Windows roles run only four own-process cases. Every case must prove
expected termination, original bounds and final zero/empty; actual RED/GREEN and
independent review are required to recommend containment corrective acceptance.
If native root-cause/correction proof is missing, return BLOCKED with evidence.
