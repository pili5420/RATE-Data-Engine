# RATE V11 Route B — Zero-Fee Production Contract V1

Route B is the adopted zero-license-fee replacement for the previous 09:30 / 12:00 real-time non-display market-data contract.

The new contract deliberately removes the requirement for a real-time TWSE / TPEx data feed and therefore does not claim real-time intraday price coverage.

## 09:30 / 12:00 semantics

Both checkpoints remain part of the continuous RATE Decision State Chain.

They use the immediately preceding validated Production state, the latest available documented official public APIs, and the previous validated EOD market/ranking baseline.

They must not synthesize or imply current intraday price, current intraday volume, opening gap from a live quote, intraday re-ranking, paper-trade fill from current market price, or real-time market timing.

Ranking, portfolio and ledger state are carried forward unless a separately allowed official-public evidence delta changes non-price commentary/risk state. The 19:30 cadence remains the full EOD market refresh and ranking owner.

## Freshness

The old CADENCE_FRESHNESS_MINUTES <= 180 real-time/intraday requirement is removed for 09:30 and 12:00.

The new freshness rule is LATEST_OFFICIAL_AVAILABLE_WITH_PREVIOUS_EOD_MARKET_BASELINE. Each official-public source keeps its own publication-date/freshness validation. No stale fallback, scraping, undocumented endpoint, or third-party substitution is allowed.

## Acceptance

Route B permits Production Acceptance and CER-081 without real-time intraday coverage, provided the Route B runtime independently proves official-public evidence gate PASS, no current intraday price/volume values, no intraday re-ranking, no intraday trade fills, state/portfolio/ledger continuity, full EOD refresh at 19:30, and no fallback.
