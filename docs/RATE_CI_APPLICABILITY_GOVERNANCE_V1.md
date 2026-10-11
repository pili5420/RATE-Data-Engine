# CI Applicability Governance V1

Historical PR24 strict verification remains byte-identical. It applies only when
the exact historical base and merge-base match its BASE and the complete changed
file set is within its controlled ALLOWED owner set. Its original scope and
protected-file assertions still run; failure is BLOCKED.

Later changes must bind the PR base to the fetched current origin/main, the exact
head and clean worktree. They always run CURRENT_MAIN_COMPATIBILITY_GATE, never
reuse the historical diff allowlist. This includes diagnostics-only changes.

The mandatory replacement runs every inherited 989 regression, including CER074
through CER081, publisher/source Latest, Thin Work, report soak, Phase2 and
full-market compatibility; then the original synthetic four-cadence and soak
proofs. New applicability tests run separately. Both Windows and Linux are
required. No skip, assertion relaxation, whitelist or continue-on-error is used.

Formal outcomes:
- APPLICABLE_STRICT_PASS
- NOT_APPLICABLE_REPLACED_BY_CURRENT_MAIN_GATE_PASS
- BLOCKED

Workflow output archives the selected mode, exact base/head, current main, changed
files, each original assertion outcome and continuity proofs. No financial
network, real Production publication, First Refresh or scheduler is authorized.
The old pre-contract historical workflows retain their existing strict gates.
