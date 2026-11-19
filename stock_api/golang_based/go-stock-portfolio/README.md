# Go Stock Market Desk

See the repository [architecture and change boundaries](../../../ARCHITECTURE.md)
for component ownership, the shared PostgreSQL contract, and implementation
scoping guidance.

Gin serves the JSON API and the production Vue build. Saved screener runs,
screener rows, and analysis snapshots are read from the existing PostgreSQL
tables. The explicit `/api/market/...` routes still fetch live data from Yahoo
Finance; `internal/marketanalysis` owns indicator scoring and preview-plan
calculations independently of Gin response types.

The current release baseline is `1.0.0`; the Vue package version is maintained
in `frontend/package.json`. See the [changelog](./CHANGELOG.md). Releases use
Semantic Versioning and Git tags in the form `vMAJOR.MINOR.PATCH`.

The saved-data boundary is defined by typed read models and the
`SavedDataStore` port in `internal/marketdesk`. `internal/postgresstore`
implements the port and owns SQL and database-row mapping; `web` maps those
models to the existing HTTP JSON DTOs. Python remains the writer for scheduled
screener and strategy-analysis records. The shared persistence fixture is
`contracts/analysis_result_row.json` at the repository root, and is exercised
by Python, adapter, and API contract tests.

## Local development

Requirements: Go 1.25+ and Node.js 22+.

The API requires `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, and `DB_NAME`.
`DB_SSLMODE` is optional and defaults to `prefer`. In a local shell, load your
protected env file and start the API from this directory:

```bash
set -a
. "$HOME/.config/stock-screener/stock-screener-db.env"
set +a
go mod tidy
go run .
```

Initialize the existing screener/analysis tables with
`screener/create_stock_screener_table.sql` before starting the API. The
database account needs `SELECT` access to `screener_runs`, `screener_results`,
`analysis_runs`, and `analysis_results`, plus `SELECT` and `INSERT` access to
`portfolio_positions` and `USAGE` on its generated `position_id` sequence for
the portfolio endpoints.
Reapply that SQL script after upgrades; it includes idempotent changes for the
analysis status and progress fields required by the dashboard, and creates the
durable portfolio table.

In another terminal, start Vue:

```bash
cd frontend
npm install
npm run dev
```

Open <http://localhost:5173>. Vite proxies `/api` requests to the Go service on
port 8080. Set `PORT` to change the API port.

The frontend is installable as a PWA on HTTPS deployments (and on localhost
for development). Its service worker caches the app shell and static assets
for offline startup; `/api` responses and TradingView embeds are not cached,
so market data and charts still require a network connection.

## API

- `GET /api/health` reports service health.
- `GET /api/ready` checks the PostgreSQL connection.
- `GET /api/screen/runs?limit=50` lists saved screener runs.
- `GET /api/screen/results?run_id={uuid}` reads one run's saved ticker rows;
  omit `run_id` to read the latest run.
- `GET /api/analysis/runs?limit=50` lists saved analysis runs.
- `GET /api/analysis/results?run_id={uuid}` reads one saved analysis run;
  omit `run_id` to read the latest run.
- `GET /api/analysis/{ticker}?screener_run_id={uuid}` reads a saved analysis
  snapshot, optionally linked to a screener run. Omit the query to read the
  latest saved snapshot for that ticker.
- `GET /api/market/analysis/{ticker}?rr_ratio=3` fetches fresh Yahoo data and
  returns an on-demand preview. It is separate from the canonical Python
  strategy-analysis workflow and is not persisted.
- `POST /api/screen` performs a live Yahoo screen for up to 50 supplied ticker
  symbols. Request bodies are limited to 64 KiB. It does not write those
  on-demand results to PostgreSQL.
- `GET /portfolio` lists PostgreSQL-backed positions.
- `POST /portfolio` adds a position to PostgreSQL.
- `GET /api/market/analysis/{ticker}` and `GET /api/market/stocks/{ticker}`
  perform live Yahoo lookups instead of reading saved data; treat these
  calculations as previews, not persisted Python strategy decisions.

The Vue dashboard reads stored runs/results by default and loads TradingView's
free embedded chart when a ticker is selected. The chart is an external
TradingView embed and requires browser access to TradingView. Some exchange
symbols may not be available in the free embedded widget; use its full-chart
link to open that ticker directly on TradingView. The database schema
does not contain historical OHLC for every screener row, so database-backed
analysis fields remain separate from chart prices; unavailable open, high, low,
and volume fields are returned as `null`. The results toolbar includes a setup
filter for all tickers, any strategy, actionable pullback plans, or a specific
strategy/timeframe, plus a status sub-filter for entry-triggered, watch, or
exit-triggered setups. Status filtering is available when filtering by any
strategy or a specific strategy/timeframe. Matches update as analysis
snapshots are saved.

Example screen request:

```bash
curl -X POST http://localhost:8080/api/screen \
  -H 'Content-Type: application/json' \
  -d '{"symbols":["AAPL","MSFT","AAL.L"],"rr_ratio":3,"green_only":false}'
```

## Container

Build and publish the Go/Vue API as a separate image from the Python scheduled
screener worker:

```bash
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  -t pikoters/stock-market-desk:latest \
  --push .
```

The image serves both the Vue app and API on port 8080 as UID 10001.
Pass the five required `DB_*` variables to the container from your deployment's
Secret/environment configuration.

Deploy the combined API and frontend with the Kubernetes Deployment and
Service plus Traefik IngressRoute from the repository root:

```bash
kubectl apply -f k8s/stock-market-desk.yaml
```

The test route uses `PathPrefix(`/`)` through Traefik's HTTP NodePort 32489, so
open <http://192.168.40.110:32489> (or use another node LAN IP). The current
nodes are `192.168.40.110`, `192.168.40.210`, `192.168.40.211`, and
`192.168.40.212`. The Traefik middleware only allows RFC1918 and IPv6 ULA
client addresses; narrow `sourceRange` in `k8s/stock-market-desk.yaml` to the
actual LAN/VPN CIDRs before deployment where possible. This is network
restriction, not application authentication: keep the route on a trusted
private network, do not forward the NodePort from the internet, and do not
expose the ClusterIP service directly. The manifest expects the image tag above
and the `stock-screener-db` and `stock-screener-registry` Secrets in `homelab`.
The server also enforces request and connection timeouts.

Run Go tests from this module with `go test ./...`.

## Notes

Yahoo Finance is an external data source; live requests can be rate-limited or
temporarily unavailable. The Go API reads the same persisted PostgreSQL tables
as the Python screener and retains the existing Python scheduled workflow.