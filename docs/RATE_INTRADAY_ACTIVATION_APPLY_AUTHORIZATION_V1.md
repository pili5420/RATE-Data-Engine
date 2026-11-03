# RATE V11 Activation Apply Authorization Gate V1

This gate validates one future **explicit Control Center authorization** to apply
the exact reviewed intraday activation candidate.

It does not apply files.

The authorization must be independently bound to:

- exact current main SHA;
- exact final-main readiness result SHA-256;
- exact candidate manifest SHA-256;
- provider identity;
- Control Center decision ID;
- the exact 9-file allowlist.

The authorization must be single-use, no-retry and no-fallback. It may authorize
only the exact candidate-file operation and may not authorize any additional live
provider request or pre-credit Production/CER-081.

A PASS means only `authorization_valid=true`.

The validator itself performs zero repository writes, zero live requests and does
not resolve the external dependency or registry state.

The next gate remains a separate, single-use activation apply executor.
