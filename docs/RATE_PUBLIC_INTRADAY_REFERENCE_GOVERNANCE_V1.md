# RATE Public Intraday Reference Governance V1

## Purpose

This Control Center change allows the formal RATE 09:30 Opening Decision and 12:00 Midday Decision reports to include a clearly separated public/external intraday **reference layer** without weakening the existing Production market-intraday gate.

It does not authorize scraping or automated collection that conflicts with a provider's published terms.

## Automation rule

GitHub Actions may automatically retrieve a source only when at least one of the following is true:

1. The provider's published terms explicitly allow the intended automated access.
2. A documented official API/feed is used within its published terms.
3. Written provider permission or a contract covers the automated use.

Automated website scraping, undocumented-endpoint reverse engineering, access-control bypass, or treating browser-viewable data as automatically licensed machine data is not allowed.

## Current classifications

### Yahoo Taiwan stock web pages

Current class: `MANUAL_REFERENCE_ONLY`.

Yahoo's Taiwan Terms of Service state that automated means such as robots, spiders, scrapers, data-mining or data-extraction tools may not access or collect Service data without Yahoo's express prior permission.

Reference:
https://legal.yahoo.com/tw/zh-hant/yahoo/terms/otos/index.html

Therefore Yahoo prices may be manually referenced in a 09:30/12:00 report, clearly marked `EXTERNAL_REFERENCE_ONLY`, but may not currently be collected by GitHub Actions as RATE's intraday feed.

### TWSE MIS / general real-time website content

Current class: `MANUAL_REFERENCE_ONLY`.

TWSE terms for automated data download require an approved method or TWSE consent. Formal use of TWSE trading information is separately governed by TWSE trading-information rules and agreements.

References:
https://eshop.twse.com.tw/en/home/terms
https://twse-regulation.twse.com.tw/ENG/EN/law/DOC01.aspx?FLCODE=FL007304&FLNO=10

Therefore browser-viewable TWSE real-time information is not automatically upgraded to a GitHub Actions source.

### TWSE OpenAPI

Current class: `OPEN_OFFICIAL_NON_INTRADAY_API`.

Documented OpenAPI endpoints may continue to be used automatically where their terms permit, but daily/open-data endpoints do not satisfy RATE's 09:30/12:00 real-time `market_intraday` requirement merely because they are automated.

## 09:30 / 12:00 report behavior

The two formal report cadences remain active.

A report may include:

- official/open public data that is valid for automated use,
- manually supplied Yahoo/TWSE reference prices,
- a clearly separated `EXTERNAL_REFERENCE_ONLY` section,
- `REFERENCE_SIGNAL_ONLY` commentary.

A reference input must not:

- satisfy the formal `authorized_market_intraday` Data Gate,
- mutate the formal Decision State,
- execute AI Paper Portfolio trades,
- append a transaction as an intraday fill,
- be used as a fallback that hides `BLOCKED_EXTERNAL`.

## Production status unchanged

`EXTERNAL_AUTHORIZED_INTRADAY_FEED_DEPENDENCY` remains:

- 09:30: `BLOCKED_EXTERNAL`
- 12:00: `BLOCKED_EXTERNAL`
- `fallback_allowed=false`

A separate Control Center change request is required before any specific automated intraday source becomes Production-eligible.
