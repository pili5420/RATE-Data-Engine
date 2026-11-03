# RATE V11 Full Synthetic Activation Candidate Review V1

This layer reviews one exact generated intraday activation candidate through every
accepted synthetic engineering gate in a single run.

The candidate is rebuilt from the externally hash-bound delta plan and then bound
to externally supplied:

- candidate manifest SHA-256;
- provider runtime SHA-256;
- acquisition CLI SHA-256;
- current main SHA;
- provider / endpoint / secret identity.

The same candidate map must then pass:

1. scaffold/static review;
2. Python/YAML/JSON syntax and AST review;
3. fake-HTTPS provider runtime semantic review;
4. fake-runtime acquisition CLI semantic review;
5. isolated 9-file materialization;
6. disk readback static/syntax/fake-HTTPS semantic review.

A PASS proves all synthetic reviewers operated on one exact candidate identity.

It still performs zero real provider requests, zero real credential access,
zero repository writes, no provider acceptance, no activation, no external
dependency resolution, and zero Production/CER-081 credit.

The resulting disposition is only:

`READY_FOR_LIVE_EVIDENCE_BOUND_ACTIVATION_REVIEW`
