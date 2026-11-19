package marketanalysis

import (
	"testing"
	"time"

	"pikoters.info.mytrading/internal/marketdata"
)

func TestBuildScreenerResultAndPlans(t *testing.T) {
	bars := make([]marketdata.Bar, 240)
	for index := range bars {
		closePrice := 80 + float64(index)*0.25
		bars[index] = marketdata.Bar{
			Date: time.Date(2026, 1, 1, 0, 0, 0, 0, time.UTC).AddDate(0, 0, index),
			Open: closePrice - 0.4, High: closePrice + 1,
			Low: closePrice - 1, Close: closePrice, Volume: 1000 + float64(index),
		}
	}

	result := BuildScreenerResult("TEST", bars, 2)
	if result.Ticker != "TEST" || result.AsOf != bars[len(bars)-1].Date.Format("2006-01-02") ||
		result.Close != bars[len(bars)-1].Close || result.RRRatio != 2 {
		t.Fatalf("unexpected screener result: %#v", result)
	}
	if result.Indicators["EMA100"] == 0 || result.Indicators["ATRr_14"] <= 0 {
		t.Fatalf("expected calculated EMA and ATR values: %#v", result.Indicators)
	}

	pullback := BuildPullbackPlan(result)
	if !pullback.Actionable || pullback.Entry == nil || pullback.Stop == nil ||
		pullback.Target == nil || pullback.RRRatio != 2 {
		t.Fatalf("expected actionable pullback plan, got %#v", pullback)
	}
	reward := BuildRiskRewardPlan(result)
	if !reward.Actionable || reward.Entry == nil || reward.RiskPerShare == nil {
		t.Fatalf("expected actionable risk/reward plan, got %#v", reward)
	}
}
