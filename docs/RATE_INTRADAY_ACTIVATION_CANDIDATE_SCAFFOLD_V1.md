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
- renders a 30-request / zero-retry / no-fallback Fugle runtime scaffold;
- renders an acquisition CLI scaffold with raw-evidence hashing;
- immediately sends the complete candidate map through the merged Activation
  Candidate Static Review gate.

The output is always `DESIGN_SCAFFOLD_ONLY`. It does not write candidate files,
does not execute provider requests, does not change the external dependency, and
does not authorize activation.
