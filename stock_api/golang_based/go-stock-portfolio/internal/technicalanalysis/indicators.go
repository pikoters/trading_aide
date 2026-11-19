package technicalanalysis

import (
	"math"

	"pikoters.info.mytrading/internal/marketdata"
)

// Bar is an alias for the provider-independent input bar type.
type Bar = marketdata.Bar

// Series maps indicator column names to value slices aligned with input bars.
type Series map[string][]float64

// Calculate returns all supported indicator series for the ordered input bars.
// Each output slice has the same length as bars; insufficient warm-up history
// is represented by NaN rather than by a shorter slice.
func Calculate(bars []Bar) Series {
	closeValues := make([]float64, len(bars))
	highValues := make([]float64, len(bars))
	lowValues := make([]float64, len(bars))
	volumeValues := make([]float64, len(bars))
	medianValues := make([]float64, len(bars))
	for index, bar := range bars {
		closeValues[index] = bar.Close
		highValues[index] = bar.High
		lowValues[index] = bar.Low
		volumeValues[index] = bar.Volume
		medianValues[index] = (bar.High + bar.Low) / 2
	}

	macdLine, macdSignal, macdHistogram := macd(closeValues, 12, 26, 9)
	trixLine, trixSignal := trix(closeValues, 7, 9)
	fisherLine, fisherSignal := fisher(highValues, lowValues, 9)
	psarLong, psarShort := parabolicSAR(bars, 0.02, 0.2)
	sma40 := rollingMean(closeValues, 40)

	series := Series{
		"ALMA":                alma(closeValues, 21, 0.85, 6),
		"AO":                  subtract(rollingMean(medianValues, 5), rollingMean(medianValues, 34)),
		"EMA9":                ema(closeValues, 9),
		"EMA50":               ema(closeValues, 50),
		"EMA100":              ema(closeValues, 100),
		"EMA200":              ema(closeValues, 200),
		"SMA40":               sma40,
		"EnvelopeUpper_40_3":  multiply(sma40, 1.03),
		"EnvelopeLower_40_3":  multiply(sma40, 0.97),
		"SMA50":               rollingMean(closeValues, 50),
		"SMA100":              rollingMean(closeValues, 100),
		"SMA200":              rollingMean(closeValues, 200),
		"BBM_20_2.0":          rollingMean(closeValues, 20),
		"VolumeAvg20":         rollingMean(volumeValues, 20),
		"RSI_14":              rsi(closeValues, 14),
		"ATRr_14":             atr(bars, 14),
		"CCI_20":              cci(bars, 20),
		"WILLR_14":            williamsR(bars, 14),
		"OBV":                 obv(bars),
		"MOM_10":              momentum(closeValues, 10),
		"ROC_12":              rateOfChange(closeValues, 12),
		"KCLe_20_2":           subtract(ema(closeValues, 20), multiply(atr(bars, 20), 2)),
		"ISA_9":               ichimokuSpanA(bars),
		"VPT":                 volumePriceTrend(bars),
		"MACD_12_26_9":        macdLine,
		"MACDs_12_26_9":       macdSignal,
		"MACDh_12_26_9":       macdHistogram,
		"TRIX_7_9":            trixLine,
		"TRIXs_7_9":           trixSignal,
		"FISHERT_9_1":         fisherLine,
		"FISHERTs_9_1":        fisherSignal,
		"STOCHRSIk_14_14_3_3": stochRSIK(closeValues, 14, 3),
		"TEMA_21":             tema(closeValues, 21),
		"ADX_14":              adx(bars, 14),
		"ADOSC":               accumulationDistributionOscillator(bars, 3, 10),
		"PSARl_0.02_0.2":      psarLong,
		"PSARs_0.02_0.2":      psarShort,
	}
	return series
}

func nanSeries(length int) []float64 {
	values := make([]float64, length)
	for index := range values {
		values[index] = math.NaN()
	}
	return values
}

func finite(value float64) bool {
	return !math.IsNaN(value) && !math.IsInf(value, 0)
}

func rollingMean(values []float64, period int) []float64 {
	result := nanSeries(len(values))
	if period <= 0 {
		return result
	}
	var total float64
	for index, value := range values {
		total += value
		if index >= period {
			total -= values[index-period]
		}
		if index >= period-1 {
			result[index] = total / float64(period)
		}
	}
	return result
}

func ema(values []float64, period int) []float64 {
	result := nanSeries(len(values))
	if period <= 0 {
		return result
	}
	start := firstFinite(values)
	if start < 0 || start+period > len(values) {
		return result
	}
	var seed float64
	for index := start; index < start+period; index++ {
		if !finite(values[index]) {
			return result
		}
		seed += values[index]
	}
	seedIndex := start + period - 1
	result[seedIndex] = seed / float64(period)
	alpha := 2.0 / float64(period+1)
	for index := seedIndex + 1; index < len(values); index++ {
		if !finite(values[index]) {
			break
		}
		result[index] = alpha*values[index] + (1-alpha)*result[index-1]
	}
	return result
}

func wildersMean(values []float64, period int) []float64 {
	result := nanSeries(len(values))
	if period <= 0 {
		return result
	}
	start := firstFinite(values)
	if start < 0 || start+period > len(values) {
		return result
	}
	var seed float64
	for index := start; index < start+period; index++ {
		if !finite(values[index]) {
			return result
		}
		seed += values[index]
	}
	seedIndex := start + period - 1
	result[seedIndex] = seed / float64(period)
	for index := seedIndex + 1; index < len(values); index++ {
		if !finite(values[index]) {
			break
		}
		result[index] = (result[index-1]*float64(period-1) + values[index]) / float64(period)
	}
	return result
}

func firstFinite(values []float64) int {
	for index, value := range values {
		if finite(value) {
			return index
		}
	}
	return -1
}

func subtract(left, right []float64) []float64 {
	result := nanSeries(len(left))
	for index := range left {
		if index < len(right) && finite(left[index]) && finite(right[index]) {
			result[index] = left[index] - right[index]
		}
	}
	return result
}

func multiply(values []float64, factor float64) []float64 {
	result := nanSeries(len(values))
	for index, value := range values {
		if finite(value) {
			result[index] = value * factor
		}
	}
	return result
}

func alma(values []float64, period int, offset, sigma float64) []float64 {
	result := nanSeries(len(values))
	if period <= 0 || len(values) < period || sigma <= 0 {
		return result
	}
	center := offset * float64(period-1)
	scale := float64(period) / sigma
	weights := make([]float64, period)
	var weightSum float64
	for index := 0; index < period; index++ {
		delta := float64(index) - center
		weights[index] = math.Exp(-(delta * delta) / (2 * scale * scale))
		weightSum += weights[index]
	}
	for end := period - 1; end < len(values); end++ {
		var total float64
		valid := true
		for index := 0; index < period; index++ {
			value := values[end-period+1+index]
			if !finite(value) {
				valid = false
				break
			}
			total += value * weights[index]
		}
		if valid {
			result[end] = total / weightSum
		}
	}
	return result
}

func rsi(values []float64, period int) []float64 {
	changes := nanSeries(len(values))
	for index := 1; index < len(values); index++ {
		changes[index] = values[index] - values[index-1]
	}
	gains := nanSeries(len(values))
	losses := nanSeries(len(values))
	for index, change := range changes {
		if finite(change) {
			gains[index] = math.Max(change, 0)
			losses[index] = math.Max(-change, 0)
		}
	}
	averageGain := wildersMean(gains, period)
	averageLoss := wildersMean(losses, period)
	result := nanSeries(len(values))
	for index := range result {
		if !finite(averageGain[index]) || !finite(averageLoss[index]) {
			continue
		}
		if averageLoss[index] == 0 {
			result[index] = 100
		} else {
			rs := averageGain[index] / averageLoss[index]
			result[index] = 100 - 100/(1+rs)
		}
	}
	return result
}

func trueRange(bars []Bar) []float64 {
	result := nanSeries(len(bars))
	for index, bar := range bars {
		if index == 0 {
			result[index] = bar.High - bar.Low
			continue
		}
		previousClose := bars[index-1].Close
		result[index] = math.Max(bar.High-bar.Low, math.Max(math.Abs(bar.High-previousClose), math.Abs(bar.Low-previousClose)))
	}
	return result
}

func atr(bars []Bar, period int) []float64 {
	return wildersMean(trueRange(bars), period)
}

func macdHistogram(values []float64, fast, slow, signal int) []float64 {
	_, _, histogram := macd(values, fast, slow, signal)
	return histogram
}

func macd(values []float64, fast, slow, signalPeriod int) ([]float64, []float64, []float64) {
	line := subtract(ema(values, fast), ema(values, slow))
	signal := ema(line, signalPeriod)
	return line, signal, subtract(line, signal)
}

func trix(values []float64, period, signalPeriod int) ([]float64, []float64) {
	first := ema(values, period)
	second := ema(first, period)
	third := ema(second, period)
	line := nanSeries(len(values))
	for index := 1; index < len(values); index++ {
		if finite(third[index]) && finite(third[index-1]) && third[index-1] != 0 {
			line[index] = 100 * (third[index]/third[index-1] - 1)
		}
	}
	return line, ema(line, signalPeriod)
}

func fisher(high, low []float64, period int) ([]float64, []float64) {
	line := nanSeries(len(high))
	signal := nanSeries(len(high))
	smoothed := 0.0
	previousFisher := 0.0
	for index := period - 1; index < len(high); index++ {
		highest, lowest := math.Inf(-1), math.Inf(1)
		for cursor := index - period + 1; cursor <= index; cursor++ {
			median := (high[cursor] + low[cursor]) / 2
			highest = math.Max(highest, median)
			lowest = math.Min(lowest, median)
		}
		if highest == lowest {
			continue
		}
		median := (high[index] + low[index]) / 2
		value := 2 * ((median-lowest)/(highest-lowest) - 0.5)
		smoothed = 0.33*value + 0.67*smoothed
		smoothed = math.Max(-0.999, math.Min(0.999, smoothed))
		currentFisher := 0.5*math.Log((1+smoothed)/(1-smoothed)) + 0.5*previousFisher
		line[index] = currentFisher
		if index > 0 && finite(line[index-1]) {
			signal[index] = line[index-1]
		}
		previousFisher = currentFisher
	}
	return line, signal
}

func tema(values []float64, period int) []float64 {
	first := ema(values, period)
	second := ema(first, period)
	third := ema(second, period)
	result := nanSeries(len(values))
	for index := range result {
		if finite(first[index]) && finite(second[index]) && finite(third[index]) {
			result[index] = 3*first[index] - 3*second[index] + third[index]
		}
	}
	return result
}

func stochRSIK(values []float64, period, smooth int) []float64 {
	rsiValues := rsi(values, period)
	stochastic := nanSeries(len(values))
	for index := period - 1; index < len(values); index++ {
		start := index - period + 1
		minimum, maximum := math.Inf(1), math.Inf(-1)
		valid := true
		for cursor := start; cursor <= index; cursor++ {
			if !finite(rsiValues[cursor]) {
				valid = false
				break
			}
			minimum = math.Min(minimum, rsiValues[cursor])
			maximum = math.Max(maximum, rsiValues[cursor])
		}
		if valid && maximum > minimum {
			stochastic[index] = 100 * (rsiValues[index] - minimum) / (maximum - minimum)
		}
	}
	return rollingMean(stochastic, smooth)
}

func cci(bars []Bar, period int) []float64 {
	typical := make([]float64, len(bars))
	for index, bar := range bars {
		typical[index] = (bar.High + bar.Low + bar.Close) / 3
	}
	mean := rollingMean(typical, period)
	result := nanSeries(len(bars))
	for index := period - 1; index < len(bars); index++ {
		var deviation float64
		for cursor := index - period + 1; cursor <= index; cursor++ {
			deviation += math.Abs(typical[cursor] - mean[index])
		}
		deviation /= float64(period)
		if deviation > 0 {
			result[index] = (typical[index] - mean[index]) / (0.015 * deviation)
		}
	}
	return result
}

func williamsR(bars []Bar, period int) []float64 {
	result := nanSeries(len(bars))
	for index := period - 1; index < len(bars); index++ {
		highest, lowest := math.Inf(-1), math.Inf(1)
		for cursor := index - period + 1; cursor <= index; cursor++ {
			highest = math.Max(highest, bars[cursor].High)
			lowest = math.Min(lowest, bars[cursor].Low)
		}
		if highest > lowest {
			result[index] = -100 * (highest - bars[index].Close) / (highest - lowest)
		}
	}
	return result
}

func adx(bars []Bar, period int) []float64 {
	length := len(bars)
	positiveDM := nanSeries(length)
	negativeDM := nanSeries(length)
	for index := range bars {
		if index == 0 {
			positiveDM[index], negativeDM[index] = 0, 0
			continue
		}
		upMove := bars[index].High - bars[index-1].High
		downMove := bars[index-1].Low - bars[index].Low
		positiveDM[index], negativeDM[index] = 0, 0
		if upMove > downMove && upMove > 0 {
			positiveDM[index] = upMove
		}
		if downMove > upMove && downMove > 0 {
			negativeDM[index] = downMove
		}
	}
	averageTR := wildersMean(trueRange(bars), period)
	averagePositive := wildersMean(positiveDM, period)
	averageNegative := wildersMean(negativeDM, period)
	dx := nanSeries(length)
	for index := range bars {
		if !finite(averageTR[index]) || averageTR[index] == 0 {
			continue
		}
		positiveDI := 100 * averagePositive[index] / averageTR[index]
		negativeDI := 100 * averageNegative[index] / averageTR[index]
		denominator := positiveDI + negativeDI
		if denominator > 0 {
			dx[index] = 100 * math.Abs(positiveDI-negativeDI) / denominator
		}
	}
	return wildersMean(dx, period)
}

func obv(bars []Bar) []float64 {
	result := make([]float64, len(bars))
	for index := 1; index < len(bars); index++ {
		result[index] = result[index-1]
		if bars[index].Close > bars[index-1].Close {
			result[index] += bars[index].Volume
		} else if bars[index].Close < bars[index-1].Close {
			result[index] -= bars[index].Volume
		}
	}
	return result
}

func momentum(values []float64, period int) []float64 {
	result := nanSeries(len(values))
	for index := period; index < len(values); index++ {
		result[index] = values[index] - values[index-period]
	}
	return result
}

func rateOfChange(values []float64, period int) []float64 {
	result := nanSeries(len(values))
	for index := period; index < len(values); index++ {
		if values[index-period] != 0 {
			result[index] = 100 * (values[index]/values[index-period] - 1)
		}
	}
	return result
}

func ichimokuSpanA(bars []Bar) []float64 {
	result := nanSeries(len(bars))
	for index := 25; index < len(bars); index++ {
		tenkanHigh, tenkanLow := math.Inf(-1), math.Inf(1)
		for cursor := index - 8; cursor <= index; cursor++ {
			tenkanHigh = math.Max(tenkanHigh, bars[cursor].High)
			tenkanLow = math.Min(tenkanLow, bars[cursor].Low)
		}
		kijunHigh, kijunLow := math.Inf(-1), math.Inf(1)
		for cursor := index - 25; cursor <= index; cursor++ {
			kijunHigh = math.Max(kijunHigh, bars[cursor].High)
			kijunLow = math.Min(kijunLow, bars[cursor].Low)
		}
		result[index] = ((tenkanHigh+tenkanLow)/2 + (kijunHigh+kijunLow)/2) / 2
	}
	return result
}

func volumePriceTrend(bars []Bar) []float64 {
	result := make([]float64, len(bars))
	for index := 1; index < len(bars); index++ {
		result[index] = result[index-1]
		if bars[index-1].Close != 0 {
			result[index] += (bars[index].Close/bars[index-1].Close - 1) * bars[index].Volume
		}
	}
	return result
}

func accumulationDistributionOscillator(bars []Bar, fast, slow int) []float64 {
	line := make([]float64, len(bars))
	for index, bar := range bars {
		spread := bar.High - bar.Low
		if spread == 0 {
			if index > 0 {
				line[index] = line[index-1]
			}
			continue
		}
		multiplier := ((bar.Close - bar.Low) - (bar.High - bar.Close)) / spread
		line[index] = multiplier * bar.Volume
		if index > 0 {
			line[index] += line[index-1]
		}
	}
	return subtract(ema(line, fast), ema(line, slow))
}

func parabolicSARLong(bars []Bar, step, maximum float64) []float64 {
	long, _ := parabolicSAR(bars, step, maximum)
	return long
}

func parabolicSAR(bars []Bar, step, maximum float64) ([]float64, []float64) {
	result := nanSeries(len(bars))
	short := nanSeries(len(bars))
	if len(bars) < 2 {
		return result, short
	}
	bullish := bars[1].Close >= bars[0].Close
	acceleration := step
	extreme := bars[0].Low
	sar := bars[0].High
	if bullish {
		extreme, sar = bars[0].High, bars[0].Low
	}
	for index := 1; index < len(bars); index++ {
		sar += acceleration * (extreme - sar)
		if bullish {
			sar = math.Min(sar, bars[index-1].Low)
			if index > 1 {
				sar = math.Min(sar, bars[index-2].Low)
			}
			if bars[index].Low < sar {
				bullish, sar, extreme, acceleration = false, extreme, bars[index].Low, step
			} else if bars[index].High > extreme {
				extreme = bars[index].High
				acceleration = math.Min(acceleration+step, maximum)
			}
		} else {
			sar = math.Max(sar, bars[index-1].High)
			if index > 1 {
				sar = math.Max(sar, bars[index-2].High)
			}
			if bars[index].High > sar {
				bullish, sar, extreme, acceleration = true, extreme, bars[index].High, step
			} else if bars[index].Low < extreme {
				extreme = bars[index].Low
				acceleration = math.Min(acceleration+step, maximum)
			}
		}
		if bullish {
			result[index] = sar
		} else {
			short[index] = sar
		}
	}
	return result, short
}

func parabolicSARShort(bars []Bar, step, maximum float64) []float64 {
	_, short := parabolicSAR(bars, step, maximum)
	return short
}
