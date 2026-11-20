# Changelog

Notable changes to Stock API are recorded here. Versions follow
[Semantic Versioning](https://semver.org/): increment MAJOR for incompatible
HTTP API, persisted-data, or frontend contract changes; MINOR for
backward-compatible functionality; and PATCH for backward-compatible fixes.
Git release tags use the `vMAJOR.MINOR.PATCH` form. Keep the frontend package
version in `frontend/package.json` aligned with each application release.

## [1.0.0] - 2026-11-19

Initial versioned baseline.

### Added

- Go HTTP API serving the Vue dashboard and PostgreSQL-backed screener runs,
  results, analysis snapshots, and portfolio positions.
- On-demand Yahoo Finance screening and market-analysis preview endpoints.
- Vue dashboard for saved screening and analysis data, including ticker charts
  and analysis progress.
- Shared Python/Go persistence contract tests and bounded HTTP server
  timeouts.
