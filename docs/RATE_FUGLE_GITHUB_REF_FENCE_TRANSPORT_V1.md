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

Only an exact HTTP 201 response to this invocation's create request, with the
expected ref and commit target, establishes exclusive-create acknowledgement.
The adapter also requires matching readback before returning executor ownership.
An ambiguous create outcome, lost ACK or conflict fails closed without recovery or
retry. A same-main readback cannot establish ownership. A pre-existing marker blocks
reentry, including when a previous executor lost its successful create ACK.
