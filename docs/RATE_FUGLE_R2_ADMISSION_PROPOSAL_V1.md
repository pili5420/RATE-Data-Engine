# RATE Fugle R2 Diagnostic and Production Admission Proposal V1

`R2-B05` has status `PROPOSAL_PENDING_CONTROL_CENTER_REVIEW`.

This proposal records the evidence and authority required for a future R2 diagnostic
and for subsequent Production admission. Its engineering baseline is main
`a37fea45423b75c4395d35a736ac33dd508b2db3`. Control Center must adjudicate the
contract decision below before a future R2 live release can rely on a different
readiness rule.

## Contract decision requiring Control Center

The current `RATE_INTRADAY_NEW_SINGLE_LIVE_QUALIFICATION_READINESS_V1.json` contract
requires all three inputs before a new single-live qualification can be ready.

1. Fugle provider written confirmation.
2. Exchange-authority evidence intake PASS.
3. Provider-authority qualification PASS, bound to the same exchange-intake digest.

`src/intraday_new_live_qualification_readiness.py` enforces these inputs. The current
Fugle license evidence records provider-plan permission for the described personal,
single-user, private automated non-display analysis. It separately records
`exchange_authority_confirmed_by_provider=false` and an unresolved TWSE/TPEx gate.

Consequently, releasing a new Diagnostic-only live request while exchange authority
is unresolved requires a Control Center contract decision. Calling a future result
Diagnostic-only does not satisfy the current new-single-live readiness requirement.
This proposal preserves that requirement. Offline corrective engineering and
synthetic review can proceed while that decision is pending.

Control Center must either require the existing readiness chain for R2 or explicitly
approve a separate, narrowly scoped diagnostic authorization contract through change
control. Any such decision must identify its scope and exact engineering version.
Production admission continues to require independently approved TWSE and TPEx
authority evidence under the existing provider-authority contract.

## Proposed distinction between evidence stages

| Dimension | R2 Diagnostic-only proposal | Production admission requirements |
| --- | --- | --- |
| Purpose | Inspect provider response semantics and collect bounded technical evidence after separate authorization | Admit an authorized, independently reviewed feed to the approved runtime path |
| Current deliverable | Offline package and synthetic evidence for review | Existing payload, authority, acceptance, permit and activation chain |
| Source identity | Exact accepted source SHA, exact workflow digest, permit ID and trigger ID supplied as independent bindings | Current-main source identity and independently supplied authority, live-review, acceptance and activation bindings |
| Universe | Exact approved 30-symbol map with TWSE 25 and TPEx 5, repository-rooted universe lineage | Same authoritative universe plus payload replay and digest binding before Phase2 consumption |
| Provider-plan permission | Existing written-confirmation evidence for the described usage scope | Valid permission covering actual automated Production usage and both markets |
| Exchange authority | Existing new-single-live readiness gate applies pending Control Center adjudication | Active, date-valid TWSE and TPEx evidence with required real-time non-display/internal-analysis scope and expected-binding hashes |
| Technical observations | Record actual symbol, exchange, trading date, timestamp source, price source, volume and turnover availability | Require every selected record to satisfy the authorized payload contract |
| Qualification result | Bounded diagnostic technical result, followed by independent review | Independently accepted provider and separate activation authorization and reviewed implementation |
| Consumption | Diagnostic evidence under protected private custody | Authorized Phase2 09:30/12:00 admission with feed and qualification digests, authoritative replay and admission age limit |
| State and credit | `production_eligible=false`, `registry_activation_allowed=false`, `external_dependency_resolved=false`, Production credit 0 and CER-081 credit 0 | Authority and acceptance gates determine later eligibility through separately reviewed changes |

## R2 execution-window proposal

The proposed R2 offline package binds the future acquisition window to Taiwan local
time, with an inclusive lower bound of `09:35:00` and exclusive upper bound of
`09:36:00`. The target trading date and `Asia/Taipei` timezone are explicit package
inputs. The proposed duration is one minute.

That restriction is an engineering proposal requiring Control Center approval. An
offline package PASS proves the declared bindings and proposed window are internally
consistent. It grants zero live requests. It cannot create, dispatch or retry a
workflow, consume or reissue a permit, read a key, or open a provider connection.
The package carries the permit ID and trigger ID as externally supplied assertions.
It cannot mint either authority.

The proposed collection window does not redefine the Production cadence contract,
whose authorized cadences remain `09:30` and `12:00`. Control Center must decide the
future diagnostic's cadence/window binding before any executable release.

If a later R2 live release is approved, its reviewed execution must retain the
existing single-use fence and independent review requirements, exact 30 approved
symbols, maximum 30 provider requests, zero automatic retries, zero redirects and
zero fallback. The previously consumed single-use permit cannot authorize R2.

## Payload semantics and disposition

The current Fugle diagnostic contract requires `symbol`, `exchange`, `date`,
`lastUpdated`, `lastPrice|lastTrade.price`, `total.tradeVolume` and
`total.tradeValue`. Its technical gate requires a matching date, non-future freshness
within 180 seconds, a positive finite price, and finite nonnegative volume and
turnover.

The authorized Production payload contract requires `symbol`, `market`, `timestamp`,
`price`, `volume` and `turnover`, an explicit timezone, matching trading date,
bounded freshness, exact approved symbol/market binding and no duplicates. Phase2
admission separately replays qualification against the same feed and repository
universe and rejects an admission older than 300 seconds.

These contracts require a provider-specific semantic mapping and complete evidence.
A diagnostic observation that a field is absent, malformed, stale, future-dated or
ambiguous must retain that condition and fail the applicable technical assertion.
Provider schema observations alone cannot establish Production admission. Any future
proposal for an alternate timestamp or price mapping must identify the exact raw
field, its meaning and units, the trading-date check and the freshness check for
independent review. Missing turnover, a prior close or a synthetic value cannot be
substituted to produce a passing payload.

An offline or synthetic PASS establishes engineering behavior only. The existing
independent live-review gate requires one bound run/job on attempt 1, rerun count 0,
job retry count 0, the consumed permit, exact 30 provider requests, the approved
universe and a private result digest. Provider acceptance and final activation each
require their own Control Center decision and trusted external bindings.

## Review and custody

R2 review material should expose source identities, hashes, field-presence and
semantic-check outcomes, counters and proposed dispositions. Credentials, raw market
data, derived analysis and market-data logs retain the existing private custody
requirements. Public review material must contain redacted structural evidence.

The next required actor for the Diagnostic-only live/readiness distinction is
Control Center. The next required actors for Production include the owners supplying
approved exchange-authority evidence and the independent reviewers of live evidence,
provider acceptance and activation implementation.

## Contract references

- `docs/contracts/RATE_FUGLE_FREE_INTRADAY_QUALIFICATION_V1.json`
- `docs/contracts/RATE_FUGLE_BASIC_PERSONAL_INTERNAL_USE_LICENSE_EVIDENCE_V1.json`
- `docs/contracts/RATE_INTRADAY_NEW_SINGLE_LIVE_QUALIFICATION_READINESS_V1.json`
- `docs/contracts/RATE_INTRADAY_EXCHANGE_AUTHORITY_EVIDENCE_INTAKE_V1.json`
- `docs/contracts/RATE_INTRADAY_PROVIDER_AUTHORITY_V1.json`
- `docs/contracts/RATE_AUTHORIZED_TAIWAN_INTRADAY_PAYLOAD_V1.json`
- `docs/contracts/RATE_PHASE2_INTRADAY_ADMISSION_INTEGRATION_V1.json`
- `docs/contracts/RATE_FUGLE_SINGLE_LIVE_QUALIFICATION_AUTHORIZATION_V1.json`
- `docs/contracts/RATE_INTRADAY_PROVIDER_ACCEPTANCE_V1.json`
- `docs/contracts/RATE_INTRADAY_ACTIVATION_PERMIT_V1.json`
