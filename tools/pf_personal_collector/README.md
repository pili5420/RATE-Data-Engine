# PF-PERSONAL-002 — Hosted Runner read-only engineering

Stacked on accepted PR80 `9cec01c262e9d0881432d08c2844924893612cee`. No accepted file is changed. The PR80 historical `native_transport` status remains unchanged: this new directory implements a separately authorized **hosted-runner-only engineering overlay**, not original-host runtime authority.

`runner_controller.py` has no arguments. It requires a fresh signed GitHub OIDC proof, exact push workflow/ref/head, immutable repository IDs, official public run/source metadata, unchanged accepted base and exact local source bytes **before** native dispatch. `native_worker.ps1` independently verifies the proof from an inherited anonymous pipe; it accepts no queries, targets or consent arguments. A signed bearer is not physical machine attestation. A hostile actor with a stolen bearer or ability to modify source is outside the qualified trust boundary; RS-05 stays BLOCKED.

The worker executes the immutable 12-entry PR80 read order. Local CIM uses fixed Namespace/Class/Property/Filter and five-second OperationTimeoutSec; Registry64 is opened read-only. No additional provider discovery, remote sessions, elevation or writes to settings occur. Returned key metadata is discarded; unexpected non-key data is rejected. Raw evidence contains only approved fields. D: absence stays SOURCE_ABSENT/INDETERMINATE. TPM absence can be UNAVAILABLE. Unexpected provider failure HALTs without retry, scope relaxation or fallback.

The parent creates a suspended own process, assigns a kill-on-close Job and resumes only after successful assignment. The proof and sanitized environment are passed through a bounded pipe and an explicit handle inheritance list. Tests use only newly created own child processes. Killing this Job **does not prove cancellation of out-of-Job WMI provider work**. Native hard cancellation, hostile filesystem races/DACL/durability and parent-death qualification remain BLOCKED as specified in RUNTIME_SAFETY_MATRIX_V1.json.

Full raw/source-error evidence remains private on each ephemeral Runner. Artifact files are fixed reviewed summaries, hashes, statuses and approved numeric projections. Independent raw rehash after VM teardown is unavailable; the receipt records that limitation. A second clean Runner independently executes the same fixed reads. Windows/Linux offline tests are separate from real API qualification; repeated runs are not new test coverage.

No original host query, Owner Consent, formal permit, GUI operation, Pagefile change, Production operation, Merge, Deploy, or automatic next stage is authorized. Global automatic=True, Initial/Maximum=0/0, Registry values or missing instances cannot prove D: policy or boot application. Sequential before/after observations are not atomic and cannot exclude ABA. Original HALT root cause remains UNKNOWN; GUI Gate 2 and source gaps remain BLOCKED.

## Threat model and source references

Threats: unsigned/environment-only invocation; changed branch or source; synthetic consent replay; query/remote/filter injection; extra properties/oversized rows; type aliases and corrupt JSON; missing providers; identity races; child hangs/descendants; private data leakage; output traversal/reparse/replay; qualification promotion. Mitigations and residual boundaries are tested separately; source hashes are not an OS sandbox.

Official API semantics: https://learn.microsoft.com/en-us/powershell/module/cimcmdlets/get-ciminstance ; https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects ; https://learn.microsoft.com/en-us/dotnet/api/microsoft.win32.registrykey.opensubkey ; https://docs.github.com/en/actions/reference/security/oidc ; https://token.actions.githubusercontent.com/.well-known/openid-configuration . OIDC id-token:write mints provenance only, while repository token permissions remain contents:read. Pinned JWKS is public key material; unknown key fails without refresh.

## Entries

`run_offline_tests.py --output <fresh approved directory>` runs pure tests under a no-native/no-network audit hook. `runner_controller.py` is workflow-only and refuses the original developer host. `native_worker.ps1` requires signed runner proof before its first Windows source call. `fault_worker.py`/`fault_leaf.py` are fixed own-process tests without CIM/Registry. No scheduled entry, owner runtime loader or fallback exists.
