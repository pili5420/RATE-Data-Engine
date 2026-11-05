# RATE CER-081 Scheduler Actual-Timing Evidence V1

Scheduler Reliability credit must be bound to the exact GitHub Actions scheduled run.

Each credited run must preserve the exact workflow run ID, first-attempt status, `event=schedule`,
the direct `github.event.schedule` value, workflow path and head SHA, the Production runtime
trading date/cadence, and GitHub Actions API `created_at` / `run_started_at` timestamps.

Cron definition alone, wall-clock proximity, nearest-slot matching, manual dispatch, post-hoc
date inference, retries, or fallback timing sources cannot substitute for this evidence.
Missing or inconsistent evidence fails closed.

The engineering blocking-delay policy is 900 seconds. Scheduler Reliability is PASS only when
all credited runs carry valid direct actual-timing evidence and the blocking-delay count is zero.
