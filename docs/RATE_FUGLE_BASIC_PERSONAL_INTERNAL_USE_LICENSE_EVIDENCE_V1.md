# RATE Fugle Basic Personal/Internal Use License Evidence V1

This governance artifact records Fugle MarketData API's written confirmation supplied
by the account owner for the described RATE V11 use case.

## Provider gate

For the described scope, the Fugle provider-plan gate is:

`PASS_CONFIRMED_IN_WRITING`

The confirmed scope is single-user personal/internal use, automated non-display
analysis, approximately 30 individual intraday quote requests per cadence within the
current 60 requests/minute Basic-user limit, calculation of technical indicators,
rankings, scores and decision logic, retention of derived personal analysis, and
execution in a user-controlled private cloud runtime.

API keys, raw market data, derived analysis and market-data-bearing logs must remain
private to the account owner. They must not be published to a public repository,
redistributed or resold.

## Exchange boundary

This provider confirmation is **not** TWSE or TPEx exchange authorization. Exchange
authority remains a separate fail-closed gate:

`UNRESOLVED_REQUIRES_SEPARATE_EXCHANGE_EVIDENCE`

No provider confirmation may bypass that gate.

## Route B boundary

This evidence does not change Route B and does not activate Fugle as a Production
source. Fugle remains:

`QUALIFIED_PROVIDER_OPTION_NOT_ACTIVE_IN_ROUTE_B`

Route B remains the zero-fee public-official Production architecture until a separate
Control Center change authorization explicitly changes that architecture.
