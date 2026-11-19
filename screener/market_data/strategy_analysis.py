"""Market-data-backed strategy signals and plan levels for manual review."""

import pandas as pd
import yfinance as yf

from screener.domain import indicators as market_indicators


OHLCV_COLUMNS = ("Open", "High", "Low", "Close", "Volume")
INTRADAY_LOOKBACK_DAYS = 59
HOURLY_LOOKBACK_DAYS = 700
FIFTEEN_MINUTE_LOOKBACK_DAYS = 59
FIVE_MINUTE_LOOKBACK_DAYS = 59
LONG_DAILY_LOOKBACK_DAYS = 365 * 8


def _normalize_history(history):
    if isinstance(history.columns, pd.MultiIndex):
        history.columns = history.columns.get_level_values(0)
    missing = set(OHLCV_COLUMNS).difference(history.columns)
    if history.empty or missing:
        return pd.DataFrame(columns=OHLCV_COLUMNS)
    return history.loc[:, OHLCV_COLUMNS].dropna(subset=["Open", "High", "Low", "Close"])


def _smoothed_moving_average(values, length):
    smoothed = pd.Series(float("nan"), index=values.index, dtype=float)
    if len(values) < length:
        return smoothed
    first_value = float(values.iloc[:length].mean())
    smoothed.iloc[length - 1] = first_value
    for index in range(length, len(values)):
        smoothed.iloc[index] = (
            smoothed.iloc[index - 1] * (length - 1) + values.iloc[index]
        ) / length
    return smoothed


def _download_history(ticker, interval, start, end):
    history = yf.download(
        ticker,
        start=start,
        end=end,
        interval=interval,
        progress=False,
        auto_adjust=False,
    )
    history = _normalize_history(history)
    if not history.empty and interval in ("1h", "30m", "15m", "5m"):
        bar_length = {
            "1h": pd.Timedelta(hours=1),
            "30m": pd.Timedelta(minutes=30),
            "15m": pd.Timedelta(minutes=15),
            "5m": pd.Timedelta(minutes=5),
        }[interval]
        timezone = history.index.tz
        now = pd.Timestamp.now(tz=timezone) if timezone is not None else pd.Timestamp.now()
        history = history.loc[history.index + bar_length <= now]
    return history


def _enrich(history):
    if history is None or history.empty:
        return pd.DataFrame()
    history = _normalize_history(history)
    if history.empty:
        return history
    enriched = market_indicators.add_indicators(
        history,
        ["alma", "macd", "rsi", "cci", "psar", "atr", "volume", "bb", "sma200"],
    )
    ta = market_indicators.ta
    enriched["ALMA9"] = ta.alma(
        enriched["Close"], length=9, sigma=6, distribution_offset=0.85
    )
    enriched["EMA9"] = ta.ema(enriched["Close"], length=9)
    enriched["EMA20"] = ta.ema(enriched["Close"], length=20)
    enriched["SMA20"] = ta.sma(enriched["Close"], length=20)
    enriched["SMA40"] = ta.sma(enriched["Close"], length=40)
    enriched["EnvelopeUpper"] = enriched["SMA40"] * 1.03
    enriched["EnvelopeLower"] = enriched["SMA40"] * 0.97
    enriched["Envelope20Lower5"] = enriched["SMA20"] * 0.95
    keltner = ta.kc(
        enriched["High"], enriched["Low"], enriched["Close"],
        length=20, scalar=1.5,
    )
    if keltner is not None:
        enriched = pd.concat([enriched, keltner], axis=1)
    supertrend = ta.supertrend(
        enriched["High"], enriched["Low"], enriched["Close"],
        length=7, multiplier=2.1,
    )
    if supertrend is not None:
        enriched = pd.concat([enriched, supertrend], axis=1)
    median_price = (enriched["High"] + enriched["Low"]) / 2
    for name, length, displacement in (
        ("Jaw", 13, 8),
        ("Teeth", 8, 5),
        ("Lips", 5, 3),
    ):
        smoothed = _smoothed_moving_average(median_price, length)
        enriched[f"Alligator{name}"] = smoothed.shift(displacement)
    trix = ta.trix(enriched["Close"], length=7)
    fisher = ta.fisher(enriched["High"], enriched["Low"], length=9)
    if trix is not None:
        enriched = pd.concat([enriched, trix], axis=1)
    if fisher is not None:
        enriched = pd.concat([enriched, fisher], axis=1)
    return enriched


def _resample_weekly(history):
    if history.empty:
        return history
    weekly = history.resample("W-FRI").agg({
        "Open": "first",
        "High": "max",
        "Low": "min",
        "Close": "last",
        "Volume": "sum",
    }).dropna(subset=["Close"])
    if not history.empty and history.index[-1].weekday() != 4 and len(weekly) > 0:
        weekly = weekly.iloc[:-1]
    return weekly


def _resample_four_hour(history):
    if history.empty:
        return history
    bars = []
    for _, session in history.groupby(history.index.date, sort=True):
        session = session.sort_index()
        complete_count = len(session) // 4
        for block_index in range(complete_count):
            block = session.iloc[block_index * 4:(block_index + 1) * 4]
            bars.append({
                "Date": block.index[-1] + pd.Timedelta(hours=1),
                "Open": block["Open"].iloc[0],
                "High": block["High"].max(),
                "Low": block["Low"].min(),
                "Close": block["Close"].iloc[-1],
                "Volume": block["Volume"].sum(),
            })
    if not bars:
        return pd.DataFrame(columns=OHLCV_COLUMNS)
    return pd.DataFrame(bars).set_index("Date").sort_index()


def _number(row, column):
    value = row.get(column)
    if value is None or pd.isna(value):
        return None
    return float(value)


def _cross_up(previous, latest, first, second):
    previous_first = _number(previous, first)
    previous_second = _number(previous, second)
    latest_first = _number(latest, first)
    latest_second = _number(latest, second)
    return (
        None not in (previous_first, previous_second, latest_first, latest_second)
        and previous_first <= previous_second
        and latest_first > latest_second
    )


def _cross_down(previous, latest, first, second):
    previous_first = _number(previous, first)
    previous_second = _number(previous, second)
    latest_first = _number(latest, first)
    latest_second = _number(latest, second)
    return (
        None not in (previous_first, previous_second, latest_first, latest_second)
        and previous_first >= previous_second
        and latest_first < latest_second
    )


def _as_of(index, timeframe):
    timestamp = pd.Timestamp(index)
    if timeframe in ("5m", "15m", "30m"):
        minutes = {"5m": 5, "15m": 15, "30m": 30}[timeframe]
        timestamp += pd.Timedelta(minutes=minutes)
        return timestamp.isoformat()
    if timeframe == "1h":
        return (timestamp + pd.Timedelta(hours=1)).isoformat()
    if timeframe == "4h":
        return timestamp.isoformat()
    return timestamp.date().isoformat()


def _round(value, decimals=2):
    return None if value is None else round(float(value), decimals)


def _make_plan(
    strategy,
    timeframe,
    history,
    entry_rule,
    exit_rule,
    stop_rule,
    conditions_met=False,
    exit_trigger=False,
    stop=None,
    risk_cap_pct=None,
    risk_cap_inclusive=False,
    data_note=None,
    parameters=None,
):
    if history is None or history.empty or len(history) < 2:
        latest = None
    else:
        latest = history.iloc[-1]

    close = _number(latest, "Close") if latest is not None else None
    stop_value = _number(latest, stop) if isinstance(stop, str) and latest is not None else stop
    if close is None or stop_value is None or stop_value >= close:
        stop_value = None
    risk_pct = (
        (close - stop_value) / close * 100
        if close is not None and stop_value is not None and close > 0 and stop_value < close
        else None
    )
    if risk_cap_pct is None:
        risk_ok = True
    elif risk_pct is None:
        risk_ok = False
    elif risk_cap_inclusive:
        risk_ok = risk_pct <= risk_cap_pct
    else:
        risk_ok = risk_pct < risk_cap_pct
    entry_trigger = bool(conditions_met and risk_ok)

    if data_note:
        status = "UNAVAILABLE"
    elif exit_trigger:
        status = "EXIT_TRIGGERED"
    elif conditions_met and not risk_ok:
        status = "RISK_TOO_HIGH"
    elif entry_trigger:
        status = "ENTRY_TRIGGERED"
    else:
        status = "WATCH"

    return {
        "strategy": strategy,
        "timeframe": timeframe,
        "as_of": _as_of(history.index[-1], timeframe) if latest is not None else None,
        "status": status,
        "conditions_met": bool(conditions_met),
        "entry_trigger": entry_trigger,
        "exit_trigger": bool(exit_trigger),
        "entry_rule": entry_rule,
        "entry": _round(close) if entry_trigger else None,
        "reference_close": _round(close),
        "stop_rule": stop_rule,
        "stop": _round(stop_value),
        "risk_pct": _round(risk_pct),
        "risk_cap_pct": risk_cap_pct,
        "target": None,
        "target_rule": "No fixed profit target was specified; use the strategy exit rule.",
        "exit_rule": exit_rule,
        "data_note": data_note,
        "parameters": parameters or {},
    }


def _unavailable(strategy, timeframe, note):
    return _make_plan(
        strategy, timeframe, None,
        "Required market history is unavailable.",
        "Required market history is unavailable.",
        "No stop calculated.",
        data_note=note,
    )


def _mama_plan(enriched, timeframe, risk_cap_pct):
    strategy = "MAMA"
    if len(enriched) < 35:
        return _unavailable(strategy, timeframe, "Insufficient bars for ALMA and MACD.")
    latest, previous = enriched.iloc[-1], enriched.iloc[-2]
    close = _number(latest, "Close")
    alma = _number(latest, "ALMA")
    prev_close = _number(previous, "Close")
    prev_alma = _number(previous, "ALMA")
    macd_values = (
        _number(previous, "MACD_12_26_9"),
        _number(previous, "MACDs_12_26_9"),
        _number(latest, "MACD_12_26_9"),
        _number(latest, "MACDs_12_26_9"),
    )
    required = (close, alma, prev_close, prev_alma, *macd_values)
    if None in required:
        return _unavailable(strategy, timeframe, "ALMA, MACD, or price values are missing.")
    entry_conditions = (
        prev_close <= prev_alma
        and close > alma
        and _cross_up(previous, latest, "MACD_12_26_9", "MACDs_12_26_9")
    )
    exit_trigger = (
        _number(latest, "Open") is not None
        and _number(latest, "Open") < alma
        and close < alma
    )
    plan = _make_plan(
        strategy,
        timeframe,
        enriched,
        "Completed candle closes above ALMA as MACD crosses bullish.",
        "Open and close both finish below ALMA.",
        "ALMA support; entry risk must be strictly below 5%.",
        conditions_met=entry_conditions,
        exit_trigger=exit_trigger,
        stop="ALMA",
        risk_cap_pct=risk_cap_pct,
    )
    return plan


def _papa_plan(enriched, macd_zero_tolerance_pct):
    strategy = "PAPA"
    timeframe = "1d"
    if len(enriched) < 42:
        return _unavailable(strategy, timeframe, "Insufficient bars for SMA40, envelope, and MACD.")
    latest, previous = enriched.iloc[-1], enriched.iloc[-2]
    close = _number(latest, "Close")
    prior_close = _number(previous, "Close")
    upper = _number(latest, "EnvelopeUpper")
    prior_upper = _number(previous, "EnvelopeUpper")
    midline = _number(latest, "SMA40")
    macd = _number(latest, "MACD_12_26_9")
    signal = _number(latest, "MACDs_12_26_9")
    if None in (close, prior_close, upper, prior_upper, midline, macd, signal):
        return _unavailable(strategy, timeframe, "Envelope or MACD values are missing.")
    if _number(previous, "MACD_12_26_9") is None or _number(previous, "MACDs_12_26_9") is None:
        return _unavailable(strategy, timeframe, "Previous MACD values are missing.")
    macd_cross = _cross_up(previous, latest, "MACD_12_26_9", "MACDs_12_26_9")
    tolerance = abs(close) * macd_zero_tolerance_pct / 100
    near_or_below_zero = max(macd, signal) <= tolerance
    entry_conditions = prior_close <= prior_upper and close > upper and macd_cross and near_or_below_zero
    exit_trigger = close < midline or (
        _number(previous, "MACD_12_26_9") is not None
        and macd < _number(previous, "MACD_12_26_9")
    )
    return _make_plan(
        strategy,
        timeframe,
        enriched,
        "Daily close breaks above the 40-SMA upper envelope and MACD crosses bullish at/below the configured zero tolerance.",
        "Daily close below the 40-SMA midline or MACD line turns down.",
        "40-SMA envelope midline.",
        conditions_met=entry_conditions,
        exit_trigger=exit_trigger,
        stop="SMA40",
        parameters={"envelope_period": 40, "envelope_deviation_pct": 3.0,
                    "macd_zero_tolerance_pct": macd_zero_tolerance_pct},
    )


def _tita_plan(enriched, rsi_threshold, risk_cap_pct):
    strategy = "TITA"
    timeframe = "1d"
    if len(enriched) < 35:
        return _unavailable(strategy, timeframe, "Insufficient bars for ALMA and RSI.")
    latest, previous = enriched.iloc[-1], enriched.iloc[-2]
    close = _number(latest, "Close")
    alma = _number(latest, "ALMA")
    prev_close = _number(previous, "Close")
    prev_alma = _number(previous, "ALMA")
    rsi = _number(latest, "RSI_14")
    previous_rsi = _number(previous, "RSI_14")
    if None in (close, alma, prev_close, prev_alma, rsi, previous_rsi):
        return _unavailable(strategy, timeframe, "ALMA, RSI, or price values are missing.")
    entry_conditions = (
        prev_close <= prev_alma
        and close > alma
        and previous_rsi <= rsi_threshold
        and rsi > rsi_threshold
    )
    return _make_plan(
        strategy,
        timeframe,
        enriched,
        f"Daily close crosses above ALMA as RSI crosses above {rsi_threshold:g}.",
        "Daily close below ALMA support.",
        "ALMA support; risk from entry to ALMA must be at most 5%.",
        conditions_met=entry_conditions,
        exit_trigger=close < alma,
        stop="ALMA",
        risk_cap_pct=risk_cap_pct,
        risk_cap_inclusive=True,
        parameters={"rsi_threshold": rsi_threshold},
    )


def _calma_plan(enriched):
    strategy = "CALMA"
    timeframe = "1wk"
    if len(enriched) < 25:
        return _unavailable(strategy, timeframe, "Insufficient completed weekly bars for ALMA and CCI.")
    latest, previous = enriched.iloc[-1], enriched.iloc[-2]
    close = _number(latest, "Close")
    alma = _number(latest, "ALMA")
    cci = _number(latest, "CCI_20")
    previous_cci = _number(previous, "CCI_20")
    if None in (close, alma, cci, previous_cci):
        return _unavailable(strategy, timeframe, "Weekly ALMA or CCI values are missing.")
    entry_conditions = previous_cci <= 100 and cci > 100 and close > alma
    return _make_plan(
        strategy,
        timeframe,
        enriched,
        "Completed weekly CCI crosses above +100 while weekly close is above ALMA.",
        "Completed weekly close below ALMA.",
        "Weekly ALMA trend support.",
        conditions_met=entry_conditions,
        exit_trigger=close < alma,
        stop="ALMA",
    )


def _fishball_plan(enriched, support_lookback):
    strategy = "FISHBALL"
    timeframe = "30m"
    minimum_bars = max(support_lookback + 3, 35)
    if len(enriched) < minimum_bars:
        return _unavailable(strategy, timeframe, "Insufficient 30-minute bars for support, Fisher, and TRIX.")
    latest, previous = enriched.iloc[-1], enriched.iloc[-2]
    support = (
        float(enriched.iloc[-support_lookback - 1:-1]["Low"].min())
        if not enriched.iloc[-support_lookback - 1:-1].empty else None
    )
    close = _number(latest, "Close")
    low = _number(latest, "Low")
    volume = _number(latest, "Volume")
    volume_avg = float(enriched["Volume"].iloc[-21:-1].mean())
    fisher_cross = _cross_up(previous, latest, "FISHERT_9_1", "FISHERTs_9_1")
    trix = _number(latest, "TRIX_7_9")
    previous_trix = _number(previous, "TRIX_7_9")
    earlier_trix = _number(enriched.iloc[-3], "TRIX_7_9")
    fisher_values = (
        _number(previous, "FISHERT_9_1"),
        _number(previous, "FISHERTs_9_1"),
        _number(latest, "FISHERT_9_1"),
        _number(latest, "FISHERTs_9_1"),
    )
    if (
        None in (support, close, low, volume, trix, previous_trix, earlier_trix, *fisher_values)
        or pd.isna(volume_avg)
    ):
        return _unavailable(strategy, timeframe, "Support, Fisher, TRIX, or volume values are missing.")
    support_test = low <= support * 1.02 and close >= support
    high_volume = volume > volume_avg
    trix_turn_up = trix > previous_trix and previous_trix <= earlier_trix
    entry_conditions = support_test and high_volume and fisher_cross and trix_turn_up
    exit_trigger = _cross_down(previous, latest, "FISHERT_9_1", "FISHERTs_9_1")
    return _make_plan(
        strategy,
        timeframe,
        enriched,
        f"30-minute price tests prior {support_lookback}-bar low within 2%, volume exceeds its 20-bar average, Fisher crosses bullish, and TRIX turns up.",
        "30-minute Fisher line crosses back below its signal line.",
        f"Prior {support_lookback}-bar support.",
        conditions_met=entry_conditions,
        exit_trigger=exit_trigger,
        stop=support,
        parameters={"support_lookback": support_lookback, "support_proximity_pct": 2.0,
                    "volume_average_period": 20, "trix_period": 7, "fisher_period": 9},
    )


def _bopis_plan(enriched):
    strategy = "BOPIS"
    timeframe = "1d"
    if len(enriched) < 35:
        return _unavailable(strategy, timeframe, "Insufficient daily bars for PSAR, EMA9, and TRIX.")
    latest, previous = enriched.iloc[-1], enriched.iloc[-2]
    close = _number(latest, "Close")
    prev_close = _number(previous, "Close")
    ema9 = _number(latest, "EMA9")
    previous_ema9 = _number(previous, "EMA9")
    trix = _number(latest, "TRIX_7_9")
    previous_trix = _number(previous, "TRIX_7_9")
    previous_psar_short = _number(previous, "PSARs_0.02_0.2")
    current_psar_long = _number(latest, "PSARl_0.02_0.2")
    if None in (close, prev_close, ema9, previous_ema9, trix, previous_trix):
        return _unavailable(strategy, timeframe, "EMA9, TRIX, or price values are missing.")
    if not {"PSARl_0.02_0.2", "PSARs_0.02_0.2"}.issubset(enriched.columns):
        return _unavailable(strategy, timeframe, "Parabolic SAR values are missing.")
    previous_psar_long = _number(previous, "PSARl_0.02_0.2")
    current_psar_short = _number(latest, "PSARs_0.02_0.2")
    if previous_psar_long is None and previous_psar_short is None:
        return _unavailable(strategy, timeframe, "Previous Parabolic SAR direction is missing.")
    if current_psar_long is None and current_psar_short is None:
        return _unavailable(strategy, timeframe, "Current Parabolic SAR direction is missing.")
    psar_flipped_bullish = (
        previous_psar_short is not None
        and previous_psar_short > prev_close
        and current_psar_long is not None
        and current_psar_long < close
    )
    entry_conditions = (
        psar_flipped_bullish
        and close > ema9
        and trix > 0
        and (previous_trix <= 0 or trix > previous_trix)
    )
    exit_trigger = close < ema9 and prev_close < previous_ema9
    return _make_plan(
        strategy,
        timeframe,
        enriched,
        "Daily PSAR flips below price, close is above EMA9, and TRIX is above zero and crosses/rises.",
        "Two consecutive daily closes below EMA9 confirm failure to reclaim it.",
        "EMA9 support.",
        conditions_met=entry_conditions,
        exit_trigger=exit_trigger,
        stop="EMA9",
        parameters={"ema_period": 9, "trix_period": 7},
    )


def _bunso_plan(enriched, timeframe, daily_history, consolidation_range_pct=5.0):
    strategy = "BUNSO"
    minimum_bars = 35
    if len(enriched) < minimum_bars:
        return _unavailable(strategy, timeframe, "Insufficient intraday bars for ALMA9, RSI, and volume.")
    if daily_history is None or len(daily_history) < 253:
        return _unavailable(strategy, timeframe, "Insufficient daily bars to confirm a 52-week high.")

    latest, previous = enriched.iloc[-1], enriched.iloc[-2]
    close = _number(latest, "Close")
    alma = _number(latest, "ALMA9")
    rsi = _number(latest, "RSI_14")
    previous_rsi = _number(previous, "RSI_14")
    volume = _number(latest, "Volume")
    prior_bars = enriched.iloc[-21:-1]
    if prior_bars.empty:
        return _unavailable(strategy, timeframe, "Previous 20 intraday bars are missing.")
    prior_high = float(prior_bars["High"].max())
    volume_average = float(prior_bars["Volume"].mean())
    consolidation_low = float(prior_bars["Low"].min())
    consolidation_width_pct = (
        (prior_high - consolidation_low) / close * 100 if close and close > 0 else None
    )
    if None in (close, alma, rsi, previous_rsi, volume) or pd.isna(volume_average):
        return _unavailable(strategy, timeframe, "ALMA9, RSI, or volume values are missing.")

    current_day = pd.Timestamp(enriched.index[-1]).date()
    daily_dates = pd.Index(pd.to_datetime(daily_history.index).date)
    completed_daily = daily_history.loc[daily_dates < current_day]
    if len(completed_daily) < 252:
        return _unavailable(strategy, timeframe, "Insufficient completed daily bars to confirm a 52-week high.")
    prior_52_week_high = float(completed_daily["High"].iloc[-252:].max())
    new_52_week_high = close > prior_52_week_high
    consolidation = (
        consolidation_width_pct is not None
        and consolidation_width_pct <= consolidation_range_pct
    )
    breakout = close > prior_high
    entry_conditions = (
        consolidation
        and breakout
        and volume > 2 * volume_average
        and previous_rsi <= 70 < rsi
        and close > alma
        and new_52_week_high
    )
    exit_trigger = close < alma or rsi < 65
    plan = _make_plan(
        strategy,
        timeframe,
        enriched,
        f"Close breaks above the prior 20-bar consolidation on more than 2x average volume, RSI crosses above 70, price is above ALMA9, and makes a 52-week high.",
        "Close below ALMA9 or RSI below 65.",
        "ALMA9 trailing support.",
        conditions_met=entry_conditions,
        exit_trigger=exit_trigger,
        stop="ALMA9",
        parameters={
            "alma_length": 9,
            "alma_offset": 0.85,
            "alma_sigma": 6,
            "rsi_period": 14,
            "rsi_entry_cross": 70,
            "rsi_exit_level": 65,
            "volume_average_period": 20,
            "volume_multiplier": 2.0,
            "consolidation_lookback": 20,
            "consolidation_max_range_pct": consolidation_range_pct,
            "requires_52_week_high": True,
            "prior_52_week_high": _round(prior_52_week_high),
        },
    )
    plan["manual_precondition"] = (
        "Volume is only a momentum proxy; OHLCV data cannot identify institutional buying."
    )
    return plan


def _lolo_plan(enriched, macd_zero_tolerance_pct):
    strategy = "LOLO"
    timeframe = "1wk"
    if len(enriched) < 200:
        return _unavailable(strategy, timeframe, "Insufficient completed weekly bars for SMA200.")
    latest, previous = enriched.iloc[-1], enriched.iloc[-2]
    close = _number(latest, "Close")
    sma200 = _number(latest, "SMA200")
    macd = _number(latest, "MACD_12_26_9")
    signal = _number(latest, "MACDs_12_26_9")
    previous_macd = _number(previous, "MACD_12_26_9")
    previous_signal = _number(previous, "MACDs_12_26_9")
    if None in (close, sma200, macd, signal, previous_macd, previous_signal):
        return _unavailable(strategy, timeframe, "Weekly SMA200 or MACD values are missing.")
    tolerance = abs(close) * macd_zero_tolerance_pct / 100
    near_or_below_zero = max(macd, signal) <= tolerance
    bullish_cross = _cross_up(previous, latest, "MACD_12_26_9", "MACDs_12_26_9")
    bearish_cross = _cross_down(previous, latest, "MACD_12_26_9", "MACDs_12_26_9")
    entry_conditions = close > sma200 and bullish_cross and near_or_below_zero
    macro_top_bearish_cross = bearish_cross and macd > 0
    exit_trigger = close < sma200 or macro_top_bearish_cross
    plan = _make_plan(
        strategy,
        timeframe,
        enriched,
        "Completed weekly close is above SMA200 and MACD crosses bullish below or within the configured zero-line tolerance.",
        "Completed weekly close below SMA200, or bearish MACD crossover while MACD is above zero (macro-top approximation).",
        "Weekly SMA200 structural trend support.",
        conditions_met=entry_conditions,
        exit_trigger=exit_trigger,
        stop="SMA200",
        parameters={
            "sma_period": 200,
            "macd_fast": 12,
            "macd_slow": 26,
            "macd_signal": 9,
            "macd_zero_tolerance_pct": macd_zero_tolerance_pct,
            "macro_top_approximation": "bearish MACD crossover with MACD line above zero",
        },
    )
    plan["manual_precondition"] = (
        "Verify index membership, dividend profile, and company quality separately; "
        "these are not assessed by price-history data."
    )
    return plan


def _tito_plan(enriched):
    strategy = "TITO"
    timeframe = "1d"
    if len(enriched) < 35:
        return _unavailable(strategy, timeframe, "Insufficient daily bars for Bollinger Bands, Keltner Channels, and MACD.")
    latest, previous = enriched.iloc[-1], enriched.iloc[-2]
    close = _number(latest, "Close")
    previous_close = _number(previous, "Close")
    upper = _number(latest, "BBU_20_2.0")
    previous_upper = _number(previous, "BBU_20_2.0")
    midline = _number(latest, "SMA20")
    previous_bb_lower = _number(previous, "BBL_20_2.0")
    previous_keltner_upper = _number(previous, "KCUe_20_1.5")
    previous_keltner_lower = _number(previous, "KCLe_20_1.5")
    macd_hist = _number(latest, "MACDh_12_26_9")
    previous_macd_hist = _number(previous, "MACDh_12_26_9")
    if None in (
        close, previous_close, upper, previous_upper, midline, previous_bb_lower,
        previous_keltner_upper, previous_keltner_lower, macd_hist, previous_macd_hist,
    ):
        return _unavailable(strategy, timeframe, "Bollinger, Keltner, SMA20, or MACD histogram values are missing.")
    squeeze = (
        previous_bb_lower > previous_keltner_lower
        and previous_upper < previous_keltner_upper
    )
    breakout = previous_close <= previous_upper and close > upper
    entry_conditions = squeeze and breakout and macd_hist > previous_macd_hist
    partial_exit_trigger = previous_close > previous_upper and close <= upper
    remaining_exit_trigger = close < midline
    plan = _make_plan(
        strategy,
        timeframe,
        enriched,
        "Daily close breaks above the upper Bollinger Band after the prior candle's Bollinger Bands were inside the Keltner Channels, with MACD histogram expanding upward.",
        "Take 50% off when the close crosses back inside the upper Bollinger Band; exit the remaining position when the close falls below the 20-SMA midline.",
        "20-SMA midline for the remaining position.",
        conditions_met=entry_conditions,
        exit_trigger=partial_exit_trigger or remaining_exit_trigger,
        stop="SMA20",
        parameters={
            "bollinger_period": 20,
            "bollinger_stddev": 2.0,
            "keltner_period": 20,
            "keltner_atr_multiplier": 1.5,
            "macd_fast": 12,
            "macd_slow": 26,
            "macd_signal": 9,
        },
    )
    plan["partial_exit_trigger"] = partial_exit_trigger
    plan["remaining_exit_trigger"] = remaining_exit_trigger
    plan["partial_exit_rule"] = "Close crosses back inside the upper Bollinger Band; exit 50%."
    plan["remaining_exit_rule"] = "Close below the 20-SMA midline; exit the remaining position."
    return plan


def _kasambahay_plan(enriched):
    strategy = "KASAMBAHAY"
    timeframe = "1d"
    if len(enriched) < 35:
        return _unavailable(strategy, timeframe, "Insufficient daily bars for 20-SMA envelope and RSI.")
    latest = enriched.iloc[-1]
    close = _number(latest, "Close")
    low = _number(latest, "Low")
    high = _number(latest, "High")
    lower = _number(latest, "Envelope20Lower5")
    midline = _number(latest, "SMA20")
    rsi = _number(latest, "RSI_14")
    if None in (close, low, high, lower, midline, rsi):
        return _unavailable(strategy, timeframe, "20-SMA envelope or RSI values are missing.")
    entry_conditions = (low <= lower or close < lower) and rsi < 30
    exit_trigger = high >= midline
    plan = _make_plan(
        strategy,
        timeframe,
        enriched,
        "Daily low pierces or close falls below the 20-SMA lower envelope (5%) while RSI is below 30.",
        "Exit when the daily high touches or crosses the 20-SMA envelope midline.",
        "No initial stop specified by the strategy; risk is not calculated.",
        conditions_met=entry_conditions,
        exit_trigger=exit_trigger,
        parameters={
            "envelope_period": 20,
            "envelope_deviation_pct": 5.0,
            "rsi_period": 14,
            "rsi_entry_level": 30,
            "exit_level": "20-SMA midline",
        },
    )
    plan["manual_precondition"] = (
        "Verify company quality and that the sell-off is temporary separately; "
        "these are not assessed by price-history data."
    )
    return plan


def _supertrend_plan(enriched, timeframe):
    strategy = "SUPERTREND"
    if len(enriched) < 10:
        return _unavailable(strategy, timeframe, "Insufficient bars for Supertrend(7, 2.1) and EMA9.")
    latest, previous = enriched.iloc[-1], enriched.iloc[-2]
    close = _number(latest, "Close")
    ema9 = _number(latest, "EMA9")
    direction = _number(latest, "SUPERTd_7_2.1")
    previous_direction = _number(previous, "SUPERTd_7_2.1")
    if None in (close, ema9, direction, previous_direction):
        return _unavailable(strategy, timeframe, "Supertrend direction or EMA9 values are missing.")
    flipped_green = previous_direction < 0 and direction > 0
    flipped_red = previous_direction > 0 and direction < 0
    entry_conditions = flipped_green and close > ema9
    exit_trigger = close < ema9 or flipped_red
    return _make_plan(
        strategy,
        timeframe,
        enriched,
        f"Supertrend(7, 2.1) flips bullish and the completed {timeframe} close is above EMA9.",
        "Completed candle closes below EMA9 or Supertrend flips bearish.",
        "Supertrend line while bullish.",
        conditions_met=entry_conditions,
        exit_trigger=exit_trigger,
        stop="SUPERTl_7_2.1" if direction > 0 else None,
        parameters={"supertrend_length": 7, "supertrend_multiplier": 2.1, "ema_period": 9},
    )


def _alligator_plan(enriched, spread_min_pct=0.5):
    strategy = "ALLIGATOR"
    timeframe = "1d"
    if len(enriched) < 40:
        return _unavailable(strategy, timeframe, "Insufficient daily bars for Williams Alligator and MACD.")
    latest, previous = enriched.iloc[-1], enriched.iloc[-2]
    close = _number(latest, "Close")
    jaw = _number(latest, "AlligatorJaw")
    teeth = _number(latest, "AlligatorTeeth")
    lips = _number(latest, "AlligatorLips")
    previous_jaw = _number(previous, "AlligatorJaw")
    previous_teeth = _number(previous, "AlligatorTeeth")
    previous_lips = _number(previous, "AlligatorLips")
    macd_hist = _number(latest, "MACDh_12_26_9")
    previous_macd_hist = _number(previous, "MACDh_12_26_9")
    if None in (
        close, jaw, teeth, lips, previous_jaw, previous_teeth, previous_lips,
        macd_hist, previous_macd_hist,
    ):
        return _unavailable(strategy, timeframe, "Alligator lines or MACD histogram values are missing.")
    ordered = lips > teeth > jaw
    was_ordered = previous_lips > previous_teeth > previous_jaw
    spread_pct = (lips - jaw) / close * 100 if close > 0 else 0
    previous_spread_pct = (
        (previous_lips - previous_jaw) / close * 100 if close > 0 else 0
    )
    expanding_green_histogram = macd_hist > 0 and macd_hist > previous_macd_hist
    entry_conditions = (
        ordered and not was_ordered and spread_pct >= spread_min_pct
        and expanding_green_histogram
    )
    crossed_or_intersecting = not ordered
    exit_trigger = (
        close < teeth
        and (
            crossed_or_intersecting
            or (spread_pct < previous_spread_pct and spread_pct < spread_min_pct)
        )
    )
    plan = _make_plan(
        strategy,
        timeframe,
        enriched,
        "Daily Alligator Lips > Teeth > Jaw fan out by at least the configured spread while MACD histogram is positive and expanding.",
        "Daily close below Alligator Teeth as the lines lose bullish order or contract back toward one another.",
        "Alligator Teeth trend support.",
        conditions_met=entry_conditions,
        exit_trigger=exit_trigger,
        stop="AlligatorTeeth",
        parameters={
            "jaw_period": 13,
            "jaw_forward_shift": 8,
            "teeth_period": 8,
            "teeth_forward_shift": 5,
            "lips_period": 5,
            "lips_forward_shift": 3,
            "minimum_fan_spread_pct": spread_min_pct,
            "spread_is_williams_alligator_approximation": True,
            "macd_histogram_expanding": True,
        },
    )
    plan["alligator_spread_pct"] = _round(spread_pct)
    return plan


def _bread_and_butter_plan(enriched, timeframe, volume_multiplier=1.5):
    strategy = "BREAD_AND_BUTTER"
    minimum_bars = 42
    if len(enriched) < minimum_bars:
        return _unavailable(strategy, timeframe, "Insufficient bars for EMA20, breakout resistance, and volume.")
    latest = enriched.iloc[-1]
    close = _number(latest, "Close")
    open_price = _number(latest, "Open")
    low = _number(latest, "Low")
    high = _number(latest, "High")
    ema20 = _number(latest, "EMA20")
    if None in (close, open_price, low, high, ema20):
        return _unavailable(strategy, timeframe, "Price or EMA20 values are missing.")

    breakout = None
    first_candidate = max(20, len(enriched) - 11)
    last_candidate = len(enriched) - 1
    for index in range(first_candidate, last_candidate):
        row = enriched.iloc[index]
        previous_bars = enriched.iloc[index - 20:index]
        resistance = float(previous_bars["High"].max())
        average_volume = float(previous_bars["Volume"].mean())
        candidate_close = _number(row, "Close")
        candidate_volume = _number(row, "Volume")
        if (
            candidate_close is not None
            and candidate_volume is not None
            and not pd.isna(average_volume)
            and candidate_close > resistance
            and candidate_volume > average_volume * volume_multiplier
        ):
            breakout = {"index": index, "resistance": resistance}

    ema_retest = low <= ema20 * 1.01 and close >= ema20
    bullish_reversal = close > open_price
    entry_conditions = breakout is not None and ema_retest and bullish_reversal
    target_lookback = 252 if timeframe == "1d" else 252 * 7
    prior_high = float(
        enriched.iloc[max(0, len(enriched) - target_lookback - 1):-1]["High"].max()
    )
    target = prior_high if prior_high > close else None
    exit_at_resistance = target is not None and high >= target
    exit_below_ema = close < ema20
    plan = _make_plan(
        strategy,
        timeframe,
        enriched,
        f"Within the prior 10 bars, price broke above the previous 20-bar resistance on more than {volume_multiplier:g}x average volume; enter on a bullish EMA20 retest candle.",
        f"Completed candle closes below EMA20 or reaches the prior {target_lookback}-bar high resistance proxy.",
        "EMA20 trailing support.",
        conditions_met=entry_conditions,
        exit_trigger=exit_below_ema or exit_at_resistance,
        stop="EMA20",
        parameters={
            "ema_period": 20,
            "resistance_lookback": 20,
            "breakout_retest_window": 10,
            "high_volume_multiplier": volume_multiplier,
            "ema_retest_tolerance_pct": 1.0,
            "bullish_reversal_approximation": "close above open",
            "resistance_target_lookback": target_lookback,
            "resistance_target_approximation": "highest high in the prior timeframe lookback",
        },
    )
    plan["target"] = _round(target)
    plan["target_rule"] = (
        "Prior 252-bar high used as a historical resistance proxy."
        if target is not None
        else "No prior resistance above the latest close was identified."
    )
    plan["breakout_resistance"] = (
        _round(breakout["resistance"]) if breakout is not None else None
    )
    plan["exit_at_resistance_trigger"] = bool(exit_at_resistance)
    plan["exit_below_ema_trigger"] = bool(exit_below_ema)
    return plan


def analyze_strategy_histories(
    ticker,
    daily_history,
    hourly_history=None,
    intraday_history=None,
    fifteen_minute_history=None,
    long_daily_history=None,
    five_minute_history=None,
    rsi_threshold=55.0,
    macd_zero_tolerance_pct=0.5,
    support_lookback=20,
    history_notes=None,
):
    """Evaluate manual-review setups from supplied OHLCV histories."""
    if not 50 <= rsi_threshold <= 55:
        raise ValueError("rsi_threshold must be between 50 and 55")
    if macd_zero_tolerance_pct < 0:
        raise ValueError("macd_zero_tolerance_pct cannot be negative")
    if support_lookback < 2:
        raise ValueError("support_lookback must be at least 2")

    history_notes = history_notes or {}
    daily = _enrich(daily_history)
    weekly = _enrich(_resample_weekly(daily_history))
    long_weekly = _enrich(_resample_weekly(long_daily_history)) if long_daily_history is not None else weekly
    four_hour = _enrich(_resample_four_hour(hourly_history)) if hourly_history is not None else pd.DataFrame()
    thirty_minute = _enrich(intraday_history) if intraday_history is not None else pd.DataFrame()
    fifteen_minute = _enrich(fifteen_minute_history) if fifteen_minute_history is not None else pd.DataFrame()
    five_minute = _enrich(five_minute_history) if five_minute_history is not None else pd.DataFrame()
    hourly = _enrich(hourly_history) if hourly_history is not None else pd.DataFrame()

    plans = {
        "MAMA_daily": _mama_plan(daily, "1d", 5.0),
        "MAMA_4h": _mama_plan(four_hour, "4h", 5.0),
        "PAPA_daily": _papa_plan(daily, macd_zero_tolerance_pct),
        "TITA_daily": _tita_plan(daily, rsi_threshold, 5.0),
        "CALMA_weekly": _calma_plan(weekly),
        "FISHBALL_30m": _fishball_plan(thirty_minute, support_lookback),
        "BOPIS_daily": _bopis_plan(daily),
        "BUNSO_15m": _bunso_plan(fifteen_minute, "15m", daily_history),
        "BUNSO_1h": _bunso_plan(hourly, "1h", daily_history),
        "LOLO_weekly": _lolo_plan(long_weekly, macd_zero_tolerance_pct),
        "TITO_daily": _tito_plan(daily),
        "KASAMBAHAY_daily": _kasambahay_plan(daily),
        "SUPERTREND_daily": _supertrend_plan(daily, "1d"),
        "SUPERTREND_5m": _supertrend_plan(five_minute, "5m"),
        "SUPERTREND_15m": _supertrend_plan(fifteen_minute, "15m"),
        "ALLIGATOR_daily": _alligator_plan(daily),
        "BREAD_AND_BUTTER_daily": _bread_and_butter_plan(daily, "1d"),
        "BREAD_AND_BUTTER_1h": _bread_and_butter_plan(hourly, "1h"),
    }
    for key, note in history_notes.items():
        if note and plans[key]["status"] == "UNAVAILABLE":
            plans[key]["data_note"] = note
    return {"ticker": ticker, "strategies": plans}


def fetch_strategy_plans(
    ticker,
    daily_history,
    rsi_threshold=55.0,
    macd_zero_tolerance_pct=0.5,
    support_lookback=20,
):
    """Fetch available timeframe histories and evaluate the manual-review plans.

    Yahoo's intraday history limits are respected; unavailable timeframes are
    represented by strategy plans with an ``UNAVAILABLE`` status and a data
    note rather than being treated as an entry signal.

    Args:
        ticker: Yahoo Finance symbol.
        daily_history: Daily OHLCV history, normally already retrieved by the
            calling analysis workflow.
        rsi_threshold: TITA entry threshold supported by the strategy rules.
        macd_zero_tolerance_pct: PAPA MACD zero-line tolerance as a percent of
            price.
        support_lookback: Number of prior bars used by FISHBALL support rules.

    Returns:
        Mapping containing the ticker, all configured strategy plans, and the
        parameters used to evaluate them.
    """
    now = pd.Timestamp.now().normalize()
    end = (now + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    hourly_start = (now - pd.Timedelta(days=HOURLY_LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    intraday_start = (now - pd.Timedelta(days=INTRADAY_LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    fifteen_minute_start = (now - pd.Timedelta(days=FIFTEEN_MINUTE_LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    notes = {}

    hourly = _download_history(ticker, "1h", hourly_start, end)
    if hourly.empty:
        notes["MAMA_4h"] = "Yahoo Finance returned no hourly bars in its available history window."
        notes["BUNSO_1h"] = "Yahoo Finance returned no hourly bars in its available history window."
        notes["BREAD_AND_BUTTER_1h"] = "Yahoo Finance returned no hourly bars in its available history window."

    intraday = _download_history(ticker, "30m", intraday_start, end)
    if intraday.empty:
        notes["FISHBALL_30m"] = (
            f"Yahoo Finance returned no 30-minute bars in the last {INTRADAY_LOOKBACK_DAYS} days."
        )

    fifteen_minute = _download_history(ticker, "15m", fifteen_minute_start, end)
    if fifteen_minute.empty:
        notes["BUNSO_15m"] = (
            f"Yahoo Finance returned no 15-minute bars in the last {FIFTEEN_MINUTE_LOOKBACK_DAYS} days."
        )
        notes["SUPERTREND_15m"] = (
            f"Yahoo Finance returned no 15-minute bars in the last {FIFTEEN_MINUTE_LOOKBACK_DAYS} days."
        )

    five_minute_start = (now - pd.Timedelta(days=FIVE_MINUTE_LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    five_minute = _download_history(ticker, "5m", five_minute_start, end)
    if five_minute.empty:
        notes["SUPERTREND_5m"] = (
            f"Yahoo Finance returned no 5-minute bars in the last {FIVE_MINUTE_LOOKBACK_DAYS} days."
        )

    long_daily = daily_history
    if len(_resample_weekly(daily_history)) < 200:
        long_daily_start = (now - pd.Timedelta(days=LONG_DAILY_LOOKBACK_DAYS)).strftime("%Y-%m-%d")
        long_daily = _download_history(ticker, "1d", long_daily_start, end)
    if len(_resample_weekly(long_daily)) < 200:
        notes["LOLO_weekly"] = "Fewer than 200 completed weekly bars are available for the weekly SMA200."

    analysis = analyze_strategy_histories(
        ticker,
        daily_history,
        hourly_history=hourly,
        intraday_history=intraday,
        fifteen_minute_history=fifteen_minute,
        long_daily_history=long_daily,
        five_minute_history=five_minute,
        rsi_threshold=rsi_threshold,
        macd_zero_tolerance_pct=macd_zero_tolerance_pct,
        support_lookback=support_lookback,
        history_notes=notes,
    )
    analysis["parameters"] = {
        "rsi_threshold": rsi_threshold,
        "macd_zero_tolerance_pct": macd_zero_tolerance_pct,
        "fishball_support_lookback": support_lookback,
        "fishball_volume_average_period": 20,
        "bunso_volume_multiplier": 2.0,
        "bunso_consolidation_lookback": 20,
        "bunso_consolidation_max_range_pct": 5.0,
        "bunso_requires_52_week_high": True,
        "alligator_fan_spread_min_pct": 0.5,
        "bread_and_butter_breakout_volume_multiplier": 1.5,
        "bread_and_butter_ema_retest_tolerance_pct": 1.0,
        "supertrend_length": 7,
        "supertrend_multiplier": 2.1,
        "protective_stops": "strategy indicator/support levels; no stop invented when unavailable",
        "manual_review_only": True,
    }
    return analysis
