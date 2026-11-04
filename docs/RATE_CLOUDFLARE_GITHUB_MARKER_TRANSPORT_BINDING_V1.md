# RATE V11 GitHub Marker Transport Binding V1

This gate freezes the real transport boundary for future Cloudflare qualification
consumption-marker creation.

The workflow must use the repository-scoped built-in GITHUB_TOKEN with only
contents: write permission. No PAT secret is permitted.

Only api.github.com HTTPS requests for the exact marker GET and ref-create POST are
allowed. PATCH, DELETE, ref listing and main-ref update are forbidden. Redirects,
automatic retries and fallback are disabled.

This gate performs no real GitHub request and creates no ref.