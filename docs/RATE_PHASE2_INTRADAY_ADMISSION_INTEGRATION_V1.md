# RATE V11 Phase2 Intraday Admission Integration V1

This package connects the already-merged provider-neutral authorized intraday
payload validator to the Phase2 09:30 / 12:00 source path.

It does **not** resolve the external intraday dependency and does not activate any
provider.

## Required order

For 09:30 / 12:00, once the separate dependency-authority gate permits execution:

1. read the configured authorized intraday feed file;
2. validate the payload against the repository-rooted approved 30-symbol universe;
3. require exact TWSE 25 / TPEx 5 market mapping;
4. require exact trading date and cadence;
5. require freshness <= the payload validator limit;
6. bind the resulting qualification and the feed digest into Phase2 input material;
7. revalidate the feed digest and qualification digest inside `evaluate_material()`
   before predecessor lookup or ranking evaluation.

A caller cannot replace the feed after admission, substitute another 25+5 universe,
or provide an unbound qualification result.

## Governance

This integration preserves:

- `EXTERNAL_AUTHORIZED_INTRADAY_FEED_DEPENDENCY = BLOCKED_EXTERNAL` until a
  separate activation implementation changes the authoritative dependency state;
- zero provider selection by this module;
- zero network requests by this module;
- zero credential access;
- zero registry mutation;
- zero Production/CER-081 credit.

The existing public-official partial runtime remains unchanged while the external
dependency is blocked.
