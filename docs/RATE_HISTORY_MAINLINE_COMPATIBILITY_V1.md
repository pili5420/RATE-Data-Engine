# RATE M-H Latest-Main Compatibility Revalidation V1

Status: `LATEST_MAIN_COMPATIBILITY_ENGINEERING_ONLY`

This package reconnects the already accepted PR #70 Sidecar and PR #71 controlled-batch engineering to the RATE V11 mainline after the State Chain scheduler correction. It does not rewrite historical acceptance and does not activate the real campaign.

## Immutable identities
- Current integration base: `5df302a720ac8114d3610342dad3783cc0a3debd`
- Frozen campaign Producer main: `fbdfbfcf0a003cd6de49911bc0a784275a32031c`
- Accepted Sidecar Head: `e3ef25084f17f9073b25555b8c0cf911e1146ec8`
- Accepted controlled-batch Head: `959ab92f67ce6e1f57eadb262984e305ab96ad55`

The campaign Producer identity remains frozen. Current main is only the compatibility integration base and never substitutes for original acquisition, RESULT, authorization or acceptance bindings.

## Exact scope
Twenty-one accepted non-workflow files are reused byte-for-byte. Only these three files are new compatibility material:
- `scripts/verify_history_mainline_compatibility.py`
- `.github/workflows/rate_history_mainline_compatibility_ci.yml`
- `docs/RATE_HISTORY_MAINLINE_COMPATIBILITY_V1.md`

The historical exact-base verifier scripts remain byte-identical accepted artifacts; they are retained for replay and are not the latest-main CI entry point.

The compatibility verifier protects every existing current-main blob, verifies the frozen Producer -> Sidecar -> controlled-batch ancestry, and verifies all accepted blob pins. Accepted Sidecar/controlled-batch core tests must PASS on the integration head. For existing current-main State Chain, Report Soak, Phase2 and prospective-activation tests, the verifier runs both the exact current-main base and the integration head in fresh isolated checkouts and requires identical per-test outcomes. Existing base failures are preserved as failures and are never relabelled PASS; compatibility means the additive M-H files introduced no new outcome change.

## Non-activation boundary
No Chunk #3 material or authorization is created. No official market-data request, real key, real authorization, formal acceptance-ledger write, ranking execution, Production publication, Decision State mutation or CER-081 credit occurs. `No-Auto-Next` remains effective.

After compatibility acceptance, separate gates remain for real Issuer/Witness deployment qualification, Production Bridge qualification, finite pilot/resume authorization, remaining M-H chunks, TPEx/history/PIT closure, ranking activation, the external authorized intraday feed, four-cadence integration, CER-081 scheduled soak, and final Production acceptance.

FE01 / E2 / A1 / G02-SIGN remain paused.
