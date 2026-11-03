# RATE V11 Intraday Activation Candidate Syntax / AST Review V1

This module adds a structural review layer after the static activation-candidate
contract.

It performs no activation and no candidate writes.

For the nine in-memory candidate files it:

- parses all three JSON registries;
- compiles the four Python candidate files with `ast.parse`;
- verifies the Phase2 cadence-derived intraday status helper structurally;
- verifies runtime constants: 30 requests, zero retries, no fallback, Fugle host,
  approved secret name;
- rejects runtime `while` loops, sleep calls and print calls;
- verifies the acquisition CLI reads the approved secret via `os.getenv` and
  does not print;
- parses both scheduler YAML files;
- requires the GitHub Secret expression to be exact;
- requires the authorized feed path to be exact;
- requires acquire → build → Phase2 run commands;
- forbids `continue-on-error: true`;
- forbids public-partial runtime;
- compares scheduler cron values against current repository cron values so cadence
  timing cannot drift during activation.

A PASS is syntax/structure evidence only. It never authorizes or applies activation.
