# Daily Stock Screener (US + Europe)

Python project to screen tradeable stocks from Yahoo Finance using daily data and 21+ selectable technical indicators.

The current version is `1.0.0` (see [`__version__`](./__init__.py) and the
[changelog](./CHANGELOG.md)). Releases use Semantic Versioning and Git tags in
the form `vMAJOR.MINOR.PATCH`.

See the repository [architecture and change boundaries](../ARCHITECTURE.md)
before making cross-component changes.

## Features
- Universe pickers: `sp500`, `nasdaq`, `dow`, `dax`, `ftse100`, `cac40`, `all-eu`
- Manually supply tickers via `--symbols` or `--symbols-file`
- **21 Technical Indicators:**
  - Arnaud Legoux Moving Average (`alma`)
  - MACD (`macd`)
  - Awesome Oscillator (`awesome`)
  - Parabolic SAR (`psar`)
  - Moving average triple / EMA crossover (`moving_average_triple`)
  - Bollinger Bands (`bollinger`)
  - Stochastic RSI (`stochrsi`)
  - Triple EMA (`triple_ema`)
  - Volume vs 20-day avg (`volume`)
  - Relative Strength Index (`rsi`)
  - Average True Range (`atr`)
  - Commodity Channel Index (`cci`)
  - Williams %R (`williams`)
  - Average Directional Index (`adx`)
  - On-Balance Volume (`obv`)
  - Momentum (`momentum`)
  - Rate of Change (`roc`)
  - Keltner Channels (`keltner`)
  - Ichimoku Cloud (`ichimoku`)
  - Accumulation/Distribution Oscillator (`adosc`)
  - Volume Price Trend (`vpt`)

## API and dashboard

The Python screener is a batch/CLI worker, not a Flask service. The separate
Go API and Vue dashboard are documented in the
[Go stock market desk README](../stock_api/golang_based/go-stock-portfolio/README.md).

## Python backend boundaries

The Python package uses folders for its internal boundaries:

```text
screener/
  application/       Analysis workflows and required ports
  domain/            Indicator calculations and trade-plan rules
  infrastructure/
    postgres/        PostgreSQL repository and connection factory
  market_data/       Yahoo Finance context and market-backed strategy analysis
  tests/             Unit and integration-focused tests
  run_daily.py       Scheduled-job composition and entry point
  stocks_screener.py Screening CLI and orchestration
  stock_analysis.py  Analysis CLI
```

The root-level `analysis_workflows.py`, `market_context.py`, `market_indicators.py`,
`persistence.py`, `strategy_analysis.py`, `trade_plans.py`, and related modules
are compatibility imports retained for callers using the older module paths.
New internal code should import from the corresponding subpackage directly.

## Install

```bash
python3 -m pip install -r requirements.txt
```

## Run

```bash
# All 21 indicators on SP500 (default)
python3 stocks_screener.py --universe sp500 --start 2024-01-01 --end 2026-01-01 --output results.csv

# Custom indicators
python3 stocks_screener.py --universe sp500 --indicators alma,macd,rsi,atr --output results_custom.csv

# Custom tickers
python3 stocks_screener.py --symbols AAPL,MSFT,GOOG --start 2025-01-01 --output results.csv

# Only keep stocks whose latest fetched daily candle is green
python3 stocks_screener.py --universe sp500 --green-only --output green_stocks.csv

# Nasdaq-listed non-ETF stocks (from Nasdaq Trader's symbol directory)
python3 stocks_screener.py --universe nasdaq --max-symbols 100
```

CSV export is optional. Without `--output`, the screener does not write a CSV;
provide `--output path.csv` when you want a local export.

`--green-only` filters out a stock unless its latest fetched daily candle closed
above its open. It does not require the stock to be above a moving average or
have a bullish indicator score.

The `nasdaq` universe is loaded from Nasdaq Trader's current listed-symbol
directory, excluding test issues and ETFs. If an indicator calculation fails
for a ticker, that ticker is skipped and the error is logged rather than
returning a result that appears complete.

## Example

```bash
python3 stocks_screener.py --symbols AAPL,MSFT,GOOG --indicators alma,macd,bollinger,rsi --start 2025-01-01
```

## Output

Results CSV with all indicator values and bullish signal flags. Sorted by `score` (weighted sum of signals).

**Weighted Scoring:** regular true signals count as +1, a crossover-up signal (e.g., `sma100_cross_up_sma200`) counts as +2, and a crossover-down signal counts as -2. The `score` column is therefore a weighted aggregate — dashboards should either use the `score` as a quick-sort metric or read the individual signal columns (for exact rule visualization) when displaying components of the score.

### CSV column changes

- `stop` and `target` columns now contain the computed stop-loss and target prices for each row. These replaced the previous `stop_1_3` / `target_1_3` column names to support arbitrary reward-to-risk ratios.
- `rr_ratio` column stores the reward-to-risk ratio used to compute the `target`.

## PostgreSQL history

CSV output remains enabled. To also save every screener execution and its
results, configure the `[database]` section in `config.ini`, create the tables
once, and pass `--save-db`:

```bash
psql -h localhost -p 5432 -U YOUR_DB_USER -d YOUR_DB_NAME \
  -f create_stock_screener_table.sql

python3 stocks_screener.py --universe sp500 --green-only \
  --output green_stocks.csv --save-db
```

The script creates `screener_runs` and `screener_results`. Each run has a new
UUID, including reruns on the same day; results reference that run and retain
the market candle date, indicator values, signals, score, stop, and target.
The UUID is included in the CSV's `run_id` column when `--save-db` is enabled.
Run parameters and the selected ticker list are stored alongside the results.

Save analysis snapshots (including indicators, signals, plan levels, source
screener data, and market date) as a separate daily history:

```bash
python3 stock_analysis.py --results green_stocks.csv --save-db
```

For database-backed runs, the analysis run is created before ticker analysis
starts. Each ticker snapshot is then committed in its own transaction, so
completed tickers are available in PostgreSQL while the remaining stocks are
still being analyzed. The Market Desk refreshes the selected ticker and reports
progress while the associated analysis run is active. Reapply
`create_stock_screener_table.sql` after upgrading; its additive statements add
the run-status and progress columns to existing databases.

By default, analysis includes every row produced by the screener, regardless
of score, with no top-N cap. To limit an analysis intentionally, pass
`--min-score` and/or `--top-n` when running the analysis command manually. The
scheduled daily job always analyzes every row produced by the screener,
regardless of score. A ticker whose market data cannot be fetched is recorded
with an explicit unavailable note, and the remaining tickers continue to be
analyzed. Set `ANALYSIS_ENABLED=false` in the scheduled job environment to skip
the analysis pass entirely while still running the screener; it defaults to
`true`.

Every analyzed ticker also receives manual-review plans for MAMA (daily and
4-hour), PAPA (daily), TITA (daily), CALMA (weekly), FISHBALL (30-minute),
BOPIS (daily), BUNSO (15-minute and 1-hour), LOLO (weekly), TITO (daily), and
KASAMBAHAY (daily), SUPERTREND (daily, 5-minute, and 15-minute), ALLIGATOR
(daily), and BREAD AND BUTTER (daily and 1-hour). Each plan reports its signal
status, entry trigger, reference entry, indicator/support stop when the
strategy specifies one, exit rule, risk percentage when calculable, and
timeframe-specific as-of date or timestamp. A fixed profit target is not
invented where the strategy rules specify an indicator exit instead. Plans are
suggestions only; the tool does not place orders.

The strategy checks use these documented defaults/approximations:

- TITA RSI threshold is 55 by default; set `--rsi-threshold` from 50 through
  55. PAPA and LOLO accept a bullish MACD cross at/below zero or within a
  default 0.5%-of-price tolerance, configurable with
  `--macd-zero-tolerance-pct`.
- MAMA's ALMA stop must imply strictly less than 5% risk; TITA's ALMA stop may
  imply up to and including 5% risk. PAPA uses its 40-period SMA midline,
  CALMA its weekly ALMA, FISHBALL the prior 20-bar support, and BOPIS EMA9 as
  the initial indicator stop.
- BUNSO uses ALMA(9, 0.85, 6), a 20-bar consolidation range no wider than 5%,
  a breakout above the prior 20-bar high on more than twice the previous
  20-bar average volume, an RSI cross above 70, and a close above the prior
  252 completed daily highs. Yahoo Finance's 15-minute history is limited to
  the recent 59 days; 1-hour history is requested for up to 700 days. If the
  required bars are unavailable, the plan says so rather than reporting no
  signal. The volume spike is a momentum proxy, not evidence of institutional
  buying.
- LOLO needs 200 completed weekly bars. If the regular daily history is too
  short, the analyzer requests up to eight years of daily bars to build weekly
  data. Its undefined “macro market top” exit is approximated as a bearish
  weekly MACD crossover with MACD above zero; the SMA200 exit remains as
  specified. Index membership, dividend profile, and company quality must be
  checked separately.
- TITO treats the immediately preceding daily bar with Bollinger Bands fully
  inside Keltner Channels as the squeeze, and requires a breakout above the
  upper Bollinger Band with a rising MACD histogram. The upper-band re-entry
  is reported as a 50% partial-exit trigger, separately from the remaining
  exit below the 20-SMA.
- KASAMBAHAY reports no initial stop or risk percentage because none was
  specified; its take-profit trigger is a daily high touching the 20-SMA
  envelope midline. Company quality and whether a sell-off is temporary
  require separate review.
- SUPERTREND uses the library's Supertrend(7, 2.1) direction and line together
  with EMA9. It is calculated on daily, 5-minute, and 15-minute histories;
  Yahoo's recent 5-minute data is limited to the last 59 days.
- ALLIGATOR uses smoothed median-price lines with the standard Jaw(13, shift
  8), Teeth(8, shift 5), and Lips(5, shift 3). Since the supplied rules do not
  quantify “fan out widely,” the analyzer requires at least a 0.5% Lips-to-Jaw
  spread and an expanding positive MACD histogram. Its “lines begin crossing”
  exit is approximated by loss of bullish line order together with a close
  below Teeth.
- BREAD AND BUTTER approximates horizontal resistance with the prior 20-bar
  high, requires a breakout on at least 1.5x prior average volume within the
  preceding 10 bars, and defines a bullish reversal candle as close above
  open on an EMA20 retest within 1% of the line. The nearest available target
  is approximated by the highest high in the prior 252 daily bars or 1,764
  hourly bars; when no such level is above price, no target is supplied. These
  definitions are explicit heuristics because the rules do not specify
  numeric meanings for “high volume,” “exactly,” or “strict historical
  resistance.”
- FISHBALL approximates horizontal support as a test within 2% of the prior
  20-bar low, requires volume above the prior 20-bar average, and uses
  9-period Fisher and 7-period TRIX. Configure its support lookback with
  `--fishball-support-lookback`.
- The 4-hour MAMA check builds bars from groups of four completed hourly bars;
  its latest completed bar can be earlier than the daily close. The weekly
  CALMA and LOLO checks exclude the current unfinished week. Yahoo Finance
  only provides limited recent windows of intraday bars, so old or
  insufficient intraday history is marked unavailable rather than treated as
  a no-signal. Five-, 15-, and 30-minute checks request up to the latest 59
  days.
  Intraday checks make additional downloads and can make large universe scans
  slower.

When using the scheduled job, thresholds can be changed through
`ANALYSIS_RSI_THRESHOLD`, `ANALYSIS_MACD_ZERO_TOLERANCE_PCT`, and
`ANALYSIS_FISHBALL_SUPPORT_LOOKBACK`. In saved-run analysis, the original
screener row remains the source of the base EMA/ATR plan; strategy checks use
latest downloadable histories and each timeframe's `as_of` date is recorded
inside its strategy plan.

To use the captured screener snapshot as the source for the base EMA/ATR plan
and preserve its run lineage, select a database run. Strategy overlays still
use latest downloadable histories as described above. Omitting the UUID after
the option selects the latest run; provide a UUID to select a specific one:

```bash
# Analyze the latest captured run as of its saved candle date
python3 stock_analysis.py --save-db --screener-run-id

# Analyze a specific captured run
python3 stock_analysis.py --save-db --screener-run-id RUN_UUID
```

This mode reads `screener_results` directly and saves its analysis linked to the
source run. Database-enabled screener runs capture EMA100, EMA200, and ATR even
when they are omitted from `--indicators`, so the base plan can use those
values. Older runs without those values remain analyzable, but their base plans
are marked non-actionable if no captured stop and target are available. The
separate strategy overlay fetches fresh histories in either CSV or saved-run
mode and records its own timeframe-specific as-of dates.

For example, to review analysis snapshots together with their originating
screener run when available:

```sql
SELECT a.started_at AS analysis_started_at, r.started_at AS screener_started_at,
       x.ticker, x.as_of, x.close, x.entry, x.stop, x.target, x.actionable
FROM analysis_results AS x
JOIN analysis_runs AS a USING (analysis_run_id)
LEFT JOIN screener_runs AS r ON r.run_id = x.screener_run_id
WHERE x.ticker = 'AAPL'
ORDER BY a.started_at;
```

## Kubernetes daily run

The container runs the screener and, only if it succeeds, analyzes that exact
PostgreSQL run. The CronJob is scheduled for 18:30 America/New_York on weekdays,
after the US market close. CSV output is disabled by default, so the job needs
no writable volume; the database is the durable record. The image runs as UID
10001, and the pod uses a read-only root filesystem with privilege escalation
disabled.

Create the PostgreSQL tables once by running `create_stock_screener_table.sql`
against the target database. Build from the `screener/` directory so the
Dockerfile packages the Python modules under the `screener` importable package.
Build and push the image, then change the image reference in
`k8s/stock-screener-cronjob.yaml` and `k8s/stock-screener-test-pod.yaml` to the
pushed tag:

```bash
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  -t pikoters/stock_trading:latest \
  --push .
```

Create a protected env file with these keys and values for the PostgreSQL
service reachable from the cluster, then create the Kubernetes Secret:

```text
DB_HOST=postgresql.default.svc.cluster.local
DB_PORT=5432
DB_USER=YOUR_DB_USER
DB_PASSWORD=YOUR_DB_PASSWORD
DB_NAME=YOUR_DB_NAME
```

Create the file locally with your real database values. The directory and file
are restricted to your user:

```bash
umask 077
mkdir -p "$HOME/.config/stock-screener"
chmod 700 "$HOME/.config/stock-screener"
${EDITOR:-vi} "$HOME/.config/stock-screener/stock-screener-db.env"
```

Create or update the Kubernetes Secret from that file:

```bash
(
  set -e -o pipefail
  kubectl -n homelab create secret generic stock-screener-db \
    --from-env-file="$HOME/.config/stock-screener/stock-screener-db.env" \
    --dry-run=client -o yaml | kubectl apply -f -
)
kubectl -n homelab apply -f k8s/stock-screener-cronjob.yaml
```

If the Docker Hub repository is private, create a pull Secret in the same
namespace as the workload. Use a Docker Hub personal access token with read
access to the repository. Enter it at the prompt; do not place it directly in
the command line:

```bash
(
  set -e -o pipefail
  printf "Docker Hub read-access token: "
  read -s DOCKERHUB_PAT
  printf '\n'
  kubectl -n homelab create secret docker-registry stock-screener-registry \
    --docker-server=https://index.docker.io/v1/ \
    --docker-username=pikoters \
    --docker-password="$DOCKERHUB_PAT" \
    --dry-run=client -o yaml | kubectl apply -f -
  unset DOCKERHUB_PAT
)
```

Both the scheduled job and test Pod reference this Secret. If the repository is
public, the pull Secret is not required; remove its `imagePullSecrets` entry
from the manifest you apply.

The universe, score threshold, result count, and green-candle filter can be
adjusted in the manifest's ConfigMap. Run a one-off check with:

```bash
kubectl -n homelab create job --from=cronjob/stock-screener stock-screener-manual
kubectl -n homelab logs -f job/stock-screener-manual
```

For a standalone test Pod using the same image and configuration:

```bash
kubectl -n homelab delete pod stock-screener-test --ignore-not-found
kubectl -n homelab apply -f k8s/stock-screener-test-pod.yaml
kubectl -n homelab logs -f pod/stock-screener-test
```

The Pod exits after the screener and analysis complete. Delete it before
re-running the test.

## Notes
- `--max-symbols` controls number of tickers to query (default 200) for speed
- Each indicator has a simple bullish rule (e.g., RSI > 50, AO > 0, close > ALMA)
- Use `--indicators ""` to skip all indicators (debug mode)

## Risk-Reward (RR) customization

- CLI flag: pass `--rr-ratio` to `stocks_screener.py` to set the reward-to-risk multiple (default `3.0`).
- API: `GET /api/analysis/<ticker>?rr_ratio=2.5` returns analysis using a 1:2.5 RR. `POST /api/screen` accepts `rr_ratio` in the JSON body to screen with a custom RR.

## Running tests

Install test dependencies and run pytest:

```bash
python3 -m pip install -r requirements.txt
python3 -m pytest -q
```

## Market context and rule-based trade plans

Use [trade_analysis.py](trade_analysis.py) to fetch fresh daily history,
calculate the selected indicators, and produce a structured long pullback plan.
The current project plan uses the highest available EMA100/EMA200 below the
latest close as the limit entry, one ATR below entry as the stop, and a 1:3
risk/reward initial target.

```python
from trade_analysis import augment_screener_results, fetch_ticker_context

context = fetch_ticker_context("AAPL", start="2025-01-01", rr_ratio=3.0)
print(context["plan"])
history_with_indicators = context["history"]

selected = augment_screener_results(
  "screener_results.csv",
  min_score=5,
  top_n=10,
  start="2025-01-01",
)
print(selected[["ticker", "entry", "stop", "target", "actionable"]])
```

Pass `tickers=["AAPL", "MSFT"]` to `augment_screener_results` to choose
symbols explicitly instead of selecting them by score. The returned rows retain
the original screener data and append fresh price, indicator, signal, and plan
columns; `fetch_ticker_context` additionally returns the full enriched history.
