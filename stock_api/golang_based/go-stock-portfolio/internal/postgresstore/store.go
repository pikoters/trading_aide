package postgresstore

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"net"
	"net/url"
	"os"
	"strconv"
	"strings"
	"time"

	_ "github.com/jackc/pgx/v5/stdlib"
	"pikoters.info.mytrading/internal/marketdata"
	"pikoters.info.mytrading/internal/marketdesk"
)

// Store implements marketdesk.SavedDataStore using a bounded database/sql pool.
type Store struct {
	db *sql.DB
}

// OpenPostgresFromEnv validates DB_* settings, opens PostgreSQL, and verifies
// connectivity with a bounded startup ping.
func OpenPostgresFromEnv() (*Store, error) {
	host := strings.TrimSpace(os.Getenv("DB_HOST"))
	user := strings.TrimSpace(os.Getenv("DB_USER"))
	password := os.Getenv("DB_PASSWORD")
	database := strings.TrimSpace(os.Getenv("DB_NAME"))
	port := strings.TrimSpace(os.Getenv("DB_PORT"))
	if host == "" || user == "" || password == "" || database == "" {
		return nil, errors.New("DB_HOST, DB_USER, DB_PASSWORD, and DB_NAME are required")
	}
	if port == "" {
		port = "5432"
	}
	if _, err := strconv.Atoi(port); err != nil {
		return nil, errors.New("DB_PORT must be a valid port number")
	}
	sslMode := strings.TrimSpace(os.Getenv("DB_SSLMODE"))
	if sslMode == "" {
		sslMode = "prefer"
	}
	connectionURL := &url.URL{
		Scheme: "postgres",
		User:   url.UserPassword(user, password),
		Host:   net.JoinHostPort(host, port),
		Path:   "/" + database,
	}
	query := connectionURL.Query()
	query.Set("sslmode", sslMode)
	connectionURL.RawQuery = query.Encode()

	databaseHandle, err := sql.Open("pgx", connectionURL.String())
	if err != nil {
		return nil, fmt.Errorf("open PostgreSQL connection: %w", err)
	}
	databaseHandle.SetMaxOpenConns(8)
	databaseHandle.SetMaxIdleConns(4)
	databaseHandle.SetConnMaxLifetime(30 * time.Minute)
	ctx, cancel := context.WithTimeout(context.Background(), 8*time.Second)
	defer cancel()
	if err := databaseHandle.PingContext(ctx); err != nil {
		databaseHandle.Close()
		return nil, fmt.Errorf("connect to PostgreSQL: %w", err)
	}
	return &Store{db: databaseHandle}, nil
}

// Close releases the database pool.
func (store *Store) Close() error {
	return store.db.Close()
}

// Ping checks database connectivity using the caller's context.
func (store *Store) Ping(ctx context.Context) error {
	return store.db.PingContext(ctx)
}

// ListPortfolioPositions returns persisted holdings ordered by position ID.
func (store *Store) ListPortfolioPositions(ctx context.Context) ([]marketdesk.Position, error) {
	rows, err := store.db.QueryContext(ctx, `
		SELECT ticker, quantity, avg_price, current_value, pnl
		FROM public.portfolio_positions
		ORDER BY position_id`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	positions := make([]marketdesk.Position, 0)
	for rows.Next() {
		var position marketdesk.Position
		if err := rows.Scan(
			&position.Ticker, &position.Quantity, &position.AvgPrice,
			&position.CurrentValue, &position.PnL,
		); err != nil {
			return nil, err
		}
		positions = append(positions, position)
	}
	return positions, rows.Err()
}

// CreatePortfolioPosition persists a holding and returns its calculated value.
func (store *Store) CreatePortfolioPosition(ctx context.Context, position marketdesk.Position) (marketdesk.Position, error) {
	err := store.db.QueryRowContext(ctx, `
		INSERT INTO public.portfolio_positions (ticker, quantity, avg_price, current_value, pnl)
		VALUES ($1, $2, $3, $2 * $3, 0)
		RETURNING ticker, quantity, avg_price, current_value, pnl`,
		position.Ticker, position.Quantity, position.AvgPrice,
	).Scan(
		&position.Ticker, &position.Quantity, &position.AvgPrice,
		&position.CurrentValue, &position.PnL,
	)
	if err != nil {
		return marketdesk.Position{}, err
	}
	return position, nil
}

// ListScreenerRuns returns recent screening-run summaries, newest first.
func (store *Store) ListScreenerRuns(ctx context.Context, limit int) ([]marketdesk.ScreenerRun, error) {
	rows, err := store.db.QueryContext(ctx, `
		SELECT run_id::text, started_at, finished_at, universe, selected_symbols, result_count
		FROM public.screener_runs
		ORDER BY started_at DESC, run_id DESC
		LIMIT $1`, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	result := make([]marketdesk.ScreenerRun, 0)
	for rows.Next() {
		var run marketdesk.ScreenerRun
		if err := rows.Scan(&run.RunID, &run.StartedAt, &run.FinishedAt, &run.Universe, &run.SelectedSymbols, &run.ResultCount); err != nil {
			return nil, err
		}
		result = append(result, run)
	}
	return result, rows.Err()
}

// LoadScreenerResults returns the selected run and its highest-scoring rows.
// An empty runID selects the most recent run; a missing run returns an empty
// run value and no rows.
func (store *Store) LoadScreenerResults(ctx context.Context, runID string, limit int) (marketdesk.ScreenerRun, []marketdesk.ScreenerResult, error) {
	var run marketdesk.ScreenerRun
	var err error
	if runID == "" {
		err = store.db.QueryRowContext(ctx, `
			SELECT run_id::text, started_at, finished_at, universe, selected_symbols, result_count
			FROM public.screener_runs
			ORDER BY started_at DESC, run_id DESC LIMIT 1`).Scan(
			&run.RunID, &run.StartedAt, &run.FinishedAt, &run.Universe, &run.SelectedSymbols, &run.ResultCount,
		)
	} else {
		err = store.db.QueryRowContext(ctx, `
			SELECT run_id::text, started_at, finished_at, universe, selected_symbols, result_count
			FROM public.screener_runs WHERE run_id = $1::uuid`, runID).Scan(
			&run.RunID, &run.StartedAt, &run.FinishedAt, &run.Universe, &run.SelectedSymbols, &run.ResultCount,
		)
	}
	if errors.Is(err, sql.ErrNoRows) {
		return run, nil, nil
	}
	if err != nil {
		return run, nil, err
	}

	rows, err := store.db.QueryContext(ctx, `
		SELECT to_jsonb(result_row)
		FROM public.screener_results AS result_row
		WHERE run_id = $1::uuid
		ORDER BY score DESC, ticker ASC
		LIMIT $2`, run.RunID, limit)
	if err != nil {
		return run, nil, err
	}
	defer rows.Close()
	results := make([]marketdesk.ScreenerResult, 0)
	for rows.Next() {
		var payload []byte
		if err := rows.Scan(&payload); err != nil {
			return run, nil, err
		}
		var values map[string]any
		if err := json.Unmarshal(payload, &values); err != nil {
			return run, nil, err
		}
		results = append(results, screenerResultFromJSON(run.RunID, values))
	}
	return run, results, rows.Err()
}

// ListAnalysisRuns returns recent analysis lifecycle summaries, newest first.
func (store *Store) ListAnalysisRuns(ctx context.Context, limit int) ([]marketdesk.AnalysisRun, error) {
	rows, err := store.db.QueryContext(ctx, `
		SELECT ar.analysis_run_id::text,
		       COALESCE(ar.screener_run_id::text, (
		           SELECT x.screener_run_id::text FROM public.analysis_results x
		           WHERE x.analysis_run_id = ar.analysis_run_id AND x.screener_run_id IS NOT NULL
		           LIMIT 1
		       )),
		       ar.started_at, ar.finished_at, ar.status, ar.source_file,
		       ar.requested_tickers, ar.result_count, ar.expected_count
		FROM public.analysis_runs ar
		ORDER BY ar.started_at DESC, ar.analysis_run_id DESC
		LIMIT $1`, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	result := make([]marketdesk.AnalysisRun, 0)
	for rows.Next() {
		var run marketdesk.AnalysisRun
		if err := rows.Scan(
			&run.AnalysisRunID, &run.ScreenerRunID, &run.StartedAt, &run.FinishedAt,
			&run.Status, &run.SourceFile, &run.RequestedTickers, &run.ResultCount,
			&run.ExpectedCount,
		); err != nil {
			return nil, err
		}
		result = append(result, run)
	}
	return result, rows.Err()
}

// LoadAnalysisResults returns one run and its actionable ticker results first.
// An empty runID selects the most recent run; a missing run returns an empty
// run value and no rows.
func (store *Store) LoadAnalysisResults(ctx context.Context, runID string, limit int) (marketdesk.AnalysisRun, []marketdesk.AnalysisResult, error) {
	var run marketdesk.AnalysisRun
	var err error
	if runID == "" {
		err = store.db.QueryRowContext(ctx, `
			SELECT analysis_run_id::text, screener_run_id::text, started_at,
			       finished_at, status, source_file, requested_tickers,
			       result_count, expected_count
			FROM public.analysis_runs
			ORDER BY started_at DESC, analysis_run_id DESC LIMIT 1`).Scan(
			&run.AnalysisRunID, &run.ScreenerRunID, &run.StartedAt, &run.FinishedAt,
			&run.Status, &run.SourceFile, &run.RequestedTickers, &run.ResultCount,
			&run.ExpectedCount,
		)
	} else {
		err = store.db.QueryRowContext(ctx, `
			SELECT analysis_run_id::text, screener_run_id::text, started_at,
			       finished_at, status, source_file, requested_tickers,
			       result_count, expected_count
			FROM public.analysis_runs WHERE analysis_run_id = $1::uuid`, runID).Scan(
			&run.AnalysisRunID, &run.ScreenerRunID, &run.StartedAt, &run.FinishedAt,
			&run.Status, &run.SourceFile, &run.RequestedTickers, &run.ResultCount,
			&run.ExpectedCount,
		)
	}
	if errors.Is(err, sql.ErrNoRows) {
		return run, nil, nil
	}
	if err != nil {
		return run, nil, err
	}

	rows, err := store.db.QueryContext(ctx, `
		SELECT to_jsonb(result_row)
		FROM public.analysis_results AS result_row
		WHERE analysis_run_id = $1::uuid
		ORDER BY actionable DESC, ticker ASC
		LIMIT $2`, run.AnalysisRunID, limit)
	if err != nil {
		return run, nil, err
	}
	defer rows.Close()
	results := make([]marketdesk.AnalysisResult, 0)
	for rows.Next() {
		var payload []byte
		if err := rows.Scan(&payload); err != nil {
			return run, nil, err
		}
		var values map[string]any
		if err := json.Unmarshal(payload, &values); err != nil {
			return run, nil, err
		}
		results = append(results, savedAnalysisFromJSON(run.AnalysisRunID, values))
	}
	return run, results, rows.Err()
}

// LoadTickerAnalysis returns the latest saved ticker snapshot, optionally
// restricted to a screener run. It wraps marketdesk.ErrNotFound when absent.
func (store *Store) LoadTickerAnalysis(ctx context.Context, ticker, screenerRunID string) (marketdesk.AnalysisSnapshot, error) {
	query := `SELECT to_jsonb(result_row) FROM public.analysis_results AS result_row WHERE upper(ticker) = upper($1)`
	arguments := []any{ticker}
	if screenerRunID != "" {
		query += ` AND screener_run_id = $2::uuid`
		arguments = append(arguments, screenerRunID)
	}
	query += ` ORDER BY captured_at DESC LIMIT 1`
	var payload []byte
	if err := store.db.QueryRowContext(ctx, query, arguments...).Scan(&payload); err != nil {
		if errors.Is(err, sql.ErrNoRows) {
			return marketdesk.AnalysisSnapshot{}, fmt.Errorf("load analysis: %w", marketdesk.ErrNotFound)
		}
		return marketdesk.AnalysisSnapshot{}, err
	}
	var values map[string]any
	if err := json.Unmarshal(payload, &values); err != nil {
		return marketdesk.AnalysisSnapshot{}, err
	}
	response := analysisResponseFromJSON(values)
	history, err := store.loadTickerHistory(ctx, ticker)
	if err != nil {
		return marketdesk.AnalysisSnapshot{}, err
	}
	response.History = history
	if len(response.History) == 0 && response.Summary.Close != 0 {
		asOf, _ := time.Parse("2006-01-02", response.Summary.AsOf)
		response.History = []marketdata.Bar{{Date: asOf, Close: response.Summary.Close}}
	}
	return response, nil
}

func (store *Store) loadTickerHistory(ctx context.Context, ticker string) ([]marketdata.Bar, error) {
	rows, err := store.db.QueryContext(ctx, `
		SELECT date, close
		FROM (
			SELECT result_row.date, result_row.close,
			       row_number() OVER (PARTITION BY result_row.date ORDER BY run.started_at DESC, result_row.run_id DESC) AS row_number
			FROM public.screener_results AS result_row
			JOIN public.screener_runs AS run USING (run_id)
			WHERE upper(result_row.ticker) = upper($1)
		) AS dated_results
		WHERE row_number = 1
		ORDER BY date DESC
		LIMIT 260`, ticker)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	reverse := make([]marketdata.Bar, 0, 260)
	for rows.Next() {
		var bar marketdata.Bar
		if err := rows.Scan(&bar.Date, &bar.Close); err != nil {
			return nil, err
		}
		reverse = append(reverse, bar)
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}
	for left, right := 0, len(reverse)-1; left < right; left, right = left+1, right-1 {
		reverse[left], reverse[right] = reverse[right], reverse[left]
	}
	return reverse, nil
}

func screenerResultFromJSON(runID string, values map[string]any) marketdesk.ScreenerResult {
	result := marketdesk.ScreenerResult{
		Ticker: rawString(values["ticker"]), RunID: runID, AsOf: rawString(values["date"]),
		Indicators: make(map[string]float64), Signals: make(map[string]bool),
		Score: int(rawFloat(values["score"])), RRRatio: rawFloat(values["rr_ratio"]),
		Close: rawFloat(values["close"]), Open: rawFloatPointer(values["open"]),
		High: rawFloatPointer(values["high"]), Low: rawFloatPointer(values["low"]),
		Volume: rawFloatPointer(values["volume"]), Stop: rawFloatPointer(values["stop"]),
		Target: rawFloatPointer(values["target"]),
	}
	if parsed, err := time.Parse("2006-01-02T15:04:05Z", result.AsOf); err == nil {
		result.AsOf = parsed.Format("2006-01-02")
	}
	if parsed, err := time.Parse("2006-01-02", result.AsOf); err == nil {
		result.AsOf = parsed.Format("2006-01-02")
	}
	for _, name := range screenerIndicatorColumns {
		if value, ok := rawFloatOK(values[name]); ok {
			result.Indicators[name] = value
		}
	}
	for name, value := range values {
		if strings.HasSuffix(name, "_bull") || strings.HasSuffix(name, "_bear") || strings.Contains(name, "_cross_") || strings.Contains(name, "_above_") || strings.Contains(name, "_below_") {
			if signal, ok := value.(bool); ok {
				result.Signals[name] = signal
			}
		}
	}
	return result
}

func savedAnalysisFromJSON(runID string, values map[string]any) marketdesk.AnalysisResult {
	var screenerRunID *string
	if value := rawString(values["screener_run_id"]); value != "" {
		screenerRunID = &value
	}
	result := marketdesk.AnalysisResult{
		AnalysisRunID: runID, ScreenerRunID: screenerRunID, Ticker: rawString(values["ticker"]),
		AsOf: rawString(values["as_of"]), Close: rawFloatPointer(values["close"]),
		Entry: rawFloatPointer(values["entry"]), EntrySupport: rawString(values["entry_support"]),
		Stop: rawFloatPointer(values["stop"]), Target: rawFloatPointer(values["target"]),
		RiskPerShare: rawFloatPointer(values["risk_per_share"]),
		Actionable:   rawBool(values["actionable"]), Indicators: rawFloatMap(values["indicators"]),
		Signals: rawBoolMap(values["signals"]), Plan: rawTradePlan(values["plan"]),
		StrategyPlans: rawStrategyPlans(values["plan"]),
	}
	snapshot, _ := rawMap(values["screener_snapshot"])
	result.Score = int(rawFloat(snapshot["score"]))
	return result
}

func analysisResponseFromJSON(values map[string]any) marketdesk.AnalysisSnapshot {
	analysisRunID := rawString(values["analysis_run_id"])
	snapshot, _ := rawMap(values["screener_snapshot"])
	indicators := rawFloatMap(values["indicators"])
	signals := rawBoolMap(values["signals"])
	plan := rawTradePlan(values["plan"])
	strategyPlans := rawStrategyPlans(values["plan"])
	var screenerRunID *string
	if value := rawString(values["screener_run_id"]); value != "" {
		screenerRunID = &value
	}
	closeValue := rawFloat(values["close"])
	if value := rawFloatPointer(values["close"]); value != nil {
		closeValue = *value
	}
	ratio := rawFloat(plan.RRRatio)
	if ratio == 0 {
		ratio = rawFloat(snapshot["rr_ratio"])
	}
	stop, target := rawFloatPointer(values["stop"]), rawFloatPointer(values["target"])
	if stop == nil {
		stop = plan.Stop
	}
	if target == nil {
		target = plan.Target
	}
	result := marketdesk.ScreenerResult{
		Ticker: rawString(values["ticker"]), RunID: stringValue(screenerRunID), AsOf: rawString(values["as_of"]),
		Close: closeValue, Open: rawFloatPointer(values["open"]), High: rawFloatPointer(values["high"]),
		Low: rawFloatPointer(values["low"]), Volume: rawFloatPointer(values["volume"]),
		Indicators: indicators, Signals: signals, Score: int(rawFloat(snapshot["score"])),
		Stop: stop, Target: target, RRRatio: ratio,
	}
	return marketdesk.AnalysisSnapshot{
		Summary: result, Plan: plan,
		StrategyPlans: strategyPlans, AnalysisRunID: analysisRunID, ScreenerRunID: screenerRunID,
		History: make([]marketdata.Bar, 0),
	}
}

func rawStrategyPlans(value any) map[string]map[string]any {
	plan, ok := rawMap(value)
	if !ok {
		return nil
	}
	strategies, ok := rawMap(plan["strategies"])
	if !ok {
		return nil
	}
	result := make(map[string]map[string]any, len(strategies))
	for name, value := range strategies {
		if strategy, ok := rawMap(value); ok {
			result[name] = strategy
		}
	}
	return result
}

var screenerIndicatorColumns = []string{
	"ALMA", "MACDh_12_26_9", "AO", "PSARl_0.02_0.2", "EMA50", "EMA100", "EMA200",
	"SMA50", "SMA100", "SMA200", "BBM_20_2.0", "STOCHRSIk_14_14_3_3", "TEMA_21",
	"VolumeAvg20", "RSI_14", "ATRr_14", "CCI_20", "WILLR_14", "ADX_14", "OBV",
	"MOM_10", "ROC_12", "KCLe_20_2", "ISA_9", "ADOSC", "VPT",
}

func rawMap(value any) (map[string]any, bool) {
	result, ok := value.(map[string]any)
	return result, ok
}

func rawString(value any) string {
	result, _ := value.(string)
	return result
}

func rawFloat(value any) float64 {
	result, _ := rawFloatOK(value)
	return result
}

func rawFloatOK(value any) (float64, bool) {
	switch number := value.(type) {
	case float64:
		return number, true
	case json.Number:
		parsed, err := number.Float64()
		return parsed, err == nil
	case int:
		return float64(number), true
	default:
		return 0, false
	}
}

func rawFloatPointer(value any) *float64 {
	if result, ok := rawFloatOK(value); ok {
		return &result
	}
	return nil
}

func rawFloatMap(value any) map[string]float64 {
	result := make(map[string]float64)
	values, ok := rawMap(value)
	if !ok {
		return result
	}
	for key, item := range values {
		if number, valid := rawFloatOK(item); valid {
			result[key] = number
		}
	}
	return result
}

func rawBool(value any) bool {
	result, _ := value.(bool)
	return result
}

func rawBoolMap(value any) map[string]bool {
	result := make(map[string]bool)
	values, ok := rawMap(value)
	if !ok {
		return result
	}
	for key, item := range values {
		if signal, valid := item.(bool); valid {
			result[key] = signal
		}
	}
	return result
}

func rawTradePlan(value any) marketdesk.TradePlan {
	payload, ok := rawMap(value)
	if !ok {
		return marketdesk.TradePlan{}
	}
	return marketdesk.TradePlan{
		Setup: rawString(payload["setup"]), Actionable: rawBool(payload["actionable"]),
		EntryRule: rawString(payload["entry_rule"]), Entry: rawFloatPointer(payload["entry"]),
		EntrySupport: rawString(payload["entry_support"]), Stop: rawFloatPointer(payload["stop"]),
		Target: rawFloatPointer(payload["target"]), RiskPerShare: rawFloatPointer(payload["risk_per_share"]),
		RRRatio: rawFloat(payload["rr_ratio"]), DataNote: rawString(payload["data_note"]),
	}
}

func stringValue(value *string) string {
	if value == nil {
		return ""
	}
	return *value
}
