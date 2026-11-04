# RATE V11 Draft PR HTTP Executor Rehearsal V1

This offline rehearsal executes the exact GitHub REST request sequence against a
synthetic HTTP transport.

The Draft PR body carries machine-readable durable receipt and execution-authorization
SHA256 markers. This allows an ambiguous POST outcome to be resolved by one exact
head/base GET without retrying POST.

Pre-existing matching Draft PR is treated as already consumed. Same head/base with
different markers is a conflict. No real GitHub request or PR is created.