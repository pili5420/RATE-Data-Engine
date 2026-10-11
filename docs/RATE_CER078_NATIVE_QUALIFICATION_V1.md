# CER078 Native Baseline Qualification

Independent Phase J-B change request, not a Production defect repair.
PR #56 and its engineering evidence remain unchanged.

Original failing identity:
`tests.test_cer079_full_day_chain.CER079FullDayChainTests.test_full_day_acceptance_artifacts_pass`.
`build_cer079_artifacts -> replay_full_day -> build_cer078_artifacts` raised
`RuntimeError: CER078_TERMINAL_GATE_FAIL` at the final terminal gate. The original
131-test native group recorded 130 passes and one error; the complete 1044-test
run recorded 1043 passes. Original Windows/Linux cloud exact-head results passed.

The original result did not record the individual terminal-gate vector or full
native dependency/locale/environment envelope. Current environment measurements
cannot retroactively establish these original values. Therefore a green rerun
alone cannot establish a root cause. Under Phase J-G's explicit disposition,
classification remains UNRESOLVED_HISTORICAL_NONREPRODUCIBLE and root_cause remains
UNRESOLVED. If the reproduction matrix and forward diagnostics pass, disposition
may be HISTORICAL_NONREPRODUCIBLE_DISPOSITION_ACCEPTED. This is not historical
PASS or PRODUCT_DEFECT_RESOLVED. New recurrence evidence is required to reopen
causal investigation. No skip, assertion relaxation, whitelist or rebaseline is used.

The observer records original owner exceptions and failure-gate returns without
replacing any SUT function or assertion. The new verifier runs original regression
groups in separate processes from an exact-head archive. It records Python,
dependencies, locale, timezone, explicit nonsecret environment keys and test order.
Environment differences are observations, not asserted causes. No Production,
strategy, ranking, fixture, historical pin or acceptance owner is changed.

All public reports are synthetic engineering evidence. Private original failure
and reproduction matrices remain external. No real provider request is permitted.
The diagnostic workflow never promotes root cause when tests pass.

At the actual terminal raise, the read-only observer captures the 16 original
terminal booleans with named subgates, nested gate values, previous/current state,
source snapshot and bundle identities, content and on-disk artifact hashes,
timestamp, exact execution head, safe environment, dependency/OS/timezone/locale,
temp/artifact paths and test order. The synthetic recurrence test invokes the
unchanged owner with a fault injected at a dependency boundary; failure remains
failure. Events are flushed/fsynced to exclusive JSONL before test cleanup.

Callback read/serialization failures are recorded separately and cannot mask the
SUT exception. Missing diagnostics blocks diagnostic acceptance; it never makes a
failed test PASS. No Production module imports this opt-in diagnostic runner.
Only the explicitly authorized shared CI workflow is modified among existing
main blobs; all SUT, historical pins, restored bytes and assertions are protected.
