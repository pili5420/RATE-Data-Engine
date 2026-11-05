# RATE V11 Fugle R2 Offline Corrective Engineering

Authority is `AUTHORIZE_RATE_V11_FUGLE_R2_B01_B05_OFFLINE_CORRECTIVE_AND_PACKAGING_ONLY`.
Reviewed baseline and integration base are
`a37fea45423b75c4395d35a736ac33dd508b2db3`.

## B01 consumption ownership

The GitHub create-only marker is the atomic arbitration point. The only admitted
executor receives an exact successful HTTP 201 create ACK in its own invocation
and verifies the exact marker readback. A timeout, lost ACK, conflict, unexpected
response or unknown readback terminates the attempt. A marker created before a
lost ACK stays consumed. No executor may use same-main readback as ownership proof.
The synthetic store and orchestration follow the same rule under a lock.

The executor accepts an optional credential loader, invoked after ownership is
verified. Existing callers supplying an already-held key retain their API. Future
R2 credential acquisition must use the deferred loader after all admission gates.
The offline suite injects synthetic values and denies socket access through RATE's
existing network audit guard.

## B02 R2 package preparation

`validate_r2_package` accepts an R2-only package and the exact source-file bytes.
Independent review supplies the expected package SHA256, source commit SHA,
workflow SHA256, Permit ID, Trigger ID and retired Trigger IDs. The exact source
inventory must match, each file digest must match and the workflow digest must
match the identified workflow file. Any altered pin or reused trigger is rejected.

The package artifact is `RATE_FUGLE_R2_OFFLINE_PACKAGE_V1`, with
`scope=OFFLINE_CORRECTIVE_ONLY`. `trigger_created`, `workflow_dispatch_allowed` and
`live_execution_allowed` must all be false. R2 identifiers used in tests are
explicitly synthetic. Packaging cannot issue a Control Center permit or create a
trigger. Final source and workflow pins belong in the external review evidence so
the source commit does not need to embed its own hash.

The workflow in this change is exclusively pull-request synthetic CI. Its identity
is recorded for engineering evidence. A future operational workflow has to receive
its own approved source/workflow pins and fresh Permit/Trigger IDs. No old trigger
is carried into an operational package.

## B03 time preflight proposal

`validate_r2_time` requires the independent package pin, trading-calendar pin and
clock-attestation pin. The calendar must cover TWSE and TPEx and include the exact
package trading date. A trusted clock authority must attest verified synchronization,
the same source/permit/trigger and a UTC sample at most five seconds old. Negative
age, unknown authority, malformed timestamps and missing bindings fail closed.

The proposed collection window is `09:35:00 <= Asia/Taipei < 09:36:00`. Clock
uncertainty is at most 1000 milliseconds and its full uncertainty interval must fit
inside the window. These duration and uncertainty limits are conservative engineering
proposals pending Control Center adjudication. The existing provider cadence remains
`09:30` or `12:00`. A calendar or clock attestation must come from the independent
trusted authority, with its digest supplied outside the package. Caller assertions
alone are insufficient. Live clock acquisition is outside this offline change.

Existing provider regressions retain the 180-second freshness, exact trading date,
approved 25 TWSE plus 5 TPEx universe, exact 30 requests and no redirect/retry rules.

## B04 private evidence protocol

`build_r2_evidence_manifest` accepts exact sanitized JSON artifact bytes, the complete
expected inventory, execution binding and an independently pinned private-custody
attestation. The binding includes source SHA, workflow SHA256, Permit ID, Trigger ID,
Run ID, Job ID and attempt 1. Each artifact has an exact-byte SHA256 and byte length.
Only references, hashes and counts enter the review manifest.

The custody attestation requires a Control Center decision, private visibility,
verified access controls, no public upload and no credential persistence. This
offline module cannot provision a store or inspect a real store's ACL. The actual
custodian must supply that independently approved attestation before real evidence
can be admitted. The payload checks reject known credential/raw-response fields,
and do not replace the custodian's responsibility for sanitizing private artifacts.

Verification requires an independently obtained manifest SHA256 and rebuilds the
full manifest using independently expected execution bindings and inventory. A
rehashed replacement, wrong run/job, second attempt, tampered bytes or absent file
fails closed. `PARTIAL` and `UNKNOWN` keep the expected inventory and missing-file
list but never become review-eligible. An unknown execution is not rerun or credited.
No private evidence is uploaded by the engineering workflow.

## B05 pending contract proposal

`RATE_FUGLE_R2_ADMISSION_PROPOSAL_V1.md` describes the Diagnostic-only and Production
admission difference for Control Center. Existing Exchange Authority contracts and
Production owners are retained. An exemption or an operational 09:35 release requires
a separate decision. Pending adjudication blocks dependent execution.

## Verification and handoff

The fixed `scripts/verify_fugle_r2_offline.py` suite covers all corrective modules,
existing diagnostic security tests, authorization, exchange authority and provider
authority regressions. It requires an exact clean checkout and treats failures,
errors and skips as blocking. Its output contains synthetic engineering counters.
The workflow logs and final evidence package bind the actual CI Run/Job/Attempt.

Engineering review can evaluate this offline implementation and proposal. Future
live execution additionally requires approved operational package pins, a fresh
Control Center Permit/Trigger decision, trusted trading-day/clock evidence and
private custody approval. No-Auto-Next remains true. Production and CER-081 credits
are zero.
