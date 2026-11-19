package web

import (
	"context"
	"errors"
	"net/http"
	"strconv"
	"strings"

	"github.com/gin-gonic/gin"
	"pikoters.info.mytrading/internal/marketdesk"
)

const maxDatabaseRows = 1000

func screenerRunsHandler(store savedDataStore) gin.HandlerFunc {
	return func(c *gin.Context) {
		if !requireStore(c, store) {
			return
		}
		limit, ok := queryLimit(c)
		if !ok {
			return
		}
		models, err := store.ListScreenerRuns(c.Request.Context(), limit)
		if err != nil {
			databaseFailure(c, err)
			return
		}
		runs := make([]screenerRun, len(models))
		for index, run := range models {
			runs[index] = screenerRunDTO(run)
		}
		c.JSON(http.StatusOK, gin.H{"runs": runs})
	}
}

func screenerResultsHandler(store savedDataStore) gin.HandlerFunc {
	return func(c *gin.Context) {
		if !requireStore(c, store) {
			return
		}
		limit, ok := queryLimit(c)
		if !ok {
			return
		}
		run, models, err := store.LoadScreenerResults(c.Request.Context(), strings.TrimSpace(c.Query("run_id")), limit)
		if err != nil {
			databaseFailure(c, err)
			return
		}
		if run.RunID == "" {
			c.JSON(http.StatusNotFound, gin.H{"error": "no saved screener runs found"})
			return
		}
		results := make([]screenerResult, len(models))
		for index, result := range models {
			results[index] = screenerResultDTO(result)
		}
		c.JSON(http.StatusOK, gin.H{
			"run": screenerRunDTO(run), "run_id": run.RunID, "results": results,
			"total_screened": run.ResultCount, "returned": len(results),
		})
	}
}

func analysisRunsHandler(store savedDataStore) gin.HandlerFunc {
	return func(c *gin.Context) {
		if !requireStore(c, store) {
			return
		}
		limit, ok := queryLimit(c)
		if !ok {
			return
		}
		models, err := store.ListAnalysisRuns(c.Request.Context(), limit)
		if err != nil {
			databaseFailure(c, err)
			return
		}
		runs := make([]analysisRun, len(models))
		for index, run := range models {
			runs[index] = analysisRunDTO(run)
		}
		c.JSON(http.StatusOK, gin.H{"runs": runs})
	}
}

func analysisResultsHandler(store savedDataStore) gin.HandlerFunc {
	return func(c *gin.Context) {
		if !requireStore(c, store) {
			return
		}
		limit, ok := queryLimit(c)
		if !ok {
			return
		}
		run, models, err := store.LoadAnalysisResults(c.Request.Context(), strings.TrimSpace(c.Query("run_id")), limit)
		if err != nil {
			databaseFailure(c, err)
			return
		}
		if run.AnalysisRunID == "" {
			c.JSON(http.StatusNotFound, gin.H{"error": "no saved analysis runs found"})
			return
		}
		results := make([]savedAnalysisResult, len(models))
		for index, result := range models {
			results[index] = analysisResultDTO(result)
		}
		c.JSON(http.StatusOK, gin.H{"run": analysisRunDTO(run), "results": results, "returned": len(results)})
	}
}

func savedAnalysisHandler(store savedDataStore) gin.HandlerFunc {
	return func(c *gin.Context) {
		if !requireStore(c, store) {
			return
		}
		tickers, err := normalizeSymbols([]string{c.Param("ticker")})
		if err != nil {
			c.JSON(http.StatusBadRequest, gin.H{"error": "invalid ticker symbol"})
			return
		}
		result, err := store.LoadTickerAnalysis(c.Request.Context(), tickers[0], strings.TrimSpace(c.Query("screener_run_id")))
		if errors.Is(err, marketdesk.ErrNotFound) {
			c.JSON(http.StatusNotFound, gin.H{"error": "no saved analysis found for ticker"})
			return
		}
		if err != nil {
			databaseFailure(c, err)
			return
		}
		c.JSON(http.StatusOK, analysisResponseDTO(result))
	}
}

func readinessHandler(store savedDataStore) gin.HandlerFunc {
	return func(c *gin.Context) {
		if !requireStore(c, store) {
			return
		}
		ctx, cancel := context.WithTimeout(c.Request.Context(), 2_000_000_000)
		defer cancel()
		if err := store.Ping(ctx); err != nil {
			c.JSON(http.StatusServiceUnavailable, gin.H{"status": "not_ready", "database": "unavailable"})
			return
		}
		c.JSON(http.StatusOK, gin.H{"status": "ok", "database": "available"})
	}
}

func requireStore(c *gin.Context, store savedDataStore) bool {
	if store == nil {
		c.JSON(http.StatusServiceUnavailable, gin.H{"error": "PostgreSQL is not configured"})
		return false
	}
	return true
}

func databaseFailure(c *gin.Context, err error) {
	c.Error(err)
	c.JSON(http.StatusInternalServerError, gin.H{"error": "database query failed"})
}

func queryLimit(c *gin.Context) (int, bool) {
	limit := 100
	if raw := c.Query("limit"); raw != "" {
		parsed, err := strconv.Atoi(raw)
		if err != nil || parsed < 1 || parsed > maxDatabaseRows {
			c.JSON(http.StatusBadRequest, gin.H{"error": "limit must be between 1 and 1000"})
			return 0, false
		}
		limit = parsed
	}
	return limit, true
}
