package web

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"pikoters.info.mytrading/internal/marketdesk"
)

type fakeMarketClient struct {
	barsByTicker map[string][]Bar
}

type fakeSavedDataStore struct {
	screenerRuns    []marketdesk.ScreenerRun
	screenerRun     marketdesk.ScreenerRun
	screenerResults []marketdesk.ScreenerResult
	analysisRuns    []marketdesk.AnalysisRun
	analysisRun     marketdesk.AnalysisRun
	analysisResults []marketdesk.AnalysisResult
	portfolio       []marketdesk.Position
	tickerAnalysis  marketdesk.AnalysisSnapshot
	requestedTicker string
	requestedRunID  string
}

func (store *fakeSavedDataStore) Ping(context.Context) error { return nil }

func (store *fakeSavedDataStore) ListPortfolioPositions(context.Context) ([]marketdesk.Position, error) {
	return store.portfolio, nil
}

func (store *fakeSavedDataStore) CreatePortfolioPosition(_ context.Context, position marketdesk.Position) (marketdesk.Position, error) {
	store.portfolio = append(store.portfolio, position)
	return position, nil
}

func (store *fakeSavedDataStore) ListScreenerRuns(context.Context, int) ([]marketdesk.ScreenerRun, error) {
	return store.screenerRuns, nil
}

func (store *fakeSavedDataStore) LoadScreenerResults(context.Context, string, int) (marketdesk.ScreenerRun, []marketdesk.ScreenerResult, error) {
	return store.screenerRun, store.screenerResults, nil
}

func (store *fakeSavedDataStore) ListAnalysisRuns(context.Context, int) ([]marketdesk.AnalysisRun, error) {
	return store.analysisRuns, nil
}

func (store *fakeSavedDataStore) LoadAnalysisResults(context.Context, string, int) (marketdesk.AnalysisRun, []marketdesk.AnalysisResult, error) {
	return store.analysisRun, store.analysisResults, nil
}

func (store *fakeSavedDataStore) LoadTickerAnalysis(_ context.Context, ticker, runID string) (marketdesk.AnalysisSnapshot, error) {
	store.requestedTicker, store.requestedRunID = ticker, runID
	return store.tickerAnalysis, nil
}

func (client fakeMarketClient) DailyHistory(_ context.Context, ticker string) ([]Bar, error) {
	bars, exists := client.barsByTicker[ticker]
	if !exists {
		return nil, context.DeadlineExceeded
	}
	return bars, nil
}

func makeTestBars(count int, firstClose float64) []Bar {
	bars := make([]Bar, count)
	for index := range bars {
		closeValue := firstClose + float64(index)
		bars[index] = Bar{
			Date: time.Date(2025, 1, 1, 0, 0, 0, 0, time.UTC).AddDate(0, 0, index),
			Open: closeValue - 0.5, High: closeValue + 1, Low: closeValue - 1,
			Close: closeValue, Volume: 1000 + float64(index),
		}
	}
	return bars
}

func TestMarketDataMapperPreservesBarValues(t *testing.T) {
	input := []Bar{{
		Date: time.Date(2025, 1, 2, 0, 0, 0, 0, time.UTC),
		Open: 10, High: 12, Low: 9, Close: 11, Volume: 1000,
	}}

	got := marketDataBarsModel(input)
	if len(got) != 1 || got[0].Date != input[0].Date ||
		got[0].Open != input[0].Open || got[0].High != input[0].High ||
		got[0].Low != input[0].Low || got[0].Close != input[0].Close ||
		got[0].Volume != input[0].Volume {
		t.Fatalf("market-data mapper changed bar values: %#v", got)
	}
}

func TestScreenHandlerReturnsSortedResultsAndFailures(t *testing.T) {
	client := fakeMarketClient{barsByTicker: map[string][]Bar{
		"AAA": makeTestBars(240, 20),
		"BBB": makeTestBars(240, 40),
	}}
	router := NewRouterWithMarketClient(client)
	request := httptest.NewRequest(http.MethodPost, "/api/screen", strings.NewReader(`{"symbols":["aaa","BBB","MISSING"],"rr_ratio":2.5}`))
	request.Header.Set("Content-Type", "application/json")
	response := httptest.NewRecorder()
	router.ServeHTTP(response, request)
	if response.Code != http.StatusOK {
		t.Fatalf("expected status 200, got %d: %s", response.Code, response.Body.String())
	}
	var payload struct {
		Results  []screenerResult `json:"results"`
		Failures []screenFailure  `json:"failures"`
	}
	if err := json.Unmarshal(response.Body.Bytes(), &payload); err != nil {
		t.Fatalf("decode screen response: %v", err)
	}
	if len(payload.Results) != 2 || payload.Results[0].Ticker != "BBB" {
		t.Fatalf("expected two score-sorted results, got %#v", payload.Results)
	}
	if len(payload.Failures) != 1 || payload.Failures[0].Ticker != "MISSING" {
		t.Fatalf("expected missing ticker failure, got %#v", payload.Failures)
	}
}

func TestScreenHandlerValidatesTickerLimit(t *testing.T) {
	router := NewRouterWithMarketClient(fakeMarketClient{})
	request := httptest.NewRequest(http.MethodPost, "/api/screen", strings.NewReader(`{"symbols":["bad ticker"]}`))
	request.Header.Set("Content-Type", "application/json")
	response := httptest.NewRecorder()
	router.ServeHTTP(response, request)
	if response.Code != http.StatusBadRequest {
		t.Fatalf("expected status 400, got %d", response.Code)
	}
}

func TestScreenHandlerRejectsOversizedRequestBody(t *testing.T) {
	router := NewRouterWithMarketClient(fakeMarketClient{})
	body := `{"symbols":["` + strings.Repeat("A", maxJSONBodyBytes) + `"]}`
	request := httptest.NewRequest(http.MethodPost, "/api/screen", strings.NewReader(body))
	request.Header.Set("Content-Type", "application/json")
	response := httptest.NewRecorder()
	router.ServeHTTP(response, request)
	if response.Code != http.StatusRequestEntityTooLarge {
		t.Fatalf("expected status 413, got %d: %s", response.Code, response.Body.String())
	}
}

func TestLiveAnalysisHandlerReturnsHistoryAndPlans(t *testing.T) {
	client := fakeMarketClient{barsByTicker: map[string][]Bar{"TEST": makeTestBars(260, 20)}}
	router := NewRouterWithMarketClient(client)
	request := httptest.NewRequest(http.MethodGet, "/api/market/analysis/test?rr_ratio=2", nil)
	response := httptest.NewRecorder()
	router.ServeHTTP(response, request)
	if response.Code != http.StatusOK {
		t.Fatalf("expected status 200, got %d: %s", response.Code, response.Body.String())
	}
	var payload analysisResponse
	if err := json.Unmarshal(response.Body.Bytes(), &payload); err != nil {
		t.Fatalf("decode analysis response: %v", err)
	}
	if payload.Summary.Ticker != "TEST" || len(payload.History) != 260 {
		t.Fatalf("unexpected analysis summary/history: %s, %d bars", payload.Summary.Ticker, len(payload.History))
	}
	if !payload.Plan.Actionable || payload.Plan.Target == nil || payload.Plan.RRRatio != 2 {
		t.Fatalf("expected actionable two-R plan, got %#v", payload.Plan)
	}
}

func TestScreenerResultsAreLoadedFromSavedRun(t *testing.T) {
	store := &fakeSavedDataStore{
		screenerRun:     marketdesk.ScreenerRun{RunID: "run-123", ResultCount: 1},
		screenerResults: []marketdesk.ScreenerResult{{Ticker: "AAPL", Close: 225, Score: 6}},
	}
	router := newRouter(fakeMarketClient{}, store)
	request := httptest.NewRequest(http.MethodGet, "/api/screen/results?run_id=run-123", nil)
	response := httptest.NewRecorder()
	router.ServeHTTP(response, request)
	if response.Code != http.StatusOK {
		t.Fatalf("expected status 200, got %d: %s", response.Code, response.Body.String())
	}
	var payload struct {
		RunID   string           `json:"run_id"`
		Results []screenerResult `json:"results"`
	}
	if err := json.Unmarshal(response.Body.Bytes(), &payload); err != nil {
		t.Fatalf("decode saved screen response: %v", err)
	}
	if payload.RunID != "run-123" || len(payload.Results) != 1 || payload.Results[0].Ticker != "AAPL" {
		t.Fatalf("unexpected saved screen payload: %#v", payload)
	}
}

func TestSavedAnalysisUsesSelectedScreenerRun(t *testing.T) {
	store := &fakeSavedDataStore{tickerAnalysis: marketdesk.AnalysisSnapshot{
		Summary: marketdesk.ScreenerResult{Ticker: "AAPL", Close: 225},
	}}
	router := newRouter(fakeMarketClient{}, store)
	request := httptest.NewRequest(http.MethodGet, "/api/analysis/aapl?screener_run_id=run-456", nil)
	response := httptest.NewRecorder()
	router.ServeHTTP(response, request)
	if response.Code != http.StatusOK {
		t.Fatalf("expected status 200, got %d: %s", response.Code, response.Body.String())
	}
	if store.requestedTicker != "AAPL" || store.requestedRunID != "run-456" {
		t.Fatalf("saved analysis query mismatch: ticker=%s run=%s", store.requestedTicker, store.requestedRunID)
	}
}

func TestSavedAnalysisResponseKeepsExistingJSONContract(t *testing.T) {
	runID := "screen-456"
	entry, stop, target, risk := 250.0, 246.0, 262.0, 4.0
	store := &fakeSavedDataStore{tickerAnalysis: marketdesk.AnalysisSnapshot{
		AnalysisRunID: "analysis-123",
		ScreenerRunID: &runID,
		Summary: marketdesk.ScreenerResult{
			Ticker: "AAPL", AsOf: "2026-10-09", Close: 258, Score: 6,
			Indicators: map[string]float64{"RSI_14": 61.5},
			Signals:    map[string]bool{"rsi_bull": true},
			Stop:       &stop, Target: &target,
		},
		Plan: marketdesk.TradePlan{
			Setup: "long_pullback", Actionable: true, Entry: &entry, Stop: &stop,
			Target: &target, RiskPerShare: &risk, RRRatio: 3,
		},
		StrategyPlans: map[string]map[string]any{
			"MAMA_daily": {"status": "ENTRY_TRIGGERED"},
		},
	}}
	router := newRouter(fakeMarketClient{}, store)
	response := httptest.NewRecorder()
	router.ServeHTTP(response, httptest.NewRequest(http.MethodGet, "/api/analysis/aapl", nil))
	if response.Code != http.StatusOK {
		t.Fatalf("expected status 200, got %d: %s", response.Code, response.Body.String())
	}

	var payload map[string]any
	if err := json.Unmarshal(response.Body.Bytes(), &payload); err != nil {
		t.Fatalf("decode saved analysis response: %v", err)
	}
	for _, key := range []string{
		"summary", "history", "plan", "risk_reward", "strategy_plans",
		"analysis_run_id", "screener_run_id",
	} {
		if _, exists := payload[key]; !exists {
			t.Errorf("response missing existing JSON field %q: %#v", key, payload)
		}
	}
	summary := payload["summary"].(map[string]any)
	plan := payload["plan"].(map[string]any)
	riskReward := payload["risk_reward"].(map[string]any)
	if summary["ticker"] != "AAPL" || summary["score"] != float64(6) ||
		plan["setup"] != "long_pullback" || plan["actionable"] != true ||
		riskReward["setup"] != "atr_risk_reward" ||
		riskReward["entry"] != float64(258) || riskReward["stop"] != float64(246) ||
		riskReward["target"] != float64(262) {
		t.Fatalf("unexpected API DTO mapping: %#v", payload)
	}
}

func TestAnalysisRunsExposeProgressAndScreenerRun(t *testing.T) {
	screenerRunID := "screen-456"
	store := &fakeSavedDataStore{
		analysisRuns: []marketdesk.AnalysisRun{{
			AnalysisRunID: "analysis-123",
			ScreenerRunID: &screenerRunID,
			Status:        "running",
			ResultCount:   3,
			ExpectedCount: 12,
		}},
	}
	router := newRouter(fakeMarketClient{}, store)
	request := httptest.NewRequest(http.MethodGet, "/api/analysis/runs?limit=50", nil)
	response := httptest.NewRecorder()
	router.ServeHTTP(response, request)
	if response.Code != http.StatusOK {
		t.Fatalf("expected status 200, got %d: %s", response.Code, response.Body.String())
	}

	var payload struct {
		Runs []analysisRun `json:"runs"`
	}
	if err := json.Unmarshal(response.Body.Bytes(), &payload); err != nil {
		t.Fatalf("decode analysis runs response: %v", err)
	}
	if len(payload.Runs) != 1 || payload.Runs[0].Status != "running" ||
		payload.Runs[0].ResultCount != 3 || payload.Runs[0].ExpectedCount != 12 ||
		payload.Runs[0].ScreenerRunID == nil || *payload.Runs[0].ScreenerRunID != screenerRunID {
		t.Fatalf("unexpected analysis progress response: %#v", payload.Runs)
	}
}

func TestPersistedRoutesRequirePostgresStore(t *testing.T) {
	router := NewRouterWithMarketClient(fakeMarketClient{})
	request := httptest.NewRequest(http.MethodGet, "/api/screen/runs", nil)
	response := httptest.NewRecorder()
	router.ServeHTTP(response, request)
	if response.Code != http.StatusServiceUnavailable {
		t.Fatalf("expected status 503, got %d", response.Code)
	}
}

func TestPortfolioPositionsPersistThroughConfiguredStore(t *testing.T) {
	store := &fakeSavedDataStore{}
	router := newRouter(fakeMarketClient{}, store)
	body := `{"ticker":"AAPL","quantity":2,"avg_price":100}`

	createRequest := httptest.NewRequest(http.MethodPost, "/portfolio", strings.NewReader(body))
	createRequest.Header.Set("Content-Type", "application/json")
	createResponse := httptest.NewRecorder()
	router.ServeHTTP(createResponse, createRequest)
	if createResponse.Code != http.StatusCreated {
		t.Fatalf("expected status 201, got %d: %s", createResponse.Code, createResponse.Body.String())
	}

	listResponse := httptest.NewRecorder()
	router.ServeHTTP(listResponse, httptest.NewRequest(http.MethodGet, "/portfolio", nil))
	if listResponse.Code != http.StatusOK {
		t.Fatalf("expected status 200, got %d: %s", listResponse.Code, listResponse.Body.String())
	}
	var payload struct {
		Positions []Position `json:"positions"`
	}
	if err := json.Unmarshal(listResponse.Body.Bytes(), &payload); err != nil {
		t.Fatalf("decode portfolio response: %v", err)
	}
	if len(payload.Positions) != 1 || payload.Positions[0].CurrentValue != 200 {
		t.Fatalf("expected persisted position with computed value, got %#v", payload.Positions)
	}
}

func TestPortfolioRequiresConfiguredStore(t *testing.T) {
	router := NewRouterWithMarketClient(fakeMarketClient{})
	response := httptest.NewRecorder()
	router.ServeHTTP(response, httptest.NewRequest(http.MethodGet, "/portfolio", nil))
	if response.Code != http.StatusServiceUnavailable {
		t.Fatalf("expected status 503, got %d", response.Code)
	}
}
