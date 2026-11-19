# Architecture and Change Boundaries

## Purpose

Keep the stock research workflow understandable and easy to change without
splitting it into more deployable services. This document distinguishes current
ownership from boundaries to strengthen incrementally; it is not a requirement
to rewrite existing modules before adding features.

## System shape

```text
Scheduled Python worker
  universe selection -> screening -> strategy analysis
  -> PostgreSQL persistence
                         |
                         v
Go API -> PostgreSQL read adapter -> Vue dashboard
   |
   +-> live Yahoo Finance adapter -> preview calculations
```

The Python worker and Go/Vue dashboard remain separate deployables. PostgreSQL
is their shared persistence contract. Do not add a queue, service, or new
database solely to create architectural layers.

## Ownership

| Capability | Owner | Source of truth |
|---|---|---|
| Scheduled universe selection and screener-run lifecycle | Python `run_daily.py` and `stocks_screener.py` | Python workflow |
| Persisted strategy analysis and trade plans | Python `stock_analysis.py`, `trade_analysis.py`, and `strategy_analysis.py` | `analysis_runs` and `analysis_results` |
| Persistence schema and additive schema changes | `screener/create_stock_screener_table.sql` | PostgreSQL schema |
| Saved-run dashboard API | Go API | PostgreSQL records written by the Python workflow |
| On-demand Go market calculations | Go API | Preview only; not authoritative persisted strategy output |
| Browser presentation and filters | Vue frontend | API response contracts |
| Broker order submission | Not present in the current checkout | Analysis remains informational; no broker orders are submitted |
| Portfolio positions | Go API | PostgreSQL `portfolio_positions` records |

Python is the canonical engine for persisted strategy decisions. The Go live
market endpoints may calculate indicators for interactive exploration, but
their plans must not be presented as equivalent to persisted Python strategy
results unless a parity contract and tests are added.

## Dependency direction

For new behavior, keep dependencies moving inward:

```text
CLI / HTTP transport -> application workflow -> domain rules
                           |                    ^
                           v                    |
                    ports / contracts <- adapters
```

- **Transport** parses CLI or HTTP input, validates protocol shape, and maps
  results to CLI output or API DTOs.
- **Application workflow** coordinates a screen, analysis run, or saved-data
  query. It owns sequencing and partial-failure policy.
- **Domain rules** calculate signals, scores, setups, and risk plans without
  reading environment variables, issuing SQL, or making network calls.
- **Adapters** implement Yahoo Finance, PostgreSQL, CSV, and external services
  when their adapter code is present.
- **Composition roots** (`run_daily.py` and Go `main.go`) select and wire
  adapters. Avoid hidden client construction inside reusable business rules.

The Go technical indicator algorithms now live in
`stock_api/golang_based/go-stock-portfolio/internal/technicalanalysis`.
`internal/marketdata` contains the Go market-bar value type. HTTP `Bar` values
are translated at the web boundary rather than making the calculation package
depend on Gin or JSON response behavior.

The Go split is intentionally incremental: `internal/marketanalysis` owns the
live preview calculations and typed market result/plan models; `web` owns HTTP
orchestration and DTO mapping. Add a separate application workflow only if the
same use case needs another transport or independently testable orchestration.

## PostgreSQL anti-corruption boundary

PostgreSQL is the intentional cross-language contract, not a shared in-memory
domain model. Preserve these rules:

1. Python owns writes for scheduled screener and analysis runs.
2. The Go dashboard reads saved analysis; Go live calculations do not silently
   replace or mutate those records.
3. SQL column names, JSONB layout, and pandas DataFrames stay inside persistence
   adapters. HTTP handlers and strategy rules consume typed application/API
   values, not SQL rows or `to_jsonb` maps.
4. Translate persisted rows explicitly into Go read models and then API DTOs.
   Translate Python result records into the existing schema inside the Python
   persistence adapter.
5. Schema evolution is additive and backward-compatible while Python and Go
   versions may overlap. Apply schema before deploying code that requires it;
   remove old columns only after all readers/writers have migrated.
6. Every schema change updates the SQL initializer, adapter mapping tests,
   representative API contract tests, and operational instructions.

The Go `internal/marketdesk` package owns typed saved-data read models and the
`SavedDataStore` port. `internal/postgresstore` implements that port and owns
SQL plus PostgreSQL-row/JSONB mapping. The `web` package translates those
read models into HTTP DTOs, keeping the public JSON contract out of the
persistence adapter. Python remains the writer; no schema change is required
for this boundary.

The Python package makes its internal boundaries visible in the directory
layout: `application/` owns analysis orchestration and its ports, `domain/`
owns indicator calculations and trade-plan rules, `market_data/` owns Yahoo
history/context and market-backed strategy analysis, and
`infrastructure/postgres/` implements persistence. Root-level modules such as
`trade_analysis.py` remain compatibility entry points; new internal imports
should target the subpackages. Google Drive upload and Trading 212 order
submission have been removed; this application provides analysis only and
does not submit broker orders.

## Current change sequence

Use small, independently verifiable slices:

1. **Technical-analysis boundary (implemented):** keep market bars separate from
   HTTP DTOs, isolate Go indicator calculations, and preserve output behavior
   with unit tests.
2. **Persistence anti-corruption layer (implemented):** move the Go
   PostgreSQL implementation out of `web`, define a storage port and typed
   read models, and map API DTOs explicitly without changing API JSON.
3. **Python analysis boundary (implemented):** keep root-level legacy modules
   as compatibility facades; place workflow orchestration and ports in
   `application/`, indicators/plans in `domain/`, market-data integration in
   `market_data/`, and PostgreSQL adapters in `infrastructure/postgres/`.
4. **Cross-language persistence contract (implemented):** use the shared
   `contracts/analysis_result_row.json` fixture in Python writer-contract and
   Go adapter-mapping tests, with a web API compatibility test. Add golden
   indicator/plan fixtures if the two languages later intentionally share
   those algorithms.

Each slice should preserve current endpoints, SQL columns, scheduled-job
behavior, and trading safety unless a separate approved change explicitly
changes them.

## Scoping template for future work

Before implementing a feature, specify:

1. **Outcome:** user-visible or operational behavior and acceptance criteria.
2. **Owner:** one workflow/component responsible for the behavior.
3. **Allowed boundary:** transport, application, domain, adapter, persistence,
   or UI; list the files/packages expected to change.
4. **Contracts:** request/response, DB/schema, configuration, or broker side
   effects affected.
5. **Invariants:** source of truth, idempotency, ordering, status transitions,
   and what must not change.
6. **Failure behavior:** partial success, retry safety, timeout, diagnostics,
   and user-visible errors.
7. **Verification:** focused unit, adapter/integration, contract, and
   compatibility tests.
8. **Out of scope:** explicitly state nearby features not included.

Prefer one owner and a narrow vertical slice. If a change crosses a boundary,
add or update the adapter/contract test rather than letting the dependency
spread into the adjacent layer.
