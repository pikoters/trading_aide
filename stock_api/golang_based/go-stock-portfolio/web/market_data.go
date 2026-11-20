package web

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/url"
	"time"
)

// Bar is the market-history JSON shape returned by live market-analysis routes.
type Bar struct {
	Date   time.Time `json:"date"`
	Open   float64   `json:"open,omitempty"`
	High   float64   `json:"high,omitempty"`
	Low    float64   `json:"low,omitempty"`
	Close  float64   `json:"close"`
	Volume float64   `json:"volume,omitempty"`
}

// marketHistoryProvider is the live daily-history capability consumed by
// market endpoints and injected by router constructors in tests.
type marketHistoryProvider interface {
	DailyHistory(context.Context, string) ([]Bar, error)
}

type yahooClient struct {
	httpClient *http.Client
	baseURL    string
}

func newYahooClient() *yahooClient {
	return &yahooClient{
		httpClient: &http.Client{Timeout: 20 * time.Second},
		baseURL:    "https://query1.finance.yahoo.com/v8/finance/chart/",
	}
}

type yahooChartResponse struct {
	Chart struct {
		Result []struct {
			Timestamp  []int64 `json:"timestamp"`
			Indicators struct {
				Quote []struct {
					Open   []*float64 `json:"open"`
					High   []*float64 `json:"high"`
					Low    []*float64 `json:"low"`
					Close  []*float64 `json:"close"`
					Volume []*float64 `json:"volume"`
				} `json:"quote"`
			} `json:"indicators"`
		} `json:"result"`
		Error *struct {
			Description string `json:"description"`
		} `json:"error"`
	} `json:"chart"`
}

// DailyHistory downloads up to five years of daily Yahoo Finance bars.
// It filters incomplete quotes and requires at least 21 complete bars.
func (client *yahooClient) DailyHistory(ctx context.Context, ticker string) ([]Bar, error) {
	endpoint := client.baseURL + url.PathEscape(ticker)
	request, err := http.NewRequestWithContext(ctx, http.MethodGet, endpoint+"?range=5y&interval=1d", nil)
	if err != nil {
		return nil, err
	}
	request.Header.Set("User-Agent", "Mozilla/5.0 stock-screener/1.0")
	request.Header.Set("Accept", "application/json")

	response, err := client.httpClient.Do(request)
	if err != nil {
		return nil, fmt.Errorf("download %s: %w", ticker, err)
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("Yahoo Finance returned HTTP %d for %s", response.StatusCode, ticker)
	}

	var payload yahooChartResponse
	if err := json.NewDecoder(response.Body).Decode(&payload); err != nil {
		return nil, fmt.Errorf("decode Yahoo Finance response for %s: %w", ticker, err)
	}
	if payload.Chart.Error != nil {
		return nil, fmt.Errorf("Yahoo Finance: %s", payload.Chart.Error.Description)
	}
	if len(payload.Chart.Result) == 0 || len(payload.Chart.Result[0].Indicators.Quote) == 0 {
		return nil, fmt.Errorf("no daily price data found for %s", ticker)
	}

	result := payload.Chart.Result[0]
	quote := result.Indicators.Quote[0]
	length := len(result.Timestamp)
	if len(quote.Open) < length || len(quote.High) < length || len(quote.Low) < length || len(quote.Close) < length || len(quote.Volume) < length {
		return nil, fmt.Errorf("incomplete daily price data for %s", ticker)
	}

	bars := make([]Bar, 0, length)
	for index, timestamp := range result.Timestamp {
		values := []*float64{quote.Open[index], quote.High[index], quote.Low[index], quote.Close[index], quote.Volume[index]}
		valid := true
		for _, value := range values {
			if value == nil {
				valid = false
				break
			}
		}
		if !valid {
			continue
		}
		bars = append(bars, Bar{
			Date: time.Unix(timestamp, 0).UTC(), Open: *quote.Open[index], High: *quote.High[index],
			Low: *quote.Low[index], Close: *quote.Close[index], Volume: *quote.Volume[index],
		})
	}
	if len(bars) < 21 {
		return nil, fmt.Errorf("%s has fewer than 21 daily bars", ticker)
	}
	return bars, nil
}
