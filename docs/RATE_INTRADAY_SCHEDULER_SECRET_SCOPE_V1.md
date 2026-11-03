# RATE V11 Intraday Scheduler Secret Scope V1

This contract constrains the future 09:30 / 12:00 activation scheduler candidate.

The provider API secret is **not** a job-level environment variable.

It may appear only in the single step named:

`Acquire authorized intraday provider feed`

and only as the exact GitHub Actions secret expression for the Control
Center-approved secret name.

All other steps must be unable to access that secret through their step-level env,
and the secret expression must not appear anywhere in those step definitions.

The runtime order is also fixed:

1. acquire authorized intraday provider feed;
2. build Phase2 authorized intraday production source bundle;
3. execute Phase2 authorized intraday runtime.

The scheduler must retain the existing cadence cron and must not use
`continue-on-error: true`.

This remains candidate engineering only and does not activate Production.
