# RATE V11 Intraday Provider Acceptance V1

This module defines the pure Control Center gate that may accept a provider only
after an independent single-live-qualification review has passed.

A PASS means **provider accepted for the next activation-design stage only**.
It does not activate Production and does not resolve the external dependency.

The acceptance decision is externally bound to:

- current main SHA;
- Control Center decision ID;
- canonical acceptance-decision SHA-256;
- provider identity;
- independent live-review SHA-256;
- provider-authority binding SHA-256;
- explicit license basis.

For the current owner-directed path, `OWNER_ASSUMED_AUTHORIZED` is distinct from
provider written confirmation. The usage scope remains personal/internal,
non-display, no resale, no redistribution, no sublicensing, and no third-party
market-data feed.

A PASS still enforces:

- activation_execution_allowed=false;
- registry_activation_allowed=false;
- external_dependency_resolved=false;
- fallback=false;
- automatic retry=false;
- Production credit=0;
- CER-081 credit=0.

The next gate is a separately reviewed Control Center activation implementation.
