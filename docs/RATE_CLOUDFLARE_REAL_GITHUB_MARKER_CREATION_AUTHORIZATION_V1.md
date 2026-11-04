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
