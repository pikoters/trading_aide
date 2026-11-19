package web

import (
	"errors"
	"net/http"
	"os"
	"path/filepath"
	"strings"

	"github.com/gin-gonic/gin"
	"pikoters.info.mytrading/internal/marketdesk"
)

const maxJSONBodyBytes = 64 << 10

// Position is the portfolio HTTP request/response shape. Quantity and average
// price are validated on creation; current value and P&L are server-computed.
type Position struct {
	Ticker       string  `json:"ticker" binding:"required"`
	Quantity     int     `json:"quantity" binding:"required,gt=0"`
	AvgPrice     float64 `json:"avg_price" binding:"required,gt=0"`
	CurrentValue float64 `json:"current_value"`
	PnL          float64 `json:"pnl"`
}

// NewRouter creates the production router with live Yahoo market data and no
// saved-data store. Database-backed routes respond unavailable in this mode.
func NewRouter() *gin.Engine {
	return newRouter(newYahooClient(), nil)
}

// NewRouterWithMarketClient creates a router with the supplied live market
// provider and no saved-data store.
func NewRouterWithMarketClient(client marketHistoryProvider) *gin.Engine {
	return newRouter(client, nil)
}

// NewRouterWithSavedDataStore creates a router with saved-data persistence and
// the default Yahoo Finance provider for live market routes.
func NewRouterWithSavedDataStore(store marketdesk.SavedDataStore) *gin.Engine {
	return newRouter(newYahooClient(), store)
}

func newRouter(client marketHistoryProvider, store marketdesk.SavedDataStore) *gin.Engine {
	// Live market routes use client; saved-data and portfolio routes use store.
	router := gin.Default()

	router.GET("/", rootHandler)
	router.GET("/health", healthHandler)
	router.GET("/stocks", screenerResultsHandler(store))
	router.GET("/stocks/:ticker", savedAnalysisHandler(store))
	router.GET("/api/health", healthHandler)
	router.GET("/api/ready", readinessHandler(store))
	router.POST("/api/screen", screenHandler(client))
	router.GET("/api/market/stocks/:ticker", analysisHandler(client))
	router.GET("/api/market/analysis/:ticker", analysisHandler(client))
	router.GET("/api/stocks", screenerResultsHandler(store))
	router.GET("/api/analysis/:ticker", savedAnalysisHandler(store))
	router.GET("/api/stocks/:ticker", savedAnalysisHandler(store))
	router.GET("/api/screen/runs", screenerRunsHandler(store))
	router.GET("/api/screen/results", screenerResultsHandler(store))
	router.GET("/api/analysis/runs", analysisRunsHandler(store))
	router.GET("/api/analysis/results", analysisResultsHandler(store))
	router.GET("/portfolio", getPortfolio(store))
	router.POST("/portfolio", createPosition(store))
	router.NoRoute(frontendHandler)

	return router
}

func rootHandler(c *gin.Context) {
	index := filepath.Join("frontend", "dist", "index.html")
	if _, err := os.Stat(index); err == nil {
		c.File(index)
		return
	}
	c.JSON(http.StatusOK, gin.H{
		"message":  "Stock screener API",
		"frontend": "Run the Vue app from frontend/ with npm run dev",
	})
}

func healthHandler(c *gin.Context) {
	c.JSON(http.StatusOK, gin.H{"status": "ok"})
}

func getPortfolio(store savedDataStore) gin.HandlerFunc {
	return func(c *gin.Context) {
		if !requireStore(c, store) {
			return
		}
		models, err := store.ListPortfolioPositions(c.Request.Context())
		if err != nil {
			databaseFailure(c, err)
			return
		}
		positions := make([]Position, len(models))
		for index, position := range models {
			positions[index] = positionDTO(position)
		}
		c.JSON(http.StatusOK, gin.H{"positions": positions})
	}
}

func frontendHandler(c *gin.Context) {
	if strings.HasPrefix(c.Request.URL.Path, "/api/") {
		c.JSON(http.StatusNotFound, gin.H{"error": "route not found"})
		return
	}

	root := filepath.Join("frontend", "dist")
	requestPath := filepath.Clean("/" + c.Request.URL.Path)
	filePath := filepath.Join(root, requestPath)
	if relative, err := filepath.Rel(root, filePath); err != nil || strings.HasPrefix(relative, "..") {
		c.JSON(http.StatusNotFound, gin.H{"error": "not found"})
		return
	}
	if info, err := os.Stat(filePath); err == nil && !info.IsDir() {
		c.File(filePath)
		return
	}
	index := filepath.Join(root, "index.html")
	if _, err := os.Stat(index); err == nil {
		c.File(index)
		return
	}
	c.JSON(http.StatusNotFound, gin.H{"error": "frontend build not found"})
}

func createPosition(store savedDataStore) gin.HandlerFunc {
	return func(c *gin.Context) {
		if !requireStore(c, store) {
			return
		}
		c.Request.Body = http.MaxBytesReader(c.Writer, c.Request.Body, maxJSONBodyBytes)
		var position Position
		if err := c.ShouldBindJSON(&position); err != nil {
			var bodyTooLarge *http.MaxBytesError
			if errors.As(err, &bodyTooLarge) {
				c.JSON(http.StatusRequestEntityTooLarge, gin.H{"error": "request body exceeds 64 KiB"})
				return
			}
			c.JSON(http.StatusBadRequest, gin.H{"error": "invalid position request"})
			return
		}

		position.CurrentValue = float64(position.Quantity) * position.AvgPrice
		position.PnL = 0
		savedPosition, err := store.CreatePortfolioPosition(c.Request.Context(), positionModel(position))
		if err != nil {
			databaseFailure(c, err)
			return
		}
		c.JSON(http.StatusCreated, positionDTO(savedPosition))
	}
}
