# Fugle Phase B Authorization Evidence

Source: Control Center supplemental authorization evidence, RATE Phase B.

- Fugle Basic User provides Taiwan stock intraday REST API access.
- Basic User limit is 60 intraday REST calls per minute.
- Intraday snapshot API is not supported on Basic User.
- REST authentication uses `X-API-KEY`.
- Official quote endpoint: `/marketdata/v1.0/stock/intraday/quote/{symbol}`.
- Multi-account or other rate-limit circumvention is prohibited.
- Market information must not be intercepted, relayed, sold, rented, transferred, or sublicensed.

RATE usage profile: authenticated official API, personal/internal analytics,
ephemeral intraday ingestion, normalized evidence, and derived RATE Decision
State. No raw-data redistribution, resale, sublicensing, account rotation,
snapshot endpoint, or permanent raw Fugle historical database.

This evidence authorizes `PASS_FOR_EPHEMERAL_INTERNAL_ANALYTICS`; permanent raw
storage remains outside scope.
