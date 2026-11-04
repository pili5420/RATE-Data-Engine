# RATE V11 Real GitHub Marker Creation Authorization V1

This gate validates one explicit authorization to create the durable lightweight tag
that consumes the Cloudflare real-qualification authorization.

It binds the exact Cloudflare qualification authorization qualification, current
main, derived marker ref and marker target.

Allowed operations are exactly:
1. marker GET preflight;
2. one marker ref create;
3. marker GET readback.

No main update, branch ref, pull request, merge, delete, marker retry or Cloudflare
request is authorized by this gate.

A PASS does not create the marker. The next gate is a separate real marker executor.


## Marker identity binding

Two hashes are intentionally distinct:

- `cloudflare_authorization_qualification_sha256` binds the complete #134 qualification object.
- `cloudflare_real_qualification_authorization_sha256` is the original Cloudflare real-qualification authorization SHA256 carried inside that qualification.

The durable marker ref is derived only from the original authorization SHA256. The
qualification-object digest must never be substituted as marker identity.
