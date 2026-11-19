package web

import (
	"errors"
	"math"
	"net/http"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"sync"

	"github.com/gin-gonic/gin"
	"pikoters.info.mytrading/internal/marketanalysis"
	"pikoters.info.mytrading/internal/marketdesk"
)

const maxScreenSymbols = 50

var tickerPattern = regexp.MustCompile(`^[A-Z0-9^=.-]{1,20}$`)

// screenRequest is the bounded live-screen endpoint input. An omitted or zero
// rr_ratio defaults to 3; symbols are limited to maxScreenSymbols.
type screenRequest struct {
	Symbols   []string `json:"symbols"`
	RRRatio   float64  `json:"rr_ratio"`
	GreenOnly bool     `json:"green_only"`
	Above     []string `json:"above"`
	AboveMode string   `json:"above_mode"`
	MinScore  *int     `json:"min_score"`
}

type screenerResult struct {
	Ticker        string             `json:"ticker"`
	RunID         string             `json:"run_id,omitempty"`
	AsOf          string             `json:"as_of"`
	Open          *float64           `json:"open"`
	High          *float64           `json:"high"`
	Low           *float64           `json:"low"`
	Close         float64            `json:"close"`
	ChangePercent *float64           `json:"change_percent"`
	Volume        *float64           `json:"volume"`
	Indicators    map[string]float64 `json:"indicators"`
	Signals       map[string]bool    `json:"signals"`
	Score         int                `json:"score"`
	Stop          *float64           `json:"stop"`
	Target        *float64           `json:"target"`
	RRRatio       float64            `json:"rr_ratio"`
}

type tradePlan struct {
	Setup        string   `json:"setup"`
	Actionable   bool     `json:"actionable"`
	EntryRule    string   `json:"entry_rule"`
	Entry        *float64 `json:"entry"`
	EntrySupport string   `json:"entry_support,omitempty"`
	Stop         *float64 `json:"stop"`
	Target       *float64 `json:"target"`
	RiskPerShare *float64 `json:"risk_per_share"`
	RRRatio      float64  `json:"rr_ratio"`
	DataNote     string   `json:"data_note,omitempty"`
}

// analysisResponse is the JSON contract for a live ticker analysis request.
type analysisResponse struct {
	Summary       screenerResult            `json:"summary"`
	History       []Bar                     `json:"history"`
	Plan          tradePlan                 `json:"plan"`
	RiskReward    tradePlan                 `json:"risk_reward"`
	StrategyPlans map[string]map[string]any `json:"strategy_plans,omitempty"`
	AnalysisRunID string                    `json:"analysis_run_id,omitempty"`
	ScreenerRunID *string                   `json:"screener_run_id,omitempty"`
}

type screenFailure struct {
	Ticker string `json:"ticker"`
	Error  string `json:"error"`
}

// screenHandler validates a bounded symbol list, fetches ticker histories with
// at most eight workers, and returns sorted results plus per-ticker failures.
func screenHandler(client marketHistoryProvider) gin.HandlerFunc {
	return func(c *gin.Context) {
		c.Request.Body = http.MaxBytesReader(c.Writer, c.Request.Body, maxJSONBodyBytes)
		var request screenRequest
		if err := c.ShouldBindJSON(&request); err != nil {
			var bodyTooLarge *http.MaxBytesError
			if errors.As(err, &bodyTooLarge) {
				c.JSON(http.StatusRequestEntityTooLarge, gin.H{"error": "request body exceeds 64 KiB"})
				return
			}
			c.JSON(http.StatusBadRequest, gin.H{"error": "invalid JSON request"})
			return
		}
		if len(request.Symbols) == 0 {
			c.JSON(http.StatusBadRequest, gin.H{"error": "provide at least one ticker in symbols"})
			return
		}
		if len(request.Symbols) > maxScreenSymbols {
			c.JSON(http.StatusBadRequest, gin.H{"error": "screen up to 50 tickers per request"})
			return
		}
		ratio := request.RRRatio
		if ratio == 0 {
			ratio = 3
		}
		if !isFinite(ratio) || ratio <= 0 || ratio > 20 {
			c.JSON(http.StatusBadRequest, gin.H{"error": "rr_ratio must be greater than 0 and no more than 20"})
			return
		}
		mode := strings.ToLower(strings.TrimSpace(request.AboveMode))
		if mode == "" {
			mode = "any"
		}
		if mode != "any" && mode != "all" {
			c.JSON(http.StatusBadRequest, gin.H{"error": "above_mode must be any or all"})
			return
		}
		above, err := normalizeAbove(request.Above)
		if err != nil {
			c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
			return
		}

		symbols, err := normalizeSymbols(request.Symbols)
		if err != nil {
			c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
			return
		}

		type outcome struct {
			result  marketdesk.ScreenerResult
			failure *screenFailure
		}
		outcomes := make(chan outcome, len(symbols))
		jobs := make(chan string)
		workerCount := min(8, len(symbols))
		var workers sync.WaitGroup
		for range workerCount {
			workers.Add(1)
			go func() {
				defer workers.Done()
				for ticker := range jobs {
					bars, fetchErr := client.DailyHistory(c.Request.Context(), ticker)
					if fetchErr != nil {
						outcomes <- outcome{failure: &screenFailure{Ticker: ticker, Error: fetchErr.Error()}}
						continue
					}
					result := marketanalysis.BuildScreenerResult(
						ticker, marketDataBarsModel(bars), ratio,
					)
					if request.GreenOnly && (result.Open == nil || result.Close <= *result.Open) {
						continue
					}
					if !matchesAbove(result.Indicators, result.Close, above, mode) {
						continue
					}
					if request.MinScore != nil && result.Score < *request.MinScore {
						continue
					}
					outcomes <- outcome{result: result}
				}
			}()
		}
		go func() {
			for _, ticker := range symbols {
				jobs <- ticker
			}
			close(jobs)
			workers.Wait()
			close(outcomes)
		}()

		results := make([]screenerResult, 0, len(symbols))
		failures := make([]screenFailure, 0)
		for item := range outcomes {
			if item.failure != nil {
				failures = append(failures, *item.failure)
				continue
			}
			results = append(results, screenerResultDTO(item.result))
		}
		if len(results) == 0 && len(failures) > 0 {
			c.JSON(http.StatusBadGateway, gin.H{"error": "all ticker data requests failed", "failures": failures})
			return
		}
		sort.Slice(results, func(left, right int) bool {
			if results[left].Score == results[right].Score {
				return results[left].Close > results[right].Close
			}
			return results[left].Score > results[right].Score
		})
		c.JSON(http.StatusOK, gin.H{
			"results":        results,
			"total_screened": len(symbols),
			"returned":       len(results),
			"failures":       failures,
			"criteria":       gin.H{"symbols": symbols, "rr_ratio": ratio, "green_only": request.GreenOnly, "above": above, "above_mode": mode},
		})
	}
}

// analysisHandler returns the latest live market context and advisory plans
// for one ticker. It does not read or write saved analysis records.
func analysisHandler(client marketHistoryProvider) gin.HandlerFunc {
	return func(c *gin.Context) {
		tickers, err := normalizeSymbols([]string{c.Param("ticker")})
		if err != nil {
			c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
			return
		}
		ratio := 3.0
		if rawRatio := c.Query("rr_ratio"); rawRatio != "" {
			ratio, err = strconv.ParseFloat(rawRatio, 64)
			if err != nil || !isFinite(ratio) || ratio <= 0 || ratio > 20 {
				c.JSON(http.StatusBadRequest, gin.H{"error": "rr_ratio must be greater than 0 and no more than 20"})
				return
			}
		}
		bars, err := client.DailyHistory(c.Request.Context(), tickers[0])
		if err != nil {
			c.JSON(http.StatusBadGateway, gin.H{"error": err.Error()})
			return
		}
		result := marketanalysis.BuildScreenerResult(
			tickers[0], marketDataBarsModel(bars), ratio,
		)
		response := analysisResponse{
			Summary:    screenerResultDTO(result),
			History:    bars[max(0, len(bars)-260):],
			Plan:       tradePlanDTO(marketanalysis.BuildPullbackPlan(result)),
			RiskReward: tradePlanDTO(marketanalysis.BuildRiskRewardPlan(result)),
		}
		c.JSON(http.StatusOK, response)
	}
}

// normalizeSymbols uppercases, de-duplicates, and validates ticker symbols.
// It returns a syntax error when every supplied value is blank or invalid.
func normalizeSymbols(input []string) ([]string, error) {
	seen := make(map[string]bool, len(input))
	symbols := make([]string, 0, len(input))
	for _, raw := range input {
		ticker := strings.ToUpper(strings.TrimSpace(raw))
		if ticker == "" {
			continue
		}
		if !tickerPattern.MatchString(ticker) {
			return nil, strconv.ErrSyntax
		}
		if !seen[ticker] {
			seen[ticker] = true
			symbols = append(symbols, ticker)
		}
	}
	if len(symbols) == 0 {
		return nil, strconv.ErrSyntax
	}
	return symbols, nil
}

// normalizeAbove validates and de-duplicates supported moving-average filters.
func normalizeAbove(input []string) ([]string, error) {
	allowed := map[string]bool{"ema50": true, "ema100": true, "ema200": true, "sma50": true, "sma100": true, "sma200": true}
	seen := make(map[string]bool, len(input))
	result := make([]string, 0, len(input))
	for _, raw := range input {
		name := strings.ToLower(strings.TrimSpace(raw))
		if name == "" {
			continue
		}
		if !allowed[name] {
			return nil, strconv.ErrSyntax
		}
		if !seen[name] {
			seen[name] = true
			result = append(result, name)
		}
	}
	return result, nil
}

func isFinite(value float64) bool {
	return !math.IsNaN(value) && !math.IsInf(value, 0)
}

// matchesAbove reports whether close is above any/all requested averages.
func matchesAbove(indicators map[string]float64, close float64, above []string, mode string) bool {
	if len(above) == 0 {
		return true
	}
	matched := 0
	for _, name := range above {
		value, exists := indicators[strings.ToUpper(name)]
		if exists && value < close {
			matched++
		}
	}
	if mode == "all" {
		return matched == len(above)
	}
	return matched > 0
}
