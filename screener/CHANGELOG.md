# Changelog

Notable changes to the Screener are recorded here. Versions follow
[Semantic Versioning](https://semver.org/): increment MAJOR for incompatible
CLI, Python API, output, or database-contract changes; MINOR for
backward-compatible functionality; and PATCH for backward-compatible fixes.
Git release tags use the `vMAJOR.MINOR.PATCH` form.

## [1.0.0] - 2026-11-19

Initial versioned baseline.

### Added

- Daily stock screening for supported US and European universes or supplied
  ticker lists, with 21 selectable technical indicators and CSV output.
- PostgreSQL persistence for screener runs, results, and analysis snapshots.
- Batch analysis and advisory trade plans, including configurable risk/reward
  levels and supported strategy/timeframe checks.
- Scheduled screener and analysis workflow suitable for container and
  Kubernetes execution.
- Compatibility import modules for callers using the previous root-level
  Python module paths.
