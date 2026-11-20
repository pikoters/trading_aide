"""Technical indicators, projected levels, and simple screening signals.

The public functions in this module use pandas rows/DataFrames with Yahoo-style
OHLCV columns (``Open``, ``High``, ``Low``, ``Close``, and ``Volume``). Indicator
selectors are lowercase names; the calculated column names follow the existing
screening and persistence contracts.
"""

from contextlib import contextmanager

import pandas as pd

try:
    import pandas_ta_classic as ta
except ImportError:
    try:
        import pandas_ta as ta
    except ImportError:
        raise ImportError(
            "pandas-ta-classic is required: python3 -m pip install pandas-ta-classic"
        ) from None


class IndicatorCalculationError(RuntimeError):
    """Raised when an individual requested technical indicator cannot be calculated."""


# Default selector set used when a caller does not request indicators explicitly.
DEFAULT_INDICATORS = [
    "ema50", "ema100", "ema200", "alma", "macd", "psar", "rsi", "atr", "volume"
]


@contextmanager
def _indicator_calculation(name):
    """Wrap a provider-library failure with the name of the failed indicator."""
    try:
        yield
    except Exception as exc:
        raise IndicatorCalculationError(f"failed to calculate {name}") from exc


def add_indicators(df, indicator_names):
    """Return a copy of OHLCV data with the selected indicator columns added.

    Args:
        df: DataFrame containing the price/volume columns required by each
            selected indicator. The input is not modified.
        indicator_names: Iterable of lowercase selectors, for example
            ``["ema100", "macd", "atr"]``. Supported selectors include
            ``alma``, ``macd``, ``awesome``/``ao``, ``psar``, ``mma``/
            ``moving_average_triple``, ``ema50``/``ema100``/``ema200``,
            ``sma50``/``ma50``, ``sma100``/``ma100``, ``sma200``/``ma200``,
            ``bb``/``bollinger``, ``stochrsi``, ``tema``/``triple_ema``,
            ``volume``, ``rsi``, ``atr``, ``cci``, ``williams``/``willr``,
            ``adx``, ``obv``, ``momentum``, ``roc``, ``kc``/``keltner``,
            ``ichimoku``/``ichi``, ``adosc``, and ``vpt``.

    Returns:
        A new DataFrame containing the original columns plus the calculated
        columns. Warm-up periods naturally produce NaN values.

    Raises:
        IndicatorCalculationError: If a selected library-backed indicator
            calculation fails. The original exception is retained as its cause.
        KeyError: May propagate when a requested calculation accesses a missing
            DataFrame column without wrapping that access in the indicator
            calculation context.
    """
    df2 = df.copy()
    if "alma" in indicator_names:
        with _indicator_calculation("ALMA"):
            df2["ALMA"] = ta.alma(df2["Close"], length=21)
    if "macd" in indicator_names:
        with _indicator_calculation("MACD"):
            macd = ta.macd(df2["Close"], fast=12, slow=26, signal=9)
            df2 = pd.concat([df2, macd], axis=1)
    if "awesome" in indicator_names or "ao" in indicator_names:
        with _indicator_calculation("Awesome Oscillator"):
            df2["AO"] = ta.ao(df2["High"], df2["Low"], fast=5, slow=34)
    if "psar" in indicator_names:
        with _indicator_calculation("Parabolic SAR"):
            psar = ta.psar(df2["High"], df2["Low"], df2["Close"], step=0.02, max_step=0.2)
            df2 = pd.concat([df2, psar], axis=1)
    if "mma" in indicator_names or "moving_average_triple" in indicator_names:
        with _indicator_calculation("triple moving averages"):
            df2["EMA50"] = ta.ema(df2["Close"], length=50)
            df2["EMA100"] = ta.ema(df2["Close"], length=100)
            df2["EMA200"] = ta.ema(df2["Close"], length=200)
    # Individual EMA/SMA 50 options
    if "ema50" in indicator_names:
        with _indicator_calculation("EMA50"):
            df2["EMA50"] = ta.ema(df2["Close"], length=50)
    if "sma50" in indicator_names or "ma50" in indicator_names:
        with _indicator_calculation("SMA50"):
            df2["SMA50"] = df2["Close"].rolling(50).mean()
    # Individual EMA/SMA options for explicit requests
    if "ema100" in indicator_names:
        with _indicator_calculation("EMA100"):
            df2["EMA100"] = ta.ema(df2["Close"], length=100)
    if "ema200" in indicator_names:
        with _indicator_calculation("EMA200"):
            df2["EMA200"] = ta.ema(df2["Close"], length=200)
    if "sma100" in indicator_names or "ma100" in indicator_names:
        with _indicator_calculation("SMA100"):
            df2["SMA100"] = df2["Close"].rolling(100).mean()
    if "sma200" in indicator_names or "ma200" in indicator_names:
        with _indicator_calculation("SMA200"):
            df2["SMA200"] = df2["Close"].rolling(200).mean()
    if "bb" in indicator_names or "bollinger" in indicator_names:
        with _indicator_calculation("Bollinger Bands"):
            bb = ta.bbands(df2["Close"], length=20, std=2)
            df2 = pd.concat([df2, bb], axis=1)
    if "stochrsi" in indicator_names:
        with _indicator_calculation("Stochastic RSI"):
            stcrsi = ta.stochrsi(df2["Close"], length=14)
            df2 = pd.concat([df2, stcrsi], axis=1)
    if "tema" in indicator_names or "triple_ema" in indicator_names:
        with _indicator_calculation("TEMA"):
            df2["TEMA"] = ta.tema(df2["Close"], length=21)
    if "volume" in indicator_names:
        with _indicator_calculation("average volume"):
            df2["VolumeAvg20"] = df2["Volume"].rolling(20).mean()
    if "rsi" in indicator_names:
        with _indicator_calculation("RSI"):
            df2["RSI_14"] = ta.rsi(df2["Close"], length=14)
    if "atr" in indicator_names:
        with _indicator_calculation("ATR"):
            atr = ta.atr(df2["High"], df2["Low"], df2["Close"], length=14)
            df2 = pd.concat([df2, atr], axis=1)
    if "cci" in indicator_names:
        with _indicator_calculation("CCI"):
            df2["CCI_20"] = ta.cci(df2["High"], df2["Low"], df2["Close"], length=20)
    if "williams" in indicator_names or "willr" in indicator_names:
        with _indicator_calculation("Williams %R"):
            df2["WILLR_14"] = ta.willr(df2["High"], df2["Low"], df2["Close"], length=14)
    if "adx" in indicator_names:
        with _indicator_calculation("ADX"):
            adx = ta.adx(df2["High"], df2["Low"], df2["Close"], length=14)
            df2 = pd.concat([df2, adx], axis=1)
    if "obv" in indicator_names:
        with _indicator_calculation("OBV"):
            df2["OBV"] = ta.obv(df2["Close"], df2["Volume"])
    if "momentum" in indicator_names:
        with _indicator_calculation("momentum"):
            df2["MOM_10"] = ta.mom(df2["Close"], length=10)
    if "roc" in indicator_names:
        with _indicator_calculation("rate of change"):
            df2["ROC_12"] = ta.roc(df2["Close"], length=12)
    if "kc" in indicator_names or "keltner" in indicator_names:
        with _indicator_calculation("Keltner Channels"):
            kc = ta.kc(df2["High"], df2["Low"], df2["Close"], length=20)
            df2 = pd.concat([df2, kc], axis=1)
    if "ichimoku" in indicator_names or "ichi" in indicator_names:
        with _indicator_calculation("Ichimoku"):
            ichi = ta.ichimoku(df2["High"], df2["Low"], df2["Close"], tenkan=9, kijun=26, senkou=52, senkou_lead=26, chikou=26)
            df2 = pd.concat([df2, ichi[0]], axis=1)
    if "adosc" in indicator_names:
        with _indicator_calculation("Accumulation/Distribution Oscillator"):
            df2["ADOSC"] = ta.adosc(df2["High"], df2["Low"], df2["Close"], df2["Volume"], fast=3, slow=10)
    if "vpt" in indicator_names:
        df2["VPT"] = (df2["Close"].pct_change(fill_method=None) * df2["Volume"]).cumsum()
    return df2

def compute_projected_1_3_target(latest):
    """Return projected stop, target, and ratio using the legacy fixed 1:3 rule.

    The stop is one ATR below ``Close`` and the target is three ATR above it.
    This remains a compatibility wrapper around :func:`compute_projected_target`.

    Args:
        latest: Mapping-like latest market row containing ``Close`` and
            ``ATRr_14``.

    Returns:
        A mapping with ``stop``, ``target``, and ``ratio``. Invalid or
        non-positive inputs produce NaN values, as in the parameterized
        function.
    """
    # Backwards compatible wrapper for a 1:3 risk:reward
    return compute_projected_target(latest, rr_ratio=3.0)


def compute_projected_target(latest, rr_ratio=3.0):
    """Calculate ATR-based projected stop and target levels.

    Stop is ``Close - ATRr_14`` and target is ``Close + rr_ratio * ATRr_14``.
    This is a simple reference calculation, not an order or position-sizing
    instruction.

    Args:
        latest: Mapping-like market row with ``Close`` and ``ATRr_14`` values.
        rr_ratio: Positive reward-to-risk multiple; defaults to 3.0.

    Returns:
        A mapping containing ``stop``, ``target``, and ``ratio``. Returns NaN
        for all three fields if price/ATR/ratio is missing or ATR/ratio is
        non-positive. Supplied values are expected to be numeric.
    """
    close = latest.get("Close", float("nan"))
    atr = latest.get("ATRr_14", float("nan"))
    try:
        rr = float(rr_ratio)
    except Exception:
        rr = float("nan")
    if pd.isna(close) or pd.isna(atr) or atr <= 0 or pd.isna(rr) or rr <= 0:
        return {"stop": float("nan"), "target": float("nan"), "ratio": float("nan")}
    stop = close - atr
    target = close + rr * atr
    return {"stop": stop, "target": target, "ratio": float(rr)}


def evaluate_signals(latest, chosen, prev=None):
    """Evaluate the screener's threshold-based signals for one market row.

    A ``*_bull`` or ``*_bear`` value is ``False`` when its source indicator is
    missing. The rules are intentionally fixed screening heuristics, not
    parameterized trading-strategy rules. Examples include RSI above 50, ADX
    above 25, volume above its 20-bar average, and close above selected moving
    averages. EMA100/EMA200 and SMA100/SMA200 relationship flags are included
    whenever both values are present.

    Args:
        latest: Mapping-like latest row, containing ``Close`` and any columns
            required for the selected signals.
        chosen: Indicator selectors used when calculating ``latest``. Only
            corresponding indicator signals are emitted, in addition to
            available moving-average relationship/crossover signals.
        prev: Optional immediately preceding row. When present and both rows
            contain the relevant values, emits EMA100/EMA200 and
            SMA100/SMA200 cross-up/cross-down flags.

    Returns:
        A dictionary mapping signal names to booleans. Missing indicator
        values do not produce a bullish/bearish signal; relationship and
        crossover signals are omitted when their inputs are unavailable.
    """
    signals = {}
    close = latest["Close"]

    if "alma" in chosen:
        alma = latest.get("ALMA", float("nan"))
        signals["alma_bull"] = bool(close > alma) if not pd.isna(alma) else False
    if "macd" in chosen:
        macdh = latest.get("MACDh_12_26_9", float("nan"))
        signals["macd_bull"] = bool(macdh > 0) if not pd.isna(macdh) else False
    if "awesome" in chosen or "ao" in chosen:
        ao = latest.get("AO", float("nan"))
        signals["ao_bull"] = bool(ao > 0) if not pd.isna(ao) else False
    if "psar" in chosen:
        psarl = latest.get("PSARl_0.02_0.2", float("nan"))
        signals["psar_bull"] = bool(psarl < close) if not pd.isna(psarl) else False
    if "moving_average_triple" in chosen or "mma" in chosen:
        ema50 = latest.get("EMA50", float("nan"))
        ema100 = latest.get("EMA100", float("nan"))
        ema200 = latest.get("EMA200", float("nan"))
        signals["mma_bull"] = bool(ema50 > ema100 > ema200) if all(not pd.isna(x) for x in [ema50, ema100, ema200]) else False
    if "bollinger" in chosen or "bb" in chosen:
        bbm = latest.get("BBM_20_2.0", float("nan"))
        signals["bb_bull"] = bool(close > bbm) if not pd.isna(bbm) else False
    if "stochrsi" in chosen:
        stochk = latest.get("STOCHRSIk_14_14_3_3", float("nan"))
        signals["stochrsi_bull"] = bool(stochk > 0.2) if not pd.isna(stochk) else False
    if "triple_ema" in chosen or "tema" in chosen:
        tema = latest.get("TEMA_21", float("nan"))
        signals["tema_bull"] = bool(close > tema) if not pd.isna(tema) else False
    if "ema100" in chosen:
        ema100 = latest.get("EMA100", float("nan"))
        signals["ema100_bull"] = bool(close > ema100) if not pd.isna(ema100) else False
        signals["ema100_bear"] = bool(close < ema100) if not pd.isna(ema100) else False
    if "ema50" in chosen:
        ema50 = latest.get("EMA50", float("nan"))
        signals["ema50_bull"] = bool(close > ema50) if not pd.isna(ema50) else False
        signals["ema50_bear"] = bool(close < ema50) if not pd.isna(ema50) else False
    if "ema200" in chosen:
        ema200 = latest.get("EMA200", float("nan"))
        signals["ema200_bull"] = bool(close > ema200) if not pd.isna(ema200) else False
        signals["ema200_bear"] = bool(close < ema200) if not pd.isna(ema200) else False
    if "sma100" in chosen or "ma100" in chosen:
        sma100 = latest.get("SMA100", float("nan"))
        signals["sma100_bull"] = bool(close > sma100) if not pd.isna(sma100) else False
        signals["sma100_bear"] = bool(close < sma100) if not pd.isna(sma100) else False
    if "sma200" in chosen or "ma200" in chosen:
        sma200 = latest.get("SMA200", float("nan"))
        signals["sma200_bull"] = bool(close > sma200) if not pd.isna(sma200) else False
        signals["sma200_bear"] = bool(close < sma200) if not pd.isna(sma200) else False
    if "sma50" in chosen or "ma50" in chosen:
        sma50 = latest.get("SMA50", float("nan"))
        signals["sma50_bull"] = bool(close > sma50) if not pd.isna(sma50) else False
        signals["sma50_bear"] = bool(close < sma50) if not pd.isna(sma50) else False
    if "volume" in chosen:
        volavg = latest.get("VolumeAvg20", float("nan"))
        vol = latest.get("Volume", float("nan"))
        signals["vol_bull"] = bool(vol > volavg) if all(not pd.isna(x) for x in [vol, volavg]) else False
    if "rsi" in chosen:
        rsi = latest.get("RSI_14", float("nan"))
        signals["rsi_bull"] = bool(rsi > 50) if not pd.isna(rsi) else False
    if "atr" in chosen:
        atr = latest.get("ATRr_14", float("nan"))
        signals["atr_bull"] = bool(atr > 0) if not pd.isna(atr) else False
    if "cci" in chosen:
        cci = latest.get("CCI_20", float("nan"))
        signals["cci_bull"] = bool(cci > 0) if not pd.isna(cci) else False
    if "williams" in chosen or "willr" in chosen:
        willr = latest.get("WILLR_14", float("nan"))
        signals["willr_bull"] = bool(willr < -50) if not pd.isna(willr) else False
    if "adx" in chosen:
        adx = latest.get("ADX_14", float("nan"))
        signals["adx_bull"] = bool(adx > 25) if not pd.isna(adx) else False
    if "obv" in chosen:
        obv = latest.get("OBV", float("nan"))
        signals["obv_bull"] = bool(obv > 0) if not pd.isna(obv) else False
    if "momentum" in chosen:
        mom = latest.get("MOM_10", float("nan"))
        signals["mom_bull"] = bool(mom > 0) if not pd.isna(mom) else False
    if "roc" in chosen:
        roc = latest.get("ROC_12", float("nan"))
        signals["roc_bull"] = bool(roc > 0) if not pd.isna(roc) else False
    if "kc" in chosen or "keltner" in chosen:
        kcle = latest.get("KCLe_20_2", float("nan"))
        signals["kc_bull"] = bool(close > kcle) if not pd.isna(kcle) else False
    if "ichimoku" in chosen or "ichi" in chosen:
        isa = latest.get("ISA_9", float("nan"))
        signals["ichi_bull"] = bool(close > isa) if not pd.isna(isa) else False
    if "adosc" in chosen:
        adosc = latest.get("ADOSC", float("nan"))
        signals["adosc_bull"] = bool(adosc > 0) if not pd.isna(adosc) else False
    if "vpt" in chosen:
        vpt = latest.get("VPT", float("nan"))
        signals["vpt_bull"] = bool(vpt > 0) if not pd.isna(vpt) else False

    # Relationship signals
    try:
        ema100 = latest.get("EMA100", float("nan"))
        ema200 = latest.get("EMA200", float("nan"))
        if not pd.isna(ema100) and not pd.isna(ema200):
            signals["ema100_above_ema200"] = bool(ema100 > ema200)
            signals["ema100_below_ema200"] = bool(ema100 < ema200)
    except Exception:
        pass
    try:
        sma100 = latest.get("SMA100", float("nan"))
        sma200 = latest.get("SMA200", float("nan"))
        if not pd.isna(sma100) and not pd.isna(sma200):
            signals["sma100_above_sma200"] = bool(sma100 > sma200)
            signals["sma100_below_sma200"] = bool(sma100 < sma200)
    except Exception:
        pass

    # Crossover signals if previous row available
    if prev is not None:
        try:
            e100_prev = prev.get("EMA100", float("nan"))
            e200_prev = prev.get("EMA200", float("nan"))
            e100 = latest.get("EMA100", float("nan"))
            e200 = latest.get("EMA200", float("nan"))
            if all(not pd.isna(x) for x in [e100_prev, e200_prev, e100, e200]):
                signals["ema100_cross_up_ema200"] = bool(e100_prev <= e200_prev and e100 > e200)
                signals["ema100_cross_down_ema200"] = bool(e100_prev >= e200_prev and e100 < e200)
        except Exception:
            pass
        try:
            s100_prev = prev.get("SMA100", float("nan"))
            s200_prev = prev.get("SMA200", float("nan"))
            s100 = latest.get("SMA100", float("nan"))
            s200 = latest.get("SMA200", float("nan"))
            if all(not pd.isna(x) for x in [s100_prev, s200_prev, s100, s200]):
                signals["sma100_cross_up_sma200"] = bool(s100_prev <= s200_prev and s100 > s200)
                signals["sma100_cross_down_sma200"] = bool(s100_prev >= s200_prev and s100 < s200)
        except Exception:
            pass

    return signals
