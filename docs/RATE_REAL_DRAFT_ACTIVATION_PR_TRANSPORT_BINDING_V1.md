# RATE V11 Real Draft Activation PR Transport Binding V1

This gate fixes the future GitHub transport used to create the one authorized Draft
activation pull request.

The workflow uses repository-scoped GITHUB_TOKEN with only contents: read and
pull-requests: write. No PAT is allowed. Repository Actions policy allowing workflow
PR creation must be externally verified before execution.

The request surface is limited to an exact open-PR preflight GET and one create-PR
POST with base=main and draft=true. PATCH, ready-for-review, comments, auto-merge,
merge queue and merge endpoints are forbidden.

GitHub may suppress or require approval for workflows associated with content created
by GITHUB_TOKEN automation. Therefore auto CI triggering is never assumed; manual
workflow approval may be required.

This validator performs no GitHub request and creates no PR.