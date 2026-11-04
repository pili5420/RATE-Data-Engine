# RATE V11 Real Git Data Transport Binding V1

Offline qualification for the GitHub Git-Data API transport that will eventually
materialize the activation candidate as 9 blobs, 1 tree, 1 commit and 1 dedicated
activation branch ref.

The workflow uses repository-scoped GITHUB_TOKEN with only contents: write. Exact
allowed REST calls are the main-ref GET, exact base-main commit-object GET (to obtain
its immutable tree SHA), target-ref GET, and the Git blobs/trees/commits/refs POST
endpoints. PATCH/DELETE refs, merges, pull requests and main updates are forbidden.

No GitHub request is performed by this validator.