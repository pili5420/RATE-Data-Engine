# RATE V11 Draft Activation PR Executor Rehearsal V1

This layer rehearses the final synthetic operation budget item after durable receipt
consumption and synthetic Git branch creation: exactly one Draft pull request.

The PR must use the reviewed activation branch as head, main as base, and draft=true.
Ready-for-review, auto-merge, merge queue and merge remain forbidden.

If Draft PR creation fails after the durable receipt has already been consumed, the
outcome is NON_RETRYABLE_AFTER_DURABLE_CONSUMPTION.

CI uses only a synthetic PR backend. No real pull request is created.