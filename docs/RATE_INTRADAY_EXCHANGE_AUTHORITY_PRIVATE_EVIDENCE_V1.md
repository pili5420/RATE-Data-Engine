# RATE V11 Private Exchange-Authority Evidence Manifest V1

This utility is for the point where real TWSE and TPEx authorization documents are
available privately.

It reads each private file locally only to compute SHA-256 and byte length. The output
contains no source path and no document content.

The operator must explicitly assert the expected scope string:

`ACTIVE_REALTIME_AUTOMATED_NONDISPLAY_INTERNAL`

That assertion is **not** authority. The output status is always:

`PENDING_CONTROL_CENTER_REVIEW`

The manifest cannot grant provider authority, Production activation, external-
dependency resolution, Production credit, or CER-081 credit.

After the private evidence is independently reviewed and approved by the Control
Center, its stable references and hashes may be supplied to the existing exchange-
authority evidence-intake gate.
