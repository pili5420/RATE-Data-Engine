# RATE V11 Intraday Activation Candidate Scaffold Builder V1

This utility renders a **design scaffold only** for the future intraday activation
candidate.

It reads the current repository and the externally hash-bound Activation Delta Plan,
then builds all nine candidate file contents in memory:

- seven approved existing mutation paths;
- two new runtime adapter files.

The scaffold:

- transforms the three registry JSON files;
- removes all three current Phase2 hard-coded intraday blockers in memory;
- preserves authoritative Phase2 admission replay;
- renders 09:30 / 12:00 scheduler candidates that acquire the provider feed before
  Phase2 build/run and inject only the approved GitHub Actions secret;
- renders a Fugle runtime scaffold with exact 30 requests, zero retries and no fallback;
- fails on an empty API key before any network request;
- normalizes each provider quote into the authoritative payload fields
  `timestamp / price / volume / turnover`;
- requires timezone-bearing timestamps and finite numeric values;
- requires positive price and nonnegative volume / turnover;
- closes every HTTPS connection in a `finally` boundary;
- renders an acquisition CLI scaffold with raw-evidence hashing;
- immediately sends the complete candidate map through the merged Activation
  Candidate Static Review gate.

The runtime semantics are subsequently qualified by a dedicated fake-HTTPS review;
the scaffold itself performs no provider request.

The output is always `DESIGN_SCAFFOLD_ONLY`. It does not write candidate files,
does not execute provider requests, does not change the external dependency, and
does not authorize activation.
