package technicalanalysis

import (
	"math"
	"testing"
	"time"
)

func testBars(count int, firstClose float64) []Bar {
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

func TestEMAUsesSimpleAverageSeed(t *testing.T) {
	values := ema([]float64{1, 2, 3, 4, 5}, 3)
	if !math.IsNaN(values[1]) {
		t.Fatalf("expected first two EMA values to be NaN, got %v", values[:2])
	}
	if values[2] != 2 || values[3] != 3 || values[4] != 4 {
		t.Fatalf("unexpected EMA values: %v", values)
	}
}

func TestCalculateIndicatorsPreservesExpectedValues(t *testing.T) {
	series := Calculate(testBars(260, 20))
	last := len(series["EMA9"])
	if last == 0 {
		t.Fatal("expected indicators to be calculated")
	}
	for _, name := range []string{
		"EMA9", "SMA40", "EnvelopeUpper_40_3", "EnvelopeLower_40_3",
		"MACD_12_26_9", "MACDs_12_26_9", "TRIX_7_9", "TRIXs_7_9",
		"FISHERT_9_1", "FISHERTs_9_1", "PSARl_0.02_0.2",
	} {
		values, exists := series[name]
		if !exists || !finite(values[last-1]) {
			t.Fatalf("expected a finite %s value, got %v", name, values)
		}
	}
	sma := series["SMA40"][last-1]
	if math.Abs(series["EnvelopeUpper_40_3"][last-1]-sma*1.03) > 1e-9 {
		t.Fatal("upper envelope does not match the 3% band")
	}
	if math.Abs(series["EnvelopeLower_40_3"][last-1]-sma*0.97) > 1e-9 {
		t.Fatal("lower envelope does not match the 3% band")
	}
	if math.Abs(series["MACDh_12_26_9"][last-1]-(series["MACD_12_26_9"][last-1]-series["MACDs_12_26_9"][last-1])) > 1e-9 {
		t.Fatal("MACD histogram does not match line minus signal")
	}
}
