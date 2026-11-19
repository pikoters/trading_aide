package marketdata

import "time"

// Bar is one timestamped OHLCV market observation. Prices and volume use the
// provider's numeric units; Date is expected to be normalized to UTC by adapters.
type Bar struct {
	Date   time.Time
	Open   float64
	High   float64
	Low    float64
	Close  float64
	Volume float64
}
