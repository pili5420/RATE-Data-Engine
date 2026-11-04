# RATE V11 Real Draft Activation PR Executor V1

Executor state machine for one authorized Draft activation PR.

CI uses only a synthetic PR transport. The executor performs an exact head/base
preflight, rejects pre-existing PRs, allows one Draft PR create attempt, and preserves
non-retryable semantics after durable receipt consumption.

Ready-for-review, auto-merge, merge queue and merge remain forbidden. No real GitHub
request or PR is created in CI.