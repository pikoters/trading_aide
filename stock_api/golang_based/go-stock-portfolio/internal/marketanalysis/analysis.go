package marketanalysis

import (
	"math"
	"strings"

	"pikoters.info.mytrading/internal/marketdata"
	"pikoters.info.mytrading/internal/marketdesk"
	"pikoters.info.mytrading/internal/technicalanalysis"
)

// BuildScreenerResult calculates the latest indicators, screening signals,
// score, and ATR reference levels for a ticker's ordered market bars. bars must
// contain at least one observation; rrRatio is the target multiple of ATR risk.
func BuildScreenerResult(ticker string, bars []marketdata.Bar, rrRatio float64) marketdesk.ScreenerResult {
	lastIndex := len(bars) - 1
	last := bars[lastIndex]
	series := technicalanalysis.Calculate(bars)
	values := make(map[string]float64, len(series)+1)
	for name, row := range series {
		if isFinite(row[lastIndex]) {
			values[name] = row[lastIndex]
		}
	}

	signals := makeSignals(last.Close, last.Volume, lastIndex, series)
	score := 0
	for name, positive := range signals {
		if !positive {
			continue
		}
		if strings.Contains(name, "cross_up") {
			score += 2
		} else if strings.Contains(name, "cross_down") {
			score -= 2
		} else {
			score++
		}
	}

	var stop, target *float64
	if atrValue, ok := values["ATRr_14"]; ok && atrValue > 0 {
		stopValue, targetValue := last.Close-atrValue, last.Close+rrRatio*atrValue
		stop, target = &stopValue, &targetValue
	}
	var changePercent *float64
	change := 0.0
	if lastIndex > 0 && bars[lastIndex-1].Close != 0 {
		change = 100 * (last.Close/bars[lastIndex-1].Close - 1)
	}
	changePercent = &change
	open, high, low, volume := last.Open, last.High, last.Low, last.Volume

	return marketdesk.ScreenerResult{
		Ticker: ticker, AsOf: last.Date.Format("2006-01-02"),
		Open: &open, High: &high, Low: &low, Close: last.Close,
		ChangePercent: changePercent, Volume: &volume, Indicators: values,
		Signals: signals, Score: score, Stop: stop, Target: target, RRRatio: rrRatio,
	}
}

// BuildPullbackPlan proposes an EMA100/EMA200 support entry with a one-ATR
// stop and the result's reward-to-risk target. Missing support or ATR leaves
// the returned advisory plan non-actionable.
func BuildPullbackPlan(result marketdesk.ScreenerResult) marketdesk.TradePlan {
	plan := marketdesk.TradePlan{
		Setup: "long_pullback", RRRatio: result.RRRatio,
		EntryRule: "limit at the highest EMA100/EMA200 support below close; stop one ATR below entry",
	}
	atrValue, hasATR := result.Indicators["ATRr_14"]
	var support float64
	for _, name := range []string{"EMA100", "EMA200"} {
		value, ok := result.Indicators[name]
		if ok && value < result.Close && value > support {
			support = value
			plan.EntrySupport = name
		}
	}
	if plan.EntrySupport == "" || !hasATR || atrValue <= 0 {
		return plan
	}
	entry, stop := support, support-atrValue
	target := support + result.RRRatio*atrValue
	risk := entry - stop
	plan.Actionable = entry > stop && target > entry
	plan.Entry, plan.Stop, plan.Target, plan.RiskPerShare = &entry, &stop, &target, &risk
	return plan
}

// BuildRiskRewardPlan expresses the result's close, stop, and target as a
// reference plan when the ATR-derived levels are available.
func BuildRiskRewardPlan(result marketdesk.ScreenerResult) marketdesk.TradePlan {
	plan := marketdesk.TradePlan{
		Setup: "atr_risk_reward", RRRatio: result.RRRatio,
		EntryRule: "reference levels from latest close and one ATR of risk",
	}
	if result.Stop == nil || result.Target == nil {
		return plan
	}
	entry := result.Close
	risk := entry - *result.Stop
	plan.Actionable = true
	plan.Entry, plan.Stop, plan.Target, plan.RiskPerShare = &entry, result.Stop, result.Target, &risk
	return plan
}

func makeSignals(close, volume float64, index int, series technicalanalysis.Series) map[string]bool {
	value := func(name string) float64 { return series[name][index] }
	available := func(name string) bool { return isFinite(value(name)) }
	compare := func(name string, condition func(float64) bool) bool {
		return available(name) && condition(value(name))
	}
	signals := map[string]bool{
		"alma_bull":     compare("ALMA", func(item float64) bool { return close > item }),
		"macd_bull":     compare("MACDh_12_26_9", func(item float64) bool { return item > 0 }),
		"ao_bull":       compare("AO", func(item float64) bool { return item > 0 }),
		"psar_bull":     compare("PSARl_0.02_0.2", func(item float64) bool { return item < close }),
		"mma_bull":      available("EMA50") && available("EMA100") && available("EMA200") && value("EMA50") > value("EMA100") && value("EMA100") > value("EMA200"),
		"bb_bull":       compare("BBM_20_2.0", func(item float64) bool { return close > item }),
		"stochrsi_bull": compare("STOCHRSIk_14_14_3_3", func(item float64) bool { return item > 0.2 }),
		"tema_bull":     compare("TEMA_21", func(item float64) bool { return close > item }),
		"vol_bull":      compare("VolumeAvg20", func(item float64) bool { return volume > item }),
		"rsi_bull":      compare("RSI_14", func(item float64) bool { return item > 50 }),
		"atr_bull":      compare("ATRr_14", func(item float64) bool { return item > 0 }),
		"cci_bull":      compare("CCI_20", func(item float64) bool { return item > 0 }),
		"willr_bull":    compare("WILLR_14", func(item float64) bool { return item < -50 }),
		"adx_bull":      compare("ADX_14", func(item float64) bool { return item > 25 }),
		"obv_bull":      compare("OBV", func(item float64) bool { return item > 0 }),
		"mom_bull":      compare("MOM_10", func(item float64) bool { return item > 0 }),
		"roc_bull":      compare("ROC_12", func(item float64) bool { return item > 0 }),
		"kc_bull":       compare("KCLe_20_2", func(item float64) bool { return close > item }),
		"ichi_bull":     compare("ISA_9", func(item float64) bool { return close > item }),
		"adosc_bull":    compare("ADOSC", func(item float64) bool { return item > 0 }),
		"vpt_bull":      compare("VPT", func(item float64) bool { return item > 0 }),
	}
	for _, name := range []string{"EMA50", "EMA100", "EMA200", "SMA50", "SMA100", "SMA200"} {
		if available(name) {
			lower := strings.ToLower(name)
			signals[lower+"_bull"] = close > value(name)
			signals[lower+"_bear"] = close < value(name)
		}
	}
	for _, pair := range []struct {
		short, long string
	}{
		{"EMA100", "EMA200"},
		{"SMA100", "SMA200"},
	} {
		shortValue, longValue := value(pair.short), value(pair.long)
		if available(pair.short) && available(pair.long) {
			prefix := strings.ToLower(pair.short)
			signals[prefix+"_above_"+strings.ToLower(pair.long)] = shortValue > longValue
			signals[prefix+"_below_"+strings.ToLower(pair.long)] = shortValue < longValue
			if index > 0 {
				previousShort, previousLong := series[pair.short][index-1], series[pair.long][index-1]
				if isFinite(previousShort) && isFinite(previousLong) {
					signals[prefix+"_cross_up_"+strings.ToLower(pair.long)] = previousShort <= previousLong && shortValue > longValue
					signals[prefix+"_cross_down_"+strings.ToLower(pair.long)] = previousShort >= previousLong && shortValue < longValue
				}
			}
		}
	}
	return signals
}

func isFinite(value float64) bool {
	return !math.IsNaN(value) && !math.IsInf(value, 0)
}
