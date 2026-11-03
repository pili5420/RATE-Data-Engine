# RATE V11 Activation Acquisition CLI Semantic Review V1

This layer executes the generated acquisition CLI only with:

- a synthetic API key;
- a fake provider runtime;
- a temporary working directory;
- repository-rooted authoritative universe validation.

It performs no real provider request and reads no real credential.

The candidate acquisition CLI is required to:

- accept only the cadence-specific fixed feed output path;
- accept only the cadence-specific fixed raw-evidence output path;
- reject absolute paths and traversal;
- reject redirected/symlinked output ancestry;
- reject existing output targets;
- perform all output-path preflight before secret access or provider-runtime calls;
- use exclusive create;
- normalize the raw evidence reference to POSIX path form for cross-platform byte identity;
- persist no API key;
- hash raw evidence and bind that hash into the feed payload reference;
- produce a feed that passes the real authoritative Phase2 intraday admission gate.

Synthetic review additionally proves:

- missing key -> zero runtime calls and zero output files;
- wrong output path -> zero secret reads, zero runtime calls and zero output files;
- existing output -> protected bytes unchanged, zero runtime calls;
- provider-runtime failure -> no feed/raw evidence files;
- 09:30 and 12:00 use distinct fixed output directories.

A PASS remains synthetic engineering evidence only. It does not accept or activate
the provider, does not mutate repository/Production state, and grants zero
Production/CER-081 credit.
