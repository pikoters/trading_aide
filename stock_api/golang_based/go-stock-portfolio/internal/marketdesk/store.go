package marketdesk

import (
	"context"
	"time"

	"pikoters.info.mytrading/internal/marketdata"
)

// SavedDataStore defines the saved PostgreSQL-backed capabilities used by the
// HTTP layer. Implementations must honor the supplied context for database work.
type SavedDataStore interface {
	// Ping checks whether the persistence adapter is available.
	Ping(context.Context) error
	// ListScreenerRuns returns recent run summaries, limited by the caller.
	ListScreenerRuns(context.Context, int) ([]ScreenerRun, error)
	// LoadScreenerResults loads a named run, or the latest run when runID is empty.
	LoadScreenerResults(context.Context, string, int) (ScreenerRun, []ScreenerResult, error)
	// ListAnalysisRuns returns recent analysis summaries, limited by the caller.
	ListAnalysisRuns(context.Context, int) ([]AnalysisRun, error)
	// LoadAnalysisResults loads a named run, or the latest run when runID is empty.
	LoadAnalysisResults(context.Context, string, int) (AnalysisRun, []AnalysisResult, error)
	// LoadTickerAnalysis loads the latest ticker snapshot, optionally scoped to a screener run.
	LoadTickerAnalysis(context.Context, string, string) (AnalysisSnapshot, error)
	// ListPortfolioPositions returns all persisted portfolio positions.
	ListPortfolioPositions(context.Context) ([]Position, error)
	// CreatePortfolioPosition persists one holding and returns its stored values.
	CreatePortfolioPosition(context.Context, Position) (Position, error)
}

// ScreenerRun summarizes one persisted batch screening operation.
type ScreenerRun struct {
	RunID           string
	StartedAt       time.Time
	FinishedAt      time.Time
	Universe        string
	SelectedSymbols string
	ResultCount     int
}

// ScreenerResult is a ticker's screening snapshot, including indicator values
// and the advisory levels captured with its run.
type ScreenerResult struct {
	Ticker        string
	RunID         string
	AsOf          string
	Open          *float64
	High          *float64
	Low           *float64
	Close         float64
	ChangePercent *float64
	Volume        *float64
	Indicators    map[string]float64
	Signals       map[string]bool
	Score         int
	Stop          *float64
	Target        *float64
	RRRatio       float64
}

// AnalysisRun records analysis lifecycle and expected/completed result counts.
type AnalysisRun struct {
	AnalysisRunID    string
	ScreenerRunID    *string
	StartedAt        time.Time
	FinishedAt       *time.Time
	Status           string
	SourceFile       string
	RequestedTickers string
	ResultCount      int
	ExpectedCount    int
}

// TradePlan contains advisory entry, stop, target, and risk/reward details.
// Actionable describes whether the plan's required data and levels are usable;
// it is not an instruction to submit an order.
type TradePlan struct {
	Setup        string
	Actionable   bool
	EntryRule    string
	Entry        *float64
	EntrySupport string
	Stop         *float64
	Target       *float64
	RiskPerShare *float64
	RRRatio      float64
	DataNote     string
}

// AnalysisResult is one ticker's saved analysis, linked to its source run when
// that relationship is known.
type AnalysisResult struct {
	AnalysisRunID string
	ScreenerRunID *string
	Ticker        string
	AsOf          string
	Close         *float64
	Score         int
	Entry         *float64
	EntrySupport  string
	Stop          *float64
	Target        *float64
	RiskPerShare  *float64
	Actionable    bool
	Indicators    map[string]float64
	Signals       map[string]bool
	Plan          TradePlan
	StrategyPlans map[string]map[string]any
}

// AnalysisSnapshot combines one saved ticker summary with its history and plans.
type AnalysisSnapshot struct {
	Summary       ScreenerResult
	History       []marketdata.Bar
	Plan          TradePlan
	StrategyPlans map[string]map[string]any
	AnalysisRunID string
	ScreenerRunID *string
}

// Position is a portfolio holding and its persisted valuation fields.
type Position struct {
	Ticker       string
	Quantity     int
	AvgPrice     float64
	CurrentValue float64
	PnL          float64
}
