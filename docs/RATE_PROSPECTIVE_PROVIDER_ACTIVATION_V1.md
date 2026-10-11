# Prospective Fundamental Provider Activation V1

CR: RATE-PHASE-I-A2-PROSPECTIVE-FUNDAMENTAL-PROVIDER-ACTIVATION.
Scope: provider authorization and immutable acquisition evidence only.
Base: main ccca06701a5dbf2c769db80a67220d7089363dd4, the PR #53 merge commit.
PR #53 is merged; this activation PR remains unmerged. Existing acceptance
contract/artifacts remain unchanged.

## Authority

FinMind / TaiwanStockFinancialStatements BASIC EPS and MOPS Official monthly
revenue are configured AUTHORIZED_PROSPECTIVE_ONLY. This setting is **not effective
on a PR branch**: a verified main authorization commit and immutable authority seal
are mandatory before any acquisition. The committed activation_timestamp is null.

The activation commit is the first main commit introducing this authorization
contract. Its effective time is the trusted GitHub PR `merged_at`, not a Git author
date, a locally chosen time, or an acquisition timestamp. Main ancestry, repository,
base branch, contract Git blob, HTTPS/status/receipt and independently trusted
proof/receipt hashes are checked. Control Center supplies the proof pins; computing
a new hash from untrusted metadata does not establish authority. Fetch main before
sealing. Later main advancement may prove ancestry but cannot move the original time.
No authority is sealed during engineering acceptance.

`scripts/run_prospective_provider_activation.py --operation seal` accepts a pinned
external binding: execution Base/Head; proof_path/proof_sha256;
proof_receipt_path/proof_receipt_sha256; main_sha. `--output` is a fresh external
authority directory. The proof is the exact GitHub PR API response; receipt records
endpoint/final_url/http_status/raw_sha256/bytes/attempts/fallback_used/requested_at/
received_at. Proof acquisition must be independently authorized and authenticated.
ACTIVATION.json is a single immutable slot; changed seals are rejected.

## Acquisition

`--operation create` requires a pinned binding containing execution, authority_root,
authority_sha256, universe_path/universe_sha256/universe_commit. It creates only an
external evidence namespace. `--operation acquire` requires execution, evidence_root,
config_sha256, externally trusted ledger head, provider and target. FinMind additionally
requires transport_path/transport_sha256 for the already delivered capture tool.
`--binding` and `--binding-sha256` are required; no import/relabel mode exists.

The pipeline verifies authority and existing heads before transport; writes an
immutable request intent; uses the existing dispatch gate (13 seconds, conservative
new-session wait); then calls the existing capture exactly once. FinMind credentials
are read locally, never serialized. MOPS reuses the existing official adapter,
strict no-redirect opener and receipt writer. Its request_started_at is captured
immediately before opener dispatch, not inferred from retrieval. The legacy formal
source files and all old receipts are byte-identical.

Every accepted record binds activation, requested/received/source_observed times,
raw/receipt SHA256, parser and pipeline identity, validation/first_seen timestamps,
raw row locators and an immutable content identity. Time order is:

activation <= intent.requested_at <= receipt.requested_at <= received
== source_observed_at <= validated <= first_seen_at <= now.

No old receipt can be relabeled. Validation failures retain exact capture material,
intent, traceback and a persistent stop. Unknown outcomes prohibit automatic retry.
No fallback, alternate provider, zero fill, imputation or older-period substitution.
OS single-writer protection and immutable put_bytes are reused, not reimplemented.

Raw, receipts, events and local observation chains are append-only. New observations
link previous scope identity without claiming official revision/publication history.
Independent replay checks every source and immutable snapshot against trusted heads.
Issuer readiness uses the latest **whole acquisition scope**, retaining all 1978
issuers and valid partial periods; completeness never controls provider authorization.

`--operation replay --replay-root ROOT --config-sha256 PIN --trusted-head HEAD
--as-of TIME --output NEW_FILE` is a cold read only; no source requests.

## Boundaries

Historical PIT remains UNPROVEN; original eight-quarter coverage credit is zero.
First-seen is prospective system availability, never original publication time.
Provider evidence credit is not ranking eligibility, first refresh authorization,
or Production publication. production_eligible=false; decision_eligible=false;
fallback_allowed=false; intraday external dependency=BLOCKED_EXTERNAL.
No scheduler, scoring, state, Portfolio or Ledger entry points import this pipeline.
Financial definitions and fixed required windows are inherited unchanged from #53.

Synthetic CI proves the lifecycle with a synthetic authority only. It does not
authorize real providers or demonstrate post-activation market acquisition.
All inherited tests and protected Git blobs are verified at the exact PR Head.
The PR #53 stack dependency is removed. Rebased exact-head gates must pass before
this activation PR's final merge review; pre-rebase runs are engineering history only.
Control Center must separately review the real main authority seal, then authorize
bounded prospective acquisition. First refresh still requires its own gate.
