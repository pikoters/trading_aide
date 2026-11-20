-- Run once after creating the target PostgreSQL database.
-- Each execution gets a unique run_id, so reruns on the same day are retained.

CREATE TABLE IF NOT EXISTS screener_runs (
    run_id UUID PRIMARY KEY,
    started_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ NOT NULL,
    universe TEXT NOT NULL,
    selected_symbols TEXT NOT NULL,
    indicators TEXT NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    max_symbols INTEGER NOT NULL,
    green_only BOOLEAN NOT NULL,
    above_filters TEXT NOT NULL,
    above_mode TEXT NOT NULL,
    rr_ratio NUMERIC NOT NULL,
    result_count INTEGER NOT NULL,
    output_file TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS portfolio_positions (
    position_id BIGSERIAL PRIMARY KEY,
    ticker TEXT NOT NULL,
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    avg_price NUMERIC NOT NULL CHECK (avg_price > 0),
    current_value NUMERIC NOT NULL,
    pnl NUMERIC NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS screener_results (
    run_id UUID NOT NULL REFERENCES screener_runs(run_id),
    ticker TEXT NOT NULL,
    date DATE NOT NULL,
    close NUMERIC,
    "ALMA" NUMERIC,
    "MACDh_12_26_9" NUMERIC,
    "AO" NUMERIC,
    "PSARl_0.02_0.2" NUMERIC,
    "EMA50" NUMERIC,
    "EMA100" NUMERIC,
    "EMA200" NUMERIC,
    "SMA100" NUMERIC,
    "SMA200" NUMERIC,
    "BBM_20_2.0" NUMERIC,
    "STOCHRSIk_14_14_3_3" NUMERIC,
    "TEMA_21" NUMERIC,
    "VolumeAvg20" NUMERIC,
    "RSI_14" NUMERIC,
    "ATRr_14" NUMERIC,
    "CCI_20" NUMERIC,
    "WILLR_14" NUMERIC,
    "ADX_14" NUMERIC,
    "OBV" NUMERIC,
    "MOM_10" NUMERIC,
    "ROC_12" NUMERIC,
    "KCLe_20_2" NUMERIC,
    "ISA_9" NUMERIC,
    "ADOSC" NUMERIC,
    "VPT" NUMERIC,
    "SMA50" NUMERIC,
    alma_bull BOOLEAN,
    macd_bull BOOLEAN,
    ao_bull BOOLEAN,
    psar_bull BOOLEAN,
    mma_bull BOOLEAN,
    bb_bull BOOLEAN,
    stochrsi_bull BOOLEAN,
    tema_bull BOOLEAN,
    ema100_bull BOOLEAN,
    ema100_bear BOOLEAN,
    ema50_bull BOOLEAN,
    ema50_bear BOOLEAN,
    ema200_bull BOOLEAN,
    ema200_bear BOOLEAN,
    sma100_bull BOOLEAN,
    sma100_bear BOOLEAN,
    sma200_bull BOOLEAN,
    sma200_bear BOOLEAN,
    sma50_bull BOOLEAN,
    sma50_bear BOOLEAN,
    vol_bull BOOLEAN,
    rsi_bull BOOLEAN,
    atr_bull BOOLEAN,
    cci_bull BOOLEAN,
    willr_bull BOOLEAN,
    adx_bull BOOLEAN,
    obv_bull BOOLEAN,
    mom_bull BOOLEAN,
    roc_bull BOOLEAN,
    kc_bull BOOLEAN,
    ichi_bull BOOLEAN,
    adosc_bull BOOLEAN,
    vpt_bull BOOLEAN,
    ema100_above_ema200 BOOLEAN,
    ema100_below_ema200 BOOLEAN,
    sma100_above_sma200 BOOLEAN,
    sma100_below_sma200 BOOLEAN,
    ema100_cross_up_ema200 BOOLEAN,
    ema100_cross_down_ema200 BOOLEAN,
    sma100_cross_up_sma200 BOOLEAN,
    sma100_cross_down_sma200 BOOLEAN,
    stop NUMERIC,
    target NUMERIC,
    rr_ratio NUMERIC,
    score INTEGER NOT NULL,
    PRIMARY KEY (run_id, ticker)
);

CREATE INDEX IF NOT EXISTS idx_screener_runs_started_at
    ON screener_runs(started_at);
CREATE INDEX IF NOT EXISTS idx_screener_results_ticker_date
    ON screener_results(ticker, date);
CREATE INDEX IF NOT EXISTS idx_screener_results_score
    ON screener_results(score);

CREATE TABLE IF NOT EXISTS analysis_runs (
    analysis_run_id UUID PRIMARY KEY,
    screener_run_id UUID REFERENCES screener_runs(run_id),
    started_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ,
    status TEXT NOT NULL DEFAULT 'completed',
    source_file TEXT NOT NULL,
    requested_tickers TEXT NOT NULL,
    min_score NUMERIC,
    top_n INTEGER,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    indicators TEXT NOT NULL,
    rr_ratio NUMERIC NOT NULL,
    price_decimals INTEGER NOT NULL,
    result_count INTEGER NOT NULL DEFAULT 0,
    expected_count INTEGER NOT NULL DEFAULT 0
);

ALTER TABLE analysis_runs
    ADD COLUMN IF NOT EXISTS screener_run_id UUID REFERENCES screener_runs(run_id);
ALTER TABLE analysis_runs
    ALTER COLUMN finished_at DROP NOT NULL;
ALTER TABLE analysis_runs
    ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'completed';
ALTER TABLE analysis_runs
    ADD COLUMN IF NOT EXISTS expected_count INTEGER NOT NULL DEFAULT 0;
UPDATE analysis_runs
SET expected_count = result_count
WHERE expected_count = 0 AND result_count > 0;

CREATE TABLE IF NOT EXISTS analysis_results (
    analysis_run_id UUID NOT NULL REFERENCES analysis_runs(analysis_run_id),
    screener_run_id UUID REFERENCES screener_runs(run_id),
    ticker TEXT NOT NULL,
    as_of DATE NOT NULL,
    captured_at TIMESTAMPTZ NOT NULL,
    open NUMERIC,
    high NUMERIC,
    low NUMERIC,
    close NUMERIC,
    volume NUMERIC,
    ema50 NUMERIC,
    ema100 NUMERIC,
    ema200 NUMERIC,
    rsi_14 NUMERIC,
    atr_14 NUMERIC,
    entry NUMERIC,
    entry_support TEXT,
    stop NUMERIC,
    target NUMERIC,
    risk_per_share NUMERIC,
    actionable BOOLEAN NOT NULL,
    indicators JSONB NOT NULL,
    signals JSONB NOT NULL,
    plan JSONB NOT NULL,
    screener_snapshot JSONB NOT NULL,
    PRIMARY KEY (analysis_run_id, ticker)
);

CREATE INDEX IF NOT EXISTS idx_analysis_runs_started_at
    ON analysis_runs(started_at);
CREATE INDEX IF NOT EXISTS idx_analysis_results_ticker_as_of
    ON analysis_results(ticker, as_of);
CREATE INDEX IF NOT EXISTS idx_analysis_results_screener_run
    ON analysis_results(screener_run_id)
    WHERE screener_run_id IS NOT NULL;
