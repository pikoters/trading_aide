package web

import (
	"time"

	"pikoters.info.mytrading/internal/marketanalysis"
	"pikoters.info.mytrading/internal/marketdata"
	"pikoters.info.mytrading/internal/marketdesk"
)

type savedDataStore = marketdesk.SavedDataStore

type screenerRun struct {
	RunID           string `json:"run_id"`
	StartedAt       string `json:"started_at"`
	FinishedAt      string `json:"finished_at"`
	Universe        string `json:"universe"`
	SelectedSymbols string `json:"selected_symbols"`
	ResultCount     int    `json:"result_count"`
}

type analysisRun struct {
	AnalysisRunID    string  `json:"analysis_run_id"`
	ScreenerRunID    *string `json:"screener_run_id"`
	StartedAt        string  `json:"started_at"`
	FinishedAt       *string `json:"finished_at"`
	Status           string  `json:"status"`
	SourceFile       string  `json:"source_file"`
	RequestedTickers string  `json:"requested_tickers"`
	ResultCount      int     `json:"result_count"`
	ExpectedCount    int     `json:"expected_count"`
}

type savedAnalysisResult struct {
	AnalysisRunID string                    `json:"analysis_run_id"`
	ScreenerRunID *string                   `json:"screener_run_id"`
	Ticker        string                    `json:"ticker"`
	AsOf          string                    `json:"as_of"`
	Close         *float64                  `json:"close"`
	Score         int                       `json:"score"`
	Entry         *float64                  `json:"entry"`
	EntrySupport  string                    `json:"entry_support"`
	Stop          *float64                  `json:"stop"`
	Target        *float64                  `json:"target"`
	RiskPerShare  *float64                  `json:"risk_per_share"`
	Actionable    bool                      `json:"actionable"`
	Indicators    map[string]float64        `json:"indicators"`
	Signals       map[string]bool           `json:"signals"`
	Plan          tradePlan                 `json:"plan"`
	StrategyPlans map[string]map[string]any `json:"strategy_plans,omitempty"`
}

func screenerRunDTO(run marketdesk.ScreenerRun) screenerRun {
	return screenerRun{
		RunID: run.RunID, StartedAt: run.StartedAt.Format(time.RFC3339Nano),
		FinishedAt: run.FinishedAt.Format(time.RFC3339Nano), Universe: run.Universe,
		SelectedSymbols: run.SelectedSymbols, ResultCount: run.ResultCount,
	}
}

func analysisRunDTO(run marketdesk.AnalysisRun) analysisRun {
	result := analysisRun{
		AnalysisRunID: run.AnalysisRunID, ScreenerRunID: run.ScreenerRunID,
		StartedAt: run.StartedAt.Format(time.RFC3339Nano), Status: run.Status,
		SourceFile: run.SourceFile, RequestedTickers: run.RequestedTickers,
		ResultCount: run.ResultCount, ExpectedCount: run.ExpectedCount,
	}
	if run.FinishedAt != nil {
		finishedAt := run.FinishedAt.Format(time.RFC3339Nano)
		result.FinishedAt = &finishedAt
	}
	return result
}

func screenerResultDTO(result marketdesk.ScreenerResult) screenerResult {
	return screenerResult{
		Ticker: result.Ticker, RunID: result.RunID, AsOf: result.AsOf,
		Open: result.Open, High: result.High, Low: result.Low, Close: result.Close,
		ChangePercent: result.ChangePercent, Volume: result.Volume,
		Indicators: result.Indicators, Signals: result.Signals, Score: result.Score,
		Stop: result.Stop, Target: result.Target, RRRatio: result.RRRatio,
	}
}

func analysisResultDTO(result marketdesk.AnalysisResult) savedAnalysisResult {
	return savedAnalysisResult{
		AnalysisRunID: result.AnalysisRunID, ScreenerRunID: result.ScreenerRunID,
		Ticker: result.Ticker, AsOf: result.AsOf, Close: result.Close, Score: result.Score,
		Entry: result.Entry, EntrySupport: result.EntrySupport, Stop: result.Stop,
		Target: result.Target, RiskPerShare: result.RiskPerShare,
		Actionable: result.Actionable, Indicators: result.Indicators, Signals: result.Signals,
		Plan: tradePlanDTO(result.Plan), StrategyPlans: result.StrategyPlans,
	}
}

func tradePlanDTO(plan marketdesk.TradePlan) tradePlan {
	return tradePlan{
		Setup: plan.Setup, Actionable: plan.Actionable, EntryRule: plan.EntryRule,
		Entry: plan.Entry, EntrySupport: plan.EntrySupport, Stop: plan.Stop,
		Target: plan.Target, RiskPerShare: plan.RiskPerShare,
		RRRatio: plan.RRRatio, DataNote: plan.DataNote,
	}
}

func analysisResponseDTO(snapshot marketdesk.AnalysisSnapshot) analysisResponse {
	result := screenerResultDTO(snapshot.Summary)
	history := make([]Bar, len(snapshot.History))
	for index, bar := range snapshot.History {
		history[index] = Bar{
			Date: bar.Date, Open: bar.Open, High: bar.High, Low: bar.Low,
			Close: bar.Close, Volume: bar.Volume,
		}
	}
	return analysisResponse{
		Summary: result, History: history, Plan: tradePlanDTO(snapshot.Plan),
		RiskReward:    tradePlanDTO(marketanalysis.BuildRiskRewardPlan(snapshot.Summary)),
		StrategyPlans: snapshot.StrategyPlans,
		AnalysisRunID: snapshot.AnalysisRunID, ScreenerRunID: snapshot.ScreenerRunID,
	}
}

func positionDTO(position marketdesk.Position) Position {
	return Position{
		Ticker: position.Ticker, Quantity: position.Quantity, AvgPrice: position.AvgPrice,
		CurrentValue: position.CurrentValue, PnL: position.PnL,
	}
}

func positionModel(position Position) marketdesk.Position {
	return marketdesk.Position{
		Ticker: position.Ticker, Quantity: position.Quantity, AvgPrice: position.AvgPrice,
		CurrentValue: position.CurrentValue, PnL: position.PnL,
	}
}

func marketDataBarsDTO(bars []marketdata.Bar) []Bar {
	result := make([]Bar, len(bars))
	for index, bar := range bars {
		result[index] = Bar{
			Date: bar.Date, Open: bar.Open, High: bar.High, Low: bar.Low,
			Close: bar.Close, Volume: bar.Volume,
		}
	}
	return result
}

func marketDataBarsModel(bars []Bar) []marketdata.Bar {
	result := make([]marketdata.Bar, len(bars))
	for index, bar := range bars {
		result[index] = marketdata.Bar{
			Date: bar.Date, Open: bar.Open, High: bar.High, Low: bar.Low,
			Close: bar.Close, Volume: bar.Volume,
		}
	}
	return result
}
