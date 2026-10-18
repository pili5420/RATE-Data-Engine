# PF002-C04-R2 GitHub Preauth Transport Corrective

Stacked base: PR86 `dec8192fa908ca0c24db568b6984b2ab5a4ed8df`.
This is a new PREAUTH-only namespace. No comparator, Job Object, worker, Process
inspection, Windows Native API, CIM/Registry/Pagefile or original-host code is imported.
Success ends at a diagnostic receipt; there is no successor Native dispatch.

## Historical finding

The preserved R1 artifact has OIDC_TOKEN=200, RUN_RECORD=403 and a PREAUTH_HALT.
Its GitHub metadata GET had no GitHub API Authorization. Its artifact lacks response
rate-limit/permission headers and body. The actual historical reason remains UNPROVEN.
New authenticated success cannot retroactively prove that reason.

## Authentication and source contract

Exactly five GET stages: OIDC_TOKEN, RUN_RECORD, PR86_BASE_REF, CURRENT_TREE,
PR86_TREE. No new endpoints, alternate credentials, redirects, retries or fallbacks.
The job has only contents:read, actions:read and id-token:write. A per-job automatic
GITHUB_TOKEN is injected only into the Python step as PF002_R2_API_TOKEN, removed
from the process environment immediately, used only for four fixed api.github.com
reads, and never used as OIDC proof. The OIDC request credential goes only to the
fixed GitHub Actions OIDC endpoint. The JWT is verified using the original pinned
GitHub RSA keys, signature algorithm, time bounds, exact immutable repository IDs,
subject, ref, workflow, run, attempt, head and workflow SHA. No key refresh fallback.
Only the R2 audience/ref/workflow namespace changes. No formal Permit is issued.

The previous 735-file Git tree is fixed from the accepted Git object. Its remote
tree must match exactly; the current tree may only add this closed source directory
and the one R2 workflow. All base and new working files must match remote Git blob,
mode and length. Manifest includes exact SHA256/length for every new tool file.

## Secret and read boundary

Credentials never occur in argv, receipts, raw events, artifacts, exceptions, logs
or a Native child environment. There is no child creation path; an audit guard
also rejects process/ctypes/registry dispatch. HTTP errors export only enums, status
and bounded validated request-id/rate-limit/retry-after headers, never response body,
Authorization, JWT or exception text. Malformed diagnostics fail closed. A proven
primary rate-limit header does not authorize an in-attempt sleep/retry. Python cannot
promise cryptographic erasure of immutable strings in process memory; process memory
inspection and compromised runner are outside this bounded engineering proof.

Output is a fresh exclusive intent and physical root under D:\a\_temp, exact run,
attempt1 and role. Intent and armed deadline policy are inside the uploaded public
evidence. After durable arming, an independent 60-second timer may only self-exit
this PREAUTH Python process with code124, without filesystem or network operations
in its callback. Python/OS/GIL scheduling is not a hard real-time guarantee. Socket
timeouts or post-read clock checks alone do not establish an absolute read bound.
The workflow timeout is an additional outer fail-stop, never a success criterion.
Complete receipt, FinalHead, valid chain AND official process/job exit0 must agree;
exit124, missing files, partial/contradictory evidence are UNKNOWN/HALT even if an
earlier PASS event exists. All normal files are durable before cancelling the timer.
Every receipt records NoRetry/NoResume/NoFallback/NoAutoNext. Crash/write failure
retains partial files; no automatic repair or cleanup occurs.
The authorized controller initially receives the short-lived API credential through
its step environment, removes it before transport use, and creates no child. This
does not claim that a credential never passed through any process environment.
Known API/OIDC/JWT/query secrets, encoded equivalents and long reflected fragments
are rejected before diagnostic export. Arbitrary obfuscation is not a universal
data-loss-prevention claim; the narrow syntax, fixed TLS sources, no body export,
signed source binding and explicit known-secret guard operate together.
Sequential file reads are not atomic snapshots; disk identity is not loaded-image
attestation. This qualification does not make any Native or ownership gate PASS.

## Threat model and acceptance

Reject missing/malformed/wrong-channel credentials, injected URLs/redirects/proxies,
wrong run/repository/head/workflow/attempt, malformed JSON/headers, duplicated or
out-of-order stages, byte/deadline overruns, source/mode changes, OIDC signature or
claim changes. Preserve every old 415 test ID and every original failure artifact.
An independent clean exact-head review and full Windows/Linux offline regression
must pass before any fresh Hosted PREAUTH-only role. Each role is dispatched at most
once; any first-role HALT forbids the second role. No historical reruns.

## Primary official sources

- https://docs.github.com/en/actions/tutorials/authenticate-with-github_token
- https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#permissions
- https://docs.github.com/en/rest/actions/workflow-runs#get-a-workflow-run
- https://docs.github.com/en/rest/git/trees#get-a-tree
- https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api
- https://docs.github.com/en/actions/concepts/security/openid-connect

Native Comparator=NOT QUALIFIED; Unknown Member Origin=UNPROVEN;
PF002-CONTAINMENT-001=OPEN; RS-02 and Complete PF002 Runtime=BLOCKED;
Owner Consent=NOT ISSUED; Original Host Execution=NOT AUTHORIZED;
Original GUI HALT Root Cause=UNKNOWN. No Merge/Deploy/Activation/Auto-Next.
