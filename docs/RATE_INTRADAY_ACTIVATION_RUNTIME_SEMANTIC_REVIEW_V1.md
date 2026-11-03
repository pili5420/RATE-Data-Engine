# RATE V11 Intraday Activation Candidate Runtime Semantic Review V1

This module executes the **in-memory provider runtime candidate only against a fake
HTTPS transport**.

It first requires the complete candidate to pass the existing syntax/AST/YAML gate
and requires the runtime source SHA-256 to match an externally supplied hash.

The runtime source is additionally guarded against unsafe imports/top-level
execution and selected filesystem/process/socket calls before it is executed.

Synthetic review proves:

- exact 30 approved symbols;
- zero real network requests;
- exactly 30 fake HTTPS requests on the success path;
- every fake connection is closed;
- API key header binding;
- normalized `timestamp / price / volume / turnover` records;
- the produced records pass the real Phase2 authoritative intraday admission
  validator at 30/30 with TWSE 25 / TPEx 5;
- empty key fails before any request;
- 29 or 31 symbols fail before any request;
- HTTP 302 / 403 / 429 each fail after exactly one request with zero retry;
- malformed JSON fails after one request;
- missing aggregate data fails closed.

This is synthetic evidence only. No Fugle live request, real credential, provider
acceptance or activation is performed.
