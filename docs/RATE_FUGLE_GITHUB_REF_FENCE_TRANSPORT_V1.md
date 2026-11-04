# RATE V11 Fugle GitHub-Ref Consumption Fence Transport V1

This module is the production-shaped durable transport for the Fugle single-live
consumption marker.

The reachable GitHub surface is deliberately narrow:

- GET one exact tag under
  `refs/tags/rate-v11-qualification-consumed/fugle-{32-hex-prefix}`;
- POST one create-only Git ref request;
- GET the same exact tag for readback.

No PATCH, DELETE, list-refs, main-ref update, retry, redirect or fallback exists.

The future workflow credential is GitHub's scoped `GITHUB_TOKEN` with only
`contents: write`. The Fugle API key is not used by this transport.

CI replaces `HTTPSConnection` completely. Therefore these tests perform no real
GitHub request and create no real ref.

An ambiguous create outcome is never retried. The adapter performs exact-key
readback only. A pre-existing marker means the single-use authorization is consumed.
